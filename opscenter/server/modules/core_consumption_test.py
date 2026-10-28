"""
core_consumption_test.py
Purpose: Core consumption panel (standard section 19). Fixture consumption.json rendering assertions
         (one row per consumer, pin, latest, behind, sync PR CI for workflow and vendored rows and
         none for the ops center, status counts or the not_collected reason, adoption risk, the
         account's awaiting and approved-unopened items, peers with new marked), the wrong-format
         error state, a render path with no gh call, the approval controls (absent on the apply-at-once
         row, disabled on a failing PR) and a gh test double that records only pr ready, pr merge and
         issue comment writes and never a git push. Hermetic: a temp feed file, a temp gh double,
         role names only.
Usage:   python3 core_consumption_test.py
Date:    2026-10-21
"""

from __future__ import annotations

import copy
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core_consumption as cc  # noqa: E402
import swr  # noqa: E402

GH_DOUBLE = """#!/usr/bin/env python3
import json, os, sys
d = os.environ["GH_DOUBLE_DIR"]
args = sys.argv[1:]
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps(args) + "\\n")
verb = " ".join(args[:2])
script = json.load(open(os.path.join(d, "script.json")))
if verb in ("pr ready", "pr merge", "issue comment"):
    print("ok")
    sys.exit(0)
if verb in script:
    print(json.dumps(script[verb]))
    sys.exit(0)
sys.stderr.write("double: unexpected gh call " + verb)
sys.exit(97)
"""

GIT_DOUBLE = """#!/usr/bin/env python3
import os, sys
with open(os.path.join(os.environ["GH_DOUBLE_DIR"], "git-calls.txt"), "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
sys.exit(0)
"""

CORE = "example-org/core-role"


def consumer(role, mode, number=None, ci=None, behind=0, pinned="v0.59.0", **extra):
    c = {
        "repo": f"example-org/{role}",
        "label": f"label-{role}",
        "mode": mode,
        "class": "apply-at-once" if mode == "ops-center" else "approval-gated",
        "report_only": False,
        "pinned": pinned,
        "latest": "v0.59.0",
        "behind": behind,
        "sync_pr": None
        if number is None
        else {
            "number": number,
            "url": f"https://example.invalid/pr/{number}",
            "head": "chore/core-v0.59.0",
            "created_at": "2026-10-21T05:00:00Z",
            "ci": ci,
        },
        "status": None,
        "ui_verdict": None,
        "adoption": [],
        "not_collected": [],
    }
    c.update(extra)
    return c


