"""Runs the auto-fix starter's synthetic checks (autofix_checks.py, a script that prints OK or FAIL per check) under
unittest, so a failed check fails core CI. The script runs in its own process because it patches the module in place."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class AutofixChecks(unittest.TestCase):
    def test_every_check_passes(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AUTOFIX_", "OWNPR_"))}
        p = subprocess.run(
            [sys.executable, str(HERE / "autofix_checks.py")],
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )
        failed = [ln for ln in p.stdout.splitlines() if ln.startswith("FAIL ")]
        ok = [ln for ln in p.stdout.splitlines() if ln.startswith("OK")]
        self.assertEqual(failed, [], p.stderr[-2000:])
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        self.assertGreater(len(ok), 100)


if __name__ == "__main__":
    unittest.main()
