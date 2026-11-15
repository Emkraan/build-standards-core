#!/usr/bin/env python3
"""Restart half of safe_hermes_restart.py. Run by the ai.hermes.safe-restart launchd agent (WatchPaths on
the trigger file), so it lives outside the gateway it restarts. Does nothing unless a fresh trigger exists.

Fenced mode (off by default, see fence_enabled): freeze new work for a bounded window, re-check idle
inside it, restart the backend and then the gateway, verifying each, and always release the freeze.
With the flag off the behaviour is the original single gateway kickstart, unchanged."""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request

HOME = os.path.expanduser("~")
HH = f"{HOME}/.hermes"
LABEL = f"gui/{os.getuid()}/ai.hermes.gateway"
ENV = {
    "HOME": HOME,
    "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"),
    "HERMES_HOME": HH,
}
FENCE_FILE = f"{HH}/state/safe-restart.fence"  # flag: present means fenced mode on (default off)
FREEZE_FILE = f"{HH}/state/safe-restart.freeze"  # freeze marker: holds the epoch the freeze expires
BACKEND_FILE = f"{HH}/state/safe-restart.backend"  # first line: launchd label of the backend
FREEZE_S = 30  # default freeze window in seconds; a parameter, see freeze_seconds
NOOP = os.environ.get("SAFE_RESTART_NOOP") == "1"


def _assignee():
    """Who the cards go to: first line of ~/.hermes/state/safe-restart.assignee, else 'operator'."""
    try:
        return open(os.path.expanduser("~/.hermes/state/safe-restart.assignee")).read().split()[0]
    except Exception:
        return "operator"


ASSIGNEE = _assignee()


def log(m):
    print(time.strftime("%F %T"), m, flush=True)


def gw_pid():
    r = subprocess.run(["launchctl", "list", "ai.hermes.gateway"], capture_output=True, text=True)
    m = re.search(r'"PID"\s*=\s*(\d+)', r.stdout)
    return int(m.group(1)) if m else None


def card(title, body, done, blocked):
    a = [
        "hermes",
        "kanban",
        "--board",
        "operator-actions",
        "create",
        title,
        "--body",
        body,
        "--tenant",
        "hermes-ops",
        "--assignee",
        ASSIGNEE,
    ]
    if blocked:
        a += ["--initial-status", "blocked"]
    r = subprocess.run(a, env=ENV, capture_output=True, text=True)
    m = re.search(r"t_[0-9a-f]+", r.stdout + r.stderr)
    if done and m:
        subprocess.run(
            [
                "hermes",
                "kanban",
                "--board",
                "operator-actions",
                "complete",
                m.group(0),
                "--summary",
                "Restart verified",
            ],
            env=ENV,
            capture_output=True,
            text=True,
        )


TRIGGER = f"{HH}/state/safe-restart.trigger"


FENCE_TOKEN = False


def take_trigger():
    """Consume the trigger once. Absent or older than 10 min means nothing to do."""
    try:
        with open(TRIGGER) as fh:
            parts = fh.read().split()
        age = time.time() - int(parts[0])
        os.remove(TRIGGER)
        global NOOP, FENCE_TOKEN
        NOOP = NOOP or "noop" in parts[1:]  # test hook: echo "$(date +%s) noop" > trigger
        FENCE_TOKEN = "fence" in parts[1:]  # per-run opt in to fenced mode
    except Exception:
        return False
    return age < 600


def fence_enabled(flag_file=None, token=False):
    """Fenced mode is opt-in: the env var SAFE_RESTART_FENCE=1, the flag file, or a 'fence' trigger token."""
    return (
        token
        or os.environ.get("SAFE_RESTART_FENCE") == "1"
        or os.path.exists(flag_file or FENCE_FILE)
    )


def freeze_seconds(flag_file=None):
    """Freeze window: env SAFE_RESTART_FREEZE_S, else a number in the flag file, else FREEZE_S."""
    for raw in (os.environ.get("SAFE_RESTART_FREEZE_S"), _first_word(flag_file or FENCE_FILE)):
        try:
            v = float(raw)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    return FREEZE_S


def _first_word(path):
    try:
        with open(path) as fh:
            return fh.read().split()[0]
    except Exception:
        return None


def backend_label(path=None):
    w = _first_word(path or BACKEND_FILE)
    return w if w and "/" in w else (f"gui/{os.getuid()}/{w}" if w else None)


