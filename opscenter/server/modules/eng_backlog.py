"""Debt and improvements: every TD and IMP entry on one Ops Center page.

Date: 2026-10-12
Purpose: parse engineering-state/technical-debt.md (TD-NNN) and state/improvement-backlog.md
(IMP-NNN) into rows for the Ops Center "Debt and improvements" page, and apply the owner's decisions.

The markdown files stay the source of truth. A decision (approve, park, decline, reopen,
accept risk) rewrites ONLY that entry's Status line in place, under a lock, keeping the old
status text after "Earlier:", so every session that reads the file before suggesting sees it.
Snooze is page-only and lives in state/dashboard/eng-backlog-handled.json.
"""

import datetime as dt
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path

import paths

ROOT = Path(os.environ.get("OPSCENTER_ROOT", paths.root()))
TD_FILE = Path(os.environ.get("ENGBL_TD", ROOT / "engineering-state" / "technical-debt.md"))
IMP_FILE = Path(os.environ.get("ENGBL_IMP", ROOT / "state" / "improvement-backlog.md"))
HANDLED = Path(
    os.environ.get("ENGBL_HANDLED", ROOT / "state" / "dashboard" / "eng-backlog-handled.json")
)
SNOOZE_DAYS = 7

HEAD_RE = re.compile(r"^(#{2,3})\s+((TD|IMP)-(\d{3}))\b[\s:\-]*(.*)$")
STATUS_RE = re.compile(
    r"^(\s*-\s+)(?:\*\*)?Status(?:\*\*)?(\s*\([^)]*\))?\s*(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.*)$", re.I
)
FIELD_RE = r"^\s*-\s+(?:\*\*)?{name}(?:\*\*)?\s*(?:\*\*)?:\s*(?:\*\*)?\s*(.*)$"
DATE_RE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
SEV = ("critical", "high", "medium", "low")


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _field(body, name):
    m = re.search(FIELD_RE.format(name=name), body, re.I | re.M)
    return m.group(1).strip() if m else ""


def _bucket(kind, heading, status):
    s = (status or "").lower()
    h = heading.lower()
    if kind == "TD":
        if re.match(r"\s*(resolved|closed|done|retired)", s) or "(resolved" in h:
            return "done"
        if re.match(r"\s*accepted", s) or "accepted workaround" in h:
            return "parked"
        return "todo"
    if re.match(r"\s*(declined|withdrawn|folded|rejected)", s):
        return "done"
    if re.match(r"\s*shipped", s):
        return "done"
    if re.match(r"\s*(deferred|parked)", s):
        return "parked"
    if re.match(r"\s*(approved|in-progress|in progress|built|building)", s):
        return "todo"
    return "decide"  # suggested, proposed, blank


def _outcome(kind, status):
    s = (status or "").strip().lower()
    for word in (
        "resolved",
        "closed",
        "shipped",
        "declined",
        "withdrawn",
        "folded",
        "accepted",
        "deferred",
        "parked",
        "approved",
        "in-progress",
        "in progress",
        "built",
        "suggested",
        "proposed",
        "open",
        "active",
    ):
        if s.startswith(word):
            return word.replace("in progress", "in-progress")
    return "open" if kind == "TD" else "suggested"


def _severity(heading, body, status):
    for src in (_field(body, "Severity"), status, heading):
        m = re.search(r"\b(critical|high|medium|low)\b", src or "", re.I)
        if m:
            return m.group(1).lower()
    return ""


