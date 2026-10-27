"""The merge gate rename deadlock: required-checks --fix rewrites a REQUIRED_CHECKS list in a gate
workflow (or prints the exact line), exits non-zero on a mismatch, and a gate that reads core-ci.yml
(required-names) follows a rename with no edit. Fixtures live under .test-work."""

import os
import shutil
import subprocess
import sys
import unittest

from support import ROOT, Work, load, sh

SCRIPTS = ROOT / "templates" / "overlay" / "scripts"
TEMPLATES = ROOT / "templates" / "overlay" / ".github" / "workflows"
ci = load("core_ci_gate", "templates/overlay/scripts/core-ci.py")

BLOCK = """name: automerge
env:
  REQUIRED_CHECKS: >-
    lint-and-build core-ascii core-python core-secret-scan
    core-attribution
  OTHER: x
"""
LINE = "env:\n  REQUIRED_CHECKS: 'build, core-ascii' # gate\n"
EXPR = "env:\n  REQUIRED_CHECKS: ${{ vars.CHECKS }}\n"


class Rewrite(unittest.TestCase):
    def test_block_swaps_obsolete_for_the_new_name_and_keeps_own_checks(self):
        new, manual = ci.rewrite_gates(
            BLOCK,
            {},
            {"core-ascii", "core-python", "core-secret-scan", "core-attribution"},
            ["core-checks"],
        )
        self.assertEqual(manual, [])
        self.assertIn("    lint-and-build core-checks\n", new)
        self.assertIn("  OTHER: x\n", new)
        self.assertNotIn("core-ascii", new)

    def test_line_keeps_quotes_separator_and_comment(self):
        new, _ = ci.rewrite_gates(LINE, {}, {"core-ascii"}, ["core-checks"])
        self.assertEqual(new, "env:\n  REQUIRED_CHECKS: 'build, core-checks'  # gate\n")

    def test_expression_is_not_edited(self):
        new, manual = ci.rewrite_gates(EXPR, {}, set(), ["core-checks"])
        self.assertEqual(new, EXPR)
        self.assertEqual(manual, [(2, "  REQUIRED_CHECKS: ${{ vars.CHECKS }}")])

    def test_stale_bare_name_is_replaced_in_place(self):
        new, _ = ci.rewrite_gates(
            "  REQUIRED_CHECKS: a checks b\n", {"checks": "core-checks"}, {"checks"}, []
        )
        self.assertEqual(new, "  REQUIRED_CHECKS: a core-checks b\n")


class Repo(Work):
    def setUp(self):
        super().setUp()
        self.repo = self.dir / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        (self.repo / ".github" / "workflows").mkdir(parents=True)
        shutil.copyfile(SCRIPTS / "core-ci.py", self.repo / "scripts" / "core-ci.py")
        shutil.copyfile(TEMPLATES / "core-ci.yml", self.repo / ".github/workflows/core-ci.yml")
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo, check=True, env=env)

    def gate(self, text):
        (self.repo / ".github/workflows/automerge.yml").write_text(text)

    def run_ci(self, *args):
        return sh([sys.executable, self.repo / "scripts/core-ci.py", *args], cwd=self.repo)

    def test_mismatch_exits_non_zero_and_fix_rewrites_the_list(self):
        self.gate(BLOCK)
        rc, out = self.run_ci("required-checks", "--lists-only")
        self.assertEqual(rc, 1, out)
        rc, out = self.run_ci("required-checks", "--lists-only", "--fix")
        self.assertEqual(rc, 0, out)
        self.assertIn("rewrote REQUIRED_CHECKS in .github/workflows/automerge.yml", out)
        text = (self.repo / ".github/workflows/automerge.yml").read_text()
        self.assertIn("core-checks", text)
        self.assertNotIn("core-ascii", text)
        self.assertEqual(self.run_ci("required-checks", "--lists-only")[0], 0)

    def test_unsafe_list_prints_file_line_and_replacement(self):
        self.gate(EXPR)
        rc, out = self.run_ci("required-checks", "--lists-only", "--fix")
        self.assertEqual(rc, 1, out)
        self.assertIn("automerge.yml:2", out)
        self.assertIn("replace it with: REQUIRED_CHECKS: ${{ vars.CHECKS }} core-checks", out)

    def test_full_fix_prints_ordering_and_ruleset_when_no_list(self):
        rc, out = self.run_ci(
            "required-checks", "--fix", "--api-json", str(self._api({"contexts": ["core-ascii"]}))
        )
        self.assertEqual(rc, 1, out)
        self.assertIn("Order: a job the gate newly requires", out)
        self.assertIn("rulesets", out)

    def _api(self, protection):
        import json

        f = self.dir / "api.json"
        f.write_text(json.dumps({"protection": protection, "rules": []}))
        return f

    def test_lists_only_skips_a_ruleset_gated_repo(self):
        self.assertEqual(self.run_ci("required-checks", "--lists-only")[0], 0)

    def test_gate_that_reads_core_ci_follows_a_rename(self):
        self.gate((TEMPLATES / "automerge.yml").read_text())
        rc, out = self.run_ci("required-checks", "--lists-only")
        self.assertEqual(rc, 0, out)
        rc, out = self.run_ci("required-names")
        self.assertEqual((rc, out.strip()), (0, "core-checks"))


if __name__ == "__main__":
    unittest.main()
