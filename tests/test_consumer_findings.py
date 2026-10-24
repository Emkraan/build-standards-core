"""Tests for the v0.77.0 consumer findings: core- job names, the merge-gate trigger warning, template
parameters rows added by sync, wait-checks progress, and the core.bare guard. Fixtures live under
.test-work, never /tmp."""

import io
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from support import ROOT, Work, load, sh

SCRIPTS = ROOT / "templates" / "overlay" / "scripts"
TEMPLATE_WF = ROOT / "templates" / "overlay" / ".github" / "workflows" / "core-ci.yml"
ci = load("core_ci_findings", "templates/overlay/scripts/core-ci.py")
nightly = load("nightly_findings", "hermes/nightly.py")
ops = nightly.ops_center
sys.path.insert(0, str(SCRIPTS))
import corehash  # noqa: E402

GIT_ENV = dict(
    GIT_AUTHOR_NAME="T",
    GIT_COMMITTER_NAME="T",
    GIT_AUTHOR_EMAIL="1+t@users.noreply.github.com",
    GIT_COMMITTER_EMAIL="1+t@users.noreply.github.com",
    GIT_CONFIG_GLOBAL="/dev/null",
    GIT_CONFIG_NOSYSTEM="1",
)


def git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_ENV)
    r = subprocess.run(["git", *map(str, args)], cwd=repo, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class JobNames(Work):
    def test_every_template_job_is_core_prefixed_and_named(self):
        names = ci.workflow_check_names(TEMPLATE_WF)
        ids = ci.workflow_job_ids(TEMPLATE_WF)
        self.assertEqual(names, ids)
        self.assertTrue(all(n.startswith("core-") for n in names), names)
        jobs = ci.core_ci_jobs(TEMPLATE_WF.parent.parent.parent)
        self.assertNotIn("core-setup", jobs)
        self.assertIn("core-python", jobs)

    def test_check_rules_job_name_guard(self):
        mod = load("check_rules_findings", "checks/check-rules.py")
        self.assertEqual(mod.job_name_problems(), [])
        bad = self.dir / "core-ci.yml"
        bad.write_text(
            "name: core-ci\njobs:\n  python:\n    runs-on: x\n  core-a:\n    name: other\n"
        )
        with mock.patch.object(mod, "TEMPLATES", self.dir):
            problems = mod.job_name_problems()
        self.assertEqual(len(problems), 3, problems)

    def repo_with(self, workflow_text):
        repo = self.dir / "repo"
        (repo / ".github" / "workflows").mkdir(parents=True)
        (repo / ".github" / "workflows" / "core-ci.yml").write_text(workflow_text)
        return repo

    def test_stale_bare_names_in_the_gate_are_named_for_replacement(self):
        repo = self.repo_with(TEMPLATE_WF.read_text())
        old = [j[len("core-") :] for j in ci.core_ci_jobs(repo)]
        rep = ci.required_report(repo, api={"protection": {"contexts": old}, "rules": []})
        self.assertEqual(rep["stale"]["python"], "core-python")
        self.assertEqual(set(rep["missing"]), set(ci.core_ci_jobs(repo)))

    def test_an_old_workflow_copy_gets_a_recopy_note(self):
        repo = self.repo_with(
            "name: core-ci\njobs:\n  setup:\n    runs-on: x\n  python:\n    runs-on: x\n"
        )
        rep = ci.required_report(repo, api={"protection": {"contexts": ["python"]}, "rules": []})
        self.assertEqual(rep["missing"], [])
        self.assertTrue(any("copy the template" in n for n in rep["notes"]), rep["notes"])

    def test_core_status_reads_results_by_the_new_names(self):
        st = load("core_status_findings", "templates/overlay/scripts/core-status.py")
        rule = {"check": {"kind": "overlay-ci", "workflow": "core-ci.yml", "jobs": ["core-python"]}}
        with mock.patch.object(
            st, "workflow_jobs", lambda name: set(ci.workflow_job_ids(TEMPLATE_WF))
        ):
            self.assertEqual(
                st.overlay_ci_status(rule, {"core-ci.yml": {"core-python": "success"}})[0], "pass"
            )
            # A repo job called python in another workflow no longer answers for the core job.
            self.assertEqual(
                st.overlay_ci_status(rule, {"core-ci.yml": {"python": "success"}})[0], "unverified"
            )


class GateTrigger(Work):
    def lint(self, text):
        wf = self.dir / "automerge.yml"
        wf.write_text(text)
        return ci.gate_trigger_warnings(wf)

    def test_warns_when_core_ci_is_not_listed(self):
        self.assertEqual(
            len(
                self.lint(
                    'on:\n  workflow_run:\n    workflows: [CI, "PR Hygiene"]\n'
                    "    types: [completed]\npermissions: {}\n"
                )
            ),
            1,
        )
        self.assertEqual(
            len(
                self.lint(
                    "on:\n  workflow_run:\n    workflows:\n      - CI\n      - lint\n"
                    "permissions: {}\n"
                )
            ),
            1,
        )

    def test_quiet_when_core_ci_is_listed_or_no_workflow_run(self):
        self.assertEqual(
            self.lint("on:\n  workflow_run:\n    workflows: [CI, core-ci]\npermissions: {}\n"), []
        )
        self.assertEqual(
            self.lint('on:\n  workflow_run:\n    workflows:\n      - "core-ci"\n      - CI\n'), []
        )
        self.assertEqual(self.lint("on:\n  pull_request:\npermissions: {}\n"), [])

    def test_workflow_lint_warns_but_passes(self):
        d = self.dir / "wf"
        d.mkdir()
        (d / "automerge.yml").write_text(
            "on:\n  workflow_run:\n    workflows: [CI]\npermissions:\n  contents: read\n"
            "jobs:\n  a:\n    runs-on: x\n"
        )
        rc, out = sh([sys.executable, SCRIPTS / "core-ci.py", "workflow-lint", d])
        self.assertEqual(rc, 0, out)
        self.assertIn("::warning", out)
        self.assertIn("not core-ci", out)


LOCAL = (
    "# Local parameters\n\n| Parameter | Value | Used by |\n|---|---|---|\n"
    "| Identity provider | OIDC | rbac.md |\n"
    "| Python interpreter floor | 3.11 | scripting-python.md 1.1 |\n\nNotes below the table.\n"
)


class ParameterRows(Work):
    def test_missing_rows_are_appended_with_marker_and_existing_rows_kept(self):
        tpl = (ROOT / corehash.PARAMETERS_TEMPLATE).read_text()
        new, added = corehash.add_parameter_rows(tpl, LOCAL, "v9.9.9")
        self.assertIn("| Identity provider | OIDC | rbac.md |", new)
        self.assertIn("| Python interpreter floor | 3.11 | scripting-python.md 1.1 |", new)
        self.assertFalse(
            any(a.startswith(("Identity provider", "Python interpreter floor")) for a in added)
        )
        self.assertTrue(any(a.startswith("Commit emails") for a in added), added)
        lines = new.splitlines()
        commit_row = next(ln for ln in lines if ln.startswith("| Commit emails"))
        self.assertIn(corehash.ROW_MARKER + " v9.9.9", commit_row)
        # Appended inside the table, before the text below it, and a value-free template row stays empty.
        self.assertLess(lines.index(commit_row), lines.index("Notes below the table."))
        self.assertEqual([c.strip() for c in commit_row.strip("|").split("|")][1], "")
        again, more = corehash.add_parameter_rows(tpl, new, "v9.9.10")
        self.assertEqual((again, more), (new, []))

    def test_a_reworded_template_label_matches_the_short_local_label(self):
        tpl = "| Parameter | Value | Used by |\n|---|---|---|\n| Commit emails the check allows (globs) | | x |\n"
        local = "| Parameter | Value | Used by |\n|---|---|---|\n| Commit emails | *@example.com | x |\n"
        self.assertEqual(corehash.add_parameter_rows(tpl, local, "v1")[1], [])

    def test_sync_core_adds_rows_and_names_them(self):
        core = self.dir / "core"
        (core / "templates" / "overlay").mkdir(parents=True)
        shutil.copytree(
            ROOT / "templates" / "overlay" / "scripts", core / "templates" / "overlay" / "scripts"
        )
        shutil.copytree(
            ROOT / "templates" / "overlay" / "standards-local",
            core / "templates" / "overlay" / "standards-local",
        )
        (core / "standards").mkdir()
        (core / "standards" / "a.md").write_text("# a\n")
        git(self.dir, "init", "-q", "-b", "main", core)
        git(core, "add", "-A")
        git(core, "commit", "-q", "-m", "init")
        git(core, "tag", "v9.9.9")
        ov = self.dir / "overlay"
        shutil.copytree(ROOT / "templates" / "overlay" / "scripts", ov / "scripts")
        (ov / "standards-local").mkdir()
        (ov / "standards-local" / "parameters.md").write_text(LOCAL)
        (ov / "standards.lock").write_text("ref=v0.0.1\ncommit=abc\n")
        env = dict(os.environ, CORE_CHECKOUT=str(core), CORE_REPO="owner/core", **GIT_ENV)
        r = subprocess.run(
            [sys.executable, ov / "scripts" / "sync-core.py", "v9.9.9"],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = [ln for ln in r.stdout.splitlines() if ln.startswith("parameters: added")]
        self.assertEqual(len(lines), 1, r.stdout)
        self.assertIn("Commit emails", lines[0])
        text = (ov / "standards-local" / "parameters.md").read_text()
        self.assertIn("| Identity provider | OIDC | rbac.md |", text)
        self.assertIn(corehash.ROW_MARKER + " v9.9.9", text)


class Progress(unittest.TestCase):
    def test_one_progress_line_at_most_every_five_minutes(self):
        now = [0.0]
        out = io.StringIO()
        pending = (
            [("a", "completed", "success"), ("b", "in_progress", None), ("c", "queued", None)],
            [],
        )
        reads = iter(
            [pending] * 12
            + [
                (
                    [
                        ("a", "completed", "success"),
                        ("b", "completed", "failure"),
                        ("c", "completed", "success"),
                    ],
                    [],
                )
            ]
        )
        with mock.patch("sys.stdout", out):
            rc = ci.wait_loop(
                lambda: next(reads),
                [],
                3600,
                60,
                2,
                sleep=lambda s: now.__setitem__(0, now[0] + s),
                clock=lambda: now[0],
            )
        self.assertEqual(rc, 1)
        lines = [ln for ln in out.getvalue().splitlines() if "progress" in ln]
        self.assertEqual(
            lines,
            [
                "wait-checks: progress 5 min: 1 done, 2 pending, 0 failed",
                "wait-checks: progress 10 min: 1 done, 2 pending, 0 failed",
            ],
        )

    def test_counts(self):
        self.assertEqual(
            ci.check_counts(
                [("a", "completed", "skipped"), ("b", "completed", "failure")],
                [("s", "pending"), ("t", "success")],
            ),
            (2, 1, 1),
        )

    def test_ops_center_prints_only_progress_lines(self):
        out = io.StringIO()
        echo = ops.progress_printer("o/app", "5", out)
        echo("wait-checks: o/app@abc, expecting x")
        echo("wait-checks: progress 5 min: 3 done, 20 pending, 0 failed")
        self.assertEqual(
            out.getvalue(),
            "ui o/app: #5 wait-checks: progress 5 min: 3 done, 20 pending, 0 failed\n",
        )

    def test_nightly_sh_streams_lines_and_drops_repo_git_variables(self):
        seen = []
        code = 'import os\nprint("one", flush=True)\nprint(os.environ.get("GIT_DIR", "none"))\n'
        with mock.patch.dict(os.environ, {"GIT_DIR": "/elsewhere/.git/worktrees/x"}):
            rc, out = nightly.sh([sys.executable, "-c", code], echo=seen.append)
            self.assertEqual(nightly.sh([sys.executable, "-c", code])[1], "one\nnone")
        self.assertEqual((rc, out, seen), (0, "one\nnone", ["one", "none"]))


class BareFlag(Work):
    """The consumer clone's core.bare flipped to true after the nightly's worktree work: a pre-push hook
    that runs git init (as test fixtures do) with the worktree's GIT_DIR writes core.bare = true."""

    def make(self):
        self.clone = self.dir / "app"
        ov = self.clone / "standards-overlay"
        (ov / "scripts").mkdir(parents=True)
        (ov / "standards.lock").write_text("ref=v1\n")
        (ov / "scripts" / "sync-core.py").write_text(
            "import sys,pathlib\npathlib.Path('standards.lock').write_text('ref=' + sys.argv[1] + '\\n')\n"
        )
        git(self.dir, "init", "-q", "-b", "main", self.clone)
        git(self.clone, "add", "-A")
        git(self.clone, "commit", "-q", "-m", "init")
        self.remote = self.dir / "remote.git"
        git(self.dir, "clone", "-q", "--bare", self.clone, self.remote)
        git(self.clone, "remote", "add", "origin", self.remote)
        git(self.clone, "fetch", "-q", "origin")
        # Absolute, so a push from a worktree runs it too; never the machine's global hooks.
        git(self.clone, "config", "core.hooksPath", self.clone / ".git" / "hooks")
        fixture = self.dir / "fixture"
        fixture.mkdir()
        hook = self.clone / ".git" / "hooks" / "pre-push"
        hook.parent.mkdir(exist_ok=True)
        hook.write_text(f'#!/bin/sh\ncd "{fixture}" && git init -q >/dev/null 2>&1\nexit 0\n')
        hook.chmod(0o755)
        self.cfg = {
            "repo": "o/app",
            "path": str(self.clone),
            "overlay": "standards-overlay",
            "apply_via": "direct",
        }

    def bare(self):
        return git(
            self.clone, "config", "--file", self.clone / ".git" / "config", "--get", "core.bare"
        )

    def run_sh(self, cmd, cwd=None, timeout=60, echo=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_ENV)
        r = subprocess.run(
            [str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env
        )
        return r.returncode, (r.stdout + r.stderr).strip()

    def test_the_hook_in_a_worktree_push_is_what_flips_it(self):
        self.make()
        wt = self.dir / "wt"
        git(self.clone, "worktree", "add", "-q", "--detach", wt)
        self.run_sh(["git", "-C", wt, "push", "-q", "origin", "HEAD:refs/heads/probe"])
        self.assertEqual(self.bare(), "true")  # the cause, reproduced

    def test_core_bare_stays_false_after_an_ops_center_apply(self):
        self.make()
        r = ops.apply(self.cfg, "v2", self.run_sh, self.dir / "state")
        self.assertEqual(r["status"], "applied", r)
        self.assertEqual(self.bare(), "false")
        self.assertEqual(r["bare"], "")
        self.assertEqual(ops.pin_at(self.remote, "main", "standards-overlay", sh), "v2")

    def test_guard_restores_a_flipped_flag_and_reports_it_once(self):
        self.make()
        git(self.clone, "config", "--file", self.clone / ".git" / "config", "core.bare", "true")
        r = ops.apply(self.cfg, "v2", self.run_sh, self.dir / "state")
        self.assertEqual(self.bare(), "false")
        self.assertIn("before", r["bare"])
        self.assertEqual(r["status"], "applied", r)
        run = nightly.Run(
            {
                "core": str(self.dir / "nocore"),
                "hermes_home": str(self.dir),
                "apply": {},
                "ui_consumers": [self.cfg],
            },
            False,
            0,
        )
        git(self.clone, "config", "--file", self.clone / ".git" / "config", "core.bare", "true")
        run.bare_guard("before the run")
        run.bare_guard("after the run")
        run.bare_report()
        self.assertEqual(len(run.problems), 1, run.problems)
        self.assertIn("before the run", run.problems[0])
        self.assertEqual(self.bare(), "false")

    def test_a_real_bare_repo_is_left_alone(self):
        self.make()
        self.assertFalse(ops.bare_flag_restore(self.remote, self.run_sh))
        self.assertEqual(git(self.remote, "config", "--get", "core.bare"), "true")


if __name__ == "__main__":
    unittest.main()
