"""
tackle_session_test.py
Purpose: A launch from a card binds to the session that started with its staged prompt, not the session a desktop plugin reports
         as focused: the first user message decides; a session that merely repeats the prompt later does not match; the newest
         match wins; nothing persisted yet is None; an unreadable database is None.
Run:     python3 tackle_session_test.py
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

TMP = Path(tempfile.mkdtemp())
os.environ["OPSCENTER_SESSIONS_DB"] = str(TMP / "state.db")

import tackle_session as ts  # noqa: E402

PROMPT = "Tackle: fix the failing apply\nref: PR #12\nfp: ac_abc123\n" + "detail " * 40


def db(rows):
    p = TMP / "state.db"
    if p.exists():
        p.unlink()
    con = sqlite3.connect(p)
    con.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT, timestamp REAL)"
    )
    for sid, role, content, t in rows:
        con.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?,?,?,?)",
            (sid, role, content, t),
        )
    con.commit()
    con.close()


class Tackle(unittest.TestCase):
    def test_the_session_whose_first_user_message_is_the_prompt(self):
        db(
            [
                ("old-focus", "user", "Discuss PR #348", 100.0),
                ("real", "user", PROMPT, 200.0),
                ("real", "assistant", "on it", 201.0),
            ]
        )
        self.assertEqual(ts.find_prompt_session(PROMPT, since_epoch=150), "real")
        self.assertTrue(ts.started_with_prompt("real", PROMPT))
        self.assertFalse(ts.started_with_prompt("old-focus", PROMPT))

    def test_a_session_that_only_repeats_the_prompt_later_is_not_the_launch(self):
        db([("chat", "user", "Discuss PR #348", 100.0), ("chat", "user", PROMPT, 300.0)])
        self.assertIsNone(ts.find_prompt_session(PROMPT, since_epoch=0))
        self.assertFalse(ts.started_with_prompt("chat", PROMPT))

    def test_the_newest_launch_wins_and_since_filters_older_ones(self):
        db([("a", "user", PROMPT, 100.0), ("b", "user", PROMPT, 200.0)])
        self.assertEqual(ts.find_prompt_session(PROMPT, since_epoch=0), "b")
        self.assertIsNone(ts.find_prompt_session(PROMPT, since_epoch=250))

    def test_nothing_persisted_yet_is_none(self):
        db([("a", "user", "something else", 100.0)])
        self.assertIsNone(ts.find_prompt_session(PROMPT))
        self.assertIsNone(ts.find_prompt_session(""))
        self.assertFalse(ts.started_with_prompt("", PROMPT))

    def test_an_unreadable_database_is_none(self):
        (TMP / "state.db").write_text("not a database")
        self.assertIsNone(ts.find_prompt_session(PROMPT))
        self.assertFalse(ts.started_with_prompt("a", PROMPT))
        (TMP / "state.db").unlink()
        self.assertIsNone(ts.find_prompt_session(PROMPT))


if __name__ == "__main__":
    unittest.main()
