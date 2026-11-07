"""
streams.py
Purpose: The pure rules of the log intake module, shared by the receiver, the stream store and the sink (log intake E1 to E3).
         A stream is data (stored in the module's database, edited in a tool), never code. Every sink table the module touches must
         match the configured namespace pattern; anything else is refused before any call is made. A field's physical column never
         changes once allocated and a retired column is never reused (a sink cannot retype or reuse a column), so a rename is a
         mapping and a retype allocates a new column.
Date:    2026-11-07
Notes:   Ported from the reference implementation and its tests. What is the consumer's own is configuration here: the table prefix and suffix
         (`LOG_INTAKE_TABLE_PREFIX`, default "Stream_"; `LOG_INTAKE_TABLE_SUFFIX`, default "") and the sink's own reserved column names (`extra_reserved`).
API:     table_for(name), is_owned_table(name), assert_stream_table(name), validate_field_name(name, extra_reserved=())
         plan_schema(current_fields, desired_fields) -> dict   pure: the same code backs the dry run, the apply and the tests
         clean_records(stream, records) -> {"rows": [...], "rejected": n}
No import side effect.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import re

STREAM_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
TABLE_NAME_RE = re.compile(r"^[A-Za-z0-9]{1,36}$")
COLUMN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,44}$")
FIELD_KINDS = ("string", "boolean", "int", "real", "datetime")
SYSTEM_COLUMNS = ("TimeGenerated", "Source", "SnapshotId", "CollectedAt", "Extra")
MAX_FIELDS = 40
MAX_FIELD_LENGTH = 300
MAX_EXTRA_KEYS = 20
MAX_EXTRA_BYTES = 4000
STREAM_MODES = ("latest", "events")
# Workspace retention for a new stream, in days. An existing stream keeps its own value until edited.
DEFAULT_RETENTION_DAYS = 180
# Starting post limit per device per hour: a latest stream sends one snapshot, an event stream one post per event.
DEFAULT_POSTS_PER_DEVICE_HOUR = 6
DEFAULT_EVENT_POSTS_PER_DEVICE_HOUR = 50
_RESERVED_BASE = {c.lower() for c in SYSTEM_COLUMNS} | {"id"}


def _prefix():
    return os.environ.get("LOG_INTAKE_TABLE_PREFIX", "Stream_")


def _suffix():
    return os.environ.get("LOG_INTAKE_TABLE_SUFFIX", "")


def table_for(name):
    """The sink table for a stream's table name. The name is 1 to 36 letters or digits."""
    if not isinstance(name, str) or not TABLE_NAME_RE.match(name):
        raise ValueError("Table name must be 1-36 letters or digits")
    return f"{_prefix()}{name}{_suffix()}"


def is_owned_table(name):
    """True only for tables this module may create, change or write to."""
    if not isinstance(name, str):
        return False
    p, s = _prefix(), _suffix()
    if not (name.startswith(p) and name.endswith(s) and len(name) >= len(p) + len(s) + 1):
        return False
    return bool(TABLE_NAME_RE.match(name[len(p) : len(name) - len(s) if s else len(name)]))


def assert_stream_table(name):
    if not is_owned_table(name):
        raise ValueError(f"Table {name} is outside the {_prefix()}*{_suffix()} namespace")


def validate_field_name(name, extra_reserved=()):
    """None when the name is fine, else the reason. `extra_reserved` is the sink's own reserved column names."""
    if not isinstance(name, str) or not COLUMN_RE.match(name):
        return f'Field "{name}" must be 2-45 characters: letters, digits, underscore, starting with a letter'
    if name.lower() in _RESERVED_BASE | {str(r).lower() for r in extra_reserved}:
        return f'Field "{name}" is a reserved column name'
    return None


def _allocate_column(name, used):
    lower = {u.lower() for u in used}
    if name.lower() not in lower:
        return name
    for n in range(2, 1000):
        suffix = f"_{n}"
        cand = name[: 45 - len(suffix)] + suffix
        if cand.lower() not in lower:
            return cand
    raise ValueError(f"No free column name for {name}")


