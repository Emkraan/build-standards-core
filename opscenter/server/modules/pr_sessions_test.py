"""
pr_sessions_test.py
Purpose: Find a live session that is working a pull request right now: a running delegated task naming the PR (or its branch), a
         live session dedicated to the PR by title, a live session whose recent tool calls work in the branch's worktree or push to
         the branch. Reading or mentioning a PR number is never working it; a finished task, a quiet, ended or cron session does
         not count; a PR number that is only a prefix of another does not match; a configured title pattern is honoured.
Run:     python3 pr_sessions_test.py
"""

import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

TMP = Path(tempfile.mkdtemp())
os.environ["PRSESS_STATE_DB"] = str(TMP / "state.db")
os.environ["PRSESS_DELEG_DIR"] = str(TMP / "deleg")

import pr_sessions as ps  # noqa: E402

BR = "TICKET-5876-platform-app"
WT = "/work/wt-TICKET-5876"


def _db(rows):
    p = TMP / "state.db"
    if p.exists():
        p.unlink()
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE sessions (id TEXT, title TEXT, source TEXT, ended_at REAL)")
    con.execute("CREATE TABLE messages (session_id TEXT, tool_calls TEXT, timestamp REAL)")
    con.execute("CREATE TABLE session_turn_leases (conversation_id TEXT, expires_at REAL)")
    for sid, title, source, ended, calls, age in rows:
        con.execute("INSERT INTO sessions VALUES (?,?,?,?)", (sid, title, source, ended))
        con.execute("INSERT INTO messages VALUES (?,?,?)", (sid, calls, time.time() - age))
    con.commit()
    con.close()


def _deleg(goal, status="running"):
    d = TMP / "deleg" / "d1"
    d.mkdir(parents=True, exist_ok=True)
    (d / "task-0.log").write_text("x")
    (d / "manifest.json").write_text(
        json.dumps({"tasks": [{"goal": goal, "status": status, "log": str(d / "task-0.log")}]})
    )


class Working(unittest.TestCase):
    def setUp(self):
        ps._cache.clear()
        ps._worktrees = lambda repo: {BR: WT}
        for f in (TMP / "deleg").glob("*/manifest.json"):
            f.unlink()
        _db([])
        os.environ.pop("PRSESS_TITLE_PATTERNS", None)

    def test_running_subagent_naming_the_pr(self):
        _deleg("Fix every red check on infra PR #448 (TICKET-5876)")
        w = ps.working("infra", 448, BR)
        self.assertEqual(w["kind"], "subagent")
        self.assertIn("fix session is working on it", w["text"])

    def test_running_subagent_naming_the_branch(self):
        _deleg(f"Rebase {BR} and fix the plan")
        self.assertEqual(ps.working("infra", 448, BR)["kind"], "subagent")

    def test_subagent_other_pr_number_prefix_does_not_match(self):
        _deleg("Fix infra PR #4481")
        self.assertIsNone(ps.working("infra", 448, BR))

    def test_finished_subagent_does_not_count(self):
        _deleg("Fix infra PR #448", status="done")
        self.assertIsNone(ps.working("infra", 448, BR))

    def test_session_editing_in_the_worktree(self):
        _db([("s1", "Tackle: x", "desktop", None, f'{{"command": "cd {WT} && git commit"}}', 30)])
        self.assertEqual(ps.working("infra", 448, BR)["kind"], "session")

    def test_session_pushing_to_the_branch(self):
        _db([("s1", "x", "desktop", None, '{"command": "git push origin HEAD:' + BR + '"}', 30)])
        self.assertEqual(ps.working("infra", 448, BR)["kind"], "session")

    def test_session_only_reading_the_pr_does_not_count(self):
        _db(
            [
                (
                    "s1",
                    "Tackle: x",
                    "desktop",
                    None,
                    '{"command": "gh pr view 448 --json checks"}',
                    30,
                )
            ]
        )
        self.assertIsNone(ps.working("infra", 448, BR))

    def test_quiet_or_cron_or_ended_sessions_do_not_count(self):
        calls = '{"command": "git push origin HEAD:' + BR + '"}'
        _db(
            [
                ("s1", "quiet", "desktop", None, calls, ps.ACTIVE_S + 60),
                ("cron_1", "cron", "cron", None, calls, 10),
                ("s3", "ended", "desktop", 1.0, calls, 10),
            ]
        )
        self.assertIsNone(ps.working("infra", 448, BR))

    def test_discuss_session_by_title(self):
        _db([("s1", "Discuss infra PR #448", "desktop", None, None, 10)])
        self.assertEqual(ps.working("infra", 448, BR)["label"], "Discuss infra PR #448")

    def test_the_title_patterns_are_configurable(self):
        _db([("s1", "Review of 448 for infra", "desktop", None, None, 10)])
        self.assertIsNone(ps.working("infra", 448, BR))
        os.environ["PRSESS_TITLE_PATTERNS"] = json.dumps([r"^Review of {pr} for {repo}$"])
        self.assertEqual(ps.working("infra", 448, BR)["kind"], "session")

    def test_an_unreadable_database_counts_as_nobody(self):
        (TMP / "state.db").write_text("not a database")
        self.assertIsNone(ps.working("infra", 448, BR))


if __name__ == "__main__":
    unittest.main()
