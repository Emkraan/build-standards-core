#!/usr/bin/env python3
"""Safe single restart of Hermes (drain check). Script-only cron (no agent). Ships PAUSED.

Operator enables the job; each tick checks for idle work. After two idle ticks in a row it pauses
this job first (so it can only ever fire once), then writes a trigger file. A separate launchd agent (installed once,
see safe_hermes_restart_exec.py) bounces the service from outside it, verifies the new gateway, and records the result on the operator-actions board.

Idle means: no live kanban worker, no other cron run in progress, no busy model slot, and no chat
turn in flight (a live, unexpired turn lease in the session store, which the desktop backend and the
gateway both take). A probe that cannot be read counts as busy, never as idle.
Flags: --dry-run (report only), --status.
"""

import contextlib
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

HOME = os.path.expanduser("~")
HH = f"{HOME}/.hermes"
JOBS = f"{HH}/cron/jobs.json"
STATE_DB = f"{HH}/state.db"
STATE = f"{HH}/state/safe-restart.json"
HELPER = f"{HH}/scripts/safe_hermes_restart_exec.py"
JOB_NAME = "safe-hermes-restart"
TRIGGER = f"{HH}/state/safe-restart.trigger"
STALE_H = 3  # a cron run older than this with no end is treated as dead
IDLE_TICKS = 2  # consecutive idle ticks required
STALL_H = 12  # armed this long without going idle: open one card
ENV = {"HOME": HOME, "PATH": os.environ.get("PATH", ""), "HERMES_HOME": HH}


def _assignee():
    """Who the cards go to: first line of ~/.hermes/state/safe-restart.assignee, else 'operator'."""
    try:
        return open(os.path.expanduser("~/.hermes/state/safe-restart.assignee")).read().split()[0]
    except Exception:
        return "operator"


ASSIGNEE = _assignee()


def hermes(*a):
    r = subprocess.run(["hermes", *a], env=ENV, capture_output=True, text=True, timeout=90)
    return r.returncode, (r.stdout + r.stderr).strip()


def jobs():
    with open(JOBS) as fh:
        d = json.load(fh)
    return d["jobs"] if isinstance(d, dict) else d


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def lease_pid(holder):
    m = re.search(r"pid=(\d+)", holder or "")
    return int(m.group(1)) if m else None


def turn_reasons(db=STATE_DB, now=None):
    """Chat turns in flight: unexpired leases whose holder process is alive. Unreadable is busy."""
    import sqlite3

    if not os.path.exists(db):
        return []
    now = time.time() if now is None else now
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
        rows = c.execute(
            "select conversation_id, holder from session_turn_leases where expires_at > ?", (now,)
        ).fetchall()
    except Exception as e:
        return [f"cannot read turn leases in {db}: {e}"]
    out = []
    for conv, holder in rows:
        pid = lease_pid(holder)
        if pid is None or alive(pid):
            out.append(f"chat turn in flight: {conv}")
    return out


def busy_reasons(own_id):
    out = turn_reasons()
    import sqlite3

    for db in glob.glob(f"{HH}/kanban/boards/*/kanban.db") + glob.glob(f"{HH}/kanban/kanban.db"):
        if "_archived" in db:
            continue
        try:
            c = sqlite3.connect(db, timeout=10)
            c.execute("pragma query_only=1")
            for tid, pid in c.execute("select id, worker_pid from tasks where status='running'"):
                if pid and alive(pid):
                    out.append(f"kanban worker {tid} (pid {pid})")
        except Exception as e:
            out.append(f"cannot read {db}: {e}")  # unknown means not safe
    now = time.time()
    for j in jobs():
        if j["id"] == own_id:
            continue
        rc, txt = hermes("cron", "runs", j["id"])
        if rc != 0:
            out.append(f"cannot read cron runs for {j['name']} (rc {rc})")
            continue
        for line in txt.splitlines():
            m = re.match(
                r"\s*\S+\s+running\s+job=\S+.*?(\d{4}-\d\d-\d\dT[\d:.]+[+-]\d\d:\d\d)", line
            )
            if m:
                from datetime import datetime

                age = now - datetime.fromisoformat(m.group(1)).timestamp()
                if age < STALE_H * 3600:
                    out.append(f"cron run in progress: {j['name']} ({int(age / 60)} min)")
    rc, txt = (
        subprocess.run(
            ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], capture_output=True, text=True
        ).returncode,
        subprocess.run(
            ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], capture_output=True, text=True
        ).stdout,
    )
    ports = {
        m
        for ln in txt.splitlines()
        if ln.startswith("llama")
        for m in re.findall(r"127\.0\.0\.1:(\d+)", ln)
    }
    for p in ports:
        try:
            s = json.load(urllib.request.urlopen(f"http://127.0.0.1:{p}/slots", timeout=5))
            if any(x.get("is_processing") for x in s):
                out.append(f"model slot busy on port {p}")
        except Exception as e:
            out.append(f"cannot read model slots on port {p}: {e}")
    return out


def load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def save(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as fh:
        json.dump(s, fh)


def main():
    dry = "--dry-run" in sys.argv or "--status" in sys.argv
    me = next((j for j in jobs() if j["name"] == JOB_NAME), None)
    own = me["id"] if me else None
    busy = busy_reasons(own)
    if dry:
        print(
            "BUSY:\n  " + "\n  ".join(busy)
            if busy
            else "IDLE: a real run would restart after one more idle tick"
        )
        return
    if me is None:
        print(f"{JOB_NAME}: own job not found in jobs.json")
        sys.exit(1)
    s = load()
    s.setdefault("armed_since", time.time())
    if busy:
        s["idle"] = 0
        if time.time() - s["armed_since"] > STALL_H * 3600 and not s.get("stall_card"):
            rc, o = hermes(
                "kanban",
                "--board",
                "operator-actions",
                "create",
                f"Safe restart waiting over {STALL_H}h [safe-hermes-restart]",
                "--body",
                "Still busy:\n"
                + "\n".join(busy)
                + "\n\nThe job stays enabled and restarts once idle. Disable it to cancel.",
                "--tenant",
                "hermes-ops",
                "--assignee",
                ASSIGNEE,
                "--initial-status",
                "blocked",
            )
            s["stall_card"] = rc == 0
        save(s)
        return
    s["idle"] = s.get("idle", 0) + 1
    if s["idle"] < IDLE_TICKS:
        save(s)
        return
    rc, o = hermes("cron", "pause", own)  # disable first: guarantees a single restart
    paused = next((j for j in jobs() if j["id"] == own), {})
    if rc != 0 or paused.get("enabled", True):
        print(f"safe restart aborted: could not disable job ({o[-200:]})")
        sys.exit(1)
    with contextlib.suppress(OSError):
        os.remove(STATE)
    os.makedirs(os.path.dirname(TRIGGER), exist_ok=True)
    with open(TRIGGER, "w") as fh:  # a launchd agent watches this file
        fh.write(str(int(time.time())))
    print("idle confirmed: job disabled, restart trigger written")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"safe_hermes_restart error: {e}")
        sys.exit(1)
