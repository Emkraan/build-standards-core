"""Tests for the v0.58.0 consumer report items: history-rewrite recovery, pinned-release checkout by
tag, vendored release detection, push guards on an ops center, the per-PR changelog check, the
fail-closed core changelog check and the report screenshot URL allowance. Fixtures live under
.test-work, never /tmp."""

import json
import os
import pathlib
import shutil
import sys
import unittest

from support import ROOT, Work, load, sh

nightly = load("nightly_items", "hermes/nightly.py")
ops = load("ops_center_items", "hermes/ops_center.py")
SCRIPTS = ROOT / "templates" / "overlay" / "scripts"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "T",
    "GIT_COMMITTER_NAME": "T",
    "GIT_AUTHOR_EMAIL": "1+t@users.noreply.github.com",
    "GIT_COMMITTER_EMAIL": "1+t@users.noreply.github.com",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo, *args):
    import subprocess

    r = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, env={**os.environ, **GIT_ENV}
    )
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def commit(repo, msg, files):
    for k, v in files.items():
        p = pathlib.Path(repo) / k
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(v)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


class HistoryRewrite(Work):
    """G-001: a clean clone with no merge base with origin/main is reset; a dirty one is not."""

    def make(self):
        self.origin = self.dir / "origin.git"
        git(self.dir, "init", "-q", "--bare", "-b", "main", str(self.origin))
        seed = self.dir / "seed"
        git(self.dir, "clone", "-q", str(self.origin), str(seed))
        git(seed, "checkout", "-q", "-b", "main")
        commit(seed, "feat: one", {"a.txt": "1\n"})
        git(seed, "tag", "v1.0.0")
        git(seed, "push", "-q", "origin", "main", "--tags")
        self.core = self.dir / "core"
        git(self.dir, "clone", "-q", str(self.origin), str(self.core))
        # Rewrite the origin: a new root commit, the same tag moved onto it.
        git(seed, "checkout", "-q", "--orphan", "rewritten")
        commit(seed, "feat: one (rewritten)", {"a.txt": "1\n", "b.txt": "2\n"})
        git(seed, "tag", "-f", "v1.0.0")
        git(seed, "push", "-q", "-f", "origin", "rewritten:main")
        git(seed, "push", "-q", "-f", "origin", "v1.0.0")
        self.new_tip = git(seed, "rev-parse", "HEAD")
        self.old_tip = git(self.core, "rev-parse", "HEAD")

    def run_pull(self, check=False):
        run = nightly.Run(
            {"core": str(self.core), "hermes_home": ".", "apply": {}, "ui_consumers": []}, check, 0
        )
        run.latest_tag = lambda: "v1.0.0"
        return run, run.pull()

    def test_clean_clone_is_reset_with_one_line_and_a_backup(self):
        self.make()
        run, ok = self.run_pull()
        self.assertTrue(ok, run.problems)
        self.assertEqual(git(self.core, "rev-parse", "HEAD"), self.new_tip)
        rewrites = [i for i in run.info if "history rewritten" in i]
        self.assertEqual(len(rewrites), 1)
        backup = f"core-before-rewrite-{self.old_tip[:7]}"
        self.assertIn(backup, rewrites[0])
        self.assertEqual(git(self.core, "rev-parse", backup), self.old_tip)
        self.assertEqual(git(self.core, "rev-parse", "v1.0.0"), self.new_tip)  # tags forced too

    def test_dirty_clone_is_left_alone_with_the_recovery_command(self):
        self.make()
        (self.core / "a.txt").write_text("local edit\n")
        run, ok = self.run_pull()
        self.assertFalse(ok)
        self.assertEqual(git(self.core, "rev-parse", "HEAD"), self.old_tip)
        self.assertEqual(len(run.problems), 1)
        self.assertIn("reset --hard origin/main", run.problems[0])
        self.assertIn("fetch --tags --force origin", run.problems[0])

    def test_check_mode_changes_nothing(self):
        self.make()
        run, ok = self.run_pull(check=True)
        self.assertTrue(ok)
        self.assertEqual(git(self.core, "rev-parse", "HEAD"), self.old_tip)
        self.assertIn("would reset", " ".join(run.info))


class PinnedCheckoutByTag(Work):
    """G-001: the overlay lock's commit is a hint; a rewritten commit id falls back to the tag."""

    def test_commit_then_tag_then_refusal(self):
        corehash = load("corehash_items", "templates/overlay/scripts/corehash.py")
        repo = self.dir / "core"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        sha = commit(repo, "feat: a", {"standards/a.md": "a\n"})
        git(repo, "tag", "v1.0.0")
        self.assertEqual(corehash.checkout_pinned(repo, {"ref": "v1.0.0", "commit": sha}), "commit")
        note = corehash.checkout_pinned(repo, {"ref": "v1.0.0", "commit": "f" * 40})
        self.assertIn("history rewritten", note)
        self.assertIn("v1.0.0", note)
        with self.assertRaises(SystemExit):
            corehash.checkout_pinned(repo, {"ref": "v9.9.9", "commit": "f" * 40})


