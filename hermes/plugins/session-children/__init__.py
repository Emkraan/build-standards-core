"""session-children: link, auto-archive and live-track sessions spawned from other sessions.

Purpose: A session started by `hermes chat` from a parent's terminal inherits the parent's
         HERMES_SESSION_ID. This plugin records that link, archives the child as soon as it
         finishes cleanly, and feeds the desktop half (live badge and pane on the parent).
         It also journals subagents through the subagent hooks, so the pane can show every kind
         of background work (collect.py reads the rest from the agent's own records).
"""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path

logger = logging.getLogger("session-children")

# The launcher id is only valid at import time: once the child's own session starts, the
# process rewrites HERMES_SESSION_ID to the child's id.
_LAUNCHER = (
    os.environ.get("HERMES_SPAWNED_BY") or os.environ.get("HERMES_SESSION_ID") or ""
).strip()
_PID = os.getpid()


def _store():
    spec = importlib.util.spec_from_file_location(
        "session_children_store", Path(__file__).with_name("children_store.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _on_start(session_id=None, platform=None, **_kw):
    if platform != "cli" or not _LAUNCHER or not session_id or session_id == _LAUNCHER:
        return
    try:
        store = _store()
        link_id = store.record_start(session_id, _LAUNCHER, _PID)
        # Running children live under the parent chat (pane), not in the flat sidebar list.
        if store.set_hidden(session_id, True) and link_id:
            store.set_vis(link_id, 1)
    except Exception:
        logger.exception("session-children: record_start failed")


def _on_turn_end(session_id=None, completed=False, failed=False, interrupted=False, **_kw):
    if not _LAUNCHER or not session_id:
        return
    outcome = (
        "ok"
        if (completed and not failed and not interrupted)
        else ("interrupted" if interrupted else "failed")
    )
    try:
        _store().record_turn(session_id, _PID, outcome)
    except Exception:
        logger.exception("session-children: record_turn failed")


def _on_finalize(session_id=None, **_kw):
    if not _LAUNCHER:
        return
    try:
        store = _store()
        link = store.record_finish(_PID)
        if link is None:
            return
        store.set_hidden(link["tip_id"], False)
        store.set_vis(link["id"], 2)
        if link["outcome"] != "ok":
            return  # failed or interrupted: back in the sidebar for review
        db = store.open_session_db()
        try:
            db.set_session_archived(link["tip_id"], True)
        finally:
            db.close()
        store.mark_archived(link["id"])
    except Exception:
        logger.exception("session-children: archive on finalize failed")


def _on_subagent_start(
    parent_session_id=None, child_session_id=None, child_role=None, child_goal=None, **_kw
):
    if not parent_session_id:
        return
    try:
        _store().record_subagent_start(
            _PID, parent_session_id, child_session_id, child_role, child_goal
        )
    except Exception:
        logger.exception("session-children: record_subagent_start failed")


def _on_subagent_stop(parent_session_id=None, child_session_id=None, child_status=None, **_kw):
    if not parent_session_id:
        return
    try:
        _store().record_subagent_stop(_PID, parent_session_id, child_session_id, child_status)
    except Exception:
        logger.exception("session-children: record_subagent_stop failed")


def register(ctx):
    ctx.register_hook("on_session_start", _on_start)
    ctx.register_hook("on_session_end", _on_turn_end)
    ctx.register_hook("on_session_finalize", _on_finalize)
    ctx.register_hook("subagent_start", _on_subagent_start)
    ctx.register_hook("subagent_stop", _on_subagent_stop)
