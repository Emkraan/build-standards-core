#!/usr/bin/env python3
# =====================================================================
# maintenance_window_test.py
# Purpose: Synthetic tests for the maintenance window lane module: the downtime
#          classifier, the window math for both change classes (standard and
#          restricted), DST, and the PR comment wording. Never calls the code host.
#          Run: python3 -m unittest opscenter/lanes/maintenance_window_test.py
# =====================================================================
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
POL = json.loads((HERE / "fixtures" / "maintenance-policy.json").read_text())


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mw = _load("maintenance_window", HERE / "maintenance_window.py")
CFG = POL["maintenance_window"]
ET = mw.ZoneInfo("America/New_York")
UTC = dt.timezone.utc


def et(y, m, d, hh, mm=0):
    """A New York wall time as an aware UTC datetime."""
    return dt.datetime(y, m, d, hh, mm, tzinfo=ET).astimezone(UTC)


SPECS = [
    {
        "tool": "vendor-b",
        "kind": "app-service",
        "edge": {"apim": {"display_name": {"dev": "vendor-b"}}},
        "deploy": {"app_path": "apps/vendor-b", "watch": ["server/**", "package.json"]},
        "_dir": "apps/vendor-b",
        "_file": "apps/vendor-b/deploy.json",
    },
    {
        "tool": "console",
        "kind": "app-service",
        "edge": {"apim": {"display_name": {"prod": "platform Console API"}}},
        "deploy": {"app_path": "apps/platform-shell", "watch": ["server/**", "package.json"]},
        "_dir": "apps/platform-shell",
        "_file": "apps/platform-shell/deploy.json",
    },
    {
        "tool": "app-b-console",
        "kind": "web-client",
        "_dir": "apps/app-b-console",
        "_file": "apps/app-b-console/deploy.json",
    },
    {
        "tool": "app-e",
        "kind": "desktop-agent",
        "_dir": "apps/app-e",
        "_file": "apps/app-e/deploy.json",
    },
    {
        "tool": "jobs",
        "kind": "function-app",
        "deploy": {"app_path": "apps/jobs", "watch": ["src/**"]},
        "_dir": "apps/jobs",
        "_file": "apps/jobs/deploy.json",
    },
]


def plan_with(resources, roots=None):
    roots = roots or [
        {
            "job": "terraform plan (vendor-b platform)",
            "root": "vendor-b",
            "tier": "prod",
            "conclusion": "success",
            "parsed": True,
            "summary": "Plan: 0 to add, 1 to change, 0 to destroy.",
        }
    ]
    return {
        "ran": True,
        "status": "completed",
        "roots": roots,
        "resources": resources,
        "run_url": "https://example.invalid/run/1",
    }


NO_PLAN = {"ran": False, "note": "terraform-ci did not run"}


