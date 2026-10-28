#!/usr/bin/env python3
"""
pr_review_branch_drift_checks.py
Purpose: Tests for apply_branch_drift() in pr_review.py: dev tier destroys of a
         new app that another open <jira-key> branch applied to shared dev tier are branch drift, never
         on primary, never a replace, fail closed on read errors. Synthetic data, no GitHub.
Date:    2026-10-21
Run:     /usr/bin/python3 pr_review_branch_drift_checks.py
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
SCRATCH = tempfile.mkdtemp(prefix="oprdrift-", dir=os.environ.get("TMPDIR"))
os.environ["OPRG_STATE_DIR"] = SCRATCH
os.environ["OPRG_CACHE_DIR"] = SCRATCH
os.environ["OPRG_GH_BIN"] = "/usr/bin/false"
os.environ["OPRG_DRY_RUN"] = "1"

spec = importlib.util.spec_from_file_location("oprg_drift", str(HERE / "pr_review.py"))
eng = importlib.util.module_from_spec(spec)
sys.modules["oprg_drift"] = eng
spec.loader.exec_module(eng)

POL = {
    "trust_rules": {"new_app_roots": ["apps", "functions"], "dev_tier_only": {"prod_tier": "prod"}}
}
REPO = "o/r"
HEAD = "f" * 40
APPS = {"jsm-mail-relay": ("functions", 434, "ticket-id-jsm-mail-relay")}
JOSH = [
    'azurerm_api_management_api.app["jsm-mail-relay"]',
    'azapi_resource.app_secret_generated["jsm-mail-relay-forge-inbound-secret"]',
    'random_password.app_secret["jsm-mail-relay-graph-client-state"]',
]
CRED = 'azurerm_federated_identity_credential.tfplan["gh-pull-request"]'


def res(addr, tier="dev", action="destroy", root="shared-core"):
    return {"root": root, "tier": tier, "address": addr, "action": action, "attrs": [], "names": []}


def plan(resources):
    d = [r["address"] for r in resources if r["action"] == "destroy"]
    roots = {}
    for r in resources:
        k = (r["root"], r["tier"])
        roots.setdefault(k, {"root": r["root"], "tier": r["tier"], "destroy": 0, "parsed": True})
        if r["action"] == "destroy":
            roots[k]["destroy"] += 1
    return {
        "ran": True,
        "status": "completed",
        "destroy": len(d),
        "destroyed": d,
        "resources": resources,
        "roots": list(roots.values()),
        "replaced": [],
    }


def absent(owner_repo, path, ref):
    return None


def present(owner_repo, path, ref):
    return "{}"


def run(p, apps=APPS, file_at=absent, pol=POL):
    return eng.apply_branch_drift(pol, REPO, 436, HEAD, p, branch_apps=apps, file_at=file_at)


class DriftTests(unittest.TestCase):
    def test_josh_pieces_are_drift_credential_stays(self):
        out = run(plan([res(a) for a in JOSH] + [res(CRED)]))
        self.assertEqual(out["destroyed"], [CRED])
        self.assertEqual(out["destroy"], 1)
        self.assertEqual(len(out["branch_drift"]), 3)
        self.assertEqual(out["branch_drift"][0]["pr"], 434)
        self.assertEqual(out["roots"][0]["destroy"], 1)

    def test_all_drift_means_no_destroy(self):
        out = run(plan([res(a) for a in JOSH]))
        self.assertEqual(out["destroyed"], [])
        self.assertEqual(out["destroy"], 0)

    def test_prod_is_never_drift(self):
        out = run(plan([res(a, tier="prod") for a in JOSH]))
        self.assertEqual(len(out["destroyed"]), 3)
        self.assertNotIn("branch_drift", out)

    def test_prod_tier_named_dev_tier_disables(self):
        pol = {
            "trust_rules": {"new_app_roots": ["functions"], "dev_tier_only": {"prod_tier": "dev"}}
        }
        out = run(plan([res(a) for a in JOSH]), pol=pol)
        self.assertEqual(len(out["destroyed"]), 3)

    def test_replace_is_never_drift(self):
        p = plan([res(JOSH[0], action="replace")])
        p["destroyed"] = [JOSH[0]]
        out = run(p)
        self.assertEqual(out["destroyed"], [JOSH[0]])

    def test_same_address_on_prod_too_keeps_both(self):
        out = run(plan([res(JOSH[0]), res(JOSH[0], tier="prod")]))
        self.assertEqual(len(out["destroyed"]), 2)

    def test_no_open_owner_is_real(self):
        out = run(plan([res(a) for a in JOSH]), apps={})
        self.assertEqual(len(out["destroyed"]), 3)

    def test_app_present_at_head_is_real(self):
        out = run(plan([res(a) for a in JOSH]), file_at=present)
        self.assertEqual(len(out["destroyed"]), 3)

    def test_prefix_needs_dash_boundary(self):
        out = run(plan([res('azurerm_api_management_api.app["jsm-mail-relayx"]')]))
        self.assertEqual(len(out["destroyed"]), 1)

    def test_longest_app_wins(self):
        apps = {
            "jsm": ("functions", 1, "ticket-id-a"),
            "jsm-mail-relay": ("functions", 434, "ticket-id-b"),
        }
        out = run(plan([res(JOSH[1])]), apps=apps)
        self.assertEqual(out["branch_drift"][0]["app"], "jsm-mail-relay")

    def test_read_error_fails_closed(self):
        def boom(*a):
            raise eng.GhError("rc=1 boom")

        out = run(plan([res(a) for a in JOSH]), file_at=boom)
        self.assertEqual(len(out["destroyed"]), 3)
        self.assertIn("branch_drift_error", out)

    def test_unkeyed_destroy_is_real(self):
        out = run(plan([res("azurerm_storage_account.this")]))
        self.assertEqual(out["destroyed"], ["azurerm_storage_account.this"])

    def test_no_destroys_untouched(self):
        p = plan([res(JOSH[0], action="create")])
        self.assertIs(run(p), p)

    def test_open_branch_apps_filters(self):
        calls = []

        def fake_gh(args, timeout=60, raw=False):
            calls.append(args[2])
            if "pulls?state=open" in args[2]:
                return "\n".join(
                    [
                        '{"number": 434, "head": {"ref": "ticket-id-jsm-mail-relay", "repo": {"full_name": "o/r"}}}',
                        '{"number": 436, "head": {"ref": "ticket-id-x", "repo": {"full_name": "o/r"}}}',
                        '{"number": 500, "head": {"ref": "dependabot/x", "repo": {"full_name": "o/r"}}}',
                        '{"number": 501, "head": {"ref": "ticket-id-fork", "repo": {"full_name": "fork/r"}}}',
                    ]
                )
            if "pulls/434/files" in args[2]:
                return (
                    "functions/jsm-mail-relay/deploy.json\nfunctions/jsm-mail-relay/infra/main.tf\n"
                )
            raise AssertionError(args)

        real = eng.gh
        eng.gh = fake_gh
        try:
            apps = eng._open_branch_apps(REPO, 436, {"functions", "apps"})
        finally:
            eng.gh = real
        self.assertEqual(apps, {"jsm-mail-relay": ("functions", 434, "ticket-id-jsm-mail-relay")})
        self.assertFalse(
            any("pulls/500" in c or "pulls/501" in c or "pulls/436" in c for c in calls)
        )


if __name__ == "__main__":
    unittest.main(verbosity=1)
