"""
approval_brief_test.py
Purpose: Tests for the approval brief on Reviews cards (approval_brief.py): the style validator,
         the deterministic prose draft, the cache key and signature, the background trigger and
         backoff, secret filtering of the diff, the plan log parser, and one full generation with a
         fake gh and a fake model command. Synthetic data and a scratch store only, nothing reaches GitHub
         or a model.
Date:    2026-10-15
Run:     python3 approval_brief_test.py
"""

import contextlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="approval-brief-"))
os.environ["APPROVAL_BRIEF_STORE"] = str(TMP / "approval-briefs.json")
os.environ["APPROVAL_BRIEF_WORK"] = str(TMP / "work")
os.environ["APPROVAL_BRIEF_TIERS"] = "dev-tier,platform"
os.environ["APPROVAL_BRIEF_MODEL_CMD"] = "/fake/model"
os.environ["APPROVAL_BRIEF_RULES"] = str(TMP / "rules.json")
os.environ["OPSCENTER_REVIEWS_CONFIG"] = str(TMP / "reviews-config.json")
os.environ["APPROVAL_BRIEF_POLICY"] = str(TMP / "policy.json")
os.environ["OPRG_GH_BIN"] = "/nonexistent/gh"
sys.path.insert(0, str(Path(__file__).resolve().parent))
(TMP / "reviews-config.json").write_text(
    json.dumps({"owner": "owner1", "plan_repo": "acme/infra", "other_repo": "acme/app"})
)
(TMP / "rules.json").write_text(
    json.dumps(
        {
            "new-postgres-server": "A new database server needs the owner. Check the plan for whether one is really created",
            "new-identity": "It creates a new identity, which is a new principal that can hold access",
            "rbac-user-or-group": "It assigns a role to a person or a group rather than to a workload identity",
        }
    )
)

import approval_brief as ab  # noqa: E402

HEAD = "a" * 40
GOOD = {
    "does": "This turns on Entra sign-in on the existing tier Postgres server and adds a small subnet for admin jobs.",
    "approving": "You are approving a rebase merge of this commit into main. The plan adds 5 resources and changes none.",
    "review": "The review raised one blocking finding, which was fixed on this head. the owner recommends you approve it.",
}


def mine_item(**over):
    it = {
        "pr": 900,
        "title": "Postgres admin path (synthetic)",
        "head_sha": HEAD,
        "branch": "synthetic-branch",
        "verdict": "blocked",
        "counts": {"blocking": 1, "high": 1, "medium": 0, "low": 0},
        "blocking": [
            {
                "id": "B1",
                "title": "Ops identity can read secrets",
                "location": "x.tf:1",
                "severity": "blocking",
            }
        ],
        "findings": [
            {"id": "H1", "severity": "high", "title": "Public access ignored", "location": "y.tf:2"}
        ],
        "labels": ["ai-review-override"],
        "hold": {
            "kind": "policy",
            "summary": "Everything passes. It waits only on your sign-off for the change below.",
            "rules": [
                {
                    "rule": "new-postgres-server",
                    "where": "infra/platform-core/dev-tier/pg.tf:12",
                    "detail": "type = x",
                    "plain": "Creates a Postgres server",
                },
                {
                    "rule": "new-postgres-server",
                    "where": "infra/platform-core/platform/pg.tf:12",
                    "detail": "type = x",
                    "plain": "Creates a Postgres server",
                },
                {
                    "rule": "new-identity",
                    "where": "infra/platform-core/platform/pg.tf:54",
                    "detail": "",
                    "plain": "Creates a new identity",
                },
            ],
            "plan": "Terraform plan: 5 add, 0 change, 0 destroy, 0 import",
            "plan_detail": {
                "run_id": 11,
                "add": 5,
                "change": 0,
                "destroy": 0,
                "import": 0,
                "roots": [
                    {
                        "job": "terraform plan (platform-core platform)",
                        "summary": "Plan: 5 to add, 0 to change, 0 to destroy.",
                    }
                ],
            },
        },
    }
    it.update(over)
    return it


