#!/usr/bin/env python3
"""Safe single restart of Hermes (drain check). Script-only cron (no agent). Ships PAUSED.

Operator enables the job; each tick checks for idle work. After two idle ticks in a row it pauses
this job first (so it can only ever fire once), then writes a trigger file. A separate launchd agent (installed once,
see safe_hermes_restart_exec.py) bounces the service from outside it, verifies the new gateway, and records the result on the operator-actions board.

Idle means: no live kanban worker, no other cron run in progress, no busy model slot, and no chat
turn in flight (a live, unexpired turn lease in the session store, which the desktop backend and the
gateway both take). A probe that cannot be read counts as busy, never as idle.
Gateway-only mode (no backend service label in ~/.hermes/state/safe-restart.backend) adds two more
sources: the gateway's own health counts, and any backend the desktop app spawned (found through its
spawn ledger), which counts as interactive work and is never restarted or killed by this tool.
Flags: --dry-run (report only), --status.
"""

import contextlib
import datetime as dt
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
BACKEND_FILE = f"{HH}/state/safe-restart.backend"  # first word: launchd label of a backend service
API_URL = os.environ.get("SAFE_RESTART_API", "http://127.0.0.1:8642")  # gateway API server
KEY_FILE = os.environ.get("SAFE_RESTART_KEY_FILE", f"{HH}/.env")  # holds API_SERVER_KEY
LEDGER = os.environ.get("SAFE_RESTART_LEDGER", f"{HH}/spawn-ledger.json")  # app-spawned backends
APP_PURPOSES = ("dashboard", "serve")  # ledger purposes the desktop app itself attaches to
LOOPBACK = ("127.0.0.1", "localhost", "::1")
START_SLACK_S = 5  # a recorded create time matches a live process start within this many seconds
TOKEN_RE = re.compile(r'__HERMES_SESSION_TOKEN__\s*=\s*"([^"\\]{16,})"')


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


def gateway_only(path=None):
    """Gateway-only mode: no backend service label is configured, so the gateway is the only service."""
    try:
        with open(path or BACKEND_FILE) as fh:
            return not fh.read().split()
    except OSError:
        return True


def api_key(path=None):
    """API_SERVER_KEY from the agent env file, or None. Never printed or logged."""
    try:
        with open(path or KEY_FILE) as fh:
            for line in fh:
                if line.startswith("API_SERVER_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'") or None
    except OSError:
        return None
    return None


def gateway_health(timeout=6):
    """GET /health/detailed on the gateway API server. Raises when it cannot be read."""
    key = api_key()
    if not key:
        raise RuntimeError("no API_SERVER_KEY in the Hermes environment")
    req = urllib.request.Request(
        API_URL + "/health/detailed", headers={"Authorization": "Bearer " + key}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def gateway_reasons(read=None, agents=True):
    """Busy reasons from the gateway's own counts: it reports busy, cannot drain, or holds agent runs,
    API runs, process completions or delegations. The counts carry no session ids and there is no
    admission fence, so this is a smaller guarantee than the backend idle proof. An unreadable health
    is busy, never idle. agents=False skips the busy flag and the agent count: a tick that runs as a
    cron job inside the gateway may be counted by them, so only the restart helper (after the tick
    exited) reads them."""
    try:
        h = (read or gateway_health)()
    except (OSError, RuntimeError, ValueError) as e:  # URLError and JSON errors are subclasses
        return [f"cannot read the gateway health: {str(e)[:120]}"]
    if not isinstance(h, dict) or "gateway_busy" not in h:
        return ["gateway health carries no busy flag"]
    out = []
    if h.get("gateway_drainable") is False:
        out.append("gateway cannot drain right now")
    queues = ((h.get("readiness") or {}).get("checks") or {}).get("background_queues") or {}
    counts = [
        ("active_api_runs", "API run"),
        ("process_completions", "process completion"),
        ("active_delegations", "delegation"),
    ]
    if agents:
        counts.insert(0, ("active_agents", "agent run"))
    for key, name in counts:
        n = queues.get(key) if key in queues else h.get(key)
        if isinstance(n, int) and n > 0:
            out.append(f"gateway has {n} {name}{'' if n == 1 else 's'} in flight")
    if agents and h.get("gateway_busy") and not out:
        out.append("gateway reports it is busy")
    return out


def started_at(pid):
    """Process start time as epoch seconds, or None."""
    try:
        r = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5
        )
        txt = " ".join(r.stdout.split())
        return dt.datetime.strptime(txt, "%a %b %d %H:%M:%S %Y").timestamp() if txt else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def app_backends(ledger=None):
    """Live backends the desktop app spawned: [{pid, port}]. Only ledger entries the app itself attaches
    to (purpose dashboard or serve, loopback, not isolated) whose process is alive and whose start time
    matches the recorded create time, so a reused pid is never taken for a backend. A missing ledger
    means none (the app is closed). Raises ValueError when the ledger exists and cannot be read."""
    path = ledger or LEDGER
    if not os.path.exists(path):
        return []
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        raise ValueError(f"spawn ledger unreadable: {str(e)[:100]}") from e
    entries = data if isinstance(data, list) else (data or {}).get("entries", [])
    out, seen = [], set()
    for e in entries if isinstance(entries, list) else []:
        if (
            not isinstance(e, dict)
            or e.get("purpose") not in APP_PURPOSES
            or e.get("isolated") is True
        ):
            continue
        pid, port = e.get("pid"), e.get("port")
        if (
            not isinstance(pid, int)
            or not isinstance(port, int)
            or pid <= 0
            or not 0 < port <= 65535
        ):
            continue
        if str(e.get("host", "")).lower() not in LOOPBACK or pid in seen or not alive(pid):
            continue
        started, created = started_at(pid), e.get("create_time")
        try:
            if started is None or created is None or abs(started - float(created)) > START_SLACK_S:
                continue
        except (TypeError, ValueError):
            continue
        seen.add(pid)
        out.append({"pid": pid, "port": port})
    return out


def backend_proof(backend, timeout=8):
    """The backend's own idle proof (GET /api/health/idle with the session token its loopback page embeds).
    Raises when it cannot be read."""
    base = f"http://127.0.0.1:{backend['port']}"
    with urllib.request.urlopen(base + "/", timeout=5) as r:
        m = TOKEN_RE.search(r.read(400000).decode("utf-8", "replace"))
    if not m:
        raise RuntimeError("no session token on the backend page")
    req = urllib.request.Request(
        base + "/api/health/idle", headers={"X-Hermes-Session-Token": m.group(1)}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def backend_reasons(ledger=None, read=None):
    """Interactive work in a desktop-app backend: busy when it says so or cannot be read. The helper
    never restarts or kills such a backend, it only waits for it."""
    try:
        found = app_backends(ledger)
    except ValueError as e:
        return [str(e)]
    out = []
    for b in found:
        try:
            proof = (read or backend_proof)(b)
        except (OSError, RuntimeError, ValueError) as e:
            out.append(f"desktop backend pid {b['pid']} cannot prove it is idle: {str(e)[:100]}")
            continue
        if not isinstance(proof, dict) or proof.get("idle") is not True:
            why = proof.get("reason") or proof.get("detail") if isinstance(proof, dict) else None
            out.append(f"desktop backend pid {b['pid']} is busy ({why or 'not idle'})")
    return out


def busy_reasons(own_id):
    out = turn_reasons()
    if gateway_only():
        out += gateway_reasons(agents=False) + backend_reasons()
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
