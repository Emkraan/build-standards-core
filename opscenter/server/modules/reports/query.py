"""
query.py
Purpose: The report engine over a stream's current snapshot (reports module R3). A report is a small structured spec, never SQL: field names are
         checked against the stream, values are bound parameters, and the SQL is assembled only from fixed fragments, so a spec cannot reach
         anything outside the stream's own rows.
Date:    2026-11-07
Notes:   Ported from the reference implementation. Differences, all deliberate: the time zone is configuration (`OPSCENTER_REPORTS_TZ`, default
         UTC; the reference had one fixed zone) and the lookup tables are the reports module's own (`log_directory`, `log_catalog`, attached to
         the connection as `lk`, see `connect`). The local day parsing accepts the reference's three formats (YYYY-MM-DD, M/D/YYYY, MMDDYYYY).

Spec:    {match: "all"|"any", filters: [{field, op, value?}], groupBy: [field], metrics: [name], columns: [field], sort?: {by, dir}, limit?}
         field: a stream field, a pseudo field (@device, @collectedAt, @receivedAt), a looked-up field (@user, @email, @department, @title,
                @publisher, @store) or a time bucket "day:<field>", "week:<field>", "month:<field>".
         metric: rows, devices, lastReport, or "<distinct|sum|avg|min|max>:<field>" (sum and avg need a number field).
         ops: eq ne contains startsWith in notIn empty notEmpty gt gte lt lte olderThanDays withinDays between inFuture notFuture.
Stream:  {key, mode: "latest"|"events", fields: [{name, column, kind, retired}]}  (what log_intake.stream_store.get_stream returns)
API:     check_spec(stream, spec) -> str | None     run_local(stream, spec, con) -> {columns: [{name, type}], rows, truncated}
         connect() -> sqlite3 connection with the lookups attached     row_columns_for(stream, spec) -> [field]
         bucket_time(value, unit, tz=None) -> str | None     day_range(value, tz=None) -> (from, to) | None     empty_spec()
"""

from __future__ import annotations

import datetime as dt
import os
import re

from . import dateranges, lookup_db

MAX_LOCAL_ROWS = 10_000
FILTER_OPS = (
    "eq",
    "ne",
    "contains",
    "startsWith",
    "in",
    "notIn",
    "empty",
    "notEmpty",
    "gt",
    "gte",
    "lt",
    "lte",
    "olderThanDays",
    "withinDays",
    "between",
    "inFuture",
    "notFuture",
)
NO_VALUE_OPS = ("empty", "notEmpty", "inFuture", "notFuture")
METRICS = ("rows", "devices", "lastReport")
METRIC_PREFIXES = ("distinct", "sum", "avg", "min", "max")
BUCKET_UNITS = ("day", "week", "month")

DEVICE, COLLECTED, RECEIVED = "@device", "@collectedAt", "@receivedAt"
PSEUDO = {
    DEVICE: {"col": "c.source", "label": "Device", "type": "string"},
    COLLECTED: {"col": "c.collected_at", "label": "Collected", "type": "datetime"},
    RECEIVED: {"col": "c.received_at", "label": "Received", "type": "datetime"},
}
# A looked-up field is a value joined from a cache table by one of the stream's own fields, resolved at ingest.
LOOKUPS = {
    "@user": {
        "table": "log_directory",
        "col": "display_name",
        "id": "account",
        "by": "UserName",
        "label": "User",
        "fallback": True,
    },
    "@email": {
        "table": "log_directory",
        "col": "email",
        "id": "account",
        "by": "UserName",
        "label": "Email",
        "fallback": False,
    },
    "@department": {
        "table": "log_directory",
        "col": "department",
        "id": "account",
        "by": "UserName",
        "label": "Department",
        "fallback": False,
    },
    "@title": {
        "table": "log_directory",
        "col": "job_title",
        "id": "account",
        "by": "UserName",
        "label": "Title",
        "fallback": False,
    },
    "@publisher": {
        "table": "log_catalog",
        "col": "publisher",
        "id": "entry_id",
        "by": "ExtensionId",
        "label": "Store publisher",
        "fallback": False,
    },
    "@store": {
        "table": "log_catalog",
        "col": "store",
        "id": "entry_id",
        "by": "ExtensionId",
        "label": "Store",
        "fallback": False,
    },
}
LOOKUP_SCHEMA = "lk"


def empty_spec():
    return {"match": "all", "filters": [], "groupBy": [], "metrics": [], "columns": []}


def tz_name():
    return os.environ.get("OPSCENTER_REPORTS_TZ") or "UTC"


def connect():
    """A connection on the log intake database with the reports lookups attached as `lk`. The caller closes it."""
    from log_intake import db as intake_db

    con = intake_db.connect()
    con.execute(f"ATTACH DATABASE ? AS {LOOKUP_SCHEMA}", (str(lookup_db.path()),))
    lookup_db.ensure(con, LOOKUP_SCHEMA)
    return con


