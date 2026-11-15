"""
dashboards.py
Purpose: Check and run a dashboard (reports module R3). A dashboard is a page of panels, each a small query on one stream plus how to draw it; a
         filter bar (a time range and a few dropdowns) narrows every panel at once. Like definitions, a dashboard is data: it is validated here and
         every query goes through the checked engine of its source. A broken panel reports its own error and never takes the page down.
Date:    2026-11-07
Notes:   Ported from the reference implementation. The query a panel runs is its `spec` (the report spec of query.py); a panel with only a
         `measure` runs `{metrics: [measure]}`, which is enough for a stat tile. The reference's worker pool is not here: panels run in order on the
         source, and a `should_stop` callable is checked between panels so a caller that has gone stops the page.

Dashboard: {key?, filters: [{id, label, stream, field}], panels: [{id?, title, stream, measure?, spec?, type, w, h?, timeField?, x?, y?, drill?,
            stat?: {hue, column, compare, shareOf, warnAt, badAt, note}}], refreshSeconds?, defaultRange?: "7"|"30"|"90"|"all"}
Run:       {generatedAt, range, options: {filterId: [value]}, panels: {panelId: {columns, rows, truncated, stat?, error?, rowsSpec?}},
            futureDated: [{stream, field, rows, devices, rowsSpec}]}
API:       check_dashboard(spec, source) -> str | None    run_dashboard(spec, input, source, should_stop=None) -> run
           parse_range(value, fallback="30") -> "all" | int    panel_spec(panel) -> spec
"""

from __future__ import annotations

import datetime as dt
import re

from . import query, sources

PANEL_TYPES = ("stat", "line", "area", "bar", "hbar", "donut", "table")
RANGE_PRESETS = ("7", "30", "90", "all")
MAX_PANELS = 40
ID_RE = re.compile(r"^[a-z0-9_-]{1,40}$")


def panel_spec(p):
    if isinstance(p.get("spec"), dict):
        return {**query.empty_spec(), **p["spec"]}
    return {**query.empty_spec(), "metrics": [p["measure"]] if p.get("measure") else []}


def _pid(p, i):
    return p["id"] if p.get("id") else str(i)


def _probe(source, stream, **kw):
    return query.check_spec(stream, {**query.empty_spec(), **kw})


