"""core-update.yml supports private repos with no personal token and no GitHub cron: an App token when
CORE_APP_ID is set, CORE_TOKEN otherwise, workflow_dispatch as the only default trigger, and a sync keeps
a schedule block a repo added."""

import re
import sys
import unittest

from support import ROOT

SCRIPTS = ROOT / "templates" / "overlay" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import corehash  # noqa: E402

TEMPLATE = ROOT / "templates" / "overlay" / ".github" / "workflows" / "core-update.yml"


def code(text):
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


class Template(unittest.TestCase):
    def setUp(self):
        self.text = TEMPLATE.read_text(encoding="utf8")
        self.code = code(self.text)

    def test_dispatch_is_the_only_trigger(self):
        on = self.code.split("permissions:")[0]
        self.assertIn("workflow_dispatch:", on)
        self.assertNotIn("schedule:", on)
        self.assertNotIn("cron:", on)

    def test_app_token_is_sha_pinned_and_scoped(self):
        self.assertRegex(
            self.code,
            r"uses: actions/create-github-app-token@[0-9a-f]{40} # v\d",
        )
        for line in (
            "if: vars.CORE_APP_ID != ''",
            "client-id: ${{ vars.CORE_APP_ID }}",
            "secrets[vars.CORE_APP_KEY_SECRET || 'CORE_APP_PRIVATE_KEY']",
            "permission-contents: write",
            "permission-pull-requests: write",
            "permission-workflows: write",
        ):
            self.assertIn(line, self.code)

    def test_core_token_stays_the_fallback(self):
        token = "${{ steps.app.outputs.token || secrets.CORE_TOKEN }}"
        self.assertGreaterEqual(self.code.count(token), 3)  # require, checkout, sync, publish
        # No job-level env carries the token: only the steps that need it.
        head = self.code.split("jobs:")[0]
        self.assertNotIn("GH_TOKEN", head)

    def test_missing_token_fails_loudly(self):
        self.assertIn("::error::core-update: set the variable CORE_APP_ID", self.code)

    def test_gate_and_never_auto_merge_unchanged(self):
        self.assertIn("vars.CORE_UPDATE_MERGE || 'approve'", self.code)
        self.assertNotIn("--auto", self.code)


class KeepSchedule(unittest.TestCase):
    TPL = "on:\n  workflow_dispatch:\npermissions:\n  contents: write\n"

    def test_repo_cron_survives_a_sync(self):
        local = 'on:\n  schedule:\n    - cron: "5 4 * * *"\n  workflow_dispatch:\npermissions: {}\n'
        out = corehash.merge_workflow(self.TPL, local)
        self.assertIn('  schedule:\n    - cron: "5 4 * * *"\n  workflow_dispatch:', out)

    def test_no_cron_stays_none(self):
        out = corehash.merge_workflow(self.TPL, self.TPL)
        self.assertEqual(out, self.TPL)
        self.assertFalse(re.search(r"schedule:", out))

    def test_template_cron_wins_over_duplicate(self):
        tpl = 'on:\n  schedule:\n    - cron: "1 1 * * *"  # core-sync: keep\n  workflow_dispatch:\n'
        local = 'on:\n  schedule:\n    - cron: "9 9 * * *"\n  workflow_dispatch:\n'
        out = corehash.merge_workflow(tpl, local)
        self.assertEqual(out.count("schedule:"), 1)
        self.assertIn("9 9 * * *", out)


if __name__ == "__main__":
    unittest.main()
