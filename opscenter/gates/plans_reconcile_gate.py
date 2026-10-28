"""
plans_reconcile_gate.py

Purpose: Wake gate for the Plans tracker reconcile job. Reads the ops center Plans API and wakes the
         agent only when an active tracker is a skeleton from the Untracked work strip, or the freshness
         check shows it Behind (pull requests or ticket status moved after the tracker was written).
         Quiet ticks cost no model run.

Wake rules:
  - a candidate tracker (skeleton or Behind) whose fingerprint (slug plus its event refs) was not handed
    to the agent before -> wake, at most once per 30 min
  - the same fingerprint was handed over 2 h ago and the tracker is still a candidate -> wake again
    once (the last run failed or skipped it), then leave it
  - any freshness state still loading -> silent, the next tick has the answer
  - freshness or API read failed -> silent with backoff, wake on the 3rd failure so a broken check never
    freezes the trackers quietly

Read only against the state tree except the trackers it archives or adds a ticket to, and its own state
file under the gate state dir. Always exits 0, signals only through stdout.

Config:  OPSCENTER_PORT (default 8766), OPSCENTER_STATE_DIR (default ~/.opscenter/state),
         PLANS_TRACKER_DRIVER (command that runs one work tracker call, see _jql), TRACKER_SITE (the
         tracker site id passed to it), PLANS_INTAKE_TYPE (the issue type of an intake ticket, default
         Discovery).
Test hooks: GATE_PLANS_JSON (read this file instead of the API), GATE_STATE (state path), GATE_NOW (epoch
seconds).
"""

import hashlib
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gatelib import STATE_DIR, clear_failures, failure_should_wake, gate_silent, wake  # noqa: E402

NAME = "plans-reconcile"
PORT = os.environ.get("OPSCENTER_PORT") or "8766"
API = f"http://127.0.0.1:{PORT}/api/plans"
PLANS_DIR = os.path.join(
    os.environ.get("OPSCENTER_STATE_DIR") or os.path.expanduser("~/.opscenter/state"), "plans"
)
STATE = os.environ.get("GATE_STATE") or os.path.join(STATE_DIR, "plans-reconcile-state.json")
DRIVER = os.environ.get("PLANS_TRACKER_DRIVER") or ""
SITE = os.environ.get("TRACKER_SITE") or ""
INTAKE_TYPE = os.environ.get("PLANS_INTAKE_TYPE") or "Discovery"
SKELETON_PREFIX = "Created from untracked work"
MIN_GAP_S = 30 * 60
RETRY_AFTER_S = 2 * 3600
MAX_HANDOFFS = 2


def _now():
    return float(os.environ.get("GATE_NOW") or time.time())