FIXTURE = {
    "format": "build-standards-consumption/1",
    "generated_at": "2026-10-21T03:15:42Z",
    "core_repo": CORE,
    "latest": "v0.59.0",
    "consumers": [
        consumer(
            "ops-center-role",
            "ops-center",
            status={"pass": 40, "proved": 3, "fail": 0, "unverified": 200},
            ui_verdict="adopted",
            adoption=[
                {
                    "part": "Card",
                    "file": "src/ui.tsx",
                    "kit_part": "Card",
                    "relation": "duplicates",
                    "risk": "low",
                },
                {
                    "part": "Wrapper",
                    "file": "src/w.tsx",
                    "kit_part": "Table",
                    "relation": "extends",
                    "risk": None,
                },
            ],
        ),
        consumer(
            "vendored-shell-role",
            "vendored",
            number=7,
            ci="pending",
            behind=24,
            pinned="v0.35.0",
            not_collected=["status: a vendored repo carries no core-status.py"],
        ),
        consumer(
            "workflow-role-pass",
            "workflow",
            number=12,
            ci="pass",
            behind=2,
            pinned="v0.57.0",
            status={"pass": 12, "proved": 0, "fail": 0, "unverified": 256},
            ui_verdict="partial",
        ),
        consumer(
            "workflow-role-fail",
            "workflow",
            number=3,
            ci="fail",
            behind=2,
            pinned="v0.57.0",
            not_collected=["status: core-status.py not found", "ui_verdict: no UI"],
        ),
        consumer("workflow-role-none", "workflow"),
    ],
    "account": {
        "report_issue": "https://example.invalid/issues/117",
        "awaiting_decision": [{"issue": 117, "id": "D-027", "title": "Awaiting item"}],
        "approved_unopened": [{"issue": 117, "id": "D-015", "title": "Approved item"}],
    },
    "peers": {
        "issues": [
            {
                "number": 115,
                "url": "https://example.invalid/issues/115",
                "author": "peer-role",
                "mine": False,
                "items": [
                    {
                        "id": "D-004",
                        "title": "Shipped item",
                        "kind": "D",
                        "status": "shipped",
                        "shipped_in": "v0.58.0",
                    },
                    {"id": "P-002", "title": "Held item", "kind": "P", "status": "held"},
                ],
            }
        ],
        "suggestions": [
            {
                "issue": 115,
                "id": "D-004",
                "title": "New one",
                "author": "peer-role",
                "shipped_in": "v0.58.0",
                "new": True,
            },
            {
                "issue": 115,
                "id": "D-003",
                "title": "Old one",
                "author": "peer-role",
                "shipped_in": "v0.57.0",
                "new": False,
            },
        ],
    },
    "not_collected": [],
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.feed = self.dir / "consumption.json"
        self.write_feed(FIXTURE)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        for name, body in (("gh", GH_DOUBLE), ("git", GIT_DOUBLE)):
            f = self.bin / name
            f.write_text(body)
            f.chmod(f.stat().st_mode | stat.S_IXUSR)
        self.script = {}
        self.write_script()
        keys = ("CORE_CONSUMPTION_FILE", "CORE_CONSUMPTION_GH", "GH_DOUBLE_DIR", "PATH")
        self.saved = {k: os.environ.get(k) for k in keys}
        os.environ["CORE_CONSUMPTION_FILE"] = str(self.feed)
        os.environ["CORE_CONSUMPTION_GH"] = str(self.bin / "gh")
        os.environ["GH_DOUBLE_DIR"] = str(self.dir)
        os.environ["PATH"] = str(self.bin) + os.pathsep + os.environ.get("PATH", "")
        cc._done.clear()
        swr.invalidate(cc.CACHE_KEY)

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        swr.invalidate(cc.CACHE_KEY)
        self.tmp.cleanup()

    def write_feed(self, doc):
        tmp = self.feed.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc))
        os.replace(tmp, self.feed)

    def write_script(self):
        (self.dir / "script.json").write_text(json.dumps(self.script))

    def calls(self):
        f = self.dir / "calls.jsonl"
        if not f.exists():
            return []
        return [json.loads(x) for x in f.read_text().splitlines() if x]

    def writes(self):
        return [
            c for c in self.calls() if " ".join(c[:2]) in ("pr ready", "pr merge", "issue comment")
        ]

    def git_calls(self):
        f = self.dir / "git-calls.txt"
        return f.read_text().splitlines() if f.exists() else []


def live_pr(draft=False, head="chore/core-v0.59.0", checks="pass", state="OPEN"):
    rollup = {
        "pass": [
            {"name": "ci", "workflowName": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}
        ],
        "fail": [
            {"name": "ci", "workflowName": "ci", "status": "COMPLETED", "conclusion": "FAILURE"}
        ],
        "pending": [
            {"name": "ci", "workflowName": "ci", "status": "IN_PROGRESS", "conclusion": ""}
        ],
        "none": [],
    }[checks]
    return {
        "state": state,
        "isDraft": draft,
        "headRefName": head,
        "headRefOid": "0" * 40,
        "statusCheckRollup": rollup,
    }


