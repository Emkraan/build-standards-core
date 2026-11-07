"""
stream_store.py
Purpose: Streams as data (log intake E1 to E3): create, list, update, edit the schema, set the sync state and delete, in the module's
         database. Every change is audited through the audit slot, a destructive schema edit needs explicit confirmation, a stream whose
         table was synced to a sink can never be deleted from here, and deleting any stream needs its table name typed.
Date:    2026-11-07
Notes:   Ported from the reference implementation. Its integration definition that carries the ingest keys is the key slot here (`ingest.py`): a stream
         records `integration_key` ("log-<key>") as the name a key provider verifies against.
Audit:   `set_audit(fn)` installs `fn(actor, action, details)`; the default appends one JSON line to `<db folder>/log-intake-audit.jsonl`.
         An audit failure never blocks the change.
"""

from __future__ import annotations

import datetime as dt
import json

from . import db
from . import streams as st

_audit_fn = None


def set_audit(fn):
    global _audit_fn
    _audit_fn = fn


def audit(actor, action, details):
    try:
        if _audit_fn:
            _audit_fn(actor, action, details)
            return
        rec = {
            "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "actor": actor,
            "action": action,
            "details": details,
        }
        with open(db.path().with_name("log-intake-audit.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:  # noqa: BLE001 - audit must never block the change
        pass


def _to_stream(con, r):
    fields = [
        {
            "name": f["name"],
            "column": f["column_name"],
            "kind": f["kind"],
            "required": bool(f["required"]),
            "retired": bool(f["retired"]),
        }
        for f in con.execute(
            "SELECT name, column_name, kind, required, retired FROM log_stream_fields WHERE stream_key = ? ORDER BY position ASC, id ASC",
            (r["key"],),
        )
    ]
    return {
        "key": r["key"],
        "name": r["name"],
        "description": r["description"],
        "table": r["table_name"],
        "integrationKey": r["integration_key"],
        "active": bool(r["active"]),
        "maxRowsPerPost": r["max_rows"],
        "maxPostBytes": r["max_bytes"],
        "retentionDays": r["retention_days"],
        "postsPerDevicePerHour": r["posts_per_device_hour"],
        "mode": "events" if r["mode"] == "events" else "latest",
        "schemaVersion": r["schema_version"],
        "syncState": r["sync_state"],
        "syncError": r["sync_error"],
        "fields": fields,
    }


def list_streams():
    con = db.connect()
    try:
        return [
            _to_stream(con, r)
            for r in con.execute("SELECT * FROM log_streams ORDER BY name COLLATE NOCASE")
        ]
    finally:
        con.close()


def get_stream(key):
    con = db.connect()
    try:
        r = con.execute("SELECT * FROM log_streams WHERE key = ?", (key,)).fetchone()
        return _to_stream(con, r) if r else None
    finally:
        con.close()


def _write_fields(con, key, fields):
    con.execute("DELETE FROM log_stream_fields WHERE stream_key = ?", (key,))
    for i, f in enumerate(fields):
        con.execute(
            "INSERT INTO log_stream_fields (stream_key, name, column_name, kind, required, retired, position) VALUES (?,?,?,?,?,?,?)",
            (
                key,
                f["name"],
                f["column"],
                f["kind"],
                1 if f.get("required") else 0,
                1 if f.get("retired") else 0,
                i,
            ),
        )


def create_stream(inp, actor, extra_reserved=()):
    """Create a stream. `inp`: {key, name, description?, tableName, fields: [{name, kind, required?}], retentionDays?, postsPerDevicePerHour?, mode?}."""
    if not st.STREAM_KEY_RE.match(str(inp.get("key") or "")):
        raise ValueError("Stream key must be lowercase letters, digits and hyphens")
    if not str(inp.get("name") or "").strip():
        raise ValueError("name is required")
    table = st.table_for(inp.get("tableName"))
    st.assert_stream_table(table)
    if get_stream(inp["key"]):
        raise ValueError(f'Stream "{inp["key"]}" already exists')
    plan = st.plan_schema([], inp.get("fields") or [], extra_reserved)
    if plan["errors"]:
        raise ValueError("; ".join(plan["errors"]))
    if not plan["fields"]:
        raise ValueError("At least one field is required")
    mode = "events" if inp.get("mode") == "events" else "latest"
    con = db.connect()
    try:
        if con.execute(
            "SELECT key FROM log_streams WHERE lower(table_name) = lower(?)", (table,)
        ).fetchone():
            raise ValueError(f"Table {table} is already used by another stream")
        retention = inp.get("retentionDays")
        limit = inp.get("postsPerDevicePerHour")
        con.execute(
            "INSERT INTO log_streams (key, name, description, table_name, integration_key, retention_days, mode, posts_per_device_hour, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                inp["key"],
                inp["name"].strip(),
                (inp.get("description") or "").strip(),
                table,
                f"log-{inp['key']}",
                retention
                if isinstance(retention, int) and not isinstance(retention, bool)
                else st.DEFAULT_RETENTION_DAYS,
                mode,
                limit
                if isinstance(limit, int) and not isinstance(limit, bool)
                else (
                    st.DEFAULT_EVENT_POSTS_PER_DEVICE_HOUR
                    if mode == "events"
                    else st.DEFAULT_POSTS_PER_DEVICE_HOUR
                ),
                actor,
            ),
        )
        _write_fields(con, inp["key"], plan["fields"])
        con.commit()
    finally:
        con.close()
    audit(
        actor,
        "log-intake.stream.create",
        {"stream": inp["key"], "table": table, "fields": len(plan["fields"]), "mode": mode},
    )
    return get_stream(inp["key"])


def _clamp(n, lo, hi, default):
    return (
        min(hi, max(lo, int(n)))
        if isinstance(n, (int, float))
        and not isinstance(n, bool)
        and n == n
        and abs(n) != float("inf")
        else default
    )


def update_stream(key, patch, actor):
    """Edit a stream's settings. Numbers are clamped (posts per hour 1 to 1000, rows 1 to 5000, bytes 1 KiB to 4 MiB, retention 4 to 730
    days); a mode other than latest or events is refused. Retention, post limit and mode changes are audited."""
    cur = get_stream(key)
    if not cur:
        raise KeyError("Stream not found")
    if patch.get("mode") is not None and patch["mode"] not in st.STREAM_MODES:
        raise ValueError("mode must be latest or events")
    nxt = {
        "mode": patch.get("mode") or cur["mode"],
        "posts": _clamp(patch.get("postsPerDevicePerHour"), 1, 1000, cur["postsPerDevicePerHour"]),
        "name": (patch.get("name") or "").strip() or cur["name"],
        "description": (
            patch["description"].strip()
            if isinstance(patch.get("description"), str)
            else cur["description"]
        ),
        "active": patch["active"] if "active" in patch else cur["active"],
        "rows": _clamp(patch.get("maxRowsPerPost"), 1, 5000, cur["maxRowsPerPost"]),
        "bytes": _clamp(patch.get("maxPostBytes"), 1024, 4 * 1024 * 1024, cur["maxPostBytes"]),
        "retention": _clamp(patch.get("retentionDays"), 4, 730, cur["retentionDays"]),
    }
    con = db.connect()
    try:
        con.execute(
            "UPDATE log_streams SET name=?, description=?, active=?, max_rows=?, max_bytes=?, mode=?, posts_per_device_hour=?, retention_days=?, "
            "sync_state = CASE WHEN retention_days <> ? THEN 'pending' ELSE sync_state END, updated_at = datetime('now') WHERE key=?",
            (
                nxt["name"],
                nxt["description"],
                1 if nxt["active"] else 0,
                nxt["rows"],
                nxt["bytes"],
                nxt["mode"],
                nxt["posts"],
                nxt["retention"],
                nxt["retention"],
                key,
            ),
        )
        con.commit()
    finally:
        con.close()
    if nxt["retention"] != cur["retentionDays"]:
        audit(
            actor,
            "log-intake.retention.change",
            {"stream": key, "from": cur["retentionDays"], "to": nxt["retention"]},
        )
    if nxt["posts"] != cur["postsPerDevicePerHour"]:
        audit(
            actor,
            "log-intake.stream.post-limit",
            {"stream": key, "from": cur["postsPerDevicePerHour"], "to": nxt["posts"]},
        )
    if nxt["mode"] != cur["mode"]:
        audit(
            actor, "log-intake.stream.mode", {"stream": key, "from": cur["mode"], "to": nxt["mode"]}
        )
    audit(actor, "log-intake.stream.update", {"stream": key})
    return get_stream(key)


def apply_schema(key, desired, actor, confirm=False, dry_run=False, extra_reserved=()):
    """Plan a schema edit and apply it. A dry run, a change that changes nothing, or a destructive change without `confirm` returns the plan
    and applies nothing. Returns {plan, applied, stream}."""
    cur = get_stream(key)
    if not cur:
        raise KeyError("Stream not found")
    plan = st.plan_schema(cur["fields"], desired, extra_reserved)
    if plan["errors"]:
        raise ValueError("; ".join(plan["errors"]))
    if not plan["changed"] or dry_run or (plan["destructive"] and not confirm):
        return {"plan": plan, "applied": False, "stream": cur}
    con = db.connect()
    try:
        _write_fields(con, key, plan["fields"])
        con.execute(
            "UPDATE log_streams SET schema_version = schema_version + 1, sync_state='pending', sync_error=NULL, updated_at=datetime('now') WHERE key=?",
            (key,),
        )
        con.commit()
    finally:
        con.close()
    audit(
        actor,
        "log-intake.schema.change",
        {
            "stream": key,
            "table": cur["table"],
            "added": plan["added"],
            "removed": plan["removed"],
            "retyped": plan["retyped"],
        },
    )
    return {"plan": plan, "applied": True, "stream": get_stream(key)}


def set_sync_state(key, state, error=None):
    if state not in ("pending", "synced", "error"):
        raise ValueError("state must be pending, synced or error")
    con = db.connect()
    try:
        con.execute(
            "UPDATE log_streams SET sync_state=?, sync_error=? WHERE key=?",
            (state, (error or "")[:300] or None, key),
        )
        con.commit()
    finally:
        con.close()


def delete_stream(key, confirm_table, actor):
    """Delete a stream whose table was never created at the sink. Needs the table name typed. A synced table is never dropped from here."""
    cur = get_stream(key)
    if not cur:
        raise KeyError("Stream not found")
    if confirm_table != cur["table"]:
        raise ValueError(f"Type the table name ({cur['table']}) to confirm")
    if cur["syncState"] == "synced":
        raise ValueError(
            "The sink table exists. Delete it at the sink first; this module does not drop tables."
        )
    con = db.connect()
    try:
        for t in (
            "log_stream_fields",
            "log_stream_current",
            "log_stream_events",
            "log_buffer",
            "log_post_log",
        ):
            con.execute(f"DELETE FROM {t} WHERE stream_key = ?", (key,))
        con.execute("DELETE FROM log_streams WHERE key = ?", (key,))
        con.commit()
    finally:
        con.close()
    audit(actor, "log-intake.stream.delete", {"stream": key, "table": cur["table"]})
