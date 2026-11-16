"""Tests for checks/check-changelog-versions.py: heading and tag agreement."""

import unittest

from support import load

cv = load("check_changelog_versions", "checks/check-changelog-versions.py")

TEXT = """# Changelog

## 2026-11-07 (v1.3.0, newest)
- x
## 2026-11-06 (v1.2.0, middle)
- x
## 2026-11-05 (v1.1.0)
- x
## 2026-10-01 (v0.9.0, before tagging)
- x
## 2026-10-01 (v0.9.0, a second 0.x heading is left alone)
- x
"""


class ConflictMarkers(unittest.TestCase):
    def test_marker_lines_are_found(self):
        text = "a\n<<<<<<< HEAD\nb\n=======\nc\n>>>>>>> origin/main\n"
        self.assertEqual(len(cv.conflict_markers(text)), 3)
        self.assertIn("line 2", cv.conflict_markers(text)[0])

    def test_clean_text_and_rules_pass(self):
        self.assertEqual(cv.conflict_markers(TEXT + "=== not a marker\n"), [])


class Headings(unittest.TestCase):
    def test_reads_1x_headings_in_order_and_skips_0x(self):
        self.assertEqual(cv.headings(TEXT), [(1, 3, 0), (1, 2, 0), (1, 1, 0)])

    def test_ignores_non_version_headings(self):
        self.assertEqual(cv.headings("## not a version\n## 2026-01-01 (vx)\n"), [])


class Malformed(unittest.TestCase):
    def test_readable_headings_pass(self):
        self.assertEqual(cv.malformed(TEXT), [])
        self.assertEqual(
            cv.malformed("## 2026-01-02 (v2.0.0)\n## 2026-01-02 (v2.0.0, a: b - c)\n"), []
        )

    def test_parentheses_inside_the_description_are_reported_with_the_line(self):
        out = cv.malformed("x\n## 2026-01-02 (v2.0.0, label (WCAG 2.5.3) text)\n")
        self.assertEqual(len(out), 1)
        self.assertIn("line 2", out[0])

    def test_matches_the_shape_the_release_step_reads(self):
        ar = load("auto_release", "checks/auto-release.py")
        for line in (
            "## 2026-01-02 (v2.0.0, a (b), c)",
            "## 2026-01-02 (v2.0.0, plain)",
            "## 2026-01-02 (v2.0.0)",
            "## 2026-01-02 (v2.0.0 no comma)",
        ):
            with self.subTest(line=line):
                readable = bool(ar.parse_entries(line + "\n"))
                self.assertEqual(not cv.malformed(line + "\n"), readable)


class Problems(unittest.TestCase):
    TAGS = {(1, 1, 0), (1, 2, 0)}

    def test_clean_with_an_unreleased_top_entry(self):
        self.assertEqual(cv.problems([(1, 3, 0), (1, 2, 0), (1, 1, 0)], self.TAGS), [])

    def test_duplicate_heading_is_reported_once_per_extra(self):
        out = cv.problems([(1, 3, 0), (1, 2, 0), (1, 2, 0), (1, 1, 0)], self.TAGS)
        self.assertEqual(out, ["v1.2.0 has more than one heading"])

    def test_heading_without_a_tag_at_or_below_the_newest_tag_fails(self):
        out = cv.problems([(1, 3, 0), (1, 2, 0), (1, 1, 5), (1, 1, 0)], self.TAGS)
        self.assertEqual(len(out), 1)
        self.assertIn("v1.1.5 has a heading but no tag", out[0])

    def test_unreleased_entries_above_every_tag_are_allowed(self):
        self.assertEqual(cv.problems([(1, 4, 0), (1, 3, 0), (1, 2, 0), (1, 1, 0)], self.TAGS), [])

    def test_tag_without_a_heading_fails(self):
        out = cv.problems([(1, 2, 0)], self.TAGS)
        self.assertEqual(out, ["v1.1.0 is a tag with no heading"])

    def test_the_168_case_is_caught(self):
        # two pull requests took v1.168.0: one tag, two headings
        out = cv.problems([(1, 169, 0), (1, 168, 0), (1, 168, 0)], {(1, 168, 0)})
        self.assertEqual(out, ["v1.168.0 has more than one heading"])


if __name__ == "__main__":
    unittest.main()
