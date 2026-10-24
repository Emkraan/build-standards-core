import unittest

from support import Work, load, sh

ops = load("ops_center_mod", "hermes/ops_center.py")

SYNC = (
    "import sys,pathlib\npathlib.Path('standards.lock').write_text('ref=' + sys.argv[1] + '\\n')\n"
)
CHECK = (
    "import pathlib\nref = pathlib.Path('standards.lock').read_text().split('=')[1].strip()\n"
    "bad = pathlib.Path('fail-on.txt').read_text().split()\nraise SystemExit(1 if ref in bad else 0)\n"
)


class Gate(Work):
    def make(self, fail_on=""):
        self.clone = self.dir / "app"
        ov = self.clone / "standards-overlay"
        (ov / "scripts").mkdir(parents=True)
        (ov / "standards.lock").write_text("ref=v1\n")
        (ov / "fail-on.txt").write_text(fail_on)
        (ov / "scripts" / "sync-core.py").write_text(SYNC)
        (ov / "scripts" / "check-core-sync.py").write_text(CHECK)
        for cmd in (
            ["init", "-q", "-b", "main"],
            ["config", "user.name", "t"],
            ["config", "user.email", "t@example.com"],
            ["add", "-A"],
            ["commit", "-q", "-m", "init"],
        ):
            sh(["git", *cmd], cwd=self.clone)
        self.cfg = {"repo": "o/app", "path": str(self.clone), "overlay": "standards-overlay"}
        self.state = self.dir / "state"

    def head(self):
        return sh(["git", "rev-parse", "main"], cwd=self.clone)[1]

    def pin(self):
        return ops.pin_at(self.clone, "main", "standards-overlay", sh)

    def apply(self, check=False):
        return ops.apply(self.cfg, "v2", sh, self.state, check)

    def test_pass_applies_and_commits(self):
        self.make()
        before = self.head()
        r = self.apply()
        self.assertEqual(r["status"], "applied")
        self.assertEqual(self.pin(), "v2")
        self.assertNotEqual(self.head(), before)
        self.assertFalse((self.dir / "app.core-gate").exists())
        self.assertEqual(sh(["git", "status", "--porcelain"], cwd=self.clone)[1], "")

    def test_current_pin_is_a_noop(self):
        self.make()
        self.cfg_latest = "v1"
        before = self.head()
        self.assertEqual(ops.apply(self.cfg, "v1", sh, self.state)["status"], "current")
        self.assertEqual(self.head(), before)

    def test_fail_on_current_pin_holds_and_blames_the_consumer(self):
        self.make(fail_on="v1")
        before = self.head()
        r = self.apply()
        self.assertEqual((r["status"], r["kind"]), ("held", "gate-current-pin"))
        self.assertIn("consumer's own failure", r["message"])
        self.assertEqual(self.head(), before)
        self.assertEqual(self.pin(), "v1")

    def test_fail_after_sync_rolls_back(self):
        self.make(fail_on="v2")
        before = self.head()
        r = self.apply()
        self.assertEqual((r["status"], r["kind"]), ("failed", "gate-after-sync"))
        self.assertEqual(self.head(), before)
        self.assertEqual(self.pin(), "v1")
        self.assertFalse((self.dir / "app.core-gate").exists())
        self.assertEqual(sh(["git", "status", "--porcelain"], cwd=self.clone)[1], "")

    def test_failure_reported_once_per_kind(self):
        self.make(fail_on="v2")
        self.assertTrue(self.apply()["report"])
        self.assertFalse(self.apply()["report"])
        (self.clone / "standards-overlay" / "fail-on.txt").write_text("")
        sh(["git", "commit", "-qam", "fix"], cwd=self.clone)
        self.assertEqual(self.apply()["status"], "applied")
        self.assertEqual(ops.State(self.state, "o/app").last(), "")  # a clean run clears it

    def test_uncommitted_work_cannot_decide_the_verdict(self):
        self.make()
        (self.clone / "standards-overlay" / "fail-on.txt").write_text("v1 v2")  # uncommitted
        self.assertEqual(self.apply()["status"], "applied")

    def test_check_mode_changes_nothing(self):
        self.make()
        before = self.head()
        self.assertEqual(self.apply(check=True)["status"], "would")
        self.assertEqual(self.head(), before)

    def test_own_verify_command_is_part_of_the_gate(self):
        self.make()
        sheet = self.clone / "standards-overlay" / "standards-local"
        sheet.mkdir()
        (sheet / "parameters.md").write_text(
            '| Parameter | Value |\n|---|---|\n| Gate verify | `python3 -c "raise SystemExit(1)"` |\n'
        )
        sh(["git", "add", "-A"], cwd=self.clone)
        sh(["git", "commit", "-qm", "params"], cwd=self.clone)
        self.assertEqual(self.apply()["kind"], "gate-current-pin")
        self.assertEqual(
            ops.gate_params(self.clone / "standards-overlay")["verify"],
            'python3 -c "raise SystemExit(1)"',
        )


