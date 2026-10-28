"""
Purpose: Live work tracker data for the ops center tracker hub (Sprint, Backlog and Changes tabs). Every read and the few
         guarded writes go through one driver command (params.driver_cmd, a reference driver is beside this file) that
         runs one tracker tool call and prints the JSON-RPC result. Nothing here is bundled: the hub reflects the
         tracker at request time, with a stale while revalidate cache so several tabs and the sidebar badge do not
         hammer the connector.

Writes (all confirmed on read-back, all limited to issues assigned to the owner):
  sprint_move     backlog item -> active sprint (sets the Sprint field)
  sprint_remove   active sprint item -> backlog (clears the Sprint field)
  transition      status change, NEVER to a done-category status. Closing a ticket runs through the owner's
                  closure-comment process, not a button.
Both writes accept what_if=True: every guard read runs, the write is skipped, and the would-be change is returned.

Parameters: tracker/params.py (site, browse URL, driver, project, team clause, field ids, change query).
"""

import datetime as dt
import json
import re
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "server" / "modules"))
import params  # noqa: E402
import swr  # noqa: E402

CLOUD_ID = params.get("site_id", "")
BROWSE = params.get("browse_url", "")
PROJECT = params.get("project", "")
SPRINT_FIELD = params.get("sprint_field", "customfield_10020")
POINTS_FIELD = params.get("points_field", "customfield_10016")
# A JQL clause that scopes a view to the owner's team (params.team_clause), empty for none.
TEAM_CLAUSE = params.get("team_clause", "")
_PROJECT_CLAUSE = f"project = {PROJECT} AND " if PROJECT else ""
_TEAM_AND = f"{TEAM_CLAUSE} AND " if TEAM_CLAUSE else ""

# Open work assigned to the owner that is not in the active sprint. "sprint is EMPTY" keeps never-sprinted items
# (sprint not in openSprints() alone drops them) and "sprint in futureSprints()" keeps items parked in a planned
# sprint, which a plain open sprint query silently loses (open = active + future).
BACKLOG_JQL = (
    "assignee = currentUser() AND statusCategory != Done "
    "AND (sprint is EMPTY OR sprint not in openSprints() OR sprint in futureSprints()) "
    "ORDER BY priority DESC, updated DESC"
)

ISSUE_FIELDS = [
    "summary",
    "status",
    "issuetype",
    "priority",
    "updated",
    "duedate",
    "assignee",
    "parent",
    POINTS_FIELD,
    SPRINT_FIELD,
]

KEY_RE = re.compile(r"^[A-Z][A-Z0-9]{1,15}-\d{1,7}$")
_DOMAIN = params.get("email_domain", "")
EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+-]+@"
    + (re.escape(_DOMAIN.lstrip("@")) if _DOMAIN else r"[A-Za-z0-9.-]+")
    + "$"
)


class TrackerError(Exception):
    """Connector failure or a refused write. code is the HTTP status to return."""

    def __init__(self, msg, code=502):
        super().__init__(msg)
        self.code = code