def unit_pid(label):
    r = subprocess.run(
        ["launchctl", "list", label.rsplit("/", 1)[-1]], capture_output=True, text=True
    )
    m = re.search(r'"PID"\s*=\s*(\d+)', r.stdout)
    return int(m.group(1)) if m else None


def restart_unit(label, name, pid_of):
    """Kickstart one launchd unit and verify a new process that stays up for 30 s. Returns (ok, old, new)."""
    old = pid_of()
    r = subprocess.run(["launchctl", "kickstart", "-k", label], capture_output=True, text=True)
    log(f"{name} kickstart rc={r.returncode} {r.stderr.strip()}")
    new = None
    for _ in range(60):
        time.sleep(5)
        new = pid_of()
        if new and new != old:
            break
    ok = bool(new and new != old)
    if ok:
        time.sleep(30)
        ok = pid_of() == new
    log(f"{name} pid {old} -> {new} stable={ok}")
    return ok, old, new


def freeze_on(seconds):
    os.makedirs(os.path.dirname(FREEZE_FILE), exist_ok=True)
    with open(FREEZE_FILE, "w") as fh:
        fh.write(str(int(time.time() + seconds)))
    log(f"freeze on for {seconds:g}s")


def freeze_off():
    try:
        os.remove(FREEZE_FILE)
    except FileNotFoundError:
        pass
    except OSError as e:
        log(f"freeze release failed: {e} (the marker expires on its own)")
        return
    log("freeze released")


def idle_reasons():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import safe_hermes_restart as sr

    return sr.busy_reasons(None)


def run_fenced(seconds):
    """Freeze, re-check idle, restart backend then gateway (verified each). Returns (ok, detail, old, new).
    The freeze is released on every exit path."""
    old = new = None
    freeze_on(seconds)
    try:
        time.sleep(seconds)
        busy = idle_reasons()
        if busy:
            return (
                False,
                "work started inside the freeze, nothing restarted: " + "; ".join(busy),
                old,
                new,
            )
        label = backend_label()
        if label:
            ok, b_old, b_new = restart_unit(label, "backend", lambda: unit_pid(label))
            if not ok:
                return (
                    False,
                    f"backend did not come back (pid {b_old} -> {b_new}); gateway left alone",
                    old,
                    new,
                )
        else:
            log("no backend configured (safe-restart.backend): backend step skipped")
        ok, old, new = restart_unit(LABEL, "gateway", gw_pid)
        return ok, "backend then gateway", old, new
    except Exception as e:
        log(f"fenced restart error: {e}")
        return False, f"error: {e}", old, new
    finally:
        freeze_off()


def main():
    if not take_trigger():
        return
    time.sleep(5)
    old = gw_pid()
    log(f"old gateway pid {old}")
    if NOOP:
        log("NOOP: skipping kickstart")
        return
    if fence_enabled(token=FENCE_TOKEN):
        ok, detail, old, new = run_fenced(freeze_seconds())
        log(f"fenced restart ok={ok}: {detail}")
    else:
        r = subprocess.run(["launchctl", "kickstart", "-k", LABEL], capture_output=True, text=True)
        log(f"kickstart rc={r.returncode} {r.stderr.strip()}")
        new = None
        for _ in range(60):
            time.sleep(5)
            new = gw_pid()
            if new and new != old:
                break
        ok = bool(new and new != old)
        if ok:
            time.sleep(30)
            ok = gw_pid() == new  # still the same pid after 30s: it did not crash-loop
        log(f"new gateway pid {new} stable={ok}")
        detail = ""
    model = "not checked"
    try:
        with open(f"{HH}/runtimes/llamacpp/server.json") as fh:
            base = json.load(fh)["base_url"]
        for _ in range(90):  # local model may take minutes to reload
            try:
                urllib.request.urlopen(base + "/models", timeout=5)
                model = "answering"
                break
            except Exception:
                time.sleep(10)
        else:
            model = "not answering after 15 min"
    except Exception:
        pass
    log(f"model server: {model}")
    if ok:
        card(
            "Hermes restarted safely [safe-hermes-restart]",
            f"Gateway pid {old} -> {new}. Model server: {model}. Job disabled again; enable it to repeat.",
            done=True,
            blocked=False,
        )
    else:
        card(
            "Safe restart FAILED [safe-hermes-restart]",
            f"Gateway pid before {old}, after {new}. {detail} See ~/.hermes/logs/safe-restart.log. "
            "Check: hermes gateway status",
            done=False,
            blocked=True,
        )


if __name__ == "__main__":
    main()
