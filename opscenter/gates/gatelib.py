"""
Shared wake-gate helpers for the ops center's scheduled jobs.

Purpose: One implementation of the agent runtime's cron wake-gate contract so every gate script
         behaves identically and fails the same way.

Wake-gate contract:
  - last stdout line {"wakeAgent": false}  -> agent is skipped, zero model cost
  - anything else                          -> agent wakes, stdout is injected into the prompt as context
  - the gate is honored ONLY when the script exits 0, so gates ALWAYS exit 0 and signal purely
    through stdout.

Fail-open vs fail-closed:
  These gates guard MUTATING jobs (they close tickets, move cards, post comments). A gate that
  silently swallows a real change is worse than an occasional wasted wake, so on any unexpected error
  we FAIL OPEN (wake the agent, hand it the error text) rather than gate silently. The one exception
  is a connector hiccup that the job itself already treats as a no-op, which is rate limited through
  the health file so a dead connector cannot spam.

State lives in GATE_STATE_DIR (default ~/.opscenter/cache/cron-gates).
"""

import contextlib
import json
import os
import subprocess
import sys
import time

STATE_DIR = os.environ.get("GATE_STATE_DIR") or os.path.expanduser("~/.opscenter/cache/cron-gates")


def _health_path(name):
    return os.path.join(STATE_DIR, f"{name}-health.json")


def load_health(name):
    try:
        with open(_health_path(name)) as fh:
            return json.load(fh)
    except Exception:
        return {"failures": 0, "last_alert_epoch": 0, "last_audit_date": ""}


def save_health(name, health):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = _health_path(name) + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(health, fh)
    os.replace(tmp, _health_path(name))


def gate_silent():
    """Nothing to do: skip the agent entirely."""
    print(json.dumps({"wakeAgent": False}))
    sys.exit(0)


def wake(*lines):
    """Wake the agent, handing it these lines as prompt context."""
    for ln in lines:
        if ln is not None:
            print(ln)
    sys.exit(0)


def failure_should_wake(name, err_text, backoff_first=3, cooldown=14400):
    """Fail-closed-with-backoff for connector errors.

    Returns True the first time a failure streak hits ``backoff_first``, then at
    most once per ``cooldown`` seconds. Keeps a dead connector from waking the
    agent every tick while still guaranteeing it is eventually surfaced.
    """
    h = load_health(name)
    h["failures"] = h.get("failures", 0) + 1
    now = int(time.time())
    should = False
    if (
        h["failures"] == backoff_first
        or h["failures"] > backoff_first
        and now - h.get("last_alert_epoch", 0) >= cooldown
    ):
        should = True
    if should:
        h["last_alert_epoch"] = now
    h["last_error"] = (err_text or "")[:300]
    save_health(name, h)
    return should


def clear_failures(name):
    h = load_health(name)
    streak = h.get("failures", 0)
    if streak:
        h["failures"] = 0
        h.pop("last_error", None)
        save_health(name, h)
    return streak


def audit_due(name, today):
    """True on the first run of a new calendar day (forced self-audit wake)."""
    h = load_health(name)
    return h.get("last_audit_date", "") != today


def mark_audit(name, today):
    h = load_health(name)
    h["last_audit_date"] = today
    save_health(name, h)


def run(cmd, timeout=180, env=None):
    """Run a subprocess, returning (rc, stdout, stderr). Never raises."""
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=full_env)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except Exception as exc:
        return 1, "", str(exc)


def load_json_file(path, default=None):
    try:
        with open(os.path.expanduser(path)) as fh:
            return json.load(fh)
    except Exception:
        return {} if default is None else default


def env_file_value(key, path=None):
    """Read KEY out of an env file (default GATE_ENV_FILE, else ~/.opscenter/.env), for a value such as a
    corporate CA bundle that a scheduled job needs and its environment does not carry. "" when absent."""
    path = path or os.environ.get("GATE_ENV_FILE") or os.path.expanduser("~/.opscenter/.env")
    try:
        with open(path) as fh:
            for line in fh:
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def curl_ca_bundle(path=None):
    return env_file_value("CURL_CA_BUNDLE", path)