def plan_schema(current, desired, extra_reserved=()):
    """The next field list for a desired schema. `current` is [{name, column, kind, required, retired}], `desired` is [{name, kind,
    required}]. Returns {fields, added, removed, retyped, changed, destructive, errors}. Column names are never reused: a retired
    column stays in the list, a retyped field gets a new column, and a removal retires the column. Removals and retypes are
    destructive and need explicit confirmation."""
    errors, seen = [], set()
    for d in desired:
        e = validate_field_name(d.get("name"), extra_reserved)
        if e:
            errors.append(e)
        if d.get("kind") not in FIELD_KINDS:
            errors.append(f'Field "{d.get("name")}" has unknown type "{d.get("kind")}"')
        low = str(d.get("name")).lower()
        if low in seen:
            errors.append(f'Field "{d.get("name")}" is listed twice')
        seen.add(low)
    if len(desired) > MAX_FIELDS:
        errors.append(f"At most {MAX_FIELDS} fields per stream")

    used = {f["column"] for f in current} | set(SYSTEM_COLUMNS)
    active = {f["name"].lower(): f for f in current if not f.get("retired")}
    nxt, added, retyped, retired_now = [], [], [], set()
    for d in desired:
        cur = active.get(str(d.get("name")).lower())
        req = bool(d.get("required"))
        if cur and cur["kind"] == d.get("kind"):
            nxt.append({**cur, "name": d["name"], "required": req})
        elif cur:
            retired_now.add(cur["column"])
            column = _allocate_column(d["name"], used)
            used.add(column)
            nxt.append(
                {
                    "name": d["name"],
                    "column": column,
                    "kind": d["kind"],
                    "required": req,
                    "retired": False,
                }
            )
            retyped.append(
                {"name": d["name"], "from": cur["kind"], "to": d["kind"], "newColumn": column}
            )
        else:
            column = _allocate_column(str(d.get("name")), used)
            used.add(column)
            nxt.append(
                {
                    "name": d.get("name"),
                    "column": column,
                    "kind": d.get("kind"),
                    "required": req,
                    "retired": False,
                }
            )
            added.append(d.get("name"))
    removed, kept = [], {str(d.get("name")).lower() for d in desired}
    for f in current:
        if f.get("retired"):
            nxt.append(f)
        elif f["column"] in retired_now:
            nxt.append({**f, "retired": True})
        elif f["name"].lower() not in kept:
            removed.append(f["name"])
            nxt.append({**f, "retired": True})

    def edited(d):
        c = active.get(str(d.get("name")).lower())
        return bool(c) and (c["required"] != bool(d.get("required")) or c["name"] != d.get("name"))

    changed = bool(added or removed or retyped) or any(edited(d) for d in desired)
    return {
        "fields": nxt,
        "added": added,
        "removed": removed,
        "retyped": retyped,
        "changed": changed,
        "destructive": bool(removed or retyped),
        "errors": errors,
    }


def _clean_string(v):
    if not isinstance(v, str):
        return None
    s = "".join(
        " " if ord(ch) < 32 else ch for ch in v.replace("\u2013", "-").replace("\u2014", "-")
    ).strip()
    return s[:MAX_FIELD_LENGTH] if s else None


def _parse_datetime(raw):
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    try:
        d = dt.datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    d = d.astimezone(dt.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _clean_value(kind, raw):
    if kind == "string":
        return _clean_string(raw)
    if kind == "boolean":
        return raw if isinstance(raw, bool) else None
    if kind == "int":
        return (
            raw
            if isinstance(raw, int) and not isinstance(raw, bool)
            else (int(raw) if isinstance(raw, float) and raw.is_integer() else None)
        )
    if kind == "real":
        return (
            raw
            if isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw)
            else None
        )
    if kind == "datetime":
        return _parse_datetime(raw)
    return None


def clean_records(stream, records, extra_reserved=()):
    """Keeps declared, typed fields keyed by physical column. Undeclared keys go into one capped Extra object so a new field never needs
    a sink change. Rows missing a required field, and anything that is not an object, are counted and dropped."""
    active = [f for f in stream["fields"] if not f.get("retired")]
    declared = {f["name"] for f in active}
    rows, rejected = [], 0
    for rec in records:
        if not isinstance(rec, dict):
            rejected += 1
            continue
        out, ok = {}, True
        for f in active:
            val = _clean_value(f["kind"], rec.get(f["name"]))
            if f.get("required") and (val is None or val == ""):
                ok = False
            out[f["column"]] = val
        if not ok:
            rejected += 1
            continue
        extra, n = {}, 0
        for k, v in rec.items():
            if k in declared or n >= MAX_EXTRA_KEYS or validate_field_name(k, extra_reserved):
                continue
            if isinstance(v, str):
                cv = _clean_string(v)
            elif isinstance(v, (int, float, bool)):
                cv = v
            else:
                cv = None
            if cv is None:
                continue
            extra[k] = cv
            n += 1
        blob = json.dumps(extra, separators=(",", ":")) if n else ""
        out["Extra"] = extra if blob and len(blob) <= MAX_EXTRA_BYTES else None
        rows.append(out)
    return {"rows": rows, "rejected": rejected}
