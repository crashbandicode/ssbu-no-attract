"""Measure stock expiry and candidate idle windows through the shared Eden runner."""

import hashlib
import json
from pathlib import Path
import re
import socket
import time
import zlib

import routes


BUILD_ID = '21450c647b8c5940ed5b68218ea128fd3c5d597d'
GUARDS = {'title': ('0x1bfb108', 'x9', 'x8', '0x1bfb110'),
          'main': ('0x185e53c', 'x8', 'x9', '0x185e540')}
SCREENS = {'title': 'title', 'main': 'main_menu'}
WIRE = re.compile(rb'^(.*) frame=(\d+) wall=(\d+)$')
DEMO_MODE = 0x01010000
INSTALL = 'plugin=ssbu-no-attract/0.1.0 result=installed site=title,main heap_allocations=0'


def run_dir(ctx):
    return Path(ctx.instance['control_log']).parent


def read_json(path):
    return json.loads(path.read_text())


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')
    return value


def fixture(ctx):
    return read_json(run_dir(ctx).parents[1] / 'menu-timers-input.json')


def screen_shot(ctx, name):
    path = ctx.row_dir / f'{name}.png'
    return ctx.call('ui.screenshot', {'target': 'screen', 'path': str(path)})


def point(ctx, offset, **opts):
    reply = ctx.call('trace.arm', {'target': 'main+' + offset, **opts})
    return str(reply.get('id', reply.get('point_id')))


def boot(ctx):
    routes.configure_boot(ctx)
    for key, value in (('core.use_gdbstub', False), ('core.lan_online', False)):
        ctx.call('settings.set', {'key': key, 'value': value})
    ctx.call('settings.save', {})
    settings = {key: ctx.call('settings.get', {'key': key}) for key in (
        'core.volume', 'core.use_gdbstub', 'core.memory_layout_mode', 'core.lan_online')}
    if tuple(str(r.get('value')).lower() for r in settings.values()) != ('0', 'false', '0', 'false'):
        raise RuntimeError(f'Unexpected persisted preload settings: {settings}')
    save(ctx.row_dir / 'settings.json', settings)
    ctx.call('trace.configure', {'run_directory': str(run_dir(ctx)), 'label': 'menu-timers'})
    ctx.call('trace.unmapped_access', {'mode': 'log'})
    ids = {}
    for menu, (branch, count, limit, expiry) in GUARDS.items():
        opts = {'registers': [count, limit], 'max_hits': 1}
        ids[f'{menu}.first'] = point(ctx, branch, **opts)
        ids[f'{menu}.over'] = point(ctx, branch, condition=f'{count} > {limit}', **opts)
        ids[f'{menu}.expiry'] = point(ctx, expiry, **opts)
    for key, offset in (('title_request', '0x235c054'), ('main_request', '0x235ccb8'),
                        ('how_to_play', '0x235c738'), ('demo', '0x235c870')):
        ids[key] = point(ctx, offset, max_hits=6)
    if 'None' in ids.values() or len(set(ids.values())) != len(ids):
        raise RuntimeError(f'Trace arm did not return unique IDs: {ids}')
    save(run_dir(ctx) / 'menu-timers-points.json', ids)
    candidate = bool(fixture(ctx).get('stock'))
    if candidate:
        # Validate this Eden executable's exact CSS capture grammar before
        # loading the guest, then leave fresh probes for the live CSS row.
        css_ids = arm_css_points(ctx)
        for probe in css_ids.values():
            ctx.call('trace.disarm', {'id': probe})
        save(ctx.row_dir / 'css-trace-preflight.json', {'disarmed': css_ids})
    routes.load_game(ctx, cap=330, min_fps=10)
    modules = ctx.call('modules.list')
    if BUILD_ID not in json.dumps(modules).lower():
        raise RuntimeError('Loaded main did not match stock 13.0.5')
    if candidate:
        install_path = Path(ctx.instance['profile']) / 'user/sdmc/ultimate/ssbu-no-attract/events.log'
        until = time.monotonic() + 10
        while not install_path.exists() and time.monotonic() < until:
            ctx.check_stop()
            time.sleep(0.1)
        if not install_path.exists() or install_path.read_text().splitlines() != [INSTALL]:
            raise RuntimeError('Expected a single successful install record for the exact release')
        (ctx.row_dir / 'plugin-install.log').write_text(install_path.read_text())
    return save(ctx.row_dir / 'module-and-trace-identity.json', {'modules': modules, 'ids': ids})


def read_trace(ctx):
    path = run_dir(ctx) / 'menu-timers.trace.jsonl'
    if not path.exists():
        return []
    records = []
    with path.open('rb') as stream:
        for row in stream:
            if not row.endswith(b'\n'):
                break
            event = json.loads(row)
            if event.get('event') == 'loss':
                raise RuntimeError(f'Guest trace reported loss: {event}')
            records.append(event)
    return records


