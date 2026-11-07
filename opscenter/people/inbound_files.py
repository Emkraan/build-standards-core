"""
inbound_files.py - files a direct report sends the owner become Action Center items.

Why: a file sent in a 1:1 chat or by mail can hold the root cause of a problem and sit unread for days. The chat and mail feeds keep
only their newest items (about three days), and the inbound monitor folds message text, so a file never became something on the board.

How:
- harvest_messages(messages, surface): called by the inbound chat and mail wake gates at pull time, on EVERY pulled message (before
  triage, so a file-only message triage drops is still caught). harvest_feeds() re-reads the rolling feeds on every bundle as a second
  path. Both upsert into the durable store <dashboard>/inbound-files.json, so nothing depends on the feed window.
- action_items(): one Action Center item per message (key file-<hash>), merged into the board like the one-on-one agenda items. It stays
  on the board until the owner resolves or ignores it there (the handled store, by fingerprint). Medium when fresh, high once it is 48
  hours old.
- Scope: direct reports only (roster group "report", people/one_on_ones.py). Chat attachments (1:1 and group chats), mail from a report
  with attachments, and share notifications from a document service naming a report.

Date:    2026-11-06
Runtime: Python 3 stdlib only (the gates run outside any service venv)

Configuration (all optional; without a roster nothing is harvested):
  INBOUND_FILES_FEEDS      JSON {"chat": "<feed.json>", "mail": "<feed.json>"}, the rolling feeds harvest_feeds() re-reads (a feed is
                           {"items": [...]}); default none
  INBOUND_FILES_TICKET_RE  regex for the ticket ids copied onto an item's refs (default: a project key, a dash and a number)
  INBOUND_FILES_TZ         IANA zone the item text shows times in (default UTC)
  INBOUND_FILES_SHARE_SENDERS  JSON list of sender domain suffixes whose share notifications count (default none)
"""

import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

sys.path.insert(0, str(HERE.parent / "server" / "modules"))

import one_on_ones  # noqa: E402  (roster is the single source of truth)
import paths  # noqa: E402

DASH = paths.dashboard_dir()
STORE_PATH = DASH / "inbound-files.json"
HANDLED_PATH = DASH / "action-handled.json"


def _feeds():
    try:
        d = json.loads(os.environ.get("INBOUND_FILES_FEEDS") or "{}")
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


ESCALATE_AFTER = dt.timedelta(hours=48)
# Store hygiene only: an entry I already resolved or ignored on the board is dropped from
# the store after this long. Unhandled entries are never pruned.
PRUNE_HANDLED_AFTER = dt.timedelta(days=30)
TEXT_KEEP = 400


def _ticket_re():
    try:
        return re.compile(
            os.environ.get("INBOUND_FILES_TICKET_RE") or r"\b([A-Z][A-Z0-9]+-\d{2,6})\b"
        )
    except re.error:
        return re.compile(r"\b([A-Z][A-Z0-9]+-\d{2,6})\b")


TICKET_RE = _ticket_re()
SHARE_SUBJ_RE = re.compile(r"\bshared\b.*\bwith you\b", re.I)


def _share_senders():
    try:
        d = json.loads(os.environ.get("INBOUND_FILES_SHARE_SENDERS") or "[]")
    except ValueError:
        return ()
    return tuple(str(x).lower() for x in d) if isinstance(d, list) else ()


def _tz():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(os.environ.get("INBOUND_FILES_TZ") or "UTC")
    except Exception:  # noqa: BLE001 - tzdata missing or a bad name
        return dt.timezone.utc


def _reports():
    return [p for p in one_on_ones.roster() if p.get("group", "report") == "report"]


def _parse(ts):
    if not ts:
        return None
    try:
        return dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".inbound-files.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=True)
        fh.write("\n")
    os.replace(tmp, path)


_ASCII_MAP = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
        "\u00a0": " ",
    }
)


def _ascii(s):
    if not s:
        return ""
    return s.translate(_ASCII_MAP).encode("ascii", "ignore").decode("ascii")


