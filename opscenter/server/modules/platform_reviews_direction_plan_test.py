"""
platform_reviews_direction_plan_test.py
Purpose: tests. A direction card (auto-fix gave up, the owner's choice needed) carries the plan of its
         exact head, so its approval brief never claims no plan ran when a plan job passed. A failed
         plan read is marked unread and the brief says it does not know. Stubbed engine, no GitHub.
Date:    2026-10-26
Run:     /usr/bin/python3 platform_reviews_direction_plan_test.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="oprev-dirplan-"))
for _d in ("", "../../lanes", "../../engine"):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), _d))

import platform_reviews as o  # noqa: E402
import platform_reviews_testenv as te  # noqa: E402
import pr_landing as pl  # noqa: E402

_ENV = {
    "TFGATE_STATE_DIR": str(Path(TMP) / "tfstate"),
    "TFGATE_CACHE_DIR": str(Path(TMP) / "tfcache"),
    "OPRG_CACHE_DIR": str(TMP / "cache"),
    "OPRG_STATE_DIR": str(TMP / "state"),
}


def setUpModule():
    te.apply(_ENV, TMP)


def tearDownModule():
    te.restore()


HEAD = "c" * 40
PLAN = {
    "ran": True,
    "run_id": 40347326535,
    "add": 7,
    "change": 0,
    "destroy": 0,
    "import": 0,
    "replace": 0,
    "resources": [{"address": "azurerm_role_definition.a", "action": "create"}],
    "roots": [
        {
            "job": "terraform plan (pipeline-identities platform)",
            "summary": "Plan: 7 to add",
            "parsed": True,
        }
    ],
    "errors": [],
}


class DirectionPlan(unittest.TestCase):
    def setUp(self):
        self.real = o._engine_check
        self.calls = 0

    def tearDown(self):
        o._engine_check = self.real

    def stub(self, out):
        def fake(n, head=None):
            self.calls += 1
            return out

        o._engine_check = fake

    def item(self):
        return {"pr": 484, "head_sha": HEAD}

    def test_direction_card_gets_the_head_plan(self):
        self.stub({"head_sha": HEAD, "plan": PLAN})
        h = o._attach_plan({"kind": "direction"}, self.item())
        self.assertEqual(h["plan_detail"]["add"], 7)
        self.assertEqual(h["plan_detail"]["run_id"], 40347326535)
        self.assertIn("7 add", h["plan"])
        self.assertNotIn("plan_unread", h)

    def test_failed_engine_read_is_unread_not_no_plan(self):
        self.stub(None)
        h = o._attach_plan({"kind": "direction"}, self.item())
        self.assertTrue(h["plan_unread"])
        self.assertIsNone(h.get("plan_detail"))

    def test_other_head_is_unread(self):
        self.stub({"head_sha": "d" * 40, "plan": PLAN})
        self.assertTrue(o._attach_plan({"kind": "direction"}, self.item())["plan_unread"])

    def test_no_terraform_change_is_a_real_no_plan(self):
        self.stub({"head_sha": HEAD, "plan": {"ran": False}})
        h = o._attach_plan({"kind": "direction"}, self.item())
        self.assertIsNone(h["plan_detail"])
        self.assertNotIn("plan_unread", h)

    def test_existing_plan_is_kept_without_a_read(self):
        self.stub({"head_sha": HEAD, "plan": PLAN})
        h = o._attach_plan({"kind": "direction", "plan_detail": {"add": 1}}, self.item())
        self.assertEqual(h["plan_detail"], {"add": 1})
        self.assertEqual(self.calls, 0)

    def test_gave_up_hold_carries_the_plan(self):
        self.stub({"head_sha": HEAD, "plan": PLAN})
        real_base = o._hold_base
        o._hold_base = lambda item: {"kind": "problem", "summary": "Review blocked.", "next": "x"}
        try:
            h = o._hold(
                dict(self.item(), autofix={"state": "gave_up", "text": "Auto-fix gave up."})
            )
        finally:
            o._hold_base = real_base
        self.assertEqual(h["kind"], "direction")
        self.assertEqual(h["plan_detail"]["add"], 7)

    def test_landing_says_unread_never_no_plan(self):
        land = pl.landing(None, [], {}, plan_unread=True)
        self.assertEqual(land["status"], "plan_unread")
        txt = pl.land_text(land)
        self.assertIn("NOT be read", txt)
        self.assertNotIn("No Terraform plan ran", txt)
        self.assertEqual(pl.landing(None, [], {})["status"], "no_plan")


if __name__ == "__main__":
    unittest.main(verbosity=1)
