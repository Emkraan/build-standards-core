import json
import unittest

from support import Work, load

report = load("report_mod", "hermes/report.py")


class Section(unittest.TestCase):
    def test_render_is_stable_and_sorted(self):
        a = report.render_section({"repo-1": (["`B` x", "`A` y"], [], [])})
        self.assertEqual(a, report.render_section({"repo-1": (["`A` y", "`B` x"], [], [])}))
        self.assertTrue(a.startswith(report.START) and a.endswith(report.END))
        self.assertLess(a.index("`A` y"), a.index("`B` x"))
        self.assertIn("- none", a)

    def test_replace_keeps_text_outside_markers(self):
        body = (
            "intro\n\n"
            + report.render_section({"repo-1": (["old"], [], [])})
            + "\n\nnotes by people"
        )
        out = report.replace_section(body, report.render_section({"repo-1": (["new"], [], [])}))
        self.assertTrue(out.startswith("intro") and out.endswith("notes by people"))
        self.assertIn("new", out)
        self.assertNotIn("old", out)

    def test_append_when_no_markers(self):
        out = report.replace_section("hello", report.render_section({}))
        self.assertTrue(out.startswith("hello\n\n" + report.START))

    def test_relation(self):
        self.assertEqual(report.relation("Button", {"Button"}), "duplicates")
        self.assertEqual(report.relation("SaveButton", {"Button"}), "extends Button")
        self.assertEqual(report.relation("Gizmo", {"Button"}), "")


def fixture(self):
    """The one-repo clone the report tests scan."""
    self.clone = self.dir / "app"
    (self.clone / "src").mkdir(parents=True)
    (self.clone / "src" / "a.tsx").write_text("export function SaveButton() {}\n")
    kit = self.clone / "standards-overlay" / "kit-core" / "src"
    kit.mkdir(parents=True)
    (kit / "b.tsx").write_text("export function Button() {}\n")
    (self.clone / "standards-overlay" / "standards-local").mkdir()
    (self.clone / "standards-overlay" / "standards-local" / "ui-lint.json").write_text(
        json.dumps({"paths": ["../src"]})
    )
    self.consumers = [{"repo": "o/app", "path": str(self.clone)}]
    self.calls = []
    self.issue = None
    self.sanitise_result = ""


class Update(Work):
    """The 'update only when changed' rule, with gh and the sanitiser mocked."""

    def setUp(self):
        super().setUp()
        fixture(self)

    def sh(self, cmd, cwd=None, timeout=60):
        self.calls.append(list(map(str, cmd)))
        if cmd[0] == "gh" and cmd[1:3] == ["issue", "list"]:
            return 0, json.dumps([self.issue] if self.issue else [])
        if cmd[0] == "gh":
            if cmd[1:3] == ["issue", "edit"]:
                self.issue["body"] = cmd[cmd.index("--body") + 1]
            elif cmd[1:3] == ["issue", "create"]:
                self.issue = {"number": 7, "url": "u", "body": cmd[cmd.index("--body") + 1]}
            return 0, ""
        return 0, '{"findings": []}'

    def run_update(self, check=False):
        orig, report.sanitise = report.sanitise, lambda core, body, sh: self.sanitise_result
        try:
            return report.update(
                self.dir, "o/core", self.consumers, self.sh, self.dir / "st", check
            )
        finally:
            report.sanitise = orig

    def writes(self):
        return [
            c for c in self.calls if c[:3] in (["gh", "issue", "edit"], ["gh", "issue", "create"])
        ]

    def test_first_run_opens_issue_then_unchanged_run_writes_nothing(self):
        info, problems = self.run_update()
        self.assertEqual((len(info), problems), (1, []))
        self.assertEqual(len(self.writes()), 1)
        self.assertIn("SaveButton", self.issue["body"])
        self.assertIn("extends Button", self.issue["body"])
        self.calls.clear()
        info, problems = self.run_update()
        self.assertEqual((info, problems, self.writes()), ([], [], []))

    def test_changed_section_updates_the_issue(self):
        self.run_update()
        self.calls.clear()
        self.run_update()  # settle the 'seen' set
        (self.clone / "src" / "c.tsx").write_text("export const Gizmo = 1;\n")
        info, _ = self.run_update()
        self.assertEqual(len(self.writes()), 1)
        self.assertIn("Gizmo", self.issue["body"])
        self.assertEqual(self.writes()[0][:3], ["gh", "issue", "edit"])

    def test_sanitiser_hit_holds_and_reports_locally(self):
        self.sanitise_result = "check-sanitised.py flagged the report (1 hit(s)), held"
        info, problems = self.run_update()
        self.assertEqual((info, self.writes()), ([], []))
        self.assertIn("held", problems[0])

    def test_check_mode_posts_nothing(self):
        info, _ = self.run_update(check=True)
        self.assertEqual(self.writes(), [])
        self.assertIn("would update", info[0])

    def test_two_repos_one_pass_one_edit_both_kept(self):
        other = self.dir / "other"
        (other / "src").mkdir(parents=True)
        (other / "src" / "d.tsx").write_text("export function Button() {}\n")
        kit = other / "standards-overlay" / "kit-core" / "src"
        kit.mkdir(parents=True)
        (kit / "b.tsx").write_text("export function Button() {}\n")
        (other / "standards-overlay" / "standards-local").mkdir()
        (other / "standards-overlay" / "standards-local" / "ui-lint.json").write_text(
            json.dumps({"paths": ["../src"]})
        )
        self.consumers.append({"repo": "o/other", "path": str(other)})
        info, problems = self.run_update()
        self.assertEqual((len(info), problems, len(self.writes())), (1, [], 1))
        body = self.issue["body"]
        a, b = report.repo_label("o/app"), report.repo_label("o/other")
        self.assertIn(f"### {a}", body)
        self.assertIn(f"### {b}", body)
        app_block = body.split(f"### {a}")[1].split("\n### ")[0]
        self.assertIn("`SaveButton` (../src/a.tsx) extends Button", app_block)
        self.assertIn("`Button` (../src/d.tsx) duplicates", body)
        self.assertIn("`SaveButton`", body)
        self.assertNotIn("o/app", body)
        self.assertNotIn("o/other", body)
        self.calls.clear()
        info, problems = self.run_update()
        self.assertEqual((info, problems, self.writes()), ([], [], []))

    def test_never_opens_a_pull_request(self):
        self.run_update()
        self.assertFalse([c for c in self.calls if c[:2] == ["gh", "pr"]])


