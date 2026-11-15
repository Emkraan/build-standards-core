"""Debt and improvements: every TD and IMP entry on one Ops Center page.

Date: 2026-10-12
Purpose: parse engineering-state/technical-debt.md (TD-NNN) and state/improvement-backlog.md
(IMP-NNN) into rows for the Ops Center "Debt and improvements" page, and apply the owner's decisions.

The markdown files stay the source of truth. A decision (approve, park, decline, reopen,
accept risk) rewrites ONLY that entry's Status line in place, under a lock, keeping the old
status text after "Earlier:", so every session that reads the file before suggesting sees it.
Snooze is page-only and lives in state/dashboard/eng-backlog-handled.json.
"""

import contextlib
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


# Status vocabulary. The first words of a Status line decide the bucket. Sessions write statuses in
# their own words ("DONE 10/24", "Resolved by #444", "Superseded by TD-075", "In review"), so the
# page reads every common spelling instead of dropping unknown words into Needs decision.
# (leading phrase, outcome) checked in order, longest phrases first where they overlap.
_VOCAB = [
    (r"folded|merged into|rolled into|absorbed into|tracked (?:in|under|as)", "folded"),
    (
        r"superseded|duplicate|dup\b|obsolete|no longer (?:applies|real|relevant)|moot|n/?a\b",
        "withdrawn",
    ),
    (r"withdrawn|retracted|dropped|cancel+ed", "withdrawn"),
    (r"declined|rejected|won'?t do|will not do", "declined"),
    (r"retired|decommissioned", "retired"),
    (r"resolved|fixed|closed", "resolved"),
    (r"shipped|done|complete[d]?|delivered|live\b|landed|merged\b", "shipped"),
    (r"risk accepted|accepted|won'?t fix", "accepted"),
    (r"deferred|parked|on hold|later\b|backlog\b", "parked"),
    (
        r"in[- ]progress|in review|in flight|building|started|staged|partly|partial|underway|blocked",
        "in-progress",
    ),
    (r"approved|planned|scheduled|queued", "approved"),
    (r"built\b", "built"),
    (r"suggested|proposed|new\b|idea\b", "suggested"),
    (r"open|active|known|monitoring|watch", "open"),
]
_LEAD = r"^[\W_]*(?:(?:20\d\d-\d\d-\d\d|\d{1,2}/\d{1,2}(?:/\d{2,4})?)[\W_]*)?"
_VOCAB_RE = [(re.compile(_LEAD + "(?:" + pat + r")", re.I), out) for pat, out in _VOCAB]
_DONE = {"folded", "withdrawn", "declined", "retired", "resolved", "shipped"}
PARENT_RE = re.compile(
    r"^[\W_]*(?:folded|merged|rolled|absorbed|tracked)\s+(?:into|in|under|as)\s+\[?((?:TD|IMP)-\d{3})"
    r"|^[\W_]*(?:superseded|replaced)\s+by\s+\[?((?:TD|IMP)-\d{3})",
    re.I,
)


def canonical(kind, status):
    """Outcome word for a Status line, or "" when the leading words are not in the vocabulary."""
    s = (status or "").strip()
    for rx, out in _VOCAB_RE:
        if rx.match(s):
            if kind == "TD" and out == "shipped":
                return "resolved"
            if kind == "IMP" and out in ("resolved", "retired"):
                return "shipped"
            return out
    return ""


def _bucket(kind, heading, status):
    h = heading.lower()
    out = canonical(kind, status)
    # A TD heading marked (RESOLVED ...) wins over a Status line nobody updated.
    if out in _DONE or (kind == "TD" and "(resolved" in h):
        return "done"
    if out in ("accepted", "parked") or (kind == "TD" and "accepted workaround" in h):
        return "parked"
    if kind == "TD":
        return "todo"
    if out in ("in-progress", "approved", "built"):
        return "todo"
    return "decide"  # suggested, proposed, blank, unknown words


def _outcome(kind, status):
    return canonical(kind, status) or ("open" if kind == "TD" else "suggested")


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
        pm = PARENT_RE.match(status) if bucket == "done" else None
        parent = (pm.group(1) or pm.group(2)).upper() if pm else ""
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
                "parent": parent,
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


def all_rows():
    return link_children(parse_file(TD_FILE, "TD") + parse_file(IMP_FILE, "IMP"))


