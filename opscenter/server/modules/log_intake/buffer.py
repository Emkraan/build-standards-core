"""
buffer.py
Purpose: The local buffer between the receiver and the sink (log intake E2, E6). One row per accepted post (a device snapshot), held only
         until a sink takes it, so it is capped by count and by size: a stream that posts large payloads, or a sink that stays down, never
         grows the database without bound. Over the cap the receiver answers 503 and devices retry later. Sent rows keep only metadata and
         are dropped after 14 days; failed rows are kept 30 days for review; with no sink nothing drains the buffer, so unsent posts are
         dropped after a short wait (the current snapshot is kept separately).
Date:    2026-11-07
Notes:   Ported from the reference implementation of an endpoint log receiver.
Config:  `LOG_INTAKE_BUFFER_MAX_MB` (default 64), `LOG_INTAKE_UNSENT_DAYS` (default 2).
"""

from __future__ import annotations

import json
import os

from . import db

MAX_PENDING_POSTS = 50_000


def max_pending_bytes():
    try:
        v = float(os.environ.get("LOG_INTAKE_BUFFER_MAX_MB", ""))
    except ValueError:
        v = 0
    return int((v if v > 0 else 64) * 1024 * 1024)


def pending_bytes():
    con = db.connect()
    try:
        return con.execute(
            "SELECT COALESCE(SUM(bytes), 0) AS n FROM log_buffer WHERE status='pending'"
        ).fetchone()["n"]
    finally:
        con.close()


def pending_count(stream_key):
    con = db.connect()
    try:
        return con.execute(
            "SELECT COUNT(*) AS n FROM log_buffer WHERE stream_key=? AND status='pending'",
            (stream_key,),
        ).fetchone()["n"]
    finally:
        con.close()


def record_post(stream_key, device):
    """Count one accepted post against the device's hourly limit (kept for every post, with or without a sink)."""
    con = db.connect()
    try:
        con.execute(
            "INSERT INTO log_post_log (stream_key, device) VALUES (?, ?)", (stream_key, device)
        )
        con.execute("DELETE FROM log_post_log WHERE received_at < datetime('now', '-1 day')")
        con.commit()
    finally:
        con.close()


def recent_posts_for(stream_key, device):
    """Posts from this device to this stream in the last hour."""
    con = db.connect()
    try:
        return con.execute(
            "SELECT COUNT(*) AS n FROM log_post_log WHERE stream_key=? AND device=? AND received_at >= datetime('now', '-1 hour')",
            (stream_key, device),
        ).fetchone()["n"]
    finally:
        con.close()


def enqueue(stream_key, device, snapshot_id, collected_at, rows):
    blob = json.dumps(rows)
    con = db.connect()
    try:
        cur = con.execute(
            "INSERT INTO log_buffer (stream_key, device, snapshot_id, collected_at, row_count, rows_json, bytes) VALUES (?,?,?,?,?,?,?)",
            (stream_key, device, snapshot_id, collected_at, len(rows), blob, len(blob)),
        )
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def claim_batch(stream_key, max_rows, max_posts=500):
    """The oldest pending posts whose combined rows stay under max_rows (always at least one post)."""
    con = db.connect()
    try:
        out, total = [], 0
        for c in con.execute(
            "SELECT id, device, snapshot_id, collected_at, row_count, rows_json FROM log_buffer WHERE stream_key=? AND status='pending' ORDER BY id ASC LIMIT ?",
            (stream_key, max_posts),
        ):
            if out and total + c["row_count"] > max_rows:
                break
            out.append(
                {
                    "id": c["id"],
                    "device": c["device"],
                    "snapshotId": c["snapshot_id"],
                    "collectedAt": c["collected_at"],
                    "rows": json.loads(c["rows_json"]),
                }
            )
            total += c["row_count"]
        return out
    finally:
        con.close()


def mark_sent(ids):
    con = db.connect()
    try:
        con.executemany(
            "UPDATE log_buffer SET status='sent', sent_at=datetime('now'), rows_json='[]' WHERE id=?",
            [(i,) for i in ids],
        )
        con.commit()
    finally:
        con.close()


def mark_failed(ids, error, max_attempts):
    con = db.connect()
    try:
        con.executemany(
            "UPDATE log_buffer SET attempts = attempts + 1, last_error=?, status = CASE WHEN attempts + 1 >= ? THEN 'failed' ELSE 'pending' END WHERE id=?",
            [(error[:300], max_attempts, i) for i in ids],
        )
        con.commit()
    finally:
        con.close()


def purge_old():
    con = db.connect()
    try:
        a = con.execute(
            "DELETE FROM log_buffer WHERE status='sent' AND sent_at < datetime('now', '-14 days')"
        ).rowcount
        b = con.execute(
            "DELETE FROM log_buffer WHERE status='failed' AND received_at < datetime('now', '-30 days')"
        ).rowcount
        con.commit()
        return a + b
    finally:
        con.close()


def purge_unsent():
    """With no sink nothing drains the buffer: unsent posts older than LOG_INTAKE_UNSENT_DAYS (default 2) are dropped."""
    try:
        days = int(float(os.environ.get("LOG_INTAKE_UNSENT_DAYS", "")))
    except ValueError:
        days = 0
    con = db.connect()
    try:
        n = con.execute(
            "DELETE FROM log_buffer WHERE status='pending' AND received_at < datetime('now', ?)",
            (f"-{days if days > 0 else 2} days",),
        ).rowcount
        con.commit()
        return n
    finally:
        con.close()


def buffer_stats(stream_key):
    con = db.connect()
    try:
        by = {
            r["status"]: r["n"]
            for r in con.execute(
                "SELECT status, COUNT(*) AS n FROM log_buffer WHERE stream_key=? GROUP BY status",
                (stream_key,),
            )
        }
        t = con.execute(
            "SELECT MAX(sent_at) AS s, MAX(received_at) AS r FROM log_buffer WHERE stream_key=?",
            (stream_key,),
        ).fetchone()
        return {
            "pending": by.get("pending", 0),
            "sent": by.get("sent", 0),
            "failed": by.get("failed", 0),
            "lastSentAt": t["s"],
            "lastReceivedAt": t["r"],
        }
    finally:
        con.close()