def trace(ctx, records):
    ids = read_json(run_dir(ctx) / 'menu-timers-points.json')
    names = {value: name for name, value in ids.items()}
    grouped = {}
    for event in records:
        name = names.get(str(event.get('point_id')))
        if name:
            grouped.setdefault(name, []).append(event)
    return grouped


def fields(text):
    return dict(word.split(b'=', 1) for word in text.split() if b'=' in word)


def bridge_sample(ctx, provider='ssbu.ui'):
    """Read one complete CRC-checked snapshot from the run's pinned loopback port."""
    if not hasattr(ctx.runner, 'menu_timers_bridge'):
        port_path = Path(ctx.instance['profile']) / 'user/sdmc/ultimate/ssbu-hw-bridge/port.txt'
        port = int(port_path.read_text())
        if port != fixture(ctx)['port']:
            raise RuntimeError('Bridge port did not match the owned fixture')
        sock = socket.create_connection(('127.0.0.1', port), timeout=2)
        ctx.runner.menu_timers_bridge = sock, sock.makefile('rb')
    sock, wire = ctx.runner.menu_timers_bridge
    try:
        name = provider.encode()
        sock.sendall(b'scene\nstate ' + name + b'\n')
        header = None
        payload = []
        scene = None
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            raw = wire.readline(8192)
            if not raw:
                raise ConnectionError('Bridge closed the observation stream')
            parsed = WIRE.fullmatch(raw.rstrip(b'\r\n'))
            if not parsed:
                continue
            line, frame, wall = parsed.groups()
            if line.startswith(b'[Bridge] scene mode='):
                words = fields(line)
                scene = {'mode': words[b'mode'].decode(), 'melee': words[b'melee'].decode(),
                         'class': words[b'class'].decode(), 'init': words[b'init'].decode(),
                         'frame': int(frame), 'wall_ms': int(wall)}
            if line.startswith(b'[Bridge] state name=' + name + b' result='):
                return None
            if line.startswith(b'[Bridge] state begin name=' + name + b' '):
                header = fields(line)
                payload.clear()
            elif header and line.startswith(b'[Bridge] state.'):
                label, value = line[len(b'[Bridge] '):].split(b' ', 1)
                if label != f'state.{len(payload)}'.encode():
                    raise RuntimeError('Unexpected ssbu.ui field numbering')
                payload.append(value)
            elif header and line.startswith(b'[Bridge] state end name=' + name + b' '):
                end = fields(line)
                crc = zlib.crc32(b'\n'.join(payload))
                if (header[b'schema'] != name + b'/1' or header[b'filtered'] != b'0'
                        or header[b'rev'] != end[b'rev'] or len(payload) != int(header[b'lines'])
                        or crc != int(end[b'crc'], 16)):
                    raise RuntimeError('Torn or incompatible ssbu.ui reply')
                values = dict(part.decode().split('=', 1) for part in payload)
                if values['boot'].encode() != header[b'boot'] or values['rev'].encode() != header[b'rev']:
                    raise RuntimeError('ssbu.ui identity disagreed with the frame')
                if scene is None or not 0 <= int(frame) - scene['frame'] <= 4:
                    return None
                return {'frame': int(frame), 'wall_ms': int(wall), 'received_ns': time.time_ns(),
                        'values': values, 'scene': scene}
        raise TimeoutError('Bridge did not return a complete snapshot')
    except (ConnectionError, TimeoutError):
        wire.close()
        sock.close()
        del ctx.runner.menu_timers_bridge
        raise
def samples(ctx, cap, interval=0.25):
    deadline = time.monotonic() + cap
    candidate = bool(fixture(ctx).get('stock'))
    if candidate and not hasattr(ctx.runner, 'menu_timers_boot'):
        previous = run_dir(ctx).parents[1] / 'out/main-idle-2x/candidate-main-idle.json'
        if previous.is_file():
            ctx.runner.menu_timers_boot = read_json(previous)['bridge_samples'][0]['values']['boot']
    while time.monotonic() < deadline:
        ctx.check_stop()
        try:
            sample = bridge_sample(ctx)
        except (ConnectionError, TimeoutError):
            sample = None
        if sample and sample['values'].get('observation.active') == 'yes':
            boot_id = sample['values']['boot']
            previous = getattr(ctx.runner, 'menu_timers_boot', boot_id)
            if previous != boot_id:
                raise RuntimeError('Bridge boot changed during the tour')
            ctx.runner.menu_timers_boot = boot_id
            if candidate:
                if sample['values'].get('screen') == 'attract' or int(sample['scene']['mode'], 16) == DEMO_MODE:
                    save(ctx.row_dir / 'unexpected-candidate-attract.json', sample)
                    raise RuntimeError('Attract screen or demo mode appeared in the candidate boot')
            yield sample
        time.sleep(interval)


