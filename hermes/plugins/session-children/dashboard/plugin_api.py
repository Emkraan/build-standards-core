"""session-children dashboard backend, mounted at /api/plugins/session-children/.

Purpose: Read-only live view of all background agent work (workstreams, headless runners,
         subagents, background processes), keyed by every id in the owning chat's compression
         lineage so the sidebar row and the focused chat both match. The collectors live in
         collect.py. Each one runs on its own, so a source that fails is reported as
         unavailable in `sections` and never hides the others.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import time
from pathlib import Path
from typing import Any

_here = Path(__file__).resolve().parent.parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _here / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


store = _load("session_children_store", "children_store.py")
collect = _load("session_children_collect", "collect.py")

router = store.host_module("fastapi").APIRouter()

# Kept for callers that imported the older names.
RECENT_SECONDS = collect.FINISHED_KEEP
_alive = collect.alive
_chain_down = collect.chain_down
_lineage_ids = collect.lineage_ids


def _state_db() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{store.state_path()}?mode=ro", uri=True, timeout=3)
    conn.row_factory = sqlite3.Row
    return conn


def build_summary(db: sqlite3.Connection, now: float) -> dict[str, Any]:
    """Collect every kind of background work into one payload. Pure apart from the two sidebar
    visibility updates for runners, which this plugin owns."""
    sections: dict[str, Any] = {}
    items: list[dict[str, Any]] = []
    by_child: dict[str, dict[str, Any]] = {}

    def run(kind: str, fn):
        try:
            result = fn()
        except Exception as exc:  # one failing source must not hide the others
            text = str(exc).strip().splitlines()[0:1]
            sections[kind] = {
                "ok": False,
                "note": "Unavailable: {}{}".format(
                    type(exc).__name__, (" - " + text[0][:120]) if text else ""
                ),
                "count": 0,
            }
            return
        sections[kind] = {"ok": True, "note": result.get("note"), "count": len(result["items"])}
        items.extend(result["items"])

    home = Path(store.state_path()).parent

    def workstreams():
        return collect.collect_workstreams(db, home, now)

    def runners():
        with store.connect() as conn:
            links = conn.execute(
                "SELECT * FROM links WHERE finished_at IS NULL OR finished_at > ? "
                "ORDER BY started_at DESC LIMIT 60",
                (now - collect.FAILED_KEEP,),
            ).fetchall()

        def adopt(link):
            # started before the plugin hid children: adopt it
            if link["vis"] == 0 and store.set_hidden(link["child_id"], True):
                store.set_vis(link["id"], 1)

        def release(link):
            # the process died with no finalize: show it again
            if link["vis"] == 1:
                store.set_hidden(link["tip_id"], False)
                store.set_vis(link["id"], 2)

        result = collect.collect_runners(db, links, now, on_running=adopt, on_lost=release)
        by_link = {str(link["id"]): link for link in links}
        for it in result["items"]:
            link = by_link[it["id"].split(":", 1)[1]]
            parent_chain = collect.chain_down(db, link["parent_id"])
            parent_title = next((r["title"] for r in reversed(parent_chain) if r["title"]), None)
            for cid in result["chains"].get(link["id"]) or [link["child_id"]]:
                by_child[cid] = {
                    "parent_id": parent_chain[-1]["id"] if parent_chain else link["parent_id"],
                    "parent_title": parent_title or "another chat",
                    "state": it["state"],
                }
        return result

    def subagents():
        recorded = collect.collect_async_subagents(db, now)
        spans = collect.async_spans(db, now)
        with store.connect() as conn:
            journal = collect.journal_rows(conn, now)
        seen = collect.collect_journal_subagents(db, journal, recorded, spans, now)
        return {"items": recorded + seen, "note": None}

    def processes():
        return collect.collect_processes(db, home, now)

    run("workstream", workstreams)
    run("runner", runners)
    run("subagent", subagents)
    run("process", processes)

    visible = [it for it in items if collect.keep(it, now)]
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for it in visible:
        entry = {k: v for k, v in it.items() if k != "parents"}
        for parent_id in it["parents"]:
            by_parent.setdefault(parent_id, []).append(entry)
    rank = {"stuck": 0, "failed": 1, "running": 2, "finished": 3}
    visible.sort(key=lambda it: (rank.get(it["state"], 4), -(it["started_at"] or 0)))
    return {
        "now": now,
        "running": sum(1 for it in visible if it["state"] == "running"),
        "attention": sum(1 for it in visible if it["state"] in ("failed", "stuck")),
        "sections": sections,
        "all": [{k: v for k, v in it.items() if k != "parents"} for it in visible],
        "by_parent": by_parent,
        "by_child": by_child,
    }


@router.get("/summary")
def summary() -> dict[str, Any]:
    now = time.time()
    try:
        db = _state_db()
    except sqlite3.Error as exc:
        note = f"Unavailable: session store ({type(exc).__name__})"
        return {
            "now": now,
            "running": 0,
            "attention": 0,
            "sections": {k: {"ok": False, "note": note, "count": 0} for k in collect.KINDS},
            "all": [],
            "by_parent": {},
            "by_child": {},
        }
    try:
        return build_summary(db, now)
    finally:
        db.close()
