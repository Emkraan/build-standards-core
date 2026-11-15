"""Issue #118: the nightly pull moves a core clone left on a clean, pushed branch back to main, and
never touches one whose work could be lost. Fixtures live under .test-work, never /tmp."""

import os
import pathlib
import subprocess
import unittest

from support import Work, load

nightly = load("nightly_branch", "hermes/nightly.py")
GIT_ENV = {
    "GIT_AUTHOR_NAME": "T",
    "GIT_COMMITTER_NAME": "T",
    "GIT_AUTHOR_EMAIL": "1+t@users.noreply.github.com",
    "GIT_COMMITTER_EMAIL": "1+t@users.noreply.github.com",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo, *args):
    r = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, env={**os.environ, **GIT_ENV}
    )
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def commit(repo, msg, name, text):
    (pathlib.Path(repo) / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


class LeaveBranch(Work):
    def make(self):
        origin = self.dir / "origin.git"
        git(self.dir, "init", "-q", "--bare", "-b", "main", str(origin))
        self.seed = self.dir / "seed"
        git(self.dir, "clone", "-q", str(origin), str(self.seed))
        git(self.seed, "checkout", "-q", "-b", "main")
        commit(self.seed, "feat: one", "a.txt", "1\n")
        git(self.seed, "push", "-q", "origin", "main")
        self.core = self.dir / "core"
        git(self.dir, "clone", "-q", str(origin), str(self.core))
        git(self.core, "checkout", "-q", "-b", "feat/x")
        commit(self.core, "feat: x", "x.txt", "x\n")
        git(self.core, "push", "-q", "-u", "origin", "feat/x")
        # main moves on in origin, so the pull has something to apply.
        self.new_tip = commit(self.seed, "feat: two", "b.txt", "2\n")
        git(self.seed, "push", "-q", "origin", "main")

    def run_pull(self, check=False):
        run = nightly.Run(
            {"core": str(self.core), "hermes_home": ".", "apply": {}, "ui_consumers": []}, check, 0
        )
        run.latest_tag = lambda: "v1.0.0"
        return run, run.pull()

    def head(self):
        return git(self.core, "rev-parse", "HEAD")

    def branch(self):
        return git(self.core, "rev-parse", "--abbrev-ref", "HEAD")

    def assert_untouched_with_recovery(self, run, ok, head, branch):
        self.assertFalse(ok)
        self.assertEqual(self.head(), head)
        self.assertEqual(self.branch(), branch)
        self.assertEqual(len(run.problems), 1)
        self.assertIn(f"git -C {self.core} checkout main", run.problems[0])

    def test_clean_pushed_branch_is_moved_to_main_and_pulled(self):
        self.make()
        run, ok = self.run_pull()
        self.assertTrue(ok, run.problems)
        self.assertEqual(self.branch(), "main")
        self.assertEqual(self.head(), self.new_tip)
        moved = [i for i in run.info if "checked out main" in i]
        self.assertEqual(len(moved), 1)
        self.assertIn("feat/x", moved[0])

    def test_untracked_files_do_not_block_the_move(self):
        self.make()
        (self.core / "scratch.txt").write_text("untracked\n")
        run, ok = self.run_pull()
        self.assertTrue(ok, run.problems)
        self.assertEqual(self.branch(), "main")
        self.assertTrue((self.core / "scratch.txt").exists())

    def test_dirty_tree_fails_with_the_recovery_command_and_is_not_touched(self):
        self.make()
        (self.core / "x.txt").write_text("local edit\n")
        head = self.head()
        run, ok = self.run_pull()
        self.assert_untouched_with_recovery(run, ok, head, "feat/x")
        self.assertEqual((self.core / "x.txt").read_text(), "local edit\n")

    def test_unpushed_commit_fails_with_the_recovery_command_and_keeps_it(self):
        self.make()
        head = commit(self.core, "feat: local only", "y.txt", "y\n")
        run, ok = self.run_pull()
        self.assert_untouched_with_recovery(run, ok, head, "feat/x")
        self.assertIn("unpushed", run.problems[0])

    def test_branch_without_upstream_fails_rather_than_guess(self):
        self.make()
        git(self.core, "branch", "--unset-upstream")
        head = self.head()
        run, ok = self.run_pull()
        self.assert_untouched_with_recovery(run, ok, head, "feat/x")
        self.assertIn("no upstream", run.problems[0])

    def test_detached_head_fails_with_the_recovery_command(self):
        self.make()
        git(self.core, "checkout", "-q", "--detach")
        head = self.head()
        run, ok = self.run_pull()
        self.assert_untouched_with_recovery(run, ok, head, "HEAD")
        self.assertIn("detached", run.problems[0])

    def test_check_mode_changes_nothing(self):
        self.make()
        head = self.head()
        run, ok = self.run_pull(check=True)
        self.assertTrue(ok)
        self.assertEqual(self.head(), head)
        self.assertEqual(self.branch(), "feat/x")
        self.assertIn("would check out main", " ".join(run.info))

    def test_clone_on_main_is_pulled_as_before(self):
        self.make()
        git(self.core, "checkout", "-q", "main")
        run, ok = self.run_pull()
        self.assertTrue(ok, run.problems)
        self.assertEqual(self.head(), self.new_tip)
        self.assertEqual([i for i in run.info if "checked out main" in i], [])


if __name__ == "__main__":
    unittest.main()
