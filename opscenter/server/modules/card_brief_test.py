"""
card_brief_test.py
Purpose: Tests for the approval brief on non-PR Reviews cards (card_brief.py) and the Terraform facts
         behind it (tf_context.py): plan parsing, plain resource sentences (identity, role, scope,
         what the access allows), the open-PR overlap check on the same root (including a PR that
         deletes what the plan would create, the synthetic case), fail-closed status when the PR list
         cannot be read, the deterministic warning and drafts for Owner, privileged and release
         cards, the gate that keeps the model from writing before the overlap check is current,
         and the rule that a model brief must name every overlapping PR. Synthetic data, fake git,
         gh behind _run and a provider file, and a scratch cache only. Nothing reaches GitHub, a cloud or a model.
Date:    2026-10-15
Run:     python3 card_brief_test.py
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="card-brief-"))
os.environ["APPROVAL_BRIEF_STORE"] = str(TMP / "approval-briefs.json")
os.environ["APPROVAL_BRIEF_WORK"] = str(TMP / "work")
os.environ["APPROVAL_BRIEF_TIERS"] = "dev-tier,platform"
os.environ["OPRG_GH_BIN"] = "/fake/gh"
os.environ["TF_CONTEXT_CACHE"] = str(TMP / "ctx")
os.environ["TF_CONTEXT_GIT"] = "/fake/git"
os.environ["TF_CONTEXT_PROVIDER"] = f"{TMP / 'ctx-provider.py'}:P"
os.environ["OPSCENTER_REVIEWS_CONFIG"] = str(TMP / "reviews-config.json")
os.environ["CARD_BRIEF_DATA"] = str(TMP / "card-brief-data.json")
os.environ["OWNER_ROOTS_CACHE"] = str(TMP / "owner-roots")
sys.path.insert(0, str(Path(__file__).resolve().parent))
(TMP / "reviews-config.json").write_text(
    json.dumps({"owner": "owner1", "plan_repo": "acme/infra", "other_repo": "acme/app"})
)
(TMP / "ctx-provider.py").write_text(
    "class P:\n    def resolve_principal(self, pid):\n"
    "        return {'name': 'Synthetic Publisher', 'kind': 'service principal'} if pid == '11111111-1111-4111-8111-111111111111' else None\n"
)
(TMP / "card-brief-data.json").write_text(
    json.dumps(
        {
            "admin": "owner-admin-account",
            "auto_rule": "improvement-id",
            "root_why": {
                "state-backend": "it manages the storage that holds every Terraform state file and decides which identities can read or write that state",
                "pipeline-identities": "it creates the pipeline identities themselves and the access they hold",
            },
            "env_why": {
                "governance": "The governance environment guards roots that set policy and identity, so only you approve them.",
                "destroy": "The Destroy environment guards Terraform runs that delete resources, so only you release them.",
            },
            "tier_plain": {
                "dev": "dev-tier tier (the dev tier)",
                "prod": "platform tier (the production tier)",
            },
            "image_gate_envs": ["image-build"],
            "release_envs": ["app-build", "app-release"],
            "release_target": "the synthetic automation account",
            "release_workflow": "deploy-runbooks",
            "host_group_roles": ["virtual machine user login"],
            "host_resource_groups": ["pool-rg"],
            "host_vm_prefix": "host-",
        }
    )
)

import approval_brief as ab  # noqa: E402
import card_brief as cb  # noqa: E402
import tf_context as tc  # noqa: E402

_ENV = {
    "APPROVAL_BRIEF_STORE": os.environ["APPROVAL_BRIEF_STORE"],
    "APPROVAL_BRIEF_WORK": os.environ["APPROVAL_BRIEF_WORK"],
    "APPROVAL_BRIEF_TIERS": os.environ["APPROVAL_BRIEF_TIERS"],
    "OPRG_GH_BIN": os.environ["OPRG_GH_BIN"],
    "TF_CONTEXT_CACHE": os.environ["TF_CONTEXT_CACHE"],
    "TF_CONTEXT_GIT": os.environ["TF_CONTEXT_GIT"],
    "TF_CONTEXT_PROVIDER": os.environ["TF_CONTEXT_PROVIDER"],
    "OPSCENTER_REVIEWS_CONFIG": os.environ["OPSCENTER_REVIEWS_CONFIG"],
    "CARD_BRIEF_DATA": os.environ["CARD_BRIEF_DATA"],
    "OWNER_ROOTS_CACHE": os.environ["OWNER_ROOTS_CACHE"],
}


def setUpModule():
    # the whole suite shares one interpreter: re-point the modules at this file's scratch tree
    os.environ.update(_ENV)
    ab.STORE, ab.WORK, ab.GH = TMP / "approval-briefs.json", TMP / "work", "/fake/gh"
    tc.CACHE, tc.GIT, tc.GH, tc.OWNER_LOGS = (
        TMP / "ctx",
        "/fake/git",
        "/fake/gh",
        TMP / "owner-roots" / "logs",
    )
    cb.PRIV_PLANS = TMP / "owner-roots" / "plans"


PID = "11111111-1111-4111-8111-111111111111"
SUB = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
ROOT = "infra/terraform/state-backend"
PLAN_SHA = "f" * 64
MAIN = "c" * 40

PLAN_LOG = f"""plan state-backend:dev at 2026-10-15T10:00:00Z
Terraform will perform the following actions:

  # azurerm_monitor_scheduled_query_rules_alert_v2.state_access will be updated in-place
  ~ resource "azurerm_monitor_scheduled_query_rules_alert_v2" "state_access" {{
        name = "devstate-unexpected-access"
      ~ criteria {{
          ~ query = <<-EOT
              - | where RequesterObjectId !in (dynamic(["{OTHER}"]))
              + | where RequesterObjectId !in (dynamic(["{OTHER}","{PID}"]))
            EOT
        }}
    }}

  # azurerm_role_assignment.state["synthetic-publisher"] will be created
  + resource "azurerm_role_assignment" "state" {{
      + condition            = "(@Resource[x:path] StringStartsWith 'runbooks/')"
      + description          = "Terraform state (synthetic-publisher): runbooks/ only"
      + principal_id         = "{PID}"
      + role_definition_name = "Storage Blob Data Contributor"
      + scope                = "/subscriptions/{SUB}/resourceGroups/dev/providers/Microsoft.Storage/storageAccounts/devstate/blobServices/default/containers/tfstate"
    }}