def intro_to_title(ctx, cap=110):
    """A single pinned Plus on the proved, undecided startup selector."""
    ready = None
    layout_captures = [
        ('x19+0x88', 'bytes', 96),
        ('[x19+0x100]', 'u64', None),
        ('[x19+0x100]+0x15', 'bytes', 4),
        ('[x19+0x100]+0x250', 'bytes', 16),
        ('[[pc+0x3734b38]+0x8]+0xf4', 'bytes', 79),
        ('[[[[pc+0x3734b38]+0x8]+0x110]+0x80]+0xc0', 'u32', None),
    ]
    captures = [{'expression': expr, 'type': kind, **({'size': size} if size else {})}
                for expr, kind, size in layout_captures]
    for sample in samples(ctx, cap):
        v = sample['values']
        if (v.get('screen') != 'title' or v.get('screen.context') != 'unknown'
                or int(sample['scene']['mode'], 16) != 0x01000000):
            continue
        if ready is None:
            ready = point(ctx, '0x1bface8', registers=['pc', 'x8', 'x19'], captures=captures,
                          max_hits=32, condition='x8 == 0xffffffff')
            continue
        for event in reversed(read_trace(ctx)):
            if str(event.get('point_id')) != ready or time.time_ns() - int(event['wall_time_ns']) >= 750_000_000:
                continue
            data = {item['expression']: bytes.fromhex(item['hex'])
                    for item in event['captures'] if not item['error']}

            def value(expr, offset=0, size=4):
                field = data.get(expr, b'')[offset:offset + size]
                return int.from_bytes(field, 'little') if len(field) == size else None

            layout = layout_captures[0][0]
            popup = layout_captures[4][0]
            base = int(event['registers']['pc'], 16) - 0x1bface8
            if (value(layout) == value(layout, 0x50) == 1
                    and value(layout, 0x4c) == value(layout, 0x5c, 1) == 0
                    and value(layout_captures[1][0], size=8) == base + 0x523d7f8
                    and data.get(layout_captures[2][0]) == b'\x01\x01\x00\x00'
                    and value(layout_captures[3][0], 0xc) == 0xffffffff
                    and value(popup) == value(popup, 0x4e, 1) == value(layout_captures[5][0]) == 0):
                ctx.shot('startup-title-before-plus')
                save(ctx.row_dir / 'startup-selector.json', {'bridge': sample, 'guest': event})
                return {'macro': routes.play(ctx, 'attract-cancel')}
    raise RuntimeError('No matching bridge and native startup selector witness for Plus')


def ticks(menu, event):
    _, count, threshold, _ = GUARDS[menu]
    regs = event['registers']
    return int(regs[count], 16) & 0xffffffff, int(regs[threshold], 16) & 0xffffffff


def measure(menu, start, over, expiry):
    begin, threshold = ticks(menu, start)
    end, end_threshold = ticks(menu, over)
    dt_ns = int(over['wall_time_ns']) - int(start['wall_time_ns'])
    frames = int(over['frame']) - int(start['frame'])
    if (begin > 8 or not threshold or end_threshold != threshold or end != threshold + 1
            or start['process_id'] != over['process_id'] or over['thread_id'] != expiry['thread_id']
            or dt_ns <= 0 or frames <= 0 or int(expiry['sequence']) <= int(over['sequence'])):
        raise RuntimeError(f'{menu} did not show a fresh counter followed by its first strict expiry')
    return {'idle_start': begin, 'idle_expiry': end, 'threshold_ticks': threshold,
            'elapsed_s': dt_ns / 1e9, 'vsync_delta': frames, 'first': start, 'over': over, 'expiry': expiry}


