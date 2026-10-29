"""
maintenance_hold_test.py
Purpose: The review pages' maintenance-window hold against stubs: the Needs me preview, the held cards, Approve on an engineer
         PR that takes a system down outside its window (held, not merged, one comment per head), the emergency override
         from a held card (pinned to the held head, reason required, recorded), and the refusals. gh is a fake that models
         one PR, every path is a temp dir, so nothing touches the code host or real state.
Run:     python3 maintenance_hold_test.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import maintenance_hold as mh  # noqa: E402
import merge_queue  # noqa: E402

merge_queue.READ_DELAY_S = 0
POL = json.loads((HERE / "fixtures" / "maintenance-policy.json").read_text())
POL["maintenance_window"]["enabled"] = True
HEAD, OTHER = "c" * 40, "d" * 40
REPO = "acme/infra"
MONDAY_10_ET = "2026-10-19T14:00:00Z"
MONDAY_22_ET = "2026-10-20T02:00:00Z"
HITS = [
    {
        "kind": "app-deploy",
        "system": "vendor-b",
        "reason": "deploys the vendor-b API, which restarts it",
        "where": "apps/b",
    }
]


def downtime(cls="standard"):
    return {"enabled": True, "downtime": True, "hits": HITS, "class": cls}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.calls, self.log, self.queue = [], [], {}
        self.in_queue = False
        self.live_head = HEAD

        def gh(args, timeout=60, raw=False):
            self.calls.append(list(args))
            if args[:2] == ["api", "graphql"]:
                pr = {
                    "state": "OPEN",
                    "headRefOid": self.live_head,
                    "baseRefName": "main",
                    "isInMergeQueue": self.in_queue,
                    "autoMergeRequest": None,
                    "mergeQueueEntry": {"position": 1, "state": "AWAITING_CHECKS"}
                    if self.in_queue
                    else None,
                    "reviewThreads": {"nodes": []},
                }
                return json.dumps(
                    {"data": {"repository": {"pullRequest": pr, "mergeQueue": {"id": "q"}}}}
                )
            if args[:2] == ["pr", "merge"] and "--auto" in args:
                self.in_queue = True
            return "" if raw else {}

        self.cfg_io = {
            "gh": gh,
            "repo": REPO,
            "log": self.log.append,
            "held_path": d / "held.json",
            "overrides_path": d / "overrides.json",
            "verify_head": lambda pr, head: {"title": "Synthetic", "head": head},
            "set_queue": lambda pr, rec: self.queue.update({pr: rec}),
            "self_login": "owner1",
        }
        self.live = {
            "title": "Synthetic",
            "user": {"login": "engineer1"},
            "html_url": "https://example.invalid/501",
        }

    def tearDown(self):
        os.environ.pop("OPRG_NOW", None)
        self.tmp.cleanup()

    def writes(self):
        return [
            c for c in self.calls if c[:2] in (["pr", "review"], ["pr", "merge"], ["pr", "comment"])
        ]


class Views(Base):
    def test_need_view_outside_the_window_says_held(self):
        os.environ["OPRG_NOW"] = MONDAY_10_ET
        v = mh.need_view(POL, {"downtime": downtime()}, "engineer1", "owner1")
        self.assertTrue(v["held_on_approve"])
        self.assertIn("vendor-b API", v["brief"]["down"])
        self.assertIn("standard window", v["brief"]["down"])
        self.assertIn("emergency override", v["brief"]["override"])

    def test_inside_the_window_it_is_not_held(self):
        os.environ["OPRG_NOW"] = MONDAY_22_ET
        self.assertFalse(
            mh.need_view(POL, {"downtime": downtime()}, "engineer1", "owner1")["held_on_approve"]
        )

    def test_nothing_to_say_for_the_owners_own_pr_a_disabled_policy_or_no_downtime(self):
        item = {"downtime": downtime()}
        self.assertIsNone(mh.need_view(POL, item, "owner1", "owner1"))
        self.assertIsNone(mh.need_view({}, item, "engineer1", "owner1"))
        self.assertIsNone(
            mh.need_view(
                POL, {"downtime": {"enabled": True, "downtime": False}}, "engineer1", "owner1"
            )
        )
        self.assertIsNone(mh.need_view(POL, {}, "engineer1", "owner1"))

    def test_an_unknown_check_waits_for_both_classes(self):
        os.environ["OPRG_NOW"] = MONDAY_10_ET
        v = mh.need_view(POL, {"downtime": {"unknown": True}}, "engineer1", "owner1")
        self.assertTrue(v["unknown"])
        self.assertEqual(v["class"], "both")


class Hold(Base):
    def test_hold_approves_without_merging_and_comments_once_per_head(self):
        os.environ["OPRG_NOW"] = MONDAY_10_ET
        done = mh.hold(self.cfg_io, POL, 501, HEAD, self.live, downtime())
        self.assertIn("approved review", done)
        self.assertIn("posted the window comment", done)
        self.assertEqual([c[:2] for c in self.writes()], [["pr", "review"], ["pr", "comment"]])
        held = json.loads(self.cfg_io["held_path"].read_text())["items"]["501"]
        self.assertEqual(
            (held["head_sha"], held["approved_by"], held["class"]), (HEAD, "owner1", "standard")
        )
        self.calls.clear()
        mh.hold(self.cfg_io, POL, 501, HEAD, self.live, downtime())
        self.assertEqual(
            [c[:2] for c in self.writes()], [["pr", "review"]]
        )  # no second comment for this head
        self.assertEqual(self.log[-1]["decision"], "approved_held_for_window")

    def test_the_comment_never_carries_a_forbidden_word(self):
        self.assertTrue(mh.FORBIDDEN.search("Co-Authored-By: x"))
        self.assertTrue(mh.FORBIDDEN.search("written by an AI"))
        self.assertFalse(mh.FORBIDDEN.search("It merges in the next standard window."))

    def test_held_cards_phase_by_the_live_heads(self):
        os.environ["OPRG_NOW"] = MONDAY_10_ET
        mh.hold(self.cfg_io, POL, 501, HEAD, self.live, downtime())
        path = self.cfg_io["held_path"]
        self.assertEqual(mh.held_cards(POL, path, {501: HEAD})[0]["phase"], "held")
        self.assertEqual(mh.held_cards(POL, path, {501: OTHER})[0]["phase"], "in_flight")
        self.assertEqual(mh.held_cards(POL, path, {})[0]["phase"], "gone")
        self.assertEqual(mh.held_cards(POL, path, None)[0]["phase"], "held")


class Override(Base):
    def held(self):
        os.environ["OPRG_NOW"] = MONDAY_10_ET
        mh.hold(self.cfg_io, POL, 501, HEAD, self.live, downtime())
        self.calls.clear()

    def test_override_queues_the_merge_records_the_reason_and_clears_the_hold(self):
        self.held()
        out = mh.override(
            self.cfg_io, {"pr": 501, "head_sha": HEAD, "reason": "the vendor needs it now"}
        )
        self.assertEqual(out["pr"], 501)
        self.assertIn("emergency override", out["done"][0])
        self.assertEqual(json.loads(self.cfg_io["held_path"].read_text())["items"], {})
        rec = json.loads(self.cfg_io["overrides_path"].read_text())["items"][0]
        self.assertEqual(
            (rec["by"], rec["via"], rec["systems"]), ("owner1", "held-card", ["vendor-b"])
        )
        self.assertEqual(self.log[-1]["decision"], "window_override")
        self.assertEqual(self.queue[501]["status"], "approved")

    def test_refusals(self):
        self.held()
        for payload, code in (
            ({"pr": "x", "head_sha": HEAD, "reason": "long enough reason"}, 400),
            ({"pr": 501, "head_sha": "short", "reason": "long enough reason"}, 400),
            ({"pr": 501, "head_sha": HEAD, "reason": "short"}, 400),
            ({"pr": 501, "head_sha": HEAD, "reason": "x" * 301}, 400),
            ({"pr": 999, "head_sha": HEAD, "reason": "long enough reason"}, 404),
            ({"pr": 501, "head_sha": OTHER, "reason": "long enough reason"}, 409),
        ):
            with self.assertRaises(mh.HoldError) as e:
                mh.override(self.cfg_io, payload)
            self.assertEqual((e.exception.code, e.exception.status), (code, code), payload)
        self.assertFalse([c for c in self.calls if c[:2] == ["pr", "merge"]])
        self.assertIn(
            501, [int(k) for k in json.loads(self.cfg_io["held_path"].read_text())["items"]]
        )


if __name__ == "__main__":
    unittest.main()
