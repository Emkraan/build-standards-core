"""Tests for templates/overlay/scripts/core-ci.py, core-status.py (overlay-ci results, proofs, Stacks
row) and merge-pr.py (post-merge local step). Fixture repos live under .test-work, never /tmp."""

import datetime
import json
import os
import random
import shutil
import string
import sys
import unittest
from unittest import mock

from support import ROOT, Work, load, sh

SCRIPTS = ROOT / "templates" / "overlay" / "scripts"
WORD = "Cla" + "ude"  # assembled, so this file never names the tool whole


def git(repo, *args, env=None):
    e = dict(
        os.environ,
        GIT_AUTHOR_NAME="T",
        GIT_COMMITTER_NAME="T",
        GIT_AUTHOR_EMAIL="1+t@users.noreply.github.com",
        GIT_COMMITTER_EMAIL="1+t@users.noreply.github.com",
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_NOSYSTEM="1",
    )
    e.update(env or {})
    import subprocess

    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env=e)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class Overlay(Work):
    """A repo whose root is the overlay, with core-ci.py and a parameters sheet."""

    def setUp(self):
        super().setUp()
        self.repo = self.dir / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        (self.repo / "standards-local").mkdir()
        for name in ("core-ci.py", "core-status.py", "corehash.py", "check-exceptions.py"):
            shutil.copyfile(SCRIPTS / name, self.repo / "scripts" / name)
        git(self.repo, "init", "-q", "-b", "main")
        self.params("")
        self.commit("chore: start", {"README.md": "x\n"})
        self.base = git(self.repo, "rev-parse", "HEAD")

    def params(self, stacks, extra=""):
        (self.repo / "standards-local" / "parameters.md").write_text(
            "| Parameter | Value | Used by |\n|---|---|---|\n"
            f"| Stacks this overlay has | {stacks} | x |\n{extra}"
        )

    def commit(self, msg, files, env=None):
        for k, v in files.items():
            p = self.repo / k
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(v if isinstance(v, bytes) else v.encode("utf8"))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", msg, env=env)
        return git(self.repo, "rev-parse", "HEAD")

    def ci(self, *args, env=None):
        old = dict(os.environ)
        os.environ.update(env or {})
        try:
            return sh(
                [sys.executable, self.repo / "scripts" / "core-ci.py", *args],
                cwd=self.repo,
                timeout=300,
            )
        finally:
            os.environ.clear()
            os.environ.update(old)


class PrHygiene(Overlay):
    def test_pr_title(self):
        self.assertEqual(self.ci("pr-title", "feat(ui): add a thing")[0], 0)
        self.assertEqual(self.ci("pr-title", "fix!: drop the old flag")[0], 0)
        self.assertEqual(self.ci("pr-title", "Add a thing")[0], 1)
        self.assertEqual(self.ci("pr-title", "feature: add")[0], 1)

    def test_commitlint(self):
        head = self.commit("feat: one", {"a": "1"})
        self.assertEqual(self.ci("commitlint", self.base, head)[0], 0)
        head = self.commit("wip stuff", {"a": "2"})
        rc, out = self.ci("commitlint", self.base, head)
        self.assertEqual(rc, 1)
        self.assertIn("1 bad subject", out)

    def test_attribution_commit_title_body(self):
        head = self.commit("feat: one", {"a": "1"})
        self.assertEqual(
            self.ci(
                "attribution",
                self.base,
                head,
                env={"PR_TITLE": "feat: one", "PR_BODY": f"See {WORD.upper()}.md"},
            )[0],
            0,
        )
        rc, out = self.ci(
            "attribution", self.base, head, env={"PR_BODY": f"Written with {WORD} help"}
        )
        self.assertEqual(rc, 1)
        self.assertIn("PR body: assistant or tool name", out)
        self.assertNotIn(WORD, out)
        head = self.commit("fix: two\n\nCo-authored-by: Bot <x@example.com>", {"a": "2"})
        rc, out = self.ci("attribution", self.base, head)
        self.assertEqual(rc, 1)
        self.assertIn("Co-authored-by trailer", out)

    def test_attribution_hashed_private_terms(self):
        import hashlib

        (self.repo / "standards-local" / "denylist.sha256").write_text(
            hashlib.sha256(b"zebra corp").hexdigest() + "\n"
        )
        head = self.commit("feat: add", {"notes.md": "made for Zebra Corp\n"})
        rc, out = self.ci("attribution", self.base, head)
        self.assertEqual(rc, 1)
        self.assertIn("notes.md line 1: private term", out)
        self.assertNotIn("Zebra", out)

    def test_identity(self):
        head = self.commit("feat: ok", {"a": "1"})
        self.assertEqual(self.ci("identity", self.base, head)[0], 0)
        head = self.commit("feat: bad", {"a": "2"}, env={"GIT_AUTHOR_EMAIL": "me@corp.invalid"})
        rc, out = self.ci("identity", self.base, head)
        self.assertEqual(rc, 1)
        self.assertIn("author email on corp.invalid", out)
        self.params("", "| Commit emails the identity check allows | *@corp.invalid | x |\n")
        self.assertEqual(self.ci("identity", self.base, head)[0], 0)


class Changelog(Overlay):
    def test_bump_needs_heading(self):
        b = self.commit(
            "chore: v1", {"package.json": '{"version": "1.0.0"}', "CHANGELOG.md": "# C\n"}
        )
        head = self.commit("feat: v1.1", {"package.json": '{"version": "1.1.0"}'})
        rc, out = self.ci("changelog", b, head)
        self.assertEqual(rc, 1)
        self.assertIn("moved to 1.1.0", out)
        head = self.commit(
            "docs: entry", {"CHANGELOG.md": "# C\n\n## 2026-10-20 (v1.1.0, a thing)\n"}
        )
        self.assertEqual(self.ci("changelog", b, head)[0], 0)

    def test_no_bump_passes_and_pyproject(self):
        b = self.commit("chore: py", {"pyproject.toml": '[project]\nversion = "0.1.0"\n'})
        head = self.commit("fix: x", {"x.py": "x = 1\n"})
        self.assertEqual(self.ci("changelog", b, head)[0], 0)
        head = self.commit("feat: y", {"pyproject.toml": '[project]\nversion = "0.2.0"\n'})
        self.assertEqual(self.ci("changelog", b, head)[0], 1)


