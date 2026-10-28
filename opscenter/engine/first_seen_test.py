#!/usr/bin/env python3
"""Tests for first_seen.py. Synthetic fps and a scratch store only."""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import first_seen as F

T0 = dt.datetime(2026, 10, 14, 14, 49, tzinfo=dt.timezone.utc)
T1 = T0 + dt.timedelta(hours=8)


class StampTest(unittest.TestCase):
    def test_new_item_gets_now_and_keeps_it_on_later_runs(self):
        seen = {}
        a = {"fp": "ac_a"}
        self.assertEqual(F.stamp([a], seen, T0), 1)
        b = {"fp": "ac_a"}
        self.assertEqual(F.stamp([b], seen, T1), 0)
        self.assertEqual(b["first_seen"], "2026-10-14T14:49:00Z")

    def test_aliased_repeat_inherits_the_earlier_time(self):
        seen = {"ac_old": "2026-10-14T13:49:00Z"}
        it = {"fp": "ac_old", "fp_alias_of": "ac_new"}
        F.stamp([it], seen, T1)
        self.assertEqual(it["first_seen"], "2026-10-14T13:49:00Z")
        # The repeat's own fp keeps its own first sighting, so handled.py can tell it was
        # not on the board when the earlier decision was made.
        self.assertEqual(seen["ac_new"], F._now_iso(T1))

    def test_item_without_fp_is_skipped(self):
        it = {"title": "x"}
        self.assertEqual(F.stamp([it], {}, T0), 0)
        self.assertNotIn("first_seen", it)

    def test_store_roundtrip_and_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            self.assertEqual(F.load(p), {})
            F.save(p, {"ac_b": "2", "ac_a": "1"})
            self.assertEqual(F.load(p), {"ac_a": "1", "ac_b": "2"})

    def test_corrupt_store_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            p.write_text('{"other": 1}')
            with self.assertRaises(ValueError):
                F.load(p)


if __name__ == "__main__":
    unittest.main()
