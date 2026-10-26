"""Tests for the reusable core-ci workflow (.github/workflows/core-ci-reusable.yml) and the tooling that
reads a core-ci.yml which calls it. Fixtures live under .test-work, never /tmp."""

import os
import re
import subprocess
import sys
import unittest

from support import ROOT, Work, load

SCRIPTS = ROOT / "templates" / "overlay" / "scripts"
TEMPLATE = ROOT / "templates" / "overlay" / ".github" / "workflows" / "core-ci.yml"
REUSABLE = ROOT / ".github" / "workflows" / "core-ci-reusable.yml"
ci = load("core_ci_reusable", "templates/overlay/scripts/core-ci.py")
sys.path.insert(0, str(SCRIPTS))
import corehash  # noqa: E402

st = load("core_status_reusable", "templates/overlay/scripts/core-status.py")

CALLER = """name: core-ci
on:
  pull_request:
    types: [opened, edited, synchronize, reopened]
  merge_group:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  %s:
%s    uses: OWNER/build-standards-core/.github/workflows/core-ci-reusable.yml@%s # v1.12.0
    with:
      runs-on: '["self-hosted", "forge"]'
"""
SHA = "0123456789abcdef0123456789abcdef01234567"


def steps_of(path):
    """The text of the steps of the job, from core-setup on, with the script path made comparable."""
    text = path.read_text(encoding="utf8")
    body = text[text.index("      - name: core-setup") :]
    return body.replace('"$OVERLAY/scripts/core-ci.py"', '"$CORE_CI"')


def step_names(path):
    return re.findall(r"^\s+-\s+name:\s*(.+?)\s*$", steps_of(path), re.M)


def env_block(path):
    text = path.read_text(encoding="utf8")
    return {k: v.strip() for k, v in re.findall(r"^  (BASE|HEAD|FULL|COMMITS): (.+)$", text, re.M)}