class WorkflowLint(Overlay):
    def test_templates_are_clean(self):
        rc, out = sh(
            [
                sys.executable,
                SCRIPTS / "core-ci.py",
                "workflow-lint",
                ROOT / "templates/overlay/.github/workflows",
                ROOT / ".github/workflows/checks.yml",
            ]
        )
        self.assertEqual(rc, 0, out)

    def test_findings(self):
        wf = self.repo / ".github" / "workflows" / "x.yml"
        wf.parent.mkdir(parents=True)
        wf.write_text(
            "on: push\njobs:\n  a:\n    container:\n      image: node:22\n    steps:\n"
            "      - uses: actions/checkout@v7\n"
            "      - uses: actions/setup-node@" + "a" * 40 + "\n"
            "      - run: pnpm install\n"
        )
        rc, out = self.ci("workflow-lint")
        self.assertEqual(rc, 1)
        for kind in (
            "no top-level permissions",
            "not pinned by a full commit sha",
            "no version comment",
            "image not pinned by digest",
            "without --frozen-lockfile",
        ):
            self.assertIn(kind, out)

    def test_every_core_workflow_is_valid_yaml_plain_scalars(self):
        mod = load("core_ci_yaml", "templates/overlay/scripts/core-ci.py")
        for path in sorted((ROOT / ".github/workflows").glob("*.yml")) + sorted(
            (ROOT / "templates/overlay/.github/workflows").glob("*.yml")
        ):
            self.assertEqual(mod.yaml_colon_scalars(path.read_text(encoding="utf8")), [], path.name)

    def test_unquoted_colon_space_value_is_found(self):
        mod = load("core_ci_yaml2", "templates/overlay/scripts/core-ci.py")
        text = (
            "on:\n  workflow_dispatch:\n    inputs:\n      sha:\n"
            "        description: Commit to release (default: the head)\n"
            "        required: false\n"
        )
        self.assertEqual(mod.yaml_colon_scalars(text), [5])

    def test_setup_python_on_ubuntu_latest_is_found(self):
        mod = load("core_ci_py", "templates/overlay/scripts/core-ci.py")
        wf = self.repo / ".github" / "workflows" / "y.yml"
        wf.parent.mkdir(parents=True)
        wf.write_text(
            "permissions:\n  contents: read\non: push\njobs:\n  a:\n"
            "    runs-on: ubuntu-latest\n    steps:\n"
            "      - uses: actions/setup-python@" + "a" * 40 + " # v7\n        with:\n"
            "          python-version: '3.9'\n"
        )
        kinds = [k for _, k in mod.lint_workflow(wf)]
        self.assertTrue(any("pin ubuntu-24.04" in k for k in kinds), kinds)
        wf.write_text(wf.read_text().replace("ubuntu-latest", "ubuntu-24.04"))
        self.assertFalse(any("pin ubuntu-24.04" in k for _, k in mod.lint_workflow(wf)))

    def test_quoted_block_and_comment_values_are_not_flagged(self):
        mod = load("core_ci_yaml3", "templates/overlay/scripts/core-ci.py")
        text = (
            "jobs:\n  a:\n    steps:\n"
            "      - name: 'quoted (default: ok)'\n"
            '      - name: "also quoted: fine"\n'
            "      - run: |\n          echo a: b\n          echo c: d\n"
            "      - uses: x/y@abc # v1: note\n"
            "    if: ${{ github.event_name == 'push' }}\n"
            "    # a comment with: a colon\n"
            "    url: https://example.com/a:80\n"
        )
        self.assertEqual(mod.yaml_colon_scalars(text), [])


