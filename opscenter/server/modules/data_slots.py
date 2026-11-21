"""
data_slots.py
Purpose: The data file form of the tracker and people slots (opscenter/DESIGN.md 12.74). A consumer with no tracker driver and no people
         provider puts plain JSON files in the state directory and the pages render from them. Read only: every write route stays absent.
Settings: OPSCENTER_TRACKER_FILES=1   the Work tracking pages read <state>/slots/tracker/*.json
          OPSCENTER_PEOPLE_FILES=1    the 1:1s page reads <state>/slots/people/board.json
          (OPSCENTER_TRACKER and OPSCENTER_PEOPLE keep their meaning: the reference tracker driver, and the people provider file. When a
          files switch is on, the matching provider switch is ignored, so the two forms never register the same route twice.)
Files:    tracker/sprint.json      {sprint, me, items[]}                       GET /api/jira/sprint
          tracker/backlog.json     {active_sprint, items[]}                    GET /api/jira/backlog
          tracker/approvals.json   {pending[], inflight[]}                     GET /api/jira/approvals
          tracker/needs-me.json    {items[]}                                   GET /api/jira/needs-me
          people/board.json        {people[], sources}                         GET /api/one-on-ones
          A missing file answers the empty page, never a 404 (a 404 means the slot is off). A file that is not a JSON object is an error the
          page shows (HTTP 502), never an empty page. generated_utc is the file's modification time unless the file carries one, and
          count is the length of items when the file does not carry it.
Date:    2026-11-21
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

OFF = ("", "0", "false", "off", "no")


def files(name):
    """True when the slot switch `name` has its data file form on: the variable `<name>_FILES` is set."""
    return os.environ.get(f"{name}_FILES", "").strip().lower() not in OFF


def _state():
    return Path(
        os.environ.get("OPSCENTER_STATE_DIR")
        or Path(os.environ.get("OPSCENTER_ROOT") or Path.home() / ".opscenter") / "state"
    )


class SlotFileError(Exception):
    status = 502


def _read(rel, default):
    f = _state() / "slots" / rel
    try:
        raw = f.read_text(encoding="utf-8")
    except FileNotFoundError:
        return dict(
            default, generated_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    except OSError as e:
        raise SlotFileError(f"{rel}: {e.strerror}") from None
    try:
        d = json.loads(raw)
    except ValueError:
        raise SlotFileError(f"{rel} is not valid JSON") from None
    if not isinstance(d, dict):
        raise SlotFileError(f"{rel} must be a JSON object")
    out = dict(default)
    out.update(d)
    if not out.get("generated_utc"):
        out["generated_utc"] = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    return out


def _listed(d, key="items"):
    if not isinstance(d.get(key), list):
        raise SlotFileError(f"{key} must be a list")
    return d


def sprint(fresh=False, sprint_id=None):
    if sprint_id not in (None, ""):
        raise SlotFileError("closed sprints are not part of the data file form")
    return _listed(_read("tracker/sprint.json", {"sprint": None, "me": "", "items": []}))


def backlog(fresh=False):
    d = _listed(_read("tracker/backlog.json", {"active_sprint": None, "items": []}))
    d.setdefault("count", len(d["items"]))
    return d


def approvals(fresh=False):
    d = _read("tracker/approvals.json", {"pending": [], "inflight": []})
    return _listed(_listed(d, "pending"), "inflight")


def needs_me(fresh=False):
    d = _listed(_read("tracker/needs-me.json", {"live_ok": True, "live_error": "", "items": []}))
    d.setdefault(
        "count",
        sum(
            1
            for i in d["items"]
            if isinstance(i, dict) and i.get("phase", "needs_me") == "needs_me"
        ),
    )
    return d


def board(fresh=False):
    d = _listed(
        _read(
            "people/board.json",
            {"people": [], "sources": {"agenda_items": 0, "calendar_ok": False}},
        ),
        "people",
    )
    return d


def register(r, tracker=False, people=False):
    """The read routes of the slots that are in files mode."""
    if tracker:
        r.add(
            "GET",
            "/api/jira/sprint",
            lambda q: sprint(False, q.arg("id") or None),
            name="data_slots.sprint",
        )
        r.add("GET", "/api/jira/backlog", lambda q: backlog(), name="data_slots.backlog")
        r.add("GET", "/api/jira/approvals", lambda q: approvals(), name="data_slots.approvals")
        r.add("GET", "/api/jira/needs-me", lambda q: needs_me(), name="data_slots.needs_me")
    if people:
        r.add("GET", "/api/one-on-ones", lambda q: board(), name="data_slots.board")
