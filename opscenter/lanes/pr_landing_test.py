"""
pr_landing_test.py
Purpose: The structured ask for PR cards (pr_landing.py) on synthetic data: which roots a merge applies (a watched path, a
         shared module, an app root's own folder, the apply tier only, the owner-applied root never), the unknown and
         no-plan statuses, the gate per applier and the destroy gate, when the typed name is required, the card fields
         for the owner's own PR and an engineer PR, and the prose check that a root the merge does not apply is never
         said to be applied. The estate values come from a temp landing config.
Run:     python3 pr_landing_test.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pr-landing-"))
(TMP / "landing.json").write_text(
    json.dumps(
        {
            "apply_tier": "prod",
            "shared_modules": ["infra/modules/"],
            "gates": {
                "consent": "consent approval",
                "runbooks": "none, the runbook workflow applies it",
            },
            "destroy_gate": "destroy approval",
            "destroy_appliers": ["tfapply", "runbooks"],
        }
    )
)
os.environ["OPSCENTER_LANDING_CONFIG"] = str(TMP / "landing.json")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pr_landing as pl  # noqa: E402

HEAD = "a" * 40
SPEC = {
    "core": {
        "name": "core",
        "apply": True,
        "watch": ["ops/core/manifest.json"],
        "tiers": {"dev": {"root": "infra/core/dev"}, "prod": {"root": "infra/core/prod"}},
    },
    "consent": {
        "name": "consent",
        "applied_by": "consent",
        "inputs": ["graph.permissions"],
        "tiers": {"prod": {"root": "infra/consent"}},
    },
    "identities": {
        "name": "identities",
        "apply": False,
        "tiers": {"prod": {"root": "infra/identities"}},
    },
    "runbooks": {
        "name": "runbooks",
        "applied_by": "runbooks",
        "watch": ["runbooks/"],
        "tiers": {"prod": {"root": "infra/runbooks"}},
    },
}


def plan(extra=()):
    return {
        "ran": True,
        "run_id": 5,
        "roots": [
            {
                "job": "terraform plan (consent prod)",
                "root": "consent",
                "tier": "prod",
                "summary": "Plan: 3 to add, 0 to change, 0 to destroy.",
            },
            {
                "job": "terraform plan (app prod)",
                "root": "app",
                "tier": "prod",
                "summary": "Plan: 0 to add, 2 to change, 3 to destroy.",
            },
            {
                "job": "terraform plan (core dev)",
                "root": "core",
                "tier": "dev",
                "summary": "Plan: 0 to add, 0 to change, 6 to destroy.",
            },
            {
                "job": "terraform plan (core prod)",
                "root": "core",
                "tier": "prod",
                "summary": "No changes. Your infrastructure matches the configuration.",
            },
        ],
        "resources": [
            {
                "root": "consent",
                "tier": "prod",
                "address": "azuread_app_role_assignment.a",
                "action": "create",
            },
            {
                "root": "consent",
                "tier": "prod",
                "address": "azurerm_role_assignment.b",
                "action": "create",
            },
            {
                "root": "consent",
                "tier": "prod",
                "address": "azuread_group_member.c",
                "action": "create",
            },
            {
                "root": "app",
                "tier": "prod",
                "address": "azurerm_role_assignment.old",
                "action": "destroy",
            },
            {"root": "app", "tier": "prod", "address": "azurerm_pool.p", "action": "update"},
        ]
        + list(extra),
    }


def landing(files, spec=SPEC, p=None):
    return pl.landing(pl.compact_plan(p or plan()), files, spec)


class Compaction(unittest.TestCase):
    def test_counts_and_resources(self):
        c = pl.compact_plan(plan())
        by = {(r["root"], r["tier"]): r for r in c["rows"]}
        self.assertEqual(
            (
                by[("app", "prod")]["add"],
                by[("app", "prod")]["change"],
                by[("app", "prod")]["destroy"],
            ),
            (0, 2, 3),
        )
        self.assertEqual(by[("core", "prod")]["destroy"], 0)
        self.assertEqual(len(c["resources"]), 5)
        self.assertIsNone(pl.compact_plan({"ran": False}))

    def test_plan_line_with_import_and_no_changes(self):
        self.assertEqual(
            pl.counts("Plan: 1 to import, 2 to add, 3 to change, 4 to destroy."), (2, 3, 4)
        )
        self.assertEqual(pl.counts("No changes"), (0, 0, 0))
        self.assertIsNone(pl.counts("log unavailable"))


class WhatLands(unittest.TestCase):
    def test_a_changed_input_lands_the_root_and_the_other_planned_roots_are_listed_as_not_applied(
        self,
    ):
        land = landing(["apps/hub/deploy.json", "apps/hub/src/index.ts"])
        self.assertEqual(land["status"], "ok")
        self.assertEqual([(r["root"], r["tier"]) for r in land["roots"]], [("consent", "prod")])
        r = land["roots"][0]
        self.assertEqual(
            (r["add"], r["grants"], r["entra"], r["applier"], r["gate"]),
            (3, 3, 2, "consent", "consent approval"),
        )
        self.assertIn("deploy.json", r["reason"])
        na = {(x["root"], x["tier"]): x for x in land["not_applied"]}
        self.assertIn(("app", "prod"), na)
        self.assertIn("this PR does not change", na[("app", "prod")]["reason"])
        self.assertIn("applied from the branch before the merge", na[("core", "dev")]["reason"])
        self.assertEqual(land["empty"], 1)  # core prod has no changes

    def test_a_shared_module_lands_an_app_root_and_a_destroy_names_the_destroy_gate(self):
        land = landing(["infra/modules/pool/main.tf"])
        r = [x for x in land["roots"] if x["root"] == "app"][0]
        self.assertIn("shared Terraform module", r["reason"])
        self.assertEqual((r["destroy"], r["gate"]), (3, "destroy approval"))
        self.assertEqual(r["destroys_named"], ["azurerm_role_assignment.old"])

    def test_the_apps_own_folder_lands_it(self):
        self.assertIn(
            "its own folder",
            [x for x in landing(["apps/app/main.tf"])["roots"] if x["root"] == "app"][0]["reason"],
        )

    def test_a_watched_path_lands_a_root(self):
        land = landing(["ops/core/manifest.json"])
        self.assertEqual([(r["root"], r["tier"]) for r in land["roots"]], [("core", "prod")])
        self.assertIn("watches", land["roots"][0]["reason"])

    def test_the_owner_applied_root_is_never_applied_by_the_merge(self):
        p = {
            "ran": True,
            "roots": [
                {
                    "job": "terraform plan (identities prod)",
                    "root": "identities",
                    "tier": "prod",
                    "summary": "Plan: 1 to add, 0 to change, 0 to destroy.",
                }
            ],
            "resources": [],
        }
        land = landing(["infra/identities/main.tf"], p=p)
        self.assertEqual(land["roots"], [])
        self.assertEqual(land["not_applied"][0]["applier"], "owner")
        self.assertIn("applies it by hand", land["not_applied"][0]["reason"])
        self.assertEqual(land["not_applied"][0]["gate"], "applied by hand")

    def test_an_unreadable_file_list_claims_nothing(self):
        land = pl.landing(pl.compact_plan(plan()), None, SPEC)
        self.assertEqual((land["status"], land["roots"]), ("unknown", []))
        self.assertTrue(pl.needs_confirm(land))
        self.assertIn("NOT KNOWN", pl.land_text(land))

    def test_no_plan_and_an_unread_plan(self):
        self.assertEqual(pl.landing(None, ["x"], SPEC)["status"], "no_plan")
        self.assertEqual(pl.landing(None, ["x"], SPEC, plan_unread=True)["status"], "plan_unread")

    def test_null_config_applies_nothing_extra(self):
        saved = os.environ["OPSCENTER_LANDING_CONFIG"]
        os.environ["OPSCENTER_LANDING_CONFIG"] = str(TMP / "absent.json")
        try:
            land = landing(["infra/modules/pool/main.tf"])
            self.assertEqual([x for x in land["roots"] if x["root"] == "app"], [])
            self.assertEqual(pl._gates(), {"tfapply": "none, the apply needs no approval"})
            self.assertEqual(
                (pl._apply_tier(), pl._shared_modules(), pl._destroy_gate()),
                ("prod", (), "destroy approval"),
            )
        finally:
            os.environ["OPSCENTER_LANDING_CONFIG"] = saved


def subject(lane="need", **over):
    s = {
        "lane": lane,
        "pr": 454,
        "title": "PRJ-101 consent for the hub",
        "author": "dev1",
        "branch": "PRJ-101-consent",
        "head": HEAD,
        "sources": ["review", "tfplan"],
        "kind": "policy",
        "counts": {"blocking": 0},
        "confirm_name_needed": "consent",
        "breakdown": {
            "rules": [
                {"rule": "consent", "reason": "Consent grant", "where": "apps/hub/deploy.json:14"}
            ],
            "risk": {"level": "medium", "why": "It grants application permissions."},
        },
        "rules": [
            {"rule": "consent", "plain": "Grants consent", "where": "apps/hub/deploy.json:14"}
        ],
        "findings": [
            {
                "id": "H1",
                "severity": "high",
                "title": "Wide scope",
                "location": "apps/hub/deploy.json:20",
            }
        ],
    }
    s.update(over)
    return s


class Card(unittest.TestCase):
    def setUp(self):
        self.land = landing(["apps/hub/deploy.json"])

    def test_the_owners_own_pr_card(self):
        st = pl.structure(subject("mine"), self.land)
        self.assertEqual(st["kind"], pl.KIND_OWN)
        self.assertIn("The merge then applies 1 root (consent prod).", st["ask"])
        self.assertEqual(
            {r["label"] for r in st["asked_by"]}, {"Author", "Branch", "Ticket", "Real source"}
        )
        self.assertEqual(
            [r["value"] for r in st["asked_by"] if r["label"] == "Ticket"], ["PRJ-101."]
        )
        self.assertTrue(st["confirm"]["required"])
        self.assertEqual(st["confirm"]["name"], "consent")
        self.assertIn("identity objects", st["confirm"]["why"])
        self.assertIn("Approve and merge re-checks the PR live", st["click"])
        self.assertTrue(any(r["kind"] == "finding" for r in st["why_rows"]))

    def test_the_engineer_card_names_the_optional_cover(self):
        st = pl.structure(subject("need"), self.land)
        self.assertEqual(st["kind"], pl.KIND_ENGINEER)
        self.assertFalse(st["confirm"]["required"])
        self.assertIn("Request changes", st["click"])
        self.assertIn("rates the risk medium", " ".join(st["risks"]))

    def test_no_name_field_when_nothing_destroys_or_grants_identity(self):
        land = landing(["apps/hub/x.ts"])
        self.assertNotIn("confirm", pl.structure(subject("mine"), land))
        self.assertFalse(pl.needs_confirm(land))

    def test_every_card_string_is_plain_ascii_without_banned_marks(self):
        for lane in ("mine", "need"):
            text = json.dumps(pl.structure(subject(lane), self.land))
            self.assertTrue(text.isascii())
            self.assertNotIn(";", text)

    def test_an_unreadable_file_list_is_named_as_a_risk(self):
        land = pl.landing(pl.compact_plan(plan()), None, SPEC)
        self.assertIn(
            "could not read the PR file list",
            " ".join(pl.structure(subject("need"), land)["risks"]),
        )


class Prose(unittest.TestCase):
    def test_a_brief_may_not_say_a_root_the_merge_does_not_apply_is_applied(self):
        land = landing(["apps/hub/deploy.json"])
        bad = {"does": "After the merge the app root is applied."}
        self.assertIn("does not apply", pl.check_prose(land, bad))
        ok = {"does": "The app root is not applied by this merge."}
        self.assertIsNone(pl.check_prose(land, ok))
        self.assertIsNone(
            pl.check_prose(landing(["x"], p={"ran": True, "roots": [], "resources": []}), bad)
        )


if __name__ == "__main__":
    unittest.main()
