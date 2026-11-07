"""
view_as_test.py
Purpose: A role preview is read only: reads always pass; a POST passes only when it is on the pinned allowlist of read-only queries
         (an exact path, or one with a `*` segment, ignoring a query string and a trailing slash); every other write is refused with
         "Preview is read-only."; the allowlist cannot grow after it is built and holds POST routes only.
Run:     python3 view_as_test.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import view_as as v

V = v.ViewAs([("POST", "/api/reports/query"), ("POST", "/api/dashboards/*/run")])


class Check(unittest.TestCase):
    def test_reads_always_pass(self):
        for m in ("GET", "HEAD", "OPTIONS", "get"):
            self.assertEqual(V.check(m, "/api/anything"), (True, ""), m)

    def test_the_two_allowed_posts_pass(self):
        self.assertTrue(V.check("POST", "/api/reports/query")[0])
        self.assertTrue(V.check("POST", "/api/reports/query/")[0])
        self.assertTrue(V.check("POST", "/api/reports/query?x=1")[0])
        self.assertTrue(V.check("post", "/api/dashboards/overview/run")[0])

    def test_every_other_write_is_refused_with_the_message(self):
        for m, p in (
            ("POST", "/api/reports"),
            ("POST", "/api/reports/query/extra"),
            ("PUT", "/api/reports/query"),
            ("DELETE", "/api/reports/x"),
            ("PATCH", "/api/dashboards/a/run"),
            ("POST", "/api/dashboards/a/b/run"),
        ):
            self.assertEqual(V.check(m, p), (False, "Preview is read-only."), (m, p))

    def test_a_star_matches_one_segment_only(self):
        self.assertFalse(V.check("POST", "/api/dashboards//run")[0])
        self.assertFalse(V.check("POST", "/api/dashboards/a/b/run")[0])

    def test_nothing_is_allowed_by_default(self):
        self.assertEqual(v.ViewAs().check("POST", "/api/reports/query"), (False, v.MESSAGE))

    def test_the_allowlist_is_pinned_and_posts_only(self):
        with self.assertRaises(ValueError):
            v.ViewAs([("GET", "/x")])
        self.assertIsInstance(V._allowed, tuple)
        self.assertFalse(hasattr(V, "add"))


if __name__ == "__main__":
    unittest.main()
