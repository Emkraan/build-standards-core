"""The overlay syncs and hashes only standards-core. kit-core, tokens-core and lint-core are the
consumer's own code after the v2.0.0 narrowing (issues 257 B.3 and 264). Fixtures live under
.test-work, never /tmp."""

import os
import shutil
import subprocess
import sys

from support import Work, load
from test_v082 import GIT_ENV, SCRIPTS, TEMPLATES, git

OWN = ("kit-core", "tokens-core", "lint-core")


class HashScope(Work):
    def setUp(self):
        super().setUp()
        self.ch = load("corehash_own", "templates/overlay/scripts/corehash.py")

    def test_sync_map_and_hash_cover_standards_only(self):
        self.assertEqual(self.ch.SYNC_MAP, (("standards", "standards-core"),))
        self.assertEqual(self.ch.COPIES, ("standards-core",))
        self.assertEqual(set(self.ch.FORMER_COPIES), set(OWN))

    def test_hash_ignores_edits_to_own_copies_and_sees_standards(self):
        (self.dir / "standards-core").mkdir()
        (self.dir / "standards-core" / "a.md").write_text("# a\n")
        before = self.ch.content_hash(self.dir)
        for name in OWN:
            (self.dir / name).mkdir()
            (self.dir / name / "f.txt").write_text("one\n")
        self.assertEqual(self.ch.content_hash(self.dir), before)
        for name in OWN:
            (self.dir / name / "f.txt").write_text("two\n")
            (self.dir / name / "new.txt").write_text("new\n")
        self.assertEqual(self.ch.content_hash(self.dir), before)
        (self.dir / "standards-core" / "a.md").write_text("# b\n")
        self.assertNotEqual(self.ch.content_hash(self.dir), before)


class ExceptionsScope(Work):
    def test_lint_fixtures_are_scanned_standards_core_is_skipped(self):
        ex = load("check_exceptions_own", "templates/overlay/scripts/check-exceptions.py")
        self.assertEqual(ex.COPIES, ("standards-core",))


class SyncKeepsOwnCopies(Work):
    def test_sync_leaves_existing_lint_kit_tokens_in_place(self):
        core = self.dir / "core"
        (core / "templates" / "overlay").mkdir(parents=True)
        shutil.copytree(SCRIPTS, core / "templates" / "overlay" / "scripts")
        shutil.copytree(TEMPLATES, core / "templates" / "overlay" / ".github" / "workflows")
        (core / "standards").mkdir()
        (core / "standards" / "a.md").write_text("# a\n")
        (core / "lint").mkdir()
        (core / "lint" / "script_lint.py").write_text("print('core lint')\n")
        git(self.dir, "init", "-q", "-b", "main", core)
        git(core, "add", "-A")
        git(core, "commit", "-q", "-m", "init")
        git(core, "tag", "v9.9.9")

        ov = self.dir / "app"
        shutil.copytree(SCRIPTS, ov / "scripts")
        (ov / "standards.lock").write_text("ref=v0.0.1\ncommit=abc\n")
        for name in OWN:
            (ov / name).mkdir()
            (ov / name / "mine.txt").write_text(f"{name} is mine\n")
        (ov / "lint-core" / "script_lint.py").write_text("print('my lint')\n")
        git(self.dir, "init", "-q", "-b", "main", ov)

        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_ENV, CORE_CHECKOUT=str(core), CORE_REPO="owner/core")
        r = subprocess.run(
            [sys.executable, ov / "scripts" / "sync-core.py", "v9.9.9"],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((ov / "standards-core" / "a.md").read_text(), "# a\n")
        for name in OWN:
            self.assertEqual((ov / name / "mine.txt").read_text(), f"{name} is mine\n")
        self.assertEqual((ov / "lint-core" / "script_lint.py").read_text(), "print('my lint')\n")
        self.assertIn("kept as your own code, no longer synced or hashed", r.stdout)
        # The lock hash is the standards-core hash and survives a later edit of an own copy.
        ch = load("corehash_sync", str(ov / "scripts" / "corehash.py"))
        (ov / "kit-core" / "mine.txt").write_text("edited\n")
        self.assertIn(ch.content_hash(ov), (ov / "standards.lock").read_text())


class WorkflowsSkipAbsentLint(Work):
    def test_template_workflows_guard_lint_core(self):
        for name in ("core-drift.yml", "lint-sweep.yml"):
            text = (TEMPLATES / name).read_text()
            self.assertIn("-f ", text)
            self.assertIn("lint-core/script_lint.py", text)
            self.assertIn("skipped", text)
