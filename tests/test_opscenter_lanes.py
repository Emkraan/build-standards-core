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


class EachClassRunsAlone(unittest.TestCase):
    """The server test modules are loaded together, so a class that only works because an earlier one imported something first goes
    unnoticed. Running one class by itself is what a person does to chase a failure, and it must give the same answer as the full run."""

    MODULES = ("optional_test",)

    def test_every_class_passes_in_its_own_process(self):
        import os
        import re
        import subprocess
        import tempfile

        server = OPSCENTER / "server"
        for module in self.MODULES:
            source = (server / f"{module}.py").read_text()
            # A class with a test_ method of its own holds cases. A base class holds none and is skipped.
            owners = []
            for block in re.split(r"(?m)^class ", source)[1:]:
                name = re.match(r"(\w+)", block).group(1)
                if re.search(r"(?m)^    def test_", block):
                    owners.append(name)
            self.assertGreater(
                len(owners),
                5,
                f"{module}: found no test classes, so this check would pass by looking at nothing",
            )
            for name in owners:
                with self.subTest(module=module, cls=name), tempfile.TemporaryDirectory() as home:
                    env = {**os.environ, "HOME": home}
                    r = subprocess.run(
                        [sys.executable, "-m", "unittest", f"{module}.{name}"],
                        cwd=server,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=240,
                    )
                    self.assertEqual(
                        r.returncode, 0, f"{module}.{name} fails when run alone:\n{r.stderr[-700:]}"
                    )
                    ran = re.search(r"Ran (\d+) test", r.stderr)
                    self.assertTrue(ran and int(ran.group(1)) > 0, f"{module}.{name} ran no test")


if __name__ == "__main__":
    unittest.main()
