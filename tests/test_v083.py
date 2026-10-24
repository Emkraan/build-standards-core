"""Tests for v0.83.0: merge-pr.py builds the noreply squash commit itself and merges it with --rebase,
so no contributor needs an account setting. The git side runs for real against a fixture remote under
.test-work, never /tmp; only gh and the checks wait are faked."""

import json
import os
import subprocess
import sys
from unittest import mock

from support import Work, load

NOREPLY = "1+t@users.noreply.github.com"
LEAK = "me" + "@" + "work.example"  # built, so the sanitiser sees no address in this file


def git(repo, *args, email=NOREPLY):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_AUTHOR_NAME="T",
        GIT_COMMITTER_NAME="T",
        GIT_AUTHOR_EMAIL=email,
        GIT_COMMITTER_EMAIL=email,
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_NOSYSTEM="1",
    )
    r = subprocess.run(["git", *map(str, args)], cwd=repo, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class MergePr(Work):
    def setUp(self):
        super().setUp()
        self.mod = load("merge_pr_v083", "templates/overlay/scripts/merge-pr.py")
        self.remote = self.dir / "remote.git"
        git(self.dir, "init", "-q", "--bare", "-b", "main", self.remote)
        self.clone = self.dir / "clone"
        git(self.dir, "clone", "-q", self.remote, self.clone)
        (self.clone / "a.txt").write_text("a\n")
        git(self.clone, "add", "-A")
        git(self.clone, "commit", "-q", "-m", "init")
        git(self.clone, "push", "-q", "origin", "HEAD:main")

    def branch(self, files, email=LEAK, base="main"):
        git(self.clone, "switch", "-q", "-C", "feat/x", f"origin/{base}")
        for i, (name, text) in enumerate(files):
            (self.clone / name).write_text(text)
            git(self.clone, "add", "-A")
            git(self.clone, "commit", "-q", "-m", f"step {i}", email=email)
        git(self.clone, "push", "-q", "-f", "origin", "HEAD:feat/x")
        git(self.clone, "switch", "-q", "--detach")
        return git(self.remote, "rev-parse", "feat/x")

    def fake(
        self, head, rebase=True, commits=(), merged=(NOREPLY, "noreply@github.com"), calls=None
    ):
        def gh(*args):
            if calls is not None:
                calls.append(args)
            if args[:2] == ("api", "user"):
                return 0, "1\tt", ""
            if args[:2] == ("pr", "view") and "mergeCommit" in args:
                return 0, "f" * 40, ""
            if args[:2] == ("pr", "view") and "state" in args:
                return 0, "OPEN", ""
            if args[:2] == ("pr", "view"):
                return (
                    0,
                    json.dumps(
                        {
                            "number": 7,
                            "title": "feat: x",
                            "body": "Body.",
                            "headRefName": "feat/x",
                            "headRefOid": head,
                            "baseRefName": "main",
                            "isCrossRepository": False,
                            "author": {"login": "t"},
                        }
                    ),
                    "",
                )
            if args[:2] == ("api", "repos/o/r"):
                return 0, "true" if rebase else "false", ""
            if args[:2] == ("api", "--paginate"):
                return 0, "\n".join("\t".join(c) for c in commits), ""
            if args[:2] == ("pr", "merge") or args[:2] == ("api", "-X"):
                return 0, "", ""
            if args[0] == "api":
                return 0, "\t".join(merged), ""
            return 1, "", "unexpected"

        return gh

    def run_main(self, gh, *extra, checks=0):
        out, err = [], []
        with (
            mock.patch.object(self.mod, "gh", gh),
            mock.patch.object(self.mod, "REMOTE", str(self.remote)),
            mock.patch.object(self.mod, "wait_checks", lambda *a: checks),
            mock.patch.object(sys, "argv", ["merge-pr.py", "7", "-R", "o/r", *extra]),
            mock.patch(
                "builtins.print",
                lambda *a, **k: (err if k.get("file") else out).append(" ".join(map(str, a))),
            ),
        ):
            old = os.getcwd()
            os.chdir(self.clone)
            try:
                rc = self.mod.main()
            finally:
                os.chdir(old)
        return rc, "\n".join(out), "\n".join(err)

    def merges(self, calls):
        return [c for c in calls if c[:2] == ("pr", "merge")]

    def test_builds_a_noreply_squash_commit_and_merges_it_with_rebase(self):
        base = git(self.remote, "rev-parse", "main")
        head = self.branch([("b.txt", "b\n"), ("c.txt", "c\n")])
        calls = []
        rc, out, err = self.run_main(self.fake(head, calls=calls))
        self.assertEqual(rc, 0, err)
        new = git(self.remote, "rev-parse", "feat/x")
        self.assertNotEqual(new, head)
        self.assertEqual(
            git(self.remote, "log", "-1", "--format=%P|%ae|%ce|%s", new),
            f"{base}|{NOREPLY}|{NOREPLY}|feat: x (#7)",
        )
        self.assertEqual(
            git(self.remote, "rev-parse", f"{new}^{{tree}}"),
            git(self.remote, "rev-parse", f"{head}^{{tree}}"),
        )
        self.assertIn("Body.", git(self.remote, "log", "-1", "--format=%b", new))
        self.assertEqual(
            self.merges(calls),
            [("pr", "merge", "7", "-R", "o/r", "--rebase", "--match-head-commit", new)],
        )
        self.assertIn(f"pushed squash commit {new[:8]}", out)

    def test_base_moved_on_merges_the_trees(self):
        head = self.branch([("b.txt", "b\n")])
        git(self.clone, "switch", "-q", "-C", "main", "origin/main")
        (self.clone / "z.txt").write_text("z\n")
        git(self.clone, "add", "-A")
        git(self.clone, "commit", "-q", "-m", "other")
        git(self.clone, "push", "-q", "origin", "HEAD:main")
        git(self.clone, "switch", "-q", "--detach")
        rc, _, err = self.run_main(self.fake(head))
        self.assertEqual(rc, 0, err)
        files = git(self.remote, "ls-tree", "--name-only", "feat/x").split()
        self.assertEqual(sorted(files), ["a.txt", "b.txt", "z.txt"])
        self.assertEqual(
            git(self.remote, "rev-parse", "feat/x^"), git(self.remote, "rev-parse", "main")
        )

    def test_already_squashed_branch_is_not_pushed_again(self):
        head = self.branch([("b.txt", "b\n")], email=NOREPLY)
        calls = []
        rc, out, err = self.run_main(self.fake(head, calls=calls), checks=1)
        self.assertEqual(rc, 0, err)
        self.assertEqual(git(self.remote, "rev-parse", "feat/x"), head)
        self.assertNotIn("pushed", out)
        self.assertEqual(self.merges(calls)[0][-1], head)

    def test_conflict_refuses(self):
        head = self.branch([("a.txt", "branch\n")])
        git(self.clone, "switch", "-q", "-C", "main", "origin/main")
        (self.clone / "a.txt").write_text("main\n")
        git(self.clone, "commit", "-qam", "clash")
        git(self.clone, "push", "-q", "origin", "HEAD:main")
        calls = []
        rc, _, err = self.run_main(self.fake(head, calls=calls))
        self.assertEqual(rc, 2)
        self.assertIn("conflicts with main", err)
        self.assertFalse(self.merges(calls))
        self.assertEqual(git(self.remote, "rev-parse", "feat/x"), head)

    def test_failed_checks_do_not_merge(self):
        head = self.branch([("b.txt", "b\n")])
        calls = []
        rc, _, err = self.run_main(self.fake(head, calls=calls), checks=1)
        self.assertEqual(rc, 2)
        self.assertIn("did not pass", err)
        self.assertFalse(self.merges(calls))

    def test_moved_head_refuses(self):
        head = self.branch([("b.txt", "b\n")])
        rc, _, err = self.run_main(self.fake(head), "--match-head-commit", "a" * 40)
        self.assertEqual(rc, 2)
        self.assertIn("not aaaaaaaa", err)

    def test_dry_run_pushes_nothing(self):
        head = self.branch([("b.txt", "b\n")])
        rc, out, err = self.run_main(self.fake(head), "--dry-run")
        self.assertEqual(rc, 0, err)
        self.assertIn("--rebase", out)
        self.assertEqual(git(self.remote, "rev-parse", "feat/x"), head)

    def test_squash_fallback_refuses_a_leaked_commit_and_names_no_account_setting(self):
        head = self.branch([("b.txt", "b\n")])
        calls = []
        rc, _, err = self.run_main(
            self.fake(
                head, rebase=False, commits=[("a" * 40, "t", LEAK, "t", NOREPLY)], calls=calls
            )
        )
        self.assertEqual(rc, 2)
        self.assertIn("Allow rebase merging", err)
        self.assertIn("work.example", err)
        self.assertNotIn(LEAK, err)
        self.assertNotIn("Keep my email", err)
        self.assertFalse(self.merges(calls))

    def test_squash_fallback_merges_noreply_commits(self):
        head = self.branch([("b.txt", "b\n")], email=NOREPLY)
        calls = []
        rc, _, err = self.run_main(
            self.fake(
                head, rebase=False, commits=[("a" * 40, "t", NOREPLY, "", NOREPLY)], calls=calls
            )
        )
        self.assertEqual(rc, 0, err)
        self.assertIn("--squash", self.merges(calls)[0])

    def test_leak_after_merge_prints_recovery(self):
        head = self.branch([("b.txt", "b\n")])
        rc, _, err = self.run_main(self.fake(head, merged=(LEAK, "noreply@github.com")))
        self.assertEqual(rc, 1)
        self.assertIn("recovery (owner-approved history rewrite of o/r", err)
        self.assertIn("Allow rebase merging", err)
        self.assertNotIn("Keep my email", err)
