"""Runs the unit tests that ship beside the ops center lane modules (opscenter/lanes/*_test.py)."""

import pathlib
import unittest

LANES = pathlib.Path(__file__).resolve().parent.parent / "opscenter" / "lanes"


def load_tests(loader, tests, pattern):
    tests.addTests(loader.discover(str(LANES), pattern="*_test.py", top_level_dir=str(LANES)))
    return tests


if __name__ == "__main__":
    unittest.main()