class RenderTests(Base):
    def rows(self):
        v = cc.get(fresh=True)
        self.assertEqual(v["state"], "ok")
        return {r["repo"].split("/")[1]: r for r in v["consumers"]}

    def test_one_row_per_consumer_with_pin_latest_behind(self):
        rows = self.rows()
        self.assertEqual(len(rows), len(FIXTURE["consumers"]))
        r = rows["vendored-shell-role"]
        self.assertEqual((r["mode"], r["class"]), ("vendored", "approval-gated"))
        self.assertEqual((r["pinned"], r["latest"], r["behind"]), ("v0.35.0", "v0.59.0", 24))
        self.assertEqual(cc.get()["latest"], "v0.59.0")

    def test_sync_pr_ci_state_on_workflow_and_vendored_none_on_ops_center(self):
        rows = self.rows()
        self.assertEqual(rows["vendored-shell-role"]["sync_pr"]["ci"], "pending")
        self.assertEqual(rows["workflow-role-pass"]["sync_pr"]["ci"], "pass")
        self.assertEqual(rows["workflow-role-fail"]["sync_pr"]["ci"], "fail")
        self.assertIsNone(rows["workflow-role-none"]["sync_pr"])
        oc = rows["ops-center-role"]
        self.assertIsNone(oc["sync_pr"])
        self.assertEqual((oc["mode"], oc["class"]), ("ops-center", "apply-at-once"))
        self.assertFalse(oc["sync_applies"])
        self.assertTrue(rows["workflow-role-none"]["sync_applies"])

    def test_ops_center_never_shows_a_sync_pr_even_if_the_feed_carries_one(self):
        doc = copy.deepcopy(FIXTURE)
        doc["consumers"][0]["sync_pr"] = {
            "number": 1,
            "url": "u",
            "head": "h",
            "created_at": "t",
            "ci": "pass",
        }
        self.write_feed(doc)
        rows = self.rows()
        self.assertIsNone(rows["ops-center-role"]["sync_pr"])
        self.assertEqual(rows["ops-center-role"]["approval"]["kind"], "none")

    def test_status_counts_or_the_not_collected_reason(self):
        rows = self.rows()
        self.assertEqual(
            rows["workflow-role-pass"]["status"],
            {"pass": 12, "proved": 0, "fail": 0, "unverified": 256},
        )
        self.assertEqual(rows["workflow-role-pass"]["ui_verdict"], "partial")
        self.assertIsNone(rows["vendored-shell-role"]["status"])
        self.assertIn("core-status.py", rows["vendored-shell-role"]["not_collected"][0])
        self.assertEqual(len(rows["workflow-role-fail"]["not_collected"]), 2)

    def test_adoption_rows_carry_risk(self):
        adoption = self.rows()["ops-center-role"]["adoption"]
        self.assertEqual(
            [(a["part"], a["risk"]) for a in adoption], [("Card", "low"), ("Wrapper", None)]
        )
        self.assertEqual(adoption[0]["kit_part"], "Card")

    def test_account_and_peers(self):
        v = cc.get(fresh=True)
        self.assertEqual(v["account"]["report_issue"], "https://example.invalid/issues/117")
        self.assertEqual([a["id"] for a in v["account"]["awaiting_decision"]], ["D-027"])
        self.assertTrue(v["account"]["awaiting_decision"][0]["can_approve"])
        self.assertEqual([a["id"] for a in v["account"]["approved_unopened"]], ["D-015"])
        self.assertEqual(
            [i["status"] for i in v["peers"]["issues"][0]["items"]], ["shipped", "held"]
        )
        news = {s["id"]: s["new"] for s in v["peers"]["suggestions"]}
        self.assertEqual(news, {"D-004": True, "D-003": False})
        self.assertEqual(v["peers"]["new_count"], 1)

    def test_wrong_format_is_an_error_state_not_stale_rows(self):
        self.assertEqual(cc.get(fresh=True)["state"], "ok")
        self.write_feed(dict(FIXTURE, format="build-standards-consumption/2"))
        v = cc.get(fresh=True)
        self.assertEqual(v["state"], "error")
        self.assertEqual(v["error"], "format")
        self.assertEqual(v["consumers"], [])
        self.assertIn("build-standards-consumption/2", v["message"])

    def test_missing_and_broken_files_are_error_states(self):
        self.feed.write_text("{not json")
        self.assertEqual(cc.get(fresh=True)["error"], "invalid")
        self.feed.unlink()
        v = cc.get(fresh=True)
        self.assertEqual((v["state"], v["error"], v["consumers"]), ("error", "missing", []))
        self.write_feed([1, 2])
        self.assertEqual(cc.get(fresh=True)["error"], "invalid")

    def test_render_path_makes_no_gh_or_git_call(self):
        cc.get(fresh=True)
        cc.get()
        cc.badge()
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.git_calls(), [])

    def test_polling_is_cached_for_a_minute(self):
        first = cc.get(fresh=True)
        self.write_feed(dict(FIXTURE, latest="v9.9.9"))
        self.assertEqual(cc.get()["latest"], first["latest"])
        self.assertEqual(cc.get(fresh=True)["latest"], "v9.9.9")

    def test_approval_controls(self):
        rows = self.rows()
        self.assertEqual(rows["ops-center-role"]["approval"]["kind"], "none")
        self.assertEqual(rows["workflow-role-none"]["approval"]["kind"], "none")
        fail = rows["workflow-role-fail"]["approval"]
        self.assertEqual(
            (fail["kind"], fail["target"]), ("disabled", "example-org/workflow-role-fail#3")
        )
        ok = rows["workflow-role-pass"]["approval"]
        self.assertEqual(
            (ok["kind"], ok["target"]), ("enabled", "example-org/workflow-role-pass#12")
        )
        self.assertEqual(rows["vendored-shell-role"]["approval"]["kind"], "enabled")

    def test_report_only_row_has_a_disabled_control(self):
        doc = copy.deepcopy(FIXTURE)
        doc["consumers"][2]["report_only"] = True
        self.write_feed(doc)
        self.assertEqual(self.rows()["workflow-role-pass"]["approval"]["kind"], "disabled")

    def test_badge_counts_passing_sync_prs_and_awaiting_items(self):
        self.assertEqual(cc.badge(), 2)