def check_dashboard(spec, source):
    """The first problem with a dashboard, None when it is fine."""
    if not isinstance(spec, dict):
        return "Dashboard definition is missing"
    panels, filters = spec.get("panels"), spec.get("filters") or []
    if not isinstance(panels, list):
        return "panels must be a list"
    if not isinstance(filters, list):
        return "filters must be a list"
    if len(panels) > MAX_PANELS:
        return f"A dashboard holds at most {MAX_PANELS} panels"
    if spec.get("defaultRange") is not None and spec["defaultRange"] not in RANGE_PRESETS:
        return "defaultRange must be 7, 30, 90 or all"
    rs = spec.get("refreshSeconds")
    if rs is not None and not (isinstance(rs, int) and not isinstance(rs, bool) and rs >= 0):
        return "refreshSeconds must be a whole number of seconds"
    fids = set()
    for f in filters:
        if not isinstance(f.get("id"), str) or not ID_RE.match(f["id"]):
            return f"Filter id must be lowercase letters, digits, - or _: {f.get('id')}"
        if f["id"] in fids:
            return f"Duplicate filter id: {f['id']}"
        fids.add(f["id"])
        if not str(f.get("label") or "").strip():
            return f"Filter {f['id']} needs a label"
        s = source.get_stream(f.get("stream"))
        if not s:
            return f"Filter {f['id']}: stream not found: {f.get('stream')}"
        err = _probe(source, s, groupBy=[f.get("field")], metrics=["rows"])
        if err:
            return f"Filter {f['id']}: {err}"
    ids = set()
    for i, p in enumerate(panels):
        if not isinstance(p, dict):
            return f"Panel {i + 1} must be an object"
        pid = _pid(p, i)
        if p.get("id") and not ID_RE.match(p["id"]):
            return f"Panel id must be lowercase letters, digits, - or _: {p['id']}"
        if pid in ids:
            return f"Duplicate panel id: {pid}"
        ids.add(pid)
        if not str(p.get("title") or "").strip():
            return f"Panel {pid} needs a title"
        if p.get("type") not in PANEL_TYPES:
            return f"Panel {pid}: unknown type {p.get('type')}"
        w = p.get("w")
        if not isinstance(w, int) or isinstance(w, bool) or not 1 <= w <= 12:
            return f"Panel {pid}: width must be 1 to 12"
        h = p.get("h")
        if h is not None and (not isinstance(h, int) or isinstance(h, bool) or not 1 <= h <= 12):
            return f"Panel {pid}: height must be 1 to 12"
        s = source.get_stream(p.get("stream"))
        if not s:
            return f"Panel {pid}: stream not found: {p.get('stream')}"
        ps = panel_spec(p)
        err = query.check_spec(s, ps)
        if err:
            return f"Panel {pid}: {err}"
        if p.get("timeField"):
            err = _probe(
                source, s, filters=[{"field": p["timeField"], "op": "withinDays", "value": "1"}]
            )
            if err:
                return f"Panel {pid}: {err}"
        if p.get("drill") and p["drill"] not in fids:
            return f"Panel {pid}: drill filter {p['drill']} does not exist"
        if p["type"] == "stat":
            if ps["groupBy"]:
                return f"Panel {pid}: a stat panel shows one number, so it cannot group"
            if not ps["metrics"]:
                return f"Panel {pid}: a stat panel needs a measure"
            share = (p.get("stat") or {}).get("shareOf")
            if share:
                err = _probe(source, s, filters=share, metrics=["rows"])
                if err:
                    return f"Panel {pid}: {err}"
        elif p["type"] != "table" and not (ps["groupBy"] and ps["metrics"]):
            return f"Panel {pid}: a chart needs a group and a measure"
    return None


def parse_range(value, fallback="30"):
    s = str(fallback if value is None else value)
    if s == "all":
        return "all"
    try:
        n = float(s)
        if n == int(n) and 1 <= n <= 3650:
            return int(n)
    except ValueError:
        pass
    try:
        return int(fallback)
    except ValueError:
        return 30


def _num(v):
    return (
        v
        if isinstance(v, (int, float))
        and not isinstance(v, bool)
        and v == v
        and abs(v) != float("inf")
        else None
    )


def _with_scope(spec, extra):
    return {**spec, "filters": [*spec["filters"], *extra]}