def _load_plans():
    path = os.environ.get("GATE_PLANS_JSON")
    if path:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    req = urllib.request.Request(API, headers={"Host": f"127.0.0.1:{PORT}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _load_state():
    try:
        with open(STATE, encoding="utf-8") as fh:
            v = json.load(fh)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)
    os.replace(tmp, STATE)


def candidates(data):
    """Active live trackers that need a reconcile, plus whether any check is still loading."""
    out, loading, errors = [], False, []
    for p in data.get("projects") or []:
        t = p.get("tracker") or {}
        if p.get("archived") or p.get("status") != "active" or not t:
            continue
        fresh = p.get("freshness") or {}
        if fresh.get("state") == "loading":
            loading = True
        if fresh.get("state") == "error":
            errors.extend(fresh.get("errors") or ["freshness check failed"])
        skeleton = str(t.get("summary") or "").startswith(SKELETON_PREFIX)
        events = (fresh.get("events") or []) if fresh.get("state") == "ok" else []
        if not skeleton and not (fresh.get("state") == "ok" and fresh.get("behind")):
            continue
        refs = sorted(str(e.get("ref") or "") for e in events)
        fp = hashlib.sha256(json.dumps([p["slug"], skeleton, refs]).encode()).hexdigest()[:16]
        out.append(
            {
                "slug": p["slug"],
                "title": p.get("title") or p["slug"],
                "path": "{}/projects/{}/tracker.md".format(PLANS_DIR, p["slug"]),
                "tickets": t.get("tickets") or [],
                "skeleton": skeleton,
                "events": events,
                "fp": fp,
            }
        )
    return out, loading, errors


def due(cands, state, now):
    """Candidates to hand to the agent this tick."""
    seen = state.get("handed") or {}
    pick = []
    for c in cands:
        rec = seen.get(c["slug"]) or {}
        if (
            rec.get("fp") != c["fp"]
            or rec.get("count", 0) < MAX_HANDOFFS
            and now - rec.get("at", 0) > RETRY_AFTER_S
        ):
            pick.append(c)
    return pick


def _jql(jql):
    """Run one tracker search through the driver command (PLANS_TRACKER_DRIVER, a script that takes the
    tool name and a JSON argument and prints the connector's JSON). Returns issues, or None on any
    failure or when no driver is configured."""
    import subprocess

    if not DRIVER:
        return None

    args = json.dumps(
        {
            "cloudId": SITE,
            "jql": jql,
            "fields": ["summary", "status", "issuetype", "created"],
            "maxResults": 20,
        }
    )
    try:
        out = subprocess.run(
            [sys.executable, DRIVER, "searchJiraIssuesUsingJql", args],
            capture_output=True,
            text=True,
            timeout=90,
        ).stdout
        return json.loads(json.loads(out)["result"]["content"][0]["text"]).get("issues") or []
    except (OSError, ValueError, KeyError, IndexError, TypeError, subprocess.SubprocessError):
        return None


def adopt_work_tickets(data, now):
    """Any tracker carrying an intake ticket (work started before the triager triaged it) watches for the
    work ticket the triager creates off it: a non-intake issue linked to the intake and created on or
    after the intake's day. The key is added to the tracker, so its normal close archives the tracker.
    The ticket close itself is the nightly sprint close-out, which already counts work done under a
    linked intake key as evidence."""
    if os.environ.get("GATE_PLANS_JSON"):
        return []
    added = []
    for p in data.get("projects") or []:
        t = p.get("tracker") or {}
        if p.get("archived") or not t.get("tickets"):
            continue
        have = {k.upper() for k in t["tickets"]}
        own = [
            i
            for i in _jql("key in ({})".format(", ".join(sorted(have)))) or []
            if i["fields"]["issuetype"]["name"] == INTAKE_TYPE
        ]
        if not own:
            continue
        since = min((i["fields"].get("created") or "")[:10] for i in own)
        if not since:
            continue
        links = " OR ".join("issue in linkedIssues({})".format(i["key"]) for i in own)
        issues = _jql(f'({links}) AND issuetype != "{INTAKE_TYPE}" AND created >= "{since}"')
        new = sorted({i["key"] for i in issues or []} - have)
        if not new:
            continue
        path = "{}/projects/{}/tracker.md".format(PLANS_DIR, p["slug"])
        try:
            with open(path, encoding="utf-8") as fh:
                lines = fh.read().split("\n")
        except OSError:
            continue
        for i, ln in enumerate(lines):
            if ln.startswith("tickets:"):
                lines[i] = ln.rstrip() + ", " + ", ".join(new)
                break
        else:
            continue
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        body = "\n".join(lines)
        note = "- {}: person's work ticket {} found linked to the intake, added here so its close archives this tracker.".format(
            day,
            ", ".join(new),
        )
        body = (
            body.replace("## Log\n", "## Log\n" + note + "\n", 1)
            if "## Log\n" in body
            else body + "\n" + note + "\n"
        )
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, path)
        added.append((p["slug"], new))
    return added


def _issue_types(keys):
    """Map ticket key -> issuetype name. Empty dict on a failed read (callers then do nothing)."""
    issues = _jql("key in ({})".format(", ".join(sorted(keys)))) if keys else []
    return {i["key"]: i["fields"]["issuetype"]["name"] for i in issues or []}


