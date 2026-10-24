import json
import unittest

from support import Work, load

report = load("report_changes_mod", "hermes/report.py")


class Signatures(unittest.TestCase):
    def test_function_arrow_class_and_plain_const(self):
        text = (
            "export function Card({ tone, size }: { tone: string; size?: number }) {\n  return null;\n}\n"
            "export const Rail = (props: RailProps) => null;\n"
            "export default class Shell extends Base<Props> {\n}\n"
            'export const Accent = "x";\n'
        )
        sig = report.signatures(text)
        self.assertEqual(sig["Card"], "({ tone, size }: { tone: string; size?: number })")
        self.assertEqual(sig["Rail"], "(props: RailProps)")
        self.assertEqual(sig["Shell"], "extends Base<Props>")
        self.assertEqual(sig["Accent"], "")

    def test_formatting_alone_is_not_a_change(self):
        a = report.signatures("export function X(a: number, b: string) {}")
        b = report.signatures("export function X(\n  a: number,\n  b: string\n) {}")
        self.assertEqual(a, b)


class Diff(unittest.TestCase):
    OLD = {
        "parts": {"Card": ["src/Card.tsx", "(a)"], "Old": ["src/Old.tsx", ""]},
        "flags": {"UI010": 2},
        "status": {"pass": 10, "fail": 1},
        "ui": "partial",
    }

    def new(self, **kw):
        base = {
            "parts": {"Card": ["src/Card.tsx", "(a, b)"], "SaveButton": ["src/Save.tsx", "()"]},
            "flags": {"UI010": 1, "UI009": 1},
            "status": {"pass": 11, "fail": 0},
            "ui": "adopted",
        }
        base.update(kw)
        return base

    def test_diff_parts(self):
        d = report.diff_parts(self.OLD["parts"], self.new()["parts"])
        self.assertEqual(d, {"added": ["SaveButton"], "removed": ["Old"], "changed": ["Card"]})

    def test_diff_counts_only_moved_keys(self):
        self.assertEqual(
            report.diff_counts({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 1}),
            {"b": [2, 3], "c": [0, 1]},
        )

    def test_change_lines(self):
        lines = report.change_lines(self.OLD, self.new(), {"Button"})
        joined = "\n".join(lines)
        self.assertIn("`SaveButton` (src/Save.tsx) added", joined)
        self.assertIn("`Old` (src/Old.tsx) removed", joined)
        self.assertIn("`Card` (src/Card.tsx) signature changed", joined)
        self.assertIn("matches a kit role: extends Button", joined)
        self.assertIn("lint UI009 (kit class restyled inline): 0 -> 1", joined)
        self.assertIn("lint UI010 (local theme or token): 2 -> 1", joined)
        self.assertIn("core-status fail: 1 -> 0", joined)
        self.assertIn("core-status ui verdict: partial -> adopted", joined)

    def test_no_change_is_empty_and_first_run_is_baseline(self):
        self.assertEqual(report.change_lines(self.OLD, dict(self.OLD), set()), [])
        self.assertIn("baseline", report.change_lines(None, self.new(), set())[0])

    def test_label_names_no_repo(self):
        label = report.repo_label("someone/some-app")
        self.assertTrue(label.startswith("repo-"))
        self.assertNotIn("some", label)
        self.assertEqual(label, report.repo_label("someone/some-app"))

    def test_render_is_stable_and_markers_keep_other_text(self):
        a = report.render_changes({"repo-b": ["x"], "repo-a": []})
        self.assertEqual(a, report.render_changes({"repo-a": [], "repo-b": ["x"]}))
        self.assertLess(a.index("repo-a"), a.index("repo-b"))
        self.assertIn("- no change recorded", a)
        body = "top\n\n" + report.render_section({}) + "\n\n" + a + "\n\nnotes"
        out = report.replace_marked(
            body, report.render_changes({"repo-a": ["y"]}), report.CH_START, report.CH_END
        )
        self.assertTrue(out.startswith("top") and out.endswith("notes"))
        self.assertIn(report.START, out)
        self.assertIn("- y", out)
        self.assertNotIn("- x", out)


class UpdateChanges(Work):
    """Update only when the section changes, hold on a sanitiser hit, keep state on the machine."""

    def setUp(self):
        super().setUp()
        self.clone = self.dir / "app"
        (self.clone / "src").mkdir(parents=True)
        (self.clone / "src" / "a.tsx").write_text("export function Panel(a: number) {}\n")
        ov = self.clone / "standards-overlay" / "standards-local"
        ov.mkdir(parents=True)
        (ov / "ui-lint.json").write_text(json.dumps({"paths": ["../src"]}))
        self.issue = {"number": 3, "url": "u", "body": "people text\n"}
        self.calls = []
        self.held = ""

    def sh(self, cmd, cwd=None, timeout=60):
        self.calls.append(list(map(str, cmd)))
        if cmd[:3] == ["gh", "issue", "list"]:
            return 0, json.dumps([self.issue])
        if cmd[:3] == ["gh", "issue", "edit"]:
            self.issue["body"] = cmd[cmd.index("--body") + 1]
        return 0, ""

    def run_changes(self, check=False):
        orig, report.sanitise = report.sanitise, lambda core, body, sh: self.held
        try:
            return report.update_changes(
                self.dir,
                "o/core",
                [{"repo": "o/app", "path": str(self.clone)}],
                self.sh,
                self.dir / "st",
                check,
            )
        finally:
            report.sanitise = orig

    def edits(self):
        return [c for c in self.calls if c[:3] == ["gh", "issue", "edit"]]

    def test_baseline_then_quiet_then_change(self):
        self.run_changes()
        self.assertIn("baseline", self.issue["body"])
        self.assertTrue(self.issue["body"].startswith("people text"))
        self.calls.clear()
        self.run_changes()
        self.assertIn("baseline", self.issue["body"])  # a quiet night keeps the last change set
        self.assertEqual(self.edits(), [])
        (self.clone / "src" / "a.tsx").write_text(
            "export function Panel(a: number, b: string) {}\n"
        )
        self.run_changes()
        self.assertEqual(len(self.edits()), 1)
        self.assertIn("`Panel` (../src/a.tsx) signature changed", self.issue["body"])
        self.assertTrue(list((self.dir / "st").glob("changes__repo-*.json")))

    def test_sanitiser_hit_holds(self):
        self.held = "check-sanitised.py flagged the report (1 hit(s)), held"
        info, problems = self.run_changes()
        self.assertEqual((info, self.edits()), ([], []))
        self.assertIn("held", problems[0])
        self.assertFalse((self.dir / "st").exists())

    def test_check_mode_writes_nothing(self):
        info, _ = self.run_changes(check=True)
        self.assertEqual(self.edits(), [])
        self.assertIn("would update", info[0])
        self.assertFalse((self.dir / "st").exists())


if __name__ == "__main__":
    unittest.main()