def _entry_from_chat(m, reports):
    if (m.get("surface") or "chat") != "chat":
        return None  # channel posts are not sent to me
    files = [f for f in (m.get("files") or []) if f.get("url")]
    if not files:
        return None
    by_name = {p["name"].lower(): p for p in reports}
    p = by_name.get((m.get("from_name") or "").strip().lower())
    if not p:
        return None
    ctype = m.get("chat_type") or ""
    if ctype == "oneOnOne":
        where = "in your 1:1 chat"
    elif m.get("chat_topic"):
        where = "in the group chat '{}'".format(m.get("chat_topic"))
    else:
        where = "in a group chat"
    return {
        "id": "chat:" + str(m.get("id")),
        "surface": "chat",
        "person": p["name"],
        "first": p.get("first") or p["name"].split(" ")[0],
        "at": m.get("created"),
        "where": where,
        "files": [{"name": f.get("name") or "file", "url": f.get("url")} for f in files],
        "text": (m.get("text") or "")[:TEXT_KEEP],
        "link": m.get("web_url"),
        "subject": "",
    }


def _entry_from_mail(m, reports):
    by_mail = {p["email"].lower(): p for p in reports}
    addr = (m.get("from_addr") or "").lower()
    p = by_mail.get(addr)
    share = False
    if (
        not p
        and any(addr.endswith(s) for s in _share_senders())
        and SHARE_SUBJ_RE.search(m.get("subject") or "")
    ):
        name = (m.get("from_name") or "").lower()
        p = next((r for r in reports if r["name"].lower() in name), None)
        share = p is not None
    if not p or not (m.get("has_attachments") or share):
        return None
    subj = m.get("subject") or ""
    shared = (
        re.search(r"shared ['\"\u2018\u201c](.+?)['\"\u2019\u201d] with you", subj)
        if share
        else None
    )
    fname = shared.group(1) if shared else (subj or "attachment")
    return {
        "id": "mail:" + str(m.get("id")),
        "surface": "mail",
        "person": p["name"],
        "first": p.get("first") or p["name"].split(" ")[0],
        "at": m.get("received"),
        "where": "by a document share" if share else (f"by email ('{subj}')"),
        "files": [{"name": fname, "url": m.get("web_link")}],
        "text": (m.get("body_text") or m.get("preview") or "")[:TEXT_KEEP],
        "link": m.get("web_link"),
        "subject": subj,
    }


def harvest_messages(messages, surface):
    """Upsert file entries from freshly pulled puller messages. Returns how many were new.
    Best-effort by design: the caller (a wake gate) must never fail because of this."""
    reports = _reports()
    build = _entry_from_chat if surface in ("chat", "teams") else _entry_from_mail
    entries = [e for e in (build(m, reports) for m in (messages or [])) if e]
    return _upsert(entries)


def harvest_feeds():
    """Second path: re-read both rolling feeds (cheap, idempotent)."""
    n, feeds = 0, _feeds()
    chat = feeds.get("chat") or feeds.get("teams")
    if chat:
        n += harvest_messages(_load(chat, {}).get("items", []), "chat")
    if feeds.get("mail"):
        mail = _load(feeds["mail"], {})
        n += harvest_messages(mail.get("items", mail) if isinstance(mail, dict) else mail, "mail")
    return n


def _upsert(entries):
    if not entries:
        return 0
    store: dict = _load(STORE_PATH, {"files": {}})
    files = store.setdefault("files", {})
    new = 0
    now = _now().isoformat(timespec="seconds")
    for e in entries:
        cur = files.get(e["id"])
        if cur:
            # keep first_seen and any dismissal, refresh content
            e["first_seen"] = cur.get("first_seen") or now
            for k in ("dismissed", "dismissed_reason"):
                if k in cur:
                    e[k] = cur[k]
        else:
            e["first_seen"] = now
            new += 1
        files[e["id"]] = e
    store["updated"] = now
    _save_atomic(STORE_PATH, store)
    return new


