"""Runs the unit tests that ship beside the ops center modules (opscenter/<area>/*_test.py)."""

import pathlib
import sys
import unittest

OPSCENTER = pathlib.Path(__file__).resolve().parent.parent / "opscenter"
AREAS = (
    "lanes",
    "server",
    "server/modules",
    "server/modules/reports",
    "gates",
    "engine",
    "people",
    "tracker",
    "tools",
)


def load_tests(loader, tests, pattern):
    for area in AREAS:
        folder = OPSCENTER / area
        if not folder.is_dir():
            continue
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
        for path in sorted(folder.glob("*_test.py")):
            tests.addTests(loader.loadTestsFromName(path.stem))
    return tests


class LaneChecks(unittest.TestCase):
    """The own-PR lane's synthetic checks (opscenter/lanes/tests/own_pr_merge_checks.py) exit non-zero on any failed case."""

    def test_own_pr_merge_checks_pass(self):
        import subprocess

        script = OPSCENTER / "lanes" / "tests" / "own_pr_merge_checks.py"
        r = subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True, timeout=300
        )
        self.assertEqual(
            r.returncode,
            0,
            "\n".join(ln for ln in r.stdout.splitlines() if ln.startswith("FAIL"))
            or r.stderr[-800:],
        )
        self.assertIn("FAILURES: 0", r.stdout)


if __name__ == "__main__":
    unittest.main()
