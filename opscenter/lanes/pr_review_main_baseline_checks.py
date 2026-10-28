#!/usr/bin/env python3
"""
pr_review_main_baseline_checks.py
Purpose: Tests for apply_main_baseline() and resource_diffs() in pr_review.py:
         a PR plan change identical to what main's nightly drift run plans is main baseline drift,
         only for creates and in-place updates, only when the PR touches no file of that root,
         and any read error fails closed. Synthetic logs, no GitHub.
Date:    2026-10-21
Run:     /usr/bin/python3 pr_review_main_baseline_checks.py
"""

from __future__ import annotations

import importlib.util
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
SCRATCH = tempfile.mkdtemp(prefix="oprbase-", dir=os.environ.get("TMPDIR"))
os.environ["OPRG_STATE_DIR"] = SCRATCH
os.environ["OPRG_CACHE_DIR"] = SCRATCH
os.environ["OPRG_GH_BIN"] = "/usr/bin/false"
os.environ["OPRG_DRY_RUN"] = "1"

spec = importlib.util.spec_from_file_location("oprg_base", str(HERE / "pr_review.py"))
eng = importlib.util.module_from_spec(spec)
sys.modules["oprg_base"] = eng
spec.loader.exec_module(eng)

POOL = 'module.pool["int-eus"].azurerm_virtual_desktop_host_pool.this'
POOL2 = 'module.pool["val-eus"].azurerm_virtual_desktop_host_pool.this'
OLD = "a:i:1;b:i:0;"
NEW = "b:i:0;a:i:1;"


def block(addr, action="will be updated in-place", old=OLD, new=NEW, ts=True, color=False):
    pre = "2026-10-21T09:31:02.1234567Z " if ts else ""
    c = "\x1b[1m" if color else ""
    return [
        f"{pre}  {c}# {addr}\x1b[0m {action}" if color else f"{pre}  # {addr} {action}",
        f'{pre}  ~ resource "azurerm_virtual_desktop_host_pool" "this" {{',
        f'{pre}        id = "/subscriptions/x/hp"',
        f'{pre}      ~ custom_rdp_properties = "{old}" -> "{new}"',
        f"{pre}        # (12 unchanged attributes hidden)",
        f"{pre}    }}",
        f"{pre}",
    ]


def log(blocks, plan_line):
    out = ["2026-10-21T09:31:00Z Terraform will perform the following actions:"]
    for b in blocks:
        out += b
    out.append(f"2026-10-21T09:31:03Z {plan_line}")
    return "\n".join(out)


def plan_with(
    root="avd", tier="prod", summary="Plan: 0 to add, 2 to change, 0 to destroy.", resources=None
):
    return {
        "ran": True,
        "status": "completed",
        "add": 0,
        "change": 2,
        "destroy": 0,
        "destroyed": [],
        "replaced": [],
        "resources": resources
        if resources is not None
        else [
            {
                "root": root,
                "tier": tier,
                "address": POOL,
                "action": "update",
                "attrs": ["custom_rdp_properties"],
            },
            {
                "root": root,
                "tier": tier,
                "address": POOL2,
                "action": "update",
                "attrs": ["custom_rdp_properties"],
            },
        ],
        "roots": [
            {
                "root": root,
                "tier": tier,
                "job_id": 7,
                "summary": summary,
                "parsed": True,
                "destroy": 0,
            },
            {
                "root": "shared-core",
                "tier": "prod",
                "job_id": 8,
                "summary": "No changes",
                "parsed": True,
                "destroy": 0,
            },
        ],
    }


MAIN_LOG = log([block(POOL), block(POOL2)], "Plan: 0 to add, 2 to change, 0 to destroy.")
BASE = {("avd", "prod"): eng.resource_diffs(MAIN_LOG)}


def run(p, pr_log_text, files=("functions/jsm-mail-relay/app.py",), baseline=BASE):
    return eng.apply_main_baseline(
        {}, "o/r", p, list(files), baseline=baseline, pr_log=lambda rt: pr_log_text
    )