class Shape(unittest.TestCase):
    def test_same_steps_and_gating_as_the_template(self):
        # Every check step, its `if` gating and its commands are the template's, byte for byte.
        self.assertEqual(steps_of(TEMPLATE), steps_of(REUSABLE))

    def test_same_event_values_as_the_template(self):
        self.assertEqual(env_block(TEMPLATE), env_block(REUSABLE))
        self.assertEqual(sorted(env_block(REUSABLE)), ["BASE", "COMMITS", "FULL", "HEAD"])

    def test_one_job_named_core_checks(self):
        text = REUSABLE.read_text(encoding="utf8")
        self.assertEqual(
            re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", text.split("\njobs:\n")[1], re.M),
            ["core-checks"],
        )
        self.assertIn("    name: core-checks\n", text)
        self.assertIn("workflow_call:", text)
        # Triggers belong to the caller: nothing here fires on its own.
        self.assertNotRegex(
            text, r"(?m)^  (pull_request|push|merge_group|schedule|workflow_dispatch):"
        )

    def test_core_and_caller_are_checked_out_at_the_pinned_ref(self):
        text = REUSABLE.read_text(encoding="utf8")
        self.assertIn("job.workflow_sha", text)
        self.assertIn("job.workflow_repository", text)
        self.assertIn("ref: ${{ env.HEAD }}", text)
        self.assertIn("CORE_CI_OVERLAY", text)

    def test_status_step_list_matches_both_workflows(self):
        core = [n for n in step_names(TEMPLATE) if n.startswith("core-")]
        self.assertEqual(
            core, [n for n in step_names(REUSABLE) if n.startswith("core-") and n != "core-fetch"]
        )
        self.assertEqual(sorted(st.CORE_CI_STEPS), sorted(core))

    def test_runner_inputs_keep_the_variable_fallback(self):
        text = REUSABLE.read_text(encoding="utf8")
        self.assertIn("fromJSON(inputs.runs-on || vars.CORE_CI_RUNNER || '\"ubuntu-24.04\"')", text)

    def test_lints_clean(self):
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "core-ci.py"), "workflow-lint", str(REUSABLE)],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class Caller(Work):
    def repo(self, text):
        subprocess.run(["git", "init", "-q", str(self.dir)], check=True)
        wf = self.dir / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "core-ci.yml").write_text(text, encoding="utf8")
        return wf / "core-ci.yml"

    def test_check_name_is_caller_slash_called(self):
        f = self.repo(CALLER % ("core-checks", "", SHA))
        self.assertEqual(ci.workflow_check_names(f), ["core-checks / core-checks"])
        f.write_text(CALLER % ("core", "    name: core\n", SHA), encoding="utf8")
        self.assertEqual(ci.workflow_check_names(f), ["core / core-checks"])
        # The synced template keeps its bare name.
        self.assertEqual(ci.workflow_check_names(TEMPLATE), ["core-checks"])

    def test_required_report_wants_the_qualified_name(self):
        self.repo(CALLER % ("core-checks", "", SHA))
        rep = ci.required_report(
            self.dir, "o/r", "main", {"protection": {"contexts": ["core-checks"]}, "rules": []}
        )
        self.assertEqual(rep["missing"], ["core-checks / core-checks"])
        self.assertEqual(rep["obsolete"], ["core-checks"])
        self.assertTrue(any("reusable workflow" in n for n in rep["notes"]))
        ok = ci.required_report(
            self.dir,
            "o/r",
            "main",
            {"protection": {"contexts": ["core-checks / core-checks"]}, "rules": []},
        )
        self.assertEqual((ok["missing"], ok["obsolete"]), ([], []))

    def test_template_copy_with_the_qualified_name_required_is_flagged(self):
        wf = self.dir / ".github" / "workflows"
        self.repo(TEMPLATE.read_text(encoding="utf8"))
        rep = ci.required_report(
            self.dir,
            "o/r",
            "main",
            {"protection": {"contexts": ["core-checks / core-checks"]}, "rules": []},
        )
        self.assertEqual(rep["missing"], ["core-checks"])
        self.assertEqual(rep["obsolete"], ["core-checks / core-checks"])
        self.assertTrue(wf.is_dir())

    def test_sync_leaves_a_caller_alone_and_refreshes_a_copy(self):
        f = self.repo(CALLER % ("core-checks", "", SHA))
        core = self.dir / "core"
        tpl = core / corehash.WORKFLOW_TEMPLATE
        tpl.mkdir(parents=True)
        (tpl / "core-ci.yml").write_text(TEMPLATE.read_text(encoding="utf8"), encoding="utf8")
        before = f.read_text(encoding="utf8")
        done, notes = corehash.sync_workflows(core, self.dir)
        self.assertEqual(done, [])
        self.assertEqual(f.read_text(encoding="utf8"), before)
        self.assertTrue(any("reusable workflow" in n for n in notes))
        # A synced copy of an older template is still refreshed.
        f.write_text("name: core-ci\njobs:\n  core-checks:\n    runs-on: x\n", encoding="utf8")
        done, _ = corehash.sync_workflows(core, self.dir)
        self.assertEqual(done, ["core-ci.yml"])

    def test_status_reads_the_core_steps_of_a_caller(self):
        self.repo(CALLER % ("core-checks", "", SHA))
        old = st.repo_root
        st.repo_root = lambda: self.dir
        self.addCleanup(setattr, st, "repo_root", old)
        jobs = st.workflow_jobs("core-ci.yml")
        self.assertIn("core-secret-scan", jobs)
        self.assertIn("core-checks", jobs)

    def test_run_results_reads_the_qualified_job_name(self):
        tsv = "core-checks / core-checks\tsuccess\ncore-secret-scan\tsuccess\n"
        got = st.run_results("1", lambda args: (0, tsv))
        self.assertEqual(got["core-checks"], "success")
        self.assertEqual(got["core-secret-scan"], "success")


class Overlay(Work):
    def test_params_read_the_callers_overlay_through_the_environment(self):
        ov = self.dir / "overlay"
        (ov / "standards-local").mkdir(parents=True)
        (ov / "standards-local" / "parameters.md").write_text(
            "| Parameter | Value |\n|---|---|\n| Stacks | `web` |\n| Python test command | `make t` |\n",
            encoding="utf8",
        )
        subprocess.run(["git", "init", "-q", str(self.dir)], check=True)
        env = dict(os.environ, CORE_CI_OVERLAY=str(ov))
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "core-ci.py"), "params"],
            capture_output=True,
            text=True,
            cwd=self.dir,
            env=env,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        got = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
        self.assertEqual(got["stacks"], "web")
        self.assertEqual(got["python_test"], "make t")
        self.assertEqual(got["web"], "true")

    def test_default_overlay_is_the_folder_above_the_scripts(self):
        env = {k: v for k, v in os.environ.items() if k != "CORE_CI_OVERLAY"}
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                "import importlib.util as u;s=u.spec_from_file_location('m','core-ci.py');"
                "m=u.module_from_spec(s);s.loader.exec_module(m);print(m.ROOT)",
            ],
            capture_output=True,
            text=True,
            cwd=SCRIPTS,
            env=env,
        )
        self.assertEqual(r.stdout.strip(), str(SCRIPTS.parent.resolve()), r.stderr)


if __name__ == "__main__":
    unittest.main()