class VendoredRelease(Work):
    """G-025: the record holds the release the copy carries, never just the newest."""

    def setUp(self):
        super().setUp()
        os.environ["CORE_VENDORED_DIR"] = str(self.dir / "vendored")
        self.addCleanup(os.environ.pop, "CORE_VENDORED_DIR")
        self.core = self.dir / "core"
        self.core.mkdir()
        git(self.core, "init", "-q", "-b", "main")
        commit(self.core, "feat: a", {"standards/a.md": "one\n"})
        git(self.core, "tag", "v1.0.0")
        commit(self.core, "feat: b", {"standards/a.md": "two\n", "kit/src/x.ts": "x\n"})
        git(self.core, "tag", "v1.1.0")
        self.run = nightly.Run(
            {"core": str(self.core), "hermes_home": ".", "apply": {}, "ui_consumers": []}, False, 0
        )
        self.rec = self.dir / "vendored" / "o__r.json"

    def test_source_hash_at_a_tag_matches_the_working_tree(self):
        self.assertEqual(
            nightly.source_hash_at(self.core, "v1.1.0"), nightly.source_hash(self.core)
        )
        self.assertNotEqual(
            nightly.source_hash_at(self.core, "v1.0.0"), nightly.source_hash(self.core)
        )
        self.assertEqual(nightly.source_hash_at(self.core, "v0.0.0"), "")

    def test_pin_file_names_the_carried_release_and_status_says_behind(self):
        pin = self.dir / "pin.txt"
        pin.write_text("vendored from v1.0.0\n")
        self.run.ui_vendored({"repo": "o/r", "path": str(self.dir), "pin": str(pin)}, "v1.1.0")
        rec = json.loads(self.rec.read_text())
        self.assertEqual((rec["release"], rec["found_by"], rec["behind"]), ("v1.0.0", "pin", True))
        self.assertEqual(rec["source_hash"], nightly.source_hash_at(self.core, "v1.0.0"))
        rc, out = sh([sys.executable, SCRIPTS / "core-status.py", "--vendored", "o/r"])
        self.assertEqual(rc, 3)
        self.assertIn("behind (core is v1.1.0)", out)
        self.run.info.clear()
        self.run.ui_vendored({"repo": "o/r", "path": str(self.dir), "pin": str(pin)}, "v1.1.0")
        self.assertEqual(self.run.info, [])  # unchanged record, no output

    def test_recorded_source_hash_is_matched_against_releases(self):
        self.rec.parent.mkdir(parents=True)
        # An old record that claimed the newest release; the hash says the copy is v1.0.0.
        self.rec.write_text(
            json.dumps(
                {"release": "v1.1.0", "source_hash": nightly.source_hash_at(self.core, "v1.0.0")}
            )
        )
        self.run.ui_vendored({"repo": "o/r", "path": str(self.dir)}, "v1.1.0")
        rec = json.loads(self.rec.read_text())
        self.assertEqual(
            (rec["release"], rec["found_by"], rec["behind"]), ("v1.0.0", "content hash", True)
        )

    def test_unknown_release_is_a_problem_not_a_guess(self):
        self.run.ui_vendored({"repo": "o/r", "path": str(self.dir)}, "v1.1.0")
        self.assertFalse(self.rec.exists())
        self.assertIn("unknown", self.run.problems[0])

    def test_report_only_vendored_entry_still_gets_its_record(self):
        # v0.59.0 (#117 G-031): the vendored record only reads and writes on this machine, so a
        # report-only vendored entry gets it too; other report-only entries are still not applied.
        entry = {"repo": "o/r", "mode": "vendored", "apply": False}
        run = nightly.Run(
            {
                "core": ".",
                "hermes_home": ".",
                "apply": dict(nightly.APPLY_DEFAULTS),
                "ui_consumers": [entry, {"repo": "o/o", "mode": "ops-center", "apply": False}],
            },
            True,
            0,
        )
        run.latest_tag = lambda: "v9"
        seen = []
        run.ui_vendored = lambda c, latest: seen.append(c)
        run.ui_ops_center = lambda c, latest: seen.append(c)
        run.ui()
        self.assertEqual(seen, [entry])


