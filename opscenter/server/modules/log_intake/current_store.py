"""
current_store.py
Purpose: The latest snapshot per device for each stream, kept locally so reports work with no sink (log intake E5). A "latest" stream keeps one
         row per device holding that device's full record list, replaced on every accepted post; a replayed older file never overwrites a
         newer snapshot. An "events" stream keeps every post, and the snapshot id makes a replayed file a no-op. History lives at the sink;
         this is current state, plus a bounded, short event history that is purged after the stream's retention.
Date:    2026-11-07
Notes:   Ported from the reference implementation. Not ported: its incremental counter table and sliced recount (a performance structure for very
         large fleets); `current_stats` counts from the table, which is exact and bounded for a latest stream (one row per device) and for the
         short event history.
"""

from __future__ import annotations

import datetime as dt
import json

from . import db


def _parse(ts):
    try:
        d = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def save_current(stream_key, device, snapshot_id, collected_at, rows, mode="latest"):
    """Store a post. Returns True when it changed the store, False for a replay (an event already stored, an older snapshot)."""
    con = db.connect()
    try:
        blob = json.dumps(rows)
        if mode == "events":
            cur = con.execute(
                "INSERT OR IGNORE INTO log_stream_events (stream_key, source, snapshot_id, collected_at, row_count, rows_json) VALUES (?,?,?,?,?,?)",
                (stream_key, device, snapshot_id, collected_at, len(rows), blob),
            )
            con.commit()
            return cur.rowcount > 0
        prev = con.execute(
            "SELECT collected_at FROM log_stream_current WHERE stream_key=? AND source=?",
            (stream_key, device),
        ).fetchone()
        if prev:
            a, b = _parse(prev["collected_at"]), _parse(collected_at)
            if a and b and b < a:
                return False  # a replayed older file must not overwrite a newer snapshot
        con.execute(
            "INSERT INTO log_stream_current (stream_key, source, snapshot_id, collected_at, row_count, rows_json) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(stream_key, source) DO UPDATE SET snapshot_id=excluded.snapshot_id, collected_at=excluded.collected_at, "
            "received_at=datetime('now'), row_count=excluded.row_count, rows_json=excluded.rows_json",
            (stream_key, device, snapshot_id, collected_at, len(rows), blob),
        )
        con.commit()
        return True
    finally:
        con.close()


def table_for_mode(mode):
    return "log_stream_events" if mode == "events" else "log_stream_current"


def current_rows(stream_key, mode="latest"):
    """[(device, collected_at, rows)] of the stored snapshots (every post for an events stream)."""
    con = db.connect()
    try:
        out = []
        for r in con.execute(
            f"SELECT source, collected_at, rows_json FROM {table_for_mode(mode)} WHERE stream_key=? ORDER BY source, collected_at",
            (stream_key,),
        ):
            out.append((r["source"], r["collected_at"], json.loads(r["rows_json"])))
        return out
    finally:
        con.close()


def current_stats(stream_key, mode="latest"):
    """{devices, rows, lastReceivedAt}. Zero for a stream that has received nothing."""
    con = db.connect()
    try:
        r = con.execute(
            f"SELECT COUNT(DISTINCT source) AS d, COALESCE(SUM(row_count), 0) AS n, MAX(received_at) AS l FROM {table_for_mode(mode)} WHERE stream_key=?",
            (stream_key,),
        ).fetchone()
        return {"devices": r["d"], "rows": r["n"], "lastReceivedAt": r["l"]}
    finally:
        con.close()


def delete_current(stream_key):
    con = db.connect()
    try:
        con.execute("DELETE FROM log_stream_current WHERE stream_key=?", (stream_key,))
        con.execute("DELETE FROM log_stream_events WHERE stream_key=?", (stream_key,))
        con.commit()
    finally:
        con.close()


def purge_events():
    """Event rows older than the stream's retention are dropped (the sink keeps its own retention). Returns how many."""
    con = db.connect()
    try:
        cur = con.execute(
            "DELETE FROM log_stream_events WHERE received_at < datetime('now', '-' || "
            "(SELECT retention_days FROM log_streams s WHERE s.key = log_stream_events.stream_key) || ' days')"
        )
        con.commit()
        return cur.rowcount
    finally:
        con.close()
