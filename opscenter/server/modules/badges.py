"""
badges.py
Purpose: The sidebar badges in one small payload (GET /api/badges): the same filters as each page, so a count never disagrees
         with the page it points at. Every section is read from a lifted module and guarded on its own: a module that is not in
         the tree, or a source that cannot be read, yields that section's zero value and never an error, and an infrastructure
         check that fails shows as one problem, never as clear. Nothing here names an estate.
Date:    2026-10-29

Keys: problems {items, counts} (problems.py, the single list), action_open (board fingerprints not handled), debt, knowledge, knowledge_pending, knowledge_docs, links, infra
      {count, items}, builds {running, waiting}, core, alerts.
"""

import datetime as dt
import importlib
import json
import os
from pathlib import Path

import paths

SERVED_BOARD_ENV = "OPSCENTER_SERVED_BOARD"


def _mod(name):
    """The lifted module, or None when it is not in the tree."""
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _guard(fn, zero):
    """fn() or the zero value: a badge never takes the sidebar down."""
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return zero


def _board():
    p = os.environ.get(SERVED_BOARD_ENV) or str(
        paths.state_dir() / "public-data" / "action-center.json"
    )
    try:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _handled():
    stores = _mod("stores")
    return _guard(stores.load_handled, {}) if stores is not None else {}


def _is_handled(handled, fp, now):
    h = handled.get(fp)
    if not isinstance(h, dict):
        return False
    if h.get("act") == "snoozed" and h.get("until"):
        try:
            return dt.datetime.fromisoformat(str(h["until"]).replace("Z", "+00:00")) > now
        except ValueError:
            return False
    return h.get("act") != "snoozed"


def _action_open():
    now = dt.datetime.now(dt.timezone.utc)
    handled = _handled()
    fps = [
        it.get("fp") for it in _board().get("items") or [] if isinstance(it, dict) and it.get("fp")
    ]
    return [f for f in fps if not _is_handled(handled, f, now)]


def _call(module, fn, zero, *args):
    m = _mod(module)
    f = getattr(m, fn, None) if m is not None else None
    return _guard(lambda: f(*args), zero) if callable(f) else zero


def _debt():
    m = _mod("eng_backlog")
    if m is None:
        return 0
    return _guard(lambda: int((m.items().get("counts") or {}).get("decide_imp", 0)), 0)


def _links():
    m = _mod("link_health")
    if m is None or not hasattr(m, "dead_count"):
        return 0
    d = paths.dashboard_dir()
    return _guard(lambda: int(m.dead_count(d / "link-health.json", d / "link-edits.json")), 0)


def _pending():
    """Proposal fingerprints still staged for approval: from an optional curation module (none: empty)."""
    m = _mod("curation")
    pub = getattr(m, "public", None) if m is not None else None
    if not callable(pub):
        return []
    return _guard(lambda: [p["fp"] for p in pub().get("proposals", []) if p.get("fp")], [])


def _infra():
    m = _mod("infra")
    if m is None or not hasattr(m, "badge_problems"):
        return {"count": 0, "items": []}
    try:
        return m.badge_problems()
    except Exception as e:  # noqa: BLE001 - unknown shows as one problem, never as clear
        return {"count": 1, "items": [f"Infrastructure checks failed: {e}"]}


def _problems():
    """The single problem list (problems.py): the rail badge, tab counts and Overview all read it."""
    return _guard(
        lambda: importlib.import_module("problems").collect(),
        {
            "items": [],
            "counts": {
                "needs_me": 0,
                "worth_a_look": 0,
                "healthy": 0,
                "running": 0,
                "total": 0,
                "by_section": {},
                "by_item": {},
            },
        },
    )


def get():
    docs = _call("doc_coverage", "badge", 0)
    pending = _pending()
    return {
        "builds": _call("builds", "badge", {"running": 0, "waiting": 0}),
        "core": _call("core_consumption", "badge", 0),
        "action_open": _guard(_action_open, []),
        "debt": _debt(),
        "knowledge": docs + len(pending),
        "knowledge_pending": pending,
        "knowledge_docs": docs,
        "links": _links(),
        "infra": _infra(),
        "alerts": _call("alerts", "badge", 0),
        "problems": _problems(),
    }