class ApprovePrTests(Base):
    PASS = {
        "repo": "example-org/workflow-role-pass",
        "number": 12,
        "confirm": "example-org/workflow-role-pass#12",
    }

    def setUp(self):
        super().setUp()
        self.script = {
            "pr view": live_pr(),
            "repo view": {
                "squashMergeAllowed": True,
                "rebaseMergeAllowed": False,
                "mergeCommitAllowed": False,
            },
        }
        self.write_script()

    def test_green_ready_pr_is_merged_with_the_declared_method_pinned_to_the_head(self):
        r = cc.approve_pr(dict(self.PASS))
        self.assertIn("merged", r["done"][0])
        self.assertEqual(
            self.writes(),
            [
                [
                    "pr",
                    "merge",
                    "12",
                    "-R",
                    "example-org/workflow-role-pass",
                    "--squash",
                    "--match-head-commit",
                    "0" * 40,
                ]
            ],
        )
        self.assertEqual(self.git_calls(), [])

    def test_declared_method_follows_the_repo(self):
        self.script["repo view"] = {
            "squashMergeAllowed": False,
            "rebaseMergeAllowed": False,
            "mergeCommitAllowed": True,
        }
        self.write_script()
        cc.approve_pr(dict(self.PASS))
        self.assertIn("--merge", self.writes()[0])

    def test_draft_pr_is_marked_ready_not_merged(self):
        self.script["pr view"] = live_pr(draft=True)
        self.write_script()
        cc.approve_pr(dict(self.PASS))
        self.assertEqual(
            self.writes(), [["pr", "ready", "12", "-R", "example-org/workflow-role-pass"]]
        )

    def test_failing_live_checks_refuse_without_a_write(self):
        for state in ("fail", "pending", "none"):
            self.script["pr view"] = live_pr(checks=state)
            self.write_script()
            with self.assertRaises(cc.ConsumptionError) as cm:
                cc.approve_pr(dict(self.PASS))
            self.assertEqual(cm.exception.code, 409)
        self.assertEqual(self.writes(), [])

    def test_a_feed_row_with_failing_ci_cannot_be_approved_even_if_live_is_green(self):
        with self.assertRaises(cc.ConsumptionError):
            cc.approve_pr(
                {
                    "repo": "example-org/workflow-role-fail",
                    "number": 3,
                    "confirm": "example-org/workflow-role-fail#3",
                }
            )
        self.assertEqual(self.writes(), [])

    def test_confirmation_must_name_the_target(self):
        for confirm in (
            None,
            "",
            "example-org/workflow-role-pass",
            "example-org/workflow-role-pass#13",
        ):
            with self.assertRaises(cc.ConsumptionError):
                cc.approve_pr(dict(self.PASS, confirm=confirm))
        self.assertEqual(self.calls(), [])

    def test_apply_at_once_row_and_unknown_prs_are_refused(self):
        with self.assertRaises(cc.ConsumptionError):
            cc.approve_pr(
                {
                    "repo": "example-org/ops-center-role",
                    "number": 1,
                    "confirm": "example-org/ops-center-role#1",
                }
            )
        with self.assertRaises(cc.ConsumptionError):
            cc.approve_pr(
                {"repo": "example-org/other", "number": 99, "confirm": "example-org/other#99"}
            )
        self.assertEqual(self.calls(), [])

    def test_a_moved_head_branch_asks_for_a_refresh(self):
        self.script["pr view"] = live_pr(head="someone/else")
        self.write_script()
        with self.assertRaises(cc.ConsumptionError) as cm:
            cc.approve_pr(dict(self.PASS))
        self.assertIn("Refresh first", str(cm.exception))
        self.assertEqual(self.writes(), [])

    def test_already_merged_is_an_idempotent_success(self):
        self.script["pr view"] = live_pr(state="MERGED")
        self.write_script()
        r = cc.approve_pr(dict(self.PASS))
        self.assertTrue(r["already"])
        self.assertEqual(self.writes(), [])

    def test_a_failed_live_read_fails_closed(self):
        self.script.pop("pr view")
        self.write_script()
        with self.assertRaises(cc.ConsumptionError):
            cc.approve_pr(dict(self.PASS))
        self.assertEqual(self.writes(), [])


