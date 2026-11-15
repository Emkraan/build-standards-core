"""
freeze_bypass_test.py
Purpose: The human freeze bypass: one pull request for the current window only, all own pull requests until the next midnight in
         the owner's zone, scoped to the window id, expiry read on every read (nothing runs at midnight), fail closed on a
         missing, unreadable, foreign-window or expired store, only the owner's own open pull requests qualify, every change is
         logged, and the lane logs a bypass once per head.
Run:     python3 freeze_bypass_test.py
"""

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import freeze_bypass as fb  # noqa: E402
import override_store as ov  # noqa: E402

UTC = dt.timezone.utc
# 10:00 on 2026-11-02 in New York (EST after the clock change on Nov 1) is 15:00 UTC
NOW = dt.datetime(2026, 11, 2, 15, 0, tzinfo=UTC)
WINDOW = {
    "id": "w-nov",
    "name": "Month end",
    "start": "2026-11-01T00:00:00",
    "end": "2026-11-04T23:59:59",
}


class Bypass(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.freeze = self.dir / "freeze.json"
        self.freeze.write_text(json.dumps({"timezone": "America/New_York", "windows": [WINDOW]}))
        self.now = NOW
        self.prs = {
            "o/r#7": {"state": "open", "author": "me", "head": "abc"},
            "o/r#8": {"state": "open", "author": "them", "head": "d"},
            "o/r#9": {"state": "closed", "author": "me", "head": "e"},
        }
        self.store = fb.make_store(
            self.dir / "bp.json", clock=lambda: self.now, read_pr=self.prs.get, self_login="me"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, fn, *a, **k):
        return fn(*a, store=self.store, freeze_file=self.freeze, now=self.now, **k)

    def test_status_outside_a_freeze_is_off(self):
        self.now = dt.datetime(2026, 12, 1, 15, 0, tzinfo=UTC)
        st = self.call(fb.status)
        self.assertEqual((st["in_freeze"], st["window"], st["all"]["on"]), (False, None, False))

    def test_nothing_to_bypass_outside_a_freeze(self):
        self.now = dt.datetime(2026, 12, 1, 15, 0, tzinfo=UTC)
        with self.assertRaises(ov.OverrideRefused) as e:
            self.call(fb.set_all, True)
        self.assertEqual(e.exception.code, 409)
        with self.assertRaises(ov.OverrideRefused):
            self.call(fb.set_pr, "o/r#7", True)

    def test_one_pr_is_bypassed_for_this_window_with_its_head(self):
        st = self.call(fb.set_pr, "o/r#7", True, head="abc")
        self.assertEqual((st["in_freeze"], st["prs"]), (True, ["o/r#7"]))
        self.assertEqual(fb.bypass_by("o/r#7", WINDOW, self.store), "pr")
        self.assertIsNone(fb.bypass_by("o/r#8", WINDOW, self.store))
        self.assertEqual(self.store.entry("o/r#7", "w-nov")["extra"]["head"], "abc")

    def test_a_bypass_never_carries_into_the_next_window(self):
        self.call(fb.set_pr, "o/r#7", True)
        self.assertIsNone(fb.bypass_by("o/r#7", {"id": "w-dec"}, self.store))

    def test_the_pr_bypass_ends_with_the_window(self):
        self.call(fb.set_pr, "o/r#7", True)
        self.now = dt.datetime(2026, 11, 5, 5, 1, tzinfo=UTC)  # after 23:59:59 on Nov 4 in New York
        self.assertIsNone(fb.bypass_by("o/r#7", WINDOW, self.store))

    def test_all_runs_until_the_next_midnight_in_the_owner_zone_and_nothing_turns_it_off(self):
        st = self.call(fb.set_all, True)
        self.assertEqual(
            st["all"]["until"], "2026-11-03T05:00:00Z"
        )  # midnight Nov 3 in New York, EST
        self.assertEqual(fb.bypass_by("o/r#anything", WINDOW, self.store), "all")
        self.now = dt.datetime(2026, 11, 3, 4, 59, tzinfo=UTC)
        self.assertEqual(fb.bypass_by("o/r#anything", WINDOW, self.store), "all")
        self.now = dt.datetime(
            2026, 11, 3, 5, 0, tzinfo=UTC
        )  # nothing ran at midnight; the read sees the expiry
        self.assertIsNone(fb.bypass_by("o/r#anything", WINDOW, self.store))

    def test_all_can_be_switched_off_before_midnight(self):
        self.call(fb.set_all, True)
        st = self.call(fb.set_all, False)
        self.assertFalse(st["all"]["on"])
        self.assertIsNone(fb.bypass_by("o/r#7", WINDOW, self.store))

    def test_only_my_own_open_prs_qualify(self):
        with self.assertRaises(ov.OverrideRefused) as e:
            self.call(fb.set_pr, "o/r#8", True)
        self.assertEqual(e.exception.code, 403)
        with self.assertRaises(ov.OverrideRefused) as e:
            self.call(fb.set_pr, "o/r#9", True)
        self.assertEqual(e.exception.code, 409)
        self.assertFalse((self.dir / "bp.json").exists())

    def test_no_pr_read_configured_means_no_single_pr_bypass(self):
        store = fb.make_store(self.dir / "bp2.json", clock=lambda: self.now)
        with self.assertRaises(ov.OverrideRefused):
            fb.set_pr("o/r#7", True, store=store, freeze_file=self.freeze, now=self.now)

    def test_fail_closed_on_a_missing_unreadable_or_foreign_store(self):
        self.assertIsNone(fb.bypass_by("o/r#7", WINDOW, self.store))  # missing
        for text in (
            "{nope",
            "[]",
            '{"keys": {"o/r#7": {"scope": "w-nov", "until": "garbage"}}}',
            '{"keys": {"o/r#7": {"scope": "other", "until": "2099-01-01T00:00:00Z"}}}',
        ):
            (self.dir / "bp.json").write_text(text)
            self.assertIsNone(fb.bypass_by("o/r#7", WINDOW, self.store), text)
        self.assertIsNone(fb.bypass_by("o/r#7", None, self.store))  # no window id

    def test_every_change_is_logged(self):
        self.call(fb.set_pr, "o/r#7", True, who="me")
        self.call(fb.set_all, True, who="me")
        self.call(fb.set_pr, "o/r#7", False, who="me")
        log = [json.loads(x) for x in (self.dir / "bp.log.jsonl").read_text().splitlines()]
        self.assertEqual(
            [(x["action"], x["key"]) for x in log], [("on", "o/r#7"), ("on", "*"), ("off", "o/r#7")]
        )
        self.assertEqual(log[0]["window"], "w-nov")

    def test_the_lane_logs_a_bypass_once_per_head_and_source(self):
        rec, lines = {}, []
        self.assertTrue(fb.note_once(rec, 7, "abc", WINDOW, "pr", lines.append))
        self.assertFalse(fb.note_once(rec, 7, "abc", WINDOW, "pr", lines.append))
        self.assertTrue(fb.note_once(rec, 7, "def", WINDOW, "pr", lines.append))  # a new head
        self.assertTrue(fb.note_once(rec, 7, "def", WINDOW, "all", lines.append))  # another source
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0]["decision"], "freeze_bypassed")


if __name__ == "__main__":
    unittest.main()
