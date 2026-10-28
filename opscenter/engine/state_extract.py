"""
State extraction helpers.

Purpose: Pure-stdlib parsers that mine the markdown and JSON state files into structured data for the
analysis bundle (analysis_bundle.py). Read only.

Sources consumed:
  state/current-state.md          master posture (escalations, open items)
  state/risk-radar.md              risk themes over time
  state/unplanned-work-ledger.md   append-only unplanned work (dated)
  state/decisions-log.md           append-only decisions (dated)
  state/sprint-watch-snapshot.json ticket status, priority and due date map
"""

import datetime as dt
import json
import re
from pathlib import Path

ANY_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ticket_stats(snapshot):
    tickets = snapshot.get("tickets", {}) or {}
    by_status = {}
    by_priority = {}
    overdue = []
    today = dt.date.today().isoformat()
    for key, meta in tickets.items():
        st = (meta or {}).get("status", "Unknown") or "Unknown"
        pr = (meta or {}).get("priority", "Unknown") or "Unknown"
        by_status[st] = by_status.get(st, 0) + 1
        by_priority[pr] = by_priority.get(pr, 0) + 1
        due = (meta or {}).get("duedate")
        if due and due < today and st not in ("Done", "Closed"):
            overdue.append((key, due, st))
    return by_status, by_priority, overdue, len(tickets)


def extract_sections(md):
    """Split a markdown doc into (title, level, body_md) sections on ## / ###."""
    sections = []
    cur_title = None
    cur_level = 2
    buf = []
    for line in md.split("\n"):
        m = re.match(r"^(#{2,3})\s+(.*)$", line)
        if m:
            if cur_title is not None:
                sections.append((cur_title, cur_level, "\n".join(buf).strip()))
            cur_level = len(m.group(1))
            cur_title = m.group(2).strip()
            buf = []
        else:
            buf.append(line)
    if cur_title is not None:
        sections.append((cur_title, cur_level, "\n".join(buf).strip()))
    return sections


def extract_escalations(current_md):
    """Top escalations = headers explicitly marked ESCALATION / TOP: / URGENT,
    excluding RESOLVED ones and unrelated sections. Returns [(title, first_line)]."""
    out = []
    secs = extract_sections(current_md)
    for title, level, body in secs:
        t = title.upper()
        if level != 2:
            continue
        if "RESOLVED" in t:
            continue
        is_esc = (
            t.startswith("ESCALATION")
            or "ESCALATION (TOP)" in t
            or "(TOP):" in t
            or t.startswith("URGENT")
            or ": URGENT" in t
        )
        if not is_esc:
            continue
        first = ""
        for line in body.split("\n"):
            if line.strip():
                first = line.strip()
                break
        out.append((title, first))
    return out


def extract_stale_tickets(current_md):
    """Parse the 'Stale/Blocked Tickets' markdown table into rows."""
    secs = extract_sections(current_md)
    rows = []
    for title, _level, body in secs:
        if "STALE/BLOCKED" in title.upper():
            for line in body.split("\n"):
                if "|" in line and not re.match(r"^\s*\|?[\s:|-]+\|", line):
                    cells = [c.strip() for c in line.strip().strip("|").split("|")]
                    if len(cells) >= 4 and cells[0].upper() not in ("KEY",):
                        rows.append(cells[:4])  # Key, Summary, Assignee, LastUpdated
    return rows


def extract_open_items(current_md, limit=12):
    """The numbered 'Open Items Awaiting Decision' list -> [text, ...]."""
    secs = extract_sections(current_md)
    items = []
    for title, _level, body in secs:
        if "OPEN ITEMS AWAITING DECISION" in title.upper():
            for line in body.split("\n"):
                m = re.match(r"^\d+\.\s+(.*)$", line.strip())
                if m:
                    items.append(m.group(1))
    return items[:limit]


def newest_dated_entries(md, limit=6):
    """Return [(date, short_title, first_body_line)] for the newest dated
    sections in an append-only log."""
    secs = extract_sections(md)
    dated = []
    for title, level, body in secs:
        m = ANY_DATE.search(title)
        if m and level == 2:
            short = re.sub(r"^\d{4}-\d{2}-\d{2}\s*\|?\s*", "", title)
            first = ""
            for line in body.split("\n"):
                if line.strip():
                    first = line.strip()
                    break
            dated.append((m.group(1), short, first))
    # logs are newest-first already; keep order
    return dated[:limit]
