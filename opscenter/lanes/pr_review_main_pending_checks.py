#!/usr/bin/env python3
"""
pr_review_main_pending_checks.py
Purpose: Tests for apply_main_pending() and main_pending_reason() in pr_review.py:
         a PR plan destroy or replace in a root the PR does not touch, that main itself still has to
         apply (failed main apply, pending Owner root), holds the PR as "main not applied" with no
         merge button. A plan that ran before main's last apply is "stale" and gets re-run. Anything
         else, and any read error, leaves the normal hold. Synthetic data, no GitHub.
Date:    2026-10-22
Run:     /usr/bin/python3 pr_review_main_pending_checks.py
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
SCRATCH = tempfile.mkdtemp(prefix="oprpend-", dir=os.environ.get("TMPDIR"))
os.environ["OPRG_STATE_DIR"] = SCRATCH
os.environ["OPRG_CACHE_DIR"] = SCRATCH
os.environ["OPRG_GH_BIN"] = "/usr/bin/false"
os.environ["OPRG_DRY_RUN"] = "1"

spec = importlib.util.spec_from_file_location("oprg_pend", str(HERE / "pr_review.py"))
eng = importlib.util.module_from_spec(spec)
sys.modules["oprg_pend"] = eng
spec.loader.exec_module(eng)

VW = 'azurerm_role_assignment.vendor_writer["jsm-mail-relay"]'
GA = "azurerm_role_definition.governance_vault_writer_admin"
FAILED = {
    "id": 111,
    "conclusion": "failure",
    "updated_at": "2026-10-22T21:20:00Z",
    "html_url": "u111",
}
OK_OLD = {"id": 100, "conclusion": "success", "updated_at": "2026-10-22T20:00:00Z"}
OK_NEW = {"id": 112, "conclusion": "success", "updated_at": "2026-10-22T22:20:00Z"}


def plan(resources, started="2026-10-22T21:51:00Z"):
    return {
        "ran": True,
        "status": "completed",
        "run_id": 900,
        "started_at": started,
        "resources": resources,
    }


def res(root, address, action, tier="prod"):
    return {"root": root, "tier": tier, "address": address, "action": action}


class MainPending(unittest.TestCase):
    def run_it(self, p, files=("apps/avd/x.tf",), owner=None, runs=None, pending=None):
        return eng.apply_main_pending(
            {},
            "o/r",
            p,
            list(files),
            owner_status=owner or {},
            apply_runs=runs or [],
            apply_pending=pending,
        )

    def test_failed_main_apply_blocks(self):
        out = self.run_it(
            plan([res("escalations", VW, "replace")]),
            runs=[FAILED, OK_OLD],
            pending={VW: "replace"},
        )
        self.assertEqual(out["main_pending"]["state"], "blocked")
        why = eng.main_pending_reason(out)
        self.assertTrue(why.startswith("main not applied:"), why)
        self.assertIn("run 111", why)
        self.assertNotIn(";", why)

    def test_pending_owner_root_blocks(self):
        owner = {
            "pipeline-identities:prod": {
                "state": "pending",
                "resources": [{"address": GA, "action": "replace"}],
            }
        }
        out = self.run_it(
            plan([res("pipeline-identities", GA, "replace")]), owner=owner, runs=[OK_OLD]
        )
        self.assertEqual(out["main_pending"]["state"], "blocked")
        self.assertIn("Owner apply of pipeline-identities prod", eng.main_pending_reason(out))

    def test_pr_touching_the_root_is_its_own_change(self):
        out = self.run_it(
            plan([res("escalations", VW, "replace")]),
            files=["infrastructure/terraform/escalations/main.tf"],
            runs=[FAILED],
            pending={VW: "replace"},
        )
        self.assertNotIn("main_pending", out)

    def test_different_action_is_not_mains(self):
        out = self.run_it(
            plan([res("escalations", VW, "destroy")]), runs=[FAILED], pending={VW: "replace"}
        )
        self.assertNotIn("main_pending", out)

    def test_plan_before_main_applied_is_stale(self):
        out = self.run_it(plan([res("escalations", VW, "replace")]), runs=[OK_NEW, FAILED])
        self.assertEqual(out["main_pending"]["state"], "stale")
        self.assertTrue(eng.main_pending_reason(out).startswith("plans predate main's last apply:"))

    def test_owner_applied_after_plan_is_stale(self):
        owner = {
            "pipeline-identities:prod": {
                "state": "clean",
                "last_apply": {"at": "2026-10-22T22:12:52Z"},
            }
        }
        out = self.run_it(
            plan([res("pipeline-identities", GA, "replace")]), owner=owner, runs=[OK_OLD]
        )
        self.assertEqual(out["main_pending"]["state"], "stale")

    def test_unexplained_destroy_keeps_the_normal_hold(self):
        out = self.run_it(
            plan([res("escalations", VW, "destroy")], started="2026-10-22T23:00:00Z"), runs=[OK_NEW]
        )
        self.assertNotIn("main_pending", out)

    def test_partly_stale_is_not_rerun(self):
        owner = {
            "pipeline-identities:prod": {
                "state": "clean",
                "last_apply": {"at": "2026-10-22T22:12:52Z"},
            }
        }
        p = plan([res("pipeline-identities", GA, "replace"), res("escalations", VW, "destroy")])
        out = self.run_it(p, owner=owner, runs=[OK_OLD])
        self.assertNotIn("main_pending", out)

    def test_creates_and_updates_are_ignored(self):
        out = self.run_it(
            plan([res("escalations", VW, "create")]), runs=[FAILED], pending={VW: "create"}
        )
        self.assertNotIn("main_pending", out)

    def test_unfinished_plan_is_ignored(self):
        p = dict(plan([res("escalations", VW, "replace")]), status="in_progress")
        self.assertNotIn("main_pending", self.run_it(p, runs=[FAILED], pending={VW: "replace"}))

    def test_read_error_fails_closed(self):
        out = eng.apply_main_pending(
            {}, "o/r", plan([res("escalations", VW, "replace")]), [], owner_status={}
        )
        self.assertNotIn("main_pending", out)  # gh is /usr/bin/false
        self.assertIn("main_pending_error", out)

    def test_no_reason_without_main_pending(self):
        self.assertIsNone(eng.main_pending_reason(plan([])))


if __name__ == "__main__":
    unittest.main(verbosity=1)