class PushGuard(Work):
    """G-005: a pre-push hook that refuses the apply is named in the failure line and by setup."""

    def make(self):
        self.remote = self.dir / "remote.git"
        git(self.dir, "init", "-q", "--bare", "-b", "main", str(self.remote))
        self.clone = self.dir / "app"
        ov = self.clone / "standards-overlay"
        (ov / "scripts").mkdir(parents=True)
        (ov / "standards.lock").write_text("ref=v1\n")
        (ov / "scripts" / "sync-core.py").write_text(
            "import sys,pathlib\npathlib.Path('standards.lock').write_text('ref=' + sys.argv[1] + '\\n')\n"
        )
        hooks = self.clone / ".githooks"
        hooks.mkdir()
        hook = hooks / "pre-push"
        hook.write_text('#!/bin/sh\necho "direct pushes to main are blocked" >&2\nexit 1\n')
        hook.chmod(0o755)
        git(self.clone, "init", "-q", "-b", "main")
        git(self.clone, "config", "user.name", "t")
        git(self.clone, "config", "user.email", "t@example.com")
        commit(self.clone, "init", {})  # the hook is committed, as a repo's guard is
        git(self.clone, "remote", "add", "origin", str(self.remote))
        git(self.clone, "push", "-q", "origin", "main")
        git(self.clone, "config", "core.hooksPath", ".githooks")

    def test_hook_found_and_named_in_the_failure_line(self):
        self.make()
        self.assertEqual(
            ops.local_push_guard(self.clone, sh), str(pathlib.Path(".githooks") / "pre-push")
        )
        before = git(self.clone, "rev-parse", "main")
        r = ops.apply(
            {
                "repo": "o/app",
                "path": str(self.clone),
                "overlay": "standards-overlay",
                "apply_via": "direct",
            },
            "v2",
            sh,
            self.dir / "state",
        )
        self.assertEqual((r["status"], r["kind"]), ("failed", "push"))
        self.assertIn("pre-push hook .githooks/pre-push", r["message"])
        self.assertIn("register the repo as workflow", r["message"])
        self.assertEqual(git(self.clone, "rev-parse", "main"), before)

    def test_setup_says_which_mode_fits(self):
        self.make()
        setup = load("setup_items", "hermes/setup.py")

        def fake(cmd, cwd=None, timeout=600):
            if cmd[0] == "gh":
                return 1, "not found"
            return sh(cmd, cwd=cwd, timeout=timeout)

        notes = setup.push_guards(
            [
                {"repo": "o/app", "mode": "ops-center", "path": str(self.clone)},
                {"repo": "o/wf", "mode": "workflow"},
            ],
            fake,
        )
        self.assertEqual(len(notes), 1)
        self.assertIn("overlay folder", notes[0])
        self.assertIn("workflow", notes[0])

    def test_remote_ruleset_is_described(self):
        def fake(cmd, cwd=None, timeout=600):
            if cmd[:2] == ["gh", "api"] and "/rules/branches/" in cmd[2]:
                return 0, json.dumps([{"type": "pull_request"}, {"type": "deletion"}])
            return 1, ""

        self.assertIn("ruleset", ops.remote_push_guard("o/app", "main", fake))
        self.assertEqual(ops.remote_push_guard("o/app", "main", lambda *a, **k: (1, "")), "")
        self.assertIn("as workflow", ops.guard_advice("o/app", "main", "", "an active ruleset"))


