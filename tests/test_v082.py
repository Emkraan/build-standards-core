"""Tests for v0.82.0: the workflow sync of scripts/sync-core.py. Fixture repos live under .test-work, never /tmp."""

import os
import re
import shutil
import subprocess
import sys
import unittest

from support import ROOT, Work, load

SCRIPTS = ROOT / "templates" / "overlay" / "scripts"
TEMPLATES = ROOT / "templates" / "overlay" / ".github" / "workflows"
sys.path.insert(0, str(SCRIPTS))
import corehash  # noqa: E402

nightly = load("nightly_v082", "hermes/nightly.py")
ops = nightly.ops_center

NOREPLY = "1+t@users.noreply.github.com"
LEAK = "me" + "@" + "work.example"  # built, so the sanitiser sees no address in this file
GIT_ENV = dict(
    GIT_AUTHOR_NAME="T",
    GIT_COMMITTER_NAME="T",
    GIT_AUTHOR_EMAIL=NOREPLY,
    GIT_COMMITTER_EMAIL=NOREPLY,
    GIT_CONFIG_GLOBAL="/dev/null",
    GIT_CONFIG_NOSYSTEM="1",
)


def git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_ENV)
    r = subprocess.run(["git", *map(str, args)], cwd=repo, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def bare_names(text):
    """A core-ci.yml from before the core- prefix: job ids and names without it."""
    return re.sub(r"^(  |    name: )core-", r"\1", text, flags=re.M)


class WorkflowMerge(unittest.TestCase):
    def test_overlay_value_and_marked_lines_are_kept(self):
        tpl = (TEMPLATES / "lint-sweep.yml").read_text()
        local = tpl.replace("OVERLAY: .", "OVERLAY: standards-overlay").replace(
            '"41 5 * * 1"', '"3 2 * * 2"'
        )
        new = corehash.merge_workflow(tpl + "# new line\n", local)
        self.assertIn("  OVERLAY: standards-overlay\n", new)
        self.assertIn('- cron: "3 2 * * 2"  # core-sync: keep', new)
        self.assertIn("# new line", new)

    def test_lint_sweep_sets_up_node_only_for_web(self):
        tpl = (TEMPLATES / "lint-sweep.yml").read_text()
        gate = "if: steps.p.outputs.web == 'true' && steps.p.outputs.lint_sweep != ''"
        self.assertEqual(tpl.count(gate), 2)
        self.assertRegex(tpl, r"uses: actions/setup-node@[0-9a-f]{40} # v")
        self.assertIn("corepack enable", tpl)
        self.assertIn("pnpm install --frozen-lockfile", tpl)
        self.assertIn("::error::toolchain missing", tpl)
        self.assertIn('"$src" -eq 127', tpl)

    def test_core_drift_prefix_is_kept(self):
        tpl = (TEMPLATES / "core-drift.yml").read_text()
        local = tpl.replace("python3 scripts/", "python3 ov/scripts/").replace(
            "python3 lint-core/", "python3 ov/lint-core/"
        )
        new = corehash.merge_workflow(tpl, local)
        self.assertIn("python3 ov/scripts/check-core-sync.py", new)
        self.assertIn("python3 ov/lint-core/ui_lint.py", new)
        self.assertNotIn("python3 scripts/", new)
        self.assertEqual(corehash.merge_workflow(tpl, tpl), tpl)

    def test_renamed_checks(self):
        tpl = (TEMPLATES / "core-ci.yml").read_text()
        pairs = corehash.renamed_checks(bare_names(tpl), tpl)
        self.assertTrue(pairs)
        self.assertTrue(all(n == "core-" + o for o, n in pairs), pairs)
        self.assertNotIn("core-setup", [n for _, n in pairs])
        self.assertEqual(corehash.renamed_checks(tpl, tpl), [])
        self.assertEqual(
            corehash.renamed_checks("jobs:\n  a:\n    x: 1\n", "jobs:\n  b:\n    x: 1\n"),
            [("a", "(removed)"), ("(new)", "b")],
        )

    def test_ops_center_commits_the_same_workflows(self):
        self.assertEqual(
            ops.WORKFLOW_PATHS, tuple(f".github/workflows/{n}" for n in corehash.WORKFLOWS)
        )

    def test_ops_center_sync_notes(self):
        out = (
            "synced\nworkflows: refreshed core-ci.yml (per-repo settings kept)\nrequired checks: x:\n"
            "  ascii -> core-ascii\nsynced core@abc"
        )
        self.assertEqual(
            ops.sync_notes(out),
            "workflows: refreshed core-ci.yml (per-repo settings kept)\n"
            "required checks: x:\n  ascii -> core-ascii",
        )


class SyncFixture(Work):
    """sync-core.py against a fixture core and a fixture consumer repo whose overlay is a subfolder."""

    def test_refreshes_template_workflows_only(self):
        core = self.dir / "core"
        (core / "templates" / "overlay" / ".github").mkdir(parents=True)
        shutil.copytree(SCRIPTS, core / "templates" / "overlay" / "scripts")
        shutil.copytree(TEMPLATES, core / "templates" / "overlay" / ".github" / "workflows")
        (core / "standards").mkdir()
        (core / "standards" / "a.md").write_text("# a\n")
        git(self.dir, "init", "-q", "-b", "main", core)
        git(core, "add", "-A")
        git(core, "commit", "-q", "-m", "init")
        git(core, "tag", "v9.9.9")

        app = self.dir / "app"
        ov = app / "ov"
        shutil.copytree(SCRIPTS, ov / "scripts")
        (ov / "standards.lock").write_text("ref=v0.0.1\ncommit=abc\n")
        wf = app / ".github" / "workflows"
        wf.mkdir(parents=True)
        old_ci = bare_names((TEMPLATES / "core-ci.yml").read_text()).replace(
            "OVERLAY: .", "OVERLAY: ov"
        )
        (wf / "core-ci.yml").write_text(old_ci + "# stale line\n")
        drift = (TEMPLATES / "core-drift.yml").read_text()
        (wf / "core-drift.yml").write_text(
            "# old\n"
            + drift.replace("python3 scripts/", "python3 ov/scripts/").replace(
                "python3 lint-core/", "python3 ov/lint-core/"
            )
        )
        own = "name: own\non: push\njobs:\n  a:\n    runs-on: x\n"
        (wf / "own.yml").write_text(own)
        git(self.dir, "init", "-q", "-b", "main", app)

        notes = self.dir / "notes.txt"
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(
            GIT_ENV, CORE_CHECKOUT=str(core), CORE_REPO="owner/core", CORE_SYNC_NOTES=str(notes)
        )
        r = subprocess.run(
            [sys.executable, ov / "scripts" / "sync-core.py", "v9.9.9"],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("workflows: refreshed core-ci.yml, core-drift.yml", r.stdout)
        self.assertIn("required checks: core-ci.yml job names changed", r.stdout)
        self.assertRegex(r.stdout, r"\n  [a-z-]+ -> core-[a-z-]+")
        self.assertIn(" -> core-", notes.read_text())
        ci = (wf / "core-ci.yml").read_text()
        self.assertNotIn("# stale line", ci)
        self.assertIn("  OVERLAY: ov\n", ci)
        self.assertEqual(
            ci, (TEMPLATES / "core-ci.yml").read_text().replace("OVERLAY: .", "OVERLAY: ov")
        )
        d = (wf / "core-drift.yml").read_text()
        self.assertIn("python3 ov/scripts/check-core-sync.py", d)
        self.assertNotIn("# old", d)
        self.assertEqual((wf / "own.yml").read_text(), own)
        self.assertFalse((wf / "lint-sweep.yml").exists())
        self.assertFalse((wf / "core-update.yml").exists())


if __name__ == "__main__":
    unittest.main()