class AsciiNodePython(Overlay):
    def test_ascii(self):
        self.commit("feat: ps", {"a.ps1": 'Write-Host "ok"\n', "b.md": "plain\n"})
        self.assertEqual(self.ci("ascii")[0], 0)
        self.commit("feat: ps", {"c.ps1": 'Write-Host "caf\xe9"\n'})
        rc, out = self.ci("ascii")
        self.assertEqual(rc, 1)
        self.assertIn("c.ps1", out)

    def test_ascii_every_text_file_by_default(self):
        self.commit(
            "feat: skip",
            {
                "img.bin": b"\x89PNG\x00\xff\xfe",
                "package-lock.json": '{"x": "caf\xe9"}\n',
                "kit-core/a.ts": "// caf\xe9\n",
                "ok.md": "plain\n",
            },
        )
        rc, out = self.ci("ascii")
        self.assertEqual(rc, 0, out)
        self.commit("docs: md", {"docs/old/b.md": "caf\xe9\n"})
        rc, out = self.ci("ascii")
        self.assertEqual(rc, 1)
        self.assertIn("docs/old/b.md", out)
        self.params("", "| ASCII check patterns | *.ps1 | x |\n")
        rc, out = self.ci("ascii")
        self.assertEqual(rc, 0)
        self.assertIn("narrowed", out)

    def test_ascii_exception_covers_a_path_not_a_script(self):
        shutil.copyfile(
            SCRIPTS / "check-exceptions.py", self.repo / "scripts" / "check-exceptions.py"
        )
        (self.repo / "standards-core").mkdir(exist_ok=True)
        (self.repo / "standards-core" / "pr-review-and-merge.md").write_text("## 1. Rules\n")
        day = datetime.date.today()
        (self.repo / "standards-local" / "exceptions.md").write_text(
            "| ID | Rule | Scope | Deviation | Reason | Owner | Approved | Review by |\n|---|---|---|---|---|---|---|---|\n"
            f"| EXC-001 | pr-review-and-merge.md 1.19 | docs/old | quotes | imported | o | {day} | {day + datetime.timedelta(days=30)} |\n"
        )
        self.commit("docs: md", {"docs/old/b.md": "caf\xe9\n"})
        rc, out = self.ci("ascii")
        self.assertEqual(rc, 0, out)
        self.assertIn("excepted by EXC-001", out)
        self.commit("feat: ps", {"docs/old/c.ps1": "# caf\xe9\n"})
        self.assertEqual(self.ci("ascii")[0], 1)

    def test_node_pin(self):
        self.commit("feat: n", {".nvmrc": "22\n", "package.json": '{"engines": {"node": ">=22"}}'})
        self.assertEqual(self.ci("node-pin")[0], 0)
        self.commit(
            "feat: n",
            {
                ".github/workflows/a.yml": "jobs:\n  a:\n    steps:\n      - with:\n          node-version: 20\n"
            },
        )
        self.assertEqual(self.ci("node-pin")[0], 1)

    def test_python_config_and_params(self):
        self.assertEqual(self.ci("python-config")[0], 1)
        self.commit("chore: ruff", {"pyproject.toml": '[tool.ruff]\ntarget-version = "py39"\n'})
        self.assertEqual(self.ci("python-config")[0], 0)
        self.params("python", "| Python interpreter floor | 3.11 | x |\n")
        self.assertEqual(self.ci("python-config")[0], 1)
        rc, out = self.ci("params")
        self.assertIn("python=true", out)
        self.assertIn("python_floor=3.11", out)
        self.assertIn("powershell=false", out)

    def test_params_node_major(self):
        rc, out = self.ci("params")
        self.assertIn("node=\n", out + "\n")
        self.commit("chore: pin", {"package.json": '{"engines": {"node": ">=22"}}\n'})
        self.assertIn("node=22", self.ci("params")[1])
        self.commit("chore: pin", {".nvmrc": "24.1.0\n"})
        self.assertIn("node=24", self.ci("params")[1])
        self.params("web", "| Node major version | 20 | x |\n")
        self.assertIn("node=20", self.ci("params")[1])

    def test_python_config_monorepo(self):
        self.params("python", "| Python interpreter floor | 3.12 | x |\n")
        self.commit(
            "chore: ruff",
            {
                "apps/a/pyproject.toml": '[tool.ruff]\ntarget-version = "py312"\n',
                "apps/b/ruff.toml": 'target-version = "py312"\n',
            },
        )
        self.assertEqual(self.ci("python-config")[0], 0)
        self.commit(
            "chore: ruff", {"apps/c/pyproject.toml": '[tool.ruff]\ntarget-version = "py314"\n'}
        )
        rc, out = self.ci("python-config")
        self.assertEqual(rc, 1)
        self.assertIn("apps/c/pyproject.toml", out)

    def test_python_config_skips_synced_fixtures(self):
        self.params("python", "| Python interpreter floor | 3.12 | x |\n")
        self.commit(
            "chore: ruff",
            {
                "pyproject.toml": '[tool.ruff]\ntarget-version = "py312"\n',
                "lint-core/script-fixtures/ruff.toml": 'target-version = "py39"\n',
            },
        )
        self.assertEqual(self.ci("python-config")[0], 0)

    def test_ruff_requirement_is_hash_pinned(self):
        rc, out = self.ci("ruff-requirements")
        self.assertRegex(out, r"^ruff==\d+\.\d+\.\d+ (--hash=sha256:[0-9a-f]{64} ?)+$")


@unittest.skipUnless(
    shutil.which("gitleaks") or os.environ.get("GITLEAKS"), "gitleaks not installed"
)
class KitPeers(Overlay):
    def kit(self, extra=None):
        files = {
            "kit-core/index.ts": "export { useChartTheme } from './charts/chartTheme';\n",
            "kit-core/charts/chartTheme.ts": "export const useChartTheme = 1;\n",
            "kit-core/charts/Charts.tsx": "import { Area } from 'recharts';\nexport { Area };\n",
            "kit-core/graph/index.ts": "export * from '@xyflow/react';\n",
            "kit-core/api-reference/index.ts": "export * from '@scalar/api-reference-react';\n",
        }
        files.update(extra or {})
        self.commit("feat: kit", files)

    def test_root_reaching_a_peer_fails(self):
        self.kit()
        self.assertEqual(self.ci("kit-peers")[0], 0)
        self.commit(
            "feat: bad",
            {
                "kit-core/charts/chartTheme.ts": "import 'recharts';\nexport const useChartTheme = 1;\n"
            },
        )
        rc, out = self.ci("kit-peers")
        self.assertEqual(rc, 1)
        self.assertIn("optional peer recharts", out)

    def test_tsconfig_must_exclude_entries_without_peers(self):
        self.kit(
            {
                "app/package.json": '{"dependencies": {"recharts": "3"}}',
                "app/tsconfig.json": '{\n  // app\n  "include": ["src", "../kit-core"],\n'
                '  "exclude": ["../kit-core/graph"],\n}\n',
            }
        )
        rc, out = self.ci("kit-peers")
        self.assertEqual(rc, 1)
        self.assertIn("api-reference", out)
        self.assertNotIn("the charts peer", out)
        self.assertNotIn("the graph peer", out)
        self.commit(
            "fix: x",
            {
                "app/tsconfig.json": '{"include": ["src", "../kit-core/**"], '
                '"exclude": ["../kit-core/graph", "../kit-core/api-reference/**"]}'
            },
        )
        self.assertEqual(self.ci("kit-peers")[0], 0)


