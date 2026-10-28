#!/usr/bin/env python3
"""Tests for publish_mode.py. Scratch files only, never the real config."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest

import publish_mode as pm

LIVE = "<table><tbody><tr><td><p>2026-10-01</p></td><td><p>First row</p></td></tr></tbody></table>"
APPENDED = LIVE.replace(
    "<tbody>", "<tbody><tr><td><p>2026-10-21</p></td><td><p>New row</p></td></tr>"
)


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="pm-test-")
        self.cfg = os.path.join(self.d, "knowledge-curation-config.json")
        self.lock = os.path.join(self.d, ".cfg.lock")

    def read(self):
        with open(self.cfg) as fh:
            return json.load(fh)

    def raw(self):
        with open(self.cfg) as fh:
            return fh.read()

    def write(self, obj):
        with open(self.cfg, "w") as fh:
            fh.write(obj if isinstance(obj, str) else json.dumps(obj))


class Modes(Base):
    def test_default_is_staged(self):
        self.write({"mode": "staged", "note": "x"})
        self.assertEqual(pm.class_modes(self.cfg), {"changelog_append": "staged"})

    def test_missing_unreadable_and_bad_value_fail_closed(self):
        self.assertEqual(
            pm.class_mode("changelog_append", os.path.join(self.d, "none.json")), "staged"
        )
        self.write("{nope")
        self.assertEqual(pm.class_mode("changelog_append", self.cfg), "staged")
        self.write({"class_modes": {"changelog_append": "autonomous"}})
        self.assertEqual(pm.class_mode("changelog_append", self.cfg), "staged")

    def test_toggle_writes_config_and_keeps_other_keys(self):
        self.write({"mode": "staged", "note": "keep me", "updated_utc": "2026-07-13T17:20:00Z"})
        out = pm.set_class_mode("changelog_append", "auto", self.cfg, self.lock)
        self.assertEqual(out["changelog_append"], "auto")
        saved = self.read()
        self.assertEqual(saved["mode"], "staged")
        self.assertEqual(saved["note"], "keep me")
        self.assertEqual(saved["class_modes"], {"changelog_append": "auto"})
        self.assertTrue(saved["class_modes_updated_utc"].endswith("Z"))
        pm.set_class_mode("changelog_append", "staged", self.cfg, self.lock)
        self.assertEqual(pm.class_mode("changelog_append", self.cfg), "staged")

    def test_toggle_rejects_unknown_class_bad_mode_and_unreadable_file(self):
        self.write({"mode": "staged"})
        with self.assertRaises(KeyError):
            pm.set_class_mode("everything", "auto", self.cfg, self.lock)
        with self.assertRaises(ValueError):
            pm.set_class_mode("changelog_append", "autonomous", self.cfg, self.lock)
        self.write("{nope")
        with self.assertRaises(ValueError):
            pm.set_class_mode("changelog_append", "auto", self.cfg, self.lock)
        self.assertEqual(self.raw(), "{nope")  # never replaced

    def test_concurrent_toggles_leave_valid_json(self):
        self.write({"mode": "staged"})
        ts = [
            threading.Thread(
                target=pm.set_class_mode, args=("changelog_append", m, self.cfg, self.lock)
            )
            for m in ("auto", "staged") * 10
        ]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertIn(self.read()["class_modes"]["changelog_append"], pm.MODES)


class Classify(unittest.TestCase):
    def prop(self, **kw):
        p = {
            "kind": "update",
            "target_id": "7",
            "target_title": "platform Changelog",
            "scope_verdict": "ALLOW",
        }
        p.update(kw)
        return p

    def test_changelog_update_is_a_class_member(self):
        self.assertEqual(pm.classify(self.prop()), "changelog_append")
        self.assertEqual(
            pm.classify(self.prop(target_title="team Console - Changelog")), "changelog_append"
        )

    def test_everything_else_is_not(self):
        for p in (
            self.prop(target_title="platform Runbook"),
            self.prop(target_title="Changelog Process Guide"),
            self.prop(kind="create"),
            self.prop(target_id=None),
            self.prop(new_parent_id="9"),
            self.prop(approve_after="merge of platform #400"),
            self.prop(scope_verdict="REFUSE"),
        ):
            self.assertIsNone(pm.classify(p), p)


class AppendOnly(unittest.TestCase):
    def test_added_row_is_an_append(self):
        self.assertEqual(pm.is_append_only(LIVE, APPENDED)[0], True)

    def test_changed_removed_or_unchanged_is_not(self):
        self.assertFalse(pm.is_append_only(LIVE, LIVE.replace("First row", "First row, edited"))[0])
        self.assertFalse(pm.is_append_only(APPENDED, LIVE)[0])
        self.assertFalse(pm.is_append_only(LIVE, LIVE)[0])
        self.assertFalse(pm.is_append_only("", APPENDED)[0])


class Digest(unittest.TestCase):
    def test_groups_auto_rows_by_eastern_day_and_skips_manual(self):
        rows = [
            {
                "fp": "a",
                "result": "published",
                "auto": True,
                "when": "2026-10-21T03:30:00Z",
                "title": "T",
                "version_before": 1,
                "version_after": 2,
                "revert_url": "u",
            },
            {
                "fp": "b",
                "result": "published",
                "auto": True,
                "when": "2026-10-21T15:00:00Z",
                "title": "T2",
            },
            {"fp": "c", "result": "published", "when": "2026-10-21T15:00:00Z"},
            {"fp": "d", "result": "exists", "auto": True, "when": "2026-10-21T15:00:00Z"},
        ]
        d = pm.digest(rows, tz_name="America/New_York")
        self.assertEqual(
            [(x["date"], x["count"]) for x in d], [("2026-10-21", 1), ("2026-10-20", 1)]
        )
        self.assertEqual(d[1]["items"][0]["revert_url"], "u")

    def test_urls_name_the_prior_version(self):
        self.assertIn("pageId=5&pageVersion=11", pm.version_url("5", 11))
        self.assertIn("viewpreviousversions.action?pageId=5", pm.history_url("5"))


if __name__ == "__main__":
    unittest.main()