Plan: 1 to add, 1 to change, 0 to destroy.
"""

ROOTS_JSON = json.dumps(
    {
        "state_backend": {},
        "roots": [
            {
                "name": "state-backend",
                "applied_by": "owner",
                "tiers": {"dev": {"root": ROOT, "key": "sb/dev", "vars": "dev.tfvars"}},
            },
            {
                "name": "runbooks",
                "applied_by": "runbooks",
                "tiers": {"prod": {"root": "infra/terraform/runbooks", "key": "rb", "vars": ""}},
            },
            {
                "name": "entra-consent",
                "applied_by": "entra-privileged",
                "tiers": {"prod": {"root": "infra/entra-consent", "key": "ec", "vars": ""}},
            },
        ],
    }
)

MAIN_TF = """locals {
  # grantees:
  #   synthetic-publisher the synthetic runbook deploy: runbooks/ only
  grants = {
    "synthetic-publisher" = { principal_id = "44444444-4444-4444-8444-444444444444" }
  }
}
"""

PR_DIFF = f'''diff --git a/{ROOT}/main.tf b/{ROOT}/main.tf
--- a/{ROOT}/main.tf
+++ b/{ROOT}/main.tf
@@ -1,5 +1,4 @@
-  #   synthetic-publisher the synthetic runbook deploy: runbooks/ only
+  #   synthetic-publisher prod only now
-    "synthetic-publisher" = {{ principal_id = "{PID}" }}
diff --git a/docs/readme.md b/docs/readme.md
+text
'''

OTHER_DIFF = """diff --git a/apps/x/main.py b/apps/x/main.py
+print(1)
"""


class Fake:
    """Fake git, gh and az. prs is the gh pr list answer, fail makes gh fail."""

    def __init__(self):
        self.prs = [
            {
                "number": 901,
                "title": "Retire the synthetic publisher grant",
                "url": "u901",
                "headRefName": "b901",
                "headRefOid": "a" * 40,
                "author": {"login": "owner1"},
                "isDraft": False,
            },
            {
                "number": 902,
                "title": "Unrelated app change",
                "url": "u902",
                "headRefName": "b902",
                "headRefOid": "b" * 40,
                "author": {"login": "someone"},
                "isDraft": False,
            },
        ]
        self.fail = False
        self.differ: list[str] | None = (
            None  # files git diff main..head names, None = the diff read fails
        )
        self.calls = []

    def __call__(self, argv, timeout=60, cwd=None, stdin_text=None):
        self.calls.append(argv)
        a = argv
        if a[0] == "/fake/git":
            sub = a[3:]
            if sub[:1] == ["rev-parse"]:
                return MAIN + "\n"
            if sub[:1] == ["show"] and sub[1].endswith("terraform-roots.json"):
                return ROOTS_JSON
            if sub[:1] == ["ls-tree"]:
                d = sub[-1]
                return f"{d}/main.tf\n{d}/dev.tfvars\n" if d == ROOT else ""
            if sub[:1] == ["show"]:
                return MAIN_TF
            if sub[:1] == ["log"]:
                return "Synthetic main commit subject\n"
            if sub[:1] in (["fetch"], ["cat-file"]):
                return ""
            if sub[:1] == ["diff"]:
                if self.differ is None:
                    raise tc.CtxError("git exit 128: synthetic bad object")
                return "".join(f + "\n" for f in self.differ)
            raise tc.CtxError("unexpected git " + " ".join(sub))
        if a[0] == "/fake/gh":
            if self.fail:
                raise tc.CtxError("gh exit 1: synthetic outage")
            if a[1:3] == ["pr", "list"]:
                return json.dumps(self.prs)
            if a[1:3] == ["pr", "diff"]:
                return PR_DIFF if a[3] == "901" else OTHER_DIFF
            if a[1:3] == ["pr", "view"]:
                return json.dumps({"body": "Synthetic PR body."})
        raise tc.CtxError("unexpected command " + " ".join(a))


def reset(fake):
    tc._run = fake
    ab._run = fake
    tc._ov.update(at=0.0, prs=None, error=None, busy=False, loaded=True)
    tc._spec.update(at=0.0, main=None, roots=None)
    tc._mem.clear()
    cb._parsed.clear()
    for p in (TMP / "ctx").glob("*.json"):
        p.unlink()
    logs = TMP / "owner-roots" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "state-backend-dev.log").write_text(PLAN_LOG)


def owner_item(**over):
    it = {
        "key": "state-backend:dev",
        "name": "state-backend",
        "tier": "dev",
        "state": "pending",
        "phase": "needs_me",
        "started": "2026-10-15T10:00:00Z",
        "planned_at": "2026-10-15T10:01:00Z",
        "pending_since": "2026-10-13T22:50:17Z",
        "main_sha": MAIN,
        "plan_sha256": PLAN_SHA,
        "counts": {"add": 1, "change": 1, "destroy": 0, "replace": 0, "import": 0},
        "resources": [
            {
                "address": "azurerm_monitor_scheduled_query_rules_alert_v2.state_access",
                "type": "x",
                "action": "change",
            },
            {
                "address": 'azurerm_role_assignment.state["synthetic-publisher"]',
                "type": "azurerm_role_assignment",
                "action": "add",
            },
        ],
    }
    it.update(over)
    return it


def style_ok(tc_, text):
    tc_.assertNotIn("\u2014", text)
    tc_.assertNotIn("\u2013", text)
    tc_.assertNotIn(";", text)
    tc_.assertTrue(all(ord(c) < 128 for c in text), text)


class PlanFacts(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        reset(self.fake)

    def test_parse_and_explain(self):
        res = tc.parse_plan(tc.actions_block(PLAN_LOG))
        self.assertEqual([r["action"] for r in res], ["change", "add"])
        self.assertEqual(res[0]["added_ids"], [PID])
        self.assertTrue(res[0]["ids_excluded"])
        self.assertEqual(res[1]["key"], "synthetic-publisher")
        self.assertEqual(res[1]["added_ids"], [])  # a create lists no growing id list
        names = tc.principal_names(tc.ids_in(res), blocking=True)
        self.assertEqual(names[PID]["name"], "Synthetic Publisher")
        text = " ".join(tc.explain(res, names, tc.code_comments("state-backend", "dev")))
        self.assertIn("gives Synthetic Publisher", text)
        self.assertIn(
            "Storage Blob Data Contributor role on the tfstate container of storage account devstate",
            text,
        )
        self.assertIn("read, write and delete blobs", text)
        self.assertIn("paths starting with runbooks/", text)
        self.assertIn("its query ignores", text)
        self.assertIn("the synthetic runbook deploy", text)

    def test_owner_plan_text_must_match_the_plan_run(self):
        self.assertTrue(
            tc.owner_plan_text(
                {"name": "state-backend", "tier": "dev", "started": "2026-10-15T10:00:00Z"}
            )
        )
        self.assertEqual(
            tc.owner_plan_text(
                {"name": "state-backend", "tier": "dev", "started": "2026-10-14T00:00:00Z"}
            ),
            "",
        )

    def test_scope_plain(self):
        self.assertEqual(
            tc.scope_plain(f"/subscriptions/{SUB}/resourceGroups/rg1"),
            "the whole resource group rg1",
        )
        self.assertIn(
            "Key Vault kv1",
            tc.scope_plain(
                f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.KeyVault/vaults/kv1"
            ),
        )


class Overlap(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        reset(self.fake)
        self.res = tc.parse_plan(tc.actions_block(PLAN_LOG))

    def test_cold_is_checking_never_clear(self):
        tc._ov["busy"] = True  # a refresh is running, nothing read yet
        ov = tc.overlaps("state-backend", "dev", self.res, kick=False)
        self.assertEqual(ov["status"], "checking")

    def test_open_pr_that_removes_the_grant(self):
        tc._ov_refresh()
        ov = tc.overlaps("state-backend", "dev", self.res, kick=False)
        self.assertEqual(ov["status"], "ok")
        self.assertEqual([p["number"] for p in ov["prs"]], [901])  # 902 does not touch the root
        self.assertEqual(ov["prs"][0]["removes"], ["synthetic-publisher"])
        self.assertEqual(ov["prs"][0]["files"], [f"{ROOT}/main.tf"])

    def test_failed_read_is_unknown(self):
        self.fake.fail = True
        tc._ov_refresh()
        ov = tc.overlaps("state-backend", "dev", self.res, kick=False)
        self.assertEqual(ov["status"], "unknown")
        self.assertIn("synthetic outage", ov["error"])

    def test_old_list_is_unknown(self):
        tc._ov_refresh()
        tc._ov["at"] = time.time() - tc.OV_MAX_AGE_S - 5
        self.assertEqual(
            tc.overlaps("state-backend", "dev", self.res, kick=False)["status"], "unknown"
        )

    def test_failed_refresh_keeps_last_good_list(self):
        tc._ov_refresh()
        self.fake.fail = True
        tc._ov_refresh()
        self.assertEqual(len(tc._ov["prs"]), 2)

    def test_roots_for_files(self):
        self.assertEqual(
            tc.roots_for_files(["infra/entra-consent/main.tf", "apps/a.py"]),
            [("entra-consent", "prod")],
        )

    # a PR stacked on a merged parent lists the parent's files against its merge base.
    def test_file_identical_to_main_is_not_an_overlap(self):
        self.fake.differ = []  # git diff main..head: nothing differs
        tc._ov_refresh()
        ov = tc.overlaps("state-backend", "dev", self.res, kick=False)
        self.assertEqual(ov["status"], "ok")
        self.assertEqual(ov["prs"], [])

    def test_file_that_differs_from_main_still_overlaps(self):
        self.fake.differ = [f"{ROOT}/main.tf"]
        tc._ov_refresh()
        ov = tc.overlaps("state-backend", "dev", self.res, kick=False)
        self.assertEqual([p["number"] for p in ov["prs"]], [901])
        self.assertEqual(ov["prs"][0]["removes"], ["synthetic-publisher"])

    def test_failed_main_comparison_still_overlaps(self):
        self.fake.differ = None  # the head cannot be read: fail closed
        tc._ov_refresh()
        ov = tc.overlaps("state-backend", "dev", self.res, kick=False)
        self.assertEqual([p["number"] for p in ov["prs"]], [901])

    def test_comparison_against_an_older_main_still_overlaps(self):
        self.fake.differ = []
        tc._ov_refresh()
        tc.roots_spec()
        tc._spec["main"] = "f" * 40  # main moved after the comparison
        tc._spec["at"] = time.time()
        ov = tc.overlaps("state-backend", "dev", self.res, kick=False)
        self.assertEqual([p["number"] for p in ov["prs"]], [901])


class OwnerCard(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        reset(self.fake)
        tc.principal_names([PID], blocking=True)
        tc._ov_refresh()

    def test_draft_warns_and_recommends_waiting(self):
        s = ab.subject("prod", owner_item(), "owner")
        f = cb.facts(s)
        out = cb.fallback(s, f)
        for v in out.values():
            style_ok(self, v)
        self.assertIn("Open PR #901", out["review"])
        self.assertIn("would put back what that PR is taking away", out["review"])
        self.assertIn("do not apply", out["review"])
        self.assertIn("ADDS access for Synthetic Publisher", out["approving"])
        self.assertIn("Synthetic main commit subject", out["does"])
        ann = cb.annotate(s, f)
        self.assertEqual([w["number"] for w in ann["wait_for"]], [901])
        self.assertIn("wait for #901", ann["warning"])
        style_ok(self, ann["warning"])

    def test_pr_stacked_on_this_apply_is_not_a_reason_to_wait(self):
        # #901 waits (through a merged parent) on this root's Owner apply: holding the apply for it deadlocks.
        import pr_deps

        saved = (pr_deps.snapshot, pr_deps.downstream_of_root, pr_deps._roots_cfg)
        pr_deps.snapshot = lambda fresh=False: {"deps": {}}
        pr_deps.downstream_of_root = lambda n, name, tier, snap=None: 347 if n == 901 else None
        pr_deps._roots_cfg = lambda: {"state-backend": {"applied_by": "owner"}}
        try:
            s = ab.subject("prod", owner_item(), "owner")
            f = cb.facts(s)
            ann = cb.annotate(s, f)
            out = cb.fallback(s, f)
        finally:
            pr_deps.snapshot, pr_deps.downstream_of_root, pr_deps._roots_cfg = saved
        self.assertNotIn("wait_for", ann)
        self.assertIn(
            "Open PR #901 also changes this root, but it waits on the #347 Owner apply",
            ann["warning"],
        )
        self.assertNotIn("do not apply", out["review"])
        self.assertIn("No other open PR", out["review"])
        style_ok(self, ann["warning"])
        style_ok(self, out["review"])

    def test_no_overlap_recommends_with_access_caveat(self):
        self.fake.prs = self.fake.prs[1:]
        tc._ov_refresh()
        s = ab.subject("prod", owner_item(), "owner")
        f = cb.facts(s)
        ann = cb.annotate(s, f)
        self.assertNotIn("wait_for", ann)
        self.assertNotIn("warning", ann)
        self.assertIn("No open PR changes this root", cb.fallback(s, f)["review"])

    def test_in_flight_card_offers_no_button(self):
        s = ab.subject("prod", owner_item(phase="in_flight", main_moved=True), "owner")
        self.assertFalse(s["model"])
        out = cb.fallback(s, cb.facts(s))
        self.assertIn("There is no button right now", out["approving"])
        self.assertIn("main has moved since", out["does"])

    def test_unknown_check_warns(self):
        tc._ov.update(prs=None, at=0.0, error="gh exit 1: down", busy=False)
        s = ab.subject("prod", owner_item(), "owner")
        f = cb.facts(s)
        tc._ov["busy"] = False
        ann = cb.annotate(s, f)
        self.assertIn(ann["overlap_status"], ("unknown", "checking"))
        self.assertIn("Do not apply", ann["warning"])

    def test_brief_for_attaches_warning_and_gates_the_model(self):
        spawned = []
        orig = ab._spawn
        ab._spawn = lambda s, sig: spawned.append(s["pr"]) or True
        try:
            out = ab.brief_for(ab.subject("prod", owner_item(), "owner"), {"briefs": {}})
            self.assertEqual(out["source"], "draft")
            self.assertEqual(out["kind"], "owner")
            self.assertEqual(out["wait_for"][0]["number"], 901)
            self.assertEqual(spawned, ["owner:state-backend:dev"])
            # Not while the PR check is unknown, and never for a card that cannot be acted on.
            spawned.clear()
            tc._ov.update(prs=None, at=0.0, error="down", busy=True)
            ab.brief_for(ab.subject("prod", owner_item(), "owner"), {"briefs": {}})
            tc._ov_refresh()
            ab.brief_for(
                ab.subject("prod", owner_item(state="error", plan_sha256=None, error="x"), "owner"),
                {"briefs": {}},
            )
            self.assertEqual(spawned, [])
        finally:
            ab._spawn = orig

    def test_failed_owner_apply_names_the_real_next_step(self):
        """the ScopeLocked loop. The card must not answer every failure with Re-plan."""
        err = "terraform apply failed: Error: unexpected status 409 (409 Conflict) with error: ScopeLocked: x"
        kind, step = (
            "scope_locked",
            "A resource lock blocked a delete. Re-plan alone will fail the same way.",
        )
        it = owner_item(
            state="error",
            plan_sha256=None,
            error=err,
            error_kind=kind,
            error_next=step,
            apply_failures={"count": 2, "kind": kind},
        )
        out = cb.fallback(cb.subject("prod", it, "owner"), {})
        self.assertNotIn("the owner recommends Re-plan", out["review"])
        self.assertIn("failed the same way 2 times", out["review"])
        self.assertIn(step, out["review"])

    def test_model_brief_keeps_the_deterministic_warning(self):
        s = ab.subject("prod", owner_item(), "owner")
        sig = ab.signature(s)
        store = {
            "briefs": {
                ab.key_of(s): {
                    "sig": sig,
                    "status": "ready",
                    "brief": {"does": "a", "approving": "b", "review": "c"},
                }
            }
        }
        out = ab.brief_for(s, store, kick=False)
        self.assertEqual(out["source"], "model")
        self.assertIn("#901", out["warning"])

    def test_signature_moves_with_the_overlap(self):
        s = ab.subject("prod", owner_item(), "owner")
        a = ab.signature(s)
        self.fake.prs = self.fake.prs[1:]
        tc._ov_refresh()
        self.assertNotEqual(a, ab.signature(s))

    def test_model_must_name_the_open_pr(self):
        s = ab.subject("prod", owner_item(), "owner")
        f = cb.facts(s)
        self.assertTrue(cb.check_model(s, f, {"review": "Looks fine, apply it."}))
        self.assertEqual(cb.check_model(s, f, {"review": "Wait for #901 to merge."}), "")

    def test_generate_rejects_a_model_brief_that_skips_the_pr(self):
        s = ab.subject("prod", owner_item(), "owner")
        good = {
            "title": "Give Synthetic Publisher blob access on the dev state",
            "origin": "Main commit ffffffff, the synthetic state change, by owner1.",
            "notes": "Nothing else to know.",
            "review": "Nothing raised. the owner recommends applying it now because the plan matches main exactly.",
        }
        ab.call_model = lambda prompt: json.dumps(good)
        ent = ab.generate(s)
        self.assertEqual(ent["status"], "failed")
        self.assertIn("#901", ent["error"])
        good["review"] = (
            "Open PR #901 deletes this grant from the code, so applying now would put it back. Wait for #901."
        )
        ent = ab.generate(s)
        self.assertEqual(ent["status"], "ready")
        self.assertEqual(ent["brief"]["title"], good["title"])
        self.assertEqual(ent["brief"]["does"], good["origin"])

    def test_prompt_carries_the_overlap_and_code(self):
        s = ab.subject("prod", owner_item(), "owner")
        ctx = cb.gather(s, self.fake)
        p = cb.build_prompt(s, ctx)
        self.assertIn("#901 Retire the synthetic publisher grant", p)
        self.assertIn("It deletes these keys from the code: synthetic-publisher", p)
        self.assertIn('"synthetic-publisher" = {', p)  # the root code
        self.assertIn("Terraform will perform the following actions", p)


class OtherCards(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        reset(self.fake)
        tc._ov_refresh()

    def test_priv_draft(self):
        it = {
            "key": "entra-privileged:1",
            "environment": "entra-privileged",
            "env_label": "Entra consent",
            "workflow": ".github/workflows/terraform-apply.yml",
            "workflow_name": "terraform-apply",
            "run_id": 1,
            "run_attempt": 1,
            "event": "push",
            "head_branch": "main",
            "head_sha": "d" * 40,
            "pr": {"number": 77, "title": "Grant scripts (synthetic)", "author": "owner1"},
            "plan": {
                "add": 1,
                "change": 0,
                "destroy": 0,
                "resources": [
                    {
                        "address": 'azuread_app_role_assignment.w["a|P"]',
                        "action": "create",
                        "type": "azuread_app_role_assignment",
                    }
                ],
            },
            "entra": [
                {
                    "app": "synthetic-app",
                    "permission": "P.ReadWrite.All",
                    "kind": "application",
                    "change": "grant",
                    "description": "Read and write P",
                }
            ],
            "data_loss": [],
            "held_reasons": [],
            "files": ["infra/entra-consent/main.tf"],
            "typed_confirm": True,
            "confirm_name": "terraform-apply",
            "assessment": {
                "risk": {"level": "high", "why": "Tenant wide."},
                "recommendation": {"action": "approve", "why": "Needed."},
            },
            "phase": "needs_me",
        }
        s = ab.subject("prod", it, "priv")
        out = ab.brief_for(s, {"briefs": {}}, kick=False)
        for k in ("does", "approving", "review"):
            style_ok(self, out[k])
        self.assertIn("paused at the entra-privileged environment", out["does"])
        self.assertIn(
            "The identity synthetic-app gets the directory application permission P.ReadWrite.All",
            out["approving"],
        )
        self.assertIn("type terraform-apply", out["approving"])
        self.assertIn("It recommends approve", out["review"])
        self.assertEqual(out["overlap_status"], "ok")

    def test_release_draft(self):
        it = {
            "pr": 55,
            "title": "Remove old runbooks (synthetic)",
            "tier": "prod",
            "state": "ready",
            "approved": ['azurerm_automation_runbook.rb["Old-One"]'],
            "approved_at": "2026-10-15T10:00:00Z",
            "run": {
                "id": 9,
                "url": "u",
                "event": "push",
                "status": "completed",
                "conclusion": "failure",
            },
            "why": "the main run stopped on the destroy guard",
        }
        out = ab.brief_for(ab.subject("prod", it, "release"), {"briefs": {}}, kick=False)
        self.assertIn("deletes the 1 runbook below", out["approving"])
        self.assertIn("Old-One", out["approving"])
        self.assertIn("the owner recommends releasing", out["review"])

    def test_request_validates_card_ids(self):
        with self.assertRaises(ab.BriefError):
            ab.request({"repo": "prod", "card": "owner:x;rm -rf"})
        with self.assertRaises(ab.BriefError):
            ab.request({"repo": "prod", "card": 5})


class StructuredAsk(unittest.TestCase):
    """the owner 2026-10-20: every card says what is asked, by who, what is granted and why it needs him."""

    PLAN = """Terraform will perform the following actions:

  # azurerm_role_assignment.dag["int-eus"] will be created
  + resource "azurerm_role_assignment" "dag" {
      + principal_id         = "44444444-4444-4444-8444-444444444444"
      + principal_type       = "Group"
      + role_definition_name = "Desktop Virtualization User"
      + scope                = "/subscriptions/x/resourceGroups/rg/providers/Microsoft.DesktopVirtualization/applicationGroups/<pool-rg>-dag-int-eus"
    }

  # azurerm_role_assignment.share_admin["int-eus"] will be created
  + resource "azurerm_role_assignment" "share_admin" {
      + principal_id         = "44444444-4444-4444-8444-444444444444"
      + principal_type       = "Group"
      + role_definition_name = "Storage File Data SMB Share Elevated Contributor"
      + scope                = "/subscriptions/x/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa1/fileServices/default/fileshares/fslogix-int-eus"
    }

  # azurerm_role_assignment.share_admin["internal"] will be destroyed
  - resource "azurerm_role_assignment" "share_admin" {
      - principal_id         = "44444444-4444-4444-8444-444444444444" -> null
      - principal_type       = "Group" -> null
      - role_definition_name = "Storage File Data SMB Share Elevated Contributor" -> null
      - scope                = "/subscriptions/x/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa1/fileServices/default/fileshares/fslogix-internal" -> null
    }

