"""
dateranges_test.py
Purpose: Whole-day filters in a named zone with the end day counted in full across a clock change (a 23 or 25 hour day is one day);
         a bad range, day or zone is refused; events dated more than a day ahead are separated from every time panel and counted,
         never dropped, and a row with no readable date stays.
Run:     python3 dateranges_test.py
"""

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dateranges as d

UTC = dt.timezone.utc
NY = "America/New_York"


class Between(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(
            d.parse_between("2026-03-07,2026-03-09"), (dt.date(2026, 3, 7), dt.date(2026, 3, 9))
        )
        self.assertEqual(d.parse_between("2026-03-09"), (dt.date(2026, 3, 9), dt.date(2026, 3, 9)))
        for bad in ("", "a,b", "2026-03-09,2026-03-07", "2026-13-01,2026-13-02", "1,2,3"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                d.parse_between(bad)

    def test_whole_days_in_a_zone(self):
        lo, hi = d.whole_day_range("2026-01-10", "2026-01-11", NY)  # winter, UTC-5
        self.assertEqual(
            (lo, hi),
            (dt.datetime(2026, 1, 10, 5, tzinfo=UTC), dt.datetime(2026, 1, 12, 5, tzinfo=UTC)),
        )

    def test_the_end_day_is_counted_in_full(self):
        self.assertTrue(d.between("2026-01-11T23:59:59-05:00", "2026-01-10", "2026-01-11", NY))
        self.assertFalse(d.between("2026-01-12T00:00:00-05:00", "2026-01-10", "2026-01-11", NY))
        self.assertTrue(d.between("2026-01-10T00:00:00-05:00", "2026-01-10", "2026-01-11", NY))
        self.assertFalse(d.between("2026-01-09T23:59:59-05:00", "2026-01-10", "2026-01-11", NY))

    def test_across_the_spring_clock_change_the_day_is_23_hours(self):
        lo, hi = d.whole_day_range("2026-03-08", "2026-03-08", NY)  # clocks go forward on Mar 8
        self.assertEqual(hi - lo, dt.timedelta(hours=23))
        self.assertTrue(
            d.between(dt.datetime(2026, 3, 9, 3, 59, tzinfo=UTC), "2026-03-08", "2026-03-08", NY)
        )
        self.assertFalse(
            d.between(dt.datetime(2026, 3, 9, 4, 0, tzinfo=UTC), "2026-03-08", "2026-03-08", NY)
        )

    def test_across_the_autumn_clock_change_the_day_is_25_hours(self):
        lo, hi = d.whole_day_range("2026-11-01", "2026-11-01", NY)  # clocks go back on Nov 1
        self.assertEqual(hi - lo, dt.timedelta(hours=25))

    def test_a_range_that_spans_the_change_is_the_sum_of_its_days(self):
        lo, hi = d.whole_day_range("2026-03-07", "2026-03-09", NY)
        self.assertEqual(hi - lo, dt.timedelta(hours=24 + 23 + 24))

    def test_naive_timestamps_are_read_as_utc_and_z_is_accepted(self):
        self.assertTrue(d.between("2026-01-10T12:00:00Z", "2026-01-10", "2026-01-10", NY))
        self.assertTrue(d.between(dt.datetime(2026, 1, 10, 12), "2026-01-10", "2026-01-10", "UTC"))

    def test_an_unknown_zone_is_refused(self):
        with self.assertRaises(ValueError):
            d.whole_day_range("2026-01-10", "2026-01-10", "Not/AZone")


class Future(unittest.TestCase):
    NOW = dt.datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

    def test_events_more_than_a_day_ahead_are_separated_not_dropped(self):
        rows = [
            {"id": 1, "at": "2026-11-07T11:00:00Z"},
            {"id": 2, "at": "2026-11-08T11:59:59Z"},  # just under a day ahead: kept
            {"id": 3, "at": "2026-11-08T12:00:01Z"},  # just over: future
            {"id": 4, "at": "2027-01-01T00:00:00Z"},
        ]
        kept, future = d.split_future(rows, self.NOW)
        self.assertEqual(([r["id"] for r in kept], [r["id"] for r in future]), ([1, 2], [3, 4]))

    def test_a_row_with_no_readable_date_stays(self):
        kept, future = d.split_future(
            [{"id": 1}, {"id": 2, "at": "garbage"}, {"id": 3, "at": None}], self.NOW
        )
        self.assertEqual((len(kept), len(future)), (3, 0))

    def test_the_horizon_and_the_key_are_configurable(self):
        rows = [{"when": "2026-11-07T13:00:00Z"}]
        self.assertEqual(
            len(d.split_future(rows, self.NOW, key="when", horizon=dt.timedelta(minutes=30))[1]), 1
        )
        self.assertEqual(len(d.split_future(rows, self.NOW, key="when")[1]), 0)

    def test_the_note_carries_the_count(self):
        self.assertIsNone(d.future_note(0))
        self.assertIn("1 event dated more than a day ahead is left off", d.future_note(1))
        self.assertIn("3 events dated more than a day ahead are left off", d.future_note(3))


if __name__ == "__main__":
    unittest.main()
