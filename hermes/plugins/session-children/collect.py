"""Collectors for the Spawned sessions pane: one function per kind of background work.

Purpose: Turn the traces each kind of agent background work leaves on disk into one list of
         items with the same shape (title, state, started, last activity, outcome). Read-only.
         Every collector takes its inputs as arguments so a test can feed it synthetic data.

Item states: running, finished, failed, stuck. A running item is never reported as failed.

Traces read (see hermes/configurations.md section 18):
  workstreams       a registry file the workstream tool keeps (table `work`), plus the session store
  headless runners  links.db written by this plugin (hermes chat started from a session terminal)
  subagents         the session store table async_delegations, plus a journal this plugin keeps
                    from the subagent_start and subagent_stop hooks (nested and synchronous ones)
  processes         the process registry checkpoint (running) and its retained results (finished)
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Callable

KINDS = ("workstream", "runner", "subagent", "process")

# A running item with no sign of life for this long is reported as stuck.
STUCK_SECONDS = int(os.environ.get("SESSION_CHILDREN_STUCK_SECONDS") or 1200)
# A finished item leaves the pane after 30 minutes. A failed or stuck one stays for 6 hours,
# because a failure nobody saw is the one that matters.
FINISHED_KEEP = 1800
FAILED_KEEP = 6 * 3600

SESSION_COLS = (
    "id, parent_session_id, end_reason, started_at, ended_at, title, message_count, "
    "tool_call_count, last_activity_at, last_activity_description"
)

WORK_COLS = ("ref", "title", "status", "session", "chat", "asked", "created", "updated", "ended")


class Unavailable(Exception):
    """A source this machine does not have, or whose layout this plugin does not recognise."""


def clip(text: Any, limit: int) -> str:
    """First line of text, at most limit characters."""
    line = str(text or "").strip().splitlines()[0:1]
    line = line[0].strip() if line else ""
    return line if len(line) <= limit else line[: limit - 3] + "..."


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError, OverflowError):
        return False


def item(
    kind: str,
    key: str,
    title: str,
    state: str,
    started_at: float | None,
    parents: list[str],
    finished_at: float | None = None,
    activity: str | None = None,
    activity_at: float | None = None,
    outcome: str | None = None,
    open_id: str | None = None,
    archived: bool = False,
    tool_calls: int | None = None,
) -> dict[str, Any]:
    return {
        "id": f"{kind}:{key}",
        "kind": kind,
        "title": title or "Untitled",
        "state": state,
        "started_at": started_at,
        "finished_at": finished_at,
        "activity": activity,
        "activity_at": activity_at,
        "outcome": outcome,
        "open_id": open_id,
        "archived": archived,
        "tool_calls": tool_calls,
        "parents": list(dict.fromkeys(p for p in parents if p)),
    }


def keep(entry: dict[str, Any], now: float) -> bool:
    """Apply the retention window: running and stuck items always, ended ones for a while."""
    if entry["state"] in ("running", "stuck") and entry["finished_at"] is None:
        return True
    ended = entry["finished_at"] or entry["started_at"] or 0
    window = FAILED_KEEP if entry["state"] in ("failed", "stuck") else FINISHED_KEEP
    return ended > now - window


# --- session store helpers --------------------------------------------------------------------


def session_row(db: sqlite3.Connection, sid: str):
    return db.execute(f"SELECT {SESSION_COLS} FROM sessions WHERE id=?", (sid,)).fetchone()


def chain_down(db: sqlite3.Connection, sid: str) -> list[Any]:
    """A session and the compression segments that continue it, oldest first."""
    rows, cur = [], session_row(db, sid)
    while cur is not None and len(rows) < 60:
        rows.append(cur)
        if cur["end_reason"] != "compression":
            break
        cur = db.execute(
            f"SELECT {SESSION_COLS} FROM sessions WHERE parent_session_id=? ORDER BY started_at DESC LIMIT 1",
            (cur["id"],),
        ).fetchone()
    return rows


def lineage_ids(db: sqlite3.Connection, sid: str) -> list[str]:
    """Every id in the compression lineage of sid, so any segment of a chat matches."""
    cur, hops = session_row(db, sid), 0
    while cur is not None and cur["parent_session_id"] and hops < 60:
        parent = session_row(db, cur["parent_session_id"])
        if parent is None or parent["end_reason"] != "compression":
            break
        cur, hops = parent, hops + 1
    root = cur["id"] if cur is not None else sid
    return [r["id"] for r in chain_down(db, root)] or [sid]


def session_trace(db: sqlite3.Connection, sid: str) -> dict[str, Any]:
    """Tip, activity and counts of the session chain that starts at sid."""
    chain = chain_down(db, sid)
    tip = chain[-1] if chain else None
    return {
        "chain": chain,
        "tip": tip,
        "tip_id": tip["id"] if tip else sid,
        "title": (tip["title"] if tip else None)
        or next((r["title"] for r in chain if r["title"]), None),
        "activity": tip["last_activity_description"] if tip else None,
        "activity_at": (tip["last_activity_at"] or tip["started_at"]) if tip else None,
        "tool_calls": sum((r["tool_call_count"] or 0) for r in chain),
    }


def parents_of(db: sqlite3.Connection, sid: str | None) -> list[str]:
    if not sid:
        return []
    try:
        return lineage_ids(db, sid) or [sid]
    except sqlite3.Error:
        return [sid]


def quiet_for(activity_at: float | None, now: float) -> bool:
    return bool(activity_at) and now - float(activity_at) > STUCK_SECONDS


# --- workstreams -----------------------------------------------------------------------------


def find_workstream_registry(home: Path) -> Path | None:
    """The registry is a sqlite file with a `work` table, named by env or found one level down."""
    named = os.environ.get("SESSION_CHILDREN_WORKSTREAM_DB")
    if named:
        return Path(named) if Path(named).is_file() else None
    for path in sorted(home.glob("*/work.db")):
        try:
            with open_readonly(path) as conn:
                cols = {r[1] for r in conn.execute("PRAGMA table_info(work)")}
            if set(WORK_COLS) <= cols:
                return path
        except sqlite3.Error:
            continue
    return None


class open_readonly:
    """Open a sqlite file that another process writes, without ever writing to it.

    A read-only URI cannot open a WAL file whose shared-memory index is absent, so the first try
    is a normal connection with query_only on, and the last resort is an immutable snapshot.
    """

    def __init__(self, path: Path):
        self.path = path
        self.conn = None  # type: Optional[sqlite3.Connection]

    def __enter__(self) -> sqlite3.Connection:
        last = None  # type: Optional[Exception]
        for uri in (None, f"file:{self.path}?immutable=1"):
            try:
                if uri is None:
                    conn = sqlite3.connect(str(self.path), timeout=3)
                else:
                    conn = sqlite3.connect(uri, uri=True, timeout=3)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only=ON")
                conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
                self.conn = conn
                return conn
            except sqlite3.Error as exc:
                last = exc
        raise sqlite3.OperationalError(f"cannot open {self.path.name}: {last}")

    def __exit__(self, *exc) -> None:
        if self.conn is not None:
            self.conn.close()


WORKSTREAM_STATE = {
    "starting": "running",
    "working": "running",
    "needs_you": "stuck",
    "done": "finished",
    "failed": "failed",
    "stopped": "finished",
}


def collect_workstreams(db: sqlite3.Connection, home: Path, now: float) -> dict[str, Any]:
    path = find_workstream_registry(home)
    if path is None:
        return {"items": [], "note": "No workstream registry found on this machine."}
    with open_readonly(path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(work)")}
        if not set(WORK_COLS) <= cols:
            raise Unavailable("workstream registry has an unexpected layout")
        rows = conn.execute(
            "SELECT {}, stopping FROM work WHERE ended IS NULL OR ended > ?".format(
                ", ".join(WORK_COLS)
            )
            if "stopping" in cols
            else "SELECT {}, 0 AS stopping FROM work WHERE ended IS NULL OR ended > ?".format(
                ", ".join(WORK_COLS)
            ),
            (now - FAILED_KEEP,),
        ).fetchall()
    items = []
    for r in rows:
        state = WORKSTREAM_STATE.get(r["status"], "stuck")
        outcome = {
            "starting": "Starting",
            "working": None,
            "needs_you": "Waiting on you" + (": " + clip(r["asked"], 120) if r["asked"] else ""),
            "done": "Done",
            "failed": "Failed",
            "stopped": "Stopped",
        }.get(r["status"], "Unknown status: " + clip(r["status"], 30))
        activity = activity_at = tool_calls = open_id = None
        if r["session"]:
            trace = session_trace(db, r["session"])
            tip = trace["tip"]
            open_id = trace["tip_id"] if tip is not None else None
            activity, activity_at, tool_calls = (
                trace["activity"],
                trace["activity_at"],
                trace["tool_calls"],
            )
            if r["status"] in ("starting", "working") and tip is not None:
                if tip["ended_at"] and tip["end_reason"] != "compression":
                    state = "failed"
                    outcome = "Session ended: %s" % (tip["end_reason"] or "unknown reason")
                elif quiet_for(activity_at, now):
                    state = "stuck"
                    outcome = f"No activity for {int((now - activity_at) // 60)} min"
                elif r["stopping"]:
                    outcome = "Stopping"
        items.append(
            item(
                "workstream",
                "{}:{}".format(r["ref"], r["created"]),
                "{}  {}".format(r["ref"], clip(r["title"], 90)),
                state,
                r["created"],
                parents_of(db, r["chat"]),
                finished_at=r["ended"] if state in ("finished", "failed") else None,
                activity=activity if state in ("running", "stuck") else None,
                activity_at=activity_at or r["updated"],
                outcome=outcome,
                open_id=open_id,
                tool_calls=tool_calls,
            )
        )
    return {"items": items, "note": None}


# --- headless runners ------------------------------------------------------------------------


def collect_runners(
    db: sqlite3.Connection,
    links: list[Any],
    now: float,
    is_alive: Callable[[int], bool] = alive,
    on_running: Callable[[Any], None] | None = None,
    on_lost: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    """Sessions started by hermes chat from a session terminal (links.db rows)."""
    items = []
    for link in links:
        trace = session_trace(db, link["child_id"])
        up = is_alive(link["pid"])
        activity_at = trace["activity_at"] or link["updated_at"]
        outcome = None
        finished_at = link["finished_at"]
        if finished_at is None:
            if up:
                state = "running"
                if on_running:
                    on_running(link)
                if quiet_for(activity_at, now):
                    state = "stuck"
                    outcome = f"No activity for {int((now - activity_at) // 60)} min"
            else:
                state = "failed"
                outcome = "Process ended without finishing"
                finished_at = link["updated_at"]
                if on_lost:
                    on_lost(link)
        elif link["outcome"] == "ok":
            state, outcome = (
                "finished",
                "Finished cleanly" + (", archived" if link["archived"] else ""),
            )
        elif link["outcome"] == "interrupted":
            state, outcome = "failed", "Interrupted"
        else:
            state, outcome = "failed", "Failed"
        items.append(
            item(
                "runner",
                str(link["id"]),
                clip(trace["title"], 90) or "Spawned session",
                state,
                link["started_at"],
                parents_of(db, link["parent_id"]),
                finished_at=finished_at,
                activity=trace["activity"] if state in ("running", "stuck") else None,
                activity_at=activity_at,
                outcome=outcome,
                open_id=trace["tip_id"],
                archived=bool(link["archived"]),
                tool_calls=trace["tool_calls"],
            )
        )
    return {"items": items, "note": None, "chains": {r["id"]: trace_ids(db, r) for r in links}}


def trace_ids(db: sqlite3.Connection, link: Any) -> list[str]:
    return [r["id"] for r in chain_down(db, link["child_id"])] or [link["child_id"]]


# --- subagents -------------------------------------------------------------------------------

_ASYNC_JSON = (
    "SELECT delegation_id, origin_session, parent_session_id, state, dispatched_at, completed_at, "
    "updated_at, json_extract(task_json,'$.goal') AS goal, "
    "json_extract(task_json,'$.goals[0]') AS goal0, json_extract(task_json,'$.role') AS role, "
    "json_extract(event_json,'$.error') AS error, "
    "json_extract(result_json,'$.results[0].status') AS result_status "
    "FROM async_delegations WHERE state IN ('running','stalling','finalizing') "
    "OR COALESCE(completed_at, updated_at) > ?"
)
_ASYNC_PLAIN = (
    "SELECT delegation_id, origin_session, parent_session_id, state, dispatched_at, completed_at, "
    "updated_at, NULL AS goal, NULL AS goal0, NULL AS role, NULL AS error, NULL AS result_status "
    "FROM async_delegations WHERE state IN ('running','stalling','finalizing') "
    "OR COALESCE(completed_at, updated_at) > ?"
)


def collect_async_subagents(db: sqlite3.Connection, now: float) -> list[dict[str, Any]]:
    """Background delegations the agent records in the session store. Result text is never read."""
    try:
        rows = db.execute(_ASYNC_JSON, (now - FAILED_KEEP,)).fetchall()
    except sqlite3.OperationalError as exc:
        if "json_extract" not in str(exc) and "malformed JSON" not in str(exc):
            raise
        rows = db.execute(_ASYNC_PLAIN, (now - FAILED_KEEP,)).fetchall()
    items = []
    for r in rows:
        state, outcome, finished_at = "running", None, r["completed_at"]
        if r["state"] == "stalling":
            state, outcome = "stuck", "The agent reports it is stalling"
        elif r["state"] == "completed":
            if r["result_status"] in ("failed", "interrupted", "error"):
                state, outcome = "failed", "Subagent reported: {}".format(r["result_status"])
            else:
                state, outcome = "finished", "Completed"
        elif r["state"] == "error":
            state, outcome = "failed", clip(r["error"], 120) or "Error"
        elif r["state"] not in ("running", "finalizing"):
            state = "failed"
            outcome = "Owner process ended before the result came back"
            finished_at = finished_at or r["updated_at"]
        goal = r["goal"] or r["goal0"]
        items.append(
            item(
                "subagent",
                r["delegation_id"],
                clip(goal, 90)
                or ("Subagent ({})".format(r["role"]) if r["role"] else "Subagent task"),
                state,
                r["dispatched_at"],
                parents_of(db, r["origin_session"]) + parents_of(db, r["parent_session_id"]),
                finished_at=finished_at if state in ("finished", "failed") else None,
                activity=None,
                activity_at=r["updated_at"],
                outcome=outcome,
            )
        )
    return items


def journal_rows(conn: sqlite3.Connection, now: float) -> list[Any]:
    return conn.execute(
        "SELECT * FROM subagents WHERE finished_at IS NULL OR finished_at > ? ORDER BY started_at DESC LIMIT 200",
        (now - FAILED_KEEP,),
    ).fetchall()


def collect_journal_subagents(
    db: sqlite3.Connection,
    journal: list[Any],
    async_items: list[dict[str, Any]],
    async_spans: list[Any],
    now: float,
    is_alive: Callable[[int], bool] = alive,
) -> list[dict[str, Any]]:
    """Subagents seen through the hooks. A row that overlaps a recorded background delegation of
    the same parent is the same work, so it is skipped (the delegation record is authoritative)."""
    items = []
    for j in journal:
        span_hit = any(
            (j["parent_id"] in (s["origin_session"], s["parent_session_id"]))
            and s["dispatched_at"] - 5 <= j["started_at"]
            and (s["completed_at"] is None or j["started_at"] <= s["completed_at"] + 5)
            for s in async_spans
        )
        if span_hit:
            continue
        activity = activity_at = open_id = None
        trace = None
        if j["child_session_id"] and session_row(db, j["child_session_id"]) is not None:
            trace = session_trace(db, j["child_session_id"])
            open_id = trace["tip_id"]
            activity, activity_at = trace["activity"], trace["activity_at"]
        activity_at = activity_at or j["updated_at"]
        finished_at, outcome = j["finished_at"], None
        if finished_at is None:
            if is_alive(j["pid"]):
                state = "running"
                if quiet_for(activity_at, now):
                    state, outcome = (
                        "stuck",
                        f"No activity for {int((now - activity_at) // 60)} min",
                    )
            else:
                state, outcome = "failed", "Process ended without finishing"
                finished_at = j["updated_at"]
        elif j["status"] in ("completed", "ok", None, ""):
            state, outcome = "finished", "Completed"
        else:
            state, outcome = "failed", "Subagent reported: {}".format(clip(j["status"], 30))
        items.append(
            item(
                "subagent",
                "j{}".format(j["id"]),
                clip(j["goal"], 90)
                or ("Subagent ({})".format(j["role"]) if j["role"] else "Subagent task"),
                state,
                j["started_at"],
                parents_of(db, j["parent_id"]),
                finished_at=finished_at if state in ("finished", "failed") else None,
                activity=activity if state in ("running", "stuck") else None,
                activity_at=activity_at,
                outcome=outcome,
                open_id=open_id,
                tool_calls=trace["tool_calls"] if trace else None,
            )
        )
    return items


def async_spans(db: sqlite3.Connection, now: float) -> list[Any]:
    return db.execute(
        "SELECT origin_session, parent_session_id, dispatched_at, completed_at FROM async_delegations "
        "WHERE state IN ('running','stalling','finalizing') OR COALESCE(completed_at, updated_at) > ?",
        (now - FAILED_KEEP,),
    ).fetchall()


# --- background processes --------------------------------------------------------------------


_WRAPPERS = ("cd", "export", "set", "source", "echo", "true", "unset", "trap")


def command_title(command: Any) -> str:
    """Executable and first operand of the first real command in a line. Wrapper steps such as a
    leading cd or a trailing echo are skipped. Never the whole command line, because arguments
    can carry values that must not be shown."""
    text = str(command or "").replace("\n", " ")
    for sep in ("&&", chr(59), "|"):
        text = text.replace(sep, "\n")
    segments = [seg.split() for seg in text.splitlines() if seg.strip()]
    real = [seg for seg in segments if os.path.basename(seg[0]) not in _WRAPPERS]
    parts = (real or segments or [[]])[0]
    if not parts:
        return "Background process"
    head = os.path.basename(parts[0].strip("'\""))
    operand = next(
        (os.path.basename(p.strip("'\"")) for p in parts[1:] if not p.startswith("-")), ""
    )
    return clip((head + " " + operand).strip(), 60)


def read_json_file(path: Path, limit: int = 16 * 1024 * 1024) -> Any:
    if path.stat().st_size > limit:
        raise Unavailable("file too large")
    with open(str(path), encoding="utf-8") as fh:
        return json.load(fh)


def process_outcome(code: Any, reason: str) -> str:
    base = f"Exit {code}" if code is not None else "Ended"
    return base if reason == "exited" else f"{base} ({clip(reason, 30)})"


def collect_processes(
    db: sqlite3.Connection | None,
    home: Path,
    now: float,
    is_alive: Callable[[int], bool] = alive,
) -> dict[str, Any]:
    """Running processes from the registry checkpoint, finished ones from its retained results.

    The checkpoint holds no output time, so a process is never reported as stuck: its last
    activity is not recorded. A result file's output and full command are never read into an item.
    """
    checkpoint = home / "processes.json"
    results_dir = home / "logs" / "process-results"
    if not checkpoint.exists() and not results_dir.exists():
        return {"items": [], "note": "No process registry found on this machine."}
    items, seen = [], set()
    if results_dir.exists():
        files = []
        for path in results_dir.glob("proc_*.json"):
            try:
                files.append((path.stat().st_mtime, path))
            except OSError:
                continue
        for mtime, path in sorted(files, reverse=True)[:80]:
            if mtime < now - FAILED_KEEP:
                break
            try:
                data = read_json_file(path)
            except (OSError, ValueError, Unavailable):
                continue
            pid_ = data.get("id") or path.stem
            seen.add(pid_)
            code = data.get("exit_code")
            reason = data.get("completion_reason") or "exited"
            ok = code == 0
            items.append(
                item(
                    "process",
                    pid_,
                    command_title(data.get("command")),
                    "finished" if ok else "failed",
                    data.get("started_at"),
                    parents_of(db, data.get("parent_session_id") or data.get("session_key"))
                    if db is not None
                    else [],
                    finished_at=mtime,
                    outcome=process_outcome(code, reason),
                    activity_at=mtime,
                )
            )
    if checkpoint.exists():
        entries = read_json_file(checkpoint)
        stamp = checkpoint.stat().st_mtime
        if not isinstance(entries, list):
            raise Unavailable("process checkpoint has an unexpected layout")
        for e in entries:
            pid_ = e.get("session_id")
            if not pid_ or pid_ in seen:
                continue
            up = is_alive(e.get("pid"))
            items.append(
                item(
                    "process",
                    pid_,
                    command_title(e.get("command")),
                    "running" if up else "failed",
                    e.get("started_at"),
                    parents_of(db, e.get("parent_session_id") or e.get("session_key"))
                    if db is not None
                    else [],
                    finished_at=None if up else stamp,
                    outcome=None if up else "Process gone, exit status not recorded yet",
                )
            )
    return {"items": items, "note": None}