def archivable(data, types=None):
    """Done trackers with every step ticked and every WORK ticket closed.
    Intake tickets are ignored (they stay open by design), a tracker with no work ticket
    never archives. A closed sibling or parent listed for context does not count on its own."""
    out = []
    for p in data.get("projects") or []:
        t = p.get("tracker") or {}
        if p.get("archived") or p.get("status") != "done" or not t:
            continue
        prog = t.get("progress") or {}
        if prog.get("done", 0) < prog.get("total", 0):
            continue
        ts = t.get("ticket_status") or {}
        kinds = types if types is not None else _issue_types(set(ts))
        if not kinds:
            continue
        work = [k for k in ts if kinds.get(k) and kinds[k] != INTAKE_TYPE]
        if work and all((ts[k] or {}).get("done") for k in work):
            out.append(p)
    return out


def auto_archive(data, state, now):
    """Archive every archivable project through the Plans API. Returns the slugs archived."""
    if os.environ.get("GATE_PLANS_JSON"):
        return []  # fixture run, never write
    done = []
    for p in archivable(data):
        body = json.dumps(
            {"path": "projects/{}".format(p["slug"]), "version": p.get("version")}
        ).encode()
        req = urllib.request.Request(
            API + "/archive",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{PORT}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30):
                done.append(p["slug"])
        except (OSError, ValueError):
            continue  # version moved or server busy, next tick retries
    if done:
        log = state.setdefault("archived", [])
        log.extend({"slug": s, "at": now} for s in done)
        state["archived"] = log[-50:]
    return done


def main():
    now = _now()
    try:
        data = _load_plans()
    except (OSError, ValueError) as exc:
        detail = f"plans API read failed: {exc}"
        if failure_should_wake(NAME, detail):
            wake(
                f"[PLANS-RECONCILE GATE ALERT] {detail}",
                "Check the Ops Center server (ai.ops-center.opscenter).",
            )
        gate_silent()
    state0 = _load_state()
    adopted = adopt_work_tickets(data, now)
    if adopted:
        log = state0.setdefault("adopted", [])
        log.extend({"slug": s, "keys": k, "at": now} for s, k in adopted)
        state0["adopted"] = log[-50:]
    archived = auto_archive(data, state0, now)
    if adopted or archived:
        _save_state(state0)
        data = _load_plans()
    cands, loading, errors = candidates(data)
    if errors and not cands:
        detail = "freshness check failed: {}".format("; ".join(sorted(set(errors)))[:300])
        if failure_should_wake(NAME, detail):
            wake(
                f"[PLANS-RECONCILE GATE ALERT] {detail}",
                "The Plans freshness check reads GitHub through gh.",
            )
        gate_silent()
    clear_failures(NAME)
    if loading:
        gate_silent()
    state = _load_state()
    live = {c["slug"] for c in cands}
    handed = {k: v for k, v in (state.get("handed") or {}).items() if k in live}
    state["handed"] = handed
    pick = due(cands, state, now)
    if not pick or now - state.get("last_wake", 0) < MIN_GAP_S:
        _save_state(state)
        gate_silent()
    for c in pick:
        rec = handed.get(c["slug"]) or {}
        count = rec.get("count", 0) + 1 if rec.get("fp") == c["fp"] else 1
        handed[c["slug"]] = {"fp": c["fp"], "at": now, "count": count}
    state["last_wake"] = now
    _save_state(state)
    lines = ["[PLANS-RECONCILE] %d tracker(s) need a reconcile against live." % len(pick)]  # noqa: UP031
    for c in pick:
        why = "skeleton from the Untracked work strip" if c["skeleton"] else "Behind"
        lines.append("")
        lines.append("TRACKER {} ({})".format(c["slug"], why))
        lines.append("  file: {}".format(c["path"]))
        lines.append("  title: {}".format(c["title"]))
        lines.append("  tickets: {}".format(", ".join(c["tickets"])))
        for e in c["events"][:12]:
            lines.append(
                "  since: {} {} {} | {}".format(
                    e.get("day", ""), e.get("ref", ""), e.get("url", ""), e.get("title", "")
                )
            )
    wake(*lines)


if __name__ == "__main__":
    main()