# ---------------------------------------------------------------------------------------------------------------- time

_DAY_FORMS = (
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), (0, 1, 2)),
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$"), (2, 0, 1)),
    (re.compile(r"^(\d{2})(\d{2})(\d{4})$"), (2, 0, 1)),
)


def parse_day(text):
    """YYYY-MM-DD, M/D/YYYY or MMDDYYYY to a date, None for anything else or an impossible date."""
    s = str(text or "").strip()
    for rx, (yi, mi, di) in _DAY_FORMS:
        m = rx.match(s)
        if m:
            try:
                d = dt.date(int(m.group(yi + 1)), int(m.group(mi + 1)), int(m.group(di + 1)))
            except ValueError:
                return None
            return d if 2000 <= d.year <= 2100 else None
    return None


def _stored(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def day_range(value, tz=None):
    """`start,end` (whole local days, the end day counted in full) to (from, to) in the stored UTC text form, half open. None when it is not two
    valid days or the end is before the start."""
    parts = str(value or "").split(",")
    if len(parts) != 2:
        return None
    a, b = parse_day(parts[0]), parse_day(parts[1])
    if not a or not b or b < a:
        return None
    start, end = dateranges.whole_day_range(a, b, tz or tz_name())
    return _stored(start), _stored(end)


def bucket_time(value, unit, tz=None):
    """The local day, week (its Monday) or month a stored UTC time falls in, as a sortable label (YYYY-MM-DD or YYYY-MM). Anything that is not a
    time returns None, so it groups as blank."""
    if not isinstance(value, str) or not value.strip():
        return None
    t = value.strip().replace(" ", "T")
    if not (t.endswith("Z") or "+" in t or re.search(r"-\d{2}:\d{2}$", t)):
        t += "Z"
    try:
        ts = dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None
    d = ts.astimezone(dateranges._zone(tz or tz_name())).date()
    if unit == "month":
        return f"{d.year}-{d.month:02d}"
    if unit == "week":
        d = d - dt.timedelta(days=d.weekday())
    return d.isoformat()


# ---------------------------------------------------------------------------------------------------------------- spec


def active_fields(stream):
    return [f for f in stream["fields"] if not f.get("retired")]


def col_of(stream, name):
    return next((f for f in active_fields(stream) if f["name"] == name), None)


def key_of(stream, name):
    lk = LOOKUPS.get(name)
    return col_of(stream, lk["by"]) if lk else None


def parse_bucket(name):
    unit, sep, field = str(name).partition(":")
    return (unit, field) if sep and unit in BUCKET_UNITS else None


def parse_metric(m):
    prefix, sep, field = str(m).partition(":")
    return (prefix, field) if sep and prefix in METRIC_PREFIXES else None


def row_columns_for(stream, spec):
    """Columns for the rows behind a panel: every stored field plus every looked-up field the stream can resolve, so an export is complete."""
    extra = [n for n in LOOKUPS if key_of(stream, n)]
    names = [*spec.get("groupBy", []), *[f["field"] for f in spec.get("filters", [])]]
    for n in (re.sub(r"^[a-z]+:(?=@)", "", x) for x in names):
        if n in LOOKUPS and n not in extra:
            extra.append(n)
    return [*[f["name"] for f in active_fields(stream)], *extra]


def _is_number(v):
    try:
        return str(v).strip() != "" and float(v) == float(v) and abs(float(v)) != float("inf")
    except ValueError:
        return False


def _whole_days(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return int(n) if n == int(n) and 0 <= n <= 36500 else None


def check_spec(stream, spec):
    """The first problem with a spec, None when it is fine."""
    if not isinstance(spec, dict):
        return "Report definition is missing"

    def plain(n):
        return n in PSEUDO or col_of(stream, n) is not None or key_of(stream, n) is not None

    def is_time(n):
        return (PSEUDO.get(n) or {}).get("type") == "datetime" or (col_of(stream, n) or {}).get(
            "kind"
        ) == "datetime"

    def known(n):
        b = parse_bucket(n)
        return is_time(b[1]) if b else plain(n)

    if spec.get("match") not in (None, "all", "any"):
        return "match must be all or any"
    for f in spec.get("filters") or []:
        if not known(f.get("field")):
            return f"Unknown field in filter: {f.get('field')}"
        if f.get("op") not in FILTER_OPS:
            return f"Unknown filter operator: {f.get('op')}"
        if f["op"] not in NO_VALUE_OPS and not isinstance(f.get("value"), str):
            return f"Filter on {f['field']} needs a value"
        if f["op"] in ("olderThanDays", "withinDays") and _whole_days(f.get("value")) is None:
            return f"Filter on {f['field']} needs a whole number of days"
        if f["op"] == "between" and not day_range(f.get("value")):
            return f"Filter on {f['field']} needs two dates (start,end) with the end on or after the start"
    for g in spec.get("groupBy") or []:
        if not known(g):
            return f"Unknown group field: {g}"
    for c in spec.get("columns") or []:
        if not known(c):
            return f"Unknown column: {c}"
    for m in spec.get("metrics") or []:
        if m in METRICS:
            continue
        pm = parse_metric(m)
        f = col_of(stream, pm[1]) if pm else None
        if not pm or not f:
            return f"Unknown metric: {m}"
        if pm[0] in ("sum", "avg") and f["kind"] not in ("int", "real"):
            return f"{pm[0]} needs a number field: {pm[1]}"
    if (spec.get("groupBy") or []) and not (spec.get("metrics") or []):
        return "Grouping needs at least one metric"
    return None


# ---------------------------------------------------------------------------------------------------------------- run


def _register(con):
    con.create_function("bucket_ts", 2, lambda v, u: bucket_time(v, u), deterministic=True)


def run_local(stream, spec, con):
    """Run a spec on `con` (from `connect`, or any connection with the intake tables and the attached lookups). Raises ValueError for a bad spec."""
    err = check_spec(stream, spec)
    if err:
        raise ValueError(err)
    _register(con)
    spec = {**empty_spec(), **spec}

    def val(name):
        """A column expression and the bound parameters it needs, in placeholder order."""
        b = parse_bucket(name)
        if b:
            inner_sql, inner_args = val(b[1])
            return f"bucket_ts({inner_sql}, ?)", [*inner_args, b[0]]
        ps = PSEUDO.get(name)
        if ps:
            return ps["col"], []
        lk = LOOKUPS.get(name)
        idc = (key_of(stream, name) or {}).get("column")
        if lk and idc:
            raw = "json_extract(j.value, ?)"
            look = f"(SELECT d.{lk['col']} FROM {LOOKUP_SCHEMA}.{lk['table']} d WHERE d.{lk['id']} = LOWER(TRIM({raw})))"
            if lk["fallback"]:
                return f"COALESCE({look}, {raw})", [f"$.{idc}", f"$.{idc}"]
            return look, [f"$.{idc}"]
        return "json_extract(j.value, ?)", [f"$.{(col_of(stream, name) or {}).get('column')}"]

    selects, select_args = [], []

    def add_field(name):
        b = parse_bucket(name)
        ps = PSEUDO.get(name)
        f = None if ps else col_of(stream, name)
        lk = LOOKUPS.get(name)
        sql, args = val(name)
        select_args.extend(args)
        label = (
            (b[0].capitalize() if b else None)
            or (ps or {}).get("label")
            or (lk or {}).get("label")
            or name
        )
        kind = "string" if b else (ps or {}).get("type") or (f or {}).get("kind") or "string"
        selects.append(
            {"sql": sql, "label": label, "type": kind, "bool": bool(f and f["kind"] == "boolean")}
        )

    aggregate = bool(spec["groupBy"] or spec["metrics"])
    if aggregate:
        for g in spec["groupBy"]:
            add_field(g)
        for m in spec["metrics"]:
            if m == "rows":
                selects.append({"sql": "COUNT(*)", "label": "Rows", "type": "long", "bool": False})
            elif m == "devices":
                selects.append(
                    {
                        "sql": "COUNT(DISTINCT c.source)",
                        "label": "Devices",
                        "type": "long",
                        "bool": False,
                    }
                )
            elif m == "lastReport":
                selects.append(
                    {
                        "sql": "MAX(c.collected_at)",
                        "label": "LastReport",
                        "type": "datetime",
                        "bool": False,
                    }
                )
            else:
                prefix, field = parse_metric(m)
                sql, args = val(field)
                select_args.extend(args)
                kind = (col_of(stream, field) or {}).get("kind", "string")
                expr = {
                    "distinct": (f"COUNT(DISTINCT {sql})", "long"),
                    "sum": (f"SUM(CAST({sql} AS REAL))", "real"),
                    "avg": (f"AVG(CAST({sql} AS REAL))", "real"),
                    "min": (f"MIN({sql})", kind),
                    "max": (f"MAX({sql})", kind),
                }[prefix]
                selects.append(
                    {
                        "sql": expr[0],
                        "label": f"{prefix.capitalize()} {field}",
                        "type": expr[1],
                        "bool": False,
                    }
                )
    else:
        add_field(DEVICE)
        cols = spec["columns"] or [f["name"] for f in active_fields(stream)]
        for c in cols:
            if c != DEVICE:
                add_field(c)

    clauses, clause_args = [], []
    for f in spec["filters"]:
        sql, args = val(f["field"])
        op, value = f["op"], f.get("value")
        text = f"COALESCE(CAST({sql} AS TEXT), '')"
        when = f"REPLACE(REPLACE({text}, 'T', ' '), 'Z', '')"
        # Each use of the column in the SQL repeats its parameters, so each clause lists them once per use.
        if op == "eq":
            clauses.append(f"LOWER({text}) = LOWER(?)")
            clause_args += [*args, value]
        elif op == "ne":
            clauses.append(f"LOWER({text}) <> LOWER(?)")
            clause_args += [*args, value]
        elif op == "contains":
            clauses.append(f"INSTR(LOWER({text}), LOWER(?)) > 0")
            clause_args += [*args, value]
        elif op == "startsWith":
            clauses.append(f"SUBSTR(LOWER({text}), 1, LENGTH(?)) = LOWER(?)")
            clause_args += [*args, value, value]
        elif op in ("in", "notIn"):
            items = [x.strip().lower() for x in (value or "").split(",") if x.strip()][:200]
            if not items:
                raise ValueError(f"Filter on {f['field']} needs at least one value")
            clauses.append(
                f"LOWER({text}) {'IN' if op == 'in' else 'NOT IN'} ({','.join('?' for _ in items)})"
            )
            clause_args += [*args, *items]
        elif op == "empty":
            clauses.append(f"{text} = ''")
            clause_args += args
        elif op == "notEmpty":
            clauses.append(f"{text} <> ''")
            clause_args += args
        elif op in ("gt", "gte", "lt", "lte"):
            cmp = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
            v = value or ""
            if _is_number(v):
                clauses.append(f"{text} <> '' AND CAST({sql} AS REAL) {cmp} ?")
                clause_args += [*args, *args, float(v)]
            else:
                clauses.append(
                    f"{text} <> '' AND {when} {cmp} REPLACE(REPLACE(?, 'T', ' '), 'Z', '')"
                )
                clause_args += [*args, *args, v]
        elif op == "between":
            lo, hi = day_range(value)
            clauses.append(f"{text} <> '' AND {when} >= ? AND {when} < ?")
            clause_args += [*args, *args, lo, *args, hi]
        elif op == "inFuture":
            clauses.append(f"{text} <> '' AND {when} > datetime('now', '+1 day')")
            clause_args += [*args, *args]
        elif op == "notFuture":
            clauses.append(f"{text} = '' OR {when} <= datetime('now', '+1 day')")
            clause_args += [*args, *args]
        elif op in ("olderThanDays", "withinDays"):
            cmp = "<" if op == "olderThanDays" else ">="
            clauses.append(f"{text} <> '' AND {when} {cmp} datetime('now', ?)")
            clause_args += [*args, *args, f"-{_whole_days(value)} days"]

    joiner = " OR " if spec["match"] == "any" else " AND "
    where, where_args = ["c.stream_key = ?"], [stream["key"]]
    if clauses:
        where.append("(" + joiner.join(f"({c})" for c in clauses) + ")")
        where_args += clause_args

    sort = spec.get("sort")
    if sort:
        idx = next((i for i, s in enumerate(selects) if s["label"] == sort.get("by")), -1)
        if idx < 0:
            raise ValueError(f'Sort column "{sort.get("by")}" is not in the report')
        order = f" ORDER BY {idx + 1} {'DESC' if sort.get('dir') == 'desc' else 'ASC'}"
    elif aggregate and spec["metrics"]:
        order = f" ORDER BY {len(spec['groupBy']) + 1} DESC"
    else:
        order = " ORDER BY 1 ASC"
    try:
        limit = min(MAX_LOCAL_ROWS, max(1, int(spec.get("limit") or MAX_LOCAL_ROWS)))
    except (TypeError, ValueError):
        limit = MAX_LOCAL_ROWS
    # Group by expressions are referenced by position, so they need no parameters of their own.
    group = (
        f" GROUP BY {', '.join(str(i + 1) for i in range(len(spec['groupBy'])))}"
        if aggregate and spec["groupBy"]
        else ""
    )
    source = "log_stream_events" if stream.get("mode") == "events" else "log_stream_current"
    sql = (
        f"SELECT {', '.join(s['sql'] for s in selects)} FROM {source} c, json_each(c.rows_json) j "
        f"WHERE {' AND '.join(where)}{group}{order} LIMIT {limit + 1}"
    )
    cur = con.execute(sql, [*select_args, *where_args])
    rows = [list(r) for r in cur.fetchall()]
    truncated = len(rows) > limit
    out = [
        [(bool(v) if selects[i]["bool"] and v is not None else v) for i, v in enumerate(r)]
        for r in rows[:limit]
    ]
    return {
        "columns": [{"name": s["label"], "type": s["type"]} for s in selects],
        "rows": out,
        "truncated": truncated,
    }