def stock_idle(ctx, menu, cap=600):
    transitions = []
    for sample in samples(ctx, cap, interval=0.5):
        values = sample['values']
        screen = (values.get('screen'), values.get('screen.context'))
        if not transitions or screen != transitions[-1][0]:
            transitions.append((screen, sample))
            save(ctx.row_dir / 'bridge-transitions.json', transitions)
        events = trace(ctx, read_trace(ctx))
        required = [events.get(f'{menu}.{suffix}') for suffix in ('first', 'over', 'expiry')]
        if not all(required):
            continue
        result = measure(menu, *(records[0] for records in required))
        follow = [(name, event) for name in ('title_request', 'how_to_play', 'demo')
                  for event in events.get(name, [])
                  if int(event['sequence']) > int(result['expiry']['sequence'])]
        confirmed = ((values.get('screen') == 'attract' or int(sample['scene']['mode'], 16) == DEMO_MODE)
                     and any(name in ('how_to_play', 'demo') for name, _ in follow))
        if confirmed:
            attract = min((event for name, event in follow if name in ('how_to_play', 'demo')),
                          key=lambda event: int(event['sequence']))
            result['next_stock_requests'] = follow
            result['bridge_attract'] = sample
            result['attract_elapsed_s'] = (int(attract['wall_time_ns']) - int(result['first']['wall_time_ns'])) / 1e9
            result['attract_vsync_delta'] = int(attract['frame']) - int(result['first']['frame'])
            ctx.shot(f'{menu}-stock-attract')
            save(ctx.row_dir / f'stock-{menu}-idle.json', result)
            return {key: result[key] for key in ('elapsed_s', 'threshold_ticks', 'vsync_delta',
                                                   'attract_elapsed_s', 'attract_vsync_delta')}
    raise RuntimeError(f'No complete fresh {menu} idle expiry/scene request within {cap}s')


def to_main(ctx, cap=90):
    """Advance from exact How To Play or a fresh guest witness of the real Title prompt."""
    armed = None
    sent = set()
    after_ns = 0
    for sample in samples(ctx, cap):
        v = sample['values']
        if (v.get('screen') == 'main_menu' and v.get('screen.layer') == 'top'
                and v.get('input.owner') == 'native' and v.get('dialog') == 'none'):
            return save(ctx.row_dir / 'qualified-main.json', sample)
        action = None
        if v.get('screen') == 'attract' and v.get('screen.context') == 'how_to_play':
            action = 'how-to-play'
        elif v.get('screen') == 'title' and 'title' not in sent:
            if armed is None:
                armed = point(ctx, GUARDS['title'][0], registers=['x8', 'x9'], max_hits=1)
            witnesses = [item for item in read_trace(ctx) if str(item.get('point_id')) == armed]
            if witnesses:
                witness = witnesses[-1]
                now = time.time_ns()
                if int(witness['wall_time_ns']) >= max(after_ns, now - 2_000_000_000):
                    save(ctx.row_dir / 'title-main-entry-witness.json', witness)
                    action = 'title'
                else:
                    armed = None
        if action is not None and action not in sent:
            save(ctx.row_dir / f'plus-source-{action}.json', sample)
            routes.play(ctx, 'attract-cancel')
            sent.add(action)
            after_ns = time.time_ns()
    raise RuntimeError(f'No qualified Main after fenced actions {sorted(sent)}')


def hold_candidate(ctx, menu, multiplier=2, cap=650):
    bounds = fixture(ctx)['stock'][menu]
    if not hasattr(ctx.runner, 'menu_timer_samples'):
        ctx.runner.menu_timer_samples = {}
    seen = ctx.runner.menu_timer_samples.setdefault(menu, [])
    checkpoint = None
    for sample in samples(ctx, cap, interval=0.5):
        events = trace(ctx, read_trace(ctx))
        if any(events.get(name) for name in (f'{menu}.expiry', 'how_to_play', 'demo')):
            raise RuntimeError(f'Unexpected expiry or attract request during candidate {menu}')
        if sample['values'].get('screen') != SCREENS[menu]:
            if not seen:
                continue
            raise RuntimeError(f'{menu} left while idle: {sample}')
        if not seen:
            first = events.get(f'{menu}.first')
            if not first or not 0 <= sample['received_ns'] - int(first[0]['wall_time_ns']) <= 8_000_000_000:
                continue
            count, limit = ticks(menu, first[0])
            if count > 8 or limit != bounds['threshold_ticks']:
                raise RuntimeError(f'Unexpected candidate {menu} entry guard: {count}/{limit}')
            save(ctx.row_dir / 'candidate-entry-guard.json', first[0])
            ctx.shot(f'{menu}-idle-start')
        if seen and (sample['frame'] < seen[-1]['frame'] or
                     int(sample['values']['observation']) < int(seen[-1]['values']['observation'])):
            raise RuntimeError(f'{menu} observation moved backwards')
        if seen:
            if sample['received_ns'] - seen[-1]['received_ns'] > 5_000_000_000:
                raise RuntimeError(f'{menu} bridge observations lost continuity')
            for key in ('mode', 'melee'):
                if sample['scene'][key] != seen[0]['scene'][key]:
                    raise RuntimeError(f'{menu} changed raw {key} while idle')
        if menu == 'main' and any(sample['values'].get(key) != expected for key, expected in (
                ('screen.layer', 'top'), ('input.owner', 'native'), ('dialog', 'none'))):
            raise RuntimeError(f'Main left its native top-level idle state: {sample}')
        seen.append(sample)
        elapsed = (sample['wall_ms'] - seen[0]['wall_ms']) / 1000
        frames = sample['frame'] - seen[0]['frame']
        over = events.get(f'{menu}.over')
        if elapsed < multiplier * bounds['elapsed_s'] or frames < multiplier * bounds['vsync_delta'] or not over:
            continue
        count, threshold = ticks(menu, over[0])
        if count != threshold + 1 or threshold != bounds['threshold_ticks']:
            raise RuntimeError(f'Unexpected {menu} over-threshold witness: {count}/{threshold}')
        if checkpoint is None:
            branch, count_reg, limit_reg, _ = GUARDS[menu]
            checkpoint = point(ctx, branch, registers=[count_reg, limit_reg], max_hits=1)
            continue
        witness = next((event for event in read_trace(ctx) if str(event.get('point_id')) == checkpoint), None)
        if witness is None:
            continue
        first = events[f'{menu}.first'][0]
        native_elapsed = (int(witness['wall_time_ns']) - int(first['wall_time_ns'])) / 1e9
        native_frames = int(witness['frame']) - int(first['frame'])
        if native_elapsed < multiplier * bounds['elapsed_s'] or native_frames < multiplier * bounds['vsync_delta']:
            checkpoint = None
            continue
        screenshot = screen_shot(ctx, f'{menu}-idle-{multiplier}x')
        return save(ctx.row_dir / f'candidate-{menu}-idle.json', {
            'elapsed_s': native_elapsed, 'vsync_delta': native_frames,
            'bridge_elapsed_s': elapsed, 'bridge_frames': frames, 'threshold': threshold, 'count': count,
            'first': first, 'guard': over[0], 'checkpoint': witness, 'bridge_samples': seen,
            'screenshot': screenshot})
    raise RuntimeError(f'Candidate {menu} did not complete {multiplier} stock intervals within {cap}s')


