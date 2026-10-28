import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ops_search as s  # noqa: E402


class OpsSearch(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        d = Path(self._d.name)
        self.dash, self.data = d / "dash", d / "data"
        self.dash.mkdir()
        self.data.mkdir()
        self._old = (s.DASH, s.DATA, s.RUNTIME_DB, os.environ.get("SEARCH_DIRS"))
        s.DASH, s.DATA, s.RUNTIME_DB = self.dash, self.data, d / "state.db"
        (d / "notes").mkdir()
        (d / "notes" / "runbook.md").write_text(
            "# Disk\nThe backup disk fills up on Fridays.\nSecond line about tape.\n"
        )
        (d / "notes" / "big.bin").write_bytes(b"\x00" * 10)
        os.environ["SEARCH_DIRS"] = json.dumps(
            [{"path": str(d / "notes"), "label": "Notes", "recursive": False}]
        )

    def tearDown(self):
        s.DASH, s.DATA, s.RUNTIME_DB = self._old[:3]
        if self._old[3] is None:
            os.environ.pop("SEARCH_DIRS", None)
        else:
            os.environ["SEARCH_DIRS"] = self._old[3]
        self._d.cleanup()

    def test_short_or_empty_queries_search_nothing(self):
        for q in ("", None, "a"):
            self.assertEqual(s.search(q)["total"], 0)

    def test_terms_keep_quoted_phrases(self):
        self.assertEqual(s._lower_terms('Disk "Backup Tape" x'), ["disk", "backup tape", "x"])

    def test_files_are_searched_ranked_and_snippeted(self):
        r = s.search("backup disk")
        hit = r["groups"]["file"][0]
        self.assertEqual((hit["title"], hit["group"]), ("runbook.md", "Notes"))
        self.assertIn("backup disk fills up", hit["snippet"])
        self.assertEqual(r["errors"], {})
        self.assertNotIn("big.bin", json.dumps(r))

    def test_board_items_open_and_completed_rotated_out(self):
        (self.data / "action-center.json").write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "fp": "f1",
                            "title": "Disk alarm",
                            "why": "backup disk",
                            "action": "free space",
                            "refs": ["T-1"],
                        }
                    ]
                }
            )
        )
        (self.dash / "action-handled.json").write_text(
            json.dumps(
                {
                    "handled": {
                        "old": {
                            "act": "resolved",
                            "item": {"title": "Old disk issue", "why": "disk"},
                            "summary": "done",
                        }
                    }
                }
            )
        )
        groups = s.search("disk")["groups"]["action"]
        routes = {h["fp"]: h["route"] for h in groups}
        self.assertEqual(routes["f1"], "/action?item=f1")
        self.assertEqual(routes["old"], "/action/completed")

    def test_one_on_one_topics(self):
        (self.dash / "one-on-one-topics.json").write_text(
            json.dumps(
                {
                    "topics": {
                        "a": {
                            "title": "Career growth",
                            "person": "pat",
                            "messages": [{"text": "wants a lead role"}],
                        }
                    }
                }
            )
        )
        h = s.search("lead role")["groups"]["one-on-one"][0]
        self.assertEqual((h["person"], h["route"]), ("pat", "/people?p=pat"))

    def test_runtime_sessions_by_title_and_full_text(self):
        con = sqlite3.connect(s.RUNTIME_DB)
        con.executescript(
            "CREATE TABLE sessions (id TEXT, title TEXT, archived INT, started_at TEXT, last_activity_at TEXT, source TEXT);"
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT);"
            "CREATE VIRTUAL TABLE messages_fts USING fts5(content, content='messages', content_rowid='id');"
        )
        con.execute(
            "INSERT INTO sessions VALUES ('s1','Tape rotation plan',0,'2026-10-01','2026-10-02','cli')"
        )
        con.execute(
            "INSERT INTO sessions VALUES ('s2','Unrelated',1,'2026-10-01','2026-10-03','cli')"
        )
        con.execute(
            "INSERT INTO messages (id, session_id, role, content) VALUES (1,'s2','user','we discussed the tape drive')"
        )
        con.execute(
            "INSERT INTO messages_fts (rowid, content) VALUES (1,'we discussed the tape drive')"
        )
        con.commit()
        con.close()
        groups = s.search("tape")["groups"]["session"]
        by = {h["session_id"]: h for h in groups}
        self.assertEqual(set(by), {"s1", "s2"})
        self.assertEqual(by["s2"]["matches"], 1)
        self.assertTrue(by["s2"]["archived"])

    def test_a_missing_runtime_db_just_means_no_session_group(self):
        self.assertNotIn("session", s.search("anything")["groups"])

    def test_one_broken_source_never_sinks_the_search(self):
        s.SOURCES["boom"] = lambda terms: 1 / 0
        try:
            r = s.search("backup")
        finally:
            del s.SOURCES["boom"]
        self.assertIn("boom", r["errors"])
        self.assertEqual(r["groups"]["file"][0]["title"], "runbook.md")

    def test_tracker_query(self):
        self.assertEqual(
            s.tracker_query("TK-12 disk full"),
            '(key in (TK-12) OR text ~ "disk full") ORDER BY updated DESC',
        )
        self.assertEqual(s.tracker_query("disk"), '(text ~ "disk") ORDER BY updated DESC')
        self.assertIsNone(s.tracker_query(""))

    def test_each_group_is_capped(self):
        for i in range(8):
            (Path(self._d.name) / "notes" / f"n{i}.md").write_text("capword\n")
        self.assertEqual(len(s.search("capword", limit=3)["groups"]["file"]), 3)


if __name__ == "__main__":
    unittest.main()