# ---------------------------------------------------------------------------
# Accumulation + urgency: the batched-fold model.
#
# Cost problem this solves: an inbound monitor that cold-starts a full agent session every 30 minutes
# whenever the static triage keeps even one routine message, just to write a narrative fold into state,
# is session churn for work that is not time-critical.
#
# New model, parity-preserving:
#   - the 30-min Python pull/triage/feed-append is unchanged (the inbound signals
#     feed and its freshness stay live every 30 min, no model),
#   - kept items ACCUMULATE to a rolling file instead of waking the agent,
#   - the agent is woken to fold ONLY when (a) an URGENT item is present, or
#     (b) it is a scheduled drain hour and the accumulation is non-empty.
# Both wake paths fold the FULL accumulation and clear it, so nothing is lost and
# routine traffic lands in state on a 2x/day batch cadence.
# ---------------------------------------------------------------------------

# A keep-reason is "urgent" (wake now) if it starts with one of these prefixes.
# Everything else the scorer keeps (plain human / unknown-sender / unrecognized
# subject) is routine and batches. See inbound_score.py for how reasons are set.
URGENT_WHY_PREFIXES = (
    "urgent-signal",
    "flagged-high-importance",
    "novel-alert",
    "count-spike",
    "firing-unresolved",
)

# Local hours (24h) whose first tick force-drains a non-empty accumulation even with no urgent item.
# Noon and 5pm keep routine folds twice a workday and cap the wait at a few hours inside a 07-19
# monitor window. GATE_DRAIN_HOURS (comma separated) overrides them.
DRAIN_HOURS = {int(h) for h in os.environ.get("GATE_DRAIN_HOURS", "12,17").split(",") if h.strip()}


def is_urgent_why(why):
    w = (why or "").lower()
    return any(w.startswith(p) for p in URGENT_WHY_PREFIXES)


def _accum_path(name):
    return os.path.join(STATE_DIR, f"{name}-accumulated.json")


def load_accumulated(name):
    try:
        with open(_accum_path(name)) as fh:
            data = json.load(fh)
            return data.get("items", []), data.get("since")
    except Exception:
        return [], None


def accumulate(name, entries):
    """Append kept entries to the rolling accumulation. Each entry is the raw
    message dict plus injected _why / _kind / _pulled_at keys. Returns the new
    total count."""
    if not entries:
        items, _ = load_accumulated(name)
        return len(items)
    os.makedirs(STATE_DIR, exist_ok=True)
    items, since = load_accumulated(name)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not since:
        since = now
    items.extend(entries)
    tmp = _accum_path(name) + ".tmp"
    with open(tmp, "w") as fh:
        json.dump({"items": items, "since": since, "updated": now}, fh, indent=2)
    os.replace(tmp, _accum_path(name))
    with contextlib.suppress(OSError):
        os.chmod(_accum_path(name), 0o600)
    return len(items)


def clear_accumulated(name):
    with contextlib.suppress(OSError):
        os.remove(_accum_path(name))


def should_drain(now=None, drain_hours=None):
    """True on the first tick (minute < 30, matching the */30 cadence) of a
    configured drain hour, so a non-empty accumulation gets folded ~2x/day even
    without an urgent item."""
    now = now or time.localtime()
    hours = DRAIN_HOURS if drain_hours is None else drain_hours
    # First 10 minutes only: the monitors run every 10 min, so a wider window
    # would drain up to three times in the same hour.
    return now.tm_hour in hours and now.tm_min < 10


_inbound_store = None


def set_inbound_store(store):
    """Register the inbound files store (an object with harvest_messages(messages, surface) -> int), the
    `collector` slot's durable file hand-off. Without one, harvesting does nothing."""
    global _inbound_store
    _inbound_store = store


def harvest_inbound_files(messages, surface):
    """Hand every pulled message (before triage) to the inbound files store, so a file a direct report
    sends becomes a board item even if triage drops the message or the feed rolls over. Best effort: a
    failure here is logged to stderr and never changes the gate's outcome."""
    if not messages or _inbound_store is None:
        return 0
    try:
        return _inbound_store.harvest_messages(messages, surface)
    except Exception as exc:  # broad on purpose: the gate must never fail on this hook
        sys.stderr.write(f"[inbound-files] harvest skipped: {exc}\n")
        return 0