NATIVE = {'input.owner': 'native', 'dialog': 'none', 'menu.admission': 'qualified_offline'}
TOP = {'screen': 'main_menu', 'screen.layer': 'top', 'focus.source': 'native'}
GAMES_SUBMENU = {'screen': 'main_menu', 'screen.layer': 'submenu', 'screen.tab': 'games_and_more',
                 'focus.source': 'native'}
GAMES = {**GAMES_SUBMENU, 'focus.id': 'training'}
SSS = {'screen': 'stage_select', 'screen.context': 'training', 'focus.source': 'tile.cursor'}
CSS = {'screen': 'css.training', 'screen.context': 'training', 'focus.source': 'tile.cursor'}
TRAINING = {'screen': 'training', 'screen.context': 'training'}
PAUSE = {'screen': 'pause', 'screen.context': 'training', 'focus.source': 'native'}

MACRO_PINS = {
    'main-menu-right': 'cf45ed4d27a1061eb7e5e55811e539d40517d5a34a851e58925a5d74aea0f36e',
    'main-menu-up': '8f093143057bd5cf44d140a4a6307fefc063f6badcda50c1ee1ab180cd744a86',
    'main-menu-down': '5d233cbcb1f89b33e9b488d72b8c634a15de4dc1ec8dc615ddf4737b3b0b9dc0',
    'main-menu-left': '0c0ed5acbecf8b42e5225f2e2f48855922e69bf9b5da7c47559d8671edd428a1',
    'enter-training': '7cdd035473160fec1a0e8c601c05f599f5b21556ac1cb4479b358c629e05b5c1',
    'pause-open': '64dd73ecc545a194de80411cddb3b8cbd5e37be8e7a4e077a39a5dedee23fe24',
    'focus-native-quit-frames': '281999e46939ca06c960cef0108b28672c611435d33260ddeddfc6c9dd475b46',
    'confirm-native-quit-frames': '6fc21293dea72efe1bfb888735d8a62d8a6754d8a1855e8bbcde9af08e24080b',
    'leave-css': '17a2d214790855f5bdb26317c6c3c428b7a4f9dfe1d02de1e6cf59577102c4c7',
}


def qualified(ctx, expected, cap=10, after=None, also=None):
    last = None
    for sample in samples(ctx, cap):
        last = sample
        if after and int(sample['values']['observation']) <= int(after['values']['observation']):
            continue
        if sample['scene']['init'] != '1':
            continue
        if expected is TRAINING and (sample['scene']['mode'], sample['scene']['melee'],
                                     sample['scene']['class']) != ('0x04040000', '0x20', 'training'):
            continue
        matched = all(sample['values'].get(key) == value
                      for key, value in {**NATIVE, **expected}.items())
        if matched or also and all(sample['values'].get(key) == value
                                   for key, value in {**NATIVE, **also}.items()):
            return sample
    raise RuntimeError(f'No current qualified {expected}. Last bridge snapshot: {last}')