class RequiredChecks(Overlay):
    def setUp(self):
        super().setUp()
        wf = self.repo / ".github" / "workflows"
        wf.mkdir(parents=True)
        shutil.copyfile(
            ROOT / "templates/overlay/.github/workflows/core-ci.yml", wf / "core-ci.yml"
        )
        self.mod = load("core_ci_rc", "templates/overlay/scripts/core-ci.py")
        self.jobs = self.mod.core_ci_jobs(self.repo)

    def api(self, data):
        f = self.dir / "api.json"
        f.write_text(json.dumps(data))
        return f

    def test_missing_and_fix(self):
        self.assertNotIn("core-setup", self.jobs)
        f = self.api(
            {
                "protection": {
                    "contexts": ["core-ascii"],
                    "checks": [{"context": "core-pr-title"}],
                },
                "rules": [],
            }
        )
        rc, out = self.ci("required-checks", "--api-json", f, "--fix")
        self.assertEqual(rc, 1)
        self.assertEqual(self.jobs, ["core-checks"])
        self.assertIn("does not require: core-checks", out)
        self.assertIn("no longer exist: core-ascii, core-pr-title", out)
        self.assertIn("-X DELETE", out)
        self.assertIn("protection/required_status_checks/contexts", out)
        self.assertIn("rulesets --input", out)
        rules = [
            {
                "type": "required_status_checks",
                "parameters": {"required_status_checks": [{"context": j} for j in self.jobs]},
            }
        ]
        self.assertEqual(
            self.ci(
                "required-checks", "--api-json", self.api({"protection": None, "rules": rules})
            )[0],
            0,
        )

    def test_merge_gate_workflow_list_counts(self):
        (self.repo / ".github" / "workflows" / "automerge.yml").write_text(
            "env:\n  REQUIRED_CHECKS: >-\n    " + " ".join(self.jobs) + "\njobs: {}\n"
        )
        self.assertEqual(
            self.ci("required-checks", "--api-json", self.api({"protection": None, "rules": []}))[
                0
            ],
            0,
        )

    def test_core_status_reports_missing_jobs(self):
        (self.repo / "standards-core").mkdir()
        (self.repo / "standards-core" / "rules.json").write_text('{"rules": []}')
        (self.repo / "standards.lock").write_text("ref=v0.0.0\ncommit=abc\n")
        f = self.api({"protection": None, "rules": []})
        rc, out = sh(
            [
                sys.executable,
                self.repo / "scripts" / "core-status.py",
                "--json",
                "--required-json",
                f,
            ],
            cwd=self.repo,
        )
        rep = json.loads(out[out.index("{") :])
        self.assertTrue(
            any("merge gate does not require" in p and "core-checks" in p for p in rep["problems"]),
            rep["problems"],
        )

    def test_verdict_and_wait(self):
        v = self.mod.checks_verdict
        self.assertEqual(v([], [], [])[0], "wait")
        self.assertEqual(v([("a", "in_progress", None)], [], [])[0], "wait")
        self.assertEqual(v([("a", "completed", "failure")], [], [])[0], "fail")
        self.assertEqual(v([("a", "completed", "success")], [("s", "error")], [])[0], "fail")
        self.assertEqual(v([("a", "completed", "success")], [], ["b"])[0], "wait")
        self.assertEqual(
            v([("a", "completed", "success"), ("b", "completed", "skipped")], [], ["b"])[0], "green"
        )
        reads = iter(
            [
                ([], []),
                ([("a", "completed", "success")], []),
                ([("a", "completed", "success"), ("late", "queued", None)], []),
                ([("a", "completed", "success"), ("late", "completed", "success")], []),
                ([("a", "completed", "success"), ("late", "completed", "success")], []),
            ]
        )
        now = [0.0]
        rc = self.mod.wait_loop(
            lambda: next(reads),
            [],
            600,
            1,
            2,
            sleep=lambda s: now.__setitem__(0, now[0] + s),
            clock=lambda: now[0],
        )
        self.assertEqual(rc, 0)
        self.assertEqual(now[0], 4)
        rc = self.mod.wait_loop(
            lambda: ([("a", "queued", None)], []),
            [],
            3,
            1,
            2,
            sleep=lambda s: now.__setitem__(0, now[0] + s),
            clock=lambda: now[0],
        )
        self.assertEqual(rc, 1)
        reads = iter([([("a", "completed", "success")], []), ([("a", "completed", "failure")], [])])
        self.assertEqual(
            self.mod.wait_loop(lambda: next(reads), [], 600, 1, 2, sleep=lambda s: None), 1
        )

    def test_update_workflow_never_auto_merges(self):
        text = (ROOT / "templates/overlay/.github/workflows/core-update.yml").read_text()
        code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
        self.assertNotIn("--auto", code)
        self.assertLess(text.index("wait-checks"), text.index("merge-pr.py"))


class SecretScan(Overlay):
    def token(self):
        rnd = random.Random(7)
        return "ghp_" + "".join(rnd.choice(string.ascii_letters + string.digits) for _ in range(36))

    def test_planted_secret_fails_and_allow_paths_are_off(self):
        clean = self.commit("feat: clean", {"a.txt": "nothing here\n"})
        self.assertEqual(self.ci("secret-scan", self.base, clean)[0], 0)
        # The PR adds its own ignore file, an allow comment and a config that allowlists everything:
        # none of them may hide the planted secret.
        tok = self.token()
        head = self.commit(
            "feat: leak",
            {
                "leak.txt": f'token = "{tok}" # gitleaks:allow\n',
                ".gitleaksignore": "leak.txt\n",
                ".gitleaks.toml": "[[allowlists]]\npaths = ['''.*''']\n",
            },
        )
        rc, out = self.ci("secret-scan", clean, head)
        self.assertEqual(rc, 1, out)
        self.assertNotIn(tok, out)


@unittest.skipUnless(shutil.which("pwsh"), "pwsh not installed")
class PowerShell(Overlay):
    def test_parse_error_fails(self):
        self.commit("feat: ps", {"ok.ps1": "Write-Output 1\n"})
        self.assertEqual(self.ci("powershell")[0], 0)
        self.commit("feat: ps", {"bad.ps1": "function f {\n"})
        rc, out = self.ci("powershell")
        self.assertEqual(rc, 1)
        self.assertIn("bad.ps1", out)


