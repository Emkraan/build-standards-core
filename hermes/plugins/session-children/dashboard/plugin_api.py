"""session-children dashboard backend, mounted at /api/plugins/session-children/.

Purpose: Read-only live view of spawned sessions, keyed by every id in the launcher's
         compression lineage so the sidebar row and the focused chat both match.
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

_spec = importlib.util.spec_from_file_location(
    "session_children_store", Path(__file__).resolve().parent.parent / "children_store.py"
)
store = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(store)

router = store.host_module("fastapi").APIRouter()

RECENT_SECONDS = 1800


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _state_db() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{store.state_path()}?mode=ro", uri=True, timeout=3)
    conn.row_factory = sqlite3.Row
    return conn


def _row(db: sqlite3.Connection, sid: str):
    return db.execute(
        "SELECT id, parent_session_id, end_reason, started_at, ended_at, title, message_count, "
        "tool_call_count, last_activity_at, last_activity_description FROM sessions WHERE id=?",
        (sid,),
    ).fetchone()


def _chain_down(db: sqlite3.Connection, sid: str) -> list[Any]:
    rows, cur = [], _row(db, sid)
    while cur is not None and len(rows) < 60:
        rows.append(cur)
        if cur["end_reason"] != "compression":
            break
        cur = db.execute(
            "SELECT id, parent_session_id, end_reason, started_at, ended_at, title, message_count, "
            "tool_call_count, last_activity_at, last_activity_description FROM sessions "
            "WHERE parent_session_id=? ORDER BY started_at DESC LIMIT 1",
            (cur["id"],),
        ).fetchone()
    return rows


def _lineage_ids(db: sqlite3.Connection, sid: str) -> list[str]:
    ids, cur = [], _row(db, sid)
    while cur is not None and cur["parent_session_id"] and len(ids) < 60:
        parent = _row(db, cur["parent_session_id"])
        if parent is None or parent["end_reason"] != "compression":
            break
        cur = parent
    root = cur["id"] if cur is not None else sid
    return [r["id"] for r in _chain_down(db, root)] or [sid]


@router.get("/summary")
def summary() -> dict[str, Any]:
    now = time.time()
    with store.connect() as conn:
        links = conn.execute(
            "SELECT * FROM links WHERE finished_at IS NULL OR finished_at > ? ORDER BY started_at DESC LIMIT 60",
            (now - RECENT_SECONDS,),
        ).fetchall()
    by_parent: dict[str, list[dict[str, Any]]] = {}
    by_child: dict[str, dict[str, Any]] = {}
    running = 0
    try:
        db = _state_db()
    except sqlite3.Error:
        return {"now": now, "running": 0, "by_parent": {}, "by_child": {}}
    try:
        for link in links:
            chain = _chain_down(db, link["child_id"])
            tip = chain[-1] if chain else None
            alive = _alive(link["pid"])
            if link["finished_at"] is None:
                state = "running" if alive else "lost"
            else:
                state = "done" if link["outcome"] == "ok" else "failed"
            if state == "running":
                running += 1
                # started before the plugin hid children: adopt it
                if link["vis"] == 0 and store.set_hidden(link["child_id"], True):
                    store.set_vis(link["id"], 1)
            elif state == "lost" and link["vis"] == 1:
                # the process died with no finalize: show it again
                store.set_hidden(link["tip_id"], False)
                store.set_vis(link["id"], 2)
            child = {
                "id": tip["id"] if tip else link["tip_id"],
                "title": (
                    (tip["title"] if tip else None)
                    or (chain[0]["title"] if chain else None)
                    or "Spawned session"
                ),
                "state": state,
                "started_at": link["started_at"],
                "finished_at": link["finished_at"],
                "activity": (
                    tip["last_activity_description"] if tip and state == "running" else None
                ),
                "activity_at": (tip["last_activity_at"] if tip else None),
                "tool_calls": sum((r["tool_call_count"] or 0) for r in chain),
                "messages": sum((r["message_count"] or 0) for r in chain),
                "archived": bool(link["archived"]),
            }
            parent_chain = _chain_down(db, link["parent_id"])
            parent_title = next((r["title"] for r in reversed(parent_chain) if r["title"]), None)
            for pid_ in _lineage_ids(db, link["parent_id"]) or [link["parent_id"]]:
                by_parent.setdefault(pid_, []).append(child)
            for cid in [r["id"] for r in chain] or [link["child_id"]]:
                by_child[cid] = {
                    "parent_id": parent_chain[-1]["id"] if parent_chain else link["parent_id"],
                    "parent_title": parent_title or "another chat",
                    "state": state,
                }
    finally:
        db.close()
    return {"now": now, "running": running, "by_parent": by_parent, "by_child": by_child}
