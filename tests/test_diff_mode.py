"""Diff mode of check-sanitised and check-consumer-neutral (ops center prerequisite P1)."""

import os
import shutil
import sys
import unittest

from support import ROOT, Work, sh

GIT = ["git", "-c", "user.name=t", "-c", "user.email=1+t@users.noreply.github.com"]


class DiffMode(Work):
    def setUp(self):
        super().setUp()
        env = self.dir / "deny.txt"
        env.write_text("acme\n")
        os.environ["CORE_PRIVATE_DENYLIST"] = str(env)
        self.addCleanup(os.environ.pop, "CORE_PRIVATE_DENYLIST")
        self.repo = self.dir / "repo"
        shutil.copytree(
            ROOT / "checks", self.repo / "checks", ignore=shutil.ignore_patterns("__pycache__")
        )
        sh(["git", "init", "-q", "-b", "main"], cwd=self.repo)
        sh(["git", "config", "user.email", "1+t@users.noreply.github.com"], cwd=self.repo)
        sh(["git", "config", "user.name", "t"], cwd=self.repo)
        (self.repo / "standards").mkdir()
        (self.repo / "CHANGELOG.md").write_text("# Changelog\n\n- the acme migration, long ago\n")
        (self.repo / "standards" / "a.md").write_text("clean\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.base = self.git("rev-parse", "HEAD")[1]

    def git(self, *a):
        return sh(GIT + list(a), cwd=self.repo)

    def run_check(self, name, *args):
        return sh([sys.executable, f"checks/{name}.py", *args], cwd=self.repo)

    def commit(self, rel, text, *flags):
        (self.repo / rel).write_text(text)
        self.git("add", "-A")
        return self.git("commit", "-q", "-m", "change", *flags)

    def test_preexisting_hit_in_changelog_does_not_fail_diff_mode(self):
        self.commit("standards/a.md", "clean\nmore clean\n")
        for name in ("check-sanitised", "check-consumer-neutral"):
            self.assertEqual(self.run_check(name, "--diff", self.base)[0], 0, name)
        # the default full-tree mode is unchanged and still sees the historical hit
        self.assertEqual(self.run_check("check-sanitised")[0], 1)

    def test_new_hit_on_added_line_fails_diff_mode(self):
        self.commit("standards/a.md", "clean\nthe acme account\n")
        for name in ("check-sanitised", "check-consumer-neutral"):
            rc, out = self.run_check(name, "--diff", self.base)
            self.assertEqual(rc, 1, name)
        self.assertIn("standards/a.md", out)

    def test_hit_added_to_changelog_fails_but_edit_beside_it_does_not(self):
        self.commit(
            "CHANGELOG.md", "# Changelog\n\n- a clean entry\n- the acme migration, long ago\n"
        )
        self.assertEqual(self.run_check("check-sanitised", "--diff", self.base)[0], 0)
        self.commit("CHANGELOG.md", "# Changelog\n\n- acme again\n- the acme migration, long ago\n")
        rc, out = self.run_check("check-sanitised", "--diff", self.base)
        self.assertEqual(rc, 1)
        self.assertIn("CHANGELOG.md,line=3", out)

    def test_staged_mode_scopes_to_the_index(self):
        (self.repo / "standards" / "a.md").write_text("clean\nthe acme account\n")
        self.git("add", "-A")
        self.assertEqual(self.run_check("check-sanitised", "--staged")[0], 1)
        self.git("reset", "-q", "--hard")
        (self.repo / "standards" / "a.md").write_text("clean\nfine\n")
        self.git("add", "-A")
        self.assertEqual(self.run_check("check-sanitised", "--staged")[0], 0)

    def test_no_verify_commit_is_blocked_by_hook_otherwise_and_caught_by_ci(self):
        self.git("config", "core.hooksPath", "checks/hooks")
        rc, out = self.commit("standards/a.md", "clean\nthe acme account\n")
        self.assertNotEqual(rc, 0, out)  # the hook stops it
        rc, out = self.commit("standards/a.md", "clean\nthe acme account\n", "--no-verify")
        self.assertEqual(rc, 0, out)  # skipping the hook gets the commit in...
        rc, out = self.run_check("check-sanitised", "--diff", self.base)
        self.assertEqual(rc, 1, out)  # ...and the CI invocation over the added lines fails it
        self.assertEqual(self.run_check("check-consumer-neutral", "--diff", self.base)[0], 1)

    def test_ci_workflow_runs_the_diff_mode(self):
        text = (ROOT / ".github/workflows/checks.yml").read_text()
        self.assertIn('check-sanitised.py --diff "$BASE"', text)
        self.assertIn('check-consumer-neutral.py --diff "$BASE"', text)
        self.assertIn("merge_group.base_sha", text)
        hook = (ROOT / "checks/hooks/pre-commit").read_text()
        self.assertIn("check-sanitised.py --staged", hook)
        self.assertIn("check-consumer-neutral.py --staged", hook)

    def test_sweep_workflow_runs_full_tree(self):
        text = (ROOT / ".github/workflows/sweep.yml").read_text()
        self.assertIn("python3 checks/check-sanitised.py\n", text)
        self.assertIn("python3 checks/check-consumer-neutral.py\n", text)
        self.assertIn("schedule:", text)


if __name__ == "__main__":
    unittest.main()
