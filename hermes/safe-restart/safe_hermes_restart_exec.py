#!/usr/bin/env python3
"""Restart half of safe_hermes_restart.py. Run by the ai.hermes.safe-restart launchd agent (WatchPaths on
the trigger file), so it lives outside the gateway it restarts. Does nothing unless a fresh trigger exists."""

import json
import os
import re
import subprocess
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


def take_trigger():
    """Consume the trigger once. Absent or older than 10 min means nothing to do."""
    try:
        with open(TRIGGER) as fh:
            parts = fh.read().split()
        age = time.time() - int(parts[0])
        os.remove(TRIGGER)
        global NOOP
        NOOP = NOOP or "noop" in parts[1:]  # test hook: echo "$(date +%s) noop" > trigger
    except Exception:
        return False
    return age < 600


def main():
    if not take_trigger():
        return
    time.sleep(5)
    old = gw_pid()
    log(f"old gateway pid {old}")
    if NOOP:
        log("NOOP: skipping kickstart")
        return
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
            f"Gateway pid before {old}, after {new}. See ~/.hermes/logs/safe-restart.log. "
            "Check: hermes gateway status",
            done=False,
            blocked=True,
        )


main()