def link_children(rows):
    """Point each folded row at its open parent and give parents a `children` uid list.

    Ids repeat across sessions, so a parent id resolves to the open row with that id, then the
    newest row. A parent link that resolves to nothing (typo, deleted entry) is dropped.
    """
    by_id = {}
    for r in rows:
        by_id.setdefault(r["id"], []).append(r)
    for r in rows:
        r["children"] = []
    for r in rows:
        pid = r.get("parent")
        if not pid:
            continue
        cands = by_id.get(pid, [])
        target = next((c for c in cands if c["bucket"] != "done"), None) or (
            cands[-1] if cands else None
        )
        if target is None or target is r:
            r["parent"] = ""
            continue
        r["parent_uid"] = target["uid"]
        target["children"].append(r["uid"])
    return rows


def resolve_id(key, rows=None):
    """A uid, or an id that names exactly one open row (else exactly one row)."""
    rows = rows if rows is not None else all_rows()
    for r in rows:
        if r["uid"] == key:
            return r
    hits = [r for r in rows if r["id"] == key.upper()]
    live = [r for r in hits if r["bucket"] != "done"]
    if len(live) == 1:
        return live[0]
    if len(hits) == 1:
        return hits[0]
    raise KeyError(key if not hits else f"{key} is ambiguous, use the uid")


def items():
    """GET /api/eng-backlog payload. Snoozed rows keep their bucket and carry `snoozed`."""
    now = _now()
    handled = _load_handled()
    rows = all_rows()
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
    for r in all_rows():
        if r["uid"] == uid:
            return r
    raise KeyError(uid)


@contextlib.contextmanager
def file_lock(path):
    lock = Path(path).with_name("." + Path(path).name + ".lock")
    with open(lock, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        yield


def atomic_write(path, text):
    path = Path(path)
    tmp = path.with_name(path.name + f".engbl.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def rewrite_status(row, new_status):
    """Replace (or add) the Status line of one entry, under the file lock."""
    path = Path(row["file"])
    with file_lock(path):
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
        atomic_write(path, "".join(lines))


# act -> (allowed kinds, allowed buckets, new status prefix)
ACTS = {
    "approve": (("IMP",), ("decide", "parked"), "approved"),
    "park": (("IMP",), ("decide", "todo"), "parked"),
    "decline": (("IMP",), ("decide", "parked", "todo"), "declined"),
    "reopen": (("IMP",), ("parked", "done"), "suggested"),
    "accept": (("TD",), ("todo",), "ACCEPTED"),
    "resolve": (("TD",), ("todo", "parked"), "RESOLVED"),
    "ship": (("IMP",), ("decide", "todo"), "shipped"),
    "withdraw": (("IMP",), ("decide", "todo", "parked"), "withdrawn"),
    "fold": (("TD", "IMP"), ("decide", "todo", "parked"), "folded into"),
    "undo": (("TD", "IMP"), ("decide", "todo", "parked", "done"), ""),
}


def set_status(uid, act, note="", target=""):
    """Rewrite one entry's Status line in place. Returns the updated row.

    fold needs `target` (the id or uid of the entry it folds into). undo puts back the status the
    entry had before its last change (the text after the first "Earlier:").
    """
    if act not in ACTS:
        raise ValueError("act must be one of " + ", ".join(ACTS))
    kinds, buckets, word = ACTS[act]
    rows = all_rows()
    row = next((r for r in rows if r["uid"] == uid), None)
    if row is None:
        raise KeyError(uid)
    if row["kind"] not in kinds:
        raise ValueError(f"{act} does not apply to {row['kind']} entries")
    if row["bucket"] not in buckets:
        raise ValueError(f"{row['id']} is {row['outcome']}, {act} does not apply")
    note = re.sub(r"\s+", " ", (note or "")).strip()[:500]
    if act in ("accept", "resolve") and not note:
        raise ValueError("accepting a risk or closing debt needs a reason")
    today = _now().strftime("%Y-%m-%d")
    if act == "undo":
        if " Earlier: " not in row["status"]:
            raise ValueError(f"{row['id']} has no earlier status to go back to")
        new_status = row["status"].split(" Earlier: ", 1)[1]
    else:
        if act == "fold":
            parent = resolve_id(target or "", rows)
            if parent["uid"] == row["uid"] or parent.get("parent"):
                raise ValueError("fold into an open entry other than itself")
            word = f"folded into {parent['id']} ({parent['title'][:70]})"
        new_status = f"{word} {today} (decided in the Ops Center)"
        new_status += f". {note.rstrip('.')}." if note else "."
        if row["status"]:
            new_status += f" Earlier: {row['status']}"
    rewrite_status(row, new_status)
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
