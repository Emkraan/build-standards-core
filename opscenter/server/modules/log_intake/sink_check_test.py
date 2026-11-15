"""
sink_check_test.py
Purpose: The sink access test: the permission matcher grants an action only when a role allows it and none of its exclusions removes it (wildcards,
         case ignored, data actions apart); a missing right is reported with the role and scope that would grant it; rights that could not be read are
         "could not be read", never a pass; the sink's own checks are normalised and a failed one always has a fix; a marked test row goes through the
         sink's real path, only for a stream whose table exists and is owned, is audited, and its marker is the only thing verify will look for.
Run:     python3 sink_check_test.py
"""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TMP = tempfile.TemporaryDirectory()
os.environ["LOG_INTAKE_DB"] = str(Path(TMP.name) / "log-intake.db")

from log_intake import db, stream_store  # noqa: E402
from log_intake import sink_check as sc  # noqa: E402

AUDIT = []
FIELDS = [{"name": "UserName", "kind": "string"}]


class Sink:
    def __init__(self, tables=("Stream_Browser",)):
        self.tables, self.sent = set(tables), []

    def has_table(self, table):
        return table in self.tables

    def send(self, table, rows):
        self.sent.append((table, rows))

    def find_marker(self, table, marker):
        return any(r["SnapshotId"] == marker for t, rows in self.sent if t == table for r in rows)


class Matcher(unittest.TestCase):
    PERMS = [
        {
            "actions": ["Svc/workspaces/tables/*", "Svc/workspaces/read"],
            "notActions": ["Svc/workspaces/tables/delete"],
            "dataActions": ["Svc/Telemetry/Write"],
        }
    ]

    def test_a_role_that_allows_it_and_no_exclusion(self):
        self.assertTrue(sc.action_allowed(self.PERMS, "Svc/workspaces/tables/write"))
        self.assertTrue(sc.action_allowed(self.PERMS, "svc/WORKSPACES/read"))  # case ignored

    def test_an_exclusion_removes_it(self):
        self.assertFalse(sc.action_allowed(self.PERMS, "Svc/workspaces/tables/delete"))

    def test_data_actions_are_apart_from_actions(self):
        self.assertTrue(sc.action_allowed(self.PERMS, "Svc/Telemetry/Write", data=True))
        self.assertFalse(sc.action_allowed(self.PERMS, "Svc/Telemetry/Write"))
        self.assertFalse(sc.action_allowed(self.PERMS, "Svc/workspaces/read", data=True))

    def test_another_role_can_grant_what_one_excludes(self):
        perms = [*self.PERMS, {"actions": ["*"]}]
        self.assertTrue(sc.action_allowed(perms, "Svc/workspaces/tables/delete"))

    def test_regex_characters_in_a_pattern_are_literal(self):
        self.assertFalse(sc.action_allowed([{"actions": ["a.b"]}], "aXb"))
        self.assertTrue(sc.action_allowed([{"actions": ["a.b"]}], "a.b"))
        self.assertFalse(sc.action_allowed([], "x"))


