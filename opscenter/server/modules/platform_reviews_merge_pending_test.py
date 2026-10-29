"""
platform_reviews_merge_pending_test.py
Purpose: live-actions rule 1.9 on the the plan repo lane. An approval the backend accepts for later (merge
         queue, auto-merge) is a pending state, not a removal: the row moves to the in-flight list
         with no actions, it leaves when a direct read shows the end state, and a PR that is ejected
         from the queue comes back with its actions. Fakes only: a scratch queue file, a fake live
         read (live_truth.pr_state), a fake gh. No network and no live state.
Run:     python3 platform_reviews_merge_pending_test.py
Date:    2026-10-27
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TMP = Path(tempfile.mkdtemp(prefix="oprev-pending-"))
for _d in ("", "../../lanes", "../../engine"):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), _d))

import live_truth  # noqa: E402
import platform_reviews as o  # noqa: E402
import platform_reviews_testenv as te  # noqa: E402
import review_acted  # noqa: E402

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


HEAD = "a" * 40
PR = 77


def queue_item(status="approved", pending=True, head=HEAD):
    it = {
        "pr": PR,
        "title": "Fixture PR",
        "author": "engineer",
        "url": "https://example.invalid/pull/77",
        "head_sha": head,
        "status": status,
        "updated": "2026-10-27T10:00:00Z",
        "escalated_at": "2026-10-27T09:00:00Z",
        "escalation": {},
        "shipped_at": "2026-10-27T10:00:00Z",
    }
    if pending:
        it["merge_pending"] = {
            "kind": "queued",
            "head": HEAD,
            "text": "in merge queue (position 2)",
            "position": 2,
            "at": "2026-10-27T10:00:00Z",
        }
    return it


class Base(unittest.TestCase):
    def setUp(self):
        (TMP / "state").mkdir(exist_ok=True)
        (TMP / "cache").mkdir(exist_ok=True)
        for f in TMP.glob("review-acted*"):
            f.unlink()
        self.pr_state = None
        self.patches = [
            mock.patch.object(live_truth, "pr_state", lambda repo, pr: self.pr_state),
            mock.patch.object(live_truth, "pr_heads", lambda repo: {PR: HEAD}),
            mock.patch.object(o.tf_reviews, "get", lambda: {"pending": [], "queue_updated": None}),
            mock.patch.object(o, "my_prs", lambda *a, **k: []),
            mock.patch.object(o, "_own_shipped", lambda now: []),
            mock.patch.object(
                o.privileged_reviews, "get", lambda: {"pending": [], "recent": [], "health": {}}
            ),
            mock.patch.object(o.owner_roots, "get", lambda: {"items": [], "running": False}),
            mock.patch.object(o.runbook_releases, "items", lambda: []),
            mock.patch.object(o.maintenance_hold, "held_cards", lambda *a, **k: []),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def put_queue(self, item):
        (TMP / "state" / "queue.json").write_text(json.dumps({"items": {str(PR): item}}))

    @staticmethod
    def prs(rows):
        return sorted(r.get("pr") for r in rows)


class MergeQueuePending(Base):
    def test_queued_result_renders_the_pending_state(self):
        # core-rule: live-actions.1.9
        self.put_queue(queue_item())
        self.pr_state = {
            "state": "OPEN",
            "head_sha": HEAD,
            "in_queue": True,
            "auto_merge": False,
            "position": 2,
        }
        d = o.get()
        self.assertEqual(self.prs(d["needs_in_flight"]), [PR], "an in-flight row, not a removal")
        row = d["needs_in_flight"][0]
        self.assertEqual(
            row["phase"],
            "in_flight",
            "the same locked phase the app already renders with a live tag",
        )
        self.assertEqual(row["merge_pending"]["state"], "pending")
        self.assertIn("merge queue (position 2)", row["blocked"])
        self.assertEqual(d["needs_me"], [], "no actions: it is not on the actionable list")
        self.assertEqual(d["counts"]["needs_me"], 0, "and it is not counted as waiting on me")
        self.assertEqual(self.prs(d["shipped"]), [], "it is not shipped before the end state")

    def test_the_tombstone_does_not_hide_the_pending_row(self):
        # core-rule: live-actions.1.9
        review_acted.record(
            o._repo(), PR, HEAD, "approved", "in merge queue (position 2)", title="Fixture PR"
        )
        self.put_queue(queue_item())
        self.pr_state = {
            "state": "OPEN",
            "head_sha": HEAD,
            "in_queue": True,
            "auto_merge": False,
            "position": 1,
        }
        d = o.get()
        self.assertEqual(self.prs(d["needs_in_flight"]), [PR])

    def test_the_end_state_removes_it(self):
        # core-rule: live-actions.1.9
        self.put_queue(queue_item())
        self.pr_state = {
            "state": "MERGED",
            "head_sha": HEAD,
            "in_queue": False,
            "auto_merge": False,
            "position": None,
        }
        d = o.get()
        self.assertEqual(
            d["needs_in_flight"], [], "a direct read shows merged, the pending row is gone"
        )
        self.assertEqual(d["needs_me"], [])
        self.assertEqual(self.prs(d["shipped"]), [PR], "and it is shipped")

    def test_an_unreadable_pr_stays_pending(self):
        # core-rule: live-actions.1.9
        self.put_queue(queue_item())
        self.pr_state = None
        d = o.get()
        self.assertEqual(
            self.prs(d["needs_in_flight"]), [PR], "unknown never hides it and never ships it"
        )
        self.assertEqual(d["needs_me"], [])

    def test_ejected_from_the_queue_brings_the_actions_back(self):
        # core-rule: live-actions.1.9
        self.put_queue(queue_item())
        self.pr_state = {
            "state": "OPEN",
            "head_sha": HEAD,
            "in_queue": False,
            "auto_merge": False,
            "position": None,
        }
        d = o.get()
        self.assertEqual(d["needs_in_flight"], [])
        self.assertEqual(self.prs(d["needs_me"]), [PR], "back on Needs me with its actions")
        row = d["needs_me"][0]
        self.assertEqual(row["phase"], "needs_me")
        self.assertTrue(row["merge_error"], "the row says why it came back")
        self.assertEqual(d["counts"]["needs_me"], 1)

    def test_ejected_with_a_fresh_tombstone_is_not_hidden(self):
        # core-rule: live-actions.1.9
        review_acted.record(o._repo(), PR, HEAD, "approved", "in merge queue", title="Fixture PR")
        self.put_queue(queue_item())
        self.pr_state = {
            "state": "OPEN",
            "head_sha": HEAD,
            "in_queue": False,
            "auto_merge": False,
            "position": None,
        }
        self.assertEqual(self.prs(o.get()["needs_me"]), [PR])

    def test_a_new_push_is_new_work_not_pending(self):
        self.put_queue(queue_item())
        self.pr_state = {
            "state": "OPEN",
            "head_sha": "b" * 40,
            "in_queue": False,
            "auto_merge": False,
            "position": None,
        }
        d = o.get()
        self.assertEqual(d["needs_in_flight"], [])

    def test_an_approval_that_was_not_queued_later_is_unchanged(self):
        # no merge_pending record (merged at once, or an older item): the shipped path as before
        self.put_queue(queue_item(pending=False))
        d = o.get()
        self.assertEqual(d["needs_in_flight"], [])
        self.assertEqual(self.prs(d["shipped"]), [PR])


class ApproveRecordsPending(Base):
    """decide() writes the pending record only when the merge was accepted for later."""

    def approve(self, item, enqueue_result):
        self.put_queue(item)
        live = {
            "state": "open",
            "head": {"sha": HEAD},
            "user": {"login": "engineer"},
            "title": "Fixture PR",
        }
        for p in (
            mock.patch.object(o, "_gh", lambda *a, **k: live if a and a[0][0] == "api" else ""),
            mock.patch.object(o, "_live_downtime", lambda pr, head: {"downtime": False}),
            mock.patch.object(o, "dep_guard", lambda *a, **k: None),
            mock.patch.object(o, "_thread_gate", lambda *a, **k: None),
            mock.patch.object(o, "_needs_override", lambda *a, **k: False),
            mock.patch.object(o, "_engineer_signoff", lambda *a, **k: []),
            mock.patch.object(o.merge_queue, "enqueue", lambda *a, **k: enqueue_result),
        ):
            p.start()
            self.addCleanup(p.stop)
        r = o.decide({"pr": PR, "head_sha": HEAD}, "approve")
        return r, json.loads((TMP / "state" / "queue.json").read_text())["items"][str(PR)]

    def test_queued_approval_stores_the_pending_record(self):
        # core-rule: live-actions.1.9
        _, it = self.approve(
            queue_item(status="escalated", pending=False),
            {"ok": True, "status": "queued", "position": 3, "text": "in merge queue (position 3)"},
        )
        self.assertEqual(it["status"], "approved")
        self.assertEqual(it["merge_pending"]["kind"], "queued")
        self.assertEqual(it["merge_pending"]["head"], HEAD)
        self.assertEqual(it["merge_pending"]["position"], 3)

    def test_an_already_merged_result_is_not_pending(self):
        _, it = self.approve(
            queue_item(status="escalated", pending=False),
            {"ok": True, "status": "merged", "position": None, "text": "already merged"},
        )
        self.assertNotIn("merge_pending", it)

    def test_an_ejected_item_accepts_the_approve_again(self):
        # core-rule: live-actions.1.9
        r, it = self.approve(
            queue_item(),  # approved with a pending record, now ejected from the queue
            {"ok": True, "status": "queued", "position": 1, "text": "in merge queue (position 1)"},
        )
        self.assertIn("in merge queue (position 1)", " ".join(r["done"]))
        self.assertEqual(it["merge_pending"]["position"], 1)

    def test_an_approved_item_without_a_pending_record_still_has_nothing_waiting(self):
        with self.assertRaises(o.ReviewError) as cm:
            self.approve(
                queue_item(pending=False),
                {"ok": True, "status": "queued", "position": 1, "text": "x"},
            )
        self.assertEqual(cm.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
