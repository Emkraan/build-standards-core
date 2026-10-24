"""The overlay scripts read the public core with no account: plain git over HTTPS when gh is absent or
not signed in."""

import os
import stat
import subprocess
import unittest

from support import Work, load

ch = load("corehash_public", "templates/overlay/scripts/corehash.py")

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_ENV)
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


class PublicAccess(Work):
    def setUp(self):
        super().setUp()
        src = self.dir / "src"
        src.mkdir()
        git(src, "init", "-q", "-b", "main")
        for tag in ("v0.9.0", "v1.0.0", "v1.0.10", "nightly"):
            (src / "VERSION").write_text(tag + "\n")
            git(src, "add", "-A")
            git(src, "commit", "-q", "-m", f"chore: {tag}")
            git(src, "tag", tag)
        base = self.dir / "host"
        (base / "owner").mkdir(parents=True)
        git(self.dir, "clone", "-q", "--bare", str(src), str(base / "owner" / "core.git"))
        # A gh that always fails, first on PATH, so the git fallback is what is under test.
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "gh"
        fake.write_text("#!/bin/sh\necho 'not signed in' >&2\nexit 1\n")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.env = {"CORE_GIT_BASE": f"file://{base}", "PATH": f"{bin_dir}:{os.environ['PATH']}"}
        self.old = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.addCleanup(self.restore)

    def restore(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_latest_tag_without_gh_is_the_highest_semver_tag(self):
        self.assertEqual(ch.latest_tag("owner/core"), "v1.0.10")

    def test_clone_without_gh_checks_out_the_ref(self):
        dest = self.dir / "core"
        ch.clone("owner/core", dest, "v1.0.0")
        self.assertEqual((dest / "VERSION").read_text().strip(), "v1.0.0")

    def test_a_missing_ref_fails_with_one_plain_message(self):
        with self.assertRaises(SystemExit) as cm:
            ch.clone("owner/core", self.dir / "core2", "v9.9.9")
        self.assertIn("The core is public", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
