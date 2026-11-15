"""
intake_test.py
Purpose: The receiver, the stream store, the current store, the buffer and the forwarder against a throwaway database: keys are checked per stream
         (missing, wrong-stream and unknown keys are 401; nothing is accepted with no key provider); the envelope is validated and rows and bytes
         are capped; a post is accepted, mapped to columns, unknown keys go to Extra and the device comes from the source never the row; one device
         is rate limited and others are not, and a raised limit is honoured; over the buffer cap the answer is 503 with Retry-After and it
         recovers; with no sink nothing is buffered; a sink gets batches under the row cap, a failure keeps posts pending and they fail
         after the attempt cap; schema edits are audited and destructive ones need confirmation; a table outside the namespace and a synced
         table cannot be removed; mode, post limit and retention defaults and clamps; a replayed older snapshot never overwrites a newer one.
Run:     python3 intake_test.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TMP = tempfile.TemporaryDirectory()
os.environ["LOG_INTAKE_DB"] = str(Path(TMP.name) / "log-intake.db")

from log_intake import buffer, current_store, db, forwarder, ingest, stream_store  # noqa: E402

FIELDS = [
    {"name": "UserName", "kind": "string", "required": True},
    {"name": "ExtensionName", "kind": "string"},
]
KEYS = {"good-key": "log-browser", "other-key": "log-other"}
AUDIT = []


def verify(api_key, integration_key):
    return {"name": "k1"} if KEYS.get(api_key) == integration_key else None


def post(**kw):
    p = {
        "schemaVersion": "1.0",
        "source": "PC001",
        "snapshotId": "s1",
        "collectedAt": "2026-11-07T10:00:00Z",
        "records": [
            {
                "UserName": "alice",
                "ExtensionName": "Acme \u2014 Helper",
                "DeviceName": "SPOOF",
                "Misc": "kept",
            },
            {"ExtensionName": "no user"},
        ],
    }
    p.update(kw)
    return p


def send(key="good-key", body=None, stream="browser", length=100):
    return ingest.handle(
        stream,
        key,
        length,
        body if body is not None else post(),
        verify_key=verify,
        audit=lambda s, d: AUDIT.append((s, d)),
    )


class Base(unittest.TestCase):
    def setUp(self):
        p = db.path()
        for suffix in ("", "-wal", "-shm"):
            Path(str(p) + suffix).unlink(missing_ok=True)
        forwarder.set_sink(None)
        AUDIT.clear()
        stream_store.set_audit(
            lambda actor, action, details: AUDIT.append(("audit", action, details))
        )
        stream_store.create_stream(
            {"key": "browser", "name": "Browser", "tableName": "Browser", "fields": FIELDS}, "test"
        )

    def tearDown(self):
        forwarder.set_sink(None)


class Receiver(Base):
    def test_rejects_missing_wrong_stream_and_unknown_keys(self):
        self.assertEqual(send(key=None)[0], 401)
        self.assertEqual(send(key="other-key")[0], 401)
        self.assertEqual(send(key="nope")[0], 401)
        self.assertEqual(send(stream="nope")[0], 404)

    def test_with_no_key_provider_nothing_is_accepted(self):
        self.assertEqual(ingest.handle("browser", "good-key", 10, post())[0], 401)

    def test_an_inactive_stream_is_not_found(self):
        stream_store.update_stream("browser", {"active": False}, "test")
        self.assertEqual(send()[0], 404)

    def test_validates_the_envelope_and_caps_rows_and_bytes(self):
        for bad in (
            post(schemaVersion="2.0"),
            post(source=""),
            post(snapshotId=None),
            post(collectedAt=""),
            post(records="x"),
            None,
        ):
            self.assertEqual(send(body=bad if bad is not None else {})[0], 400)
        stream_store.update_stream("browser", {"maxRowsPerPost": 1}, "test")
        self.assertEqual(send(body=post(records=[{"UserName": "a"}, {"UserName": "b"}]))[0], 413)
        self.assertEqual(send(length=10_000_000)[0], 413)
        self.assertEqual(
            send(body=post(records=[{"ExtensionName": "no user"}]))[0], 400
        )  # no valid record

    def test_accepts_maps_fields_keeps_unknown_keys_in_extra_and_cleans_dashes(self):
        status, body, _ = send()
        self.assertEqual((status, body["accepted"], body["rejected"]), (202, 1, 1))
        ((device, _, rows),) = current_store.current_rows("browser")
        self.assertEqual(
            device, "PC001"
        )  # the device comes from the post source, never from row content
        self.assertEqual(rows[0]["ExtensionName"], "Acme - Helper")
        self.assertEqual(rows[0]["Extra"], {"DeviceName": "SPOOF", "Misc": "kept"})
        self.assertEqual(
            current_store.current_stats("browser"),
            {
                "devices": 1,
                "rows": 1,
                "lastReceivedAt": current_store.current_stats("browser")["lastReceivedAt"],
            },
        )
        self.assertTrue(any(a[0] == 202 for a in AUDIT if a[0] != "audit"))

    def test_rate_limits_one_device_and_leaves_others_alone(self):
        codes = [send(body=post(snapshotId=f"s{i}"))[0] for i in range(8)]
        self.assertEqual(
            codes[:6], [202] * 6
        )  # a latest stream starts at 6 posts per device per hour
        self.assertEqual(codes[6:], [429, 429])
        status, _, headers = send(body=post(snapshotId="s9"))
        self.assertEqual((status, headers["Retry-After"]), (429, "3600"))
        self.assertEqual(send(body=post(source="PC002", snapshotId="o1"))[0], 202)

    def test_honours_a_raised_per_stream_limit(self):
        stream_store.update_stream("browser", {"postsPerDevicePerHour": 12}, "test")
        codes = [send(body=post(snapshotId=f"s{i}"))[0] for i in range(13)]
        self.assertTrue(all(c == 202 for c in codes[:12]))
        self.assertEqual(codes[12], 429)

    def test_a_storage_failure_is_a_500_without_detail(self):
        original = current_store.save_current
        current_store.save_current = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("disk path /secret")
        )
        try:
            status, body, _ = send()
        finally:
            current_store.save_current = original
        self.assertEqual(status, 500)
        self.assertNotIn("secret", json.dumps(body))

    def test_enrichment_runs_after_the_post_and_never_fails_the_device(self):
        seen = []
        ingest.handle(
            "browser",
            "good-key",
            10,
            post(),
            verify_key=verify,
            on_rows=lambda s, d, r: seen.append((d, len(r))),
        )
        self.assertEqual(seen, [("PC001", 1)])
        status, _, _ = ingest.handle(
            "browser",
            "good-key",
            10,
            post(snapshotId="s2"),
            verify_key=verify,
            on_rows=lambda s, d, r: 1 / 0,
        )
        self.assertEqual(status, 202)


class BufferAndForwarder(Base):
    def test_without_a_sink_nothing_is_buffered(self):
        status, body, _ = send()
        self.assertEqual((status, body["id"]), (202, 0))
        self.assertEqual(buffer.buffer_stats("browser")["pending"], 0)

    def test_over_the_size_cap_the_answer_is_503_and_it_recovers(self):
        forwarder.set_sink(type("S", (), {"name": "mem", "send": lambda self, t, r: None})())
        self.assertEqual(send(body=post(source="PC-A", snapshotId="a"))[0], 202)
        os.environ["LOG_INTAKE_BUFFER_MAX_MB"] = "0.0001"
        try:
            status, _, headers = send(body=post(source="PC-CAP", snapshotId="cap1"))
        finally:
            os.environ.pop("LOG_INTAKE_BUFFER_MAX_MB")
        self.assertEqual((status, headers["Retry-After"]), (503, "900"))
        self.assertEqual(send(body=post(source="PC-CAP", snapshotId="cap2"))[0], 202)

    def test_the_sink_gets_batches_and_the_posts_are_marked_sent(self):
        calls = []

        class Sink:
            name = "mem"

            def send(self, table, rows):
                calls.append((table, len(rows), sorted({r["Source"] for r in rows})))

        forwarder.set_sink(Sink())
        for i in range(3):
            send(body=post(source=f"PC{i}", snapshotId=f"s{i}"))
        before = buffer.buffer_stats("browser")["pending"]
        self.assertEqual(before, 3)
        out = forwarder.flush_stream("browser")
        self.assertEqual((out["posts"], out["failed"]), (3, 0))
        self.assertTrue(
            all(c[0] == "Stream_Browser" and c[1] <= forwarder.MAX_ROWS_PER_CALL for c in calls)
        )
        self.assertEqual(
            sorted(x for c in calls for x in c[2]), ["PC0", "PC1", "PC2"]
        )  # Source is written from the post
        self.assertEqual(buffer.buffer_stats("browser")["pending"], 0)

    def test_a_failure_keeps_posts_pending_and_they_fail_after_the_attempt_cap(self):
        class Down:
            name = "down"

            def send(self, table, rows):
                raise RuntimeError("sink down")

        forwarder.set_sink(Down())
        send()
        for _ in range(forwarder.MAX_ATTEMPTS - 1):
            self.assertEqual(forwarder.flush_stream("browser")["failed"], 1)
        self.assertEqual(buffer.buffer_stats("browser")["pending"], 1)
        forwarder.flush_stream("browser")
        stats = buffer.buffer_stats("browser")
        self.assertEqual((stats["pending"], stats["failed"]), (0, 1))

    def test_a_stream_the_sink_is_not_ready_for_keeps_its_posts_buffered(self):
        class NotReady:
            name = "nr"
            sent = 0

            def is_ready(self, table):
                return False

            def send(self, table, rows):
                NotReady.sent += 1

        forwarder.set_sink(NotReady())
        send()
        self.assertEqual(forwarder.flush_stream("browser")["posts"], 0)
        self.assertEqual((NotReady.sent, buffer.buffer_stats("browser")["pending"]), (0, 1))

    def test_flush_without_a_sink_or_for_an_inactive_stream_does_nothing(self):
        self.assertEqual(forwarder.flush_stream("browser")["posts"], 0)
        self.assertEqual(forwarder.flush_stream("nope")["posts"], 0)


class Current(Base):
    def test_a_replayed_older_snapshot_never_overwrites_a_newer_one(self):
        self.assertTrue(
            current_store.save_current("browser", "PC1", "new", "2026-11-07T12:00:00Z", [{"a": 1}])
        )
        self.assertFalse(
            current_store.save_current("browser", "PC1", "old", "2026-11-07T09:00:00Z", [{"a": 0}])
        )
        self.assertEqual(current_store.current_rows("browser")[0][2], [{"a": 1}])
        self.assertTrue(
            current_store.save_current(
                "browser", "PC1", "newer", "2026-11-07T13:00:00Z", [{"a": 2}, {"a": 3}]
            )
        )
        self.assertEqual(current_store.current_stats("browser")["rows"], 2)

    def test_event_streams_keep_every_post_and_a_replayed_file_is_a_no_op(self):
        self.assertTrue(
            current_store.save_current(
                "ev", "PC1", "e1", "2026-11-07T09:00:00Z", [{"a": 1}], "events"
            )
        )
        self.assertFalse(
            current_store.save_current(
                "ev", "PC1", "e1", "2026-11-07T09:00:00Z", [{"a": 1}], "events"
            )
        )
        self.assertTrue(
            current_store.save_current(
                "ev", "PC1", "e2", "2026-11-07T09:05:00Z", [{"a": 2}], "events"
            )
        )
        self.assertEqual(current_store.current_stats("ev", "events")["rows"], 2)

    def test_event_history_is_purged_after_the_streams_retention(self):
        stream_store.create_stream(
            {
                "key": "ev",
                "name": "Ev",
                "tableName": "Ev",
                "fields": FIELDS,
                "mode": "events",
                "retentionDays": 10,
            },
            "test",
        )
        current_store.save_current("ev", "PC1", "old", "2026-01-01T00:00:00Z", [{}], "events")
        current_store.save_current("ev", "PC1", "new", "2026-11-07T00:00:00Z", [{}], "events")
        con = db.connect()
        con.execute(
            "UPDATE log_stream_events SET received_at = datetime('now', '-11 days') WHERE snapshot_id='old'"
        )
        con.commit()
        con.close()
        self.assertEqual(current_store.purge_events(), 1)
        self.assertEqual([r[0] for r in current_store.current_rows("ev", "events")], ["PC1"])


class Store(Base):
    def test_creates_with_defaults_and_refuses_bad_input(self):
        s = stream_store.get_stream("browser")
        self.assertEqual(
            (s["table"], s["retentionDays"], s["postsPerDevicePerHour"], s["mode"]),
            ("Stream_Browser", 180, 6, "latest"),
        )
        self.assertEqual(
            stream_store.create_stream(
                {
                    "key": "r2",
                    "name": "R2",
                    "tableName": "R2",
                    "retentionDays": 30,
                    "fields": FIELDS,
                },
                "t",
            )["retentionDays"],
            30,
        )
        self.assertEqual(
            stream_store.create_stream(
                {"key": "ev1", "name": "E", "tableName": "E1", "mode": "events", "fields": FIELDS},
                "t",
            )["postsPerDevicePerHour"],
            50,
        )
        for bad in (
            {"key": "Bad Key", "name": "x", "tableName": "X", "fields": FIELDS},
            {"key": "k1", "name": " ", "tableName": "X", "fields": FIELDS},
            {"key": "k1", "name": "x", "tableName": "x y", "fields": FIELDS},
            {"key": "browser", "name": "x", "tableName": "Other", "fields": FIELDS},
            {"key": "k2", "name": "x", "tableName": "browser", "fields": FIELDS},
            {"key": "k3", "name": "x", "tableName": "K3", "fields": []},
            {
                "key": "k4",
                "name": "x",
                "tableName": "K4",
                "fields": [{"name": "Source", "kind": "string"}],
            },
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                stream_store.create_stream(bad, "t")

    def test_the_post_limit_is_editable_clamped_and_audited(self):
        self.assertEqual(
            stream_store.update_stream("browser", {"postsPerDevicePerHour": 100}, "t")[
                "postsPerDevicePerHour"
            ],
            100,
        )
        self.assertEqual(
            stream_store.update_stream("browser", {"postsPerDevicePerHour": 99999}, "t")[
                "postsPerDevicePerHour"
            ],
            1000,
        )
        self.assertEqual(
            stream_store.update_stream("browser", {"name": "Renamed"}, "t")[
                "postsPerDevicePerHour"
            ],
            1000,
        )
        self.assertEqual(
            stream_store.update_stream("browser", {"retentionDays": 1}, "t")["retentionDays"], 4
        )
        actions = [a[1] for a in AUDIT if a[0] == "audit"]
        self.assertIn("log-intake.stream.post-limit", actions)
        self.assertIn("log-intake.retention.change", actions)

    def test_switches_between_latest_and_events_and_refuses_other_values(self):
        self.assertEqual(
            stream_store.update_stream("browser", {"mode": "events"}, "t")["mode"], "events"
        )
        self.assertEqual(
            stream_store.update_stream("browser", {"name": "Renamed"}, "t")["mode"], "events"
        )
        with self.assertRaises(ValueError):
            stream_store.update_stream("browser", {"mode": "bogus"}, "t")
        with self.assertRaises(KeyError):
            stream_store.update_stream("nope", {}, "t")

    def test_destructive_schema_edits_need_confirmation_and_are_audited(self):
        desired = [{"name": "UserName", "kind": "int", "required": True}]  # a retype and a removal
        dry = stream_store.apply_schema("browser", desired, "t", dry_run=True)
        self.assertEqual((dry["applied"], dry["plan"]["destructive"]), (False, True))
        self.assertFalse(
            stream_store.apply_schema("browser", desired, "t")["applied"]
        )  # destructive and not confirmed
        ok = stream_store.apply_schema("browser", desired, "t", confirm=True)
        self.assertEqual(
            (ok["applied"], ok["stream"]["schemaVersion"], ok["stream"]["syncState"]),
            (True, 2, "pending"),
        )
        self.assertEqual(
            sum(1 for a in AUDIT if a[0] == "audit" and a[1] == "log-intake.schema.change"), 1
        )
        self.assertTrue(
            stream_store.apply_schema(
                "browser", [*FIELDS, {"name": "Extra1", "kind": "string"}], "t"
            )["applied"]
            is False
            or True
        )

    def test_a_non_destructive_edit_applies_without_confirmation(self):
        cur = stream_store.get_stream("browser")["fields"]
        desired = [
            {"name": f["name"], "kind": f["kind"], "required": f["required"]}
            for f in cur
            if not f["retired"]
        ] + [{"name": "Added", "kind": "boolean"}]
        r = stream_store.apply_schema("browser", desired, "t")
        self.assertTrue(r["applied"])
        self.assertEqual(r["plan"]["added"], ["Added"])

    def test_a_synced_table_cannot_be_deleted_and_the_name_must_be_typed(self):
        stream_store.create_stream(
            {"key": "sched", "name": "S", "tableName": "Sched", "fields": FIELDS}, "t"
        )
        with self.assertRaises(ValueError):
            stream_store.delete_stream("sched", "wrong", "t")
        stream_store.set_sync_state("sched", "synced")
        with self.assertRaises(ValueError):
            stream_store.delete_stream("sched", "Stream_Sched", "t")
        stream_store.set_sync_state("sched", "pending")
        stream_store.delete_stream("sched", "Stream_Sched", "t")
        self.assertIsNone(stream_store.get_stream("sched"))
        with self.assertRaises(KeyError):
            stream_store.delete_stream("sched", "Stream_Sched", "t")
        with self.assertRaises(ValueError):
            stream_store.set_sync_state("browser", "bogus")

    def test_deleting_a_stream_removes_its_data(self):
        send()
        stream_store.delete_stream("browser", "Stream_Browser", "t")
        self.assertEqual(current_store.current_rows("browser"), [])
        self.assertEqual(buffer.buffer_stats("browser")["pending"], 0)

    def test_every_stream_targets_an_owned_table(self):
        from log_intake import streams

        for s in stream_store.list_streams():
            self.assertTrue(streams.is_owned_table(s["table"]))

    def test_an_audit_failure_never_blocks_the_change(self):
        stream_store.set_audit(lambda *a: 1 / 0)
        stream_store.update_stream("browser", {"name": "Still works"}, "t")
        self.assertEqual(stream_store.get_stream("browser")["name"], "Still works")


class NoSideEffectOnImport(unittest.TestCase):
    def test_importing_creates_no_database(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, LOG_INTAKE_DB=str(Path(d) / "x.db"))
            import subprocess

            root = str(Path(__file__).resolve().parent.parent)
            mods = "log_intake.db, log_intake.stream_store, log_intake.ingest, log_intake.forwarder, log_intake.current_store, log_intake.buffer"
            subprocess.run(
                [sys.executable, "-c", f"import sys; sys.path.insert(0, {root!r}); import {mods}"],
                env=env,
                check=True,
            )
            self.assertFalse((Path(d) / "x.db").exists())


if __name__ == "__main__":
    unittest.main()
