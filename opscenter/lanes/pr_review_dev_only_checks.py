#!/usr/bin/env python3
"""
pr_review_dev_only_checks.py
Purpose: Tests for the 2026-10-20 review policy changes in pr_review.py: line rule
         path_exceptions (Flex FC1 plan and system-assigned identity under functions/<app>/infra/),
         dev_tier_only_waiver() (trust rules waived for dev-only new apps) and prod_wiring_hits()
         (first PR that adds the prod tier to an existing app). gh is faked. Never touches GitHub.
Date:    2026-10-20
Run:     /usr/bin/python3 <agent-home>/scripts/pr_review_dev_only_checks.py
"""

from __future__ import annotations

import importlib.util
import json
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
SCRATCH = tempfile.mkdtemp(prefix="oprho-", dir=os.environ.get("TMPDIR"))
os.environ["OPRG_STATE_DIR"] = SCRATCH
os.environ["OPRG_CACHE_DIR"] = SCRATCH
os.environ["OPRG_GH_BIN"] = "/usr/bin/false"
os.environ["OPRG_DRY_RUN"] = "1"

spec = importlib.util.spec_from_file_location("oprg_ho", str(HERE / "pr_review.py"))
eng = importlib.util.module_from_spec(spec)
sys.modules["oprg_ho"] = eng
spec.loader.exec_module(eng)

REPO = "owner/primary-repo"
HEAD = "a" * 40

LINE_RULES = [
    {
        "id": "new-app-service-plan",
        "pattern": '(resource\\s+"azurerm_(service_plan|app_service_plan)"\\s|Microsoft\\.Web/serverfarms@)',
        "reason": "creates an App Service plan",
        "path_exceptions": [
            {
                "path_regex": "^functions/[^/]+/infra/",
                "block_regex": '(sku_name|name)\\s*=\\s*"FC1"',
            }
        ],
    },
    {
        "id": "new-system-identity",
        "pattern": '^\\s*type\\s*=\\s*"(SystemAssigned|UserAssigned|SystemAssigned, ?UserAssigned)"',
        "reason": "adds a managed identity block",
        "path_exceptions": [
            {
                "path_regex": "^functions/[^/]+/infra/",
                "line_regex": '^\\s*type\\s*=\\s*"SystemAssigned"\\s*$',
            }
        ],
    },
]

POL = {
    "self_login": "owner-account",
    "line_rules": LINE_RULES,
    "scan_suffixes": [".tf"],
    "trust_rules": {
        "new_app_roots": ["apps", "functions"],
        "dev_tier_only": {
            "enabled": True,
            "prod_tier": "prod",
            "kinds": ["function-app", "app-service", "container-app"],
        },
    },
}


def diff_for(path, body):
    lines = body.strip("\n").splitlines()
    out = [
        f"diff --git a/{path} b/{path}",
        "--- /dev/null",
        f"+++ b/{path}",
        f"@@ -0,0 +1,{len(lines)} @@",
    ]
    return "\n".join(out + ["+" + x for x in lines]) + "\n"


PLAN_FC1 = """
resource "azurerm_service_plan" "func" {
  name     = "x-asp"
  os_type  = "Linux"
  sku_name = "FC1"
}
"""
PLAN_EP1 = PLAN_FC1.replace("FC1", "EP1")
SITE = """
resource "azapi_resource" "func" {
  type = "Microsoft.Web/sites@2024-04-01"
  identity {
    type = "SystemAssigned"
  }
}
"""


def rules(hits):
    return sorted(h["rule"] for h in hits)


class LineExceptions(unittest.TestCase):
    def test_fc1_plan_in_function_infra_is_exempt(self):
        p = "functions/relay/infra/main.tf"
        self.assertEqual(eng.policy_hits(POL, [p], diff_for(p, PLAN_FC1)), [])

    def test_other_sku_in_function_infra_still_hits(self):
        p = "functions/relay/infra/main.tf"
        self.assertEqual(
            rules(eng.policy_hits(POL, [p], diff_for(p, PLAN_EP1))), ["new-app-service-plan"]
        )

    def test_fc1_plan_outside_functions_still_hits(self):
        p = "apps/relay/infra/main.tf"
        self.assertEqual(
            rules(eng.policy_hits(POL, [p], diff_for(p, PLAN_FC1))), ["new-app-service-plan"]
        )

    def test_system_identity_in_function_infra_is_exempt(self):
        p = "functions/relay/infra/main.tf"
        self.assertEqual(eng.policy_hits(POL, [p], diff_for(p, SITE)), [])

    def test_user_assigned_in_function_infra_still_hits(self):
        p = "functions/relay/infra/main.tf"
        body = SITE.replace('"SystemAssigned"', '"SystemAssigned, UserAssigned"')
        self.assertEqual(
            rules(eng.policy_hits(POL, [p], diff_for(p, body))), ["new-system-identity"]
        )

    def test_system_identity_in_shared_root_still_hits(self):
        p = "infrastructure/terraform/shared-core/main.tf"
        self.assertEqual(
            rules(eng.policy_hits(POL, [p], diff_for(p, SITE))), ["new-system-identity"]
        )