def play_menu(ctx, macro):
    if macro not in MACRO_PINS:
        return routes.play(ctx, macro)
    pin = MACRO_PINS[macro]
    recorded = Path(__file__).with_name('macros') / f'{macro}.edenmacro.json'
    if hashlib.sha256(recorded.read_bytes()).hexdigest() != pin:
        raise RuntimeError(f'Changed menu macro: {recorded}')
    ctx.call('macro.play', {'path': str(recorded)})
    ctx.runner.wait_macro(ctx.on, 20)
    ctx.log({'route_macro': macro, 'sha256': pin})
    return pin


def route_edge(ctx, name, before, macro, after, cap=10):
    source = qualified(ctx, before)
    pin = play_menu(ctx, macro)
    dest = qualified(ctx, after, cap, source)
    return save(ctx.row_dir / f'{name}.json', {'before': source, 'macro_sha256': pin, 'after': dest})


def training_picker(ctx):
    smash, vault, games = ({**TOP, 'screen.tab': tab, 'focus.id': tab}
                          for tab in ('smash', 'vault', 'games_and_more'))
    classic = {**GAMES, 'focus.id': 'classic_mode'}
    mob = {**GAMES, 'focus.id': 'mob_smash'}
    path = (
        ('vault', smash, 'main-menu-right', vault),
        ('games-and-more', vault, 'main-menu-up', games),
        ('classic', games, 'tap-a1', classic),
        ('mob-smash', classic, 'main-menu-down', mob),
        ('training-row', mob, 'main-menu-left', GAMES),
    )
    for name, source, macro, dest in path:
        current = qualified(ctx, source, also=GAMES)
        if current['values'].get('focus.id') == 'training':
            save(ctx.row_dir / 'current-training-row.json', current)
            break
        pin = play_menu(ctx, macro)
        reached = qualified(ctx, dest, after=current, also=GAMES)
        save(ctx.row_dir / f'{name}.json', {'before': current, 'macro_sha256': pin, 'after': reached})
        if reached['values'].get('focus.id') == 'training':
            break
    route_edge(ctx, 'training-stage-select', GAMES, 'tap-a1', SSS, 45)
    walker = routes.TileWalker(ctx, 'sss')
    try:
        save(ctx.row_dir / 'sss-verified-tile.json', walker.walk_to(routes.stage_entry('Final Destination')['tile']))
    finally:
        walker.cursor.close()
    return route_edge(ctx, 'training-fighter-select', SSS, 'tap-a1', CSS, 60)


STEVE = 0xc100700fdc91574e
INVALID_PREVIEW = 0xc1ffff0000000000
STEVE_RECT = '000022c40000fcc30000ecc2000010c2'


def captures(*specs):
    return [{'expression': expr, 'type': kind, **({'size': size[0]} if size else {})}
            for expr, kind, *size in specs]


def capture_bytes(event, expression):
    return next((bytes.fromhex(item['hex']) for item in event['captures']
                 if item['expression'] == expression and not item['error']), b'')


def css_player_state(owner, hover, preview, *, held_only=False):
    player = capture_bytes(owner, 'x8+0x28')
    input_route = capture_bytes(owner, 'x9+0x484')
    holding = capture_bytes(owner, '[x8+0x20]+0x167')
    if player[:4] != bytes(4) or player[14:] != b'\x01' or input_route != bytes(12):
        return None
    carried = player[8:12]
    if carried == b'\xff' * 4 and holding == b'\x00':
        # Slot zero is resolved from the live vector's first panel entry and checked
        # against the native panel index before taking its committed kind.
        panel_kind = int.from_bytes(capture_bytes(owner, '[[x19+0x250]+8]+0x200'), 'little')
        if (capture_bytes(owner, '[[x19+0x250]+8]+0x150') == bytes(4) and panel_kind == STEVE
                and capture_bytes(owner, '[x19+0xdf0]+0x1c') == bytes.fromhex('4e000000')
                and capture_bytes(owner, '[x19+0xdf0]+0xd0').hex() == STEVE_RECT
                and capture_bytes(owner, '[x19+0xdf0]+0x11b')[::4] == b'\x01\x00'):
            return 'placed'
    if carried != bytes(4) or holding != b'\x01':
        return None
    if held_only:
        return 'holding'
    if hover is None or preview is None:
        return None
    at = int(hover['registers']['x24'], 16) & 0xffffffff
    hovered = int(hover['registers']['x9'], 16) & 0xffffffff
    kind = int(preview['registers']['x0'], 16)
    stored = int.from_bytes(capture_bytes(preview, '[x21]+0x200'), 'little')
    preview_at = int(preview['registers']['x24'], 16) & 0xffffffff
    if (at, hovered, preview_at, kind, stored) == (0xffffffff,) * 3 + (INVALID_PREVIEW,) * 2:
        return 'off_grid'
    if ((at, hovered, preview_at, kind, stored) == (78, 78, 78, STEVE, STEVE)
            and capture_bytes(preview, '[x21]+0x6be') == bytes(2)):
        return 'hovered'
    return None