class CoreStatus(Overlay):
    def setUp(self):
        super().setUp()
        (self.repo / "standards-core").mkdir()
        rules = [
            {
                "id": "a.1",
                "ref": "a.md 1",
                "title": "T1",
                "statement": "s",
                "level": "must",
                "applies_to": ["all"],
                "check": {
                    "kind": "overlay-ci",
                    "workflow": "core-ci.yml",
                    "jobs": ["core-pr-title"],
                },
                "acceptance": "x",
            },
            {
                "id": "a.2",
                "ref": "a.md 2",
                "title": "T2",
                "statement": "s",
                "level": "must",
                "applies_to": ["all"],
                "check": {"kind": "review"},
                "acceptance": "x",
            },
            {
                "id": "a.3",
                "ref": "a.md 3",
                "title": "T3",
                "statement": "s",
                "level": "must",
                "applies_to": ["all"],
                "check": {"kind": "test"},
                "acceptance": "x",
            },
        ]
        (self.repo / "standards-core" / "rules.json").write_text(json.dumps({"rules": rules}))
        (self.repo / "standards.lock").write_text("ref=v0.0.0\ncommit=abc\n")

    def status(self, *args):
        rc, out = sh(
            [sys.executable, self.repo / "scripts" / "core-status.py", "--json", *args],
            cwd=self.repo,
        )
        return rc, json.loads(out[out.index("{") :])

    def by_id(self, rep):
        return {r["id"]: r for r in rep["rules"]}

    def test_overlay_ci_needs_installed_workflow_then_reads_results(self):
        _, rep = self.status()
        self.assertEqual(self.by_id(rep)["a.1"]["status"], "fail")
        wf = self.repo / ".github" / "workflows"
        wf.mkdir(parents=True)
        shutil.copyfile(
            ROOT / "templates/overlay/.github/workflows/core-ci.yml", wf / "core-ci.yml"
        )
        self.assertEqual(self.by_id(self.status()[1])["a.1"]["status"], "unverified")
        res = self.dir / "res.json"
        for conclusion, want in (
            ("success", "pass"),
            ("failure", "fail"),
            ("skipped", "unverified"),
        ):
            res.write_text(json.dumps({"core-ci.yml": {"core-pr-title": conclusion}}))
            self.assertEqual(
                self.by_id(self.status("--ci-results", res)[1])["a.1"]["status"], want, conclusion
            )

    def test_kit_core_ci_rule_is_not_applicable_without_ui_adoption(self):
        rules = json.loads((self.repo / "standards-core" / "rules.json").read_text())["rules"]
        rules.append(
            {
                "id": "a.9",
                "ref": "a.md 9",
                "title": "T9",
                "statement": "s",
                "level": "must",
                "applies_to": ["all"],
                "check": {"kind": "core-ci", "command": "x", "requires": "ui-adoption"},
                "acceptance": "x",
            }
        )
        (self.repo / "standards-core" / "rules.json").write_text(json.dumps({"rules": rules}))
        rc, rep = self.status()
        self.assertEqual(self.by_id(rep)["a.9"]["status"], "not_applicable")
        self.assertEqual(rep["summary"]["not_applicable"], 1)

    def test_proofs(self):
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "t.py").write_text("")
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "review.md").write_text("reviewed\n")
        today = datetime.date.today().isoformat()
        proofs = {
            "a.2": {
                "kind": "review",
                "ref": "docs/review.md",
                "date": today,
                "reviewed_by": "owner",
            },
            "a.3": {"kind": "test", "ref": "tests/t.py"},
        }
        (self.repo / "standards-local" / "proofs.json").write_text(json.dumps(proofs))
        _, rep = self.status()
        ids = self.by_id(rep)
        self.assertEqual(ids["a.2"]["status"], "attested")
        self.assertEqual(ids["a.3"]["status"], "proved")
        self.assertEqual((rep["summary"]["proved"], rep["summary"]["attested"]), (1, 1))
        self.assertEqual(rep["summary"]["pass"], 0)
        old = (datetime.date.today() - datetime.timedelta(days=400)).isoformat()
        proofs = {
            "a.2": {"kind": "review", "ref": "docs/review.md", "date": old},
            "a.3": {"kind": "review", "ref": "docs/review.md", "date": today},
            "a.1": {"kind": "ci", "ref": "core-ci.yml#nope"},
            "zz.9": {"kind": "test", "ref": "tests/t.py"},
            "a.9": {"kind": "test", "ref": "tests/missing.py"},
        }
        (self.repo / "standards-local" / "proofs.json").write_text(json.dumps(proofs))
        _, rep = self.status()
        ids = self.by_id(rep)
        self.assertEqual(ids["a.2"]["status"], "unverified")
        self.assertEqual(ids["a.3"]["status"], "unverified")
        text = "\n".join(rep["problems"])
        for want in (
            "days old",
            "weaker than",
            "core-ci.yml#nope not found",
            "zz.9: no such rule",
            "a.9: no such rule",
        ):
            self.assertIn(want, text)

    def test_waiver_needs_a_reason_a_record_and_a_date_and_never_counts_as_proof(self):
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "waiver.md").write_text("not applicable here\n")
        today = datetime.date.today().isoformat()
        good = {
            "kind": "waiver",
            "ref": "docs/waiver.md",
            "date": today,
            "reason": "no database in this repo",
            "reviewed_by": "owner",
        }
        write = lambda d: (self.repo / "standards-local" / "proofs.json").write_text(json.dumps(d))  # noqa: E731
        write({"a.3": good})
        _, rep = self.status()
        self.assertEqual(self.by_id(rep)["a.3"]["status"], "waived")
        self.assertEqual((rep["summary"]["waived"], rep["summary"]["proved"]), (1, 0))
        for bad, want in (
            (dict(good, reason=""), "needs a reason"),
            (dict(good, date="2020-01-01"), "days old"),
            (dict(good, ref="docs/none.md"), "does not exist"),
        ):
            write({"a.3": bad})
            _, rep = self.status()
            self.assertEqual(self.by_id(rep)["a.3"]["status"], "unverified", want)
            self.assertIn(want, "\n".join(rep["problems"]))

    def test_test_proof_without_the_rule_tag_warns_and_a_tagged_one_does_not(self):
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "t.py").write_text("# nothing\n")
        (self.repo / "tests" / "u.py").write_text("# core-rule: a.3\n")
        proofs = {"a.3": {"kind": "test", "ref": "tests/t.py"}}
        (self.repo / "standards-local" / "proofs.json").write_text(json.dumps(proofs))
        _, rep = self.status()
        self.assertEqual(self.by_id(rep)["a.3"]["status"], "proved")
        self.assertIn("core-rule: a.3", "\n".join(rep["warnings"]))
        proofs["a.3"]["ref"] = "tests/u.py"
        (self.repo / "standards-local" / "proofs.json").write_text(json.dumps(proofs))
        _, rep = self.status()
        self.assertEqual(rep["warnings"], [])

    def test_missing_stacks_row_is_a_problem(self):
        (self.repo / "standards-local" / "parameters.md").write_text(
            "| Parameter | Value |\n|---|---|\n"
        )
        rc, rep = self.status("--require-lint-config")
        self.assertEqual(rc, 1)
        self.assertTrue(any("no Stacks row" in p for p in rep["problems"]))
        self.params("")
        rc, rep = self.status("--require-lint-config")
        self.assertEqual(rc, 0)
        self.assertFalse(any("no Stacks row" in p for p in rep["problems"]))


