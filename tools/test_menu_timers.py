"""Host checks for native timer and fighter-select evidence used by the Eden rows."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


path = Path(__file__).resolve().parents[1] / "eden" / "menu_timers.py"
spec = importlib.util.spec_from_file_location("menu_timers", path)
menu_timers = importlib.util.module_from_spec(spec)
# The timing extraction takes trace records directly. The runner owns live I/O.
with patch.dict(sys.modules, routes=types.ModuleType("routes")):
    spec.loader.exec_module(menu_timers)


def event(menu, count, limit, frame, wall, sequence):
    _, count_reg, limit_reg, _ = menu_timers.GUARDS[menu]
    return {
        "registers": {count_reg: hex(count), limit_reg: hex(limit)},
        "frame": str(frame),
        "wall_time_ns": str(wall),
        "sequence": str(sequence),
        "process_id": "81",
        "thread_id": "80",
    }


class TimingTests(unittest.TestCase):
    def test_stock_timing_uses_each_menus_register_order(self):
        for menu, limit in (("title", 720), ("main", 18000)):
            with self.subTest(menu=menu):
                start = event(menu, 1, limit, 200, 10_000_000_000, 20)
                duration_s = limit // 60
                end = 10_000_000_000 + duration_s * 1_000_000_000
                over = event(menu, limit + 1, limit, 200 + limit, end, 21)
                expiry = event(menu, 0, 0, 200 + limit, end + 1, 22)
                result = menu_timers.measure(menu, start, over, expiry)
                self.assertEqual(result["threshold_ticks"], limit)
                self.assertEqual(result["idle_expiry"], limit + 1)
                self.assertEqual(result["elapsed_s"], duration_s)
                self.assertEqual(result["vsync_delta"], limit)

    def test_invalid_stock_window_is_refused(self):
        start = event("title", 1, 720, 200, 10_000_000_000, 20)
        over = event("title", 721, 720, 920, 22_000_000_000, 21)
        expiry = event("title", 0, 0, 920, 22_000_000_001, 22)
        cases = [
            (event("title", 100, 720, 250, 11_000_000_000, 20), over, expiry),
            (start, event("title", 720, 720, 920, 22_000_000_000, 21), expiry),
            (start, dict(over, process_id="82"), expiry),
            (start, dict(over, wall_time_ns=start["wall_time_ns"]), expiry),
            (start, over, dict(expiry, sequence=over["sequence"])),
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(RuntimeError):
                menu_timers.measure("title", *case)



def capture(expression, data):
    return {"expression": expression, "hex": data.hex(), "error": ""}


class CandidateCssTests(unittest.TestCase):
    def setUp(self):
        player = bytearray(15)
        player[14] = 1
        self.owner = {
            "captures": [
                capture("x8+0x28", player),
                capture("x9+0x484", bytes(12)),
                capture("[x8+0x20]+0x167", b"\x01"),
            ],
        }
        self.hover = {"registers": {"x24": "0x4e", "x9": "0x4e"}}
        steve = menu_timers.STEVE.to_bytes(8, "little")
        self.preview = {
            "registers": {"x24": "0x4e", "x0": hex(menu_timers.STEVE)},
            "captures": [
                capture("[x21]+0x200", steve),
                capture("[x21]+0x6be", bytes(2)),
            ],
        }

    def test_navigation_requires_native_hover_after_tile_settles(self):
        early = {"registers": {"x24": "0x4e", "x9": "0xffffffff"}}
        self.assertIsNone(menu_timers.css_player_state(self.owner, early, self.preview))
        self.assertEqual(
            menu_timers.css_player_state(self.owner, self.hover, self.preview), "hovered"
        )

    def test_navigation_requires_committed_p1_medal(self):
        player = bytearray.fromhex(self.owner["captures"][0]["hex"])
        player[8:12] = b"\xff" * 4
        self.owner["captures"] = [
            capture("x8+0x28", player),
            capture("x9+0x484", bytes(12)),
            capture("[x8+0x20]+0x167", b"\x00"),
            capture("[x19+0xdf0]+0x1c", bytes.fromhex("4e000000")),
            capture("[x19+0xdf0]+0xd0", bytes.fromhex(menu_timers.STEVE_RECT)),
            capture("[[x19+0x250]+8]+0x150", bytes(4)),
            capture("[[x19+0x250]+8]+0x200", menu_timers.STEVE.to_bytes(8, "little")),
        ]
        self.assertIsNone(menu_timers.css_player_state(self.owner, None, None))
        self.owner["captures"].append(capture("[x19+0xdf0]+0x11b", b"\x01" + bytes(4)))
        self.assertEqual(menu_timers.css_player_state(self.owner, None, None), "placed")

if __name__ == "__main__":
    unittest.main()
