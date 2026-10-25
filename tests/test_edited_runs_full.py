"""A pull request edit must run every check. The merge gate reads the newest result for the check name
`core-checks`, and an edit starts a run that cancels the push's run through the concurrency group, so a
lighter edit run would report green for a commit whose full checks were cancelled or had failed."""

import re
import unittest

from support import ROOT

TEMPLATE = ROOT / "templates" / "overlay" / ".github" / "workflows" / "core-ci.yml"
REUSABLE = ROOT / ".github" / "workflows" / "core-ci-reusable.yml"


class EditedRunsAreFull(unittest.TestCase):
    def read(self, path):
        return path.read_text(encoding="utf8")

    def test_no_gate_excludes_an_edit(self):
        for path in (TEMPLATE, REUSABLE):
            text = self.read(path)
            code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
            self.assertNotIn("'edited'", code, f"{path.name} gates a step on the edited action")

    def test_full_and_commits_cover_every_pull_request_run(self):
        for path in (TEMPLATE, REUSABLE):
            text = self.read(path)
            full = re.search(r"^\s*FULL: (.+)$", text, re.M).group(1)
            commits = re.search(r"^\s*COMMITS: (.+)$", text, re.M).group(1)
            self.assertEqual(full, "${{ github.event_name == 'pull_request' || github.event_name == 'merge_group' }}")
            self.assertEqual(commits, "${{ github.event_name == 'pull_request' }}")

    def test_template_still_runs_on_an_edit(self):
        self.assertIn("types: [opened, edited, synchronize, reopened]", self.read(TEMPLATE))


if __name__ == "__main__":
    unittest.main()
