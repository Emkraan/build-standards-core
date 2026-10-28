#!/usr/bin/env python3
"""
sitrep.py

Purpose: The one daily message for the owner, built with no agent and no model call. It lists only what waits on
         the owner in the ops center, read from the same server endpoints the sidebar badges use, so the numbers
         match what the owner sees there:
           1. Action Center Now items (the board minus what the owner resolved, ignored or snoozed)
           2. Reviews, builds, knowledge and debt decisions that need the owner
           3. Infrastructure problems
           4. Alerts not acknowledged and jobs failing now
Usage:   sitrep.py
Exit:    0 when the sitrep printed, 1 when the ops center could not be read (the scheduler then sends its failure
         notice to the same place, so a dead ops center is never silent).
Config:  OPSCENTER_URL (default http://127.0.0.1:<OPSCENTER_PORT>), OPSCENTER_PORT (default 8766),
         SITREP_REVIEWS (JSON list of {"label", "path"}: the review endpoints whose counts.needs_me is summed,
         default the primary, secondary and other repository endpoints the app serves).
System python3 is 3.9: no 3.10+ syntax.
"""

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

URL = (
    os.environ.get("OPSCENTER_URL")
    or f"http://127.0.0.1:{os.environ.get('OPSCENTER_PORT') or '8766'}"
)
ORDER = {"critical": 0, "highest": 0, "high": 1, "medium": 2, "low": 3}
MAX_ITEMS = 10
DEFAULT_REVIEWS = [
    {"label": "Primary", "path": "/api/platform-reviews"},
    {"label": "Secondary", "path": "/api/team_prefix-reviews"},
    {"label": "other repos", "path": "/api/repo-reviews"},
]


def review_sources():
    try:
        v = json.loads(os.environ.get("SITREP_REVIEWS") or "null")
    except ValueError:
        v = None
    return v if isinstance(v, list) and v else DEFAULT_REVIEWS


def get_json(path, timeout=30):
    with urllib.request.urlopen(URL + path, timeout=timeout) as r:
        return json.load(r)


def needs_me(path):
    """counts.needs_me from a review endpoint, None when it could not be read."""
    try:
        return int((get_json(path, 60).get("counts") or {}).get("needs_me") or 0)
    except (urllib.error.URLError, OSError, ValueError, TypeError):
        return None


def open_action_items():
    board = get_json("/data/action-center.json").get("items") or []
    handled = get_json("/api/action-handled")
    handled = handled.get("handled", handled)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    out = []
    for it in board:
        h = handled.get(it.get("fp")) or {}
        act = h.get("act")
        if act in ("resolved", "ignored", "ignored_forever"):
            continue
        if act == "snoozed" and (h.get("until") or "") > now:
            continue
        out.append(it)
    out.sort(key=lambda i: ORDER.get(str(i.get("priority") or "").lower(), 9))
    return out


def plural(n, word, many=None):
    return f"{n} {word if n == 1 else (many or word + 's')}"


def build():
    badges = get_json("/api/badges")
    items = open_action_items()
    alerts = get_json("/api/alerts")
    reviews = {s["label"]: needs_me(s["path"]) for s in review_sources()}

    lines, total = [], 0
    if items:
        total += len(items)
        lines.append(f"**Action Center ({len(items)})**")
        for it in items[:MAX_ITEMS]:
            pri = str(it.get("priority") or "").lower()
            tag = f"[{pri}] " if pri in ("critical", "highest", "high") else ""
            lines.append(f"- {tag}{it.get('title') or '(untitled)'}")
        if len(items) > MAX_ITEMS:
            lines.append(f"- and {len(items) - MAX_ITEMS} more")
        lines.append("")

    rv = {k: v for k, v in reviews.items() if v}
    if rv:
        total += sum(rv.values())
        lines.append(
            f"**Reviews ({sum(rv.values())}):** " + ", ".join(f"{k} {v}" for k, v in rv.items())
        )
    unread = [k for k, v in reviews.items() if v is None]
    waiting = int((badges.get("builds") or {}).get("waiting") or 0)
    if waiting:
        total += waiting
        lines.append(f"**Builds waiting on your approval:** {waiting}")
    kp, kd = len(badges.get("knowledge_pending") or []), int(badges.get("knowledge_docs") or 0)
    if kp or kd:
        total += kp + kd
        parts = ([plural(kp, "proposal")] if kp else []) + ([plural(kd, "doc gap")] if kd else [])
        lines.append("**Knowledge:** " + ", ".join(parts))
    debt = int(badges.get("debt") or 0)
    if debt:
        # A standing backlog, not today's work: listed, never counted in the headline.
        lines.append(f"**Debt decisions open:** {debt}")
    infra = badges.get("infra") or {}
    if infra.get("count"):
        total += int(infra["count"])
        lines.append(
            f"**Infrastructure ({infra['count']}):** " + "; ".join((infra.get("items") or [])[:3])
        )

    c = alerts.get("counts") or {}
    failing = sorted({a["name"] for a in alerts.get("alerts") or [] if a.get("open")})
    if c.get("unacked") or failing:
        txt = plural(int(c.get("unacked") or 0), "new alert")
        if failing:
            txt += ", failing now: " + ", ".join(failing)
        lines.append(f"**Alerts:** {txt}")

    day = dt.datetime.now().strftime("%a %b %d")
    head = [f"**Ops center sitrep, {day}**"]
    head.append(f"{plural(total, 'item')} waiting on you." if total else "Nothing waiting on you.")
    if unread:
        lines.append(f"_Could not read reviews for {', '.join(unread)}, check the Reviews page._")
    body = head + ([""] + lines if lines else [])
    while body and body[-1] == "":
        body.pop()
    body += ["", URL + "/"]
    return "\n".join(body)


def main():
    try:
        text = build()
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as e:
        print(f"Ops center sitrep failed: the ops center at {URL} could not be read ({e}).")
        return 1
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