def deploy(kind="function-app", tiers=("dev",)):
    return json.dumps({"tool": "relay", "kind": kind, "infra": {t: {"root": "x"} for t in tiers}})


class FakeGh:
    """Answers repos/<repo>/contents/<path>?ref=<ref> from {(path, ref): text}. Missing = 404."""

    def __init__(self, files, fail=()):
        self.files, self.fail, self.calls = files, set(fail), []

    def __call__(self, args, timeout=60, raw=False):
        self.calls.append(args)
        path, ref = args[1].split("/contents/", 1)[1].split("?ref=")
        if (path, ref) in self.fail:
            raise eng.GhError("api: rc=1 HTTP 502")
        if (path, ref) not in self.files:
            raise eng.GhError("gh: Not Found (HTTP 404)")
        return self.files[(path, ref)]


def with_gh(fake, fn, *a):
    orig = eng.gh
    eng.gh = fake
    try:
        return fn(*a)
    finally:
        eng.gh = orig


GREEN_PLAN = {
    "ran": True,
    "status": "completed",
    "conclusion": "success",
    "errors": [],
    "resources": [],
    "roots": [
        {"root": "relay", "tier": "dev", "parsed": True, "summary": "No changes"},
        {"root": "shared-core", "tier": "prod", "parsed": True, "summary": "No changes"},
    ],
}
TRUST = [
    {"rule": "new-app-first-pr", "reason": "x", "where": "functions/relay/"},
    {"rule": "new-contributor", "reason": "x", "where": "eng1"},
]
FILES = [
    "functions/relay/deploy.json",
    "functions/relay/function_app.py",
    "functions/relay/infra/main.tf",
    "docs/relay.md",
]


def waive(files=FILES, hits=TRUST, plan=GREEN_PLAN, gh_files=None, fail=(), pol=POL):
    gh_files = {("functions/relay/deploy.json", HEAD): deploy()} if gh_files is None else gh_files
    return with_gh(
        FakeGh(gh_files, fail), eng.dev_tier_only_waiver, pol, REPO, HEAD, files, list(hits), plan
    )


