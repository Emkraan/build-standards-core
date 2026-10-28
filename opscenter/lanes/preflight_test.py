#!/usr/bin/env python3
"""
preflight_test.py
Purpose: Tests for preflight.py on synthetic git repos (a bare origin plus a clone), a fake gh
         and repo gates switched off. Never touches a real repo or GitHub.
Run:     python3 preflight_test.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "preflight.py"
DASH = "\u2014"


def sh(args, cwd, env=None):
    r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise AssertionError(f"{args} failed: {r.stderr}")
    return r.stdout


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pf-test-", dir=os.environ.get("TMPDIR")))
        self.origin = self.tmp / "origin.git"
        self.wt = self.tmp / "wt"
        sh(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], self.tmp)
        sh(["git", "clone", "-q", str(self.origin), str(self.wt)], self.tmp)
        self.git("config", "user.name", "owner-name")
        self.git("config", "user.email", "owner@users.noreply.github.com")
        self.write("apps/demo/lib/version.ts", 'export const APP_VERSION = "1.2.3";\n')
        self.write("apps/demo/server/index.js", "module.exports = 1;\n")
        self.write(
            "infrastructure/terraform/core/main.tf",
            'resource "azurerm_resource_group" "rg" {\n  name = "rg"\n}\n',
        )
        self.write("README.md", "demo\n")
        self.commit("chore: seed")
        self.git("push", "-q", "origin", "main")
        self.git("switch", "-q", "-c", "TKT-1-demo-change")
        self.gh_out = self.tmp / "gh.json"
        self.gh_out.write_text("[]")
        fake = self.tmp / "gh"
        fake.write_text(
            '#!/bin/sh\nif [ -n "$FAKE_GH_FAIL" ]; then echo boom >&2; exit 1; fi\ncat "$FAKE_GH_OUT"\n'
        )
        fake.chmod(0o755)
        (self.tmp / "engine.py").write_text(
            "def policy_hits(pol, files, diff, own=False):\n"
            "    return [{'rule': 'github-dir', 'reason': 'changes .github/', 'where': f} for f in files if f.startswith('.github/') and not f.startswith('.github/scripts/')]\n"
        )
        (self.tmp / "policy.json").write_text("{}")
        self.targets = self.tmp / "targets.json"
        self.targets.write_text(
            json.dumps(
                {
                    "self_login": "owner-login",
                    "author_name": "owner-name",
                    "author_email": "owner@users.noreply.github.com",
                    "targets": {
                        "prod": {
                            "repo": "owner/prod",
                            "version_file": "lib/version.ts",
                            "branch_rule": r"^TKT-\d+-[a-z0-9][a-z0-9-]*(--[a-z0-9-]+)?$",
                            "prompts": [
                                ".github/prompts/pr-review-constructive.md",
                                ".github/prompts/pr-review-redteam.md",
                            ],
                            "catalog": str(self.tmp / "finding-catalog.md"),
                            "js_gate": "workspace",
                            "plan_matcher": str(HERE / "tfplan_gate.py"),
                            "lane_engine": str(self.tmp / "engine.py"),
                            "policy": str(self.tmp / "policy.json"),
                        },
                        "team": {"repo": "owner/team", "version_file": "lib/version.ts"},
                    },
                }
            )
        )
        self.env = dict(
            os.environ,
            AUTOFIX_TARGETS=str(self.targets),
            PREFLIGHT_GH_BIN=str(fake),
            FAKE_GH_OUT=str(self.gh_out),
            PREFLIGHT_GATES="off",
            PREFLIGHT_LOCAL_REVIEW="off",
        )

    def git(self, *a):
        return sh(["git"] + list(a), self.wt)

    def write(self, rel, text):
        p = self.wt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self, msg, author=None):
        self.git("add", "-A")
        args = ["git"]
        if author:
            args += ["-c", f"user.name={author[0]}", "-c", f"user.email={author[1]}"]
        sh(args + ["commit", "-q", "-m", msg], self.wt)

    def run_pf(self, *extra, env=None):
        out = self.tmp / "out.json"
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "run",
                "--repo",
                "prod",
                "--worktree",
                str(self.wt),
                "--json",
                str(out),
            ]
            + list(extra),
            capture_output=True,
            text=True,
            env=env or self.env,
        )
        data = json.loads(out.read_text()) if out.exists() else {}
        return r.returncode, data, r.stdout

    def status(self, data, cid):
        for c in data.get("checks", []):
            if c["id"] == cid:
                return c["status"]
        return None

    def self_review(self, body="NONE: nothing high"):
        _, data, _ = self.run_pf()
        gd = Path(self.git("rev-parse", "--absolute-git-dir").strip())
        (gd / "preflight-review.md").write_text(f"diff: {data['diff_hash']}\n{body}\n")

    def good_change(self):
        self.write("apps/demo/server/index.js", "module.exports = 2;\n")
        self.write("apps/demo/lib/version.ts", 'export const APP_VERSION = "1.2.4";\n')
        self.commit("fix(demo): return two")


class PreflightTest(Base):
    def test_clean_change_passes_with_self_review(self):
        self.good_change()
        self.self_review()
        rc, data, out = self.run_pf()
        self.assertEqual(rc, 0, out)
        self.assertEqual(data["result"], "pass")
        self.assertEqual(self.status(data, "self-review"), "pass")

    def test_missing_self_review_fails(self):
        self.good_change()
        rc, data, _ = self.run_pf()
        self.assertEqual(rc, 1)
        self.assertEqual(self.status(data, "self-review"), "fail")

    def test_stale_self_review_fails_after_diff_changes(self):
        self.good_change()
        self.self_review()
        self.write("apps/demo/server/index.js", "module.exports = 3;\n")
        self.commit("fix(demo): return three")
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "self-review"), "fail")

    def test_pre_triage_without_evidence_fails(self):
        self.good_change()
        self.self_review("PRE-TRIAGE: the grant is fine")
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "self-review"), "fail")

    def test_pre_triage_lands_in_pr_body_notes(self):
        self.good_change()
        self.self_review("PRE-TRIAGE: Grant is app scoped | main.tf:12 scope is the app vault")
        rc, data, _ = self.run_pf()
        self.assertEqual(rc, 0)
        self.assertIn("Grant is app scoped", data["pr_body_notes"])

    def test_missing_version_bump_fails(self):
        self.write("apps/demo/server/index.js", "module.exports = 2;\n")
        self.commit("fix(demo): return two")
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "version-bump"), "fail")

    def test_deleted_version_file_fails(self):
        (self.wt / "apps/demo/lib/version.ts").unlink()
        self.write("apps/demo/server/index.js", "module.exports = 2;\n")
        self.commit("fix(demo): drop version")
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "version-bump"), "fail")
        self.assertEqual(self.status(data, "catalog"), "fail")

    def test_em_dash_and_escaped_dash_fail(self):
        self.good_change()
        self.write("apps/demo/server/a.js", f"// a {DASH} b\nconst s = '\\u2014';\n")
        self.commit("fix(demo): note")
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "em-dash"), "fail")

    def test_non_ascii_in_powershell_fails(self):
        self.write("runbooks/x.ps1", "Write-Output 'caf\u00e9'\n")
        self.commit("feat(runbooks): add x")
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "ascii"), "fail")

    def test_secret_literal_fails(self):
        self.write("runbooks/y.ps1", "$password = 'Sup3rS3cretValue!'\n")
        self.commit("feat(runbooks): add y")
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "secrets"), "fail")

    def test_key_vault_reference_is_not_a_secret(self):
        self.write(
            "infrastructure/terraform/core/kv.tf",
            'locals {\n  secret = "@Microsoft.KeyVault(SecretUri=https://x.vault.azure.net/secrets/y)"\n}\n',
        )
        self.commit("feat(core): kv ref")
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "secrets"), "pass")

    def test_bad_branch_name_fails(self):
        self.git("switch", "-q", "-c", "feature/whatever")
        self.good_change()
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "branch-name"), "fail")

    def test_foreign_author_and_attribution_fail(self):
        self.write("apps/demo/lib/version.ts", 'export const APP_VERSION = "1.2.4";\n')
        self.commit("fix: x\n\nCo-authored-by: Someone <s@example.com>")
        self.write("README.md", "demo two\n")
        self.commit("docs: y", author=("Other Person", "other@example.com"))
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "commits"), "fail")

    def test_azapi_import_id_with_query_fails(self):
        self.write(
            "infrastructure/terraform/core/imports.tf",
            'import {\n  to = azapi_resource.t\n  id = "/subscriptions/x/resourceGroups/rg/providers/Microsoft.OperationalInsights/workspaces/w/tables/T_CL?api-version=2022-10-01"\n}\n',
        )
        self.commit("feat(core): import table")
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "catalog"), "fail")

    def test_removed_resource_block_warns(self):
        self.write("infrastructure/terraform/core/main.tf", "# emptied\n")
        self.commit("refactor(core): drop rg")
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "catalog"), "warn")

    def test_subscription_scope_grant_warns(self):
        self.write(
            "infrastructure/terraform/core/rbac.tf",
            'resource "azurerm_role_assignment" "r" {\n  scope = "/subscriptions/'
            + "-".join(["0" * 8, "0" * 4, "0" * 4, "0" * 4, "0" * 12])
            + '"\n}\n',
        )
        self.commit("feat(core): grant")
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "catalog"), "warn")

    def test_github_change_is_an_expected_signoff(self):
        self.write(".github/workflows/x.yml", "name: x\non: push\njobs: {}\n")
        self.commit("ci: add x")
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "expected-signoff"), "info")
        rules = {h["rule"] for h in data["expected_signoff"]}
        self.assertIn("github-dir", rules)
        self.assertIn("tfplan-matcher", rules)

    def test_plain_github_script_uses_the_own_pr_rule(self):
        # the preview applies the lane's own-PR .github rule. A plain script edit is not a
        # github-dir sign-off. Before the push the tfplan matcher cannot read the head, so it stays held.
        self.git("switch", "-q", "main")
        self.write(".github/scripts/util.py", "def add(a, b):\n    return a + b\n")
        self.commit("chore: seed script")
        self.git("push", "-q", "origin", "main")
        self.git("switch", "-q", "TKT-1-demo-change")
        self.git("rebase", "-q", "main")
        self.write(
            ".github/scripts/util.py", "def add(a, b):\n    total = a + b\n    return total\n"
        )
        self.commit("chore: tidy util")
        rc, data, _ = self.run_pf()
        rules = {h["rule"] for h in data.get("expected_signoff") or []}
        self.assertNotIn("github-dir", rules)
        self.assertIn("tfplan-matcher", rules)

    def test_conflict_with_main_fails(self):
        self.write("README.md", "branch side\n")
        self.commit("docs: branch")
        self.git("switch", "-q", "main")
        self.write("README.md", "main side\n")
        self.commit("docs: main")
        self.git("push", "-q", "origin", "main")
        self.git("switch", "-q", "TKT-1-demo-change")
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "conflict"), "fail")

    def test_behind_main_without_conflict_warns(self):
        self.good_change()
        self.git("switch", "-q", "main")
        self.write("OTHER.md", "x\n")
        self.commit("docs: other")
        self.git("push", "-q", "origin", "main")
        self.git("switch", "-q", "TKT-1-demo-change")
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "conflict"), "warn")

    def test_overlap_with_another_open_pr_warns(self):
        self.write(
            "infrastructure/terraform/core/main.tf",
            'resource "azurerm_resource_group" "rg" {\n  name = "rg2"\n}\n',
        )
        self.commit("feat(core): rename")
        self.gh_out.write_text(
            json.dumps(
                [
                    {
                        "number": 77,
                        "headRefName": "ticket-id-other",
                        "files": [{"path": "infrastructure/terraform/core/other.tf"}],
                    }
                ]
            )
        )
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "overlap"), "warn")
        self.assertIn("#77", next(c["detail"] for c in data["checks"] if c["id"] == "overlap"))

    def test_own_branch_pr_is_not_an_overlap(self):
        self.write(
            "infrastructure/terraform/core/main.tf",
            'resource "azurerm_resource_group" "rg" {\n  name = "rg2"\n}\n',
        )
        self.commit("feat(core): rename")
        self.gh_out.write_text(
            json.dumps(
                [
                    {
                        "number": 78,
                        "headRefName": "TKT-1-demo-change",
                        "files": [{"path": "infrastructure/terraform/core/main.tf"}],
                    }
                ]
            )
        )
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "overlap"), "pass")

    def test_gh_failure_is_an_environment_problem(self):
        self.write(
            "infrastructure/terraform/core/main.tf",
            'resource "azurerm_resource_group" "rg" {\n  name = "rg2"\n}\n',
        )
        self.commit("feat(core): rename")
        rc, data, out = self.run_pf(env=dict(self.env, FAKE_GH_FAIL="1"))
        self.assertEqual(rc, 2, out)
        self.assertIn("ENVIRONMENT PROBLEM", out)

    def test_untracked_file_is_checked_and_index_untouched(self):
        self.good_change()
        self.write("apps/demo/server/new.js", f"// {DASH}\n")
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "em-dash"), "fail")
        self.assertEqual(self.status(data, "uncommitted"), "warn")
        self.assertIn("?? apps/demo/server/new.js", self.git("status", "--porcelain"))

    def test_not_a_worktree_is_an_environment_problem(self):
        r = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "run",
                "--repo",
                "prod",
                "--worktree",
                str(self.tmp / "nope"),
            ],
            capture_output=True,
            text=True,
            env=self.env,
        )
        self.assertEqual(r.returncode, 2)


FAKE_HERMES = """#!/usr/bin/python3
import json, os, sys
q = sys.stdin.read()
log = os.environ["FAKE_HERMES_LOG"]
with open(log, "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "query": q}) + "\\n")
mode = "redteam" if "REDTEAM-PROMPT" in q else "constructive"
out = os.environ.get("FAKE_REVIEW_" + mode.upper()) or os.environ.get("FAKE_REVIEW")
if out == "FAIL":
    sys.stderr.write("boom")
    sys.exit(1)
print(out)
print("")
print("session_id: 20261023_000000_abcdef")
"""

HIGH = json.dumps(
    {
        "summary": "x",
        "findings": [
            {
                "title": "Applier gate fails open",
                "severity": "high",
                "blocking_reason": "none",
                "location": "apps/demo/server/index.js:1",
                "summary": "a skipped job passes the gate",
                "fix": "fail closed",
            },
            {
                "title": "nit",
                "severity": "low",
                "blocking_reason": "none",
                "location": "x:1",
                "summary": "s",
                "fix": "f",
            },
        ],
    }
)
CLEAN = json.dumps({"summary": "fine", "findings": []})


class ReviewBase(Base):
    def setUp(self):
        super().setUp()
        self.git("switch", "-q", "main")
        self.write(
            ".github/prompts/pr-review-constructive.md", "CONSTRUCTIVE-PROMPT\n{{CONTEXT_FILES}}\n"
        )
        self.write(".github/prompts/pr-review-redteam.md", "REDTEAM-PROMPT\n{{CONTEXT_FILES}}\n")
        self.write(
            ".github/ai-review/models.json", '{"claude": "claude-test-1", "openai": "gpt-test-1"}\n'
        )
        self.write("AGENTS.md", "REPO-CONTEXT-MARKER\n")
        self.commit("chore: review inputs")
        self.git("push", "-q", "origin", "main")
        self.git("switch", "-q", "TKT-1-demo-change")
        self.git("merge", "-q", "--ff-only", "main")
        self.log = self.tmp / "hermes.log"
        fake = self.tmp / "hermes"
        fake.write_text(FAKE_HERMES)
        fake.chmod(0o755)
        self.env = dict(
            self.env,
            PREFLIGHT_HERMES_BIN=str(fake),
            FAKE_HERMES_LOG=str(self.log),
            FAKE_REVIEW=CLEAN,
        )
        self.env.pop("PREFLIGHT_LOCAL_REVIEW")
        self.env["PREFLIGHT_CODEX_BIN"] = ""
        self.env["PREFLIGHT_REVIEW_PROVIDERS"] = "claude"
        self.env.pop("PREFLIGHT_OPENAI_KEY_CMD", None)  # no key command unless a test sets one
        self.good_change()

    def review(self, **extra):
        env = dict(self.env, **extra)
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "review", "--repo", "prod", "--worktree", str(self.wt)],
            capture_output=True,
            text=True,
            env=env,
        )
        return r.returncode, r.stdout

    def gd(self):
        return Path(self.git("rev-parse", "--absolute-git-dir").strip())

    def calls(self):
        return (
            [json.loads(ln) for ln in self.log.read_text().splitlines()]
            if self.log.exists()
            else []
        )

    def write_self_review(self, extra=""):
        _, data, _ = self.run_pf()
        (self.gd() / "preflight-review.md").write_text(
            f"diff: {data['diff_hash']}\nNONE: nothing high\n{extra}"
        )
        return data["diff_hash"]


class LocalReviewTest(ReviewBase):
    def test_run_fails_until_a_review_exists(self):
        self.write_self_review()
        rc, data, _ = self.run_pf()
        self.assertEqual(rc, 1)
        self.assertEqual(self.status(data, "local-review"), "fail")

    def test_clean_review_passes_the_gate(self):
        rc, out = self.review()
        self.assertEqual(rc, 0, out)
        self.assertIn("CLEAN", out)
        self.write_self_review()
        rc, data, out = self.run_pf()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.status(data, "local-review"), "pass")

    def test_reviewers_use_the_ci_prompts_context_and_models_from_origin_main(self):
        self.review()
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        queries = " ".join(c["query"] for c in calls)
        self.assertIn("CONSTRUCTIVE-PROMPT", queries)
        self.assertIn("REDTEAM-PROMPT", queries)
        self.assertIn("REPO-CONTEXT-MARKER", queries)
        self.assertNotIn("{{CONTEXT_FILES}}", queries)
        self.assertIn("module.exports = 2", queries)
        for c in calls:
            self.assertIn("claude-test-1", c["argv"])
            self.assertIn("--safe-mode", c["argv"])
        self.assertEqual(
            {"constructive", "redteam"},
            {"constructive" if "CONSTRUCTIVE-PROMPT" in c["query"] else "redteam" for c in calls},
        )

    def test_highs_fail_and_a_refutation_with_evidence_clears_them(self):
        rc, out = self.review(FAKE_REVIEW=HIGH)
        self.assertEqual(rc, 1, out)
        self.assertIn("LR-", out)
        key = [w for w in out.split() if w.startswith("LR-")][0]
        self.write_self_review()
        rc, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "local-review"), "fail")
        self.write_self_review(
            f"REFUTED: {key} | apps/demo/server/index.js:1 the gate reads the job result first\n"
        )
        rc, data, out = self.run_pf()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.status(data, "local-review"), "pass")

    def test_refutation_without_evidence_does_not_count(self):
        rc, out = self.review(FAKE_REVIEW=HIGH)
        key = [w for w in out.split() if w.startswith("LR-")][0]
        self.write_self_review(f"REFUTED: {key}\n")
        _, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "local-review"), "fail")

    def test_a_changed_diff_needs_a_new_review(self):
        self.review()
        self.write("apps/demo/server/index.js", "module.exports = 9;\n")
        self.commit("fix(demo): nine")
        self.write_self_review()
        _, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "local-review"), "fail")

    def test_same_diff_is_not_reviewed_twice_without_again(self):
        self.review()
        n = len(self.calls())
        rc, out = self.review()
        self.assertEqual(len(self.calls()), n)
        self.assertEqual(rc, 0)

    def test_three_rounds_then_pass_with_open_highs_listed(self):
        for i in range(3):
            rc, out = self.review(FAKE_REVIEW=HIGH)
            self.assertEqual(rc, 1 if i < 2 else 0, out)
            self.write("apps/demo/server/index.js", f"module.exports = {10 + i};\n")
            self.commit(f"fix(demo): round {i}")
        self.assertIn("BUDGET SPENT", out)
        calls_before = len(self.calls())
        h = self.write_self_review()
        rc, data, out = self.run_pf()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.status(data, "local-review"), "warn")
        self.assertEqual(len(self.calls()), calls_before, "no fourth round calls a model")
        text = (self.gd() / "preflight-review.md").read_text()
        self.assertTrue(text.startswith(f"diff: {h}"))
        self.assertIn("OPEN-HIGH: LR-", text)
        self.assertIn("Applier gate fails open", data["pr_body_notes"])
        rc2, data2, _ = self.run_pf()
        self.assertEqual(rc2, 0)
        self.assertEqual(
            (self.gd() / "preflight-review.md").read_text().count("OPEN-HIGH:"), 1, "idempotent"
        )

    def test_reviewer_failure_fails_closed(self):
        rc, out = self.review(FAKE_REVIEW="FAIL")
        self.assertEqual(rc, 2, out)
        self.write_self_review()
        rc, data, _ = self.run_pf()
        self.assertEqual(rc, 1)
        self.assertEqual(self.status(data, "local-review"), "fail")

    def test_one_failed_reviewer_is_not_a_clean_review_and_costs_no_round(self):
        rc, out = self.review(FAKE_REVIEW_REDTEAM="FAIL")
        self.assertEqual(rc, 2, out)
        self.write_self_review()
        _, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "local-review"), "fail")
        self.assertIn(
            "not independent", [c for c in data["checks"] if c["id"] == "local-review"][0]["detail"]
        )
        rc, out = self.review()
        self.assertEqual(rc, 0, out)
        self.assertEqual(
            len(json.loads((self.gd() / "local-review.json").read_text())["rounds"]), 2
        )
        _, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "local-review"), "pass")

    def test_malformed_output_is_an_error_not_a_clean_pass(self):
        rc, out = self.review(FAKE_REVIEW="the owner looked and it is fine")
        self.assertEqual(rc, 2, out)

    def test_unknown_severity_counts_as_high(self):
        bad = json.dumps(
            {
                "summary": "",
                "findings": [
                    {"title": "odd", "severity": "critical", "location": "a:1", "summary": "s"}
                ],
            }
        )
        rc, out = self.review(FAKE_REVIEW=bad)
        self.assertEqual(rc, 1, out)

    def test_lockfile_bodies_are_not_sent(self):
        self.write("pnpm-lock.yaml", "LOCKFILE-BODY-MARKER\n")
        self.commit("chore: lock")
        self.review()
        self.assertNotIn("LOCKFILE-BODY-MARKER", " ".join(c["query"] for c in self.calls()))

    def test_codex_adds_a_second_provider(self):
        codex = self.tmp / "codex"
        codex.write_text(
            "#!/usr/bin/python3\nimport sys\nargs = sys.argv[1:]\nout = args[args.index('-o') + 1]\nsys.stdin.read()\n"
            f"open(out, 'w').write({CLEAN!r})\n"
        )
        codex.chmod(0o755)
        rc, out = self.review(
            PREFLIGHT_CODEX_BIN=str(codex),
            PREFLIGHT_REVIEW_PROVIDERS="claude,openai",
            PREFLIGHT_OPENAI_USE_CODEX="1",
        )
        self.assertEqual(rc, 0, out)
        self.assertIn("two providers", out)
        self.assertIn("openai-redteam", out)
        data = json.loads((self.gd() / "local-review.json").read_text())
        self.assertEqual(len(data["rounds"][0]["reviewers"]), 4)

    def _fake_openai(self, reply_text, status="completed"):
        """A local HTTP server standing in for the Responses API. Records each request body."""
        import http.server
        import threading

        seen = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append({"auth": self.headers.get("Authorization"), "body": body})
                out = json.dumps(
                    {
                        "status": status,
                        "output": [{"content": [{"type": "output_text", "text": reply_text}]}],
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        op = self.tmp / "op"
        op.write_text("#!/bin/sh\necho sk-test-KEY\n")
        op.chmod(0o755)
        return seen, f"http://127.0.0.1:{srv.server_address[1]}/v1/responses", str(op)

    def test_openai_api_is_the_second_provider_with_key_from_the_key_command(self):
        seen, url, op = self._fake_openai(CLEAN)
        rc, out = self.review(
            PREFLIGHT_REVIEW_PROVIDERS="claude,openai",
            PREFLIGHT_OPENAI_KEY_CMD=op,
            PREFLIGHT_OPENAI_URL=url,
        )
        self.assertEqual(rc, 0, out)
        self.assertIn("two providers", out)
        self.assertEqual(len(seen), 2)  # constructive + redteam
        self.assertEqual(seen[0]["auth"], "Bearer sk-test-KEY")
        self.assertEqual(seen[0]["body"]["model"], "gpt-test-1")
        self.assertFalse(seen[0]["body"]["store"])
        self.assertIn("<untrusted_diff>", seen[0]["body"]["input"])
        raw = (self.gd() / "local-review.json").read_text()
        self.assertNotIn("sk-test-KEY", raw)

    def test_openai_high_is_reported(self):
        high = json.dumps(
            {
                "summary": "",
                "findings": [
                    {"title": "fail open", "severity": "high", "location": "a.py:1", "summary": "s"}
                ],
            }
        )
        seen, url, op = self._fake_openai(high)
        rc, out = self.review(
            PREFLIGHT_REVIEW_PROVIDERS="claude,openai",
            PREFLIGHT_OPENAI_KEY_CMD=op,
            PREFLIGHT_OPENAI_URL=url,
        )
        self.assertEqual(rc, 1, out)
        self.assertIn("fail open", out)

    def test_openai_incomplete_is_an_error(self):
        seen, url, op = self._fake_openai("", status="incomplete")
        rc, out = self.review(
            PREFLIGHT_REVIEW_PROVIDERS="claude,openai",
            PREFLIGHT_OPENAI_KEY_CMD=op,
            PREFLIGHT_OPENAI_URL=url,
        )
        self.assertEqual(rc, 2, out)

    def test_no_key_falls_back_to_claude_only(self):
        rc, out = self.review(PREFLIGHT_REVIEW_PROVIDERS="claude,openai")
        self.assertEqual(rc, 0, out)
        self.assertIn("no second provider available locally", out)
        data = json.loads((self.gd() / "local-review.json").read_text())
        self.assertIn("key command", data["rounds"][0]["openai_note"])

    def test_single_provider_is_stated(self):
        rc, out = self.review()
        self.assertIn("no second provider available locally", out)


class DesignCheckTest(ReviewBase):
    def setUp(self):
        super().setUp()
        self.env["PREFLIGHT_LOCAL_REVIEW"] = "off"

    def acting(self, wf_extra="", script="az role assignment delete --ids $id\n"):
        self.write(".github/scripts/cleanup.sh", script)
        self.write(
            ".github/workflows/nightly.yml",
            "on:\n  schedule:\n    - cron: '0 3 * * *'\njobs:\n  j:\n    steps:\n      - run: echo hi\n"
            + wf_extra,
        )
        self.commit("feat(ci): nightly cleanup")

    def answers(self, hdr, n=8, thin=None):
        keys = [
            "fail-closed",
            "main-moves",
            "concurrency",
            "lock-window",
            "audit",
            "kill-switch",
            "dark-launch",
            "abac-actions",
        ]
        lines = [hdr]
        for k in keys[:n]:
            a = (
                "ok"
                if k == thin
                else f"handled in .github/scripts/cleanup.sh:12 and proven by the test in tests/test_cleanup.py:40 ({k})"
            )
            lines.append(f"{k}: {a}")
        return "\n".join(lines) + "\n"

    def test_plain_change_needs_no_design_check(self):
        _, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "design-check"), "pass")

    def test_role_assignment_delete_requires_a_design_check(self):
        self.acting()
        rc, data, out = self.run_pf()
        self.assertEqual(self.status(data, "design-check"), "fail")
        self.assertIn("fail-closed", out)

    def test_complete_design_check_passes_and_thin_answers_fail(self):
        self.acting()
        out = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "design-template",
                "--repo",
                "prod",
                "--worktree",
                str(self.wt),
            ],
            capture_output=True,
            text=True,
            env=self.env,
        ).stdout
        hdr = out.splitlines()[0]
        self.assertTrue(hdr.startswith("design-check: "))
        for k in (
            "fail-closed:",
            "main-moves:",
            "concurrency:",
            "lock-window:",
            "audit:",
            "kill-switch:",
            "dark-launch:",
            "abac-actions:",
        ):
            self.assertIn(k, out)
        path = self.gd() / "design-check.md"
        path.write_text(self.answers(hdr, thin="audit"))
        _, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "design-check"), "fail")
        path.write_text(self.answers(hdr, n=7))
        _, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "design-check"), "fail")
        path.write_text(self.answers(hdr))
        _, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "design-check"), "pass")

    def test_na_needs_a_reason(self):
        self.acting()
        out = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "design-template",
                "--repo",
                "prod",
                "--worktree",
                str(self.wt),
            ],
            capture_output=True,
            text=True,
            env=self.env,
        ).stdout
        hdr = out.splitlines()[0]
        body = self.answers(hdr).replace(
            "lock-window: handled in .github/scripts/cleanup.sh:12 and proven by the test in tests/test_cleanup.py:40 (lock-window)",
            "lock-window: N/A",
        )
        (self.gd() / "design-check.md").write_text(body)
        _, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "design-check"), "fail")
        body = body.replace(
            "lock-window: N/A", "lock-window: N/A: this job never lifts or sets any lock"
        )
        (self.gd() / "design-check.md").write_text(body)
        _, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "design-check"), "pass")

    def test_design_check_goes_stale_when_the_acting_lines_change(self):
        self.acting()
        out = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "design-template",
                "--repo",
                "prod",
                "--worktree",
                str(self.wt),
            ],
            capture_output=True,
            text=True,
            env=self.env,
        ).stdout
        (self.gd() / "design-check.md").write_text(self.answers(out.splitlines()[0]))
        self.write(
            ".github/scripts/cleanup.sh",
            "az role assignment delete --ids $id\naz lock delete --name x\n",
        )
        self.commit("fix(ci): lift lock")
        _, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "design-check"), "fail")

    def test_terraform_apply_triggers_only_in_a_scheduled_workflow(self):
        self.write(
            ".github/workflows/apply.yml",
            "on:\n  push:\n    branches: [main]\njobs:\n  j:\n    steps:\n      - run: terraform apply plan.tfplan\n",
        )
        self.commit("ci: merge driven apply")
        _, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "design-check"), "pass")
        self.write(
            ".github/workflows/sched.yml",
            "on:\n  schedule:\n    - cron: '0 3 * * *'\njobs:\n  j:\n    steps:\n      - run: terraform apply plan.tfplan\n",
        )
        self.commit("ci: scheduled apply")
        _, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "design-check"), "fail")

    def test_scheduled_write_identity_with_an_acting_verb_triggers(self):
        self.write(
            ".github/workflows/sched2.yml",
            "on:\n  schedule:\n    - cron: '0 3 * * *'\npermissions:\n  id-token: write\njobs:\n  j:\n    steps:\n      - run: tf-apply-roots.sh\n",
        )
        self.commit("ci: scheduled roots")
        _, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "design-check"), "fail")

    def test_docs_tests_and_comments_do_not_trigger(self):
        self.write("docs/runbook.md", "run az role assignment delete by hand\n")
        self.write("apps/demo/tests/test_x.py", "CMD = 'az lock delete --name x'\n")
        self.write("apps/demo/server/note.sh", "# az role assignment delete is documented here\n")
        self.commit("docs: notes")
        _, data, _ = self.run_pf()
        self.assertEqual(self.status(data, "design-check"), "pass")

    def test_lock_and_roleassignments_delete_patterns(self):
        for i, line in enumerate(
            (
                "az lock delete --ids $x",
                "POST roleAssignments/delete",
                "Remove-AzRoleAssignment -ObjectId $o",
            )
        ):
            self.write(f"scripts/act{i}.sh", line + "\n")
            self.commit(f"chore: act {i}")
            _, data, _ = self.run_pf()
            self.assertEqual(self.status(data, "design-check"), "fail", line)
            self.git("reset", "-q", "--hard", "HEAD~1")


class CiPytestCmdTest(unittest.TestCase):
    """the .github/scripts pytest gate runs on CI's Python through uv."""

    def setUp(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("pf_imp209", str(SCRIPT))
        self.pf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.pf)
        self.wt = Path(tempfile.mkdtemp(dir=os.environ.get("TMPDIR")))
        self.uv = self.wt / "uv"
        self.uv.write_text("")
        self.old = dict(os.environ)
        os.environ["PREFLIGHT_UV_BIN"] = str(self.uv)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old)

    def test_uses_uv_python_312_and_requirements(self):
        (self.wt / ".github" / "scripts").mkdir(parents=True)
        (self.wt / ".github" / "scripts" / "requirements.txt").write_text("pytest\n")
        cmd = self.pf.ci_pytest_cmd(self.wt)
        self.assertEqual(
            cmd[:6], [str(self.uv), "run", "--quiet", "--no-project", "--python", "3.12"]
        )
        self.assertIn("--with-requirements", cmd)
        self.assertEqual(cmd[-3:], ["pytest", "-q", ".github/scripts/tests"])

    def test_no_requirements_file_still_runs(self):
        cmd = self.pf.ci_pytest_cmd(self.wt)
        self.assertNotIn("--with-requirements", cmd)
        self.assertIn("pytest", cmd)

    def test_python_override(self):
        os.environ["PREFLIGHT_CI_PYTHON"] = "3.13"
        self.assertEqual(self.pf.ci_pytest_cmd(self.wt)[5], "3.13")

    def test_missing_uv_falls_back_to_current_python(self):
        os.environ["PREFLIGHT_UV_BIN"] = str(self.wt / "nope")
        self.pf.shutil.which = lambda name: None
        self.pf.HOME = self.wt
        self.assertEqual(self.pf.ci_pytest_cmd(self.wt)[0], sys.executable)


if __name__ == "__main__":
    unittest.main(verbosity=1)
