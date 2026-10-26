"""Tests for checks/auto-release.py: changelog parsing, the decision table, notes extraction."""

import unittest

from support import load

ar = load("auto_release", "checks/auto-release.py")

TEXT = """# Changelog

## 2026-10-25 (v1.12.1, an edit runs every check)

- first body line
- second line

## 2026-10-25 (v1.12.0, reusable core-ci workflow)

- older body

## 2026-10-20 (v1.11.1)

- no slug
## not a version heading
- stray
"""
SHA, OTHER = "a" * 40, "b" * 40


class Parser(unittest.TestCase):
    def test_entries_in_order(self):
        e = ar.parse_entries(TEXT)
        self.assertEqual([x[0] for x in e], [(1, 12, 1), (1, 12, 0), (1, 11, 1)])

    def test_odd_slug_and_no_slug(self):
        e = ar.parse_entries("## 2026-01-02 (v2.0.0, a (b), c: d)\n\nx\n")
        self.assertEqual(e, [])  # nested parens are not a valid heading, never a wrong version
        e = ar.parse_entries("## 2026-01-02 (v2.0.0, slug: with - odd, chars)\nx\n")
        self.assertEqual(e[0][0], (2, 0, 0))

    def test_notes_are_exactly_the_body(self):
        top = ar.top_entry(TEXT)
        self.assertEqual(top[2], "- first body line\n- second line\n")

    def test_stray_heading_ends_body(self):
        last = ar.parse_entries(TEXT)[-1]
        self.assertEqual(last[2], "- no slug\n")

    def test_empty(self):
        self.assertIsNone(ar.top_entry("# Changelog\n"))


class Decide(unittest.TestCase):
    def test_new_version(self):
        a, _ = ar.decide((1, 13, 1), (1, 12, 1), {(1, 12, 1): OTHER}, SHA)
        self.assertEqual(a, "tag")

    def test_same_commit_noop(self):
        a, _ = ar.decide((1, 12, 1), (1, 12, 0), {(1, 12, 1): SHA}, SHA)
        self.assertEqual(a, "noop")

    def test_moved_tag_fails(self):
        a, m = ar.decide((1, 12, 1), (1, 12, 0), {(1, 12, 1): OTHER}, SHA)
        self.assertEqual(a, "fail")
        self.assertIn("never moved", m)

    def test_non_monotonic_fails(self):
        a, _ = ar.decide((1, 12, 0), (1, 11, 1), {(1, 12, 1): OTHER}, SHA)
        self.assertEqual(a, "fail")

    def test_no_new_entry(self):
        a, _ = ar.decide((1, 12, 1), (1, 12, 1), {(1, 12, 1): OTHER}, SHA)
        self.assertEqual(a, "noop")

    def test_no_entry_at_all(self):
        self.assertEqual(ar.decide(None, None, {}, SHA)[0], "noop")

    def test_untagged_unchanged_top_still_tags(self):
        a, _ = ar.decide((1, 13, 0), (1, 13, 0), {(1, 12, 1): OTHER}, SHA)
        self.assertEqual(a, "tag")

    def test_first_ever_release(self):
        self.assertEqual(ar.decide((0, 1, 0), None, {}, SHA)[0], "tag")


if __name__ == "__main__":
    unittest.main()
