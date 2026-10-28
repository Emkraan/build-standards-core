#!/usr/bin/env python3
"""Ops center API for Action Center routing.

GET  /api/ac-routing            -> rules, sources, defaults, people, last collector report
POST /api/ac-routing/preview    -> {match, route, scope?} what the rule would catch now
POST /api/ac-routing/rule       -> {match, route, where?, reason?, scope?, from_fp?} add (idempotent)
POST /api/ac-routing/disable    -> {id, disabled: bool}
POST /api/ac-routing/delete     -> {id} (click rules only)

Every write re-bundles the Action Center in the background, so the routed item leaves the
served action-center.json within seconds. The client also drops it at once (live-actions 1.1).
Writes touch only ac-routing.json. Loopback and same-origin are enforced by server.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "engine"))
import collect  # noqa: E402
import paths  # noqa: E402
import routing  # noqa: E402

DASH = paths.dashboard_dir()
# The command that re-bundles the board after a write (a script path, optional): without it the next refresh tick
# picks the rule up.
REFRESH = (
    Path(os.environ["OPSCENTER_REFRESH_CMD"]) if os.environ.get("OPSCENTER_REFRESH_CMD") else None
)
_cache = {"at": 0.0, "cands": None}
_lock = threading.Lock()
CACHE_S = 60


def _json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def get():
    try:
        data = routing.load()
        err = None
    except routing.RoutingError as exc:
        data, err = {"rules": [], "sources": {}, "defaults": {}, "people": {}}, str(exc)
    rep = _json(DASH / "ac-routing-report.json", {})
    # Board items the refresh routed away (board_build applies the same rules to the final
    # items, including the 1:1, file and automation items the collector never sees).
    served = _json(
        Path(
            os.environ.get("OPSCENTER_SERVED_BOARD")
            or paths.state_dir() / "public-data" / "action-center.json"
        ),
        {},
    )
    seen = {a.get("key") for a in rep.get("items_routed_away", [])}
    rep["items_routed_away"] = list(rep.get("items_routed_away", [])) + [
        a
        for a in (served.get("routing") or {}).get("items_routed_away", [])
        if a.get("key") not in seen
    ]
    hits = {}
    for c in rep.get("routed_away", []):
        hits[c.get("rule")] = hits.get(c.get("rule"), 0) + 1
    for c in rep.get("items_routed_away", []):
        hits[c.get("rule")] = hits.get(c.get("rule"), 0) + 1
    rules = [dict(r, hits=hits.get(r["id"], 0)) for r in data.get("rules", [])]
    return {
        "rules": rules,
        "sources": data.get("sources", {}),
        "defaults": data.get("defaults", {}),
        "people": data.get("people", {}),
        "report": rep,
        "error": err,
    }


def _candidates():
    with _lock:
        if _cache["cands"] is not None and time.time() - _cache["at"] < CACHE_S:
            return _cache["cands"]
        res = collect.collect()
        _cache.update(at=time.time(), cands=res["candidates"])
        return res["candidates"]


def _items():
    ac = _json(DASH / "action-center.json", {})
    return ac.get("items", [])


def _clean(payload):
    if not isinstance(payload, dict):
        raise routing.RoutingError("body must be an object")
    match = payload.get("match")
    route = payload.get("route")
    scope = payload.get("scope") or "all"
    if not isinstance(match, dict):
        raise routing.RoutingError("match must be an object")
    match = {k: v for k, v in match.items() if v not in (None, "", [])}
    return match, route, scope


def preview(payload):
    match, route, scope = _clean(payload)
    cands = _candidates() if scope != "items" else []
    items = _items() if scope != "candidates" else []
    return routing.preview(match, route, cands, items)


def _refresh_soon():
    if REFRESH is None or not REFRESH.exists():
        return
    try:  # noqa: SIM105
        subprocess.Popen(
            ["/bin/bash", str(REFRESH)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass  # the next refresh tick re-bundles anyway


def add(payload):
    match, route, scope = _clean(payload)
    rule = routing.add_rule(
        match,
        route,
        where=str(payload.get("where") or ""),
        reason=str(payload.get("reason") or ""),
        origin="click",
        from_item=str(payload.get("from_fp") or ""),
        scope=scope,
    )
    _cache["cands"] = None
    _refresh_soon()
    return {"ok": True, "rule": rule, "already": rule.get("already", False)}


def disable(payload):
    rid = str((payload or {}).get("id") or "")
    r = routing.set_disabled(rid, bool(payload.get("disabled", True)))
    _refresh_soon()
    return {"ok": True, "rule": r}


def delete(payload):
    rid = str((payload or {}).get("id") or "")
    gone = routing.delete_rule(rid)
    _refresh_soon()
    return {"ok": True, "already": not gone}
