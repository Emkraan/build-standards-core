"""tests: dependency-aware approvals (pr_deps.py).
Synthetic PRs only, modelled on a chain of stacked pull requests. No GitHub call is made.
Run: /usr/bin/python3 pr_deps_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

_tmp = tempfile.mkdtemp()
os.environ.setdefault("PRDEPS_STATE_DIR", _tmp)
os.environ.setdefault("PRDEPS_CACHE_ROOT", _tmp)
os.environ.setdefault("PRDEPS_CACHE_DIR", _tmp)
os.environ.setdefault("PRDEPS_GH_BIN", "/nonexistent/gh")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pr_deps as d  # noqa: E402

MERGED_AT = "2026-10-16T18:00:00Z"
ROOTS = {
    "pipeline-identities": {
        "applied_by": "owner",
        "tiers": {"prod": {"root": "infrastructure/terraform/pipeline-identities"}},
    },
    "policy": {"applied_by": "governance", "tiers": {"prod": {"root": "infrastructure/policy"}}},
}
BODY_349 = "Adding the desktop base.\n\nWaits on #347, which must merge and be Owner-applied first. Until then the plan fails."
BODY_350 = "Entra groups root.\n\nWaits on #348."
BODY_351 = "Routing runbook.\n\nWaits on #347, which must merge and be Owner-applied first. This PR also touches it."


def pr(state="open", **kw):
    base = {"state": state, "title": "t", "url": "u", "head": "a" * 40, "owner_marker": False}
    if state == "merged":
        base.update(merged_at=MERGED_AT, merge_commit="m" * 40)
    base.update(kw)
    return base


def snap(prs, bodies, files=None, applies=None):
    deps = {}
    for n, b in bodies.items():
        p = d.parse_body(b, n)
        if p:
            deps[str(n)] = d.merge_deps(p)
    return {
        "prs": {str(k): v for k, v in prs.items()},
        "deps": deps,
        "files": {str(k): v for k, v in (files or {}).items()},
        "applies": applies or {},
        "roots": ROOTS,
    }


def stack(state347="open", state348="open"):
    prs = {347: pr(state347), 348: pr(state348), 349: pr(), 350: pr(), 351: pr()}
    files = {
        347: [
            "infrastructure/terraform/pipeline-identities/desktop.tf",
            "infrastructure/policy/desktop.tf",
        ]
    }
    return snap(
        prs, {347: "Foundations, no deps.", 349: BODY_349, 350: BODY_350, 351: BODY_351}, files
    )


OWNER_PENDING = [
    {
        "name": "pipeline-identities",
        "tier": "prod",
        "state": "pending",
        "started": "2026-10-16T18:05:00Z",
    }
]
OWNER_APPLIED = [
    {
        "name": "pipeline-identities",
        "tier": "prod",
        "state": "clean",
        "started": "2026-10-16T17:00:00Z",
        "last_apply": {"at": "2026-10-16T18:30:00Z", "verified": True},
    }
]
OWNER_CLEAN_AFTER = [
    {
        "name": "pipeline-identities",
        "tier": "prod",
        "state": "clean",
        "started": "2026-10-16T18:20:00Z",
    }
]
OWNER_CLEAN_BEFORE = [
    {
        "name": "pipeline-identities",
        "tier": "prod",
        "state": "clean",
        "started": "2026-10-16T17:20:00Z",
    }
]


class BodyParse(unittest.TestCase):
    def test_variants(self):
        cases = {
            "Waits on #347.": [(347, "merged")],
            "waits on #12 and #13": [(12, "merged"), (13, "merged")],
            "Lands after #251, #253 and the #254 change.": [
                (251, "merged"),
                (253, "merged"),
                (254, "merged"),
            ],
            "STACKED ON #9": [(9, "merged")],
            "Stacked on top of #9.": [(9, "merged")],
            "Waits on the #348 Graph consent apply in entra-privileged.": [(348, "merged_applied")],
            "Waits on #347, which must merge and be Owner-applied first.": [(347, "owner_applied")],
            "Lands after #5 once its Owner apply is done.": [(5, "owner_applied")],
            "Waiting on #7/#8.": [(7, "merged"), (8, "merged")],
        }
        for body, want in cases.items():
            got = sorted((x["pr"], x["kind"]) for x in d.parse_body(body, 1))
            self.assertEqual(got, sorted(want), body)

    def test_ignores_self_code_blocks_comments_and_plain_mentions(self):
        self.assertEqual(d.parse_body("Waits on #10.", 10), [])
        self.assertEqual(d.parse_body("```\nWaits on #11\n```", 1), [])
        self.assertEqual(d.parse_body("<!-- Waits on #12 -->", 1), [])
        self.assertEqual(
            d.parse_body("#348 merged on 2026-10-16. The only #348 step left is its apply.", 1), []
        )
        self.assertEqual(d.parse_body("", 1), [])

    def test_only_the_same_sentence_sets_the_kind(self):
        got = d.parse_body("Waits on #3. The Owner apply of this PR runs after merge.", 1)
        self.assertEqual([(x["pr"], x["kind"]) for x in got], [(3, "merged")])

    def test_strongest_kind_wins_per_parent(self):
        got = d.parse_body("Lands after #4. Waits on #4, which must be Owner-applied.", 1)
        self.assertEqual([(x["pr"], x["kind"]) for x in got], [(4, "owner_applied")])

    def test_owner_marker(self):
        self.assertTrue(d.owner_marker("Done.\nOwner applied: pipeline-identities 2026-10-16"))
        self.assertTrue(d.owner_marker("<!-- owner-applied -->"))
        self.assertFalse(d.owner_marker("After merge the owner run the Owner apply."))


class StackedChain(unittest.TestCase):
    def test_349_held_while_347_open(self):
        v = d.evaluate(stack(), OWNER_PENDING)[349]
        self.assertEqual(v["first"], [347])
        self.assertEqual(v["waiting"][0]["stage"], "open")
        self.assertTrue(v["lines"][0].startswith("Waiting on #347: "))
        self.assertIn("Owner apply of pipeline-identities (prod)", v["lines"][0])
        self.assertEqual(v["first_line"], "Do this first: #347.")

    def test_349_held_when_347_merged_but_not_owner_applied(self):
        s = stack(state347="merged")
        for owner in (OWNER_PENDING, OWNER_CLEAN_BEFORE, []):
            v = d.evaluate(s, owner).get(349)
            self.assertIsNotNone(v, owner)
            self.assertEqual(v["waiting"][0]["stage"], "owner")
            self.assertIn("Owner apply of pipeline-identities (prod)", v["waiting"][0]["need"])
            self.assertTrue(v["waiting"][0]["need"].startswith("Merged "), v["waiting"][0]["need"])
            self.assertEqual(v["waiting"][0]["step"], "Owner apply")
            self.assertEqual(v["first_line"], "Do this first: #347 Owner apply.")

    def test_stacked_child_names_the_merged_parent_step(self):
        s = stack(state347="merged")
        s["prs"]["361"] = dict(s["prs"]["349"], state="open")
        s["deps"]["361"] = [{"pr": 349, "kind": "merged", "source": "body", "text": ""}]
        v = d.evaluate(s, OWNER_PENDING)[361]
        self.assertEqual(
            v["first_line"],
            "Do this first: #347 Owner apply. Order: #347 Owner apply, then #349, then this PR.",
        )
        self.assertIn("It waits on #347 Owner apply first", v["lines"][0])

    def test_later_successful_main_run_covers_a_failed_merge_run(self):
        runs = {
            "m" * 40: {
                "id": 1,
                "status": "completed",
                "conclusion": "failure",
                "created": "2026-10-16T17:47:00Z",
            },
            "n" * 40: {
                "id": 2,
                "status": "completed",
                "conclusion": "success",
                "created": "2026-10-16T18:27:00Z",
            },
        }
        r = d._apply_for("m" * 40, runs, {})
        self.assertEqual((r["id"], r["covers"]), (2, 1))
        runs["n" * 40]["conclusion"] = "failure"
        self.assertEqual(d._apply_for("m" * 40, runs, {})["id"], 1)

    def test_downstream_of_root_walks_the_chain(self):
        s = stack(state347="merged")
        s["prs"]["361"] = dict(s["prs"]["349"], state="open")
        s["deps"]["361"] = [{"pr": 349, "kind": "merged", "source": "body", "text": ""}]
        self.assertEqual(d.downstream_of_root(349, "pipeline-identities", "prod", s), 347)
        self.assertEqual(d.downstream_of_root(361, "pipeline-identities", "prod", s), 347)
        self.assertIsNone(d.downstream_of_root(361, "state-backend", "prod", s))
        self.assertIsNone(
            d.downstream_of_root(349, "pipeline-identities", "prod", stack())
        )  # #347 still open

    def test_merged_owner_parent_also_owes_its_waiting_main_apply(self):
        s = stack(state347="merged")
        mc = s["prs"]["347"].get("merge_commit") or "c" * 40
        s["prs"]["347"]["merge_commit"] = mc
        s["applies"] = {mc: {"status": "waiting", "conclusion": None}}
        need = d.evaluate(s, OWNER_PENDING)[349]["waiting"][0]["need"]
        self.assertIn(
            "Owner apply of pipeline-identities (prod), then its main terraform-apply (waiting on an approval)",
            need,
        )
        # Owner side done, the pipeline apply still waiting: held on the main apply only.
        w = d.evaluate(s, OWNER_APPLIED)[349]["waiting"][0]
        self.assertEqual((w["stage"], w["step"]), ("apply", "main apply"))
        s["applies"] = {mc: {"status": "completed", "conclusion": "success"}}
        self.assertNotIn(349, d.evaluate(s, OWNER_APPLIED))

    def test_349_clears_on_a_recorded_owner_apply_after_merge(self):
        self.assertNotIn(349, d.evaluate(stack(state347="merged"), OWNER_APPLIED))

    def test_349_clears_on_a_clean_main_plan_after_merge(self):
        self.assertNotIn(349, d.evaluate(stack(state347="merged"), OWNER_CLEAN_AFTER))

    def test_owner_marker_is_the_fallback_only_for_untracked_roots(self):
        s = stack(state347="merged")
        s["files"]["347"] = [
            "infrastructure/policy/desktop.tf"
        ]  # no Owner root the Ops Center plans
        self.assertIn(349, d.evaluate(s, OWNER_PENDING))
        s["prs"]["347"]["owner_marker"] = True
        self.assertNotIn(349, d.evaluate(s, OWNER_PENDING))
        s2 = stack(state347="merged")
        s2["prs"]["347"]["owner_marker"] = True  # a marker never overrides a pending tracked root
        self.assertIn(349, d.evaluate(s2, OWNER_PENDING))

    def test_350_held_while_348_open_and_cleared_once_merged(self):
        self.assertIn(350, d.evaluate(stack(), OWNER_PENDING))
        self.assertNotIn(350, d.evaluate(stack(state348="merged"), OWNER_PENDING))

    def test_351_held_on_347(self):
        v = d.evaluate(stack(state348="merged"), OWNER_PENDING)
        self.assertEqual(v[351]["first"], [347])
        self.assertEqual(sorted(v), [349, 351])

    def test_merged_applied_needs_the_main_apply_run(self):
        s = snap({348: pr("merged"), 350: pr()}, {350: "Waits on the #348 Graph consent apply."})
        mc = "m" * 40
        s["applies"] = {mc: {"status": "in_progress", "conclusion": None}}
        v = d.evaluate(s, [])[350]
        self.assertIn("Still owed: its main terraform-apply (in progress)", v["lines"][0])
        self.assertEqual(v["first_line"], "Do this first: #348 main apply.")
        s["applies"] = {mc: {"status": "completed", "conclusion": "failure"}}
        self.assertIn("ended failure", d.evaluate(s, [])[350]["lines"][0])
        s["applies"] = {mc: {"status": "completed", "conclusion": "success"}}
        self.assertNotIn(350, d.evaluate(s, []))

    def test_need_text_comes_from_the_parent_hold(self):
        mine = [
            {
                "pr": 347,
                "labels": ["do-not-merge"],
                "hold": {"kind": "problem", "summary": "Label do-not-merge."},
            },
            {"pr": 349, "labels": [], "hold": {"kind": "policy", "summary": "s"}},
        ]
        needs = [{"pr": 347, "sources": ["tfplan"]}]
        need = d.evaluate(stack(), OWNER_PENDING, mine, needs)[349]["waiting"][0]["need"]
        self.assertTrue(
            need.startswith(
                "Approve its terraform-plan runs on Needs me, then remove its do-not-merge label"
            )
        )
        self.assertIn("then merge it", need)

    def test_ui_text_has_no_em_dash_or_semicolon(self):
        mine = [
            {"pr": 347, "labels": [], "hold": {"kind": "problem", "summary": "Red checks; lint."}}
        ]
        for s, owner in ((stack(), OWNER_PENDING), (stack(state347="merged"), [])):
            for v in d.evaluate(s, owner, mine).values():
                for line in v["lines"] + [v["first_line"]] + [w["need"] for w in v["waiting"]]:
                    self.assertNotIn("\u2014", line)
                    self.assertNotIn(";", line.replace("Red checks; lint", ""))


class OtherSources(unittest.TestCase):
    def test_branch_ancestry(self):
        commits = {
            360: {"head": "h360", "shas": ["c1", "h360"]},
            361: {"head": "h361", "shas": ["c1", "h360", "h361"]},
            362: {"head": "h362", "shas": ["x", "h362"]},
        }
        self.assertEqual(d.ancestry(commits), {361: [360]})

    def test_destroy_attribution_from_the_lane(self):
        s = snap({370: pr(), 371: pr()}, {})
        mine = [{"pr": 371, "autofix": {"state": "waiting_on", "waits_on": [370]}}]
        v = d.evaluate(s, [], mine)[371]
        self.assertEqual(v["waiting"][0]["sources"], ["destroys"])

    def test_chain_renders_in_order(self):
        s = snap(
            {380: pr(), 381: pr(), 382: pr()}, {381: "Stacked on #380.", 382: "Lands after #381."}
        )
        v = d.evaluate(s, [])[382]
        self.assertEqual(v["chain"], [380, 381])
        self.assertEqual(v["first"], [380])
        self.assertEqual(
            v["first_line"], "Do this first: #380. Order: #380, then #381, then this PR."
        )
        self.assertEqual(v["lines"][0], "Waiting on #381: It waits on #380 first, then merge it.")

    def test_unknown_or_closed_parent_never_holds(self):
        s = snap(
            {390: pr(), 391: pr("unknown"), 392: pr("closed")},
            {390: "Waits on #391 and #392 and #393."},
        )
        self.assertEqual(d.evaluate(s, []), {})

    def test_cycle_does_not_hold_forever(self):
        s = snap({400: pr(), 401: pr()}, {400: "Waits on #401.", 401: "Waits on #400."})
        v = d.evaluate(s, [])
        self.assertEqual(v[400]["first"], [401])

    def test_no_snapshot_holds_nothing(self):
        self.assertEqual(d.evaluate(None, []), {})
        self.assertEqual(d.blocking(349, None, []), [])


if __name__ == "__main__":
    unittest.main()
