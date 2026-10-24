"""Tests for v0.88.0: the pin-file consumer mode, run for real against a fixture remote under .test-work;
only gh is faked."""

import json
import os
import subprocess

from support import Work, load

pf = load("pin_file_v088", "hermes/pin_file.py")
NOREPLY = "1+t@users.noreply.github.com"


def git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_AUTHOR_NAME="T",
        GIT_COMMITTER_NAME="T",
        GIT_AUTHOR_EMAIL=NOREPLY,
        GIT_COMMITTER_EMAIL=NOREPLY,
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_NOSYSTEM="1",
    )
    r = subprocess.run(["git", *map(str, args)], cwd=repo, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class Pure(Work):
    def test_read_and_rewrite(self):
        text = "# pin\nCORE_VERSION=v1.0.0\n"
        self.assertEqual(pf.read_pin(text, "CORE_VERSION"), "v1.0.0")
        self.assertEqual(pf.rewrite(text, "CORE_VERSION", "v2.0.0"), "# pin\nCORE_VERSION=v2.0.0\n")
        self.assertEqual(pf.read_pin("# CORE_VERSION=v9\n", "CORE_VERSION"), "")

    def test_metrics_body(self):
        b = pf.metrics_body("x_", "r", "v1", "v2", 5)
        self.assertIn('x_core_pin_behind{repo="r",pinned="v1",latest="v2"} 1', b)
        self.assertIn('x_core_pin_last_check_timestamp_seconds{repo="r"} 5', b)

    def test_metrics_failure_is_a_line(self):
        def boom(*a, **k):
            raise OSError("refused")

        self.assertIn(
            "refused", pf.push_metrics({"url": "http://x"}, "o/r", "v1", "v1", opener=boom)
        )


class Fixture(Work):
    def setUp(self):
        super().setUp()
        self.remote = self.dir / "remote.git"
        git(self.dir, "init", "-q", "--bare", "-b", "main", self.remote)
        self.clone = self.dir / "clone"
        git(self.dir, "clone", "-q", self.remote, self.clone)
        (self.clone / "pin").mkdir()
        (self.clone / "pin" / "CORE_VERSION").write_text("# managed\nCORE_VERSION=v1.0.0\n")
        (self.clone / "gen.sh").write_text("cat pin/CORE_VERSION | shasum > SUMS\n")
        git(self.clone, "add", "-A")
        git(self.clone, "commit", "-q", "-m", "init")
        git(self.clone, "push", "-q", "origin", "HEAD:main")
        git(self.clone, "config", "user.email", NOREPLY)
        git(self.clone, "config", "user.name", "T")
        self.entry = {
            "repo": "o/r",
            "mode": "pin-file",
            "path": str(self.clone),
            "file": "pin/CORE_VERSION",
            "after": [["bash", "gen.sh"]],
            "add": ["SUMS"],
        }

    def sh(self, prs=(), calls=None):
        real = load("nightly_v088", "hermes/nightly.py").sh

        def sh(cmd, *a, **k):
            if calls is not None:
                calls.append(cmd)
            if cmd[:3] == ["gh", "pr", "list"]:
                return 0, json.dumps(list(prs))
            if cmd[:3] == ["gh", "pr", "create"]:
                return 0, "https://github.com/o/r/pull/9"
            return real(cmd, *a, **k)

        return sh

    def test_current_pin_does_nothing(self):
        info, problems = pf.apply(self.entry, "v1.0.0", self.sh())
        self.assertEqual((info, problems), ([], []))

    def test_behind_opens_a_pull_request_with_the_regenerated_files(self):
        calls = []
        info, problems = pf.apply(self.entry, "v2.0.0", self.sh(calls=calls))
        self.assertEqual(problems, [])
        self.assertIn("opened https://github.com/o/r/pull/9", info[0])
        head = "chore/core-pin-v2.0.0"
        self.assertIn("CORE_VERSION=v2.0.0", git(self.remote, "show", f"{head}:pin/CORE_VERSION"))
        self.assertTrue(git(self.remote, "show", f"{head}:SUMS"))
        self.assertEqual(
            git(self.remote, "log", "-1", "--format=%ae|%s", head),
            f"{NOREPLY}|chore(standards): bump the core pin to v2.0.0",
        )
        create = [c for c in calls if c[:3] == ["gh", "pr", "create"]][0]
        self.assertIn("--body-file", create)
        self.assertFalse((self.dir / "clone.core-pin").exists())

    def test_open_pull_request_is_reported(self):
        info, problems = pf.apply(
            self.entry, "v2.0.0", self.sh(prs=[{"url": "u", "statusCheckRollup": []}])
        )
        self.assertIn("pull request open", info[0])

    def test_check_mode_writes_nothing(self):
        info, _ = pf.apply(self.entry, "v2.0.0", self.sh(), check=True)
        self.assertIn("would open", info[0])
        self.assertEqual(git(self.remote, "branch", "--list", "chore/*"), "")

    def test_non_noreply_identity_refuses(self):
        git(self.clone, "config", "user.email", "a" + "@" + "b.example")
        _, problems = pf.apply(self.entry, "v2.0.0", self.sh())
        self.assertIn("not a GitHub noreply address", problems[0])

    def test_failed_regeneration_stops(self):
        self.entry["after"] = [["false"]]
        _, problems = pf.apply(self.entry, "v2.0.0", self.sh())
        self.assertIn("failed after the pin rewrite", problems[0])
        self.assertEqual(git(self.remote, "branch", "--list", "chore/*"), "")
