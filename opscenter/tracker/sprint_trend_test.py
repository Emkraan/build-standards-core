"""
sprint_trend_test.py
Purpose: The sprint trend builder (OC-18), against fake sources. Recent closed sprints are one per id, newest first, capped at 12; the trend takes the
         last six closed sprints oldest first with the active sprint last; items, done, points (a non number counts 0), points done and carried
         are counted from the source's rows; a sprint the source cannot read fails the trend instead of reading as empty; a source's own
         `committed` is passed through; only an id from the closed list may be opened (400 for a non number, 404 otherwise).
Run:     python3 sprint_trend_test.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sprint_trend as t  # noqa: E402


def sp(i, end, **kw):
    return {"id": i, "name": f"S{i}", "start": "", "end": end, "state": "closed", **kw}


def item(cat="new", pts=None, later=False):
    return {"key": "K", "status_category": cat, "points": pts, "later_sprint": later}


class Recent(unittest.TestCase):
    def test_one_per_id_newest_first_by_end_then_completion(self):
        rows = t.recent_closed(
            [
                sp(1, "2026-01-14"),
                sp(2, "2026-02-14"),
                sp(1, "2026-01-15"),
                sp(3, "", complete="2026-03-01"),
            ]
        )
        self.assertEqual([r["id"] for r in rows], [3, 2, 1])
        self.assertEqual(rows[2]["end"], "2026-01-15", "the later copy of an id wins")

    def test_rows_without_an_id_or_not_closed_are_dropped_and_the_list_is_capped(self):
        rows = t.recent_closed(
            [
                {"name": "x"},
                {"id": "", "end": "x"},
                sp(1, "2026-01-01", state="active"),
                None,
                "junk",
            ]
        )
        self.assertEqual(rows, [])
        many = [sp(i, f"2026-01-{i:02d}") for i in range(1, 20)]
        self.assertEqual(len(t.recent_closed(many)), 12)
        self.assertEqual(len(t.recent_closed(many, 3)), 3)
        self.assertEqual(t.recent_closed(None), [])

    def test_a_missing_state_counts_as_closed_for_a_source_that_does_not_send_one(self):
        self.assertEqual(len(t.recent_closed([{"id": 1, "name": "a", "end": "x"}])), 1)


class Trend(unittest.TestCase):
    def rows(self, closed, active=None, items=None):
        return t.trend(closed, active, lambda sid: (items or {}).get(sid, []))

    def test_counts_and_carried(self):
        items = {
            1: [item("done", 3), item("done", 2, later=True), item("new", None), item("new", "n/a")]
        }
        r = self.rows([sp(1, "2026-01-14")], items=items)[0]
        self.assertEqual(
            (r["items"], r["done"], r["points"], r["points_done"], r["carried"]),
            (4, 2, 5.0, 5.0, 1),
        )
        self.assertFalse(r["active"])
        self.assertNotIn("committed", r)

    def test_the_last_six_closed_sprints_oldest_first_then_the_active_one(self):
        closed = [sp(i, f"2026-01-{i:02d}") for i in range(1, 10)]
        rows = self.rows(closed, {"id": 99, "name": "Now", "start": "s", "end": "e"})
        self.assertEqual([r["id"] for r in rows], [4, 5, 6, 7, 8, 9, 99])
        self.assertEqual([r["active"] for r in rows], [False] * 6 + [True])

    def test_no_active_sprint_means_no_active_row_and_an_empty_sprint_is_a_row_of_zeros(self):
        r = self.rows([sp(1, "2026-01-01")], active=None)
        self.assertEqual((len(r), r[0]["items"], r[0]["points"]), (1, 0, 0.0))
        self.assertEqual(self.rows([], None), [])
        self.assertEqual(len(self.rows([], {"id": 5, "name": "x"})), 1)

    def test_a_source_that_cannot_read_a_sprint_fails_the_trend(self):
        with self.assertRaises(t.SourceUnreadable):
            t.trend([sp(1, "2026-01-01")], None, lambda sid: None)

    def test_a_committed_count_from_the_source_is_passed_through(self):
        r = self.rows([sp(1, "2026-01-01", committed=12)])[0]
        self.assertEqual(r["committed"], 12)

    def test_a_boolean_is_not_a_point_value(self):
        r = self.rows([sp(1, "2026-01-01")], items={1: [item("done", True)]})[0]
        self.assertEqual(r["points"], 0.0)


class Allowed(unittest.TestCase):
    def test_only_a_closed_id_opens(self):
        closed = t.recent_closed([sp(5, "2026-01-01")])
        self.assertEqual(t.allowed_closed_id("5", closed), 5)
        self.assertEqual(t.allowed_closed_id(5, closed), 5)
        with self.assertRaises(t.BadSprint) as c:
            t.allowed_closed_id("five", closed)
        self.assertEqual(c.exception.status, 400)
        with self.assertRaises(t.BadSprint) as c:
            t.allowed_closed_id("6", closed)
        self.assertEqual(c.exception.status, 404)
        with self.assertRaises(t.BadSprint):
            t.allowed_closed_id(None, closed)


if __name__ == "__main__":
    unittest.main()
