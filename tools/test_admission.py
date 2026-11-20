"""Check the actual supervisor admission gate against captured ledger syntax."""

import json
from pathlib import Path
import subprocess
import sys
import unittest


GATE = Path(__file__).resolve().parents[1] / "eden" / "admission.py"


class AdmissionTests(unittest.TestCase):
    def gate(self, *lines):
        result = subprocess.run(
            [sys.executable, "-I", str(GATE), "yoga"],
            input="\n".join(lines),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertFalse(result.stderr, result.stderr)
        return result.returncode, json.loads(result.stdout)

    def test_priority_admission(self):
        unrelated = "BUILD CLAIMED host=xps owner=drill-picker-sol bid=123"
        build = "BUILD CLAIMED host=yoga owner=integration bid=456"
        runtime = "CLAIMED: Codex test/lockon-sol-3 host=yoga lifecycle=789"
        wrong_release = "RELEASED: Codex test/lockon-sol-3 host=yoga lifecycle=other"

        status, proof = self.gate(unrelated, build, runtime, wrong_release)
        self.assertEqual(status, 1)
        self.assertEqual(proof["build"], [build])
        self.assertEqual(proof["runtime"], [runtime])

        build_done = "BUILD RELEASED host=yoga owner=integration bid=456"
        runtime_done = "RELEASED: Codex test/lockon-sol-3 host=yoga lifecycle=789"
        status, proof = self.gate(unrelated, build, runtime, build_done, runtime_done)
        self.assertEqual(status, 0)
        self.assertEqual(proof["build"], [])
        self.assertEqual(proof["runtime"], [])

    def test_empty_ledger_blocks_admission(self):
        result = subprocess.run(
            [sys.executable, "-I", str(GATE), "yoga"],
            input="",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Unable to read the authoritative ledger", result.stderr)


if __name__ == "__main__":
    unittest.main()
