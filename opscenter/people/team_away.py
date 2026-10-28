#!/usr/bin/env python3
"""
Who on the owner's team is out today and in the next two weeks, for the Action Center.

Source: the meetings slot's `away` command (free/busy, status out of office only, DESIGN.md 12.14) for the owner's direct
reports in one_on_ones.ROSTER. Times only, never subjects. The board composer (OPSCENTER_TEAM_AWAY) calls
`snapshot()` on every refresh. The read runs at most every REFRESH_S, and the last good
result is kept with an error note when a read fails, so a failed read never shows the team
as all in (unknown never hides).
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("OPSCENTER_ROOT") or Path.home() / ".opscenter")
STATE = Path(os.environ.get("OPSCENTER_STATE_DIR") or ROOT / "state")
STORE = Path(os.environ.get("TEAM_AWAY_STORE") or STATE / "dashboard" / "team-away.json")
REFRESH_S = 30 * 60
DAYS = 14


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _load():
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save(d):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    os.replace(tmp, STORE)


def team():
    import one_on_ones

    return [p for p in one_on_ones.ROSTER if p.get("group", "report") == "report"]


def _pull(people, gm=None):
    if gm is None:
        import one_on_ones

        gm = one_on_ones._gm
    raw = gm(
        ["away", "--emails", ",".join(p["email"] for p in people), "--days", str(DAYS)], timeout=60
    )
    by_email = raw.get("people") or {}
    out = []
    for p in people:
        r = by_email.get(p["email"].lower()) or {"error": "schedule missing", "blocks": []}
        out.append(
            {
                "name": p["name"],
                "first": p["first"],
                "error": r.get("error"),
                "blocks": r.get("blocks") or [],
            }
        )
    return out


def snapshot(force=False, gm=None, now=None):
    """Return {checked_utc, days, people:[{name, first, error, blocks}], error, stale}."""
    now = now or _now()
    cur = _load()
    last = cur.get("checked_utc")
    fresh = False
    if last:
        try:
            fresh = (
                now - dt.datetime.fromisoformat(last.replace("Z", "+00:00"))
            ).total_seconds() < REFRESH_S
        except ValueError:
            fresh = False
    if fresh and not force and not cur.get("error"):
        return cur
    try:
        people = _pull(team(), gm)
        cur = {
            "checked_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "days": DAYS,
            "people": people,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - keep the last good answer, flagged
        cur = dict(cur) if cur else {}
        cur.setdefault("people", [])
        cur.setdefault("days", DAYS)
        cur["error"] = "free/busy read failed: %s" % str(exc)[:200]  # noqa: UP031
        cur["error_utc"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    _save(cur)
    return cur


if __name__ == "__main__":
    print(json.dumps(snapshot(force=True), indent=1))
