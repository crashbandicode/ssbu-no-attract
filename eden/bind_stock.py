"""Bind a candidate's idle bounds to its completed, matched stock control."""

import argparse
import hashlib
import json
from pathlib import Path


def load(path):
    return json.loads(path.read_text())


def bind(stock, candidate, *, allow_cross_host=False):
    if (stock / 'supervisor-result.txt').read_text().strip() != '0':
        raise RuntimeError('Stock control did not complete and Down')
    phase = load(stock / 'state/lifecycle.json')
    if phase.get('phase') != 'down' or not phase.get('released') or phase.get('cleanup_failures'):
        raise RuntimeError('Stock control lacks an independently verified lifecycle release')

    before = load(stock / 'config.json')
    after = load(candidate / 'config.json')
    keys = ('playbook', 'runner', 'game_base', 'game_updates', 'expected_game_version')
    if not allow_cross_host:
        keys += ('host', 'hostname')
    for key in keys:
        if before[key] != after[key]:
            raise RuntimeError(f'Stock and candidate {key} differ')
    initial, = before['instances']
    patched, = after['instances']
    release = [p for p in patched['plugins'] if p['name'] == 'libssbu_no_attract.nro']
    comparable = dict(patched, plugins=[p for p in patched['plugins'] if p not in release])
    if len(release) != 1 or initial != comparable:
        raise RuntimeError('The exact release must be the sole lineup difference')
    bounds = {}
    for menu in ('title', 'main'):
        receipt = stock / 'out' / f'{menu}-idle' / f'stock-{menu}-idle.json'
        result = load(receipt)
        bridge_interval = (result['bridge_attract']['received_ns'] - int(result['first']['wall_time_ns'])) / 1e9
        bounds[menu] = {
            'elapsed_s': max(result['elapsed_s'], result['attract_elapsed_s'], bridge_interval),
            'vsync_delta': max(result['vsync_delta'], result['attract_vsync_delta']),
            'threshold_ticks': result['threshold_ticks'],
            'receipt_sha256': hashlib.sha256(receipt.read_bytes()).hexdigest(),
        }
    fixture = {'port': load(stock / 'menu-timers-input.json')['port'], 'stock_run': str(stock), 'stock': bounds}
    if before['host'] != after['host']:
        fixture.update(stock_host=before['host'], candidate_host=after['host'],
                       original_stock_run=str(Path(before['state_dir']).parent))
    (candidate / 'menu-timers-input.json').write_text(json.dumps(fixture, indent=2) + '\n')
    return fixture


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stock', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--allow-cross-host', action='store_true')
    args = parser.parse_args()
    print(json.dumps(bind(args.stock, args.candidate, allow_cross_host=args.allow_cross_host), indent=2))
