"""The per pull request changelog tool, on scratch git repositories: check (missing entry, bad heading, undeclared area, downstream
rules, append only history, overlay sync), new (a generated entry that then passes check) and areas."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "changelog.py"
MARKER = "<!-- changelog:entries -->"
BASE_LOG = f"# Changelog\n\n{MARKER}\n\n## [baseline] 2026-01-01 - Start\nDownstream: none\nAreas: platform\n\n### Platform\n- start\n\n"
CONFIG = {
    "area_rules": [["^docs/", "standards"], ["^skills/", "skills"]],
    "sync_overlay": "app/",
    "sync_paths": ["core-copy/"],
}


def entry(n, downstream="none", areas="platform", extra=""):
    secs = "".join(f"### {a.strip().title()}\n- x\n\n" for a in areas.split(","))
    return f"## [#{n}] 2026-02-01 - Change {n}\nDownstream: {downstream}\nAreas: {areas}\n\n{secs}{extra}"


class Changelog(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="changelog-test-"))
        self.cfg = self.d / "cfg.json"
        self.cfg.write_text(json.dumps(CONFIG))
        self.repo = self.d / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        (self.repo / "CHANGELOG.md").write_text(BASE_LOG)
        self.write("README.md", "x\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.git("switch", "-q", "-c", "work")

    def git(self, *a):
        return subprocess.run(
            ["git", *a], cwd=self.repo, capture_output=True, text=True, check=True
        ).stdout

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "change")

    def tool(self, *args):
        env = dict(os.environ, CHANGELOG_TOOL_CONFIG=str(self.cfg))
        p = subprocess.run(
            [sys.executable, str(TOOL), *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        return p.returncode, p.stdout + p.stderr

    def check(self, n=5):
        return self.tool("check", "--pr", str(n), "--base", self.base)

    def set_log(self, text):
        (self.repo / "CHANGELOG.md").write_text(text)

    def test_a_change_without_an_entry_fails(self):
        self.write("src/a.py", "x\n")
        self.commit()
        rc, out = self.check()
        self.assertEqual(rc, 1)
        self.assertIn("does not update CHANGELOG.md", out)

    def test_a_valid_entry_passes_and_an_undeclared_area_fails(self):
        self.write("src/a.py", "x\n")
        self.set_log(BASE_LOG.replace(MARKER + "\n\n", MARKER + "\n\n" + entry(5)))
        self.commit()
        self.assertEqual(self.check()[0], 0)
        self.write("docs/guide.md", "x\n")
        self.commit()
        rc, out = self.check()
        self.assertEqual(rc, 1)
        self.assertIn("areas not declared", out)

    def test_the_first_entry_must_be_this_pr_and_history_is_append_only(self):
        self.write("src/a.py", "x\n")
        self.set_log(BASE_LOG.replace(MARKER + "\n\n", MARKER + "\n\n" + entry(6)))
        self.commit()
        self.assertIn("first entry under the marker must be '## [#5]", self.check(5)[1])
        self.set_log(
            (BASE_LOG + "")
            .replace("- start", "- rewritten")
            .replace(MARKER + "\n\n", MARKER + "\n\n" + entry(5))
        )
        self.commit()
        self.assertIn("history is append-only", self.check(5)[1])

    def test_consumer_areas_forbid_downstream_none_and_review_needs_actions(self):
        self.write("docs/guide.md", "x\n")
        self.set_log(
            BASE_LOG.replace(MARKER + "\n\n", MARKER + "\n\n" + entry(5, "none", "standards"))
        )
        self.commit()
        self.assertIn("Downstream cannot be 'none'", self.check()[1])
        self.set_log(
            BASE_LOG.replace(MARKER + "\n\n", MARKER + "\n\n" + entry(5, "review", "standards"))
        )
        self.commit()
        self.assertIn("no '### Downstream actions' section", self.check()[1])
        self.set_log(
            BASE_LOG.replace(
                MARKER + "\n\n",
                MARKER
                + "\n\n"
                + entry(5, "review", "standards", "### Downstream actions\n- reread\n\n"),
            )
        )
        self.commit()
        self.assertEqual(self.check()[0], 0)

    def test_a_missing_marker_and_a_bad_heading_fail(self):
        self.write("src/a.py", "x\n")
        self.set_log("# Changelog\n")
        self.commit()
        self.assertIn("missing the", self.check()[1])
        self.set_log(BASE_LOG.replace(MARKER + "\n\n", MARKER + "\n\n## [#5] bad heading\n"))
        self.commit()
        self.assertIn("bad heading", self.check()[1])

    def test_an_overlay_only_sync_needs_no_entry(self):
        self.write("app/core-copy/x.txt", "x\n")
        self.commit()
        rc, out = self.check()
        self.assertEqual(rc, 0)
        self.assertIn("overlay-only core sync", out)

    def test_new_generates_an_entry_that_passes_check(self):
        self.write("docs/guide.md", "# Top\n\nline\n")
        self.write("src/a.py", "x\n")
        self.commit()
        rc, out = self.tool(
            "new",
            "--pr",
            "5",
            "--title",
            "Add things",
            "--base",
            self.base,
            "--summary",
            "Summary line",
        )
        self.assertEqual(rc, 0, out)
        self.assertIn("## [#5]", out)
        self.assertIn("Downstream: review", out)
        self.assertIn("### Standards", out)
        self.commit()
        self.assertEqual(self.check()[0], 0)

    def test_areas_lists_what_the_change_touches(self):
        self.write("docs/guide.md", "x\n")
        self.write("src/a.py", "x\n")
        self.commit()
        rc, out = self.tool("areas", "--base", self.base)
        self.assertEqual((rc, out.split()), (0, ["platform", "standards"]))


if __name__ == "__main__":
    unittest.main()