class ParserTests(unittest.TestCase):
    def test_timestamps_and_color_do_not_change_digest(self):
        a = eng.resource_diffs(
            log([block(POOL, ts=True)], "Plan: 0 to add, 1 to change, 0 to destroy.")
        )
        b = eng.resource_diffs(
            log([block(POOL, ts=False, color=True)], "Plan: 0 to add, 1 to change, 0 to destroy.")
        )
        self.assertEqual(a, b)

    def test_value_change_changes_digest(self):
        a = eng.resource_diffs(log([block(POOL)], "Plan: 0 to add, 1 to change, 0 to destroy."))
        b = eng.resource_diffs(
            log([block(POOL, new="b:i:1;a:i:1;")], "Plan: 0 to add, 1 to change, 0 to destroy.")
        )
        self.assertEqual(a[POOL][0], "update")
        self.assertNotEqual(a[POOL][1], b[POOL][1])

    def test_data_source_read_is_not_a_change(self):
        lines = ["  # data.x.y will be read during apply", "  <= data x y {", "  }"] + block(POOL)
        d = eng.resource_diffs("\n".join(lines))
        self.assertEqual(list(d), [POOL])


class BaselineTests(unittest.TestCase):
    def test_identical_drift_reads_no_changes(self):
        out = run(plan_with(), MAIN_LOG)
        avd = out["roots"][0]
        self.assertEqual(avd["summary"], "No changes")
        self.assertEqual(sorted(avd["baseline_drift"]), sorted([POOL, POOL2]))
        self.assertEqual(out["resources"], [])
        self.assertEqual(out["change"], 0)
        self.assertEqual(len(out["main_baseline"]), 2)

    def test_pr_change_on_top_keeps_root_dirty(self):
        extra = 'azurerm_role_assignment.x["y"]'
        pr = log(
            [block(POOL), block(POOL2), block(extra, action="will be created")],
            "Plan: 1 to add, 2 to change, 0 to destroy.",
        )
        p = plan_with(summary="Plan: 1 to add, 2 to change, 0 to destroy.")
        p["resources"].append(
            {"root": "avd", "tier": "prod", "address": extra, "action": "create", "attrs": []}
        )
        out = run(p, pr)
        self.assertNotEqual(out["roots"][0]["summary"], "No changes")
        self.assertEqual([r["address"] for r in out["resources"]], [extra])

    def test_different_value_is_the_prs(self):
        pr = log(
            [block(POOL, new="a:i:0;"), block(POOL2)], "Plan: 0 to add, 2 to change, 0 to destroy."
        )
        out = run(plan_with(), pr)
        self.assertNotEqual(out["roots"][0]["summary"], "No changes")
        self.assertEqual([r["address"] for r in out["resources"]], [POOL])

    def test_pr_touching_root_is_never_baseline(self):
        out = run(plan_with(), MAIN_LOG, files=("infrastructure/terraform/avd/main.tf",))
        self.assertNotIn("main_baseline", out)

    def test_pr_touching_shared_modules_is_never_baseline(self):
        out = run(plan_with(), MAIN_LOG, files=("infrastructure/terraform/modules/x/main.tf",))
        self.assertNotIn("main_baseline", out)

    def test_destroy_and_replace_never_baseline(self):
        for action in ("will be destroyed", "must be replaced"):
            text = log([block(POOL, action=action)], "Plan: 0 to add, 0 to change, 1 to destroy.")
            base = {("avd", "prod"): eng.resource_diffs(text)}
            p = plan_with(summary="Plan: 0 to add, 0 to change, 1 to destroy.")
            out = run(p, text, baseline=base)
            self.assertNotIn("main_baseline", out, action)

    def test_no_baseline_for_root_is_real(self):
        out = run(plan_with(), MAIN_LOG, baseline={})
        self.assertNotIn("main_baseline", out)

    def test_count_mismatch_keeps_summary(self):
        out = run(plan_with(summary="Plan: 0 to add, 3 to change, 0 to destroy."), MAIN_LOG)
        self.assertNotEqual(out["roots"][0]["summary"], "No changes")

    def test_read_error_fails_closed(self):
        def boom(rt):
            raise eng.GhError("rc=1 boom")

        p = plan_with()
        out = eng.apply_main_baseline({}, "o/r", p, [], baseline=BASE, pr_log=boom)
        self.assertIn("main_baseline_error", out)
        self.assertEqual(out["roots"][0]["summary"], "Plan: 0 to add, 2 to change, 0 to destroy.")

    def test_no_dirty_roots_untouched(self):
        p = plan_with(summary="No changes")
        self.assertIs(run(p, MAIN_LOG), p)

    def test_waiver_sees_clean_prod_root(self):
        out = run(plan_with(), MAIN_LOG)
        prod = [r for r in out["roots"] if r["tier"] == "prod"]
        self.assertTrue(all(r["summary"] == "No changes" for r in prod))


if __name__ == "__main__":
    unittest.main(verbosity=1)