def run_dashboard(spec, input=None, source=None, should_stop=None):
    """Every panel in one pass. A broken panel reports its own error and never takes the page down; `should_stop()` returning true between
    panels raises, so a caller that has gone stops the work."""
    input = input or {}
    days = parse_range(input.get("range"), spec.get("defaultRange") or "30")
    picks = input.get("selections") or {}

    def stop():
        if should_stop and should_stop():
            raise RuntimeError("stopped: the caller has gone")

    options = {}
    for f in spec.get("filters") or []:
        stop()
        try:
            s = source.get_stream(f["stream"])
            options[f["id"]] = sources.options(source, s, f["field"]) if s else []
        except Exception:  # noqa: BLE001 - a dropdown that cannot load is empty, the page still renders
            options[f["id"]] = []
    out = {}
    for i, p in enumerate(spec.get("panels") or []):
        stop()
        pid = _pid(p, i)
        try:
            stream = source.get_stream(p["stream"])
            if not stream:
                raise ValueError(f"Stream not found: {p['stream']}")
            ps = panel_spec(p)
            scoped = []
            for f in spec.get("filters") or []:
                picked = picks.get(f["id"])
                if not isinstance(picked, str) or not picked:
                    continue
                # A dropdown narrows a panel only when the panel's stream has that field.
                if _probe(source, stream, groupBy=[f["field"]], metrics=["rows"]):
                    continue
                scoped.append({"field": f["field"], "op": "eq", "value": picked})
            tf = p.get("timeField") or None
            # Future-dated events never count, in any range: they would stretch the axis and skew "last N days".
            sane = [{"field": tf, "op": "notFuture"}] if tf else []
            in_range = [
                *sane,
                *(
                    [{"field": tf, "op": "withinDays", "value": str(days)}]
                    if tf and days != "all"
                    else []
                ),
            ]
            rows_spec = (
                None
                if ps.get("match") == "any"
                else {
                    **query.empty_spec(),
                    "filters": [*ps["filters"], *scoped, *in_range],
                    "columns": query.row_columns_for(stream, ps),
                }
            )

            def run(extra, base=ps, stream=stream, scoped=scoped):
                return source.run(stream, _with_scope(base, [*scoped, *extra]))

            if p["type"] != "stat":
                out[pid] = {**run(in_range), "rowsSpec": rows_spec}
                continue
            st = p.get("stat") or {}

            def column(r, st=st, ps=ps):
                names = [c["name"] for c in r["columns"]]
                if st.get("column") in names:
                    return names.index(st["column"])
                return max(0, len(r["columns"]) - len(ps["metrics"]))

            def pick(r, column=column):
                return _num(r["rows"][0][column(r)]) if r["rows"] else None

            share_of = st.get("shareOf") or []
            percent = bool(share_of)
            prior = (
                [
                    {"field": tf, "op": "withinDays", "value": str(days * 2)},
                    {"field": tf, "op": "olderThanDays", "value": str(days)},
                ]
                if st.get("compare") and tf and days != "all"
                else []
            )
            now = run(in_range)
            matched = run([*in_range, *share_of]) if percent else None
            before = run(prior) if prior else None
            prior_matched = run([*prior, *share_of]) if prior and percent else None
            value, previous, change = pick(now), None, None
            if matched:
                m = pick(matched)
                value = (
                    round(m / value * 1000) / 10
                    if value and m is not None
                    else (0 if value == 0 else None)
                )
            if before:
                previous = pick(before)
                if prior_matched:
                    m = pick(prior_matched)
                    previous = (
                        round(m / previous * 1000) / 10
                        if previous and m is not None
                        else (0 if previous == 0 else None)
                    )
                if value is not None and previous is not None:
                    change = (
                        (0 if value == 0 else None)
                        if previous == 0
                        else round((value - previous) / previous * 1000) / 10
                    )
            out[pid] = {
                **now,
                "stat": {
                    "value": value,
                    "previous": previous,
                    "change": change,
                    "percent": percent,
                },
                "rowsSpec": rows_spec,
            }
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001 - one broken panel reports its own error
            out[pid] = {"columns": [], "rows": [], "truncated": False, "error": str(exc)}

    future, seen = [], set()
    for p in spec.get("panels") or []:
        key = (p.get("stream"), p.get("timeField"))
        if not p.get("timeField") or key in seen:
            continue
        seen.add(key)
        stop()
        try:
            stream = source.get_stream(p["stream"])
            if not stream:
                continue
            q = {
                **query.empty_spec(),
                "filters": [{"field": p["timeField"], "op": "inFuture"}],
                "metrics": ["rows", "devices"],
            }
            r = source.run(stream, q)
            rows = _num(r["rows"][0][0]) if r["rows"] else None
            if rows:
                future.append(
                    {
                        "stream": p["stream"],
                        "field": p["timeField"],
                        "rows": rows,
                        "devices": (_num(r["rows"][0][1]) or 0),
                        "rowsSpec": {**q, "metrics": []},
                    }
                )
        except Exception:  # noqa: BLE001, S110 - the data quality note is optional, the dashboard still renders
            pass
    return {
        "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "range": str(days),
        "options": options,
        "panels": out,
        "futureDated": future,
    }
