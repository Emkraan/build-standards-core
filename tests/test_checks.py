import json
import os
import sys
import unittest

from support import ROOT, Work, load, sh


class FileMode(Work):
    def test_sanitised_file_mode_word_boundary(self):
        env = self.dir / "deny.txt"
        env.write_text("core\n")
        os.environ["CORE_PRIVATE_DENYLIST"] = str(env)
        self.addCleanup(os.environ.pop, "CORE_PRIVATE_DENYLIST")
        ok, bad = self.dir / "ok.md", self.dir / "bad.md"
        ok.write_text("the score and a corehash table\n")
        bad.write_text("the pure core walk\n")
        self.assertEqual(
            sh([sys.executable, ROOT / "checks/check-sanitised.py", "--file", ok], cwd=ROOT)[0], 0
        )
        self.assertEqual(
            sh([sys.executable, ROOT / "checks/check-sanitised.py", "--file", bad], cwd=ROOT)[0], 1
        )

    def test_consumer_neutral_file_mode(self):
        env = self.dir / "deny.txt"
        env.write_text("acme\n")
        os.environ["CORE_PRIVATE_DENYLIST"] = str(env)
        self.addCleanup(os.environ.pop, "CORE_PRIVATE_DENYLIST")
        ok, bad = self.dir / "ok.md", self.dir / "bad.md"
        ok.write_text("acmeish is a different word? no: pacmen\n")
        bad.write_text("from the acme account\n")
        script = ROOT / "checks/check-consumer-neutral.py"
        self.assertEqual(sh([sys.executable, script, "--file", ok], cwd=ROOT)[0], 0)
        self.assertEqual(sh([sys.executable, script, "--file", bad], cwd=ROOT)[0], 1)

    def test_kit_comments_name_no_doc(self):
        ok, bad = self.dir / "ok.tsx", self.dir / "bad.tsx"
        ok.write_text("/* the UI standard, section 7 */\n")
        bad.write_text("/* the page web-ui.md requires */\n")
        script = ROOT / "checks/check-kit-comments.py"
        self.assertEqual(sh([sys.executable, script, "--file", ok])[0], 0)
        self.assertEqual(sh([sys.executable, script, "--file", bad])[0], 1)
        self.assertEqual(sh([sys.executable, script], cwd=ROOT)[0], 0)  # the real kit is clean


class ExceptionsBaseline(Work):
    def run_check(self, baseline_text):
        ov = self.dir / "ov"
        (ov / "scripts").mkdir(parents=True)
        (ov / "standards-local").mkdir()
        src = (ROOT / "templates/overlay/scripts/check-exceptions.py").read_text()
        (ov / "scripts" / "check-exceptions.py").write_text(src)
        (ov / "standards-local" / "ui-lint-baseline.json").write_text(baseline_text)
        sh(
            ["git", "init", "-q"], cwd=ov
        )  # its own repo, so the worktree's ignore rules do not apply
        return sh([sys.executable, "scripts/check-exceptions.py"], cwd=ov)

    def test_orphan_baseline_is_flagged(self):
        rc, out = self.run_check(json.dumps({"EXC-001": {"UI001": 3}}))
        self.assertEqual(rc, 1)
        self.assertIn("baseline names EXC-001", out)

    def test_baseline_without_ids_passes(self):
        self.assertEqual(self.run_check("{}")[0], 0)


class StatusGap(Work):
    def test_declared_stack_without_lint_config_fails(self):
        status = load("core_status2", "templates/overlay/scripts/core-status.py")
        status.ch.ROOT = self.dir
        (self.dir / "standards-local").mkdir()
        self.assertEqual(len(status.missing_lint_config({"python", "web"})), 2)
        (self.dir / "standards-local" / "script-lint.json").write_text("{}")
        (self.dir / "standards-local" / "ui-lint.json").write_text("{}")
        self.assertEqual(status.missing_lint_config({"python", "web"}), [])
        self.assertEqual(status.missing_lint_config({"wpf"}), [])


class StatusStandIns(Work):
    def test_named_copy_without_kit_import_is_a_stand_in_adapter_is_not(self):
        status = load("core_status3", "templates/overlay/scripts/core-status.py")
        kit = self.dir / "kit-core"
        kit.mkdir()
        (kit / "index.ts").write_text(
            "export { Spinner, Button as Btn } from './p';\nexport type { X } from './x';\n"
        )
        names = status.kit_exports(kit)
        self.assertEqual(names, {"Spinner", "Btn"})
        copy, adapter = self.dir / "Spinner.tsx", self.dir / "Btn.tsx"
        copy.write_text("export function Spinner() { return null }\n")
        adapter.write_text("import { Btn as K } from '@kit';\nexport const Btn = K;\n")
        self.assertEqual(status.stand_ins([copy, adapter], names), ["Spinner (Spinner.tsx)"])