class MergePr(Work):
    """merge-pr.py never reports refusal after the merge landed, and its local step is safe anywhere."""

    def setUp(self):
        super().setUp()
        self.mod = load("merge_pr_t", "templates/overlay/scripts/merge-pr.py")

    def fake_gh(
        self, merge_rc, state="MERGED", calls=None, merges=None, head="a" * 40, rebase=False
    ):
        """merges, when given, is a list of (rc, stderr) answers for successive merge calls."""
        queue = list(merges or [])

        def gh(*args):
            if calls is not None:
                calls.append(args)
            if args[:2] == ("api", "user"):
                return 0, "1\tt", ""
            if args[:2] == ("pr", "view") and any(
                str(a).startswith("number,title,body,headRefName") for a in args
            ):
                return (
                    0,
                    json.dumps(
                        {
                            "number": 7,
                            "title": "t",
                            "body": "",
                            "headRefName": "feat/x",
                            "headRefOid": "a" * 40,
                            "baseRefName": "main",
                            "isCrossRepository": False,
                            "author": {"login": "t"},
                        }
                    ),
                    "",
                )
            if args[:2] == ("pr", "merge"):
                if queue:
                    rc, err = queue.pop(0) if len(queue) > 1 else queue[0]
                    return rc, "", err
                return (
                    merge_rc,
                    "",
                    "failed to run git: fatal: 'main' is already checked out at '/x'",
                )
            if args[:2] == ("pr", "view") and "state,headRefOid" in args:
                return 0, json.dumps({"state": state, "headRefOid": head}), ""
            if args[:2] == ("pr", "view") and "mergeCommit" in args:
                return 0, "f" * 40, ""
            if args[:2] == ("api", "-X"):
                return 0, "", ""
            if args[0] == "api" and rebase and ".allow_rebase_merge" in args:
                return 0, "true", ""
            if args[0] == "api":
                return 0, "1+t@users.noreply.github.com\t2+t@users.noreply.github.com", ""
            return 1, "", "unexpected"

        return gh

    def run_main(self, gh, cwd, extra=()):
        out, err = [], []
        old = os.getcwd()
        os.chdir(cwd)
        try:
            with (
                mock.patch.object(self.mod, "gh", gh),
                mock.patch.object(sys, "argv", ["merge-pr.py", "7", "-R", "o/r", *extra]),
                mock.patch(
                    "builtins.print",
                    lambda *a, **k: (err if k.get("file") else out).append(" ".join(map(str, a))),
                ),
            ):
                rc = self.mod.main()
        finally:
            os.chdir(old)
        return rc, "\n".join(out), "\n".join(err)

    def repo_with_branch(self):
        repo = self.dir / "r"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        (repo / "a").write_text("1")
        git(repo, "add", "a")
        git(repo, "commit", "-q", "-m", "chore: a")
        git(repo, "branch", "feat/x")
        return repo

    def test_no_delete_branch_flag_and_detached_head(self):
        repo = self.repo_with_branch()
        git(repo, "checkout", "-q", "--detach")
        calls = []
        rc, out, err = self.run_main(self.fake_gh(0, calls=calls), repo)
        self.assertEqual(rc, 0, err)
        merge = [c for c in calls if c[:2] == ("pr", "merge")][0]
        self.assertNotIn("--delete-branch", merge)
        self.assertIn("local branch: deleted feat/x", out)
        self.assertNotIn("refused", err)

    def test_gh_error_after_merge_is_not_refusal(self):
        repo = self.repo_with_branch()
        rc, out, err = self.run_main(self.fake_gh(1), repo)
        self.assertEqual(rc, 0)
        self.assertNotIn("refused", err)
        self.assertIn("the PR is merged", err)

    def test_real_refusal(self):
        rc, _, err = self.run_main(self.fake_gh(1, state="OPEN"), self.dir)
        self.assertEqual(rc, 2)
        self.assertIn("merge refused", err)

    def test_branch_checked_out_in_another_worktree_is_left(self):
        repo = self.repo_with_branch()
        git(repo, "worktree", "add", "-q", str(self.dir / "wt"), "feat/x")
        rc, out, _ = self.run_main(self.fake_gh(0), repo)
        self.assertEqual(rc, 0)
        self.assertIn("checked out in a worktree, left in place", out)

    def test_outside_a_checkout(self):
        rc, out, _ = self.run_main(self.fake_gh(0), self.dir)
        self.assertEqual(rc, 0)
        self.assertIn("local branch:", out)

    def merge_calls(self, calls):
        return [c for c in calls if c[:2] == ("pr", "merge")]

    def run_retry(self, repo, calls, **kw):
        with mock.patch.object(self.mod, "MERGE_PAUSE", 0):
            return self.run_main(self.fake_gh(1, calls=calls, **kw), repo)

    # Design section 7.2: a retrying merge reads the pull request before each retry.
    def test_transient_merge_failure_is_retried_after_reading_the_pr(self):
        repo = self.repo_with_branch()
        calls = []
        rc, out, err = self.run_retry(
            repo, calls, state="OPEN", merges=[(1, "HTTP 502: bad gateway"), (0, "")]
        )
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(self.merge_calls(calls)), 2)
        self.assertIn("retrying (2 of 3)", err)
        merges = [i for i, c in enumerate(calls) if c[:2] == ("pr", "merge")]
        reads = [
            i for i, c in enumerate(calls) if c[:2] == ("pr", "view") and "state,headRefOid" in c
        ]
        self.assertTrue(any(merges[0] < i < merges[1] for i in reads), "no read between the tries")

    def test_merge_that_failed_but_landed_is_not_retried(self):
        repo = self.repo_with_branch()
        calls = []
        rc, out, err = self.run_retry(
            repo, calls, state="MERGED", merges=[(1, "HTTP 503: unavailable")]
        )
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(self.merge_calls(calls)), 1)
        self.assertIn("the PR is merged", err)

    def test_refusal_that_is_not_transient_is_never_retried(self):
        repo = self.repo_with_branch()
        calls = []
        rc, out, err = self.run_retry(
            repo, calls, state="OPEN", merges=[(1, "Pull request is not mergeable")]
        )
        self.assertEqual(rc, 2)
        self.assertEqual(len(self.merge_calls(calls)), 1)
        self.assertIn("merge refused", err)

    def test_closed_pr_is_not_retried(self):
        repo = self.repo_with_branch()
        calls = []
        rc, out, err = self.run_retry(
            repo, calls, state="CLOSED", merges=[(1, "connection reset by peer")]
        )
        self.assertEqual(rc, 2)
        self.assertEqual(len(self.merge_calls(calls)), 1)

    def test_moved_head_stops_the_retry(self):
        repo = self.repo_with_branch()
        calls = []
        rc, out, err = self.run_retry(
            repo,
            calls,
            state="OPEN",
            head="b" * 40,
            merges=[(1, "HTTP 502: bad gateway"), (0, "")],
        )
        self.assertEqual(rc, 2)
        self.assertEqual(len(self.merge_calls(calls)), 1)
        self.assertIn("moved", err)

    def test_retry_carries_the_pin_even_when_the_caller_passed_none(self):
        repo = self.repo_with_branch()
        calls = []
        rc, out, err = self.run_retry(
            repo, calls, state="OPEN", merges=[(1, "HTTP 502: bad gateway"), (0, "")]
        )
        self.assertEqual(rc, 0, err)
        first, retry = self.merge_calls(calls)
        self.assertNotIn("--match-head-commit", first)
        self.assertEqual(retry[retry.index("--match-head-commit") + 1], "a" * 40)
        self.assertEqual(retry.count("--match-head-commit"), 1)

    def test_retry_sleeps_then_reads_then_merges_on_the_rebase_path(self):
        repo = self.repo_with_branch()
        calls = []
        sleeps = lambda s: calls.append(("sleep", s))  # noqa: E731
        with (
            mock.patch.object(self.mod, "squash_commit", lambda *a: ("a" * 40, "")),
            mock.patch.object(self.mod.time, "sleep", sleeps),
        ):
            rc, out, err = self.run_main(
                self.fake_gh(
                    1,
                    calls=calls,
                    state="OPEN",
                    rebase=True,
                    merges=[(1, "HTTP 502: bad gateway"), (0, "")],
                ),
                repo,
            )
        self.assertEqual(rc, 0, err)
        steps = [
            "merge"
            if c[:2] == ("pr", "merge")
            else "read"
            if "state,headRefOid" in c
            else "sleep"
            if c[0] == "sleep"
            else None
            for c in calls
        ]
        self.assertEqual([x for x in steps if x], ["merge", "sleep", "read", "merge"])
        for merge in self.merge_calls(calls):
            self.assertIn("--rebase", merge)
            self.assertEqual(merge.count("--match-head-commit"), 1)
            self.assertEqual(merge[merge.index("--match-head-commit") + 1], "a" * 40)

    def test_attempts_and_pause_come_from_the_flags(self):
        repo = self.repo_with_branch()
        calls = []
        pauses = []
        with mock.patch.object(self.mod.time, "sleep", pauses.append):
            rc, out, err = self.run_main(
                self.fake_gh(1, calls=calls, state="OPEN", merges=[(1, "HTTP 502: bad gateway")]),
                repo,
                extra=("--attempts", "2", "--pause", "4"),
            )
        self.assertEqual(rc, 2)
        self.assertEqual(len(self.merge_calls(calls)), 2)
        self.assertEqual(pauses, [4])

    def test_retries_stop_after_the_attempt_limit(self):
        repo = self.repo_with_branch()
        calls = []
        rc, out, err = self.run_retry(
            repo, calls, state="OPEN", merges=[(1, "HTTP 502: bad gateway")]
        )
        self.assertEqual(rc, 2)
        self.assertEqual(len(self.merge_calls(calls)), self.mod.MERGE_ATTEMPTS)


