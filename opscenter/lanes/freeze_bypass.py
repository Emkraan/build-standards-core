#!/usr/bin/env python3
"""
freeze_bypass.py

Purpose: A human, logged, expiring lift of the change-freeze hold for the owner's own pull requests. The own-PR lane
         (own_pr_merge.py) holds every pull request while a freeze window is on (freeze file, `OWNPR_FREEZE_FILE`). From the ops
         center the owner lifts that hold two ways: one pull request, for the current window only (it expires with the window,
         and the entry carries the head it was made for); or all of the owner's pull requests until the next midnight in the
         owner's time zone. Every other gate (checks, findings, policy rules, conflicts, sign-offs) still applies.
         Built on the override store (server/modules/override_store.py), so it is scoped to the window id, the expiry is stored
         with the entry and compared on every read (nothing runs at midnight), and a missing, unreadable, foreign-window or
         expired store means no bypass. This module is the only writer; every change is appended to the store's log; the lane logs
         a bypass once per head (`note_once`).
Date:    2026-11-06

Store:   `OWNPR_FREEZE_BYPASS_FILE` (default `<state>/freeze-bypass.json`), the override store's file; its log sits beside it.
Slots:   the code host read that says whether a pull request is open and the owner's own (`read_pr(key)`), so only the owner's own
         open pull requests qualify; nothing here names an estate or a host.
"""

import datetime as dt
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "server" / "modules"))

import override_store as ov  # noqa: E402
import paths  # noqa: E402

DEFAULT_TZ = "America/New_York"


def _freeze_file():
    return Path(os.environ.get("OWNPR_FREEZE_FILE") or paths.state_dir() / "change-freeze.json")


def _store_file():
    return Path(
        os.environ.get("OWNPR_FREEZE_BYPASS_FILE") or paths.state_dir() / "freeze-bypass.json"
    )


def _load(p):
    try:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _tz(freeze):
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(freeze.get("timezone") or DEFAULT_TZ)
    except Exception:  # noqa: BLE001 - tzdata missing: the same fixed fallback the lane uses
        return dt.timezone(dt.timedelta(hours=-4))


def active_window(freeze_file=None, now=None):
    """The change-freeze window on right now (its stamps are wall times in the file's zone), or None."""
    freeze = _load(freeze_file or _freeze_file())
    local = (now or dt.datetime.now(dt.timezone.utc)).astimezone(_tz(freeze)).replace(tzinfo=None)
    for w in freeze.get("windows") or []:
        try:
            if (
                dt.datetime.fromisoformat(w["start"])
                <= local
                <= dt.datetime.fromisoformat(w["end"])
            ):
                return w
        except (KeyError, TypeError, ValueError):
            continue
    return None


def window_end_utc(window, freeze):
    end = dt.datetime.fromisoformat(window["end"]).replace(tzinfo=_tz(freeze))
    return end.astimezone(dt.timezone.utc)


def make_store(store_file=None, clock=None, read_pr=None, self_login=""):
    """The override store for the freeze bypass. `read_pr(key)` returns {state, author, head} for a pull request key; with it,
    only an open pull request of `self_login` qualifies (the null default qualifies none: nothing can be bypassed one by one
    until the consumer supplies the read)."""

    def qualify(key):
        if read_pr is None:
            raise ov.OverrideRefused(
                "no pull request read is configured, so no single pull request can be bypassed", 409
            )
        pr = read_pr(key) or {}
        if pr.get("state") != "open":
            raise ov.OverrideRefused(f"{key} is no longer open", 409)
        if not self_login or pr.get("author") != self_login:
            raise ov.OverrideRefused(
                f"{key} is not mine; the freeze bypass covers my own pull requests only", 403
            )

    return ov.OverrideStore(store_file or _store_file(), clock=clock, qualify=qualify)


def status(store=None, freeze_file=None, now=None):
    """What the ops center page shows: whether a freeze is on, its window, the all switch and the pull requests bypassed."""
    store = store or make_store()
    w = active_window(freeze_file, now)
    if not w:
        return {"in_freeze": False, "window": None, "all": {"on": False, "until": None}, "prs": []}
    s = store.status(w.get("id"))
    return {
        "in_freeze": True,
        "window": {"id": w.get("id"), "name": w.get("name"), "end": w.get("end")},
        "all": {"on": s["all"], "until": s["until"]},
        "prs": s["keys"],
    }


def set_all(on, who="", store=None, freeze_file=None, now=None):
    """Turn the all-my-pull-requests bypass on (until the next midnight in the file's zone) or off."""
    store = store or make_store()
    w = active_window(freeze_file, now)
    if on:
        if not w:
            raise ov.OverrideRefused("No change freeze is on, so there is nothing to bypass.", 409)
        freeze = _load(freeze_file or _freeze_file())
        until = ov.expires_at_local_midnight(_tz(freeze), now)
        store.set("*", None, until, who=who, window=w["id"])
    else:
        store.clear("*", who=who)
    return status(store, freeze_file, now)


def set_pr(key, on, who="", head=None, store=None, freeze_file=None, now=None):
    """Bypass the freeze for one pull request for the current window, or take the bypass back. The entry expires with the window
    and carries the head it was made for."""
    store = store or make_store()
    w = active_window(freeze_file, now)
    if on:
        if not w:
            raise ov.OverrideRefused("No change freeze is on, so there is nothing to bypass.", 409)
        freeze = _load(freeze_file or _freeze_file())
        store.set(
            key,
            None,
            window_end_utc(w, freeze),
            who=who,
            window=w["id"],
            extra={"head": head} if head else None,
        )
    else:
        store.clear(key, who=who)
    return status(store, freeze_file, now)


def bypass_by(key, window, store=None):
    """The lane's read: 'pr' when this pull request is bypassed in this window, 'all' when the all switch is on, else None.
    Anything unreadable is None (fail closed): the store's status is empty on any error."""
    wid = (window or {}).get("id")
    if not wid:
        return None
    s = (store or make_store()).status(wid)
    if key in s["keys"]:
        return "pr"
    return "all" if s["all"] else None


def note_once(rec, number, head, window, by, log):
    """Log a bypass once per head and source, so every merge inside a freeze has its record. `rec` is the lane's record of the
    pull request (changed in place); `log(dict)` writes the lane's decision log."""
    seen = rec.get("freeze_bypass") or {}
    if seen.get("head") == head and seen.get("by") == by:
        return False
    rec["freeze_bypass"] = {"head": head, "by": by}
    log(
        {
            "lane": "own-pr",
            "pr": number,
            "decision": "freeze_bypassed",
            "sha": head,
            "detail": f"{window.get('id', '')}: bypassed by the owner ({'this PR' if by == 'pr' else 'all own PRs until midnight'})",
        }
    )
    return True
