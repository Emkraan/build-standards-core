"""Runs the plan gate's synthetic checks (tfplan_gate_checks.py, a script that prints OK or FAIL per check)
under unittest, so a failed check fails core CI. The script runs in its own process because it patches the
gate module in place."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class PlanGateChecks(unittest.TestCase):
    def test_every_check_passes(self):
        env = dict(os.environ)
        for k in [k for k in env if k.startswith("TFGATE_")]:
            del env[k]
        p = subprocess.run(
            [sys.executable, str(HERE / "tfplan_gate_checks.py")],
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )
        failed = [line for line in p.stdout.splitlines() if line.startswith("FAIL")]
        ok = [line for line in p.stdout.splitlines() if line.startswith("OK")]
        self.assertEqual(failed, [], p.stderr[-2000:])
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        self.assertGreater(len(ok), 250)

    def test_the_wrappers_exist_and_are_executable(self):
        for name in ("tfplan-gate.sh", "tfplan-fastpass.sh"):
            self.assertTrue(os.access(HERE / name, os.X_OK), name)


if __name__ == "__main__":
    unittest.main()