def parse_file(path, kind):
    """Rows for every TD/IMP heading of the given kind in one markdown file."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    heads = [i for i, ln in enumerate(lines) if HEAD_RE.match(ln)]
    rows = []
    for n, i in enumerate(heads):
        m = HEAD_RE.match(lines[i])
        if m is None or m.group(3) != kind:
            continue
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        # stop at a horizontal rule or a higher-level section that is not an entry
        block = []
        for ln in lines[i + 1 : end]:
            if ln.strip() == "---" or (ln.startswith("# ") and not HEAD_RE.match(ln)):
                break
            block.append(ln)
        body = "\n".join(block).strip()
        title = m.group(5).strip().strip("-: ").strip()
        status = ""
        for ln in block:
            sm = STATUS_RE.match(ln)
            if sm:
                status = ((sm.group(2) or "").strip() + " " + sm.group(3)).strip()
                break
        if not status:
            pm = re.search(r"\(([^)]*)\)\s*$", title)
            status = pm.group(1) if pm else ""
        heading = lines[i]
        bucket = _bucket(kind, heading, status)
        outcome = _outcome(kind, status)
        if kind == "TD" and bucket == "done" and outcome in ("open", "active"):
            outcome = "resolved"  # the heading says RESOLVED, the Status line was never updated
        uid = f"{m.group(2).lower()}-{hashlib.sha1(heading.encode()).hexdigest()[:6]}"
        goals = sorted(set(re.findall(r"\bG([1-4])\b", _field(body, "Goal") or body)))
        effort = _field(body, "Effort")
        if not effort:
            em = re.search(r"\*\*Effort\*\*:\s*([^\n]+)", body)
            effort = em.group(1).strip() if em else ""
        dates = DATE_RE.findall(heading + " " + status) or DATE_RE.findall(body)
        rows.append(
            {
                "uid": uid,
                "id": m.group(2),
                "kind": kind,
                "title": title,
                "heading": heading,
                "line": i + 1,
                "status": status,
                "outcome": outcome,
                "bucket": bucket,
                "severity": _severity(heading, body, status) if kind == "TD" else "",
                "goals": ["G" + g for g in goals] if kind == "IMP" else [],
                "effort": effort[:160],
                "owner": _field(body, "Owner")[:120],
                "date": max(dates) if dates else "",
                "body": body[:12000],
                "file": str(path),
            }
        )
    return rows


def _load_handled():
    try:
        h = json.loads(HANDLED.read_text(encoding="utf-8")).get("handled", {})
        return h if isinstance(h, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_handled(h):
    HANDLED.parent.mkdir(parents=True, exist_ok=True)
    tmp = HANDLED.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"handled": h}, indent=2), encoding="utf-8")
    tmp.replace(HANDLED)


def items():
    """GET /api/eng-backlog payload. Snoozed rows keep their bucket and carry `snoozed`."""
    now = _now()
    handled = _load_handled()
    rows = parse_file(TD_FILE, "TD") + parse_file(IMP_FILE, "IMP")
    for r in rows:
        h = handled.get(r["uid"])
        r["snoozed"] = None
        if h and h.get("act") == "snoozed":
            try:
                until = dt.datetime.strptime(h["until"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=dt.timezone.utc
                )
            except (KeyError, ValueError):
                until = now
            if until > now and r["bucket"] in ("decide", "todo"):
                r["snoozed"] = h
    counts = {}
    for r in rows:
        key = "snoozed" if r["snoozed"] else r["bucket"]
        counts[key] = counts.get(key, 0) + 1
    counts["decide_imp"] = sum(1 for r in rows if r["bucket"] == "decide" and not r["snoozed"])
    return {"generated_utc": _iso(now), "counts": counts, "items": rows}


def find(uid):
    for r in parse_file(TD_FILE, "TD") + parse_file(IMP_FILE, "IMP"):
        if r["uid"] == uid:
            return r
    raise KeyError(uid)


# act -> (allowed kinds, allowed buckets, new status prefix)
ACTS = {
    "approve": (("IMP",), ("decide", "parked"), "approved"),
    "park": (("IMP",), ("decide", "todo"), "parked"),
    "decline": (("IMP",), ("decide", "parked", "todo"), "declined"),
    "reopen": (("IMP",), ("parked", "done"), "suggested"),
    "accept": (("TD",), ("todo",), "ACCEPTED"),
    "resolve": (("TD",), ("todo", "parked"), "RESOLVED"),
}


def set_status(uid, act, note=""):
    """Rewrite one entry's Status line in place. Returns the updated row."""
    if act not in ACTS:
        raise ValueError("act must be one of " + ", ".join(ACTS))
    kinds, buckets, word = ACTS[act]
    row = find(uid)
    if row["kind"] not in kinds:
        raise ValueError(f"{act} does not apply to {row['kind']} entries")
    if row["bucket"] not in buckets:
        raise ValueError(f"{row['id']} is {row['outcome']}, {act} does not apply")
    note = re.sub(r"\s+", " ", (note or "")).strip()[:500]
    if act in ("accept", "resolve") and not note:
        raise ValueError("accepting a risk or closing debt needs a reason")
    path = Path(row["file"])
    today = _now().strftime("%Y-%m-%d")
    new_status = f"{word} {today} (decided in the Ops Center)"
    if note:
        new_status += f". {note.rstrip('.')}."
    else:
        new_status += "."
    if row["status"]:
        new_status += f" Earlier: {row['status']}"
    lock = path.with_name("." + path.name + ".lock")
    with open(lock, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        lines = path.read_text(encoding="utf-8").splitlines(True)
        hits = [i for i, ln in enumerate(lines) if ln.rstrip("\n") == row["heading"]]
        if len(hits) != 1:
            raise RuntimeError(f"{row['id']} heading found {len(hits)} times, refusing to edit")
        i = hits[0]
        j = i + 1
        status_at = None
        while j < len(lines) and not HEAD_RE.match(lines[j]) and lines[j].strip() != "---":
            if status_at is None and STATUS_RE.match(lines[j].rstrip("\n")):
                status_at = j
            j += 1
        line = f"- **Status**: {new_status}\n"
        if status_at is not None:
            lines[status_at] = line
        else:
            k = j
            while k > i + 1 and not lines[k - 1].strip():
                k -= 1
            lines.insert(k, line)
        tmp = path.with_name(path.name + ".engbl.tmp")
        tmp.write_text("".join(lines), encoding="utf-8")
        os.replace(tmp, path)
    handled = _load_handled()
    if handled.pop(uid, None) is not None:
        _save_handled(handled)
    return find(uid)


def handle(uid, act):
    """Page-only snooze (7 days) or restore."""
    if act not in ("snooze", "restore"):
        raise ValueError("act must be snooze or restore")
    find(uid)
    h = _load_handled()
    if act == "restore":
        h.pop(uid, None)
    else:
        now = _now()
        h[uid] = {
            "act": "snoozed",
            "at": _iso(now),
            "until": _iso(now + dt.timedelta(days=SNOOZE_DAYS)),
        }
    _save_handled(h)
    return {"uid": uid, "handled": h.get(uid)}


def tackle_item(row):
    """The item the runtime slot starts a session for (server/runtime_slot.py): the entry as written, with its source file and line."""
    return {
        "title": f"{row['id']}: {row['title']}"[:160],
        "summary": (
            f"Status: {row['status'] or '(none)'}\n"
            f"Source: {row['file']} (line {row['line']})\n"
            + (
                f"Goals: {', '.join(row['goals']) or '?'}. Effort: {row['effort'] or '?'}.\n"
                if row["kind"] == "IMP"
                else f"Severity: {row['severity'] or '?'}. Owner: {row['owner'] or '?'}.\n"
            )
            + f"Entry as written:\n{row['body'][:6000]}"
        ),
        "priority": row["severity"] if row["severity"] in SEV else "medium",
        "refs": [row["id"]],
        "key": row["id"],
    }