Plan: 2 to add, 0 to change, 1 to destroy.
"""

    def _card(self, tmp):
        import pathlib

        d = pathlib.Path(tmp)
        (d / "governance-77.txt").write_text(self.PLAN)
        cb.PRIV_PLANS = d
        item = {
            "environment": "governance",
            "run_id": 77,
            "status": "pending",
            "phase": "needs_me",
            "actor": "owner1",
            "event": "workflow_dispatch",
            "head_sha": "9f30b807aaaa",
            "head_branch": "main",
            "plan_source": "log:plan",
            "workflow_name": "terraform-apply",
            "source_pr": {"number": 418, "title": "dev-tier sign-in", "author": "owner1"},
            "plan": {
                "add": 2,
                "change": 0,
                "destroy": 1,
                "resources": [
                    {
                        "address": 'azurerm_role_assignment.dag["int-eus"]',
                        "type": "azurerm_role_assignment",
                        "action": "create",
                    },
                    {
                        "address": 'azurerm_role_assignment.share_admin["int-eus"]',
                        "type": "azurerm_role_assignment",
                        "action": "create",
                    },
                    {
                        "address": 'azurerm_role_assignment.share_admin["internal"]',
                        "type": "azurerm_role_assignment",
                        "action": "delete",
                    },
                ],
            },
        }
        s = cb.subject("prod", item, "priv")
        f = cb.facts(s)
        # The open PR check is its own concern (tf_context tests): here one root, checked, no PRs.
        f["overlap"] = [{"root": "escalations", "tier": "prod", "status": "ok", "prs": []}]
        return s, f

    def test_structure_names_the_ask_the_asker_the_grants_and_why(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            s, f = self._card(tmp)
            st = cb.structure(s, f)
        self.assertIn("create 2 access grants and remove 1 access grant", st["ask"])
        self.assertIn(
            "You (owner1), by starting the terraform-apply workflow by hand on main",
            st["asked_by"][0]["value"],
        )
        self.assertIn("can carry earlier merges", st["asked_by"][1]["value"])
        roles = {(g["change"], g["role"], g["move"]) for g in st["grants"]}
        self.assertIn(("add", "Desktop Virtualization User", False), roles)
        self.assertIn(("remove", "Storage File Data SMB Share Elevated Contributor", True), roles)
        rem = [g for g in st["grants"] if g["change"] == "remove"][0]
        self.assertEqual(rem["on"], ["file share fslogix-internal in storage account sa1"])
        self.assertIn("only you approve them", st["why_you"])
        self.assertIn("only when every change passes my improvement-id rule", st["why_you"])
        self.assertIn("only removes access", st["why_you"])
        self.assertTrue(st["auto"]["fits"])
        for v in [st["ask"], st["why_you"], st["auto"]["text"]] + [
            r["value"] for r in st["asked_by"]
        ]:
            style_ok(self, v)

    def test_a_new_role_for_an_identity_keeps_the_card(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            s, f = self._card(tmp)
            f["resources"] = [
                dict(r, attrs=dict(r["attrs"], role_definition_name="Reader"))
                if r["action"] == "destroy"
                else r
                for r in f["resources"]
            ]
            st = cb.structure(s, f)
        self.assertFalse(st["auto"]["fits"])
        self.assertIn("which it does not hold anywhere else in this plan", st["auto"]["text"])

    def test_auto_rule_fails_closed(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            s, f = self._card(tmp)
            cases = {
                "the open PR check is not current": lambda s, f: f.update(
                    overlap=[{"status": "checking", "prs": []}]
                ),
                "open PR #7 changes the same root": lambda s, f: f.update(
                    overlap=[{"status": "ok", "prs": [{"number": 7}], "root": "r", "tier": "t"}]
                ),
                "could not tell which Terraform root": lambda s, f: f.update(overlap=[]),
                "the run is not on main": lambda s, f: s.update(unexpected=True),
                "the plan counts do not match": lambda s, f: s.update(plan=dict(s["plan"], add=3)),
                "grants directory permissions": lambda s, f: s.update(
                    entra=[
                        {
                            "app": "x",
                            "permission": "User.Read.All",
                            "kind": "application",
                            "change": "grant",
                        }
                    ]
                ),
                "who or which role": lambda s, f: f.update(
                    resources=[dict(r, attrs={}) for r in f["resources"]]
                ),
            }
            for want, mut in cases.items():
                s2, f2 = json.loads(json.dumps(s)), json.loads(json.dumps(f))
                mut(s2, f2)
                st = cb.structure(s2, f2)
                self.assertFalse(st["auto"]["fits"], want)
                self.assertIn(want, st["auto"]["text"])

    # ---- ----
    AVD_TXT = """Terraform will perform the following actions:

  # azurerm_role_assignment.pool_access["login|host-val-02"] will be created
  + resource "azurerm_role_assignment" "pool_access" {
      + principal_id         = "44444444-4444-4444-8444-444444444444"
      + principal_type       = "%(ptype)s"
      + role_definition_name = "%(role)s"
      + scope                = "%(scope)s"
    }

