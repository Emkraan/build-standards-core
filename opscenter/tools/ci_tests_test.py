"""
ci_tests_test.py
Purpose: The CI test runner: every file runs in its own process (an environment variable one file sets never reaches the next), a
         failing file fails the run and shows its error, a live-state file is skipped and listed on every run, a listed proof that is
         missing fails, a broken config is exit 2, and patterns and folders select the files.
Run:     python3 ci_tests_test.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ci_tests as c

PASS = "import unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertTrue(True)\n"
FAIL = "import unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.fail('boom here')\n"


class Runner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.lines = []

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def run_all(self, config=None):
        return c.run(self.root, config or {}, out=self.lines.append)

    def test_a_passing_and_a_failing_file(self):
        self.put("a_test.py", PASS)
        self.put("b_test.py", FAIL)
        ran, failed, skipped = self.run_all()
        self.assertEqual((ran, failed, skipped), (2, ["b_test.py"], []))
        text = "\n".join(self.lines)
        self.assertIn("ok   a_test.py", text)
        self.assertIn("FAIL b_test.py", text)
        self.assertIn("boom here", text)

    def test_each_file_runs_in_its_own_process(self):
        self.put(
            "a_test.py",
            "import os, unittest\nos.environ['LEAK'] = '1'\nclass T(unittest.TestCase):\n    def test_a(self):\n        pass\n",
        )
        self.put(
            "b_test.py",
            "import os, unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertNotIn('LEAK', os.environ)\n",
        )
        self.assertEqual(self.run_all()[1], [])

    def test_a_live_state_file_is_skipped_and_the_skip_list_is_printed_every_run(self):
        self.put("live_test.py", FAIL)
        self.put("a_test.py", PASS)
        ran, failed, skipped = self.run_all({"live_state": ["live_test.py", "ghost_test.py"]})
        self.assertEqual((ran, failed, skipped), (1, [], ["live_test.py"]))
        text = "\n".join(self.lines)
        self.assertIn("skip live_test.py: needs live machine state", text)
        self.assertIn("1 live-state file(s) skipped", text)
        self.assertIn("ghost_test.py is in the live-state list but no such test file", text)

    def test_a_missing_proof_fails_and_a_present_one_runs_from_its_folder(self):
        self.put("scripts/proof.py", "import sys\nsys.exit(0)\n")
        ran, failed, _ = self.run_all({"proofs": ["scripts/proof.py", "scripts/gone.py"]})
        self.assertEqual((ran, failed), (2, ["scripts/gone.py"]))
        self.put("scripts/bad.py", "import sys\nsys.exit(3)\n")
        self.assertEqual(self.run_all({"proofs": ["scripts/bad.py"]})[1], ["scripts/bad.py"])

    def test_folders_and_patterns_select_the_files(self):
        self.put("app/x_test.py", PASS)
        self.put("app/y_checks.py", FAIL)
        self.put("other/z_test.py", FAIL)
        ran, failed, _ = self.run_all({"folders": ["app"]})
        self.assertEqual((ran, failed), (1, []))
        ran, failed, _ = self.run_all(
            {"folders": ["app"], "patterns": ["*_test.py", "*_checks.py"]}
        )
        self.assertEqual((ran, failed), (2, ["y_checks.py"]))

    def test_the_config_file_and_exit_codes(self):
        self.put("a_test.py", PASS)
        self.assertEqual(c.main(["--root", str(self.root)]), 0)
        self.put("b_test.py", FAIL)
        self.assertEqual(c.main(["--root", str(self.root)]), 1)
        (self.root / "ci-tests.json").write_text(json.dumps({"live_state": ["b_test.py"]}))
        self.assertEqual(c.main(["--root", str(self.root)]), 0)
        (self.root / "ci-tests.json").write_text("{nope")
        self.assertEqual(c.main(["--root", str(self.root)]), 2)
        self.assertEqual(c.main(["--bogus"]), 2)


if __name__ == "__main__":
    unittest.main()
