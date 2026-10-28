"""own_lane.py - read the own-PR auto-merge lane of every review lane for the Reviews hub.

The lane merges the owner's own pull requests once green, holds policy rules for the owner's sign-off,
and starts an auto-fix session at once for fixable problems. This module only reads its state file.

Each lane's state file is <OPSCENTER_LANE_STATE_DIR>/<lane>/own-pr-merge.json (default
~/.opscenter/lanes); `register(lane, path)` points one lane somewhere else, for example a lane whose
fix records sit in a differently named file.
"""

import datetime as dt
import json
import os
from pathlib import Path

STATE = {}


def _base():
    return Path(
        os.environ.get("OPSCENTER_LANE_STATE_DIR", str(Path.home() / ".opscenter" / "lanes"))
    )


def register(lane, path):
    """Point one lane at its state file."""
    STATE[lane] = Path(path)


def _state_path(lane):
    return STATE.get(lane) or _base() / lane / "own-pr-merge.json"


FRESH_S = (
    900  # a lane passes every few minutes, so 15 minutes without a pass means it is not running
)
_PROBLEM = {
    "red-checks": "red checks",
    "untriaged-highs": "untriaged high findings",
    "blocking-findings": "blocking findings",
    "merge-conflict": "the merge conflict",
    "review-threads": "open review threads",
    "rebase-on-main": "the rebase on main",
    "directed-fix": "the fix the owner chose",
}


def _epoch(s):
    try:
        return (
            dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
            .replace(tzinfo=dt.timezone.utc)
            .timestamp()
        )
    except (TypeError, ValueError):
        return 0.0


def _hhmm(s):
    """'4:05 pm' style local time (the host's zone) for a lane timestamp."""
    e = _epoch(s)
    if not e:
        return ""
    local = dt.datetime.fromtimestamp(e)
    return local.strftime("%-I:%M %p").lower()


def load(target):
    try:
        return json.loads(_state_path(target).read_text())
    except (OSError, ValueError):
        return {}


def fresh(st, now=None):
    now = now if now is not None else dt.datetime.now(dt.timezone.utc).timestamp()
    return (
        bool(st)
        and now - _epoch(st.get("updated")) < FRESH_S
        and not int(st.get("error_count") or 0)
    )


def lane(st, n, head):
    """{status, reason} the lane recorded for this head, else None."""
    rec = (st.get("prs") or {}).get(str(n)) or {}
    if rec.get("head") != head or not rec.get("status"):
        return None
    return {"status": rec["status"], "reason": rec.get("reason", "")}


def _side(target, name):
    """A file the ops center writes next to the lane state (decision cards)."""
    try:
        return json.loads((_state_path(target).parent / name).read_text())
    except (OSError, ValueError):
        return {}


def choice(target, n, head):
    """The owner's decision-card choice for this head that the lane has not acted on yet, else None.
    fix -> own-pr-directions.json (the fixer starts it), override -> own-pr-signoffs.json."""
    for name, kind in (("own-pr-directions.json", "fix"), ("own-pr-signoffs.json", "override")):
        rec = (_side(target, name).get("prs") or {}).get(str(n)) or {}
        if rec.get("head") == head and rec.get("at"):
            return dict(rec, kind=kind)
    return None


NEVER_SIGNOFF = {"plan-destroy", "plan-replace"}  # mirrors decision_cards.NEVER_SIGNOFF


def held_rules(reason):
    """The rules of a lane 'needs me: a, b, c' reason, in order, else []."""
    if not (reason or "").startswith("needs me: "):
        return []
    return [r.strip() for r in reason[len("needs me: ") :].split(",") if r.strip()]


def uncovered_rules(reason, ch):
    """The rules of the lane's CURRENT 'needs me' reason that the owner's recorded decision-card sign-off does not
    cover, in lane order. NEVER_SIGNOFF rules are never covered (they go through Approve and merge). A
    sign-off covers a rule only when it names it, so a partial one (3 held, 1 signed) leaves the rest
    on the owner's plate instead of reading as a wait on the lane."""
    done = set((ch or {}).get("rules") or [])
    return [r for r in held_rules(reason) if r in NEVER_SIGNOFF or r not in done]


def autofix(st, n, head, target="default"):
    """What the auto-fix is doing for this PR, else None.
    state running  = a fix session is working it (any head: it may have pushed already)
          deferred = another live session is already on the PR, so the fix waits for it
          gave_up  = the fix could not clear this head and it needs the owner's direction"""
    f = (st.get("fix") or {}).get(str(n)) or {}
    run = f.get("running")
    if run:
        what = _PROBLEM.get(run.get("problem"), run.get("problem") or "it")
        return {
            "state": "running",
            "since": run.get("started"),
            "text": f"An auto-fix session is working on {what} (started {_hhmm(run.get('started'))}). "
            "The lane merges it once it clears.",
        }
    d = f.get("deferred")
    if d and d.get("head") == head:
        return {
            "state": "deferred",
            "since": d.get("since"),
            "text": f'The session "{d.get("session")}" is already on it. Auto-fix starts if it is still held '
            "once that session goes quiet.",
        }
    g = f.get("gave_up")
    if g and g.get("head") == head:
        w = g.get("waits_on") or []
        if w:
            # the lane rebases it on its own once every one of these merges.
            tags = [f"#{x}" for x in w]
            names = tags[0] if len(tags) == 1 else ", ".join(tags[:-1]) + " and " + tags[-1]
            return {
                "state": "waiting_on",
                "since": g.get("at"),
                "waits_on": w,
                "text": f"Auto-fix waits on {names} to merge, then rebases this PR on main by itself.",
            }
        ch = choice(target, n, head)
        if ch and ch["kind"] == "fix" and ch.get("at", "") >= (g.get("at") or ""):
            return {
                "state": "running",
                "since": ch.get("at"),
                "text": f'The owner chose "{ch.get("label")}". A fix session starts on the next lane pass.',
            }
        out = {
            "state": "gave_up",
            "since": g.get("at"),
            "text": f"Auto-fix gave up: {g.get('why')}",
        }
        if g.get("decision"):
            out["decision"] = g["decision"]
        return out
    r = f.get("rearm")
    if r and r.get("head") == head:
        return {
            "state": "running",
            "since": r.get("at"),
            "text": "The PRs it waited on merged. Auto-fix rebases it on main on the next lane pass.",
        }
    return None


def autofix_or_session(st, n, head, target="default", branch=None, sessions=None):
    """autofix(), and when the lane has nothing on the PR, a live session working it (a delegated
    fix, a Discuss session, any session pushing or editing in the branch worktree) as state
    'deferred'. The card then says "session on it" and locks its buttons instead of looking idle.
    `sessions` is the runtime slot's session reader: sessions.working(lane, pr, branch) returns
    {label, text} or None; without one the lane's own record is all there is."""
    af = autofix(st, n, head, target)
    if af and af.get("state") != "gave_up":
        return af
    # A gave-up record for this head is stale the moment a session picks the PR back up (a directed
    # fix after the owner's decision, a Discuss session). The live session wins so the card reads in
    # progress and locks its buttons instead of asking for a direction already given.
    if sessions is None:
        return af
    try:
        w = sessions.working(target, n, branch)
    except Exception:  # noqa: BLE001 - detection is advisory, never break the card
        return af
    if not w:
        return af
    return {"state": "deferred", "session": w["label"], "text": w["text"]}