PLAN_LOG = "\n".join(
    [
        "2026-10-15T17:26:17.2Z Refreshing state...",
        "2026-10-15T17:26:17.2Z Terraform will perform the following actions:",
        "2026-10-15T17:26:17.2Z   # azapi_update_resource.postgres_entra_auth will be created",
        '2026-10-15T17:26:17.2Z   + resource "azapi_update_resource" "postgres_entra_auth" {',
        '2026-10-15T17:26:17.2Z       + type = "Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01"',
        "2026-10-15T17:26:17.2Z     }",
        "2026-10-15T17:26:17.2Z   # azurerm_user_assigned_identity.pg_ops will be created",
        '2026-10-15T17:26:17.2Z   + resource "azurerm_user_assigned_identity" "pg_ops" {',
        '2026-10-15T17:26:17.2Z       + name                = "prod-prefix-pg-ops"',
        "2026-10-15T17:26:17.2Z     }",
        "2026-10-15T17:26:17.2Z Plan: 2 to add, 0 to change, 0 to destroy.",
        "2026-10-15T17:26:17.2Z after the plan",
    ]
)
DIFF = (
    'diff --git a/infra/pg.tf b/infra/pg.tf\n+resource "azurerm_user_assigned_identity" "pg_ops" {}\n'
    '+  client_secret = "SuperSecretValue12345"\n'
    "diff --git a/app/.env.production b/app/.env.production\n+DB_PASSWORD=hunter2hunter2\n"
)


