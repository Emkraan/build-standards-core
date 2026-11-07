"""
forwarder.py
Purpose: Sends buffered posts to the sink in batches (log intake E6). The sink is a slot: an object with `name`, `send(table, rows)` (must
         raise on failure) and optionally `isReady(table)`/`is_ready(table)` (False while a stream has no table at the sink: its posts stay
         buffered instead of failing). With no sink registered nothing is sent and the receiver does not buffer. Source is the posting device
         and is written here, from the post and never from row content.
Date:    2026-11-07
Notes:   Ported from the reference implementation. The timer is the server's own background-task list (registered by routes only when the module is on);
         nothing starts here.
"""

from __future__ import annotations

from . import buffer, current_store, stream_store
from . import streams as st

MAX_ROWS_PER_CALL = 1500  # a sink call stays well under a typical 1 MB limit
MAX_ATTEMPTS = 8

_sink = None


def set_sink(sink):
    global _sink
    _sink = sink


def get_sink():
    return _sink


def sink_rows(post):
    """Stream-shaped rows for the sink: Source, SnapshotId and CollectedAt come from the post, not from the row."""
    return [
        dict(
            r, Source=post["device"], SnapshotId=post["snapshotId"], CollectedAt=post["collectedAt"]
        )
        for r in post["rows"]
    ]


def _ready(sink, table):
    fn = getattr(sink, "is_ready", None) or getattr(sink, "isReady", None)
    return True if fn is None else bool(fn(table))


def flush_stream(stream_key, max_batches=20):
    """Send pending posts of one stream. Safe to call repeatedly; does nothing without a sink. Returns {stream, posts, rows, failed}."""
    result = {"stream": stream_key, "posts": 0, "rows": 0, "failed": 0}
    stream, sink = stream_store.get_stream(stream_key), _sink
    if not stream or not sink or not stream["active"]:
        return result
    st.assert_stream_table(stream["table"])
    if not _ready(sink, stream["table"]):
        return result
    for _ in range(max_batches):
        batch = buffer.claim_batch(stream_key, MAX_ROWS_PER_CALL)
        if not batch:
            break
        ids = [b["id"] for b in batch]
        rows = [r for b in batch for r in sink_rows(b)]
        try:
            sink.send(stream["table"], rows)
        except Exception as e:  # noqa: BLE001 - kept pending, failed after the attempt cap
            buffer.mark_failed(ids, str(e), MAX_ATTEMPTS)
            result["failed"] += len(batch)
            break
        buffer.mark_sent(ids)
        result["posts"] += len(batch)
        result["rows"] += len(rows)
    return result


def flush_all():
    out = [flush_stream(s["key"]) for s in stream_store.list_streams()]
    try:
        buffer.purge_old()
        current_store.purge_events()
        if _sink is None:
            buffer.purge_unsent()
    except Exception:  # noqa: BLE001 - housekeeping only
        pass
    return out
