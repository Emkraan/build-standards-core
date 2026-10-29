"""tests: The owner's PRs rows waiting on plan say where the approval really sits.
Synthetic rows only. Run: /usr/bin/python3 platform_reviews_plan_gate_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_tmp = tempfile.mkdtemp()
for _d in ("", "../../lanes", "../../engine"):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), _d))

import platform_reviews as o  # noqa: E402
import platform_reviews_testenv as te  # noqa: E402

_ENV = {
    "TFGATE_STATE_DIR": str(Path(_tmp) / "tfstate"),
    "TFGATE_CACHE_DIR": str(Path(_tmp) / "tfcache"),
    "OPRG_STATE_DIR": _tmp,
    "OPRG_CACHE_DIR": _tmp,
}


def setUpModule():
    te.apply(_ENV, _tmp)


def tearDownModule():
    te.restore()


SHA = "0" * 40


def row(pr=9001, sha=SHA, plan_wait=True):
    hold: dict = {"kind": "waiting", "summary": "old", "next": "Approve the plan runs on Needs me."}
    if plan_wait:
        hold["plan_wait"] = True
    return {"pr": pr, "head_sha": sha, "waiting": ["plan (a)", "plan (b)"], "hold": hold}


class PlanGateText(unittest.TestCase):
    def test_pending_keeps_the_approve_text(self):
        out = o._plan_gate_text([row()], {"pending": [{"pr": 9001, "head_sha": SHA}], "parked": []})
        self.assertEqual(out[0]["hold"]["next"], "Approve the plan runs on Needs me.")
        self.assertNotIn("plan_parked", out[0]["hold"])

    def test_parked_says_why_and_no_click(self):
        tf = {
            "pending": [],
            "parked": [{"pr": 9001, "head_sha": SHA, "why": "session 'X' is working the PR"}],
        }
        h = o._plan_gate_text([row()], tf)[0]["hold"]
        self.assertEqual(h["plan_parked"], "session 'X' is working the PR")
        self.assertIn("2 terraform check(s)", h["summary"])
        self.assertIn("session 'X' is working the PR", h["summary"])
        self.assertTrue(h["next"].startswith("Nothing to click yet"))

    def test_parked_on_an_older_head_does_not_match(self):
        tf = {"pending": [], "parked": [{"pr": 9001, "head_sha": "1" * 40, "why": "w"}]}
        h = o._plan_gate_text([row()], tf)[0]["hold"]
        self.assertNotIn("plan_parked", h)
        self.assertIn("has not taken this run yet", h["summary"])

    def test_not_in_gate_queue_says_gate_has_not_taken_it(self):
        h = o._plan_gate_text([row()], {"pending": [], "parked": []})[0]["hold"]
        self.assertIn("has not taken this run yet", h["summary"])
        self.assertNotIn("Approve", h["next"])

    def test_other_rows_untouched_and_input_not_mutated(self):
        r1, r2 = dict(row(plan_wait=False), waiting=[]), row()
        out = o._plan_gate_text([r1, r2], {"pending": [], "parked": []})
        self.assertIs(out[0], r1)
        self.assertEqual(r2["hold"]["summary"], "old")

    def test_label_hold_row_says_plan_is_on_needs_me(self):
        r = {
            "pr": 9001,
            "head_sha": SHA,
            "waiting": ["plan (a)"],
            "hold": {"kind": "problem", "summary": "Label do-not-merge."},
        }
        h = o._plan_gate_text([r], {"pending": [{"pr": 9001, "head_sha": SHA}], "parked": []})[0][
            "hold"
        ]
        self.assertEqual(h["summary"], "Label do-not-merge.")
        self.assertIn("The card is on Needs me", h["plan_line"])
        self.assertNotIn("plan_line", r["hold"])

    def test_label_hold_row_not_taken_yet(self):
        r = {
            "pr": 9001,
            "head_sha": SHA,
            "waiting": ["plan (a)"],
            "hold": {"kind": "problem", "summary": "Label do-not-merge."},
        }
        h = o._plan_gate_text([r], {"pending": [], "parked": []})[0]["hold"]
        self.assertIn("within 2 minutes", h["plan_line"])

    def test_newest_queue_stamp(self):
        self.assertIsNone(o._newest(None, None))
        self.assertEqual(o._newest(None, "2026-10-15T22:24:58Z"), "2026-10-15T22:24:58Z")
        self.assertEqual(
            o._newest("2026-10-15T22:00:00Z", "2026-10-15T22:24:58Z"), "2026-10-15T22:24:58Z"
        )


if __name__ == "__main__":
    unittest.main()
