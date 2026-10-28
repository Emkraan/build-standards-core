"""Consumer-reported gaps: latest by semantic version, the gate rewrite order, same-named workflows,
the UI adoption stage and the ascii_ignore table. Fixtures live under .test-work, never /tmp."""

import os
import shutil
import stat
import subprocess
import sys
import unittest

from support import ROOT, Work, load

SCRIPTS = ROOT / "templates" / "overlay" / "scripts"
TEMPLATES = ROOT / "templates" / "overlay" / ".github" / "workflows"
sys.path.insert(0, str(SCRIPTS))
import corehash as ch  # noqa: E402

core_ci = load("core_ci_gaps", "templates/overlay/scripts/core-ci.py")
status = load("core_status_gaps", "templates/overlay/scripts/core-status.py")

NOREPLY = "1+t@users.noreply.github.com"
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


class Latest(Work):
    """latest is the highest strict vX.Y.Z tag, whatever gh calls the latest release."""

    def setUp(self):
        super().setUp()
        src = self.dir / "src"
        src.mkdir()
        git(src, "init", "-q", "-b", "main")
        for i, tag in enumerate(
            ("v1.28.1", "v1.2.0-rc1", "v1.9.0", "v0.101.0", "nightly", "v1.28.0")
        ):
            (src / "f").write_text(f"{i}\n")
            git(src, "add", "-A")
            git(src, "commit", "-q", "-m", f"chore: {i}")
            git(src, "tag", tag)
        base = self.dir / "host"
        (base / "owner").mkdir(parents=True)
        git(self.dir, "clone", "-q", "--bare", str(src), str(base / "owner" / "core.git"))
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        # gh claims the old v0.101.0 is the latest release, as a flag set by hand can.
        gh.write_text('#!/bin/sh\n[ "$1" = repo ] && exit 1\necho v0.101.0\n')
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.src = src
        self.old = dict(os.environ)
        os.environ.update(CORE_GIT_BASE=f"file://{base}", PATH=f"{bin_dir}:{os.environ['PATH']}")
        os.environ.pop("CORE_CHECKOUT", None)
        self.addCleanup(self.restore)

    def restore(self):
        os.environ.clear()
        os.environ.update(self.old)

    def test_latest_ignores_gh_latest_flag_and_non_strict_tags(self):
        self.assertEqual(ch.latest_tag("owner/core"), "v1.28.1")

    def test_latest_reads_a_named_checkout_without_network(self):
        os.environ["CORE_CHECKOUT"] = str(self.src)
        os.environ["CORE_GIT_BASE"] = "file:///nonexistent"
        self.assertEqual(ch.latest_tag("owner/core"), "v1.28.1")

    def test_checkout_alone_names_the_core(self):
        os.environ["CORE_CHECKOUT"] = str(self.src)
        self.assertEqual(ch.checkout_slug(), "local/core")
        git(self.src, "remote", "add", "origin", "https://github.com/owner/core.git")
        self.assertEqual(ch.checkout_slug(), "owner/core")

    def test_explicit_tag_clones_with_no_checkout_variable(self):
        dest = self.dir / "c"
        ch.clone("owner/core", dest, "v1.9.0")
        self.assertEqual((dest / "f").read_text().strip(), "2")


def build_core(work):
    core = work.dir / "core"
    (core / "templates" / "overlay" / ".github").mkdir(parents=True)
    shutil.copytree(SCRIPTS, core / "templates" / "overlay" / "scripts")
    shutil.copytree(TEMPLATES, core / "templates" / "overlay" / ".github" / "workflows")
    (core / "standards").mkdir()
    (core / "standards" / "a.md").write_text("# a\n")
    git(work.dir, "init", "-q", "-b", "main", core)
    git(core, "add", "-A")
    git(core, "commit", "-q", "-m", "init")
    git(core, "tag", "v9.9.9")
    return core


def old_core_ci():
    text = (TEMPLATES / "core-ci.yml").read_text()
    return text.replace("core-checks:", "core-ascii:").replace("OVERLAY: .", "OVERLAY: ov")


