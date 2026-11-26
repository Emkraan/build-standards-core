"""Runs the auto-fix starter's synthetic checks (autofix_checks.py, a script that prints OK or FAIL per check) under
unittest, so a failed check fails core CI. The script runs in its own process because it patches the module in place."""

import os
import sys
import unittest
from pathlib import Path

import checkrun

HERE = Path(__file__).resolve().parent
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("AUTOFIX_", "OWNPR_"))}
# About 30 seconds, so the full run starts it early (checkrun.py).
JOB = checkrun.register(
    [sys.executable, str(HERE / "autofix_checks.py")], env=ENV, timeout=300, expect=30
)


class AutofixChecks(unittest.TestCase):
    def test_every_check_passes(self):
        p = JOB.result()
        failed = [ln for ln in p.stdout.splitlines() if ln.startswith("FAIL ")]
        ok = [ln for ln in p.stdout.splitlines() if ln.startswith("OK")]
        self.assertEqual(failed, [], p.stderr[-2000:])
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        self.assertGreater(len(ok), 100)


if __name__ == "__main__":
    unittest.main()