class Checks(unittest.TestCase):
    NEEDS = [
        ("write", "Create tables", "Svc/workspaces/tables/write", False, "Contributor", "/ws/1"),
        ("send", "Send data", "Svc/Telemetry/Write", True, "Publisher", "/rg/1"),
    ]

    def test_a_missing_right_names_the_role_and_scope_that_would_grant_it(self):
        out = sc.check_actions([{"actions": ["Svc/workspaces/tables/*"]}], self.NEEDS)
        self.assertEqual([c["ok"] for c in out], [True, False])
        self.assertEqual(out[0]["detail"], "Allowed.")
        self.assertEqual(out[1]["fix"], 'Assign "Publisher" to the module\'s identity on /rg/1.')
        self.assertIn("Missing Svc/Telemetry/Write", out[1]["detail"])
        self.assertNotIn("fix", out[0])

    def test_rights_that_could_not_be_read_are_not_a_pass(self):
        out = sc.check_actions({"error": "HTTP 403"}, self.NEEDS)
        self.assertEqual([c["ok"] for c in out], [None, None])
        self.assertIn("HTTP 403", out[0]["detail"])

    def test_diagnose_normalises_and_always_gives_a_failed_check_a_fix(self):
        class S:
            def diagnose(self):
                return [
                    {"id": "a", "label": "A", "ok": True, "detail": "fine"},
                    {"id": "b", "label": "B", "ok": False, "detail": "bad"},
                    {"id": "c", "label": "C", "ok": "maybe"},
                ]

        out = sc.diagnose(S())
        self.assertEqual([c["ok"] for c in out], [True, False, None])
        self.assertEqual(out[1]["fix"], "See the detail.")
        self.assertNotIn("fix", out[0])

    def test_no_sink_or_a_sink_that_cannot_diagnose_is_one_failed_check(self):
        for sink in (None, object()):
            out = sc.diagnose(sink)
            self.assertEqual((len(out), out[0]["ok"]), (1, False))
            self.assertIn("fix", out[0])

    def test_a_sink_whose_checks_raise_is_not_a_pass(self):
        class S:
            def diagnose(self):
                raise RuntimeError("timeout")

        out = sc.diagnose(S())
        self.assertEqual((out[0]["ok"], "timeout" in out[0]["detail"]), (None, True))


class TestRow(unittest.TestCase):
    def setUp(self):
        for suffix in ("", "-wal", "-shm"):
            Path(str(db.path()) + suffix).unlink(missing_ok=True)
        AUDIT.clear()
        stream_store.set_audit(
            lambda actor, action, details: AUDIT.append((actor, action, details))
        )
        stream_store.create_stream(
            {"key": "browser", "name": "Browser", "tableName": "Browser", "fields": FIELDS}, "t"
        )

    def test_a_marked_row_goes_through_the_sink_and_is_audited(self):
        sink = Sink()
        r = sc.send_test_row("browser", "owner", sink)
        self.assertEqual(r["table"], "Stream_Browser")
        self.assertTrue(re.fullmatch(r"test-[0-9a-f]{12}", r["marker"]))
        table, rows = sink.sent[0]
        self.assertEqual(
            (table, rows[0]["Source"], rows[0]["SnapshotId"]),
            ("Stream_Browser", sc.TEST_SOURCE, r["marker"]),
        )
        self.assertTrue(rows[0]["CollectedAt"].endswith("Z"))
        self.assertEqual(AUDIT[-1][1], "log-intake.sink.test-row")

    def test_a_stream_with_no_table_at_the_sink_is_refused(self):
        with self.assertRaises(ValueError):
            sc.send_test_row("browser", "owner", Sink(tables=()))
        with self.assertRaises(ValueError):
            sc.send_test_row("browser", "owner", None)
        with self.assertRaises(KeyError):
            sc.send_test_row("nope", "owner", Sink())

    def test_markers_are_unique(self):
        sink = Sink()
        self.assertNotEqual(
            sc.send_test_row("browser", "o", sink)["marker"],
            sc.send_test_row("browser", "o", sink)["marker"],
        )

    def test_verify_finds_only_a_marker_this_module_made(self):
        sink = Sink()
        marker = sc.send_test_row("browser", "owner", sink)["marker"]
        self.assertEqual(sc.verify_test_row("browser", marker, sink), {"found": True})
        self.assertEqual(sc.verify_test_row("browser", "test-" + "0" * 12, sink), {"found": False})
        for bad in ("x", "test-ZZZZZZZZZZZZ", 'test-aaaaaaaaaaaa" | drop', None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                sc.verify_test_row("browser", bad, sink)
        with self.assertRaises(ValueError):
            sc.verify_test_row("browser", marker, object())


if __name__ == "__main__":
    unittest.main()
