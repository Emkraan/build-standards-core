"""
tackle_session.py
Purpose: Find the session a launch from a card really created, from the agent runtime's session database, instead of
         trusting the session id a desktop plugin reports. The plugin reads the focused session after submitting the prompt
         and can report the previously focused chat, so the item was bound and titled on the wrong session.
         A Tackle session is the one whose FIRST user message is the staged prompt for that fp.
         Stdlib only, read-only on the session database.
Date:    2026-11-06
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import paths

STATE_DB = Path(os.environ.get("OPSCENTER_SESSIONS_DB") or paths.agent_home() / "state.db")
MATCH_CHARS = 1500  # the prompt head carries the item title, refs and fp, enough to be unique


def _connect(db=None):
    path = Path(db) if db else STATE_DB
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3)


def _norm(text):
    return (text or "").strip()[:MATCH_CHARS]


def started_with_prompt(session_id, prompt, db=None):
    """True when the session's first user message is this prompt."""
    if not session_id or not prompt:
        return False
    try:
        con = _connect(db)
    except sqlite3.Error:
        return False
    try:
        row = con.execute(
            "SELECT content FROM messages WHERE session_id = ? AND role = 'user' ORDER BY timestamp, id LIMIT 1",
            (session_id,),
        ).fetchone()
    except sqlite3.Error:
        return False
    finally:
        con.close()
    return bool(row) and _norm(row[0]) == _norm(prompt)


def find_prompt_session(prompt, since_epoch=0.0, db=None):
    """Session id whose first user message is this prompt, created at or after since_epoch.
    Newest first. None when nothing matches yet (the message may not be persisted)."""
    head = _norm(prompt)
    if not head:
        return None
    try:
        con = _connect(db)
    except sqlite3.Error:
        return None
    try:
        rows = con.execute(
            "SELECT session_id, content FROM messages WHERE role = 'user' AND timestamp >= ? "
            "AND substr(content, 1, 200) = ? ORDER BY timestamp DESC",
            (float(since_epoch or 0), head[:200]),
        ).fetchall()
        for sid, content in rows:
            if _norm(content) != head:
                continue
            first = con.execute(
                "SELECT content FROM messages WHERE session_id = ? AND role = 'user' ORDER BY timestamp, id LIMIT 1",
                (sid,),
            ).fetchone()
            if first and _norm(first[0]) == head:
                return sid
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return None