class GatedRepo(Gate):
    """An ops center whose source is a repo with its own CI gate: the release lands as a pull request."""

    def make_remote(self, checks_rc=0, merge_rc=0):
        self.make()
        (self.clone / "standards-overlay" / "scripts" / "core-ci.py").write_text("")
        (self.clone / "standards-overlay" / "scripts" / "merge-pr.py").write_text("")
        sh(["git", "add", "-A"], cwd=self.clone)
        sh(["git", "commit", "-qm", "scripts"], cwd=self.clone)
        self.bare = self.dir / "remote.git"
        sh(["git", "clone", "-q", "--bare", self.clone, self.bare])
        sh(["git", "remote", "add", "origin", self.bare], cwd=self.clone)
        sh(["git", "fetch", "-q", "origin"], cwd=self.clone)
        self.cfg["apply_via"] = "pr"
        self.checks_rc, self.merge_rc = checks_rc, merge_rc
        self.calls = []
        self.echoes = []
        self.pr = None

    def fake(self, cmd, cwd=None, timeout=60, echo=None):
        cmd = [str(x) for x in cmd]
        self.calls.append(cmd)
        self.echoes.append(echo)
        if cmd[0] == "gh":
            if cmd[1:3] == ["pr", "create"]:
                self.pr = {"number": "5", "head": cmd[cmd.index("--head") + 1]}
                return 0, "https://example.invalid/pull/5"
            if cmd[1:3] == ["pr", "view"]:
                sha = sh(["git", "rev-parse", self.pr["head"]], cwd=self.bare)[1]
                return 0, f"5\t{sha}"
            if cmd[1:3] == ["pr", "close"]:
                return 0, ""
            return 1, "unexpected gh call"
        if len(cmd) > 1 and cmd[1].endswith("core-ci.py"):
            return (
                self.checks_rc,
                "wait-checks: timed out" if self.checks_rc else "wait-checks: 3 check(s) green",
            )
        if len(cmd) > 1 and cmd[1].endswith("merge-pr.py"):
            if self.merge_rc == 0:
                sha = cmd[cmd.index("--match-head-commit") + 1]
                sh(["git", "update-ref", "refs/heads/main", sha], cwd=self.bare)
            return (
                self.merge_rc,
                "merge-pr: merged" if self.merge_rc == 0 else "merge-pr: merge refused",
            )
        return sh(cmd, cwd=cwd, timeout=timeout)

    def remote_pin(self):
        return ops.pin_at(self.bare, "main", "standards-overlay", sh)

    def branches(self):
        return sh(["git", "branch", "--list"], cwd=self.bare)[1]

    def test_pr_path_merges_through_the_repo_checks_and_never_writes_the_checkout(self):
        self.make_remote()
        before = self.head()
        r = ops.apply(self.cfg, "v2", self.fake, self.state)
        self.assertEqual(r["status"], "applied", r)
        self.assertIn("by pull request", r["message"])
        self.assertEqual(self.remote_pin(), "v2")
        self.assertEqual(self.head(), before)  # the deploy checkout is never written
        self.assertEqual(self.pin(), "v1")
        wait = [c for c in self.calls if len(c) > 1 and c[1].endswith("core-ci.py")]
        merge = [c for c in self.calls if len(c) > 1 and c[1].endswith("merge-pr.py")]
        self.assertEqual(wait[0][2], "wait-checks")
        self.assertIn("--match-head-commit", merge[0])
        self.assertEqual(wait[0][3], merge[0][merge[0].index("--match-head-commit") + 1])

    def test_failed_checks_close_the_pr_delete_the_branch_and_keep_the_pin(self):
        self.make_remote(checks_rc=1)
        r = ops.apply(self.cfg, "v2", self.fake, self.state)
        self.assertEqual((r["status"], r["kind"]), ("failed", "pr-checks"))
        self.assertTrue(r["report"])
        self.assertEqual(self.remote_pin(), "v1")
        self.assertNotIn("chore/core-v2", self.branches())
        self.assertTrue(any(c[:3] == ["gh", "pr", "close"] for c in self.calls))
        self.assertFalse(any(c[1].endswith("merge-pr.py") for c in self.calls if len(c) > 1))
        self.assertFalse(
            ops.apply(self.cfg, "v2", self.fake, self.state)["report"]
        )  # once per kind

    def test_refused_merge_rolls_back(self):
        self.make_remote(merge_rc=2)
        r = ops.apply(self.cfg, "v2", self.fake, self.state)
        self.assertEqual((r["status"], r["kind"]), ("failed", "pr-merge"))
        self.assertEqual(self.remote_pin(), "v1")
        self.assertNotIn("chore/core-v2", self.branches())

    def test_detected_from_a_pre_push_guard(self):
        self.make_remote()
        del self.cfg["apply_via"]
        sh(
            ["git", "config", "core.hooksPath", ".git/hooks"], cwd=self.clone
        )  # not the machine's global hooks
        hook = self.clone / ".git" / "hooks" / "pre-push"
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)
        self.assertEqual(ops.apply_via(self.cfg, self.clone, "main", self.fake), "pr")
        hook.unlink()
        self.calls.clear()

        def fake(cmd, cwd=None, timeout=60):
            return (0, "[]") if cmd[0] == "gh" else self.fake(cmd, cwd, timeout)

        self.assertEqual(ops.apply_via(self.cfg, self.clone, "main", fake), "direct")


class NodeModules(Work):
    def test_overlay_subfolder_node_modules_is_linked_too(self):
        clone, wt = self.dir / "app", self.dir / "wt"
        (clone / "node_modules").mkdir(parents=True)
        (clone / "ui" / "node_modules").mkdir(parents=True)
        (wt / "ui").mkdir(parents=True)
        ops.link_node_modules(clone, wt, "ui")
        self.assertTrue((wt / "node_modules").is_symlink())
        self.assertEqual(
            (wt / "ui" / "node_modules").resolve(), (clone / "ui" / "node_modules").resolve()
        )
        ops.link_node_modules(clone, wt, "ui")  # idempotent


if __name__ == "__main__":
    unittest.main()
