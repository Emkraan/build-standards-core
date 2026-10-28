"""
jira_needs_me_test.py

Purpose: Synthetic-data tests for the Jira hub Needs me tab (needs_me.py). No Jira call,
         work.sprint is patched and both state files live in a scratch directory.
Date:    2026-10-15
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import needs_me as nm  # noqa: E402
import work  # noqa: E402


def _row(key, done=False, mine=True):
    return {
        "key": key,
        "summary": f"Synthetic {key}",
        "status": "Closed" if done else "To Do",
        "status_category": "done" if done else "new",
        "mine": mine,
        "url": work.BROWSE + key,
    }


class NeedsMeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.state = d / "state.json"
        self.dec = d / "decisions.json"
        nm.STATE, nm.DECISIONS = self.state, self.dec
        self.sprint_rows = [
            _row("TKT-9001"),
            _row("TKT-9002"),
            _row("TKT-9003", done=True),
            _row("TKT-9004", mine=False),
        ]
        self.read_fails = False

        def fake_sprint(fresh=False):
            if self.read_fails:
                raise work.TrackerError("synthetic read failure", 502)
            return {"items": self.sprint_rows}

        self._orig = work.sprint
        work.sprint = fake_sprint
        self.triggers = []
        self._orig_run = nm.run_close_out
        nm.run_close_out = lambda: self.triggers.append(1) or ""
        self.write_state(
            {
                "TKT-9001": {
                    "disposition": "held 2026-10-10: x",
                    "needs_me": {"question": "Close on the built pipeline?"},
                },
                "TKT-9002": {"disposition": "held 2026-10-14: not started"},
                "TKT-9003": {"needs_me": {"question": "Closed already", "since": "2026-10-01"}},
                "TKT-9004": {"needs_me": {"question": "Someone else's", "since": "2026-10-01"}},
            }
        )

    def tearDown(self):
        work.sprint = self._orig
        nm.run_close_out = self._orig_run
        self.tmp.cleanup()

    def write_state(self, tickets):
        self.state.write_text(json.dumps({"tickets": tickets}))

    def test_lists_only_open_mine_with_an_ask(self):
        out = nm.items()
        self.assertEqual([r["key"] for r in out["items"]], ["TKT-9001"])
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["items"][0]["since"], "2026-10-10")  # falls back to the held date

    def test_unknown_never_hides(self):
        self.read_fails = True
        out = nm.items()
        self.assertFalse(out["live_ok"])
        self.assertEqual(
            sorted(r["key"] for r in out["items"]), ["TKT-9001", "TKT-9003", "TKT-9004"]
        )

    def test_close_goes_pending_until_applied(self):
        r = nm.decide("TKT-9001", "close", "Close on the built pipeline?", "fine")
        self.assertFalse(r["already"])
        self.assertEqual(self.triggers, [1])  # close fires the close-out at once
        out = nm.items()
        self.assertEqual(out["items"][0]["phase"], "closing")
        self.assertEqual(out["count"], 0)
        st = json.loads(self.state.read_text())
        st["tickets"]["TKT-9001"]["decision_applied"] = {"at": r["decision"]["at"]}
        self.state.write_text(json.dumps(st))
        self.assertEqual(
            nm.items()["items"][0]["phase"], "needs_me"
        )  # applied but still open: ask again

    def test_keep_hides_until_question_changes(self):
        nm.decide("TKT-9001", "keep", "Close on the built pipeline?")
        self.assertEqual(self.triggers, [])  # keep never runs the close-out
        self.assertEqual(nm.items()["items"], [])
        st = json.loads(self.state.read_text())
        st["tickets"]["TKT-9001"]["needs_me"]["question"] = "New reason"
        self.state.write_text(json.dumps(st))
        self.assertEqual([r["key"] for r in nm.items()["items"]], ["TKT-9001"])

    def test_stale_question_is_409(self):
        with self.assertRaises(work.TrackerError) as cm:
            nm.decide("TKT-9001", "close", "an older question")
        self.assertEqual(cm.exception.code, 409)

    def test_not_waiting_is_404_and_closed_is_409(self):
        with self.assertRaises(work.TrackerError) as cm:
            nm.decide("TKT-9002", "close", "")
        self.assertEqual(cm.exception.code, 404)
        with self.assertRaises(work.TrackerError) as cm:
            nm.decide("TKT-9003", "close", "Closed already")
        self.assertEqual(cm.exception.code, 409)

    def test_what_if_and_idempotent_and_undo(self):
        nm.decide("TKT-9001", "close", "Close on the built pipeline?", what_if=True)
        self.assertFalse(self.dec.exists())
        self.assertEqual(self.triggers, [])
        nm.decide("TKT-9001", "close", "Close on the built pipeline?")
        self.assertTrue(nm.decide("TKT-9001", "close", "Close on the built pipeline?")["already"])
        self.assertFalse(nm.decide("TKT-9001", "undo", "")["already"])
        self.assertTrue(nm.decide("TKT-9001", "undo", "")["already"])

    def test_bad_input(self):
        for args in (("TKT-9001", "delete", "q"), ("not a key", "close", "q")):
            with self.assertRaises(work.TrackerError):
                nm.decide(*args)
        with self.assertRaises(work.TrackerError):
            nm.decide("TKT-9001", "close", "Close on the built pipeline?", "x" * (nm.NOTE_MAX + 1))


if __name__ == "__main__":
    unittest.main()