Plan: 1 to add, 0 to change, 0 to destroy.
"""
    VM = "/subscriptions/***/resourceGroups/pool-rg/providers/Microsoft.Compute/virtualMachines/host-val-02"

    def _avd(
        self,
        tmp,
        role="Virtual Machine User Login",
        ptype="Group",
        scope=None,
        prs=None,
        overlap_extra=None,
    ):
        import pathlib

        d = pathlib.Path(tmp)
        cb.PRIV_PLANS = d
        self.__class__._rid = getattr(self.__class__, "_rid", 7800) + 1
        rid = self._rid
        item = {
            "environment": "governance",
            "run_id": rid,
            "status": "pending",
            "phase": "needs_me",
            "actor": "owner1",
            "event": "push",
            "head_sha": "9f30b807aaaa",
            "head_branch": "main",
            "plan_source": "log:plan",
            "workflow_name": "terraform-apply",
            "plan": {
                "add": 1,
                "change": 0,
                "destroy": 0,
                "resources": [
                    {
                        "address": 'azurerm_role_assignment.pool_access["login|host-val-02"]',
                        "type": "azurerm_role_assignment",
                        "action": "create",
                    }
                ],
            },
        }
        (d / f"governance-{rid}.txt").write_text(
            self.AVD_TXT % {"ptype": ptype, "role": role, "scope": scope or self.VM}
        )
        s = cb.subject("prod", item, "priv")
        f = cb.facts(s)
        f["overlap"] = [
            dict(
                {
                    "root": "escalations",
                    "tier": "prod",
                    "status": "ok",
                    "prs": prs or [],
                    "paths": {"dir": "infra/esc", "modules": []},
                },
                **(overlap_extra or {}),
            )
        ]
        return s, f

    def _auto_of(self, **kw):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            s, f = self._avd(tmp, **kw)
            return cb.structure(s, f)["auto"]

    def test_avd_vm_login_to_group_on_session_host_clears(self):
        a = self._auto_of()
        self.assertTrue(a["fits"], a)
        self.assertIn("a sign-in grant to a group on pool session hosts", a["kinds"])
        style_ok(self, a["text"])

    def test_avd_vm_login_on_the_avd_resource_group_clears(self):
        a = self._auto_of(scope="/subscriptions/***/resourceGroups/pool-rg")
        self.assertTrue(a["fits"], a)

    def test_avd_vm_admin_login_never_clears(self):
        a = self._auto_of(role="Virtual Machine Administrator Login")
        self.assertFalse(a["fits"])
        self.assertIn("does not hold anywhere else", a["text"])

    def test_avd_vm_login_to_a_user_never_clears(self):
        self.assertFalse(self._auto_of(ptype="User")["fits"])

    def test_avd_vm_login_off_the_avd_scope_never_clears(self):
        for sc in (
            "/subscriptions/***/resourceGroups/other-rg/providers/Microsoft.Compute/virtualMachines/host-val-02",
            "/subscriptions/***/resourceGroups/pool-rg/providers/Microsoft.Compute/virtualMachines/jump01",
            "/subscriptions/***",
            "/subscriptions/***/resourceGroups/pool-rg/providers/Microsoft.KeyVault/vaults/kv",
            "/subscriptions/***/resourceGroups/prod-prefix-pool2",
        ):
            self.assertFalse(self._auto_of(scope=sc)["fits"], sc)

    def _pr(self, n=7):
        return {"number": n, "title": "t", "diff_known": True, "head": "h" * 40, "files": []}

    DECL = 'resource "azurerm_role_assignment" "pool_access" {\n  scope = "z"\n}\n'
    OTHER = 'resource "azurerm_resource_group" "x" {\n  name = "a"\n}\n\nlocals {\n  a = 1\n}\n'

    @staticmethod
    def _diff(path, hunk, new=False):
        return (
            f"diff --git a/{path} b/{path}\n"
            + ("new file mode 100644\n" if new else "")
            + f"--- a/{path}\n+++ b/{path}\n"
            + hunk
        )

    EDIT_X = (
        '@@ -2,1 +2,1 @@ resource "azurerm_resource_group" "x" {\n-  name = "a"\n+  name = "b"\n'
    )

    def _with_diff(self, diff, files=None, pr=None, git_fails=False, prs=None):
        files = (
            files
            if files is not None
            else {"infra/esc/other.tf": self.OTHER, "infra/esc/decl.tf": self.DECL}
        )
        saved = (tc._root_diff, tc._git)
        tc._root_diff = lambda head, paths: diff

        def fake_git(*a, **k):
            if git_fails:
                raise tc.CtxError("no git")
            if a[0] == "ls-tree":
                return "\n".join(files)
            return files[a[1].split(":", 1)[1]]

        tc._git = fake_git
        try:
            return self._auto_of(prs=prs or [pr or self._pr()])
        finally:
            tc._root_diff, tc._git = saved

    def test_open_pr_on_other_resources_of_the_root_no_longer_blocks(self):
        a = self._with_diff(self._diff("infra/esc/other.tf", self.EDIT_X))
        self.assertTrue(a["fits"], a)

    def test_open_pr_new_file_with_other_resources_does_not_block(self):
        d = self._diff(
            "infra/esc/new.tf",
            '@@ -0,0 +1,3 @@\n+resource "azurerm_resource_group" "y" {\n+  name = "b"\n+}\n',
            new=True,
        )
        self.assertTrue(self._with_diff(d)["fits"])

    def test_open_pr_editing_the_same_resource_blocks(self):
        d = self._diff("infra/esc/decl.tf", '@@ -2,1 +2,1 @@\n-  scope = "z"\n+  scope = "y"\n')
        a = self._with_diff(d)
        self.assertFalse(a["fits"])
        self.assertIn("open PR #7 changes the same root", a["text"])

    def test_open_pr_adding_the_same_resource_blocks(self):
        d = self._diff(
            "infra/esc/new.tf",
            '@@ -0,0 +1,2 @@\n+resource "azurerm_role_assignment" "pool_access" {\n+}\n',
            new=True,
        )
        self.assertFalse(self._with_diff(d)["fits"])

    def test_open_pr_naming_the_plan_resource_in_a_changed_line_blocks(self):
        d = self._diff(
            "infra/esc/other.tf",
            '@@ -2,1 +2,1 @@\n-  name = "a"\n+  name = azurerm_role_assignment.pool_access.id\n',
        )
        self.assertFalse(self._with_diff(d)["fits"])

    def test_open_pr_changing_a_resource_the_plan_resource_references_blocks(self):
        files = {
            "infra/esc/other.tf": self.OTHER,
            "infra/esc/decl.tf": self.DECL.replace('"z"', "azurerm_resource_group.x.id"),
        }
        self.assertFalse(
            self._with_diff(self._diff("infra/esc/other.tf", self.EDIT_X), files=files)["fits"]
        )

    LOCALS = 'resource "azurerm_resource_group" "x" {\n  name = "a"\n}\n\nlocals {\n  unused = 1\n  used = 2\n  multi = [\n    "a",\n  ]\n}\n'

    def _locals_files(self, decl_extra=""):
        return {
            "infra/esc/other.tf": self.LOCALS,
            "infra/esc/decl.tf": self.DECL.replace('"z"', f'"z" #{decl_extra}'),
        }

    def test_locals_attribute_the_plan_does_not_use_does_not_block_but_one_it_uses_does(self):
        free = self._diff("infra/esc/other.tf", "@@ -6,1 +6,1 @@\n-  unused = 1\n+  unused = 2\n")
        self.assertTrue(self._with_diff(free, files=self._locals_files(" local.used"))["fits"])
        used = self._diff("infra/esc/other.tf", "@@ -7,1 +7,1 @@\n-  used = 2\n+  used = 3\n")
        self.assertFalse(self._with_diff(used, files=self._locals_files(" local.used"))["fits"])
        multi = self._diff("infra/esc/other.tf", '@@ -9,1 +9,2 @@\n     "a",\n+    "b",\n')
        self.assertFalse(self._with_diff(multi, files=self._locals_files(" local.multi"))["fits"])
        self.assertTrue(self._with_diff(multi, files=self._locals_files(" local.used"))["fits"])

    def test_locals_used_through_another_local_blocks(self):
        files = self._locals_files(" local.used")
        files["infra/esc/other.tf"] = files["infra/esc/other.tf"].replace(
            "used = 2", "used = local.unused + 1"
        )
        free = self._diff("infra/esc/other.tf", "@@ -6,1 +6,1 @@\n-  unused = 1\n+  unused = 2\n")
        self.assertFalse(self._with_diff(free, files=files)["fits"])

    def test_variable_module_provider_blocks_always_block(self):
        for kind in ("variable", "module", "provider", "output", "terraform"):
            main = f'{kind} "v" {{\n  a = 1\n}}\n'
            files = {"infra/esc/other.tf": main, "infra/esc/decl.tf": self.DECL}
            d = self._diff("infra/esc/other.tf", "@@ -2,1 +2,1 @@\n-  a = 1\n+  a = 2\n")
            self.assertFalse(self._with_diff(d, files=files)["fits"], kind)

    def test_data_source_used_by_the_plan_blocks_unused_does_not(self):
        main = 'data "azuread_group" "g" {\n  display_name = "a"\n}\n'
        d = self._diff(
            "infra/esc/other.tf", '@@ -2,1 +2,1 @@\n-  display_name = "a"\n+  display_name = "b"\n'
        )
        files = {"infra/esc/other.tf": main, "infra/esc/decl.tf": self.DECL}
        self.assertTrue(self._with_diff(d, files=files)["fits"])
        files["infra/esc/decl.tf"] = self.DECL.replace('"z"', "data.azuread_group.g.id")
        self.assertFalse(self._with_diff(d, files=files)["fits"])

    def test_comment_inside_locals_and_a_new_resource_after_it_do_not_block(self):
        files = self._locals_files(" local.used")
        comment = self._diff("infra/esc/other.tf", "@@ -7,0 +7,1 @@\n+  # x\n")
        self.assertTrue(self._with_diff(comment, files=files)["fits"])
        after = self._diff(
            "infra/esc/other.tf",
            '@@ -12,0 +12,3 @@\n+resource "azurerm_resource_group" "z" {\n+  name = "c"\n+}\n',
        )
        self.assertTrue(self._with_diff(after, files=files)["fits"])

    def test_open_pr_adding_a_top_level_locals_block_blocks(self):
        d = self._diff("infra/esc/other.tf", "@@ -8,0 +8,3 @@\n+locals {\n+  b = 2\n+}\n")
        self.assertFalse(self._with_diff(d)["fits"])

    def test_undeterminable_cases_keep_the_old_behavior(self):
        d = self._diff("infra/esc/other.tf", self.EDIT_X)
        self.assertFalse(self._with_diff(d, pr=dict(self._pr(), diff_known=False))["fits"])
        self.assertFalse(self._with_diff("")["fits"])
        self.assertFalse(self._with_diff(d, git_fails=True)["fits"])
        self.assertFalse(self._with_diff(d.replace("other.tf", "platform.tfvars"))["fits"])
        self.assertFalse(
            self._with_diff(d, files={"infra/esc/other.tf": self.OTHER})["fits"]
        )  # plan resource not found in the root
        dele = d.replace("--- a/", "deleted file mode 100644\n--- a/", 1)
        self.assertFalse(self._with_diff(dele)["fits"])

    def test_one_blocking_pr_among_unrelated_ones_still_blocks(self):
        unrelated = self._diff("infra/esc/other.tf", self.EDIT_X)
        same = self._diff("infra/esc/decl.tf", '@@ -2,1 +2,1 @@\n-  scope = "z"\n+  scope = "y"\n')
        saved = (tc._root_diff, tc._git)
        tc._root_diff = lambda head, paths: unrelated if head == "a" * 40 else same
        files = {"infra/esc/other.tf": self.OTHER, "infra/esc/decl.tf": self.DECL}
        tc._git = lambda *a, **k: (
            "\n".join(files) if a[0] == "ls-tree" else files[a[1].split(":", 1)[1]]
        )
        try:
            a = self._auto_of(
                prs=[dict(self._pr(7), head="a" * 40), dict(self._pr(8), head="b" * 40)]
            )
        finally:
            tc._root_diff, tc._git = saved
        self.assertFalse(a["fits"])
        self.assertIn("PR #8", a["text"])
        self.assertNotIn("PR #7", a["text"])

    def test_auto_verdict_never_raises(self):
        v = cb.auto_verdict("prod", {"key": None})
        self.assertFalse(v["fits"])

    # ---- warning and wait_for use the same filter as the auto-approve guard ----

    def _annotated(self, diff, prs, files=None, status="ok", also=None):
        import tempfile

        files = (
            files
            if files is not None
            else {"infra/esc/other.tf": self.OTHER, "infra/esc/decl.tf": self.DECL}
        )
        saved = (tc._root_diff, tc._git)
        tc._root_diff = lambda head, paths: diff[head] if isinstance(diff, dict) else diff

        def fake_git(*a, **k):
            if a[0] == "ls-tree":
                return "\n".join(files)
            return files[a[1].split(":", 1)[1]]

        tc._git = fake_git
        try:
            with tempfile.TemporaryDirectory() as tmp:
                s, f = self._avd(tmp, prs=prs, overlap_extra={"status": status})
                return s, f, cb.annotate(s, f), (also(s, f) if also else None)
        finally:
            tc._root_diff, tc._git = saved

    def test_pr_on_the_root_but_not_the_plan_gives_no_warning_or_wait_for(self):
        # PR #460 changes another resource of the root, the plan only creates the AVD role assignment
        pr = dict(self._pr(460), title="Other escalation", files=["infra/esc/other.tf"])
        s, f, out, ex = self._annotated(
            self._diff("infra/esc/other.tf", self.EDIT_X),
            [pr],
            also=lambda s, f: cb.check_model(s, f, {"review": "Nothing raised."}),
        )
        self.assertNotIn("warning", out)
        self.assertNotIn("wait_for", out)
        self.assertEqual(out["overlap_status"], "ok")
        self.assertEqual(ex, "")

    def test_pr_that_edits_a_plan_resource_still_warns_with_wait_for(self):
        pr = dict(self._pr(461), title="Change the grant", files=["infra/esc/decl.tf"])
        d = self._diff("infra/esc/decl.tf", '@@ -2,1 +2,1 @@\n-  scope = "z"\n+  scope = "y"\n')
        s, f, out, ex = self._annotated(
            d, [pr], also=lambda s, f: cb.check_model(s, f, {"review": "Fine."})
        )
        self.assertEqual([w["number"] for w in out["wait_for"]], [461])
        self.assertIn("Open PR #461", out["warning"])
        self.assertIn("wait for #461", out["warning"])
        self.assertIn("#461", ex)

    def test_mixed_prs_warn_only_for_the_one_that_touches_the_plan(self):
        d = {
            "a" * 40: self._diff("infra/esc/other.tf", self.EDIT_X),
            "b" * 40: self._diff(
                "infra/esc/decl.tf", '@@ -2,1 +2,1 @@\n-  scope = "z"\n+  scope = "y"\n'
            ),
        }
        prs = [dict(self._pr(460), head="a" * 40), dict(self._pr(461), head="b" * 40)]
        _, _, out, _ = self._annotated(d, prs)
        self.assertEqual([w["number"] for w in out["wait_for"]], [461])
        self.assertNotIn("#460", out["warning"])

    def test_undeterminable_pr_still_warns_fail_closed(self):
        pr = dict(self._pr(462), diff_known=False, files=["infra/esc/other.tf"])
        _, _, out, _ = self._annotated(self._diff("infra/esc/other.tf", self.EDIT_X), [pr])
        self.assertEqual([w["number"] for w in out["wait_for"]], [462])
        _, _, out, _ = self._annotated("", [dict(self._pr(463), files=["infra/esc/other.tf"])])
        self.assertEqual([w["number"] for w in out["wait_for"]], [463])

    def test_checking_and_unknown_sentences_stay(self):
        _, _, out, _ = self._annotated("", [], status="checking")
        self.assertIn("still reading the open PRs", out["warning"])
        self.assertNotIn("wait_for", out)
        _, _, out, _ = self._annotated("", [], status="unknown")
        self.assertIn("could not check the open PRs", out["warning"])

    def test_the_prompt_does_not_ask_the_model_to_wait_on_a_clear_pr(self):
        pr = dict(self._pr(460), title="Other escalation", files=["infra/esc/other.tf"])
        _, _, _, p = self._annotated(
            self._diff("infra/esc/other.tf", self.EDIT_X),
            [pr],
            also=lambda s, f: cb.build_prompt(s, {"facts": f}),
        )
        self.assertIn("#460 Other escalation changes this root but not what this plan creates", p)

    # ---- the person behind the merge ----

    def _merged_pr_card(self, tmp, actor="github-merge-queue[bot]", author="koolaid-summers"):
        import pathlib

        d = pathlib.Path(tmp)
        cb.PRIV_PLANS = d
        (d / "governance-4601.txt").write_text(self.PLAN)
        item = {
            "environment": "governance",
            "run_id": 4601,
            "status": "pending",
            "phase": "needs_me",
            "actor": actor,
            "event": "push",
            "head_sha": "9f30b807aaaa",
            "head_branch": "main",
            "plan_source": "log:plan",
            "workflow_name": "terraform-apply",
            "pr": {"number": 461, "title": "Add vendor writer", "author": author},
            "plan": {"add": 0, "change": 0, "destroy": 0, "resources": []},
        }
        s = cb.subject("prod", item, "priv")
        f = {"overlap": [], "resources": []}
        return s, f

    def _names(self, mapping):
        import swr

        calls = []

        def fake(login):
            calls.append(login)
            if login not in mapping:
                raise RuntimeError("gh down")
            return mapping[login]

        saved = cb._fetch_name
        cb._fetch_name = fake
        swr.invalidate_prefix("gh-user-name:")
        cb._name_fail.clear()
        self.addCleanup(setattr, cb, "_fetch_name", saved)
        self.addCleanup(swr.invalidate_prefix, "gh-user-name:")
        return calls

    def test_asked_by_leads_with_the_pr_author_and_the_bot_is_the_mechanism(self):
        import tempfile

        calls = self._names({"koolaid-summers": "manager-name"})
        self.assertEqual(cb.person("koolaid-summers", wait=True), "manager-name (koolaid-summers)")
        cb.person("koolaid-summers", wait=True)
        self.assertEqual(calls, ["koolaid-summers"])  # cached
        with tempfile.TemporaryDirectory() as tmp:
            s, f = self._merged_pr_card(tmp)
            row = cb._asked_by(s, f)[0]["value"]
        self.assertTrue(
            row.startswith("Manager-name (koolaid-summers), by merging PR #461 to main"), row
        )
        self.assertIn("the merge ran through github-merge-queue[bot]", row)
        style_ok(self, row)

    def test_asked_by_falls_back_to_the_login_and_never_waits_when_cold(self):
        import tempfile
        import time

        self._names({})
        self.assertEqual(cb.person("koolaid-summers", wait=True), "koolaid-summers")
        with tempfile.TemporaryDirectory() as tmp:
            s, f = self._merged_pr_card(tmp)
            t0 = time.time()
            row = cb._asked_by(s, f)[0]["value"]
        self.assertLess(time.time() - t0, 2)
        self.assertTrue(row.startswith("PR author koolaid-summers, by merging PR #461"), row)

    def test_asked_by_names_a_human_merger_and_dispatch_runs_keep_the_old_text(self):
        import tempfile

        self._names({"koolaid-summers": "manager-name"})
        cb.person("koolaid-summers", wait=True)
        with tempfile.TemporaryDirectory() as tmp:
            s, f = self._merged_pr_card(tmp, actor="owner1")
            row = cb._asked_by(s, f)[0]["value"]
            self.assertIn("(merged by You (owner1))", row)
            s["event"] = "workflow_dispatch"
            self.assertIn(
                "by starting the terraform-apply workflow by hand", cb._asked_by(s, f)[0]["value"]
            )

    def test_real_source_carries_the_display_name(self):
        import tempfile

        self._names({"koolaid-summers": "manager-name"})
        cb.person("koolaid-summers", wait=True)
        with tempfile.TemporaryDirectory() as tmp:
            s, f = self._merged_pr_card(tmp)
            self.assertIn("PR #461 by manager-name (koolaid-summers)", cb._fb_origin(s))
        txt = "The vendor writer grant from PR #461 by koolaid-summers. Already manager-name (koolaid-summers) said it."
        out = cb.name_people(txt, ["koolaid-summers"])
        self.assertIn("PR #461 by manager-name (koolaid-summers).", out)
        self.assertEqual(out.count("manager-name (koolaid-summers)"), 2)

    # ---- the full scope of a grant ----

    def test_scope_plain_names_a_secret_inside_its_vault(self):
        base = f"/subscriptions/{SUB}/resourceGroups/dev-tier/providers/Microsoft.KeyVault/vaults/dev-prefix-vault"
        self.assertEqual(
            tc.scope_plain(base), "Key Vault dev-prefix-vault (resource group dev-tier)"
        )
        self.assertEqual(
            tc.scope_plain(base + "/secrets/jsm-mail-relay-forge-webtrigger-url"),
            "Secret jsm-mail-relay-forge-webtrigger-url in Key Vault dev-prefix-vault (resource group dev-tier)",
        )
        self.assertEqual(
            tc.scope_plain(base + "/keys/signing"),
            "Key signing in Key Vault dev-prefix-vault (resource group dev-tier)",
        )

    def test_scope_plain_names_children_of_other_resources(self):
        sa = f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa1"
        self.assertEqual(tc.scope_plain(sa), "storage account sa1 (resource group rg)")
        self.assertEqual(
            tc.scope_plain(sa + "/queueServices/default/queues/jobs"),
            "Queue jobs in storage account sa1 (resource group rg)",
        )
        aa = f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Automation/automationAccounts/auto1"
        self.assertEqual(
            tc.scope_plain(aa + "/runbooks/Nightly"),
            "Runbook Nightly in Automation account auto1 (resource group rg)",
        )

    def test_grants_table_where_shows_the_secret(self):
        scope = f"/subscriptions/{SUB}/resourceGroups/dev-tier/providers/Microsoft.KeyVault/vaults/dev-prefix-vault/secrets/s1"
        res = [
            {
                "address": 'azurerm_role_assignment.vendor_writer["a"]',
                "type": "azurerm_role_assignment",
                "action": "create",
                "key": "a",
                "attrs": {
                    "principal_id": PID,
                    "role_definition_name": "Key Vault Secrets Officer",
                    "scope": scope,
                },
            }
        ]
        rows = tc.access_rows(res, {})
        self.assertEqual(
            rows[0]["on"], ["Secret s1 in Key Vault dev-prefix-vault (resource group dev-tier)"]
        )


class NullDefaults(unittest.TestCase):
    """With no data file nothing about an estate is assumed."""

    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("CARD_BRIEF_DATA", "OPSCENTER_REVIEWS_CONFIG")}
        os.environ["CARD_BRIEF_DATA"] = str(TMP / "absent-data.json")
        os.environ["OPSCENTER_REVIEWS_CONFIG"] = str(TMP / "absent-config.json")

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ[k] = v

    def test_defaults_are_generic(self):
        self.assertEqual(cb._admin(), "the owner's admin account")
        self.assertEqual(cb._auto_rule(), "auto-approve")
        self.assertEqual((cb._image_envs(), cb._release_envs()), (set(), set()))
        self.assertEqual(cb._tier("dev"), "dev tier")
        self.assertIn("pipeline itself", cb._root_why("anything"))
        self.assertEqual(cb._env_why("x", "fallback"), "fallback")

    def test_no_owner_means_nobody_is_you_and_no_host_grant_is_inert(self):
        self.assertFalse(cb._is_owner("owner1"))
        g = {"scopes": ["/subscriptions/x/resourceGroups/pool-rg"]}
        self.assertFalse(cb._host_scopes(g))

    def test_pool_roll_is_off_without_the_optional_module(self):
        self.assertFalse(cb.avd_pool.is_roll("any.yml"))


if __name__ == "__main__":
    unittest.main()
