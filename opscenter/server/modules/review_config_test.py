"""
review_config_test.py
Purpose: review_config reads the estate values from one JSON file, treats a missing or broken file as nothing
         configured, ignores unknown keys, and need() raises a 501 NotConfigured naming the missing value.
Run:     python3 review_config_test.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_config as cfg  # noqa: E402


class Config(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.f = Path(self.d.name) / "c.json"
        self.old = os.environ.get("OPSCENTER_REVIEWS_CONFIG")
        os.environ["OPSCENTER_REVIEWS_CONFIG"] = str(self.f)

    def tearDown(self):
        if self.old is None:
            os.environ.pop("OPSCENTER_REVIEWS_CONFIG", None)
        else:
            os.environ["OPSCENTER_REVIEWS_CONFIG"] = self.old
        self.d.cleanup()

    def test_missing_file_is_nothing_configured(self):
        self.assertEqual(
            (cfg.owner(), cfg.plan_repo(), cfg.privileged_envs(), cfg.typed_confirm()),
            ("", "", {}, ()),
        )
        self.assertEqual(cfg.repo_reviews(), [])

    def test_broken_file_is_nothing_configured(self):
        self.f.write_text("{not json")
        self.assertEqual(cfg.load(), {})

    def test_values_are_read_on_every_call(self):
        self.f.write_text(
            json.dumps({"owner": " me ", "plan_repo": "o/r", "plan_env": "plan", "extra": 1})
        )
        self.assertEqual((cfg.owner(), cfg.plan_repo(), cfg.plan_env()), ("me", "o/r", "plan"))
        self.assertNotIn("extra", cfg.load())
        self.f.write_text(json.dumps({"owner": "you"}))
        self.assertEqual(cfg.owner(), "you")

    def test_collections_are_typed(self):
        self.f.write_text(
            json.dumps(
                {
                    "privileged_envs": {"a": "A"},
                    "typed_confirm": ["a"],
                    "repo_reviews": ["o/r", "bad"],
                }
            )
        )
        self.assertEqual(cfg.privileged_envs(), {"a": "A"})
        self.assertEqual(cfg.typed_confirm(), ("a",))
        self.assertEqual(cfg.repo_reviews(), ["o/r"])

    def test_need_raises_501(self):
        with self.assertRaises(cfg.NotConfigured) as c:
            cfg.need("", "owner")
        self.assertEqual(c.exception.status, 501)
        self.assertIn("owner", str(c.exception))
        self.assertEqual(cfg.need("x", "owner"), "x")


if __name__ == "__main__":
    unittest.main()