class LicenseExempt(Work):
    def test_root_license_is_exempt_in_repo_mode_only(self):
        env = self.dir / "deny.txt"
        env.write_text("acme\n")
        os.environ["CORE_PRIVATE_DENYLIST"] = str(env)
        self.addCleanup(os.environ.pop, "CORE_PRIVATE_DENYLIST")
        repo = self.dir / "repo"
        (repo / "docs").mkdir(parents=True)
        (repo / "LICENSE").write_text("Copyright (c) 2026 acme\n")
        (repo / "docs" / "LICENSE").write_text("Copyright (c) 2026 acme\n")
        (repo / "notes.md").write_text("written for acme\n")
        (repo / "renovate.json").write_text('{"extends": ["github>acme/.github//renovate.json"]}\n')
        sh(["git", "init", "-q"], cwd=repo)
        sh(["git", "add", "-A"], cwd=repo)
        code, out = sh([sys.executable, ROOT / "checks/check-sanitised.py"], cwd=repo)
        self.assertEqual(code, 1)
        self.assertIn("notes.md", out)
        self.assertIn("docs/LICENSE", out)
        self.assertNotIn("file=LICENSE", out)
        self.assertNotIn("file=renovate.json", out)
        code, out = sh(
            [sys.executable, ROOT / "checks/check-sanitised.py", "--file", repo / "LICENSE"],
            cwd=repo,
        )
        self.assertEqual(code, 1)


class SharedHashedTerms(unittest.TestCase):
    def test_hashed_term_matches_whole_word_spans_only(self):
        san = load("check_sanitised", "checks/check-sanitised.py")
        hashes = {san.digest("acme corp"), san.digest("zed")}
        self.assertTrue(san.shared_hit("built for acme corp in 2026", hashes))
        self.assertTrue(san.shared_hit("the zed team", hashes))
        self.assertFalse(san.shared_hit("zedonk and acme alone", hashes))
        self.assertNotIn("acme", (ROOT / "checks/denylist.sha256").read_text())


class HashSkipsCaches(Work):
    def test_tool_caches_in_a_copy_do_not_change_the_hash(self):
        ch = load("corehash_t", "templates/overlay/scripts/corehash.py")
        (self.dir / "lint-core").mkdir()
        (self.dir / "lint-core" / "a.py").write_text("x = 1\n")
        before = ch.content_hash(self.dir)
        for d in (".ruff_cache", "__pycache__"):
            (self.dir / "lint-core" / d).mkdir()
            (self.dir / "lint-core" / d / "f").write_text("cache")
        self.assertEqual(ch.content_hash(self.dir), before)


class SkillLogMarks(unittest.TestCase):
    def test_dates_and_tickets_found_versions_and_encodings_not(self):
        skills = load("check_hermes_skills", "checks/check-hermes-skills.py")
        self.assertEqual(
            skills.log_marks("Fixed on 2026-10-13 in #142 and OPS-77."),
            ["2026-10-13", "#142", "OPS-77"],
        )
        self.assertEqual(
            skills.log_marks("Use v1.2.3, UTF-8, SHA-256 and UI010 (web-ui 0.11)."), []
        )


class ClosingRefs(Work):
    """A core pull request must never close a consumer-report issue through a closing keyword."""

    def run_check(self, title, body):
        event, labels = self.dir / "event.json", self.dir / "labels.json"
        event.write_text(json.dumps({"pull_request": {"title": title, "body": body}}))
        labels.write_text(json.dumps({"117": ["consumer-report"], "90": ["bug"]}))
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("CI", "GITHUB_ACTIONS", "GITHUB_EVENT_PATH")
        }
        import subprocess

        r = subprocess.run(
            [
                sys.executable,
                str(ROOT / "checks/check-closing-refs.py"),
                "--event",
                str(event),
                "--labels-json",
                str(labels),
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=self.dir,
        )
        return r.returncode, r.stdout

    def test_closing_keyword_on_a_report_issue_fails(self):
        for body in (
            "Closes #117",
            "fixes: #117",
            "Resolved o/core#117",
            "FIX https://github.com/o/core/issues/117",
        ):
            self.assertEqual(self.run_check("feat: x", body)[0], 1, body)
        self.assertEqual(self.run_check("fix(kit): resolves #117", "")[0], 1)

    def test_plain_link_and_other_issues_pass(self):
        for body in (
            "Refs #117 D-015",
            "for #117",
            "Fixes #90",
            "a fix for the table (#117)",
            "prefix #117",
        ):
            self.assertEqual(self.run_check("feat: x", body)[0], 0, body)

    def test_references_parse(self):
        mod = load("closing_refs", "checks/check-closing-refs.py")
        self.assertEqual(
            mod.references("Closes #1, fixes o/r#2 and resolved https://github.com/a/b/issues/3"),
            [("", 1), ("o/r", 2), ("a/b", 3)],
        )


if __name__ == "__main__":
    unittest.main()
