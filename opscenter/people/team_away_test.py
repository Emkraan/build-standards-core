#!/usr/bin/env python3
"""Tests for team_away.py. Fake calendar helper and a scratch store, no calendar calls."""

from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path

T0 = dt.datetime(2026, 10, 14, 12, 0, tzinfo=dt.timezone.utc)
PEOPLE = [{"name": "Pat Report", "first": "Pat", "email": "pat.report@example.com"}]


class TeamAwayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["TEAM_AWAY_STORE"] = str(Path(self.tmp.name) / "away.json")
        import importlib

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import team_away

        self.m = importlib.reload(team_away)
        self.m.team = lambda: PEOPLE
        self.calls = 0

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("TEAM_AWAY_STORE", None)

    def gm_ok(self, args, timeout=60):
        self.calls += 1
        blk = {
            "start": "2026-10-12T00:00:00-04:00",
            "end": "2026-10-15T00:00:00-04:00",
            "all_day": True,
        }
        return {"people": {"pat.report@example.com": {"error": None, "blocks": [blk]}}}

    def gm_fail(self, args, timeout=60):
        raise RuntimeError("calendar helper timed out")

    def test_pull_maps_blocks_to_people(self):
        d = self.m.snapshot(gm=self.gm_ok, now=T0)
        self.assertIsNone(d["error"])
        self.assertEqual(d["people"][0]["first"], "Pat")
        self.assertTrue(d["people"][0]["blocks"][0]["all_day"])

    def test_cached_inside_refresh_window(self):
        self.m.snapshot(gm=self.gm_ok, now=T0)
        self.m.snapshot(gm=self.gm_ok, now=T0 + dt.timedelta(minutes=10))
        self.assertEqual(self.calls, 1)
        self.m.snapshot(gm=self.gm_ok, now=T0 + dt.timedelta(minutes=31))
        self.assertEqual(self.calls, 2)

    def test_failed_read_keeps_last_good_and_flags_it(self):
        self.m.snapshot(gm=self.gm_ok, now=T0)
        d = self.m.snapshot(force=True, gm=self.gm_fail, now=T0 + dt.timedelta(minutes=40))
        self.assertIn("timed out", d["error"])
        self.assertEqual(len(d["people"][0]["blocks"]), 1)

    def test_failed_first_read_is_an_error_not_an_empty_team(self):
        d = self.m.snapshot(gm=self.gm_fail, now=T0)
        self.assertTrue(d["error"])
        self.assertEqual(d["people"], [])


if __name__ == "__main__":
    unittest.main()
