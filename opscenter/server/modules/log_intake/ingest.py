"""
ingest.py
Purpose: The receiver (log intake E1, E2): one post route per stream with one ingest key per stream. It only validates and buffers; it never
         touches the sink in the request path, so a slow or down sink cannot slow a device down. `handle` is a pure function of the request
         facts, so the server route is a thin adapter and the tests need no HTTP.
Date:    2026-11-07
Notes:   Ported from the reference implementation. Its key store is the key slot here: `verify_key(api_key, integration_key)` returns the key's name when
         the key is valid for that stream's integration key, else None (null default: every key is refused, so nothing is accepted until a consumer
         supplies one). Hooks `on_rows(stream, device, rows)` (enrichment, never delays the device) and `audit(status, details)`.
Envelope: {"schemaVersion": "1.0", "source": "<device>", "snapshotId": "...", "collectedAt": "<ISO>", "records": [ {...}, ... ]}
Answers:  404 unknown or inactive stream, 401 missing/invalid key, 413 too large or too many rows, 400 bad envelope or no valid record,
          503 (Retry-After 900) when the buffer is over its cap, 429 (Retry-After 3600) over the device's hourly limit, 202 accepted.
"""

from __future__ import annotations

import contextlib

from . import buffer, current_store, forwarder, stream_store
from . import streams as st


def handle(
    stream_key,
    api_key,
    content_length,
    body,
    verify_key=None,
    on_rows=None,
    audit=None,
    extra_reserved=(),
):
    """Returns (status, json body, headers). `body` is the parsed JSON (a dict) or None."""
    audit = audit or (lambda status, details: None)
    stream = stream_store.get_stream(stream_key)
    if not stream or not stream["active"]:
        return 404, {"success": False, "message": "Stream not found"}, {}
    if not api_key:
        audit(401, {"stream": stream["key"], "reason": "missing api key"})
        return 401, {"success": False, "message": "X-Api-Key header required"}, {}
    info = verify_key(api_key, stream["integrationKey"]) if verify_key else None
    if not info:
        audit(401, {"stream": stream["key"], "reason": "invalid, revoked, or wrong-scope key"})
        return 401, {"success": False, "message": "Invalid or revoked API key"}, {}
    key_name = (
        info if isinstance(info, str) else (info.get("name") if isinstance(info, dict) else "key")
    )
    if (content_length or 0) > stream["maxPostBytes"]:
        audit(413, {"stream": stream["key"], "keyName": key_name, "reason": "payload too large"})
        return 413, {"success": False, "message": "Payload too large"}, {}
    b = body if isinstance(body, dict) else {}
    source = b.get("source").strip()[:120] if isinstance(b.get("source"), str) else ""
    snapshot_id = b.get("snapshotId").strip()[:200] if isinstance(b.get("snapshotId"), str) else ""
    collected_at = (
        b.get("collectedAt").strip()[:40] if isinstance(b.get("collectedAt"), str) else ""
    )
    if (
        b.get("schemaVersion") != "1.0"
        or not source
        or not snapshot_id
        or not collected_at
        or not isinstance(b.get("records"), list)
    ):
        return (
            400,
            {
                "success": False,
                "message": "schemaVersion 1.0, source, snapshotId, collectedAt and a records array are required",
            },
            {},
        )
    if len(b["records"]) > stream["maxRowsPerPost"]:
        audit(
            413,
            {
                "stream": stream["key"],
                "keyName": key_name,
                "reason": "too many rows",
                "rows": len(b["records"]),
            },
        )
        return (
            413,
            {"success": False, "message": f"At most {stream['maxRowsPerPost']} records per post"},
            {},
        )
    # Back-pressure first: tell devices to come back later instead of growing the buffer without bound. Only a registered sink drains the
    # buffer; without one, buffering would just fill the database, and the current snapshot below is all reports need.
    buffering = forwarder.get_sink() is not None
    if buffering and (
        buffer.pending_count(stream["key"]) >= buffer.MAX_PENDING_POSTS
        or buffer.pending_bytes() >= buffer.max_pending_bytes()
    ):
        return (
            503,
            {"success": False, "message": "Receiver is catching up, retry later"},
            {"Retry-After": "900"},
        )
    if buffer.recent_posts_for(stream["key"], source) >= stream["postsPerDevicePerHour"]:
        return (
            429,
            {"success": False, "message": "Too many posts from this device"},
            {"Retry-After": "3600"},
        )
    cleaned = st.clean_records(stream, b["records"], extra_reserved)
    rows, rejected = cleaned["rows"], cleaned["rejected"]
    # Rows are tied to the posting source: the forwarder writes Source from the post, never from row content.
    if not rows and b["records"]:
        return 400, {"success": False, "message": "No valid records in the post"}, {}
    try:
        post_id = (
            buffer.enqueue(stream["key"], source, snapshot_id, collected_at, rows)
            if buffering
            else 0
        )
        current_store.save_current(
            stream["key"], source, snapshot_id, collected_at, rows, stream["mode"]
        )
        buffer.record_post(stream["key"], source)
    except Exception:  # noqa: BLE001 - never leak storage detail to a device
        return 500, {"success": False, "message": "Failed to store snapshot"}, {}
    if on_rows:
        with contextlib.suppress(Exception):  # enrichment: never delays or fails the device
            on_rows(stream, source, rows)
    audit(
        202,
        {
            "stream": stream["key"],
            "keyName": key_name,
            "device": source,
            "rows": len(rows),
            "rejected": rejected,
        },
    )
    return 202, {"success": True, "accepted": len(rows), "rejected": rejected, "id": post_id}, {}
