"""Runs the unit tests that ship beside the ops center modules (opscenter/<area>/*_test.py)."""

import pathlib
import sys
import unittest

OPSCENTER = pathlib.Path(__file__).resolve().parent.parent / "opscenter"
AREAS = ("lanes", "server/modules", "gates", "engine", "people", "tracker")


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


if __name__ == "__main__":
    unittest.main()