class TombstoneTests(Base):
    def test_an_approved_row_and_item_stay_done_until_the_next_feed(self):
        self.script = {
            "pr view": live_pr(),
            "repo view": {"squashMergeAllowed": True},
            "issue view": {"state": "OPEN", "comments": []},
        }
        self.write_script()
        cc.approve_pr(
            {
                "repo": "example-org/workflow-role-pass",
                "number": 12,
                "confirm": "example-org/workflow-role-pass#12",
            }
        )
        cc.approve_item({"issue": 117, "id": "D-027", "confirm": "D-027 on issue #117"})
        v = cc.get()
        row = [r for r in v["consumers"] if r["repo"].endswith("workflow-role-pass")][0]
        self.assertEqual(row["approval"]["kind"], "done")
        self.assertTrue(v["account"]["awaiting_decision"][0]["done"])
        self.assertEqual(v["needs_me"], 0)
        self.write_feed(dict(FIXTURE, generated_at="2026-10-22T03:15:42Z"))
        v = cc.get(fresh=True)
        row = [r for r in v["consumers"] if r["repo"].endswith("workflow-role-pass")][0]
        self.assertEqual(row["approval"]["kind"], "enabled")
        self.assertEqual(v["needs_me"], 2)

    def tearDown(self):
        cc._done.clear()
        super().tearDown()


class ApproveItemTests(Base):
    ITEM = {"issue": 117, "id": "D-027", "confirm": "D-027 on issue #117"}

    def setUp(self):
        super().setUp()
        self.script = {"issue view": {"state": "OPEN", "comments": [{"body": "approve D-001"}]}}
        self.write_script()

    def test_posts_my_decision_text_on_the_items_issue(self):
        r = cc.approve_item(dict(self.ITEM))
        self.assertIn("approve D-027", r["done"][0])
        self.assertEqual(
            self.writes(), [["issue", "comment", "117", "-R", CORE, "--body", "approve D-027"]]
        )
        self.assertEqual(self.git_calls(), [])

    def test_already_approved_is_an_idempotent_success(self):
        self.script["issue view"]["comments"].append({"body": "approve D-027"})
        self.write_script()
        r = cc.approve_item(dict(self.ITEM))
        self.assertTrue(r["already"])
        self.assertEqual(self.writes(), [])

    def test_only_awaiting_items_with_a_matching_confirmation(self):
        bad = [
            {"issue": 117, "id": "D-015", "confirm": "D-015 on issue #117"},
            {"issue": 5, "id": "D-027", "confirm": "D-027 on issue #5"},
            {"issue": 117, "id": "D-027", "confirm": "D-027"},
            {"issue": 117, "id": "D-027; rm", "confirm": "D-027; rm on issue #117"},
        ]
        for p in bad:
            with self.assertRaises(cc.ConsumptionError):
                cc.approve_item(p)
        self.assertEqual(self.calls(), [])


# core-rule: local-ops-app.19
class NeverPushTests(Base):
    def test_every_recorded_write_is_pr_ready_pr_merge_or_issue_comment(self):
        self.script = {
            "pr view": live_pr(draft=True),
            "repo view": {"squashMergeAllowed": True},
            "issue view": {"state": "OPEN", "comments": []},
        }
        self.write_script()
        target = {
            "repo": "example-org/workflow-role-pass",
            "number": 12,
            "confirm": "example-org/workflow-role-pass#12",
        }
        cc.approve_pr(dict(target))
        self.script["pr view"] = live_pr()
        self.write_script()
        cc.approve_pr(dict(target))
        cc.approve_item({"issue": 117, "id": "D-027", "confirm": "D-027 on issue #117"})
        verbs = [" ".join(c[:2]) for c in self.writes()]
        self.assertEqual(verbs, ["pr ready", "pr merge", "issue comment"])
        reads = {" ".join(c[:2]) for c in self.calls()} - set(verbs)
        self.assertEqual(reads, {"pr view", "repo view", "issue view"})
        self.assertEqual(self.git_calls(), [])
        for c in self.calls():
            self.assertNotIn("push", c)


if __name__ == "__main__":
    unittest.main()