class Classifier(unittest.TestCase):
    def hits(self, files, plan=NO_PLAN, specs=SPECS, err=None):
        return mw.classify(POL, files, plan, specs, err)

    def test_app_service_code_change_is_downtime(self):
        h = self.hits(["apps/vendor-b/server/src/index.ts"])
        self.assertEqual([x["system"] for x in h], ["vendor-b"])
        self.assertIn(
            "deploys the vendor-b API, which restarts it for a few seconds", h[0]["reason"]
        )

    def test_console_name(self):
        h = self.hits(["apps/platform-shell/package.json"])
        self.assertIn("platform Console API", h[0]["reason"])

    def test_function_app_is_downtime(self):
        h = self.hits(["apps/jobs/src/a.py"])
        self.assertEqual(h[0]["system"], "jobs")

    def test_web_client_only_is_not(self):
        self.assertEqual(
            self.hits(["apps/app-b-console/client/src/App.tsx", "web/src/main.tsx"]), []
        )

    def test_client_folder_of_app_service_is_not(self):
        self.assertEqual(self.hits(["apps/vendor-b/client/src/App.tsx"]), [])

    def test_docs_only_is_not(self):
        self.assertEqual(
            self.hits(["apps/vendor-b/server/README.md", "docs/adr/0009.md", "README.md"]), []
        )

    def test_desktop_agent_is_not(self):
        self.assertEqual(self.hits(["apps/app-e/agent/main.go"]), [])

    def test_shared_packages_redeploy_every_restarting_app(self):
        h = self.hits(["shared/packages/auth/index.ts"])
        self.assertEqual(sorted(x["system"] for x in h), ["console", "jobs", "vendor-b"])

    def test_kind_pipeline_file_redeploys_that_kind(self):
        h = self.hits([".github/workflows/_deploy-app-service.yml"])
        self.assertEqual(sorted(x["system"] for x in h), ["console", "vendor-b"])

    def test_runbooks_are_not(self):
        self.assertEqual(self.hits(["runbooks/Invoke-Thing.ps1"]), [])

    def test_logic_apps_off_until_enabled(self):
        self.assertEqual(self.hits(["logic-apps/flow/workflow.json"]), [])
        pol = json.loads(json.dumps(POL))
        pol["maintenance_window"]["extra_deploys"][0]["enabled"] = True
        h = mw.classify(pol, ["logic-apps/flow/workflow.json"], NO_PLAN, SPECS, None)
        self.assertEqual(h[0]["system"], "automation-logic")

    def test_unreadable_deploy_map_is_downtime_with_unknown_system(self):
        h = self.hits(["apps/vendor-b/client/x.ts"], specs=[], err=ValueError("boom"))
        self.assertEqual(h[0]["kind"], "deploy-map-unreadable")
        self.assertEqual(mw.change_class(POL, h), "both")

    def test_unreadable_deploy_map_docs_only_is_not(self):
        self.assertEqual(self.hits(["README.md"], specs=[], err=ValueError("boom")), [])

    def test_terraform_replace_of_app_service_is_downtime(self):
        p = plan_with(
            [
                {
                    "root": "vendor-b",
                    "tier": "prod",
                    "address": "azurerm_linux_web_app.vendor-b",
                    "action": "replace",
                    "attrs": [],
                    "names": [],
                }
            ]
        )
        h = self.hits(["apps/vendor-b/infra/main.tf"], p)
        self.assertEqual(h[0]["kind"], "tf-replace")
        self.assertIn("replaces the App Service app", h[0]["reason"])

    def test_terraform_delete_of_postgres_database_in_module(self):
        addr = 'module.db.azurerm_postgresql_flexible_server_database.this["vendor-b"]'
        p = plan_with(
            [
                {
                    "root": "platform-core",
                    "tier": "prod",
                    "address": addr,
                    "action": "destroy",
                    "attrs": [],
                    "names": [],
                }
            ]
        )
        h = self.hits(["infrastructure/terraform/platform-core/platform/main.tf"], p)
        self.assertEqual(h[0]["kind"], "tf-destroy")
        self.assertIn("Postgres database", h[0]["reason"])

    def test_terraform_restart_attribute(self):
        p = plan_with(
            [
                {
                    "root": "vendor-b",
                    "tier": "prod",
                    "address": "azurerm_linux_web_app.vendor-b",
                    "action": "update",
                    "attrs": ["virtual_network_subnet_id"],
                    "names": ["prod-prefix-vendor-b-api"],
                }
            ]
        )
        h = self.hits(["apps/vendor-b/infra/main.tf"], p)
        self.assertEqual(h[0]["kind"], "tf-restart")

    def test_terraform_tag_only_update_is_not(self):
        p = plan_with(
            [
                {
                    "root": "vendor-b",
                    "tier": "prod",
                    "address": "azurerm_linux_web_app.vendor-b",
                    "action": "update",
                    "attrs": ["tags"],
                    "names": [],
                }
            ]
        )
        self.assertEqual(self.hits(["apps/vendor-b/infra/main.tf"], p), [])

    def test_postgres_static_parameter(self):
        p = plan_with(
            [
                {
                    "root": "platform-core",
                    "tier": "prod",
                    "address": "azurerm_postgresql_flexible_server_configuration.x",
                    "action": "update",
                    "attrs": ["value"],
                    "names": ["shared_preload_libraries"],
                }
            ]
        )
        self.assertEqual(self.hits(["a.tf"], p)[0]["kind"], "tf-restart")
        p2 = plan_with(
            [
                {
                    "root": "platform-core",
                    "tier": "prod",
                    "address": "azurerm_postgresql_flexible_server_configuration.x",
                    "action": "update",
                    "attrs": ["value"],
                    "names": ["log_min_duration_statement"],
                }
            ]
        )
        self.assertEqual(self.hits(["a.tf"], p2), [])

    def test_dev_tier_only_is_not(self):
        p = plan_with(
            [
                {
                    "root": "vendor-b",
                    "tier": "dev",
                    "address": "azurerm_linux_web_app.vendor-b",
                    "action": "replace",
                    "attrs": [],
                    "names": [],
                }
            ],
            roots=[
                {
                    "job": "terraform plan (vendor-b dev-tier)",
                    "root": "vendor-b",
                    "tier": "dev",
                    "conclusion": "success",
                    "parsed": True,
                }
            ],
        )
        self.assertEqual(self.hits(["apps/vendor-b/infra/main.tf"], p), [])

    def test_unreadable_plan_is_downtime(self):
        p = plan_with(
            [],
            roots=[
                {
                    "job": "terraform plan (vendor-b platform)",
                    "root": "vendor-b",
                    "tier": "prod",
                    "conclusion": "success",
                    "parsed": False,
                    "summary": "log unavailable",
                }
            ],
        )
        h = self.hits(["apps/vendor-b/infra/main.tf"], p)
        self.assertEqual(h[0]["kind"], "plan-unreadable")
        self.assertEqual(h[0]["system"], "vendor-b")

    def test_terraform_files_without_a_plan_fail_closed(self):
        h = self.hits(["apps/vendor-b/infra/main.tf"], NO_PLAN)
        self.assertEqual(h[0]["kind"], "plan-unreadable")
        self.assertEqual(mw.change_class(POL, h), "both")

    def test_plan_still_running_fails_closed(self):
        h = self.hits(["a.tf"], {"ran": True, "status": "in_progress", "roots": []})
        self.assertEqual(h[0]["kind"], "plan-unreadable")

    def test_azapi_patch_is_downtime(self):
        p = plan_with(
            [
                {
                    "root": "platform-core",
                    "tier": "prod",
                    "address": "azapi_update_resource.pg",
                    "action": "create",
                    "attrs": [],
                    "names": [],
                }
            ]
        )
        self.assertEqual(self.hits(["a.tf"], p)[0]["kind"], "tf-patch")

    def test_restricted_class_from_policy(self):
        h = self.hits(["apps/vendor-b/server/a.ts"])
        self.assertEqual(mw.change_class(POL, h), "standard")
        pol = json.loads(json.dumps(POL))
        pol["maintenance_window"]["restricted_systems"] = ["vendor-b"]
        self.assertEqual(mw.change_class(pol, h), "restricted")

    def test_restricted_systems_is_empty_today(self):
        self.assertEqual(POL["maintenance_window"]["restricted_systems"], [])