class FakeTools:
    """Fake gh and model command behind approval_brief._run. reply is what the model prints."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []
        self.prompt = ""

    def __call__(self, argv, timeout=60, stdin_text=None):
        self.calls.append(argv)
        if argv[0] == "/fake/model":
            self.prompt = stdin_text or ""
            if isinstance(self.reply, Exception):
                raise self.reply
            return self.reply + "\n\nsession_id: 20261015_000000_abcdef\n"
        if argv[1:3] == ["pr", "view"]:
            return json.dumps(
                {
                    "body": "## What\n\nTurns on Entra sign-in on the tier Postgres servers.\n\nMore detail.",
                    "files": [{"path": "infra/pg.tf"}],
                }
            )
        if argv[1:3] == ["pr", "diff"]:
            return DIFF
        if argv[1] == "api" and "/jobs?" in " ".join(argv):
            return json.dumps({"name": "terraform plan (platform-core platform)", "id": 77}) + "\n"
        if argv[1] == "api" and "jobs/77/logs" in argv[-1]:
            return PLAN_LOG
        raise ab.BriefError(f"unexpected call {argv}")


def reset_store():
    with contextlib.suppress(OSError):
        ab.STORE.unlink()


class ValidateTest(unittest.TestCase):
    def test_accepts_plain_prose(self):
        self.assertEqual(ab.validate(GOOD)["does"], GOOD["does"])

    def test_rejects_style_breaks(self):
        for bad in (
            "It merges \u2014 then applies the plan and more words here.",
            "It merges, then applies; the plan adds five resources here.",
        ):
            with self.assertRaises(ab.BriefError):
                ab.validate(dict(GOOD, approving=bad))
        with self.assertRaises(ab.BriefError):
            ab.validate(
                dict(GOOD, review="Findings:\n- B1 is fixed on this head\n- H1 is accepted for now")
            )
        with self.assertRaises(ab.BriefError):
            ab.validate(
                dict(
                    GOOD,
                    does="It turns on Entra sign\u2011in on the existing server for admin jobs.",
                )
            )
        with self.assertRaises(ab.BriefError):
            ab.validate(dict(GOOD, does="Too short."))
        with self.assertRaises(ab.BriefError):
            ab.validate({"does": GOOD["does"]})

    def test_parse_skips_session_lines(self):
        out = ab._parse("Warning: x\n" + json.dumps(GOOD) + "\nsession_id: 1")
        self.assertEqual(out["review"], GOOD["review"])
        with self.assertRaises(ab.BriefError):
            ab._parse("no json here")


class FallbackTest(unittest.TestCase):
    def test_prose_no_bullets_no_banned_marks(self):
        s = ab.subject("plan", mine_item(), "mine")
        f = ab.fallback(
            s, {"body_lead": "Turns on Entra sign-in; keeps \u2014 passwords.", "resources": []}
        )
        for k in ("does", "approving", "review"):
            self.assertTrue(f[k])
            self.assertNotIn(";", f[k])
            self.assertNotIn("\u2014", f[k])
            self.assertIsNone(ab._BULLET.search(f[k]))
            self.assertTrue(all(ord(c) < 128 for c in f[k]))
        self.assertIn("Approve and merge", f["approving"])
        self.assertIn("5 to add", f["approving"])
        # The Postgres rule explains that it also fires on an update to an existing server.
        self.assertIn("Check the plan for whether one is really created", f["approving"])
        self.assertIn("both tiers (dev-tier and platform)", f["approving"])
        self.assertIn("B1 (Ops identity can read secrets)", f["review"])

    def test_resources_named_when_known(self):
        s = ab.subject("plan", mine_item(), "mine")
        ctx = {
            "resources": [
                {
                    "root": "platform-core (platform)",
                    "address": "azurerm_user_assigned_identity.pg_ops",
                    "action": "will be created",
                    "name": "prod-prefix-pg-ops",
                }
            ]
        }
        self.assertIn(
            "azurerm_user_assigned_identity.pg_ops (prod-prefix-pg-ops) will be created",
            ab.fallback(s, ctx)["approving"],
        )

    def test_engineer_and_other_cards(self):
        need = {
            "pr": 5,
            "title": "Engineer change",
            "author": "dev1",
            "head_sha": HEAD,
            "sources": ["review", "tfplan"],
            "breakdown": {
                "summary": "Adds a storage container",
                "rules": ["rbac-user-or-group: grant to a user"],
                "risk": {"level": "medium", "why": "a user grant"},
                "recommendation": {"action": "approve", "why": "scoped to one container"},
            },
            "tfplan": {"held_reasons": ["role assignment"], "files": ["a.tf"]},
        }
        f = ab.fallback(ab.subject("plan", need, "need"))
        self.assertIn("Approve as me", f["approving"])
        self.assertIn("held terraform-plan runs", f["approving"])
        self.assertIn("recommends approve", f["review"])
        other_row = {
            "pr": 8,
            "title": "other change",
            "head_sha": HEAD,
            "kind": "signoff",
            "rules": ["Changes .github/ (workflows)"],
            "why": "Everything passes.",
        }
        self.assertIn(
            "Changes .github/ (workflows)",
            ab.fallback(ab.subject("other", other_row, "other"))["approving"],
        )

    def test_no_card_for_non_decisions(self):
        self.assertIsNone(
            ab.subject("plan", mine_item(hold={"kind": "waiting", "summary": "x"}), "mine")
        )
        self.assertIsNone(ab.subject("other", {"pr": 1, "head_sha": HEAD}, "other"))


class SignatureTest(unittest.TestCase):
    def test_stable_on_wording_moves_on_rules(self):
        a = ab.subject("plan", mine_item(), "mine")
        it = mine_item()
        it["hold"] = dict(it["hold"], summary="Different wording")
        self.assertEqual(ab.signature(a), ab.signature(ab.subject("plan", it, "mine")))
        it["hold"] = dict(it["hold"], rules=it["hold"]["rules"][:1])
        self.assertNotEqual(ab.signature(a), ab.signature(ab.subject("plan", it, "mine")))
        self.assertEqual(ab.key_of(a), f"plan#900@{HEAD}")


class TriggerTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.spawned = []
        self._spawn = ab._spawn
        ab._spawn = lambda s, sig: self.spawned.append(ab.key_of(s)) or True

    def tearDown(self):
        ab._spawn = self._spawn

    def test_draft_then_model(self):
        s = ab.subject("plan", mine_item(), "mine")
        b = ab.brief_for(s)
        self.assertEqual((b["source"], b["pending"]), ("draft", True))
        self.assertEqual(self.spawned, [ab.key_of(s)])
        ab._update(
            ab.key_of(s), sig=ab.signature(s), status="ready", brief=GOOD, generated_at=ab._now()
        )
        b = ab.brief_for(s)
        self.assertEqual((b["source"], b["does"]), ("model", GOOD["does"]))
        self.assertEqual(len(self.spawned), 1)

    def test_rule_change_regenerates(self):
        s = ab.subject("plan", mine_item(), "mine")
        ab._update(ab.key_of(s), sig="old", status="ready", brief=GOOD, generated_at=ab._now())
        self.assertEqual(ab.brief_for(s)["source"], "draft")
        self.assertEqual(len(self.spawned), 1)

    def test_failure_backoff_and_cap(self):
        s = ab.subject("plan", mine_item(), "mine")
        sig = ab.signature(s)
        ab._update(
            ab.key_of(s),
            sig=sig,
            status="failed",
            error="model timed out",
            attempts=1,
            attempted_at=ab._now(),
        )
        b = ab.brief_for(s)
        self.assertEqual(
            (b["source"], b["pending"], b["error"]), ("draft", False, "model timed out")
        )
        self.assertEqual(self.spawned, [])
        ab._update(ab.key_of(s), attempted_at="2020-01-01T00:00:00Z")
        ab.brief_for(s)
        self.assertEqual(len(self.spawned), 1)
        ab._update(ab.key_of(s), attempts=ab.MAX_ATTEMPTS)
        ab.brief_for(s)
        self.assertEqual(len(self.spawned), 1)

    def test_new_head_replaces_old_entry(self):
        ab._update("platform#900@" + "b" * 40, status="ready")
        ab._update("platform#900@" + HEAD, status="ready")
        self.assertEqual(list(ab._load()["briefs"]), ["platform#900@" + HEAD])

    def test_decorate_does_not_mutate_and_skips_non_decisions(self):
        data = {
            "my_prs": [mine_item(), mine_item(pr=901, hold={"kind": "problem", "summary": "red"})],
            "needs_me": [],
            "counts": {},
        }
        out = ab.decorate_plan(data)
        self.assertNotIn("brief", data["my_prs"][0])
        self.assertIn("brief", out["my_prs"][0])
        self.assertNotIn("brief", out["my_prs"][1])


class GenerateTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self._run = ab._run

    def tearDown(self):
        ab._run = self._run

    def test_full_generation_filters_secrets(self):
        fake = FakeTools(json.dumps(GOOD))
        ab._run = fake
        s = ab.subject("plan", mine_item(), "mine")
        ent = ab.generate(s)
        self.assertEqual(ent["status"], "ready", ent.get("error"))
        self.assertEqual(ent["brief"]["review"], GOOD["review"])
        self.assertNotIn("hunter2", fake.prompt)
        self.assertNotIn("SuperSecretValue12345", fake.prompt)
        self.assertIn("app/.env.production", fake.prompt)  # named as skipped, content left out
        self.assertIn("azurerm_user_assigned_identity.pg_ops will be created", fake.prompt)
        self.assertIn("Approve and merge", fake.prompt)
        names = {r["address"]: r["name"] for r in ent["ctx"]["resources"]}
        self.assertEqual(names["azurerm_user_assigned_identity.pg_ops"], "prod-prefix-pg-ops")
        self.assertEqual(names["azapi_update_resource.postgres_entra_auth"], "")
        self.assertEqual(
            [c for c in fake.calls if c[0] == "/fake/model"], [["/fake/model"]]
        )  # the prompt goes on stdin
        self.assertEqual(ab.brief_for(s, kick=False)["source"], "model")

    def test_code_named_after_secrets_is_shown_redacted(self):
        # secrets-pending.py is code. Its diff goes to the model, inline values redacted.
        self.assertFalse(ab._withheld(".github/scripts/secrets-pending.py"))
        self.assertFalse(ab._withheld("apps/x/infra/secrets.tf"))
        for p in (
            "app/.env.production",
            "infra/prod.tfvars",
            "certs/client-secret.pem",
            "secrets.json",
            "db_password.txt",
        ):
            self.assertTrue(ab._withheld(p), p)
        raw = (
            "diff --git a/.github/scripts/secrets-pending.py b/.github/scripts/secrets-pending.py\n"
            "-      --content-type vendor\n+      --content-type manual\n"
            '+API_TOKEN = "SyntheticTokenValue123456"\n'
        )
        ab._run = lambda argv, timeout=60, stdin_text=None: raw
        text, skipped = ab._diff("github-user/example", 1)
        self.assertEqual(skipped, [])
        self.assertIn("--content-type manual", text)
        self.assertNotIn("SyntheticTokenValue123456", text)

    def test_style_break_falls_back(self):
        ab._run = FakeTools(
            json.dumps(
                dict(GOOD, review="It is fine; approve it, the finding is fixed on this head.")
            )
        )
        s = ab.subject("plan", mine_item(), "mine")
        ent = ab.generate(s)
        self.assertEqual(ent["status"], "failed")
        self.assertIn("semicolon", ent["error"])
        b = ab.brief_for(s, kick=False)
        self.assertEqual(b["source"], "draft")
        self.assertIn(
            "Turns on Entra sign-in", b["does"]
        )  # the draft uses the description lead once gathered

    def test_model_error_is_recorded(self):
        ab._run = FakeTools(ab.BriefError("model timed out after 240s"))
        ent = ab.generate(ab.subject("plan", mine_item(), "mine"))
        self.assertEqual((ent["status"], ent["error"]), ("failed", "model timed out after 240s"))


class TriageDriftTest(unittest.TestCase):
    """the brief of the owner's own PR carries the owner's triage replies, the override event and branch drift."""

    TRIAGE = {
        "replies": [
            {
                "ids": ["B1"],
                "text": "Accepted. The identity is scoped to the app vault.",
                "at": "2026-10-22T11:00:00Z",
                "after_review": True,
            },
            {"ids": ["B2"], "text": "stale", "at": "2026-10-22T08:00:00Z", "after_review": False},
        ],
        "override": {"actor": "owner1", "at": "2026-10-22T11:05:00Z"},
    }
    DRIFT = [{"address": "azurerm_x.a", "root": "dev", "app": "relay", "pr": 434, "branch": "feat"}]

    def item(self, **over):
        it = mine_item(triage=self.TRIAGE)
        it["hold"] = dict(
            it["hold"],
            plan_detail=dict(it["hold"].get("plan_detail") or {}, branch_drift=self.DRIFT),
        )
        it.update(over)
        return it

    def test_subject_carries_replies_override_and_drift(self):
        s = ab.subject("plan", self.item(), "mine")
        self.assertEqual([r["ids"] for r in s["triage"]["replies"]], [["B1"]])
        self.assertEqual(s["triage"]["override"], {"by": "owner1", "at": "2026-10-22T11:05:00Z"})
        self.assertEqual(s["branch_drift"][0]["pr"], 434)

    def test_override_dropped_when_the_label_is_off(self):
        s = ab.subject("plan", self.item(labels=[]), "mine")
        self.assertIsNone(s["triage"]["override"])

    def test_no_triage_is_none(self):
        self.assertIsNone(ab.subject("plan", mine_item(), "mine")["triage"])

    def test_signature_moves_on_reply_override_and_drift(self):
        base = ab.signature(ab.subject("plan", self.item(), "mine"))
        none = ab.signature(ab.subject("plan", mine_item(), "mine"))
        self.assertNotEqual(base, none)
        t2 = json.loads(json.dumps(self.TRIAGE))
        t2["override"] = None
        self.assertNotEqual(base, ab.signature(ab.subject("plan", self.item(triage=t2), "mine")))
        t3 = json.loads(json.dumps(self.TRIAGE))
        t3["replies"][0]["text"] = "Different reason."
        self.assertNotEqual(base, ab.signature(ab.subject("plan", self.item(triage=t3), "mine")))
        it = self.item()
        it["hold"]["plan_detail"]["branch_drift"] = []
        self.assertNotEqual(base, ab.signature(ab.subject("plan", it, "mine")))

    def test_prompt_carries_the_facts_and_the_rules(self):
        s = ab.subject("plan", self.item(), "mine")
        p = ab.build_prompt(s, {})
        self.assertIn("Accepted. The identity is scoped to the app vault.", p)
        self.assertIn("owner1", p)
        self.assertIn("azurerm_x.a", p)
        self.assertIn("accepted risk", p)
        self.assertIn("BRANCH DRIFT", p)

    def test_fallback_draft_says_accepted_risk_and_drift_owner(self):
        s = ab.subject("plan", self.item(), "mine")
        r = ab.fallback(s)["review"]
        self.assertIn("accepted risk", r)
        self.assertIn("#434", r)

    def test_other_mine_row_carries_triage(self):
        row = {"pr": 5, "head_sha": HEAD, "kind": "signoff", "mine": True, "triage": self.TRIAGE}
        self.assertEqual(ab.subject("other", row, "other")["triage"]["replies"][0]["ids"], ["B1"])
        row["mine"] = False
        self.assertIsNone(ab.subject("other", row, "other")["triage"])

    def test_need_lane_reads_drift_from_the_plan(self):
        it = {
            "pr": 7,
            "head_sha": HEAD,
            "plan": {"ran": True, "run_id": 1, "branch_drift": self.DRIFT, "roots": []},
        }
        self.assertEqual(ab.subject("plan", it, "need")["branch_drift"][0]["app"], "relay")


class NullDefaults(unittest.TestCase):
    def setUp(self):
        self.saved = {
            k: os.environ.get(k)
            for k in (
                "APPROVAL_BRIEF_MODEL_CMD",
                "OPSCENTER_REVIEWS_CONFIG",
                "APPROVAL_BRIEF_RULES",
            )
        }

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        reset_store()

    def test_no_model_means_no_generation_and_a_clear_error(self):
        os.environ.pop("APPROVAL_BRIEF_MODEL_CMD")
        self.assertFalse(ab.model_configured())
        with self.assertRaises(ab.BriefError):
            ab.call_model("x")
        s = ab.subject("plan", mine_item(), "mine")
        self.assertFalse(ab._spawn(s, ab.signature(s)))
        out = ab.brief_for(s, kick=True)
        self.assertEqual(out["source"], "draft")
        self.assertTrue(out["approving"])  # the deterministic draft, never blank

    def test_no_repos_configured_refuses_a_request_with_400(self):
        os.environ["OPSCENTER_REVIEWS_CONFIG"] = str(TMP / "none.json")
        self.assertEqual(ab._repos(), {})
        with self.assertRaises(ab.BriefError) as e:
            ab.request({"repo": "plan", "pr": 1})
        self.assertEqual(e.exception.status, 400)

    def test_an_unknown_card_is_a_404_and_rule_text_is_data(self):
        with self.assertRaises(ab.NotFound) as e:
            ab.request({"repo": "plan", "pr": 424242})
        self.assertEqual(e.exception.status, 404)
        os.environ["APPROVAL_BRIEF_RULES"] = str(TMP / "absent-rules.json")
        self.assertEqual(sorted(ab._rule_why()), ["ai-review-override", "github-dir"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