def _key(entry_id):
    return "file-" + hashlib.sha1(entry_id.encode("utf-8")).hexdigest()[:12]


def _when(ts):
    d = _parse(ts)
    if not d:
        return "recently"
    loc = d.astimezone(_tz())
    hour = loc.strftime("%I:%M %p").lstrip("0")
    return f"{loc.month}/{loc.day} {hour} {loc.tzname() or ''}"


def action_items(now=None):
    """Action Center items for every stored file not dismissed (consumed by bundle_data).
    Resolve/Ignore on the board hides an item by fingerprint, so handled ones need no
    filtering here."""
    now = now or _now()
    store = _load(STORE_PATH, {"files": {}})
    out = []
    for e in sorted(store.get("files", {}).values(), key=lambda x: x.get("at") or ""):
        if e.get("dismissed"):
            continue
        names = [f["name"] for f in e.get("files", [])]
        lead = names[0] if names else "a file"
        more = f" (+{len(names) - 1} more)" if len(names) > 1 else ""
        at = _parse(e.get("at"))
        old = bool(at and now - at >= ESCALATE_AFTER)
        text = " ".join((e.get("text") or "").split())
        said = (f' with: "{text[:280]}"') if text else ""
        refs = sorted(set(TICKET_RE.findall(text + " " + (e.get("subject") or ""))))
        out.append(
            {
                "key": _key(e["id"]),
                "priority": "high" if old else "medium",
                "title": _ascii("Unread file from {}: {}{}".format(e.get("first"), lead, more)),
                "why": _ascii(
                    "{} sent this {} on {}{}.".format(
                        e.get("first"), e.get("where"), _when(e.get("at")), said
                    )
                ),
                "action": "Open it and decide what it needs, or use Tackle to have it read and summarized. Resolve here once it is handled.",
                "owner": e.get("person") or "",
                "refs": refs,
                "sources": [
                    "File from report",
                    "Chat" if e.get("surface") in ("chat", "teams") else "Mail",
                ],
                "links": [
                    {"label": _ascii(f["name"]), "url": f["url"]}
                    for f in e.get("files", [])
                    if f.get("url")
                ]
                + (
                    [{"label": "Message", "url": e["link"]}]
                    if e.get("link") and e.get("surface") in ("chat", "teams")
                    else []
                ),
            }
        )
    return out


def dismiss(entry_id, reason):
    """Mark an entry handled outside the board (for example a file already read and acted on)."""
    store = _load(STORE_PATH, {"files": {}})
    e = store.get("files", {}).get(entry_id)
    if not e:
        return False
    e["dismissed"] = True
    e["dismissed_reason"] = reason
    _save_atomic(STORE_PATH, store)
    return True


def prune(now=None):
    """Drop entries the owner resolved or ignored on the board more than PRUNE_HANDLED_AFTER ago.
    Never drops an unhandled entry."""
    now = now or _now()
    store = _load(STORE_PATH, {"files": {}})
    handled = _load(HANDLED_PATH, {}).get("handled", {})
    ac_fingerprint = one_on_ones._board_fingerprint()
    if ac_fingerprint is None:
        return 0
    drop = []
    for eid, e in store.get("files", {}).items():
        h = handled.get(ac_fingerprint({"key": _key(eid)})) or {}
        at = _parse(h.get("at"))
        if (
            h.get("act") in ("resolved", "ignored", "ignored_forever")
            and at
            and now - at >= PRUNE_HANDLED_AFTER
            or e.get("dismissed")
            and (_parse(e.get("at")) or now) < now - PRUNE_HANDLED_AFTER
        ):
            drop.append(eid)
    for eid in drop:
        store["files"].pop(eid, None)
    if drop:
        _save_atomic(STORE_PATH, store)
    return len(drop)


if __name__ == "__main__":
    print("new from feeds:", harvest_feeds())
    print("pruned:", prune())
    for it in action_items():
        print(it["priority"], it["key"], "|", it["title"])
