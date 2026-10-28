#!/usr/bin/env python3
"""
alerts.py

Purpose: Ops Center Alerts (Action Center > Alerts tab). The scheduled jobs that used to ping
         Their messages now deliver locally. This module reads their saved run outputs and
         lists every run that said something or failed, so the owner can read and acknowledge it in one
         place. A report clears itself 48 hours after the run. A job whose latest run failed
         stays listed and raises one Action Center item (automation_actions, key
         auto-alert-<job>-<streak start>), which closes itself when a later run succeeds.
         Failures are watched for EVERY enabled job in jobs.json by default, so a new
         job is covered the day it is added. state/dashboard/alert-sources.json "jobs" lists the
         jobs whose ordinary reports also show, and "ignore_failures" opts a job out of failure
         watching (empty by default, every opt-out needs a reason in the file's comment).
         Only failures need an acknowledgement and count in the badge, a report (kind report)
         is information with needs_ack false.
Date:    2026-10-16 (failures watched by default 2026-10-17, reports out of the badge 2026-10-21)
Usage:   imported by server.py (GET /api/alerts, POST /api/alerts/ack).
         alerts.py sync   raise or close the failure items (run by the data refresh)
         alerts.py list   print the current alert list as JSON
Exit:    0 on success, 1 when sync failed.
Test hooks: ALERTS_CRON_HOME (folder holding jobs.json and output/), ALERTS_DASH (state/dashboard).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import tempfile
import threading
from pathlib import Path

import paths

CRON = Path(os.environ.get("ALERTS_CRON_HOME") or paths.agent_home() / "cron")
DASH = Path(os.environ.get("ALERTS_DASH") or paths.dashboard_dir())
SOURCES = DASH / "alert-sources.json"
ACK = DASH / "alerts-ack.json"

WINDOW_H = 48  # a report clears itself this long after its run
ACK_KEEP_DAYS = 7
BODY_MAX = 6000
ITEM_PREFIX = "alert-"  # automation_actions id prefix (shown as auto-alert-...)
OPS_URL = "http://127.0.0.1:9121/#/action/alerts"

STAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})\.md$")
STATUS_RE = re.compile(r"(?m)^\*\*Status:\*\* (.+)$")
PROMPT_FRAME_RE = re.compile(r"(?m)^\*\*Prompt Characters:\*\* (\d+)\n## Prompt\n\n")
RESPONSE_FRAME_RE = re.compile(r"\*\*Response Characters:\*\* \d+\n## Response\n\n")
SILENT_TOKENS = {"[SILENT]", "SILENT", "NO_REPLY", "NO REPLY"}
FAILURE_MARKER = "[CRON_FAILURE]"

_lock = threading.Lock()
_parse_cache: dict[str, tuple[float, str, str, str]] = {}


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
        f.write("\n")
    os.replace(tmp, path)


def _ids(values):
    return [j for j in values or [] if re.fullmatch(r"[0-9a-f]{12}", str(j))]


def sources():
    """Jobs whose reports show (not only failures), in config order."""
    return _ids(_load_json(SOURCES, {}).get("jobs"))


def _jobs():
    data = _load_json(CRON / "jobs.json", {})
    jobs = data.get("jobs", data) if isinstance(data, dict) else data
    return [j for j in jobs or [] if isinstance(j, dict) and j.get("id")]


def job_names():
    return {j.get("id"): j.get("name") or j.get("id") for j in _jobs()}


def watched():
    """Every job checked for failures: report sources first, then every other enabled job,
    minus the ignore_failures opt-outs."""
    ignore = set(_ids(_load_json(SOURCES, {}).get("ignore_failures")))
    out = [j for j in sources() if j not in ignore]
    for j in _jobs():
        jid = j["id"]
        if j.get("enabled", True) and jid not in ignore and jid not in out:
            out.append(jid)
    return out


def _is_silent(answer):
    text = (answer or "").strip()
    if not text or text == "(No response generated)":
        return True
    lines = [ln.strip().upper() for ln in text.splitlines() if ln.strip()]
    return lines[0] in SILENT_TOKENS or lines[-1] in SILENT_TOKENS


def parse_run(text):
    """Classify one saved run: ("silent" | "report" | "failure", body).

    Shapes written by the Hermes scheduler: script runs (no_agent or monitor) carry a Status
    line (silent, no_change, script failed) or the output after the header rule. Agent runs
    carry a length-framed prompt then the response or an Error block. Older agent runs are
    unframed, so the LAST Response or Error heading is the writer's boundary (the prompt can
    quote either heading)."""
    head = text.split("\n## Prompt", 1)[0]
    m = STATUS_RE.search(head)
    status = m.group(1).strip().lower() if m else ""
    if status.startswith("silent") or status.startswith("no_change"):
        return "silent", ""
    if m and status.startswith("script failed"):
        return "failure", text[m.end() :].strip()
    if "\n## Prompt" not in text:
        # Script output: everything after the header rule.
        _, sep, body = text.partition("\n---\n")
        body = body.strip() if sep else ""
        return ("report", body) if body else ("silent", "")
    frame = PROMPT_FRAME_RE.search(text)
    if frame:
        rest = text[frame.end() + int(frame.group(1)) :].lstrip("\n")
        r = RESPONSE_FRAME_RE.match(rest)
        if r:
            answer = rest[r.end() :].strip()
        elif "## Error" in rest:
            return "failure", rest.split("## Error", 1)[1].strip()
        else:
            return "failure", "The run saved no response."
    else:
        resp, err = text.rfind("## Response"), text.rfind("## Error")
        if err > resp:
            return "failure", text[err + len("## Error") :].strip()
        if resp < 0:
            return "silent", ""
        answer = text[resp + len("## Response") :].strip()
    if _is_silent(answer):
        return "silent", ""
    first, _, rest_lines = answer.partition("\n")
    if first.strip() == FAILURE_MARKER:
        return "failure", rest_lines.strip() or "The job reported a failure."
    return "report", answer


def _parse_file(path):
    """(kind, body, fmt) for one run file. fmt is "md" for an agent answer, "text" for script output."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return "silent", "", "text"
    key = str(path)
    hit = _parse_cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1], hit[2], hit[3]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "silent", "", "text"
    kind, body = parse_run(text)
    fmt = "md" if "\n## Prompt" in text else "text"
    if len(body) > BODY_MAX:
        body = body[:BODY_MAX].rstrip() + "\n\n(cut, full output in " + str(path) + ")"
    _parse_cache[key] = (mtime, kind, body, fmt)
    return kind, body, fmt