class Fetch(unittest.TestCase):
    """The download helper: retry transient failures, fall back to a second URL, never retry a bad checksum."""

    API = "https://api.example/pkg/1"
    CDN = "https://cdn.example/pkg.1.nupkg"

    def setUp(self):
        self.ci = load("core_ci_fetch", "templates/overlay/scripts/core-ci.py")
        self.sleeps = []
        self.urls = []
        self.lines = []
        for p in (
            mock.patch.object(self.ci.time, "sleep", self.sleeps.append),
            mock.patch.object(self.ci, "say", self.lines.append),
        ):
            p.start()
            self.addCleanup(p.stop)

    def fake(self, plan):
        """plan maps a URL to a list of outcomes: bytes or an exception, consumed in order."""

        def get(url):
            self.urls.append(url)
            out = plan[url].pop(0)
            if isinstance(out, Exception):
                raise out
            return out

        p = mock.patch.object(self.ci, "_get", get)
        p.start()
        self.addCleanup(p.stop)

    def http(self, code):
        return self.ci.urllib.error.HTTPError(self.API, code, "x", {}, None)

    def sha(self, data):
        return self.ci.hashlib.sha256(data).hexdigest()

    def test_first_try(self):
        self.fake({self.API: [b"ok"]})
        self.assertEqual(self.ci.fetch(self.API, self.sha(b"ok"), self.CDN), b"ok")
        self.assertEqual((self.urls, self.sleeps), ([self.API], []))

    def test_404_then_success(self):
        self.fake({self.API: [self.http(404), b"ok"]})
        self.assertEqual(self.ci.fetch(self.API, self.sha(b"ok"), self.CDN, "dl"), b"ok")
        self.assertEqual((self.urls, self.sleeps), ([self.API, self.API], [5]))
        self.assertTrue(any("attempt 1 of 3 failed: HTTP 404" in x for x in self.lines))

    def test_api_fails_then_cdn_succeeds(self):
        err = self.ci.urllib.error.URLError("reset")
        self.fake({self.API: [self.http(503), err, TimeoutError("slow")], self.CDN: [b"ok"]})
        self.assertEqual(self.ci.fetch(self.API, self.sha(b"ok"), self.CDN), b"ok")
        self.assertEqual(self.urls, [self.API] * 3 + [self.CDN])
        self.assertEqual(self.sleeps, [5, 15])
        self.assertTrue(any("falling back to " + self.CDN in x for x in self.lines))

    def test_checksum_mismatch_fails_at_once(self):
        self.fake({self.API: [b"bad"], self.CDN: [b"ok"]})
        with self.assertRaises(self.ci.ChecksumError) as cm:
            self.ci.fetch(self.API, self.sha(b"ok"), self.CDN)
        self.assertIn("checksum mismatch", str(cm.exception))
        self.assertEqual((self.urls, self.sleeps), ([self.API], []))

    def test_checksum_mismatch_on_the_fallback_fails_at_once(self):
        self.fake({self.API: [self.http(404)] * 3, self.CDN: [b"bad", b"ok"]})
        with self.assertRaises(self.ci.ChecksumError):
            self.ci.fetch(self.API, self.sha(b"ok"), self.CDN)
        self.assertEqual(self.urls, [self.API] * 3 + [self.CDN])

    def test_everything_fails_gives_a_clear_error(self):
        self.fake({self.API: [self.http(404)] * 3, self.CDN: [self.http(502)] * 3})
        with self.assertRaises(RuntimeError) as cm:
            self.ci.fetch(self.API, self.sha(b"ok"), self.CDN, "install-x")
        msg = str(cm.exception)
        self.assertIn("install-x: every attempt failed (6 in all)", msg)
        self.assertIn("HTTP 502", msg)
        self.assertEqual(self.sleeps, [5, 15, 5, 15])

    def test_no_fallback_and_a_final_http_error_is_not_retried(self):
        self.fake({self.API: [self.http(403)]})
        with self.assertRaises(RuntimeError):
            self.ci.fetch(self.API, self.sha(b"ok"))
        self.assertEqual((self.urls, self.sleeps), ([self.API], []))

    def test_pssa_install_passes_the_cdn_fallback(self):
        seen = {}
        fake = lambda *a, **k: seen.update(a=a, k=k) or b"not a zip"  # noqa: E731
        # Parenthesised context managers need 3.10; the core supports 3.9, so two managers on one line.
        with mock.patch.object(self.ci, "fetch", fake), self.assertRaises(Exception):  # noqa: B017 - any failure after the fetch is the point
            self.ci.cmd_install_pssa([str(ROOT / ".test-work" / "pssa-x")])
        self.assertIn("/api/v2/package/PSScriptAnalyzer/" + self.ci.PSSA_VERSION, seen["a"][0])
        self.assertEqual(
            seen["k"]["fallback"],
            f"https://cdn.powershellgallery.com/packages/psscriptanalyzer.{self.ci.PSSA_VERSION}.nupkg",
        )


