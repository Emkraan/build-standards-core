"""Documentation coverage page: the registry joined with the audit store, snooze and ignore (and when they stop applying), the badge count
and the tackle item."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import doc_coverage as dc

REG = {
    "things": [
        {
            "id": "a",
            "name": "Alpha",
            "tier": "A",
            "status": "live",
            "repo": "r",
            "path": "alpha",
            "confluence_home": "10",
        },
        {
            "id": "b",
            "name": "Beta",
            "tier": "B",
            "status": "live",
            "repo": "r",
            "action_center": False,
            "action_center_note": "kept off",
        },
        {"id": "c", "name": "Gamma", "tier": "B", "status": "live", "repo": "r"},
    ]
}
GAPS = {
    "generated_utc": "2026-01-01T00:00:00Z",
    "last_error": None,
    "counts": {"high": 1, "medium": 1, "low": 0},
    "surface": ["a"],
    "things": {
        "a": {
            "key": "doc-a-g2",
            "priority": "high",
            "owner_r": "Ann",
            "home_title": "Alpha home",
            "gaps": [
                {"id": "R6:metadata", "rule": "R6", "severity": "low", "text": "meta"},
                {"id": "R1:x", "rule": "R1", "severity": "high", "text": "worst"},
            ],
            "closed": [{"id": str(i)} for i in range(8)],
        },
        "b": {
            "key": "doc-b-g1",
            "priority": "medium",
            "gaps": [{"id": "x", "rule": "R2", "severity": "medium", "text": "m"}],
        },
        "c": {"key": None, "priority": "none", "gaps": []},
        "_registry": {"name": "Documentation registry", "gaps": [{"id": "R9:x"}]},
        "_duplicates": {"name": "Dups", "gaps": [{"id": "R11:1-2"}, {"id": "R11:3-4"}]},
    },
}


class Coverage(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="doc-cov-"))
        self._env = dict(os.environ)
        os.environ["OPSCENTER_STATE_DIR"] = str(self.d / "state")
        os.environ.pop("DOC_COVERAGE_HANDLED", None)
        self.dash = self.d / "state" / "dashboard"
        self.dash.mkdir(parents=True)
        (self.dash / "doc-inventory.json").write_text(json.dumps(REG))
        (self.dash / "doc-gaps.json").write_text(json.dumps(GAPS))

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.d, ignore_errors=True)

    def row(self, doc, id_):
        return next(r for r in doc["things"] if r["id"] == id_)

    def test_the_payload_joins_the_registry_and_the_audit(self):
        doc = dc.get()
        a = self.row(doc, "a")
        self.assertEqual(
            (a["priority"], a["owner_r"], a["surfaced"], a["open"], a["key"]),
            ("high", "Ann", True, True, "doc-a-g2"),
        )
        self.assertEqual(len(a["closed"]), 5)
        b = self.row(doc, "b")
        self.assertEqual((b["on_board"], b["open"], b["board_note"]), (False, False, "kept off"))
        self.assertEqual(self.row(doc, "c")["priority"], "none")
        self.assertEqual([i["id"] for i in doc["internal"]], ["_registry"])
        self.assertEqual(len(doc["duplicates"]), 2)
        self.assertEqual(
            (doc["open_count"], dc.badge()), (3, 3)
        )  # one open thing plus two duplicate sets
        self.assertEqual(doc["audited_utc"], "2026-01-01T00:00:00Z")

    def test_missing_files_give_an_empty_page(self):
        (self.dash / "doc-inventory.json").unlink()
        (self.dash / "doc-gaps.json").unlink()
        self.assertEqual((dc.get()["things"], dc.get()["open_count"]), ([], 0))

    def test_snooze_hides_for_a_week_and_restore_brings_it_back(self):
        out = dc.handle("a", "snooze")
        self.assertEqual((out["handled"]["act"], out["handled"]["key"]), ("snoozed", "doc-a-g2"))
        doc = dc.get()
        self.assertEqual((self.row(doc, "a")["open"], doc["open_count"]), (False, 2))
        dc.handle("a", "restore")
        self.assertTrue(self.row(dc.get(), "a")["open"])

    def test_an_expired_snooze_no_longer_applies(self):
        dc.handle("a", "snooze")
        p = self.dash / "doc-handled.json"
        h = json.loads(p.read_text())
        h["handled"]["a"]["until"] = "2000-01-01T00:00:00Z"
        p.write_text(json.dumps(h))
        self.assertTrue(self.row(dc.get(), "a")["open"])

    def test_ignore_holds_for_this_generation_only(self):
        dc.handle("a", "ignore")
        self.assertFalse(self.row(dc.get(), "a")["open"])
        g = json.loads(json.dumps(GAPS))
        g["things"]["a"]["key"] = "doc-a-g3"
        (self.dash / "doc-gaps.json").write_text(json.dumps(g))
        self.assertTrue(self.row(dc.get(), "a")["open"])

    def test_bad_acts_and_unknown_things_are_refused(self):
        with self.assertRaises(ValueError):
            dc.handle("a", "delete")
        with self.assertRaises(KeyError):
            dc.handle("zzz", "snooze")

    def test_tackle_sessions_are_shown_per_thing(self):
        self.assertEqual(
            self.row(dc.get({"doc-a": {"state": "running"}}), "a")["tackle"], {"state": "running"}
        )

    def test_the_tackle_item_lists_the_gaps_worst_first(self):
        item = dc.tackle_item("a", "https://docs.example.com/p/")
        self.assertEqual(
            (item["title"], item["priority"], item["refs"]), ("Document Alpha", "high", ["doc-a"])
        )
        lines = item["summary"].splitlines()
        self.assertIn("Docs home: Alpha home https://docs.example.com/p/10", lines)
        self.assertLess(item["summary"].index("worst"), item["summary"].index("meta"))

    def test_tackle_refuses_unknown_things_off_board_things_and_things_without_gaps(self):
        with self.assertRaises(KeyError):
            dc.tackle_item("zzz")
        with self.assertRaises(PermissionError):
            dc.tackle_item("b")
        with self.assertRaises(ValueError):
            dc.tackle_item("c")


if __name__ == "__main__":
    unittest.main()
