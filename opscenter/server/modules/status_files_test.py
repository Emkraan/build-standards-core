import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

NOW = 2_000_000_000.0


class StatusFiles(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="status-"))
        self._env = dict(os.environ)
        os.environ["OPSCENTER_STATE_DIR"] = str(self.d / "state")
        os.environ.pop("OPSCENTER_STATUS_FRESH_MIN", None)
        for m in ("stores", "status_files"):
            sys.modules.pop(m, None)
        import status_files

        self.sf = importlib.reload(status_files)
        self.dash = self.d / "state" / "dashboard"
        self.dash.mkdir(parents=True)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def put(self, name, age_min, text="{}"):
        p = self.dash / name
        p.write_text(text)
        os.utime(p, (NOW - age_min * 60, NOW - age_min * 60))

    def test_it_lists_json_files_oldest_first_with_size_and_a_server_decided_state(self):
        self.put("fresh.json", 5, '{"a": 1}')
        self.put("old.json", 3000)
        self.put("notes.txt", 1)
        self.put(".hidden.json", 1)
        (self.dash / "sub.json").mkdir()
        out = self.sf.get(NOW)
        self.assertEqual([f["name"] for f in out["files"]], ["old.json", "fresh.json"])
        self.assertEqual([f["state"] for f in out["files"]], ["stale", "fresh"])
        self.assertEqual(out["files"][1]["size"], 8)
        self.assertEqual(out["counts"], {"fresh": 1, "stale": 1})
        self.assertEqual(out["stale_after_min"], 1440)

    def test_the_limit_is_a_parameter_and_a_bad_value_falls_back(self):
        self.put("a.json", 100)
        os.environ["OPSCENTER_STATUS_FRESH_MIN"] = "60"
        self.assertEqual(self.sf.get(NOW)["files"][0]["state"], "stale")
        os.environ["OPSCENTER_STATUS_FRESH_MIN"] = "nope"
        self.assertEqual(self.sf.get(NOW)["stale_after_min"], 1440)

    def test_no_contents_and_a_missing_folder_is_an_empty_list(self):
        self.put("secret.json", 1, '{"token": "SECRETVALUE"}')
        self.assertNotIn("SECRETVALUE", repr(self.sf.get(NOW)))
        for p in self.dash.iterdir():
            p.unlink()
        self.dash.rmdir()
        out = self.sf.get(NOW)
        self.assertEqual((out["files"], out["counts"]), ([], {"fresh": 0, "stale": 0}))

    def test_a_symlink_is_not_listed(self):
        self.put("real.json", 1)
        (self.dash / "link.json").symlink_to(self.dash / "real.json")
        self.assertEqual([f["name"] for f in self.sf.get(NOW)["files"]], ["real.json"])


if __name__ == "__main__":
    unittest.main()