class Waiver(unittest.TestCase):
    def test_dev_tier_only_new_app_waives_both_trust_rules(self):
        hits, info = waive()
        self.assertEqual(hits, [])
        self.assertTrue(info["waived"])
        self.assertEqual(sorted(info["rules"]), ["new-app-first-pr", "new-contributor"])

    def test_other_rules_survive_the_waiver(self):
        extra = TRUST + [{"rule": "graph-app-role", "reason": "x", "where": "y"}]
        hits, info = waive(hits=extra)
        self.assertEqual(rules(hits), ["graph-app-role"])
        self.assertTrue(info["waived"])

    def test_file_outside_new_app_keeps_rules(self):
        hits, info = waive(files=FILES + ["shared/packages/ui/x.ts"])
        self.assertEqual(rules(hits), ["new-app-first-pr", "new-contributor"])
        self.assertFalse(info["waived"])

    def test_new_contributor_without_new_app_keeps_rule(self):
        hits, info = waive(hits=[TRUST[1]], files=["apps/vendor-b/server/a.js"])
        self.assertEqual(rules(hits), ["new-contributor"])
        self.assertFalse(info["waived"])

    def test_prod_tier_declared_keeps_rules(self):
        hits, info = waive(
            gh_files={("functions/relay/deploy.json", HEAD): deploy(tiers=("dev", "prod"))}
        )
        self.assertFalse(info["waived"])
        self.assertEqual(len(hits), 2)

    def test_web_client_kind_keeps_rules(self):
        hits, info = waive(
            gh_files={("functions/relay/deploy.json", HEAD): deploy(kind="web-client")}
        )
        self.assertFalse(info["waived"])

    def test_missing_deploy_json_keeps_rules(self):
        hits, info = waive(gh_files={})
        self.assertFalse(info["waived"])

    def test_deploy_json_read_error_keeps_rules(self):
        hits, info = waive(fail=[("functions/relay/deploy.json", HEAD)])
        self.assertFalse(info["waived"])

    def test_plan_running_waits_instead_of_escalating(self):
        hits, info = waive(plan=dict(GREEN_PLAN, status="in_progress"))
        self.assertEqual(hits, [])
        self.assertTrue(info["pending"])
        self.assertFalse(info["waived"])

    def test_plan_not_started_with_infra_waits(self):
        hits, info = waive(plan={"ran": False})
        self.assertEqual(hits, [])
        self.assertTrue(info["pending"])

    def test_plan_running_keeps_other_rules(self):
        extra = TRUST + [{"rule": "graph-app-role", "reason": "x", "where": "y"}]
        hits, info = waive(hits=extra, plan=dict(GREEN_PLAN, status="queued"))
        self.assertEqual(rules(hits), ["graph-app-role"])

    def test_plan_not_run_without_infra_keeps_rules(self):
        files = ["functions/relay/deploy.json", "functions/relay/function_app.py"]
        hits, info = waive(files=files, plan={"ran": False})
        self.assertEqual(len(hits), 2)
        self.assertFalse(info.get("pending"))

    def test_plan_finished_red_keeps_rules(self):
        hits, info = waive(plan=dict(GREEN_PLAN, conclusion="failure"))
        self.assertEqual(len(hits), 2)
        self.assertFalse(info.get("pending"))

    def test_plan_errors_keep_rules(self):
        hits, info = waive(plan=dict(GREEN_PLAN, errors=["boom"]))
        self.assertFalse(info["waived"])

    def test_prod_resource_in_plan_keeps_rules(self):
        res = [{"root": "shared-edge", "tier": "prod", "address": "x", "action": "create"}]
        hits, info = waive(plan=dict(GREEN_PLAN, resources=res))
        self.assertFalse(info["waived"])

    def test_prod_root_with_changes_keeps_rules(self):
        roots = [dict(GREEN_PLAN["roots"][1], summary="Plan: 1 to add, 0 to change, 0 to destroy.")]
        hits, info = waive(plan=dict(GREEN_PLAN, roots=roots))
        self.assertFalse(info["waived"])

    def test_unparsed_prod_root_keeps_rules(self):
        roots = [dict(GREEN_PLAN["roots"][1], parsed=False, summary="")]
        hits, info = waive(plan=dict(GREEN_PLAN, roots=roots))
        self.assertFalse(info["waived"])

    def test_disabled_changes_nothing(self):
        pol = dict(POL, trust_rules=dict(POL["trust_rules"], dev_tier_only={"enabled": False}))
        hits, info = waive(pol=pol)
        self.assertEqual(len(hits), 2)
        self.assertIsNone(info)

    # the owner 2026-10-20: dev-only branches do not come to him unless they affect primary.
    EXISTING = {
        ("functions/relay/deploy.json", HEAD): deploy(),
        ("functions/relay/deploy.json", "main"): deploy(),
    }

    def test_existing_dev_tier_only_app_waives_new_contributor(self):
        hits, info = waive(hits=[TRUST[1]], gh_files=self.EXISTING)
        self.assertEqual(hits, [])
        self.assertTrue(info["waived"])

    def test_app_resource_rules_are_waived(self):
        extra = [
            {"rule": r, "reason": "x", "where": "functions/relay/infra/main.tf:1"}
            for r in ("new-key-vault", "new-storage-account", "new-identity", "rbac-user-or-group")
        ]
        hits, info = waive(hits=extra, gh_files=self.EXISTING)
        self.assertEqual(hits, [])
        self.assertTrue(info["waived"])

    def test_tenant_wide_rules_survive(self):
        keep = (
            "graph-app-role",
            "federated-credential",
            "rbac-custom-role",
            "rbac-scope-outside-app",
            "postgres-aad-admin",
            "tfplan-matcher",
            "plan-destroy",
        )
        extra = [{"rule": r, "reason": "x", "where": "y"} for r in keep] + [TRUST[1]]
        hits, info = waive(hits=extra, gh_files=self.EXISTING)
        self.assertEqual(rules(hits), sorted(keep))

    def test_main_declares_prod_keeps_rules(self):
        gh = {
            ("functions/relay/deploy.json", HEAD): deploy(),
            ("functions/relay/deploy.json", "main"): deploy(tiers=("dev", "prod")),
        }
        hits, info = waive(hits=[TRUST[1]], gh_files=gh)
        self.assertEqual(rules(hits), ["new-contributor"])
        self.assertIn("on main", info["why"])

    def test_main_read_error_keeps_rules(self):
        hits, info = waive(
            hits=[TRUST[1]], gh_files=self.EXISTING, fail=[("functions/relay/deploy.json", "main")]
        )
        self.assertFalse(info["waived"])

    def test_two_apps_one_prod_keeps_rules(self):
        gh = dict(self.EXISTING)
        gh[("apps/vendor-b/deploy.json", HEAD)] = deploy(kind="app-service", tiers=("dev", "prod"))
        hits, info = waive(
            hits=[TRUST[1]], files=FILES + ["apps/vendor-b/server/a.js"], gh_files=gh
        )
        self.assertFalse(info["waived"])

    def test_approval_path_keeps_rules(self):
        pol = dict(POL, trust_rules=dict(POL["trust_rules"], approval_paths=["functions/relay/"]))
        hits, info = waive(pol=pol, gh_files=self.EXISTING)
        self.assertFalse(info["waived"])
        self.assertIn("approval path", info["why"])

    def test_only_kept_rules_means_no_waiver_info(self):
        hits, info = waive(
            hits=[{"rule": "graph-app-role", "reason": "x", "where": "y"}], gh_files=self.EXISTING
        )
        self.assertEqual(rules(hits), ["graph-app-role"])
        self.assertIsNone(info)

    # deploy.include guard: another app must not ship a dev-only folder to prod.
    def _with_includer(self, include, ref="main", where="deploy"):
        gh = dict(self.EXISTING)
        gh[("functions", ref)] = [
            {"type": "dir", "name": "relay"},
            {"type": "dir", "name": "prodapp"},
        ]
        body = {"kind": "function-app", "infra": {"dev": {}, "prod": {}}}
        if where == "deploy":
            body["deploy"] = {"include": include}
        else:
            body["include"] = include
        gh[("functions/prodapp/deploy.json", ref)] = json.dumps(body)
        return gh

    def test_prod_app_including_changed_file_keeps_rules(self):
        hits, info = waive(
            hits=[TRUST[1]], gh_files=self._with_includer(["functions/relay/function_app.py"])
        )
        self.assertEqual(rules(hits), ["new-contributor"])
        self.assertIn("via deploy.include", info["why"])

    def test_prod_app_including_parent_folder_keeps_rules(self):
        hits, info = waive(
            hits=[TRUST[1]], gh_files=self._with_includer(["functions/relay"], where="top")
        )
        self.assertFalse(info["waived"])

    def test_include_added_at_head_keeps_rules(self):
        hits, info = waive(
            hits=[TRUST[1]], gh_files=self._with_includer(["functions/relay/shared"], ref=HEAD)
        )
        self.assertFalse(info["waived"])

    def test_unrelated_include_still_waives(self):
        hits, info = waive(
            hits=[TRUST[1]], gh_files=self._with_includer(["runbooks/shared/lib.ps1"])
        )
        self.assertEqual(hits, [])
        self.assertTrue(info["waived"])

    def test_listing_error_keeps_rules(self):
        hits, info = waive(hits=[TRUST[1]], gh_files=self.EXISTING, fail=[("functions", "main")])
        self.assertFalse(info["waived"])
        self.assertIn("deploy.include", info["why"])

    def test_unreadable_other_deploy_json_keeps_rules(self):
        gh = self._with_includer([])
        gh[("functions/prodapp/deploy.json", "main")] = "{not json"
        hits, info = waive(hits=[TRUST[1]], gh_files=gh)
        self.assertFalse(info["waived"])


