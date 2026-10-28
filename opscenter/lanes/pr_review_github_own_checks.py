#!/usr/bin/env python3
"""
pr_review_github_own_checks.py
Purpose: engine side. The github-dir path rule releases a plain script, prompt, test or
         workflow-step edit for the owner's PRs only and keeps every hold for engineer PRs. Synthetic policy and
         diffs, a fake gh. The plan-environment side is tested in tfplan_gate_test.py.
Run:     /usr/bin/python3 pr_review_github_own_checks.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="oprg-gh-own-"))
os.environ["OPRG_CACHE_DIR"] = str(TMP / "cache")
os.environ["OPRG_STATE_DIR"] = str(TMP / "state")
os.environ["TFGATE_STATE_DIR"] = str(TMP / "tf")
os.environ["TFGATE_CACHE_DIR"] = str(TMP / "tfc")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "testing"))
import policy_env  # noqa: E402

STATE_ROOT = (
    policy_env.install()
)  # a scratch state tree holding the policy fixtures, so no live state is read
spec = importlib.util.spec_from_file_location("eng", str(HERE / "pr_review.py"))
eng = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eng)

POL = json.loads((STATE_ROOT / "review" / "policy.json").read_text())
POL["path_rules"] = [
    r for r in POL["path_rules"] if r["id"] in ("github-dir", "codeowners", "forbidden-patterns")
]
POL["line_rules"] = []
SHA = "1" * 40


def diff_for(path, added=(), removed=(), new=False):
    lines = ["diff --git a/%s b/%s" % (path, path)]  # noqa: UP031
    lines += (
        ["new file mode 100644", "--- /dev/null"]
        if new
        else ["index 1..2 100644", "--- a/%s" % path]  # noqa: UP031
    )
    lines += (
        ["+++ b/%s" % path, "@@ -1,2 +1,2 @@", " ctx"]  # noqa: UP031
        + ["-" + x for x in removed]
        + ["+" + x for x in added]
    )
    return "\n".join(lines) + "\n"


class FakeGate:
    pass


def fake_tfgate():
    spec2 = importlib.util.spec_from_file_location("g199", str(HERE / "tfplan_gate.py"))
    mod = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(mod)

    def gh(args, timeout=60, raw=False):
        if args[1].endswith("/commits/main"):
            return "m" * 40
        if "/contents/.github/workflows?ref=" in args[1]:
            return [{"name": "ci.yml", "path": ".github/workflows/ci.yml", "type": "file"}]
        if "ci.yml" in args[1]:
            return "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@" + SHA + "\n"
        raise mod.GhError("404")

    mod.gh = gh
    return mod


eng._tfgate = fake_tfgate


def rules(path, added=(), removed=(), new=False, own=True):
    return [
        h["rule"]
        for h in eng.policy_hits(POL, [path], diff_for(path, added, removed, new), own=own)
    ]


class GithubOwn(unittest.TestCase):
    def test_own_script_edit_is_released(self):
        self.assertEqual(rules(".github/scripts/x.py", ["print(1)"]), [])

    def test_engineer_script_edit_holds(self):
        self.assertEqual(rules(".github/scripts/x.py", ["print(1)"], own=False), ["github-dir"])

    def test_default_is_the_engineer_behaviour(self):
        h = eng.policy_hits(
            POL, [".github/scripts/x.py"], diff_for(".github/scripts/x.py", ["print(1)"])
        )
        self.assertEqual([x["rule"] for x in h], ["github-dir"])

    def test_own_prompt_and_test_edits_are_released(self):
        self.assertEqual(rules(".github/prompts/a.md", ["x"]), [])
        self.assertEqual(rules(".github/scripts/tests/test_a.py", ["x"]), [])

    def test_own_workflow_step_edit_is_released(self):
        self.assertEqual(rules(".github/workflows/u.yml", ["      - run: echo hi"]), [])

    def test_security_edits_hold_for_me_too(self):
        for line in (
            "permissions: write-all",
            "  id-token: write",
            "  environment: prod",
            "  X: ${{ secrets.A }}",
            "  pull_request_target:",
            "  workflow_run:",
            "      - uses: evil/x@v1",
            "      - uses: actions/x@v1",
        ):
            self.assertEqual(rules(".github/workflows/u.yml", [line]), ["github-dir"], line)

    def test_codeowners_and_config_hold_for_me(self):
        self.assertIn("codeowners", rules(".github/CODEOWNERS", ["* @a"]))
        self.assertIn("github-dir", rules(".github/CODEOWNERS", ["* @a"]))
        self.assertEqual(rules(".github/terraform-roots.json", ["{}"]), ["github-dir"])
        self.assertIn("forbidden-patterns", rules(".github/forbidden-patterns.json", ["{}"]))
        self.assertEqual(rules(".github/unknown.cfg", ["x"]), ["github-dir"])

    def test_new_workflow_holds(self):
        self.assertEqual(rules(".github/workflows/new.yml", ["on: push"], new=True), ["github-dir"])

    def test_an_empty_diff_holds(self):
        h = eng.policy_hits(POL, [".github/scripts/x.py"], "", own=True)
        self.assertEqual([x["rule"] for x in h], ["github-dir"])

    def test_a_gate_error_holds(self):
        real = eng._tfgate
        eng._tfgate = lambda: (_ for _ in ()).throw(RuntimeError("x"))
        try:
            with self.assertRaises(RuntimeError):
                rules(".github/scripts/x.py", ["print(1)"])
        finally:
            eng._tfgate = real

    def test_other_paths_are_untouched(self):
        self.assertEqual(rules("infrastructure/x.tf", ["a = 1"]), [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