class CiFallback(unittest.TestCase):
    """#117 G-035 (core-status --ci): a merge gate that merges with the workflow token starts no push run,
    so the run on the head of the last merged pull request whose tree equals the branch stands in."""

    def setUp(self):
        self.st = load("core_status_ci", "templates/overlay/scripts/core-status.py")

    def runner(self, branch_runs, tree="T1", prs=None, head_trees=None, commit_runs=None):
        calls = []

        def run(args):
            calls.append(args)
            if args[:2] == ["run", "list"] and "--branch" in args:
                return 0, branch_runs.get(args[args.index("--workflow") + 1], "")
            if args[:2] == ["run", "list"] and "--commit" in args:
                return 0, (commit_runs or {}).get(
                    (args[args.index("--workflow") + 1], args[args.index("--commit") + 1]), ""
                )
            if args[:2] == ["run", "view"]:
                return 0, "lint\tsuccess\ntest\tsuccess"
            if args[:2] == ["pr", "list"]:
                return 0, json.dumps(prs or [])
            if args[0] == "api":
                ref = args[1].rsplit("/", 1)[1]
                return 0, tree if ref == "main" else (head_trees or {}).get(ref, "")
            return 1, ""

        return run, calls

    def test_default_branch_run_is_used_first(self):
        run, calls = self.runner({"core-ci.yml": "11"})
        out, problems = self.st.read_ci_runs(["core-ci.yml"], "main", run)
        self.assertEqual(
            (out, problems), ({"core-ci.yml": {"lint": "success", "test": "success"}}, [])
        )
        self.assertFalse([c for c in calls if c[:2] == ["pr", "list"]])

    def test_falls_back_to_the_last_merged_pr_head_with_the_same_tree(self):
        prs = [
            {"headRefOid": "old", "mergedAt": "2026-10-01T00:00:00Z"},
            {"headRefOid": "new", "mergedAt": "2026-10-02T00:00:00Z"},
        ]
        run, calls = self.runner(
            {},
            prs=prs,
            head_trees={"new": "T1", "old": "T0"},
            commit_runs={("core-ci.yml", "new"): "22", ("lint-sweep.yml", "new"): "23"},
        )
        out, problems = self.st.read_ci_runs(["core-ci.yml", "lint-sweep.yml"], "main", run)
        self.assertEqual(problems, [])
        self.assertEqual(sorted(out), ["core-ci.yml", "lint-sweep.yml"])
        self.assertEqual(
            len([c for c in calls if c[:2] == ["pr", "list"]]), 1
        )  # read once for both

    def test_steps_answer_and_a_push_run_is_filled_from_the_merged_pr_head(self):
        views = {
            "11": "core-checks\tsuccess\ncore-secret-scan\tsuccess\ncore-ascii\tskipped\ncore-python\tskipped",
            "22": "core-checks\tsuccess\ncore-secret-scan\tsuccess\ncore-ascii\tsuccess\ncore-python\tfailure",
        }
        run, calls = self.runner(
            {"core-ci.yml": "11"},
            prs=[{"headRefOid": "new", "mergedAt": "2026-10-02T00:00:00Z"}],
            head_trees={"new": "T1"},
            commit_runs={("core-ci.yml", "new"): "22"},
        )

        def viewing(args):
            if args[:2] == ["run", "view"]:
                return 0, views[args[2]]
            return run(args)

        out, problems = self.st.read_ci_runs(["core-ci.yml"], "main", viewing)
        self.assertEqual(problems, [])
        self.assertEqual(
            out["core-ci.yml"],
            {
                "core-checks": "success",
                "core-secret-scan": "success",
                "core-ascii": "success",
                "core-python": "failure",
            },
        )

    def test_no_fallback_when_the_tree_differs(self):
        run, _ = self.runner(
            {},
            prs=[{"headRefOid": "new", "mergedAt": "2026-10-02T00:00:00Z"}],
            head_trees={"new": "OTHER"},
            commit_runs={("core-ci.yml", "new"): "22"},
        )
        out, problems = self.st.read_ci_runs(["core-ci.yml"], "main", run)
        self.assertEqual(out, {})
        self.assertIn("no run of core-ci.yml", problems[0])


if __name__ == "__main__":
    unittest.main()
