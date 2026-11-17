"""Link store for session-children.

Purpose: Shared sqlite store (spawned session -> launcher session) used by the hooks
         in __init__.py and the dashboard backend in dashboard/plugin_api.py.
"""

from __future__ import annotations

import importlib
import os
import sqlite3
import time
from pathlib import Path


def host_module(name: str):
    """Load a module the agent itself provides (its session store, its web framework).

    The plugin runs inside the agent's own interpreter, so these are not dependencies it installs
    or can pin: the agent's version is the only one that exists. They are loaded here, in one place,
    so the plugin still imports on its own for a syntax check.
    """
    return importlib.import_module(name)


def open_session_db():
    """Open the agent's session store through its own API."""
    return host_module("hermes_state").SessionDB()


def _home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def links_path() -> Path:
    return _home() / "session-children" / "links.db"


def state_path() -> Path:
    return _home() / "state.db"


def connect() -> sqlite3.Connection:
    path = links_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS links ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " pid INTEGER NOT NULL,"
        " child_id TEXT NOT NULL,"
        " tip_id TEXT NOT NULL,"
        " parent_id TEXT NOT NULL,"
        " started_at REAL NOT NULL,"
        " updated_at REAL NOT NULL,"
        " finished_at REAL,"
        " outcome TEXT,"
        " archived INTEGER NOT NULL DEFAULT 0)"
    )
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(links)")}
    if "vis" not in cols:
        # 0 = untouched, 1 = hidden from the sidebar by this plugin, 2 = released back
        conn.execute("ALTER TABLE links ADD COLUMN vis INTEGER NOT NULL DEFAULT 0")
    conn.execute("CREATE INDEX IF NOT EXISTS links_parent ON links(parent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS links_pid ON links(pid, started_at)")
    return conn


def record_start(child_id: str, parent_id: str, pid: int) -> int:
    now = time.time()
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM links WHERE pid=? AND finished_at IS NULL ORDER BY id DESC LIMIT 1",
            (pid,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE links SET tip_id=?, updated_at=? WHERE id=?", (child_id, now, row["id"])
            )
            return row["id"]
        cur = conn.execute(
            "INSERT INTO links(pid, child_id, tip_id, parent_id, started_at, updated_at) VALUES (?,?,?,?,?,?)",
            (pid, child_id, child_id, parent_id, now, now),
        )
        return cur.lastrowid


def record_turn(session_id: str, pid: int, outcome: str) -> None:
    now = time.time()
    with connect() as conn:
        conn.execute(
            "UPDATE links SET tip_id=?, outcome=?, updated_at=? WHERE pid=? AND finished_at IS NULL",
            (session_id, outcome, now, pid),
        )


def record_finish(pid: int) -> sqlite3.Row | None:
    """Mark the open link for this pid finished and return it (None when this process was not linked)."""
    now = time.time()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM links WHERE pid=? AND finished_at IS NULL ORDER BY id DESC LIMIT 1",
            (pid,),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE links SET finished_at=?, updated_at=? WHERE id=?", (now, now, row["id"])
        )
        return row


def mark_archived(link_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE links SET archived=1 WHERE id=?", (link_id,))


def set_vis(link_id: int, vis: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE links SET vis=? WHERE id=?", (vis, link_id))


def set_hidden(session_id: str, hidden: bool) -> bool:
    """Hide or show a session (and its compression lineage) in the sidebar. Never raises."""
    try:
        db = open_session_db()
        try:
            return bool(db.set_session_hidden(session_id, hidden))
        finally:
            db.close()
    except Exception:
        return False
