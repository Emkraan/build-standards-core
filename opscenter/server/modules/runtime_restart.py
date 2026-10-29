"""
runtime_restart.py
Purpose: The agent runtime restart card. GET shows whether the runtime needs a restart and what is running right now;
         POST queues a restart (mode now or idle) or cancels it. The restart itself is the consumer's: a script it supplies
         does the work (OPSCENTER_RUNTIME_RESTART_SCRIPT, a Python file exposing status(), request(mode, note, who) and
         cancel()), never this server, so nothing here can take the backend down while work is running. With no script
         configured the card is empty (nothing to restart) and a POST answers 501.
Date:    2026-10-17

alert is set when a restart is queued, a restart failed, or plugins or config changed after the runtime started (stale).
"""

import importlib.util
import os
from pathlib import Path

_mod = {"path": None, "obj": None}


class NotConfigured(Exception):
    status = 501


def _script():
    return os.environ.get("OPSCENTER_RUNTIME_RESTART_SCRIPT", "").strip()


def _engine():
    path = _script()
    if not path:
        raise NotConfigured(
            "no runtime restart script configured (OPSCENTER_RUNTIME_RESTART_SCRIPT)"
        )
    if _mod["path"] != path:
        file = Path(path).expanduser()
        spec = importlib.util.spec_from_file_location("runtime_restart_script", file)
        if not file.is_file() or spec is None or spec.loader is None:
            raise ImportError("cannot load the runtime restart script")
        obj = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(obj)
        _mod.update(path=path, obj=obj)
    return _mod["obj"]


def _shape(st):
    last = st.get("last") or {}
    failed = last and not last.get("ok") and not last.get("refused")
    alert = (
        "pending"
        if st.get("pending")
        else "failed"
        if failed
        else "stale"
        if st.get("stale")
        else None
    )
    return dict(st, alert=alert)


def get():
    if not _script():
        return {"alert": None, "busy": [], "safe": False, "configured": False}
    try:
        return _shape(_engine().status())
    except (OSError, ImportError, AttributeError, ValueError, SyntaxError) as e:
        return {"alert": None, "error": str(e)[:300], "busy": [], "safe": False, "configured": True}


def post(payload):
    action = (payload or {}).get("action")
    if action not in ("now", "idle", "cancel"):
        raise ValueError("action must be now, idle or cancel")
    eng = _engine()
    if action == "cancel":
        eng.cancel()
    else:
        eng.request(action, "Requested from the Ops Center", "ops-center")
    return get()