def call(tool, args, timeout=90):
    """Invoke one tracker tool through the driver command and return the parsed result payload. Raises TrackerError
    on any failure."""
    try:
        r = subprocess.run(
            [*params.driver_cmd(), tool, json.dumps(args)],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise TrackerError(f"{tool} timed out") from exc
    if r.returncode != 0:
        raise TrackerError(f"{tool} driver exit {r.returncode}: {(r.stderr or '')[:300]}")
    try:
        out = json.loads(r.stdout)
    except ValueError as exc:
        raise TrackerError(f"{tool} returned non-JSON: {(r.stdout or '')[:200]}") from exc
    res = out.get("result") if isinstance(out, dict) else None
    if not isinstance(res, dict):
        raise TrackerError(f"{tool} malformed response")
    if res.get("isError"):
        content = res.get("content") or [{}]
        raise TrackerError(f"{tool} tool error: {content[0].get('text', '')[:300]}")
    content = res.get("content") or []
    if content and content[0].get("text"):
        txt = content[0]["text"]
        try:
            return json.loads(txt)
        except ValueError:
            return {"_raw": txt}
    return res


# --------------------------------------------------------------------------
# TTL cache (per process). Writes invalidate the views they change.
# --------------------------------------------------------------------------
_CACHE = {}
_CACHE_LOCK = threading.Lock()


def _cached(name, ttl, fn, fresh=False):
    # Stale-while-revalidate (swr.py): an expired view is served at once and refreshed in the background.
    return swr.cached(f"tracker:{name}", ttl, fn, fresh=fresh)


def invalidate(*names):
    swr.invalidate(*[f"tracker:{n}" for n in names])


def _utc_now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _key(key):
    k = (key or "").strip().upper()
    if not KEY_RE.match(k):
        raise TrackerError("valid issue key required", 400)
    return k


def _search_all(jql, fields, pages=5):
    """Search with nextPageToken paging (maxResults caps at 100 per call)."""
    out, token = [], None
    for _ in range(pages):
        args = {"cloudId": CLOUD_ID, "jql": jql, "fields": fields, "maxResults": 100}
        if token:
            args["nextPageToken"] = token
        r = call("searchJiraIssuesUsingJql", args)
        if not isinstance(r, dict):
            break
        if r.get("error"):
            raise TrackerError(str(r.get("message", "search failed"))[:300])
        out.extend(r.get("issues") or [])
        token = r.get("nextPageToken")
        if r.get("isLast", True) or not token:
            break
    return out


_ME = {}


def me():
    """The owner's Atlassian account id (cached for the life of the process)."""
    if "id" not in _ME:
        u = call("atlassianUserInfo", {})
        acct = u.get("account_id") if isinstance(u, dict) else None
        if not acct:
            raise TrackerError("could not resolve the owner's Atlassian account id")
        _ME["id"] = acct
    return _ME["id"]


def _report_emails():
    """The owner's direct reports' addresses from the people plug-in roster (partners excluded), so a report's sprint
    item without the team field still shows up. No plug-in or a failure means none."""
    try:
        people = params.people()
        return [
            p["email"]
            for p in (people.roster() if people else [])
            if p.get("group", "report") != "partner" and EMAIL_RE.match(p.get("email") or "")
        ]
    except Exception:  # noqa: BLE001
        return []


def _sprint_obj(s):
    return {
        "id": s.get("id"),
        "name": s.get("name"),
        "board_id": s.get("boardId"),
        "start": s.get("startDate") or "",
        "end": s.get("endDate") or "",
        "goal": s.get("goal") or "",
    }


def active_sprint(fresh=False):
    """The active sprint of the project, read through the Sprint field of issues in it (the connector exposes no
    agile or board API). futureSprints() is excluded so a planned-only issue cannot hide the active one, and the
    team's issues are preferred so another board's sprint never wins."""

    def load():
        base = "sprint in openSprints() AND sprint not in futureSprints() ORDER BY updated DESC"
        tally = {}
        for jql in dict.fromkeys(
            (f"{_PROJECT_CLAUSE}{_TEAM_AND}{base}", f"{_PROJECT_CLAUSE}{base}")
        ):
            r = call(
                "searchJiraIssuesUsingJql",
                {"cloudId": CLOUD_ID, "jql": jql, "fields": [SPRINT_FIELD], "maxResults": 5},
            )
            for i in r.get("issues", []) if isinstance(r, dict) else []:
                for s in i.get("fields", {}).get(SPRINT_FIELD) or []:
                    if isinstance(s, dict) and s.get("state") == "active":
                        n, _ = tally.get(s.get("id"), (0, s))
                        tally[s.get("id")] = (n + 1, s)
            if tally:
                break
        if not tally:
            return None
        return _sprint_obj(max(tally.values(), key=lambda t: t[0])[1])

    return _cached("active_sprint", 300, load, fresh)


def _row(i, my_id=None):
    f = i.get("fields") or {}
    st = f.get("status") or {}
    asg = f.get("assignee") or {}
    parent = f.get("parent") or {}
    sprints = [s for s in (f.get(SPRINT_FIELD) or []) if isinstance(s, dict)]
    planned = next((s for s in sprints if s.get("state") == "future"), None)
    pts = f.get(POINTS_FIELD)
    key = i.get("key") or ""
    return {
        "key": key,
        "summary": f.get("summary", ""),
        "status": st.get("name", ""),
        "status_category": (st.get("statusCategory") or {}).get("key", ""),
        "issuetype": (f.get("issuetype") or {}).get("name", ""),
        "priority": (f.get("priority") or {}).get("name", ""),
        "points": pts if isinstance(pts, (int, float)) else None,
        "assignee": asg.get("displayName") or "Unassigned",
        "assignee_id": asg.get("accountId") or "",
        "mine": bool(my_id) and asg.get("accountId") == my_id,
        "parent_key": parent.get("key") or "",
        "parent_summary": (parent.get("fields") or {}).get("summary") or "",
        "updated": f.get("updated", ""),
        "due": f.get("duedate") or "",
        "carry": sum(1 for s in sprints if s.get("state") == "closed"),
        "planned_sprint": {"id": planned.get("id"), "name": planned.get("name")}
        if planned
        else None,
        "url": BROWSE + key,
    }


def sprint(fresh=False):
    """Active sprint plus every item in it that belongs to the team, a direct report, or the owner. Each row
    carries mine=True|False and the UI filters."""

    def load():
        sp = active_sprint(fresh)
        my_id = me()
        if not sp or not sp.get("id"):
            return {"generated_utc": _utc_now(), "sprint": None, "me": my_id, "items": []}
        who = ([TEAM_CLAUSE] if TEAM_CLAUSE else []) + ["assignee = currentUser()"]
        emails = _report_emails()
        if emails:
            who.append("assignee in (" + ", ".join(f'"{e}"' for e in emails) + ")")
        jql = f"sprint = {int(sp['id'])} AND ({' OR '.join(who)}) ORDER BY rank ASC"
        issues = _search_all(jql, ISSUE_FIELDS)
        return {
            "generated_utc": _utc_now(),
            "sprint": sp,
            "me": my_id,
            "items": [_row(i, my_id) for i in issues],
        }

    return _cached("sprint", 60, load, fresh)


def backlog(fresh=False):
    """The owner's open work not in the active sprint. Items parked in a future sprint
    carry planned_sprint so the UI can group them."""

    def load():
        sp = active_sprint(fresh)
        issues = _search_all(BACKLOG_JQL, ISSUE_FIELDS)
        items = [_row(i) for i in issues]
        for it in items:
            it.pop("mine", None)
        return {
            "generated_utc": _utc_now(),
            "active_sprint": sp,
            "count": len(items),
            "items": items,
        }

    return _cached("backlog", 60, load, fresh)


def my_open_item(key):
    """Row for one of the owner's open issues, from the live sprint or backlog view (the
    same rows the tracker hub shows). Used by Tackle so the prompt is built from
    the tracker, never from client text. Raises KeyError when the issue is not mine,
    not open, or not in either view."""
    key = _key(key)
    for fresh in (False, True):
        for it in sprint(fresh).get("items") or []:
            if it.get("key") == key and it.get("mine") and it.get("status_category") != "done":
                return dict(it, view="sprint")
        for it in backlog(fresh).get("items") or []:
            if it.get("key") == key:
                return dict(it, view="backlog")
    raise KeyError(f"{key} is not an open item of the owner in the sprint or backlog")


def _issue(key, fields):
    rb = call("getJiraIssue", {"cloudId": CLOUD_ID, "issueIdOrKey": key, "fields": fields})
    return (rb.get("fields") if isinstance(rb, dict) else None) or {}


def _assert_mine(key, fields):
    f = _issue(key, ["assignee"] + fields)
    if (f.get("assignee") or {}).get("accountId") != me():
        raise TrackerError(
            f"{key} is not assigned to the owner. Only the owner's own items change from here", 403
        )
    return f


def sprint_move(key):
    """Backlog item -> active sprint. Idempotent on the tracker side."""
    key = _key(key)
    sp = active_sprint()
    if not sp or not sp.get("id"):
        raise TrackerError("no active sprint in the project", 409)
    call(
        "editJiraIssue",
        {"cloudId": CLOUD_ID, "issueIdOrKey": key, "fields": {SPRINT_FIELD: sp["id"]}},
    )
    sprints = _issue(key, [SPRINT_FIELD]).get(SPRINT_FIELD) or []
    if not any(isinstance(s, dict) and s.get("id") == sp["id"] for s in sprints):
        raise TrackerError(f"{key} edit accepted but sprint not confirmed on read-back")
    invalidate("sprint", "backlog")
    return {"key": key, "moved_to": {"id": sp["id"], "name": sp["name"]}}


def sprint_remove(key, what_if=False):
    """Active sprint item -> backlog (Sprint field cleared). Mine only."""
    key = _key(key)
    sp = active_sprint()
    if not sp or not sp.get("id"):
        raise TrackerError("no active sprint in the project", 409)
    f = _assert_mine(key, [SPRINT_FIELD, "status"])
    if not any(isinstance(s, dict) and s.get("id") == sp["id"] for s in f.get(SPRINT_FIELD) or []):
        raise TrackerError(f"{key} is not in {sp['name']}", 409)
    if ((f.get("status") or {}).get("statusCategory") or {}).get("key") == "done":
        raise TrackerError(f"{key} is already closed and stays in the sprint record", 409)
    out = {"key": key, "removed_from": {"id": sp["id"], "name": sp["name"]}}
    if what_if:
        return {**out, "what_if": True}
    call(
        "editJiraIssue", {"cloudId": CLOUD_ID, "issueIdOrKey": key, "fields": {SPRINT_FIELD: None}}
    )
    after = _issue(key, [SPRINT_FIELD]).get(SPRINT_FIELD) or []
    if any(isinstance(s, dict) and s.get("state") in ("active", "future") for s in after):
        raise TrackerError(f"{key} edit accepted but removal not confirmed on read-back")
    invalidate("sprint", "backlog")
    return out


def transitions(key):
    """Transitions available from the issue's current status. allowed=False
    for done-category targets (closing has its own process) and for any
    transition with a screen (needs fields this surface does not collect)."""
    key = _key(key)
    r = call("getTransitionsForJiraIssue", {"cloudId": CLOUD_ID, "issueIdOrKey": key})
    out = []
    for t in r.get("transitions", []) if isinstance(r, dict) else []:
        to = t.get("to") or {}
        cat = (to.get("statusCategory") or {}).get("key", "")
        out.append(
            {
                "id": str(t.get("id")),
                "name": t.get("name") or "",
                "to": to.get("name") or "",
                "to_category": cat,
                "allowed": cat != "done" and not t.get("hasScreen"),
            }
        )
    return {"key": key, "transitions": out}


def transition(key, tid, what_if=False):
    """Move one of the owner's issues to a non-done status, confirmed on read-back."""
    key = _key(key)
    tid = str(tid or "").strip()
    if not tid.isdigit():
        raise TrackerError("transition id required", 400)
    f = _assert_mine(key, ["status"])
    t = next((x for x in transitions(key)["transitions"] if x["id"] == tid), None)
    if not t:
        raise TrackerError(f"that transition is not available from {key}'s current status", 409)
    if not t["allowed"]:
        raise TrackerError(
            "closing transitions run through the owner's closure process, not from here", 403
        )
    out = {
        "key": key,
        "from": (f.get("status") or {}).get("name", ""),
        "transition": t["name"],
        "to": t["to"],
    }
    if what_if:
        return {**out, "what_if": True}
    call(
        "transitionJiraIssue", {"cloudId": CLOUD_ID, "issueIdOrKey": key, "transition": {"id": tid}}
    )
    st = _issue(key, ["status"]).get("status") or {}
    if st.get("name") != t["to"]:
        raise TrackerError(
            f"{key} transition accepted but status reads {st.get('name')!r} on read-back"
        )
    invalidate("sprint", "backlog")
    return {
        **out,
        "status": st.get("name"),
        "status_category": (st.get("statusCategory") or {}).get("key", ""),
    }


# --------------------------------------------------------------------------
# Changes pending the owner's approval (read only)
# --------------------------------------------------------------------------
# The connector exposes no service desk approvals API, so "pending the owner" is a query the consumer writes
# (params.change_jql, for example an Approvers field containing the owner) plus the statuses that mean pending and
# in flight. Approve and Decline happen in the tracker. Without a change_jql the data is empty.
CHANGE_BASE_JQL = params.get("change_jql", "")
APPROVAL_PENDING_STATUSES = tuple(params.get("change_pending_statuses", []))
APPROVAL_INFLIGHT_STATUSES = tuple(params.get("change_inflight_statuses", []))
_CF = params.get("change_fields", {}) if isinstance(params.get("change_fields", {}), dict) else {}
# field ids for planned start and end, change type, risk and the portal link object
F_START, F_END = _CF.get("planned_start"), _CF.get("planned_end")
F_TYPE, F_RISK, F_LINKS = _CF.get("change_type"), _CF.get("risk"), _CF.get("links")
CHANGE_FIELDS = [
    "summary",
    "status",
    "reporter",
    "created",
    "updated",
    *[f for f in (F_START, F_END, F_TYPE, F_RISK, F_LINKS) if f],
]


def _opt(v):
    if isinstance(v, dict):
        return v.get("value") or v.get("name") or ""
    return v or ""


def _change_rows(statuses):
    if not CHANGE_BASE_JQL or not statuses:
        return []
    quoted = ", ".join(f'"{s}"' for s in statuses)
    order = f"ORDER BY {F_START} ASC, created ASC" if F_START else "ORDER BY created ASC"
    r = call(
        "searchJiraIssuesUsingJql",
        {
            "cloudId": CLOUD_ID,
            "jql": f"{CHANGE_BASE_JQL} AND status in ({quoted}) {order}",
            "fields": CHANGE_FIELDS,
            "maxResults": 100,
        },
    )
    if isinstance(r, dict) and r.get("error"):
        raise TrackerError(str(r.get("message", "search failed"))[:300])
    out = []
    portal = params.get("portal_url_template", "")
    for i in r.get("issues", []) if isinstance(r, dict) else []:
        f = i.get("fields", {})
        key = i.get("key")
        links = ((f.get(F_LINKS) or {}) if F_LINKS else {}).get("_links") or {}
        out.append(
            {
                "key": key,
                "summary": f.get("summary", ""),
                "status": (f.get("status") or {}).get("name", ""),
                "requester": (f.get("reporter") or {}).get("displayName", ""),
                "change_type": _opt(f.get(F_TYPE)) if F_TYPE else "",
                "risk": _opt(f.get(F_RISK)) if F_RISK else "",
                "planned_start": (f.get(F_START) or "") if F_START else "",
                "planned_end": (f.get(F_END) or "") if F_END else "",
                "created": f.get("created", ""),
                "url": BROWSE + str(key),
                "portal_url": links.get("web") or (portal.format(key=key) if portal else ""),
            }
        )
    return out


def approvals(fresh=False):
    return _cached(
        "approvals",
        60,
        lambda: {
            "generated_utc": _utc_now(),
            "pending": _change_rows(APPROVAL_PENDING_STATUSES),
            "inflight": _change_rows(APPROVAL_INFLIGHT_STATUSES),
        },
        fresh,
    )