def _run_time(name):
    m = STAMP_RE.match(name)
    if not m:
        return None
    try:
        local = dt.datetime.strptime("{} {}:{}:{}".format(*m.groups()), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return local.astimezone()  # file names are local time


def _load_acks():
    acks = _load_json(ACK, {})
    return acks if isinstance(acks, dict) else {}


def collect(now=None):
    """Every alert in the window plus each job's current failure streak.

    Returns {"alerts": [...], "streaks": {job: {...}}}. Consecutive failed runs collapse into
    the newest one with a count. A failure streak that is still current stays listed after
    the window, because it still needs me."""
    now = now or _now()
    cutoff = now - dt.timedelta(hours=WINDOW_H)
    names = job_names()
    acks = _load_acks()
    alerts, streaks = [], {}
    reporting = set(sources())
    for jid in watched():
        folder = CRON / "output" / jid
        try:
            files = sorted(
                (p for p in folder.iterdir() if STAMP_RE.match(p.name)),
                key=lambda p: p.name,
                reverse=True,
            )
        except OSError:
            continue
        name = names.get(jid) or jid
        # The alert heading the current run of consecutive failures (newest first), if any.
        streak = None
        for idx, f in enumerate(files):
            at = _run_time(f.name)
            if at is None:
                continue
            kind, body, fmt = _parse_file(f)
            if kind == "report" and jid not in reporting:
                kind = "silent"  # failure-only job: a normal run ends a streak and shows nothing
            if streak is not None:
                if kind == "failure":
                    # Older failure in the same streak: fold it in, even past the window when
                    # the streak is still open (it still needs me).
                    streak["count"] += 1
                    streak["since"] = _iso(at)
                    continue
                streak = None
            if at < cutoff:
                break
            if kind == "silent":
                continue
            aid = f"{jid}:{f.stem}"
            is_open = kind == "failure" and idx == 0
            alert = {
                "id": aid,
                "job": jid,
                "name": name,
                "at": _iso(at),
                "kind": kind,
                "body": body,
                "fmt": fmt,
                "acked": acks.get(aid),
                # A report is information that clears itself, it needs no ack and never counts
                # in the badge. Only a failure needs me.
                "needs_ack": kind == "failure",
                "open": is_open,
                "count": 1,
                "since": _iso(at),
                "expires": None if is_open else _iso(at + dt.timedelta(hours=WINDOW_H)),
            }
            alerts.append(alert)
            if kind == "failure":
                streak = alert
                if is_open:
                    streaks[jid] = alert
    alerts.sort(key=lambda a: a["at"], reverse=True)
    return {"alerts": alerts, "streaks": streaks}


def get():
    """GET /api/alerts payload."""
    with _lock:
        data = collect()
    alerts = data["alerts"]
    for a in alerts:
        if a["open"]:
            a["item_key"] = "auto-" + _item_id(a)
    unacked = [a for a in alerts if a["needs_ack"] and not a["acked"]]
    return {
        "window_hours": WINDOW_H,
        "alerts": alerts,
        "counts": {
            "unacked": len(unacked),
            "failing": sum(1 for a in alerts if a["open"]),
            "acked": sum(1 for a in alerts if a["needs_ack"] and a["acked"]),
            "reports": sum(1 for a in alerts if not a["needs_ack"]),
        },
        "sources": len(sources()),
        "watched": len(watched()),
    }


def badge():
    """Unacknowledged failures, for the Alerts tab count. Reports never count."""
    try:
        return get()["counts"]["unacked"]
    except Exception:  # noqa: BLE001 - a badge never takes the sidebar down
        return 0


def ack(ids, act="ack"):
    """Acknowledge (or un-acknowledge) alerts by id. Prunes acks older than a week."""
    if act not in ("ack", "unack"):
        raise ValueError("act must be ack or unack")
    clean = [str(i) for i in ids or [] if re.fullmatch(r"[0-9a-f]{12}:[0-9_-]{19}", str(i))]
    if not clean:
        raise ValueError("no valid alert ids")
    with _lock:
        acks = _load_acks()
        stamp = _iso(_now())
        for i in clean:
            if act == "ack":
                acks[i] = stamp
            else:
                acks.pop(i, None)
        keep = _iso(_now() - dt.timedelta(days=ACK_KEEP_DAYS))
        acks = {k: v for k, v in acks.items() if (v or "") >= keep}
        _save_json(ACK, acks)
    return {"acked": acks}


def _item_id(alert):
    return "{}{}-{}".format(ITEM_PREFIX, alert["job"], re.sub(r"\D", "", alert["since"])[:12])


def _excerpt(body, n=700):
    body = (body or "").strip()
    return body if len(body) <= n else body[-n:].lstrip()


def sync(now=None):
    """Raise one Action Center item per failing job and close items whose job recovered.

    Only writes when something changed, so the 10-minute refresh does not churn the board."""
    import automation_actions

    with _lock:
        data = collect(now)
    store = automation_actions._load()["items"]
    want = {}
    for a in data["streaks"].values():
        want[_item_id(a)] = a
    raised = closed = 0
    for iid, a in want.items():
        times = "once" if a["count"] == 1 else "%d times in a row" % a["count"]  # noqa: UP031
        local = dt.datetime.fromisoformat(a["at"].replace("Z", "+00:00")).astimezone()
        why = "{} failed {}, last run {}. Last output: {}".format(
            a["name"],
            times,
            local.strftime("%a %b %d %the owner:%M %p"),
            _excerpt(a["body"]),
        )
        prev = store.get(iid)
        if prev and not prev.get("closed") and prev.get("why") == automation_actions._ascii(why):
            continue
        automation_actions.raise_item(
            iid,
            title="{} is failing".format(a["name"]),
            why=why,
            action="Read the full output under Action Center > Alerts and fix the cause. This item closes itself when the job's next run succeeds.",
            priority="high",
            owner="owner",
            refs=["cron " + a["job"]],
            links=[{"label": "Open Alerts", "url": OPS_URL}],
            source="Alerts",
        )
        raised += 1
    for iid, e in store.items():
        if iid.startswith(ITEM_PREFIX) and not e.get("closed") and iid not in want:
            automation_actions.close_item(iid, "The job's next run succeeded.")
            closed += 1
    return {"failing": len(want), "raised_or_updated": raised, "closed": closed}


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "list"
    if cmd == "sync":
        try:
            print(json.dumps(sync()))
        except Exception as e:  # noqa: BLE001 - report and exit non-zero, the refresh carries on
            print(f"alerts sync failed: {e}", file=sys.stderr)
            return 1
        return 0
    if cmd == "list":
        print(json.dumps(get(), indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