class OneIssuePerRun(Work):
    """#117 G-033: the issue list lags a create, so a run with no open issue must still create one, once."""

    def setUp(self):
        super().setUp()
        fixture(self)

    def sh(self, cmd, cwd=None, timeout=60):
        cmd = list(map(str, cmd))
        self.calls.append(cmd)
        if cmd[:3] == ["gh", "issue", "list"]:
            return 0, "[]"  # the list never shows the issue created seconds ago
        if cmd[:3] == ["gh", "issue", "create"]:
            self.issue = {
                "number": 41,
                "url": "https://example.invalid/issues/41",
                "body": cmd[cmd.index("--body") + 1],
            }
            return 0, self.issue["url"]
        if cmd[:3] == ["gh", "issue", "view"]:
            return (
                (0, json.dumps(self.issue)) if self.issue and cmd[3] == "41" else (1, "not found")
            )
        if cmd[:3] == ["gh", "issue", "edit"]:
            self.issue["body"] = cmd[cmd.index("--body") + 1]
            return 0, ""
        return 0, '{"findings": []}'

    def both(self, run):
        orig, report.sanitise = report.sanitise, lambda core, body, sh: ""
        try:
            report.update(self.dir, "o/core", self.consumers, self.sh, self.dir / "st", False, run)
            return report.update_changes(
                self.dir, "o/core", self.consumers, self.sh, self.dir / "st", False, run
            )
        finally:
            report.sanitise = orig

    def test_run_with_no_open_issue_creates_exactly_one(self):
        run = {}
        info, problems = self.both(run)
        creates = [c for c in self.calls if c[:3] == ["gh", "issue", "create"]]
        self.assertEqual(len(creates), 1)
        self.assertEqual(run["number"], 41)
        self.assertEqual(problems, [])
        self.assertIn(report.START, self.issue["body"])
        self.assertIn(
            report.CH_START, self.issue["body"]
        )  # the second section landed on the same issue

    def test_unreadable_number_never_creates_twice(self):
        run = {}
        orig = self.sh

        def no_url(cmd, cwd=None, timeout=60):
            rc, out = orig(cmd, cwd, timeout)
            return (rc, "") if list(map(str, cmd[:3])) == ["gh", "issue", "create"] else (rc, out)

        self.sh = no_url
        _, problems = self.both(run)
        self.assertEqual(len([c for c in self.calls if c[:3] == ["gh", "issue", "create"]]), 1)
        self.assertIn("not readable yet", problems[0])


if __name__ == "__main__":
    unittest.main()