class Sync(Work):
    def app(self, committed):
        """An app repo with the overlay in ov/ and the given files committed on main."""
        app = self.dir / "app"
        ov = app / "ov"
        shutil.copytree(SCRIPTS, ov / "scripts")
        (ov / "standards.lock").write_text("ref=v0.0.1\ncommit=abc\n")
        wf = app / ".github" / "workflows"
        wf.mkdir(parents=True)
        git(self.dir, "init", "-q", "-b", "main", app)
        for name, text in committed.items():
            (wf / name).write_text(text)
        if committed:
            git(app, "add", "-A")
            git(app, "commit", "-q", "-m", "init")
        return app, ov, wf

    def sync(self, ov, *args):
        core = build_core(self)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_ENV, CORE_CHECKOUT=str(core), CORE_REPO="owner/core")
        return subprocess.run(
            [sys.executable, ov / "scripts" / "sync-core.py", "v9.9.9", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )

    GATE = "name: automerge\nenv:\n  REQUIRED_CHECKS: own-build core-ascii\n"

    def test_gate_is_not_rewritten_where_the_default_branch_lacks_core_checks(self):
        app, ov, wf = self.app({"automerge.yml": self.GATE})
        (wf / "core-ci.yml").write_text(old_core_ci())  # the sync branch only: not committed
        r = self.sync(ov)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((wf / "automerge.yml").read_text(), self.GATE)
        self.assertIn("required-checks: not rewritten", r.stdout)
        self.assertIn("REQUIRED_CHECKS: own-build core-checks", r.stdout)
        self.assertIn("Ordering rule", r.stdout)

    def test_gate_is_rewritten_once_the_default_branch_has_core_checks(self):
        committed = {
            "automerge.yml": self.GATE,
            "core-ci.yml": (TEMPLATES / "core-ci.yml").read_text(),
        }
        app, ov, wf = self.app(committed)
        (wf / "core-ci.yml").write_text(old_core_ci())
        r = self.sync(ov)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("REQUIRED_CHECKS: own-build core-checks", (wf / "automerge.yml").read_text())
        self.assertIn("required-checks: rewrote", r.stdout)

    def test_gate_is_rewritten_when_the_sync_adds_job_and_gate_together(self):
        app, ov, wf = self.app({})
        (wf / "automerge.yml").write_text(self.GATE)
        (wf / "core-ci.yml").write_text(old_core_ci())
        r = self.sync(ov)
        self.assertIn("required-checks: rewrote", r.stdout)

    def test_a_same_named_own_workflow_is_never_overwritten(self):
        own = "name: lint-sweep\non: push\njobs:\n  a:\n    runs-on: x\n"
        app, ov, wf = self.app({"lint-sweep.yml": own})
        r = self.sync(ov)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((wf / "lint-sweep.yml").read_text(), own)
        self.assertTrue((wf / "lint-sweep.yml.core-new").is_file())
        self.assertIn(
            "diff -u .github/workflows/lint-sweep.yml .github/workflows/lint-sweep.yml.core-new",
            r.stdout,
        )

    def test_strict_exits_nonzero_when_a_file_was_skipped(self):
        own = "name: lint-sweep\non: push\njobs:\n  a:\n    runs-on: x\n"
        app, ov, wf = self.app({"lint-sweep.yml": own})
        r = self.sync(ov, "--strict")
        self.assertEqual(r.returncode, 1)
        self.assertEqual((wf / "lint-sweep.yml").read_text(), own)

    def test_a_marked_or_older_synced_copy_is_still_refreshed(self):
        app, ov, wf = self.app({})
        (wf / "core-ci.yml").write_text(old_core_ci())
        legacy = (
            (TEMPLATES / "core-drift.yml")
            .read_text()
            .replace(
                "# core-managed: this file is refreshed from the core release by scripts/sync-core.py\n",
                "",
            )
        )
        (wf / "core-drift.yml").write_text(legacy + "# stale\n")
        r = self.sync(ov, "--strict")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("workflows: refreshed", r.stdout)
        self.assertNotIn("# stale", (wf / "core-drift.yml").read_text())
        self.assertFalse((wf / "core-drift.yml.core-new").exists())

    def test_is_core_managed(self):
        self.assertTrue(ch.is_core_managed("x.yml", "name: x\n# core-managed: y\n"))
        self.assertFalse(ch.is_core_managed("core-ci.yml", "name: core-ci\njobs: {}\n"))
        self.assertFalse(ch.is_core_managed("core-ci.yml", "name: other\n# standards.lock\n"))


class Params(Work):
    def sheet(self, text):
        f = self.dir / "parameters.md"
        f.write_text(text)
        return f

    def test_ui_stage_reads_the_row(self):
        for value, want in (
            ("none", "none"),
            ("`Partial`", "partial"),
            ("adopted", "adopted"),
            ("", ""),
            ("junk", ""),
        ):
            status.PARAMETERS = self.sheet(
                f"| Parameter | Value | Used |\n|---|---|---|\n| UI adoption stage (x) | {value} | y |\n"
            )
            self.assertEqual(status.ui_stage(), want)
        status.PARAMETERS = self.dir / "missing.md"
        self.assertEqual(status.ui_stage(), "")

    def test_template_ships_the_rows(self):
        text = (ROOT / "templates/overlay/standards-local/parameters.md").read_text()
        self.assertIn("| UI adoption stage", text)
        self.assertIn("## ascii_ignore", text)
        # the ignore table header is not mistaken for a parameter row by the sync
        self.assertIsNone(ch._row_cells("| Path | Reason |"))

    def test_ascii_ignore_needs_a_reason_and_skips_scripts(self):
        f = self.sheet(
            "| Parameter | Value |\n|---|---|\n| X | y |\n\n## ascii_ignore\n\n| Path | Reason |\n|---|---|\n"
            "| vendor/ | imported archive |\n| data/*.csv | export |\n| bad/ | |\n"
        )
        rows, problems = core_ci.ascii_ignore_rows(f)
        self.assertEqual(rows, [("vendor/", "imported archive"), ("data/*.csv", "export")])
        self.assertEqual(len(problems), 1)
        self.assertEqual(core_ci.ascii_ignored("vendor/a/b.txt", rows), "imported archive")
        self.assertEqual(core_ci.ascii_ignored("data/x.csv", rows), "export")
        self.assertIsNone(core_ci.ascii_ignored("src/a.txt", rows))
        self.assertIsNone(core_ci.ascii_ignored("vendor/a.ps1", rows))
        self.assertIsNone(core_ci.ascii_ignored("vendor/a.xaml", rows))
        self.assertEqual(core_ci.ascii_ignore_rows(self.dir / "none.md"), ([], []))

    def test_cmd_ascii_ignores_listed_paths_and_fails_unlisted(self):
        repo = self.dir / "r"
        (repo / "vendor").mkdir(parents=True)
        (repo / "vendor" / "a.txt").write_bytes("caf\u00e9\n".encode())
        (repo / "b.txt").write_bytes("caf\u00e9\n".encode())
        git(self.dir, "init", "-q", "-b", "main", repo)
        git(repo, "add", "-A")
        sheet = repo / "parameters.md"
        sheet.write_text(
            "## ascii_ignore\n\n| Path | Reason |\n|---|---|\n| vendor/ | imported |\n"
        )
        old = os.getcwd()
        os.chdir(repo)
        saved = (core_ci.PARAMETERS, core_ci.tracked)
        core_ci.PARAMETERS = sheet
        core_ci.tracked = lambda: ["vendor/a.txt", "b.txt"]
        try:
            self.assertEqual(core_ci.cmd_ascii([]), 1)  # b.txt still fails
            core_ci.tracked = lambda: ["vendor/a.txt"]
            self.assertEqual(core_ci.cmd_ascii([]), 0)
            sheet.write_text("")
            self.assertEqual(core_ci.cmd_ascii([]), 1)  # nothing declared: unchanged
        finally:
            os.chdir(old)
            core_ci.PARAMETERS, core_ci.tracked = saved


if __name__ == "__main__":
    unittest.main()