class TierSkip(unittest.TestCase):
    """<improvement-id> on main: an app whose deploy target declares infra without an <platform> tier never
    deploys to <platform>, so a push to main does not take it down. No or odd infra counts (fail closed)."""

    def specs(self, infra):
        d = {
            "tool": "relay",
            "kind": "function-app",
            "deploy": {
                "app_path": "functions/relay",
                "watch": ["src/**"],
                "include": ["runbooks/shared/"],
            },
            "_dir": "functions/relay",
            "_file": "functions/relay/deploy.json",
        }
        if infra is not None:
            d["infra"] = infra
        return [d]

    def tools(self, files, infra, tier="prod"):
        return [d["tool"] for d in mw.deployed_apps(files, self.specs(infra), tier=tier)]

    def test_dev_tier_only_app_skips_platform(self):
        self.assertEqual(self.tools(["functions/relay/src/a.ps1"], {"dev": {}}), [])

    def test_dev_tier_only_app_still_deploys_dev_tier(self):
        self.assertEqual(
            self.tools(["functions/relay/src/a.ps1"], {"dev": {}}, tier="dev"), ["relay"]
        )

    def test_platform_app_deploys(self):
        self.assertEqual(
            self.tools(["functions/relay/src/a.ps1"], {"dev": {}, "prod": {}}), ["relay"]
        )

    def test_missing_infra_counts(self):
        self.assertEqual(self.tools(["functions/relay/src/a.ps1"], None), ["relay"])

    def test_include_path_deploys(self):
        self.assertEqual(self.tools(["runbooks/shared/util.ps1"], {"prod": {}}), ["relay"])

    def test_include_sibling_does_not(self):
        self.assertEqual(self.tools(["runbooks/sharedx/util.ps1"], {"prod": {}}), [])

    def test_own_deploy_json_deploys(self):
        self.assertEqual(self.tools(["functions/relay/deploy.json"], {"prod": {}}), ["relay"])


