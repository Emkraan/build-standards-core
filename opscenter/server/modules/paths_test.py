import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paths  # noqa: E402

KEYS = ("OPSCENTER_ROOT", "OPSCENTER_STATE_DIR", "OPSCENTER_AGENT_HOME", "OPSCENTER_REPOS", "X_BIN")


class Paths(unittest.TestCase):
    def setUp(self):
        self._old = {k: os.environ.pop(k, None) for k in KEYS}

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_defaults_live_under_one_dot_folder_in_home(self):
        self.assertEqual(paths.root(), Path.home() / ".opscenter")
        self.assertEqual(paths.state_dir(), Path.home() / ".opscenter" / "state")
        self.assertEqual(paths.dashboard_dir(), Path.home() / ".opscenter" / "state" / "dashboard")
        self.assertEqual(paths.agent_home(), Path.home() / ".opscenter" / "agent")
        self.assertEqual(paths.repos_dir(), Path.home() / "repos")

    def test_the_root_moves_everything_and_a_specific_variable_wins(self):
        os.environ["OPSCENTER_ROOT"] = "/data/ops"
        self.assertEqual(paths.state_dir(), Path("/data/ops/state"))
        self.assertEqual(paths.agent_home(), Path("/data/ops/agent"))
        os.environ["OPSCENTER_STATE_DIR"] = "/elsewhere/state"
        self.assertEqual(paths.dashboard_dir(), Path("/elsewhere/state/dashboard"))

    def test_which_prefers_the_override_then_path_then_the_bare_name(self):
        os.environ["X_BIN"] = "/custom/x"
        self.assertEqual(paths.which("python3", "X_BIN"), "/custom/x")
        del os.environ["X_BIN"]
        self.assertTrue(paths.which("python3", "X_BIN").endswith("python3"))
        self.assertEqual(paths.which("no-such-binary-xyz"), "no-such-binary-xyz")


if __name__ == "__main__":
    unittest.main()