def arm_css_points(ctx):
    # These exact 13.0.5 callbacks and the accepted Tile NRO were exercised in
    # native-ui-state/tile-css-native-qualification.md.
    options = {'max_hits': 32, 'condition': 'thread == main'}
    return {
        'owner': point(ctx, '0x1a1308c', registers=['x19', 'x8', 'x9'], captures=captures(
            ('x8+0x28', 'bytes', 15), ('x9+0x484', 'bytes', 12),
            ('[x8+0x20]+0x167', 'u8'),
            ('[x19+0xdf0]+0x1c', 'i32'), ('[x19+0xdf0]+0xd0', 'bytes', 16),
            ('[x19+0xdf0]+0x11b', 'bytes', 5),
            ('[[x19+0x250]+8]+0x150', 'i32'), ('[[x19+0x250]+8]+0x200', 'u64')), **options),
        'hover': point(ctx, '0x1a1316c', registers=['x19', 'x24', 'x9', 'x28'], **options),
        'preview': point(ctx, '0x1a13930', registers=['x19', 'x24', 'x0', 'x21', 'x28'],
                         captures=captures(('[x21]+0x200', 'u64'), ('[x21]+0x6be', 'bytes', 2)),
                         **options),
    }


def css_native(ctx, expected, after=None, *, melee='0x00'):
    """Join the native P1 direct input, actual hover, preview and medal in one layout."""
    qualified(ctx, CSS)
    ids = arm_css_points(ctx)
    last = []
    for ui in samples(ctx, 3, interval=0.06):
        if (not all(ui['values'].get(k) == v for k, v in {**NATIVE, **CSS}.items())
                or ui['scene']['mode'] != '0x04040000' or ui['scene']['melee'] != melee):
            continue
        last = [event for event in read_trace(ctx) if str(event.get('point_id')) in ids.values()]
        joins = {}
        for event in last:
            if time.time_ns() - int(event['wall_time_ns']) > 800_000_000:
                continue
            key = tuple(event[k] for k in ('process_id', 'thread_id', 'frame')) + (
                event['registers']['x19'],)
            if after and (key[0] != after['owner']['process_id'] or key[3] != after['owner']['registers']['x19']
                          or int(key[2]) <= int(after['owner']['frame'])):
                continue
            matched = joins.setdefault(key, {})
            pid = str(event['point_id'])
            if pid == ids['owner'] and capture_bytes(event, 'x8+0x28')[:4] == bytes(4):
                matched['owner'] = event
            if pid == ids['hover'] and int(event['registers']['x28'], 16) == 0:
                matched['hover'] = event
            if pid == ids['preview'] and int(event['registers']['x28'], 16) == 0 and 'hover' in matched:
                matched['preview'] = event
        streak = None
        for matched in joins.values():
            if 'owner' not in matched:
                continue
            owner = matched['owner']
            state = css_player_state(owner, matched.get('hover'), matched.get('preview'),
                                     held_only='holding' in expected)
            if state not in expected:
                streak = None
                continue
            if (streak and streak[0] == state and streak[1]['frame'] != owner['frame']
                    and streak[1]['registers']['x8'] == owner['registers']['x8']):
                return {'state': state, 'bridge': ui, **matched}
            streak = state, owner
    save(ctx.row_dir / f'css-unqualified-{time.time_ns()}.json', {'ids': ids, 'records': last})
    raise RuntimeError(f'Native Training CSS did not qualify any of {expected}')


def training(ctx):
    placed_path = ctx.row_dir / 'placed-fighter.json'
    if placed_path.exists():
        for sample in samples(ctx, 1):
            if (all(sample['values'].get(k) == v for k, v in {**NATIVE, **TRAINING}.items())
                    and (sample['scene']['mode'], sample['scene']['melee'], sample['scene']['class'])
                    == ('0x04040000', '0x20', 'training')
                    and read_json(placed_path)['bridge']['values']['boot'] == sample['values']['boot']):
                screen_shot(ctx, 'native-training')
                return save(ctx.row_dir / 'native-training.json', {'after': sample})
            break
    before = css_native(ctx, ('off_grid', 'hovered', 'placed'))
    if before['state'] == 'off_grid':
        save(ctx.row_dir / 'off-grid-fighter.json', before)
        routes.play(ctx, 'tile-up')
        before = css_native(ctx, ('hovered',), after=before)
    if before['state'] == 'hovered':
        save(ctx.row_dir / 'hovered-fighter.json', before)
        routes.play(ctx, 'tap-a1')
        before = css_native(ctx, ('placed',), after=before)
    else:
        hover_path = ctx.row_dir / 'hovered-fighter.json'
        stored = read_json(hover_path) if hover_path.exists() else None
        if (not stored or stored['bridge']['values']['boot'] != before['bridge']['values']['boot']
                or stored['owner']['registers']['x19'] != before['owner']['registers']['x19']
                or stored['owner']['process_id'] != before['owner']['process_id']):
            raise RuntimeError('No same-boot typed hover receipt for existing P1 placement')
    save(placed_path, before)
    result = route_edge(ctx, 'native-training', CSS, 'enter-training', TRAINING, 90)
    screen_shot(ctx, 'native-training')
    return result


