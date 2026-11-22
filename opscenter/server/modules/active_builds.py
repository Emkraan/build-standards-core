"""
active_builds.py
Purpose: The active builds feed (a provider slot, read only): agent work that is running, stuck, failed or finished, so the Action Center can show
         what is being built and what needs a look. The consumer owns where the sessions come from (an agent runner's own database, a queue, a
         service) and how it knows one is alive. The core owns the row shape, the state vocabulary, the limits and the route. Nothing here starts
         or stops anything: a Stop action is a separate decision with its own confirmation (issue 308, items 7 and 26).
Date:    2026-11-20
Notes:   Opt in: with no provider (`OPSCENTER_BUILDS_PROVIDER` unset) there is no route and the panel is hidden. Unlike the docs drift feed this
         is never cached: a build shown as running after it died is the wrong answer, so every GET asks the provider, under a short limit.
         A source that fails or is slow is reported as an error with no rows. It is never shown as an empty list, because "nothing is running"
         and "I could not tell" are different answers.

Provider (`path/to/file.py:ClassName`):
         active_builds(now) -> [<build>]                            the sessions as the consumer sees them, any order
         authorize(headers, action, key) -> actor | falsy           action active-builds.read; the null default refuses everything
Build:   {id, title, state, started, finished?, activity?, activity_at?, outcome?, url?, kind?, lane?, pr?}
         lane: the repo lane or area the work belongs to (up to 40 characters), for the Lane select of the Live tab. Absent is null, never guessed.
         state: running | stuck | failed | finished     An unknown state is kept and drawn neutral. `started` and the other times are epoch
         seconds or an ISO string with an offset. `url` is shown only when it is an http or https link.
         pr: {number, url?, state?, red?}   the pull request that carries the work. number is a positive whole number, state is open,
         merged or closed (anything else is dropped, never called open), red is the count of failing checks (a missing count stays
         missing, it is never turned into zero), url follows the same http or https rule. A malformed block is no block.
Summary: {fetched_utc, counts: {running, stuck, failed, finished, total}, builds (at most 50, newest first), truncated, error}
Route:   GET /api/active-builds
API:     summarize(builds, now=None)  read(provider, now=None)  register(registry, provider)
"""

from __future__ import annotations

import datetime as dt
import threading

import optional_provider as op

MAX_BUILDS = 50
MAX_TEXT = 200
MAX_RED = 999
PR_STATES = ("open", "merged", "closed")
TIMEOUT_SECONDS = 8
STATES = ("running", "stuck", "failed", "finished")


def _clip(value, limit=MAX_TEXT):
    text = " ".join(str(value).split()) if value is not None else ""
    return text[:limit]


def _when(value):
    """An epoch number or an ISO string with an offset, as epoch seconds. Anything else is None, never a guess."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, str) and value.strip():
        try:
            parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.timestamp()
    return None


def _safe_url(value):
    text = _clip(value, 400)
    return text if text.startswith(("https://", "http://")) else None


def _whole(value):
    """A whole number from a real number type. A boolean, a string, a float with a fraction, NaN and infinity are not numbers here."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if (
        isinstance(value, float)
        and value == value
        and value not in (float("inf"), float("-inf"))
        and value == int(value)
    ):
        return int(value)
    return None


def _pr(raw):
    """The pull request block, or None. Each part is checked alone, so one bad part never takes the others down with it."""
    if not isinstance(raw, dict):
        return None
    number = _whole(raw.get("number"))
    if number is None or number <= 0:
        return None
    state = _clip(raw.get("state"), 20).lower() if isinstance(raw.get("state"), str) else ""
    red = _whole(raw.get("red"))
    return {
        "number": number,
        "url": _safe_url(raw.get("url")),
        "state": state if state in PR_STATES else None,
        "red": min(red, MAX_RED) if red is not None and red >= 0 else None,
    }


def _build(raw):
    if not isinstance(raw, dict) or raw.get("id") in (None, ""):
        return None
    state = _clip(raw.get("state"), 20).lower() or "running"
    return {
        "id": _clip(raw.get("id"), 80),
        "title": _clip(raw.get("title")) or "Untitled",
        "state": state,
        "started": _when(raw.get("started")),
        "finished": _when(raw.get("finished")),
        "activity": _clip(raw.get("activity")) or None,
        "activity_at": _when(raw.get("activity_at")),
        "outcome": _clip(raw.get("outcome")) or None,
        "url": _safe_url(raw.get("url")),
        "kind": _clip(raw.get("kind"), 40) or None,
        "lane": _clip(raw.get("lane"), 40) or None,
        "pr": _pr(raw.get("pr")),
    }


def summarize(builds, now=None):
    """The rows a client draws: malformed ones dropped, newest first, capped, with the counts of what was seen before the cap."""
    now = now if now is not None else dt.datetime.now(dt.timezone.utc).timestamp()
    rows = [b for b in (_build(x) for x in (builds if isinstance(builds, list) else [])) if b]
    counts = {s: 0 for s in STATES}
    for b in rows:
        if b["state"] in counts:
            counts[b["state"]] += 1
    counts["total"] = len(rows)
    rows.sort(key=lambda b: b["activity_at"] or b["started"] or 0, reverse=True)
    return {
        "fetched_utc": dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "counts": counts,
        "builds": rows[:MAX_BUILDS],
        "truncated": max(0, len(rows) - MAX_BUILDS),
        "error": None,
    }


def _failed(reason, now=None):
    out = summarize([], now)
    out["error"] = reason
    return out


def read(provider, now=None):
    """Ask the provider now, under a limit. A missing method, an exception or a slow source is an error with no rows."""
    fn = op.method(provider, "active_builds")
    if fn is None:
        return _failed("the provider has no active_builds method", now)
    box = {}

    def run():
        try:
            box["value"] = fn(
                now if now is not None else dt.datetime.now(dt.timezone.utc).timestamp()
            )
        except Exception as exc:  # noqa: BLE001 a provider is consumer code, whatever it raises is a failed read and not a crash
            box["error"] = type(exc).__name__

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(TIMEOUT_SECONDS)
    if worker.is_alive():
        return _failed(f"the source did not answer within {TIMEOUT_SECONDS} s", now)
    if "error" in box:
        return _failed(f"the source failed ({box['error']})", now)
    value = box.get("value")
    if not isinstance(value, list):
        return _failed("the source did not return a list", now)
    return summarize(value, now)


def register(r, provider):
    def get(q):
        op.actor_of(q.headers, provider, "active-builds.read")
        return read(provider)

    r.add("GET", "/api/active-builds", get, name="active_builds.get")
