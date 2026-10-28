#!/usr/bin/env python3
"""
pr_review_defer_checks.py
Purpose: Tests for defer_escalation() and record() in pr_review.py: an engineer
         PR escalated while the review still has open findings goes to the engineer first and
         reaches Needs me only once a round records it with no real findings open. Synthetic data,
         scratch state dir, gh faked. Never touches GitHub.
Date:    2026-10-20
Run:     /usr/bin/python3 pr_review_defer_checks.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "testing"))
import policy_env  # noqa: E402

STATE_ROOT = (
    policy_env.install()
)  # a scratch state tree holding the policy fixtures, so no live state is read
SCRATCH = tempfile.mkdtemp(prefix="oprdefer-", dir=os.environ.get("TMPDIR"))
os.environ["OPRG_STATE_DIR"] = SCRATCH
os.environ["OPRG_CACHE_DIR"] = SCRATCH
os.environ["OPRG_GH_BIN"] = "/usr/bin/false"
os.environ["OPRG_DRY_RUN"] = "1"

spec = importlib.util.spec_from_file_location("oprg_defer", str(HERE / "pr_review.py"))
eng = importlib.util.module_from_spec(spec)
sys.modules["oprg_defer"] = eng
spec.loader.exec_module(eng)

ESC = {
    "summary": "synthetic",
    "changes": ["functions/demo/app.py -> synthetic behaviour"],
    "rules": [{"rule": "new-app-first-pr", "reason": "x", "where": "functions/demo/"}],
    "risk": {"level": "medium", "why": "synthetic"},
    "recommendation": {"action": "request changes", "why": "synthetic"},
    "plan": "none",
}
BUG = {"where": "functions/demo/app.py:1", "severity": "BUG", "text": "synthetic"}
NIT = {"where": "functions/demo/host.json:1", "severity": "NIT", "text": "synthetic"}


def upd(**kw):
    base = {
        "status": "escalated",
        "escalation": json.loads(json.dumps(ESC)),
        "head_sha": "0" * 40,
        "last_action": "requested changes",
        "downtime": {"enabled": False},
    }
    base.update(kw)
    return base


class DeferTests(unittest.TestCase):
    def test_open_bug_defers(self):
        st, u = eng.defer_escalation(upd(open_findings=1, findings=[BUG]))
        self.assertEqual(st, "changes_requested")
        self.assertNotIn("escalation", u)
        self.assertEqual(u["pending_escalation"]["rules"][0]["rule"], "new-app-first-pr")

    def test_no_open_findings_escalates(self):
        st, u = eng.defer_escalation(upd(open_findings=0, findings=[]))
        self.assertEqual(st, "escalated")
        self.assertIn("escalation", u)

    def test_only_nits_escalates(self):
        st, _ = eng.defer_escalation(upd(open_findings=1, findings=[NIT]))
        self.assertEqual(st, "escalated")

    def test_reject_recommendation_escalates_at_once(self):
        u = upd(open_findings=2, findings=[BUG, BUG])
        u["escalation"]["recommendation"]["action"] = "reject"
        st, _ = eng.defer_escalation(u)
        self.assertEqual(st, "escalated")

    def test_count_without_list_defers(self):
        st, _ = eng.defer_escalation(upd(open_findings=3))
        self.assertEqual(st, "changes_requested")

    def test_record_round_trip(self):
        p = Path(SCRATCH) / "u.json"
        p.write_text(json.dumps(upd(open_findings=1, findings=[BUG])))
        eng.record(9001, str(p))
        it = eng.load_queue()["items"]["9001"]
        self.assertEqual(it["status"], "changes_requested")
        self.assertIn("pending_escalation", it)
        self.assertNotIn("escalated_at", it)
        p.write_text(json.dumps(upd(open_findings=0, findings=[])))
        eng.record(9001, str(p))
        it = eng.load_queue()["items"]["9001"]
        self.assertEqual(it["status"], "escalated")
        self.assertNotIn("pending_escalation", it)
        self.assertIn("escalated_at", it)


if __name__ == "__main__":
    unittest.main(verbosity=1)