def leave_warm_css(ctx):
    player = css_native(ctx, ('placed', 'holding'), melee='0x20')
    if player['state'] == 'placed':
        save(ctx.row_dir / 'warm-placed-fighter.json', player)
        play_menu(ctx, 'leave-css')
        player = css_native(ctx, ('holding',), after=player, melee='0x20')
    save(ctx.row_dir / 'warm-held-fighter.json', player)
    return route_edge(ctx, 'warm-stage-select', CSS, 'leave-css', SSS, 20)


def leave_warm_stage_select(ctx):
    before = qualified(ctx, SSS)
    if (before['scene']['mode'], before['scene']['melee']) != ('0x04040000', '0x20'):
        raise RuntimeError(f'Unexpected warm Training Stage Select scene: {before}')
    # The original picker requires sustained B. The pinned 90-frame hold
    # also allows a fresh observation of either native Main layer.
    pin = play_menu(ctx, 'leave-css')
    after = qualified(ctx, GAMES_SUBMENU, 20, before, also=TOP)
    return save(ctx.row_dir / 'warm-picker-back.json', {'before': before, 'macro_sha256': pin, 'after': after})


def return_from_training(ctx):
    cpu, quit_focus = ({**PAUSE, 'focus.id': focus} for focus in ('cpu_count', 'quit_training'))
    path = (
        ('native-pause', TRAINING, 'pause-open', cpu),
        ('native-quit-focus', cpu, 'focus-native-quit-frames', quit_focus),
        ('warm-css', quit_focus, 'confirm-native-quit-frames', CSS),
    )
    checkpoints = (*[item[1] for item in path], CSS, SSS, GAMES_SUBMENU, TOP)
    pending = None
    for sample in samples(ctx, 10):
        if sample['scene']['init'] != '1':
            continue
        pending = next((index for index, screen in enumerate(checkpoints)
                        if all(sample['values'].get(key) == value for key, value in {**NATIVE, **screen}.items())),
                       None)
        if pending is not None:
            break
    if pending is None:
        raise RuntimeError('No qualified screen in the native Training return path')
    for name, source, macro, dest in path[pending:]:
        sample = route_edge(ctx, name, source, macro, dest, 20)['after']
    if pending <= 3:
        sample = leave_warm_css(ctx)['after']
    if pending <= 4:
        sample = leave_warm_stage_select(ctx)['after']
    if sample['values'].get('screen.layer') != 'top':
        sample = route_edge(ctx, 'native-main-return', GAMES_SUBMENU, 'tap-b1', TOP, 20)['after']
    screen_shot(ctx, 'native-main-return')
    return save(ctx.row_dir / 'qualified-return-main.json', sample)


def finish_trace(ctx):
    candidate = bool(fixture(ctx).get('stock'))
    if candidate:
        hits = trace(ctx, read_trace(ctx))
        if any(hits.get(name) for name in ('title.expiry', 'main.expiry', 'how_to_play', 'demo')):
            raise RuntimeError('Unexpected guest expiry or attract request during candidate navigation')
    counters = ctx.call('trace.counters')
    receipt = save(ctx.row_dir / 'end.json', {
        'list': ctx.call('trace.list'), 'counters': counters,
        'unmapped': ctx.call('trace.unmapped_access', {}), 'modules': ctx.call('modules.list')})
    if counters['output_error'] or counters['boot_error'] or int(counters['file_lost']):
        raise RuntimeError('Guest trace output reported loss or failure')
    by_id = {counter['id']: counter for counter in counters['points']}
    if any(int(counter['dropped']) for counter in by_id.values()):
        raise RuntimeError('A guest trace point dropped records')
    if candidate:
        ids = read_json(run_dir(ctx) / 'menu-timers-points.json')
        for name in ('title.expiry', 'main.expiry', 'how_to_play', 'demo'):
            if int(by_id[ids[name]]['hits']):
                raise RuntimeError(f'Candidate hit {name}')
    return receipt
