"""Runs the unit tests that ship beside the ops center lane modules (opscenter/lanes/*_test.py)."""

import pathlib
import sys
import unittest

LANES = pathlib.Path(__file__).resolve().parent.parent / "opscenter" / "lanes"


def load_tests(loader, tests, pattern):
    if str(LANES) not in sys.path:
        sys.path.insert(0, str(LANES))
    for path in sorted(LANES.glob("*_test.py")):
        tests.addTests(loader.loadTestsFromName(path.stem))
    return tests


if __name__ == "__main__":
    unittest.main()
