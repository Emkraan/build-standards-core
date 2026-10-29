"""
platform_reviews_needs_me_rows_test.py
Purpose: and tests. "Just acted on" names a plan-run approval as a plan approval and
         flags it when the PR still waits on the owner's sign-off. Every Needs me item becomes one Action
         Center row, the same items counts.needs_me adds up. Synthetic data, scratch state dirs.
Run:     /usr/bin/python3 platform_reviews_needs_me_rows_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="oprev-rows-"))
for _d in ("", "../../lanes", "../../engine"):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), _d))

import platform_reviews as o  # noqa: E402
import platform_reviews_testenv as te  # noqa: E402
import review_acted as ra  # noqa: E402

_ENV = {
    "OPRG_CACHE_DIR": str(TMP / "cache"),
    "OPRG_STATE_DIR": str(TMP / "state"),
    "TFGATE_STATE_DIR": str(TMP / "tfstate"),
    "TFGATE_CACHE_DIR": str(TMP / "tfcache"),
    "REVIEW_ACTED_STORE": str(TMP / "review-acted.json"),
}


def setUpModule():
    te.apply(_ENV, TMP)


def tearDownModule():
    te.restore()


def _tomb(pr, outcome, note):
    return {
        pr: {
            "repo": "x/y",
            "pr": pr,
            "head": "a" * 40,
            "outcome": outcome,
            "note": note,
            "title": "t",
            "at": time.time(),
        }
    }


class JustActedTest(unittest.TestCase):
    def test_plan_only_approval_is_named_as_a_plan_approval(self):
        self.assertEqual(ra.approved_what("approved 1 terraform-plan run(s)"), "plan")
        self.assertEqual(
            ra.approved_what("approved 2 terraform-plan run(s); approved 1 terraform-plan run(s)"),
            "plan",
        )

    def test_pr_approval_is_named_as_a_pr_approval(self):
        self.assertEqual(
            ra.approved_what("approved review; merge queued; approved 1 terraform-plan run(s)"),
            "pr",
        )
        self.assertEqual(ra.approved_what("ECR override"), "pr")
        self.assertEqual(ra.approved_what(""), "pr")

    def test_plan_approval_on_a_pr_still_waiting_on_me_says_so(self):
        rows = ra.public(_tomb(490, "approved", "approved 1 terraform-plan run(s)"), {490}, {490})
        self.assertEqual(rows[0]["what"], "plan")
        self.assertTrue(rows[0]["still_needs_me"])

    def test_approval_with_no_open_card_is_not_flagged(self):
        rows = ra.public(_tomb(490, "approved", "approved review; merge queued"), {490}, set())
        self.assertEqual(rows[0]["what"], "pr")
        self.assertFalse(rows[0]["still_needs_me"])

    def test_merge_rows_never_carry_approval_fields(self):
        rows = ra.public(_tomb(12, "merged", ""), set(), {12})
        self.assertIsNone(rows[0]["what"])
        self.assertFalse(rows[0]["still_needs_me"])
        self.assertTrue(rows[0]["confirmed"])

    def test_old_callers_without_needs_me_still_work(self):
        rows = ra.public(_tomb(7, "approved", "approved 1 terraform-plan run(s)"))
        self.assertFalse(rows[0]["still_needs_me"])


class NeedsMeRowsTest(unittest.TestCase):
    def test_one_row_per_counted_item(self):
        need = [
            {"pr": 492, "title": "dispatch", "sources": ["tfplan"]},
            {"pr": 300, "title": "eng", "sources": ["lane"]},
        ]
        mine = [
            {"pr": 490, "title": "gateway", "hold": {"kind": "policy"}},
            {"pr": 491, "title": "dir", "hold": {"kind": "direction", "decision": {"q": "x"}}},
            {"pr": 493, "title": "risk", "hold": {"kind": "problem"}, "can_accept_risk": True},
        ]
        priv = [
            {"pr": {"number": 77}, "workflow_name": "terraform-apply", "env_label": "Production"}
        ]
        owner = [{"name": "state-backend", "tier": "dev"}]
        rel = [{"pr": 88, "title": "runbooks"}]
        rows = o.needs_me_rows(need, mine, priv, owner, rel)
        self.assertEqual(len(rows), len(need) + len(mine) + len(priv) + len(owner) + len(rel))
        by = {(r["kind"], r["pr"]): r["what"] for r in rows}
        self.assertEqual(by[("plan", 492)], "Approve its terraform plan run")
        self.assertEqual(by[("review", 300)], "Review the escalated PR")
        self.assertEqual(by[("mine", 490)], "Approve and merge (the owner's PR, held by policy)")
        self.assertEqual(by[("mine", 491)], "Give the decision it asks for")
        self.assertEqual(by[("mine", 493)], "Accept the risk")
        self.assertEqual(by[("privileged", 77)], "Approve the Production run")
        self.assertEqual(by[("owner", None)], "Owner apply only the owner can run")
        self.assertEqual(by[("release", 88)], "Release its runbook deletes")

    def test_nothing_waiting_means_no_rows(self):
        self.assertEqual(o.needs_me_rows([], [], [], [], []), [])

    def test_missing_fields_never_raise(self):
        rows = o.needs_me_rows([{}], [{}], [{}], [{}], [{}])
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[1]["what"], "Remove the hold label")


if __name__ == "__main__":
    unittest.main()