class ChangelogEntries(Work):
    """P-001: one entry per pull request, fixed heading, newest first, append-only."""

    def setUp(self):
        super().setUp()
        self.repo = self.dir / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        (self.repo / "standards-local").mkdir()
        shutil.copyfile(SCRIPTS / "core-ci.py", self.repo / "scripts" / "core-ci.py")
        (self.repo / "standards-local" / "parameters.md").write_text(
            "| Parameter | Value | Used by |\n|---|---|---|\n| Changelog entries | per-pr | x |\n"
        )
        git(self.repo, "init", "-q", "-b", "main")
        self.log = "# Changelog\n\n## 2026-10-01 (v1.0.0)\n\n- first\n"
        self.base = commit(
            self.repo, "chore: start", {"CHANGELOG.md": self.log, "app.py": "x = 1\n"}
        )

    def ci(self, head, base=None, env=None):
        old = dict(os.environ)
        os.environ.pop("CI", None)
        os.environ.pop("GITHUB_ACTIONS", None)
        os.environ.update(env or {})
        try:
            return sh(
                [
                    sys.executable,
                    self.repo / "scripts" / "core-ci.py",
                    "changelog-entries",
                    base or self.base,
                    head,
                ],
                cwd=self.repo,
            )
        finally:
            os.environ.clear()
            os.environ.update(old)

    def branch(self, files):
        git(self.repo, "checkout", "-q", "-B", "pr", self.base)
        return commit(self.repo, "feat: change", files)

    def test_one_new_entry_on_top_passes(self):
        log = self.log.replace(
            "## 2026-10-01", "## 2026-10-20 (v1.1.0, a thing)\n\n- added a thing\n\n## 2026-10-01"
        )
        self.assertEqual(self.ci(self.branch({"app.py": "x = 2\n", "CHANGELOG.md": log}))[0], 0)

    def test_no_entry_fails(self):
        rc, out = self.ci(self.branch({"app.py": "x = 2\n"}))
        self.assertEqual(rc, 1)
        self.assertIn("exactly one entry", out)

    def test_two_entries_fail(self):
        log = self.log.replace(
            "## 2026-10-01",
            "## 2026-10-20 (v1.2.0)\n\n- b\n\n## 2026-10-19 (v1.1.0)\n\n- a\n\n## 2026-10-01",
        )
        self.assertEqual(self.ci(self.branch({"CHANGELOG.md": log}))[0], 1)

    def test_editing_an_older_entry_fails(self):
        log = self.log.replace("- first", "- first, reworded").replace(
            "## 2026-10-01", "## 2026-10-20 (v1.1.0)\n\n- new\n\n## 2026-10-01"
        )
        rc, out = self.ci(self.branch({"CHANGELOG.md": log}))
        self.assertEqual(rc, 1)
        self.assertIn("append-only", out)

    def test_bad_heading_and_order_fail(self):
        bad = self.log.replace("## 2026-10-01", "## Next release\n\n- new\n\n## 2026-10-01")
        self.assertIn("is not", self.ci(self.branch({"CHANGELOG.md": bad}))[1])
        older = self.log.replace(
            "## 2026-10-01", "## 2026-09-01 (no version change)\n\n- new\n\n## 2026-10-01"
        )
        self.assertIn("newest first", self.ci(self.branch({"CHANGELOG.md": older}))[1])

    def test_overlay_only_sync_is_exempt(self):
        head = self.branch(
            {
                "standards.lock": "ref=v2\n",
                "kit-core/a.ts": "x\n",
                "scripts/core-ci.py": (SCRIPTS / "core-ci.py").read_text() + "\n",
            }
        )
        rc, out = self.ci(head)
        self.assertEqual(rc, 0, out)
        self.assertIn("overlay-only sync", out)

    def test_unknown_base_fails_in_ci_and_skips_locally(self):
        head = self.branch({"app.py": "x = 3\n"})
        self.assertEqual(self.ci(head, base="e" * 40)[0], 0)
        rc, out = self.ci(head, base="e" * 40, env={"CI": "true"})
        self.assertEqual(rc, 1)
        self.assertIn("failing closed", out)

    def test_off_without_the_parameter(self):
        (self.repo / "standards-local" / "parameters.md").write_text(
            "| Parameter | Value |\n|---|---|\n"
        )
        head = self.branch({"app.py": "x = 4\n"})
        self.assertIn("skip", self.ci(head)[1])


class CoreChangelogFailsClosed(Work):
    """P-001: the core's own check fails on an unknown base in CI and stays usable locally."""

    def test_unknown_base(self):
        script = ROOT / "checks" / "check-changelog.py"
        env = {k: v for k, v in os.environ.items() if k not in ("CI", "GITHUB_ACTIONS")}
        import subprocess

        local = subprocess.run(
            [sys.executable, str(script), "refs/heads/no-such-base"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(local.returncode, 0)
        self.assertIn("skipped (local run)", local.stdout)
        ci = subprocess.run(
            [sys.executable, str(script), "refs/heads/no-such-base"],
            cwd=ROOT,
            env={**env, "CI": "true"},
            capture_output=True,
            text=True,
        )
        self.assertEqual(ci.returncode, 1)
        self.assertIn("failing closed", ci.stdout)


class ReportScreenshotUrl(Work):
    """G-027: in file mode the login in a raw gist image URL is allowed; elsewhere it still fails."""

    def test_raw_gist_login_allowed_only_in_that_form(self):
        deny = self.dir / "deny.txt"
        deny.write_text("zebrafox\n")
        os.environ["CORE_PRIVATE_DENYLIST"] = str(deny)
        self.addCleanup(os.environ.pop, "CORE_PRIVATE_DENYLIST")
        ok, bad = self.dir / "ok.md", self.dir / "bad.md"
        ok.write_text(
            "![x](https://gist.githubusercontent.com/zebrafox/0123456789abcdef0123/raw/home-dark.png)\n"
        )
        bad.write_text(
            "posted by zebrafox\nhttps://gist.github.com/zebrafox/0123456789abcdef0123\n"
        )
        for script in ("check-sanitised.py", "check-consumer-neutral.py"):
            self.assertEqual(
                sh([sys.executable, ROOT / "checks" / script, "--file", ok], cwd=ROOT)[0], 0, script
            )
            self.assertEqual(
                sh([sys.executable, ROOT / "checks" / script, "--file", bad], cwd=ROOT)[0],
                1,
                script,
            )


if __name__ == "__main__":
    unittest.main()