def wiring(files, gh_files, author="eng1", fail=()):
    return with_gh(FakeGh(gh_files, fail), eng.prod_wiring_hits, POL, REPO, author, files, HEAD)


class ProdWiring(unittest.TestCase):
    F = "functions/relay/deploy.json"

    def test_adding_prod_tier_hits(self):
        hits = wiring(
            [self.F], {(self.F, "main"): deploy(), (self.F, HEAD): deploy(tiers=("dev", "prod"))}
        )
        self.assertEqual(rules(hits), ["prod-wiring-first-pr"])

    def test_already_prod_is_clean(self):
        both = deploy(tiers=("dev", "prod"))
        self.assertEqual(wiring([self.F], {(self.F, "main"): both, (self.F, HEAD): both}), [])

    def test_new_app_is_left_to_new_app_rule(self):
        self.assertEqual(wiring([self.F], {(self.F, HEAD): deploy(tiers=("dev", "prod"))}), [])

    def test_read_error_fails_closed(self):
        hits = wiring([self.F], {(self.F, HEAD): deploy()}, fail=[(self.F, "main")])
        self.assertEqual(rules(hits), ["trust-check-failed"])

    def test_my_own_pr_skips(self):
        hits = wiring(
            [self.F],
            {(self.F, "main"): deploy(), (self.F, HEAD): deploy(tiers=("dev", "prod"))},
            "owner-account",
        )
        self.assertEqual(hits, [])

    def test_nested_deploy_json_ignored(self):
        self.assertEqual(wiring(["functions/relay/sub/deploy.json"], {}), [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