class Windows(unittest.TestCase):
    # 2026-10-19 is a Monday.
    def test_standard_monday_night(self):
        self.assertFalse(mw.in_window(CFG, "standard", et(2026, 10, 19, 20, 59)))
        self.assertTrue(mw.in_window(CFG, "standard", et(2026, 10, 19, 21, 0)))
        self.assertTrue(mw.in_window(CFG, "standard", et(2026, 10, 20, 5, 59)))
        self.assertFalse(mw.in_window(CFG, "standard", et(2026, 10, 20, 6, 0)))

    def test_standard_friday_night_into_saturday(self):
        self.assertTrue(mw.in_window(CFG, "standard", et(2026, 10, 24, 5, 59)))
        self.assertFalse(mw.in_window(CFG, "standard", et(2026, 10, 24, 6, 0)))

    def test_standard_saturday_daytime_waits_for_monday(self):
        now = et(2026, 10, 24, 12, 0)
        self.assertFalse(mw.in_window(CFG, "standard", now))
        self.assertEqual(mw.next_open(CFG, "standard", now)[0], et(2026, 10, 26, 21, 0))
        self.assertFalse(mw.in_window(CFG, "standard", et(2026, 10, 24, 23, 0)))
        self.assertFalse(mw.in_window(CFG, "standard", et(2026, 10, 25, 22, 0)))
        self.assertEqual(
            mw.window_phrase(CFG, "standard", now),
            "the next standard window, Monday at 9:00 PM Eastern",
        )

    def test_standard_tonight_phrase(self):
        self.assertEqual(
            mw.window_phrase(CFG, "standard", et(2026, 10, 19, 10, 0)),
            "the next standard window, tonight at 9:00 PM Eastern",
        )

    def test_restricted_monday_waits_for_thursday(self):
        now = et(2026, 10, 19, 10, 0)
        self.assertFalse(mw.in_window(CFG, "restricted", now))
        self.assertEqual(mw.next_open(CFG, "restricted", now)[0], et(2026, 10, 22, 22, 0))
        self.assertEqual(
            mw.window_phrase(CFG, "restricted", now),
            "the next restricted window, Thursday at 10:00 PM Eastern",
        )

    def test_restricted_edges(self):
        self.assertFalse(mw.in_window(CFG, "restricted", et(2026, 10, 22, 21, 59)))
        self.assertTrue(mw.in_window(CFG, "restricted", et(2026, 10, 22, 22, 0)))
        self.assertTrue(
            mw.in_window(CFG, "restricted", et(2026, 10, 25, 3, 59))
        )  # Saturday night into Sunday
        self.assertFalse(mw.in_window(CFG, "restricted", et(2026, 10, 25, 4, 0)))
        self.assertFalse(
            mw.in_window(CFG, "restricted", et(2026, 10, 21, 23, 0))
        )  # Wednesday night

    def test_both_is_the_intersection(self):
        self.assertFalse(
            mw.in_window(CFG, "both", et(2026, 10, 24, 23, 0))
        )  # Saturday night: restricted only
        self.assertFalse(
            mw.in_window(CFG, "both", et(2026, 10, 19, 22, 0))
        )  # Monday night: non-restricted only
        self.assertTrue(mw.in_window(CFG, "both", et(2026, 10, 22, 23, 0)))  # Thursday night: both
        self.assertFalse(
            mw.in_window(CFG, "both", et(2026, 10, 23, 4, 30))
        )  # restricted closed at 04:00
        self.assertEqual(
            mw.next_open(CFG, "both", et(2026, 10, 19, 10, 0))[0], et(2026, 10, 22, 22, 0)
        )

    def test_dst_fall_back(self):
        # 2026-11-01 02:00 EDT falls back to 01:00 EST. Saturday 10/31 22:00 EDT to Sunday 04:00 EST.
        s, e = mw.current(CFG, "restricted", dt.datetime(2026, 11, 1, 8, 30, tzinfo=UTC))
        self.assertEqual(s, dt.datetime(2026, 11, 1, 2, 0, tzinfo=UTC))
        self.assertEqual(e, dt.datetime(2026, 11, 1, 9, 0, tzinfo=UTC))
        self.assertFalse(
            mw.in_window(CFG, "restricted", dt.datetime(2026, 11, 1, 9, 0, tzinfo=UTC))
        )

    def test_dst_spring_forward(self):
        # 2027-03-14 02:00 EST jumps to 03:00 EDT. Saturday 3/13 22:00 EST to Sunday 04:00 EDT.
        s, e = mw.current(CFG, "restricted", dt.datetime(2027, 3, 14, 7, 30, tzinfo=UTC))
        self.assertEqual(s, dt.datetime(2027, 3, 14, 3, 0, tzinfo=UTC))
        self.assertEqual(e, dt.datetime(2027, 3, 14, 8, 0, tzinfo=UTC))
        # The Monday after, the standard window opens at 21:00 EDT = 01:00Z.
        self.assertEqual(
            mw.next_open(CFG, "standard", dt.datetime(2027, 3, 15, 12, 0, tzinfo=UTC))[0],
            dt.datetime(2027, 3, 16, 1, 0, tzinfo=UTC),
        )

    def test_stale_after_a_full_window(self):
        held = et(2026, 10, 19, 10, 0)
        self.assertFalse(mw.stale(CFG, "standard", held, et(2026, 10, 20, 6, 20)))
        self.assertTrue(mw.stale(CFG, "standard", held, et(2026, 10, 20, 6, 31)))

    def test_naive_now_refused(self):
        with self.assertRaises(ValueError):
            mw.in_window(CFG, "restricted", dt.datetime(2026, 10, 19, 10, 0))

    def test_comment_wording(self):
        h = mw.classify(POL, ["apps/vendor-b/server/a.ts"], NO_PLAN, SPECS)
        body = mw.pr_comment(CFG, "standard", h, et(2026, 10, 19, 10, 0))
        self.assertIn("Approved.", body)
        self.assertIn("vendor-b API", body)
        self.assertIn("next standard window, tonight at 9:00 PM Eastern", body)
        self.assertNotIn(";", body)
        self.assertNotIn("\u2014", body)
        body.encode("ascii")
