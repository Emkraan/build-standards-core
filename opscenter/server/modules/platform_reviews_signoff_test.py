"""
platform_reviews_signoff_test.py
Purpose: tests for the Ops Center side of one sign-off per PR. Approve and merge records one
         sign-off and approves the plan waits on the same head, and a later head shows a card that
         names only what is new. Synthetic data, a fake engine, scratch state dirs, no GitHub.
Run:     /usr/bin/python3 platform_reviews_signoff_test.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="oprev-signoff-"))
for _d in ("", "../../lanes", "../../engine"):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), _d))

import platform_reviews as o  # noqa: E402
import platform_reviews_testenv as te  # noqa: E402

_ENV = {
    "OPRG_CACHE_DIR": str(TMP / "cache"),
    "OPRG_STATE_DIR": str(TMP / "state"),
    "TFGATE_STATE_DIR": str(TMP / "tfstate"),
    "TFGATE_CACHE_DIR": str(TMP / "tfcache"),
}


def setUpModule():
    te.apply(_ENV, TMP)
    _extra_setup()


def tearDownModule():
    _extra_teardown()
    te.restore()


H1, H2 = "a" * 40, "b" * 40
_REAL_THREAD_GATE = o._thread_gate


def _extra_setup():
    # added a read of the review conversations before any GitHub write. These tests cover
    # the sign-off, so no conversation is open here. review_threads_test.py covers the gate itself.
    o._thread_gate = lambda pr, head, payload: None


def _extra_teardown():
    o._thread_gate = _REAL_THREAD_GATE


HIT1 = {
    "rule": "github-dir",
    "where": ".github/x.yml:3",
    "detail": "d",
    "fp": "f1",
    "cfp": "c1",
    "path": ".github/x.yml",
}
HIT2 = {
    "rule": "rbac-custom-role",
    "where": "a.tf:9",
    "detail": "d",
    "fp": "f2",
    "cfp": "c2",
    "path": "a.tf",
}
PLAN = {
    "ran": True,
    "status": "completed",
    "add": 1,
    "destroy": 0,
    "replace": 0,
    "change": 0,
    "resources": [{"address": "azurerm_resource_group.a", "action": "create"}],
    "roots": [{"job": "terraform plan (a platform)", "conclusion": "success", "parsed": True}],
    "errors": [],
    "destroyed": [],
    "replaced": [],
}


class ApproveMergeSignoff(unittest.TestCase):
    def setUp(self):
        self.saved = (
            o._verify_head,
            o.my_prs,
            o._gh,
            o._log,
            o.runbook_releases.record,
            o.tf_reviews.approve_for_signoff,
        )
        self.logs, self.waits = [], []
        o._verify_head = lambda pr, head: {"user": {"login": o._self()}}
        o._gh = lambda args, timeout=60, raw=False: ""
        o._log = lambda rec: self.logs.append(rec)
        o.tf_reviews.approve_for_signoff = lambda pr, head: (
            self.waits.append((pr, head)) or "approved 2 plan wait(s) with the same sign-off"
        )
        self.so = o.tf_reviews.signoff_mod()
        p = TMP / "tfstate" / "pr-signoffs.json"
        if p.exists():
            p.unlink()

    def tearDown(self):
        (
            o._verify_head,
            o.my_prs,
            o._gh,
            o._log,
            o.runbook_releases.record,
            o.tf_reviews.approve_for_signoff,
        ) = self.saved

    def mine(self, head=H1):
        hold = {
            "kind": "policy",
            "rules": [{"rule": "github-dir"}],
            "signoff_hits": [HIT1, HIT2],
            "signoff_plan": self.so.plan_facts(PLAN),
            "destroy_roots": [],
        }
        o.my_prs = lambda force=False: [
            {"pr": 7, "head_sha": head, "title": "t", "url": "u", "hold": hold}
        ]

    def test_click_records_one_signoff_bound_to_what_i_saw(self):
        self.mine()
        out = o.approve_merge({"pr": 7, "head_sha": H1})
        rec = self.so.active(7, lane=self.so.OWN)
        self.assertEqual(rec["head_sha"], H1)
        self.assertEqual([h["fp"] for h in rec["hits"]], ["f1", "f2"])
        self.assertEqual(rec["plan"]["resources"], [["azurerm_resource_group.a", "create"]])
        self.assertEqual(rec["source"], "approve_merge")
        self.assertEqual(self.logs[-1]["signoff"], rec["id"])
        self.assertTrue(any("plan wait" in d for d in out["done"]))

    def test_click_covers_the_apply_of_the_merged_head_plan(self):
        #
        self.mine()
        o.approve_merge({"pr": 7, "head_sha": H1})
        rec = self.so.active(7, lane=self.so.OWN)
        self.assertTrue(rec["apply_ok"])
        self.assertEqual(rec["plan_head"], H1)
        self.assertIsNone(rec["confirm_name"])

    def test_destroy_plan_without_typed_name_does_not_cover_the_apply(self):
        # the card has no confirm field yet, so destroys and Entra types keep asking
        self.mine()
        hold = o.my_prs()[0]["hold"]
        hold["signoff_plan"] = self.so.plan_facts(DESTROY_PLAN)
        hold["signoff_confirm"] = "apps/foo"
        o.approve_merge({"pr": 7, "head_sha": H1})
        rec = self.so.active(7, lane=self.so.OWN)
        self.assertFalse(rec["apply_ok"])
        self.assertIn("type apps/foo", rec["apply_why"])

    def test_typed_name_covers_it(self):
        self.mine()
        hold = o.my_prs()[0]["hold"]
        hold["signoff_plan"] = self.so.plan_facts(DESTROY_PLAN)
        hold["signoff_confirm"] = "apps/foo"
        o.approve_merge({"pr": 7, "head_sha": H1, "confirm_name": "apps/foo"})
        rec = self.so.active(7, lane=self.so.OWN)
        self.assertTrue(rec["apply_ok"])
        self.assertEqual(rec["confirm_name"], "apps/foo")

    def test_wrong_or_empty_name_does_not_carry(self):
        # the card blocks the button on a wrong or empty name, and the server still records
        # no confirm name for one that reaches it, so the post-merge apply asks again.
        for typed in ("apps/fo", "", "  APPS/FOO "):
            self.mine()
            hold = o.my_prs()[0]["hold"]
            hold["signoff_plan"] = self.so.plan_facts(DESTROY_PLAN)
            hold["signoff_confirm"] = "apps/foo"
            o.approve_merge({"pr": 7, "head_sha": H1, "confirm_name": typed})
            rec = self.so.active(7, lane=self.so.OWN)
            self.assertFalse(rec["apply_ok"], typed)
            self.assertIsNone(rec["confirm_name"], typed)

    def test_typed_name_is_trimmed(self):
        self.mine()
        hold = o.my_prs()[0]["hold"]
        hold["signoff_plan"] = self.so.plan_facts(DESTROY_PLAN)
        hold["signoff_confirm"] = "apps/foo"
        o.approve_merge({"pr": 7, "head_sha": H1, "confirm_name": "  apps/foo "})
        self.assertEqual(self.so.active(7, lane=self.so.OWN)["confirm_name"], "apps/foo")

    def test_plan_detail_carries_the_per_root_rows(self):
        # the card's landing table is built from these rows, not from the model.
        plan = dict(
            PLAN,
            roots=[
                {
                    "job": "terraform plan (a platform)",
                    "root": "a",
                    "tier": "prod",
                    "conclusion": "success",
                    "summary": "Plan: 1 to add, 0 to change, 0 to destroy.",
                }
            ],
            resources=[
                {
                    "root": "a",
                    "tier": "prod",
                    "address": "azurerm_resource_group.a",
                    "action": "create",
                }
            ],
        )
        rows = o._plan_detail(plan)["plan_rows"]
        self.assertEqual(
            [(r["root"], r["tier"], r["add"], r["destroy"]) for r in rows["rows"]],
            [("a", "prod", 1, 0)],
        )
        self.assertEqual(rows["resources"][0]["address"], "azurerm_resource_group.a")
        self.assertIsNone(o._plan_detail({"ran": False}))

    def test_no_plan_does_not_cover_the_apply(self):
        self.mine()
        o.my_prs()[0]["hold"]["signoff_plan"] = None
        o.approve_merge({"pr": 7, "head_sha": H1})
        self.assertFalse(self.so.active(7, lane=self.so.OWN)["apply_ok"])

    def test_click_approves_the_plan_waits_on_that_head_only(self):
        self.mine()
        o.approve_merge({"pr": 7, "head_sha": H1})
        self.assertEqual(self.waits, [(7, H1)])

    def test_store_failure_never_blocks_the_merge(self):
        self.mine()
        s = self.so.record
        self.so.record = lambda *a, **k: (_ for _ in ()).throw(OSError("disk"))
        try:
            out = o.approve_merge({"pr": 7, "head_sha": H1})
        finally:
            self.so.record = s
        self.assertTrue(any("could not record the sign-off" in d for d in out["done"]))
        self.assertTrue(out["done"][0].startswith("approved and merged"))

    def test_wait_failure_never_blocks_the_merge(self):
        self.mine()
        o.tf_reviews.approve_for_signoff = lambda pr, head: (_ for _ in ()).throw(
            RuntimeError("gh")
        )
        out = o.approve_merge({"pr": 7, "head_sha": H1})
        self.assertTrue(any("could not approve the plan waits" in d for d in out["done"]))


class CardNamesOnlyWhatIsNew(unittest.TestCase):
    def setUp(self):
        p = TMP / "tfstate" / "pr-signoffs.json"
        if p.exists():
            p.unlink()
        self.so = o.tf_reviews.signoff_mod()
        self.item = {"pr": 7, "head_sha": H2}
        self.rules = [{"rule": h["rule"], "plain": h["rule"] + " plain"} for h in (HIT1, HIT2)]

    def card(self, escs, plan=PLAN):
        rules = [{"rule": e["rule"], "plain": e["rule"] + " plain"} for e in escs]
        return o._signoff_card(
            self.item, {}, escs, rules, plan, {"kind": "policy", "summary": "s", "rules": rules}
        )

    def test_no_signoff_shows_the_full_card_and_what_a_click_will_record(self):
        h = self.card([HIT1, HIT2])
        self.assertEqual(len(h["rules"]), 2)
        self.assertEqual(len(h["signoff_hits"]), 2)
        self.assertEqual(h["signoff_plan"]["resources"], [["azurerm_resource_group.a", "create"]])
        self.assertNotIn("new_since", h)

    def test_new_hit_card_names_only_the_new_one(self):
        self.so.record(7, H1, self.so.OWN, "approve_merge", [HIT1], self.so.plan_facts(PLAN))
        h = self.card([HIT1, HIT2])
        self.assertEqual([r["rule"] for r in h["rules"]], ["rbac-custom-role"])
        self.assertEqual(h["carried_rules"], ["github-dir plain"])
        self.assertEqual(h["new_since"], H1)
        self.assertIn(f"compare/{H1}...{H2}", h["compare_url"])
        self.assertIn("rbac-custom-role plain", h["summary"])
        self.assertNotIn("github-dir plain", h["summary"])
        for bad in (";", "\u2014"):
            self.assertNotIn(bad, h["summary"])

    def test_new_plan_destroy_is_named_in_the_card(self):
        self.so.record(7, H1, self.so.OWN, "approve_merge", [HIT1], self.so.plan_facts(PLAN))
        destroy = dict(
            PLAN,
            destroy=1,
            destroyed=["azurerm_x.y"],
            resources=PLAN["resources"] + [{"address": "azurerm_x.y", "action": "delete"}],
        )
        h = self.card([HIT1], destroy)
        self.assertEqual(h["kind"], "policy")
        self.assertIn("destroys azurerm_x.y", h["summary"])

    def test_everything_covered_becomes_a_waiting_card_not_a_click(self):
        self.so.record(7, H1, self.so.OWN, "approve_merge", [HIT1, HIT2], self.so.plan_facts(PLAN))
        h = self.card([HIT1])
        self.assertEqual(h["kind"], "waiting")
        self.assertIn("covers every held change", h["summary"])

    def test_rejected_signoff_is_not_used(self):
        self.so.record(7, H1, self.so.OWN, "approve_merge", [HIT1], None)
        self.so.revoke(7)
        h = self.card([HIT1])
        self.assertNotIn("new_since", h)

    def test_error_leaves_the_full_card(self):
        s = self.so.active
        self.so.active = lambda *a, **k: (_ for _ in ()).throw(ValueError("x"))
        try:
            h = self.card([HIT1])
        finally:
            self.so.active = s
        self.assertEqual(h["kind"], "policy")
        self.assertIn("signoff_error", h)


DESTROY_PLAN = dict(
    PLAN,
    destroy=1,
    destroyed=["azurerm_x.y"],
    resources=[{"address": "azurerm_x.y", "action": "delete", "root": "apps/foo"}]
    + PLAN["resources"],
)


class EngineerSignoff(unittest.TestCase):
    """the owner's approval of an engineer PR is the one sign-off, with the confirm name moved here."""

    def setUp(self):
        self.saved = (
            o._engine_check,
            o._verify_head,
            o._gh,
            o._log,
            o.dep_guard,
            o._live_downtime,
            o._needs_override,
            o.tf_reviews.get,
            o.tf_reviews.decide,
            o.review_acted.record,
        )
        self.calls, self.engine = [], {"plan": PLAN, "escalations": [HIT1]}
        o._engine_check = lambda n, head=None: self.engine
        o._verify_head = lambda pr, head: {"user": {"login": "alice"}, "title": "t"}
        o._gh = lambda args, timeout=60, raw=False: (
            self.calls.append(args) or {"user": {"login": "alice"}}
        )
        o._log = lambda rec: None
        o.dep_guard = lambda pr, payload: None
        o._live_downtime = lambda pr, head: {"downtime": False}
        o._needs_override = lambda pr, head: False
        o.tf_reviews.get = lambda: {
            "pending": [{"pr": 7, "head_sha": H1, "hits": [HIT2]}],
            "parked": [],
        }
        o.tf_reviews.decide = lambda pr, state, **k: {"runs": [1, 2]}
        o.review_acted.record = lambda *a, **k: None
        self.so = o.tf_reviews.signoff_mod()
        p = TMP / "tfstate" / "pr-signoffs.json"
        if p.exists():
            p.unlink()
        q = o.QUEUE
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_text(
            json.dumps(
                {"items": {"7": {"status": "escalated", "head_sha": H1, "escalations": [HIT1]}}}
            )
        )

    def tearDown(self):
        (
            o._engine_check,
            o._verify_head,
            o._gh,
            o._log,
            o.dep_guard,
            o._live_downtime,
            o._needs_override,
            o.tf_reviews.get,
            o.tf_reviews.decide,
            o.review_acted.record,
        ) = self.saved

    def test_approve_records_an_engineer_signoff_bound_to_hits_and_plan(self):
        out = o.decide({"pr": 7, "head_sha": H1}, "approve")
        rec = self.so.active(7, lane=self.so.ENGINEER, head_sha=H1)
        self.assertEqual({h["rule"] for h in rec["hits"]}, {"github-dir", "rbac-custom-role"})
        self.assertTrue(rec["apply_ok"])
        self.assertEqual(rec["plan"]["resources"], [["azurerm_resource_group.a", "create"]])
        self.assertTrue(any("recorded my sign-off" in d for d in out["done"]))
        self.assertTrue(any("plan run" in d for d in out["done"]))

    def test_engineer_signoff_never_covers_another_head(self):
        o.decide({"pr": 7, "head_sha": H1}, "approve")
        self.assertIsNone(self.so.active(7, lane=self.so.ENGINEER, head_sha=H2))
        self.assertIsNone(self.so.active(7, lane=self.so.OWN))

    def test_destroy_plan_without_the_typed_name_does_not_cover_the_apply(self):
        self.engine = {"plan": DESTROY_PLAN, "escalations": []}
        out = o.decide({"pr": 7, "head_sha": H1}, "approve")
        rec = self.so.active(7, lane=self.so.ENGINEER, head_sha=H1)
        self.assertFalse(rec["apply_ok"])
        self.assertIn("type apps/foo", rec["apply_why"])
        self.assertTrue(any("approved review" in d for d in out["done"]))

    def test_wrong_typed_name_does_not_cover_the_apply(self):
        self.engine = {"plan": DESTROY_PLAN, "escalations": []}
        o.decide({"pr": 7, "head_sha": H1, "confirm_name": "other"}, "approve")
        self.assertFalse(self.so.active(7, lane=self.so.ENGINEER, head_sha=H1)["apply_ok"])

    def test_typed_name_covers_the_apply(self):
        self.engine = {"plan": DESTROY_PLAN, "escalations": []}
        o.decide({"pr": 7, "head_sha": H1, "confirm_name": "apps/foo"}, "approve")
        rec = self.so.active(7, lane=self.so.ENGINEER, head_sha=H1)
        self.assertTrue(rec["apply_ok"])
        self.assertEqual(rec["confirm_name"], "apps/foo")

    def test_no_plan_or_a_failed_engine_check_covers_nothing(self):
        self.engine = None
        o.decide({"pr": 7, "head_sha": H1}, "approve")
        self.assertFalse(self.so.active(7, lane=self.so.ENGINEER, head_sha=H1)["apply_ok"])

    def test_request_changes_revokes(self):
        o.decide({"pr": 7, "head_sha": H1}, "approve")
        q = json.loads(o.QUEUE.read_text())
        q["items"]["7"]["status"] = "escalated"
        o.QUEUE.write_text(json.dumps(q))
        o.decide({"pr": 7, "head_sha": H1}, "request-changes")
        self.assertIsNone(self.so.active(7, lane=self.so.ENGINEER, head_sha=H1))

    def test_a_store_failure_never_blocks_the_approval(self):
        r = self.so.record
        self.so.record = lambda *a, **k: (_ for _ in ()).throw(OSError("disk"))
        try:
            out = o.decide({"pr": 7, "head_sha": H1}, "approve")
        finally:
            self.so.record = r
        self.assertTrue(any("could not record the sign-off" in d for d in out["done"]))
        self.assertTrue(any("approved review" in d for d in out["done"]))


if __name__ == "__main__":
    unittest.main(verbosity=1)
