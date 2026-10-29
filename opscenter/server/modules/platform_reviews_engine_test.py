"""
platform_reviews_engine_test.py
Purpose: Tests for the engine-check failure handling in platform_reviews.py. A fake
         engine script stands in for platform_pr_review.py, and OPRG_CACHE_DIR points at a
         temp dir, so nothing touches GitHub or the real cache.
Date:    2026-10-13
Run:     python3 platform_reviews_engine_test.py
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="oprev-engine-"))
for _d in ("", "../../lanes", "../../engine"):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), _d))

import platform_reviews as o  # noqa: E402
import platform_reviews_testenv as te  # noqa: E402

_ENV = {
    "TFGATE_STATE_DIR": str(Path(TMP) / "tfstate"),
    "TFGATE_CACHE_DIR": str(Path(TMP) / "tfcache"),
    "OPRG_CACHE_DIR": str(TMP / "cache"),
    "OPRG_STATE_DIR": str(TMP / "state"),
}


def setUpModule():
    import copy

    cfg = copy.deepcopy(te.CONFIG)
    cfg["platform"]["review_script_path"] = str(FAKE)
    te.apply(_ENV, TMP, cfg)


def tearDownModule():
    te.restore()


HEAD = "a" * 40
OTHER = "b" * 40
FAKE = TMP / "fake_engine.py"
MODE = TMP / "mode.txt"
FAKE.write_text(
    "import json, sys, time\n"
    f"mode = open({str(MODE)!r}).read().strip()\n"
    "if mode == 'fail':\n"
    "    sys.stderr.write('gh: HTTP 502 Bad Gateway\\n'); sys.exit(1)\n"
    "if mode == 'garbage':\n"
    "    print('not json'); sys.exit(0)\n"
    "if mode == 'slow':\n"
    "    time.sleep(5)\n"
    "checks = {'green': True}\n"
    "mpr = None\n"
    "if mode == 'mainpend':\n"
    "    mpr = 'main not applied: 1 destroy or replace in escalations platform are main pending change, waits on main terraform-apply run 111 (failed)'\n"
    "if mode == 'covred':\n"
    "    checks = {'green': False, 'red': ['terraform-drift/coverage (platform)'], 'pending': []}\n"
    "escs, threads = [], 0\n"
    "if mode in ('policy', 'mixed'):\n"
    "    escs = [{'rule': 'github-dir', 'where': '.github/x.yml', 'detail': '', 'fp': 'f1', 'cfp': 'c1', 'path': '.github/x.yml'}]\n"
    "if mode == 'mixed':\n"
    "    checks = {'green': False, 'red': ['CI/lint'], 'pending': []}\n"
    "    threads = 1\n"
    f"print(json.dumps({{'head_sha': {HEAD!r}, 'unresolved_threads': threads, 'escalations': escs,\n"
    "                  'checks': checks, 'mergeable': 'MERGEABLE', 'plan': {}, 'main_pending_reason': mpr}))\n"
)


def mode(m):
    MODE.write_text(m)


def item():
    return {
        "pr": 7,
        "head_sha": HEAD,
        "auto_merge": {"status": "held", "reason": "needs me: plan-destroy"},
    }


class EngineCheck(unittest.TestCase):
    def setUp(self):
        o.ENGINE_TIMEOUT_S = 180
        (Path(TMP) / "tfstate" / "pr-signoffs.json").unlink(
            missing_ok=True
        )  # tests here record sign-offs
        # These cases flip the fake engine's mode between calls, so no memo reuse here.
        o.ENGINE_CACHE_S = 0
        o._ENGINE_MEMO.clear()
        o.ENGINE_FAILS.unlink(missing_ok=True)

    def test_success_returns_output_and_clears(self):
        mode("fail")
        o._engine_check(7, HEAD)
        mode("ok")
        self.assertEqual(o._engine_check(7, HEAD)["head_sha"], HEAD)
        self.assertIsNone(o.engine_failure(7, HEAD))

    def test_failure_records_rc_and_stderr(self):
        mode("fail")
        self.assertIsNone(o._engine_check(7, HEAD))
        f = o.engine_failure(7, HEAD)
        self.assertEqual(f["count"], 1)
        self.assertIn("exit 1", f["reason"])
        self.assertIn("502 Bad Gateway", f["reason"])

    def test_garbage_output_is_a_failure(self):
        mode("garbage")
        self.assertIsNone(o._engine_check(7, HEAD))
        self.assertIn("no usable output", o.engine_failure(7, HEAD)["reason"])

    def test_timeout_is_a_failure(self):
        mode("slow")
        o.ENGINE_TIMEOUT_S = 1
        self.assertIsNone(o._engine_check(7, HEAD))
        self.assertIn("timed out after 1s", o.engine_failure(7, HEAD)["reason"])

    def test_streak_resets_on_new_head(self):
        mode("fail")
        o._engine_check(7, HEAD)
        o._engine_check(7, HEAD)
        self.assertEqual(o.engine_failure(7, HEAD)["count"], 2)
        o._engine_check(7, OTHER)
        self.assertIsNone(o.engine_failure(7, HEAD))
        self.assertEqual(o.engine_failure(7, OTHER)["count"], 1)

    def test_hold_waits_on_first_failure_then_says_why(self):
        mode("fail")
        h1 = o._hold_base(item())
        self.assertEqual(h1["kind"], "waiting")
        h2 = o._hold_base(item())
        self.assertEqual(h2["kind"], "problem")
        self.assertIn("failed 2 times in a row", h2["summary"])
        self.assertIn("502 Bad Gateway", h2["summary"])
        self.assertNotIn(";", h2["summary"] + h2["next"])
        self.assertNotIn("\u2014", h2["summary"] + h2["next"])

    def test_hold_head_mismatch_still_waits(self):
        mode("ok")
        it = item()
        it["head_sha"] = OTHER
        self.assertEqual(o._hold_base(it)["kind"], "waiting")

    def test_hold_policy_when_check_passes(self):
        mode("ok")
        self.assertEqual(o._hold_base(item())["kind"], "policy")

    def test_main_pending_in_the_live_check_has_no_merge_button(self):
        # the lane still says needs me, but the live check sees main's own unapplied change.
        mode("mainpend")
        h = o._hold_base(item())
        self.assertEqual(h["kind"], "waiting")
        self.assertIn("run 111", h["summary"])
        self.assertIn("Needs me", h["next"])
        self.assertEqual(h.get("parked"), "main")
        self.assertNotIn(";", h["summary"] + h["next"])

    def test_lane_main_pending_reasons_wait(self):
        for why in (
            "main not applied: 2 destroy or replace in escalations platform are main's pending change, waits on x",
            "plans predate main's last apply: 2 destroy or replace in escalations platform only main had, re-running the plan",
        ):
            it = item()
            it["auto_merge"] = {"status": "held", "reason": why}
            h = o._hold_base(it)
            self.assertEqual(h["kind"], "waiting", why)
            self.assertNotIn("rules", h)
            self.assertNotIn(";", h["summary"] + h["next"])

    def test_draft_parked_on_gate_shows_the_checks(self):
        # never "needs a fix", never a button, says when the lane checks next.
        it = item()
        it["draft"] = True
        it["auto_merge"] = {
            "status": "held",
            "reason": "draft: gate 1 of 2 met, waiting on real calls refused (94, needs <= 0)",
            "gate": {
                "at": "2026-10-23T01:30:00Z",
                "results": [
                    {"label": "#465 merged and applied on main", "ok": True, "detail": "run 7"},
                    {"label": "real calls refused", "ok": False, "detail": "94, needs <= 0"},
                ],
            },
        }
        h = o._hold_base(it)
        self.assertEqual((h["kind"], h["parked"], h["gate_met"]), ("waiting", "gate", 1))
        self.assertIn("1 of 2 checks pass", h["summary"])
        self.assertIn("every 10 minutes", h["next"])
        self.assertNotIn(";", h["summary"] + h["next"])

    def test_draft_without_gate_says_so(self):
        it = item()
        it["draft"] = True
        it["auto_merge"] = {
            "status": "held",
            "reason": "draft: no gate block, nothing tells the lane when it is ready",
        }
        h = o._hold_base(it)
        self.assertEqual((h["kind"], h["parked"]), ("problem", "nogate"))
        self.assertIn("gate block", h["next"])

    def test_draft_not_seen_by_the_lane_yet(self):
        it = item()
        it["draft"] = True
        it["auto_merge"] = None
        self.assertEqual(o._hold_base(it)["kind"], "waiting")

    def test_parked_draft_plan_line_offers_nothing(self):
        m = {
            "pr": 467,
            "draft": True,
            "waiting": [1, 2],
            "hold": {"plan_wait": True, "plan_line": "approve now"},
        }
        h = o._draft_plan_line(m)["hold"]
        self.assertNotIn("plan_wait", h)
        self.assertIn("nothing to approve now", h["plan_line"])

    def test_coverage_red_the_lane_covered_is_still_a_policy_hold(self):
        # the lane proved the coverage red is only this head's own imports.
        mode("covred")
        it = item()
        it["auto_merge"]["import_covered"] = ["terraform-drift/coverage (platform)"]
        self.assertEqual(o._hold_base(it)["kind"], "policy")

    def test_coverage_red_the_lane_did_not_cover_is_a_problem(self):
        mode("covred")
        h = o._hold_base(item())
        self.assertEqual(h["kind"], "problem")
        self.assertIn("coverage (platform)", h["summary"])


class ApproveMergeRunbooks(unittest.TestCase):
    """Approve and merge records the runbook deletes for the applier route."""

    def setUp(self):
        self.saved = (o._verify_head, o.my_prs, o._gh, o._log, o.runbook_releases.record)
        self.rec = []
        o._verify_head = lambda pr, head: {"user": {"login": o._self()}}
        o._gh = lambda args, timeout=60, raw=False: ""
        o._log = lambda rec: None
        o.runbook_releases.record = lambda *a: self.rec.append(a) or "3 runbook delete(s) wait"

    def tearDown(self):
        o._verify_head, o.my_prs, o._gh, o._log, o.runbook_releases.record = self.saved

    def mine(self, routes):
        hold = {
            "kind": "policy",
            "rules": [{"rule": "plan-destroy"}],
            "destroy_roots": [],
            "destroy_routes": routes,
            "plan_run_id": 900,
        }
        o.my_prs = lambda force=False: [
            {"pr": 7, "head_sha": HEAD, "title": "t", "url": "u", "hold": hold}
        ]

    def test_runbooks_applier_is_recorded(self):
        self.mine([{"tool": "runbooks", "tier": "prod", "route": "applier", "applier": "runbooks"}])
        out = o.approve_merge({"pr": 7, "head_sha": HEAD})
        self.assertEqual(self.rec, [(7, "t", "u", "prod", 900, HEAD)])
        self.assertIn("3 runbook delete(s) wait", out["done"])

    def test_other_routes_are_not_recorded(self):
        self.mine(
            [{"tool": "governance", "tier": "prod", "route": "applier", "applier": "governance"}]
        )
        o.approve_merge({"pr": 7, "head_sha": HEAD})
        self.assertEqual(self.rec, [])

    def test_record_failure_never_fails_the_merge(self):
        self.mine([{"tool": "runbooks", "tier": "prod", "route": "applier", "applier": "runbooks"}])

        def boom(*a):
            raise RuntimeError("gh down")

        o.runbook_releases.record = boom
        out = o.approve_merge({"pr": 7, "head_sha": HEAD})
        self.assertTrue(any("could not record" in d for d in out["done"]))


class EngineMemo(unittest.TestCase):
    def setUp(self):
        o.ENGINE_TIMEOUT_S = 180
        o.ENGINE_CACHE_S = 300
        o._ENGINE_MEMO.clear()

    def tearDown(self):
        o._LIVE.fresh = False
        o._ENGINE_MEMO.clear()

    def test_passing_check_is_reused_on_the_same_head(self):
        mode("ok")
        self.assertEqual(o._engine_check(7, HEAD)["head_sha"], HEAD)
        mode("fail")
        self.assertEqual(o._engine_check(7, HEAD)["head_sha"], HEAD)

    # core-rule: automation-safety.1.4
    def test_live_re_derive_never_uses_the_memo(self):
        mode("ok")
        o._engine_check(7, HEAD)
        mode("fail")
        o._LIVE.fresh = True
        self.assertIsNone(o._engine_check(7, HEAD))

    def test_failure_is_never_memoized(self):
        mode("fail")
        self.assertIsNone(o._engine_check(7, HEAD))
        mode("ok")
        self.assertEqual(o._engine_check(7, HEAD)["head_sha"], HEAD)


class MyPrsStale(unittest.TestCase):
    def setUp(self):
        self.saved = (o._build_my_prs, o.MY_CACHE)
        self.cache = Path(tempfile.mkdtemp()) / "the owner's-prs.json"
        o.MY_CACHE = self.cache
        self.calls = []
        o._build_my_prs = lambda force: self.calls.append(force) or [{"pr": 1, "fresh": True}]

    def tearDown(self):
        o._build_my_prs, o.MY_CACHE = self.saved

    def write(self, age):
        self.cache.write_text(
            json.dumps({"epoch": time.time() - age, "items": [{"pr": 1, "fresh": False}]})
        )

    def test_fresh_cache_is_served(self):
        self.write(10)
        self.assertFalse(o.my_prs()[0]["fresh"])
        self.assertEqual(self.calls, [])

    def test_stale_cache_is_served_and_refreshed_in_the_background(self):
        self.write(120)
        self.assertFalse(o.my_prs()[0]["fresh"])
        for _ in range(50):
            if self.calls:
                break
            time.sleep(0.02)
        self.assertEqual(self.calls, [False])

    def test_too_old_cache_waits_for_a_rebuild(self):
        self.write(o.MY_STALE_MAX_S + 5)
        self.assertTrue(o.my_prs()[0]["fresh"])

    def test_force_always_rebuilds_live(self):
        self.write(1)
        self.assertTrue(o.my_prs(force=True)[0]["fresh"])
        self.assertEqual(self.calls, [True])


class HoldClassifier(unittest.TestCase):
    """pr-review-and-merge.1.9: a policy hold shows the sign-off, a problem (alone or mixed with a policy
    rule) goes to the fixer and never offers a merge."""

    def setUp(self):
        o.ENGINE_TIMEOUT_S = 180
        o.ENGINE_CACHE_S = 0
        o._ENGINE_MEMO.clear()
        self.saved = (o._verify_head, o.my_prs, o._gh, o._log)
        o._verify_head = lambda pr, head: {"user": {"login": o._self()}}
        o._gh = lambda args, timeout=60, raw=False: ""
        o._log = lambda rec: None

    def tearDown(self):
        o._verify_head, o.my_prs, o._gh, o._log = self.saved

    def classify(self, reason, engine="ok"):
        mode(engine)
        it = item()
        it["auto_merge"] = {"status": "held", "reason": reason}
        return o._hold_base(it)

    def approve_offered(self, hold):
        """True when Approve and merge is accepted for this hold, False when it is refused (409)."""
        o.my_prs = lambda force=False: [
            {"pr": 7, "head_sha": HEAD, "title": "t", "url": "u", "hold": hold}
        ]
        try:
            o.approve_merge({"pr": 7, "head_sha": HEAD})
        except o.ReviewError as e:
            self.assertIn("not waiting on a sign-off", str(e))
            return False
        return True

    def test_policy_only_hold_shows_the_sign_off(self):
        # core-rule: pr-review-and-merge.1.9
        h = self.classify("needs me: github-dir", "policy")
        self.assertEqual(h["kind"], "policy")
        self.assertEqual([r["rule"] for r in h["rules"]], ["github-dir"])
        self.assertTrue(self.approve_offered(h))

    def test_problem_only_hold_goes_to_the_fixer_with_no_merge_button(self):
        # core-rule: pr-review-and-merge.1.9
        for reason in ("checks red: CI/lint", "1 blocking finding(s)", "merge conflict with main"):
            h = self.classify(reason)
            self.assertEqual(h["kind"], "problem", reason)
            self.assertNotIn("sign-off", h["summary"].lower(), reason)
            self.assertFalse(self.approve_offered(h), reason)

    def test_mixed_hold_is_a_problem_first_and_never_offers_the_merge(self):
        # core-rule: pr-review-and-merge.1.9
        h = self.classify("needs me: github-dir", "mixed")
        self.assertEqual(h["kind"], "problem")
        self.assertIn("Also held", h["summary"])
        self.assertIn("checks not green: CI/lint", h["summary"])
        self.assertIn("1 unresolved review thread(s)", h["summary"])
        self.assertEqual(
            [r["rule"] for r in h["rules"]], ["github-dir"]
        )  # the policy rule is still named
        self.assertFalse(self.approve_offered(h))


if __name__ == "__main__":
    unittest.main(verbosity=1)
