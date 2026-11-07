"""
routes.py
Purpose: The reports HTTP routes, registered only when a consumer turns the module on (`OPSCENTER_REPORTS`). Importing this file registers nothing
         and touches nothing; `register(registry, provider)` adds the routes and seeds the shipped dashboards.
Date:    2026-11-07
Notes:   Writes are POST (the registry has no PUT or DELETE), so a save of one dashboard is `POST /api/dashboards/<key>` and a delete is
         `POST /api/dashboards/<key>/delete`. Every route needs the provider's `authorize` (null default refuses everything). The store is
         `OPSCENTER_REPORTS_DASHBOARDS` (default `<state>/dashboards.json`).

Provider (all optional, `OPSCENTER_REPORTS_PROVIDER=path/to/file.py:ClassName`):
         authorize(headers, action, key) -> actor | falsy      source() -> a source (sources.py contract), default the local snapshot source
         dashboards() -> {"defaults": [definition], "version": int}   the shipped dashboards, seeded by version, an edited copy never overwritten

Routes:  GET  /api/dashboards                  action dashboards.read    rows {key, title, description, def, isDefault, modified, canEdit}
         POST /api/dashboards                  dashboards.write          {def} create or replace by key
         POST /api/dashboards/<key>            dashboards.write          {def} replace (the key is the path's)
         POST /api/dashboards/<key>/delete     dashboards.write
         POST /api/dashboards/<key>/reset      dashboards.write          back to the shipped copy
         GET  /api/dashboards/export           dashboards.read           {dashboards: [def]}
         POST /api/dashboards/import           dashboards.write          {dashboards: [def]} every one validated, a bad one refuses the whole batch
         POST /api/dashboards/run              dashboards.read           {key | def, range?, selections?} the run result of dashboards.py
         POST /api/reports/query               reports.run               {stream, spec} one report spec on the source
Answers: {success: true, data} or the registry's error mapping (ValueError 400, KeyError 404, PermissionError 403)
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import optional_provider as op
import paths

from . import dashboards, definitions, sources

RESERVED_KEYS = ("run", "import", "export")
KEY = r"([a-z0-9][a-z0-9_-]{0,63})"


def _ok(data=None):
    return {"success": True, "data": data}


def store_path():
    return Path(
        os.environ.get("OPSCENTER_REPORTS_DASHBOARDS") or paths.state_dir() / "dashboards.json"
    )


def register(r, provider):
    store = definitions.Store(store_path())
    meth = lambda name: op.method(provider, name)  # noqa: E731
    shipped = (meth("dashboards") or (lambda: {"defaults": [], "version": 0}))()
    defaults, version = shipped.get("defaults") or [], int(shipped.get("version") or 0)
    if defaults:
        store.seed(defaults, version)

    def source():
        return (meth("source") or sources.LocalSource)()

    def who(q, action, key=None):
        return op.actor_of(q.headers, provider, action, key)

    def allowed(q, action, key):
        try:
            who(q, action, key)
            return True
        except PermissionError:
            return False

    def checked(defn, key=None):
        if not isinstance(defn, dict):
            raise ValueError("def must be a dashboard definition object")
        if key is not None:
            defn = {**defn, "key": key}
        if defn.get("key") in RESERVED_KEYS:
            raise ValueError(f"key {defn['key']!r} is reserved")
        problems = definitions.validate(defn)
        if problems:
            raise ValueError("; ".join(problems))
        problem = dashboards.check_dashboard(defn, source())
        if problem:
            raise ValueError(problem)
        return defn

    def row(q, key, rec):
        d = rec["def"]
        return {
            "key": key,
            "title": d.get("title"),
            "description": d.get("description"),
            "def": d,
            "isDefault": rec.get("shipped_version") is not None and not rec.get("edited"),
            "modified": rec.get("at"),
            "canEdit": allowed(q, "dashboards.write", key),
        }

    def list_(q):
        who(q, "dashboards.read")
        return _ok(
            [
                row(q, k, rec)
                for k, rec in sorted(store.records().items())
                if allowed(q, "dashboards.read", k)
            ]
        )

    def save_new(q):
        who(q, "dashboards.write")
        defn = checked(q.payload().get("def"))
        who(q, "dashboards.write", defn["key"])
        return _ok({"key": store.save(defn)})

    def save_one(q):
        who(q, "dashboards.write", q.groups[0])
        return _ok({"key": store.save(checked(q.payload().get("def"), q.groups[0]))})

    def delete(q):
        who(q, "dashboards.write", q.groups[0])
        store.delete(q.groups[0])
        return _ok()

    def reset(q):
        who(q, "dashboards.write", q.groups[0])
        store.reset(q.groups[0], defaults)
        return _ok(store.get(q.groups[0]))

    def export(q):
        who(q, "dashboards.read")
        return _ok(
            {
                "dashboards": [
                    rec["def"]
                    for k, rec in sorted(store.records().items())
                    if allowed(q, "dashboards.read", k)
                ]
            }
        )

    def import_(q):
        who(q, "dashboards.write")
        items = q.payload().get("dashboards")
        if not isinstance(items, list):
            raise ValueError("dashboards must be a list")
        # Every definition is checked before any is stored: a bad one refuses the whole batch.
        good = [checked(d) for d in items]
        for d in good:
            who(q, "dashboards.write", d["key"])
        return _ok({"keys": [store.save(d) for d in good]})

    def run(q):
        p = q.payload()
        key = p.get("key")
        if key:
            who(q, "dashboards.read", key)
            defn = store.get(key)
            if defn is None:
                raise KeyError(key)
        else:
            who(q, "dashboards.read")
            defn = p.get("def")
            problem = dashboards.check_dashboard(defn, source())
            if problem:
                raise ValueError(problem)
        problem = dashboards.check_dashboard(defn, source())
        if problem:
            raise ValueError(problem)
        return _ok(
            dashboards.run_dashboard(
                defn, {"range": p.get("range"), "selections": p.get("selections")}, source()
            )
        )

    def query_(q):
        who(q, "reports.run")
        p = q.payload()
        src = source()
        stream = src.get_stream(p.get("stream"))
        if not stream:
            raise KeyError("Stream not found")
        return _ok(src.run(stream, p.get("spec")))

    r.add("GET", "/api/dashboards", list_, name="reports.list")
    r.add("GET", "/api/dashboards/export", export, name="reports.export")
    r.add("POST", "/api/dashboards", save_new, name="reports.save-new")
    r.add("POST", "/api/dashboards/import", import_, name="reports.import")
    r.add("POST", "/api/dashboards/run", run, name="reports.run")
    r.add("POST", re.compile(rf"/api/dashboards/{KEY}"), save_one, name="reports.save")
    r.add("POST", re.compile(rf"/api/dashboards/{KEY}/delete"), delete, name="reports.delete")
    r.add("POST", re.compile(rf"/api/dashboards/{KEY}/reset"), reset, name="reports.reset")
    r.add("POST", "/api/reports/query", query_, name="reports.query")
