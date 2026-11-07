"""
sprint_trend.py
Purpose: The sprint trend: team totals for the last closed sprints plus the active one (items, how many are done today, points, points done, how
         many were carried into a later sprint), and the list of recent closed sprints the per sprint view is allowed to open. Pure: the tracker
         is two small functions the caller passes in (the "slot"), so a tracker without a Jira style sprint field supplies its own.
Date:    2026-11-07
Notes:   Ported from the consumer's running module. "Committed and completed" is as built there: there is no committed at start snapshot, so
         `items` is what is in the sprint now and `done` is what the tracker shows today as done. A source that can give the count at sprint
         start returns it as `committed` per sprint and it is passed through; the client labels the figure "items in sprint" when absent.

Slot:    closed_sprints(limit) -> [{id, name, start, end, complete?}]      newest first not required (it is sorted here); None or [] = none
         sprint_items(sprint_id) -> [{key, status_category ("done" or other), points (number or None), later_sprint (bool)}] | None
         `later_sprint` is the source's answer to "also in a sprint that started later", so the core never reads a raw sprint field.
         None from sprint_items means the tracker cannot read that sprint: the trend raises SourceUnreadable (a failed read is never an empty page).
API:     recent_closed(closed, limit=PAST_SPRINTS) -> [sprint]     normalise, drop non closed rows without an id, dedupe by id, newest first
         trend(closed, active, sprint_items) -> [row]              oldest first, the active sprint last
         row: {id, name, start, end, active, items, done, points, points_done, carried, committed?}
         allowed_closed_id(value, closed) -> int                   400 for a non number, 404 for an id that is not a recent closed sprint
"""

from __future__ import annotations

TREND_SPRINTS = 6
PAST_SPRINTS = 12


class SourceUnreadable(Exception):
    status = 502


class BadSprint(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def _norm(s):
    out = {
        "id": s.get("id"),
        "name": s.get("name") or "",
        "start": s.get("start") or "",
        "end": s.get("end") or "",
        "complete": s.get("complete") or "",
    }
    if s.get("committed") is not None:
        out["committed"] = s["committed"]
    return out


def recent_closed(closed, limit=PAST_SPRINTS):
    """Closed sprints, normalised, one per id, newest first by end date (then completion date). A row without an id, or one whose state is
    present and not closed, is dropped."""
    seen = {}
    for s in closed or []:
        if not isinstance(s, dict) or s.get("id") in (None, ""):
            continue
        if s.get("state") not in (None, "", "closed"):
            continue
        seen[s["id"]] = _norm(s)
    rows = sorted(seen.values(), key=lambda r: r["end"] or r["complete"], reverse=True)
    return rows[:limit]


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _row(sp, items, active):
    n = done = carried = 0
    pts = pts_done = 0.0
    for it in items:
        p = _num(it.get("points"))
        n += 1
        pts += p
        if it.get("status_category") == "done":
            done += 1
            pts_done += p
        if it.get("later_sprint"):
            carried += 1
    out = {
        "id": sp["id"],
        "name": sp.get("name") or "",
        "start": sp.get("start") or "",
        "end": sp.get("end") or "",
        "active": active,
        "items": n,
        "done": done,
        "points": pts,
        "points_done": pts_done,
        "carried": carried,
    }
    if sp.get("committed") is not None:
        out["committed"] = sp["committed"]
    return out


def trend(closed, active, sprint_items):
    """The trend rows: the last TREND_SPRINTS closed sprints, oldest first, then the active sprint (when there is one)."""
    sprints = [(sp, False) for sp in reversed(recent_closed(closed, TREND_SPRINTS))]
    if active and active.get("id") not in (None, ""):
        sprints.append((active, True))
    rows = []
    for sp, is_active in sprints:
        items = sprint_items(sp["id"])
        if items is None:
            raise SourceUnreadable(f"the tracker could not read sprint {sp['id']}")
        rows.append(_row(sp, items, is_active))
    return rows


def allowed_closed_id(value, closed):
    """The sprint id the per sprint view may open: only an id in the recent closed list. 400 for a non number, 404 for any other id."""
    try:
        sid = int(value)
    except (TypeError, ValueError):
        raise BadSprint("sprint id must be a number", 400) from None
    if not any(s.get("id") == sid for s in closed or []):
        raise BadSprint(f"sprint {sid} is not one of the recent closed sprints", 404)
    return sid
