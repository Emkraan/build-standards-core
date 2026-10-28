#!/usr/bin/env python3
"""
one_on_ones.py - 1:1 board harvester for the ops center (the people slot, off by default).

Purpose: Turn data already collected into per-person 1:1 discussion topics:
           - chat 1:1, group and channel messages (the chat feed)
           - mail from the person (the mail feed)
           - action items from the weekly team assessment
           - the owner's curated agenda (state/dashboard/one-on-one-agenda.json)
           - topics the owner adds by hand on the board
         Pure parsing. No model call. Harvested topics accumulate in a ledger so they survive the feeds'
         rolling window. Scope is the roster only: the owner's direct reports, plus any standing 1:1 partners
         shown as a second group. Every other sender is ignored.

Parameters: one JSON file, OPSCENTER_PEOPLE_PARAMS (default <state>/people-params.json), every key optional:
  owner_name, owner_email   the owner's identity (their own messages are not topics, their address is not an attendee)
  roster                    [{"name", "first", "email", "title", "group"}] (group report, the default, or partner)
  calendar_tz               the zone the calendar reads wall clock times in (default UTC)
  feeds                     {"chat": path, "mail": path} (defaults <agent home>/feeds/chat.json and mail.json)
  roster_pull_file          the directory pull, a JSON list of {displayName, jobTitle, mail} rows (the roster slot)
  calendar_cmd              command list printing today's events as JSON (the calendar slot)
  meetings_cmd              command list for upcoming, availability, create and away (the meetings slot)
  meeting_subject           the 1:1 invite subject, with {owner}, {first} and {name} (default "{owner} and {first}: 1:1")
  retention_days            how long the ledger keeps a topic (default 45, DESIGN.md section 11 item 5)
  ticket_regex, ticket_url_regex   what a work ticket key and a browse URL look like
  mail_noise_regex, partner_invite_regex   mail subjects that are never topics, and standing meeting invites
  excluded_title_regex      topics from analyzed sources whose title matches are dropped (optional)
Adapter contracts are in opscenter/DESIGN.md section 12.14. With no adapter configured the board still renders from
the feeds and the ledger; the calendar and scheduling parts report themselves unavailable.

Used by the server (live API) and by the refresh step (keeps the ledger current even when the board is not open).
"""

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from zoneinfo import ZoneInfo


def _params():
    state = Path(
        os.environ.get("OPSCENTER_STATE_DIR")
        or Path(os.environ.get("OPSCENTER_ROOT") or Path.home() / ".opscenter") / "state"
    )
    f = os.environ.get("OPSCENTER_PEOPLE_PARAMS") or str(state / "people-params.json")
    try:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


_P = _params()
ROOT = Path(os.environ.get("OPSCENTER_ROOT") or Path.home() / ".opscenter")
STATE = Path(os.environ.get("OPSCENTER_STATE_DIR") or ROOT / "state")
AGENT = Path(os.environ.get("OPSCENTER_AGENT_HOME") or ROOT / "agent")
DASH = STATE / "dashboard"
try:
    ET = ZoneInfo(
        str(_P.get("calendar_tz") or "UTC")
    )  # the calendar's wall clock zone (the name is historic)
except Exception:  # noqa: BLE001
    ET = ZoneInfo("UTC")
_FEEDS = _P.get("feeds") if isinstance(_P.get("feeds"), dict) else {}
CHAT_FEED = Path(_FEEDS.get("chat") or AGENT / "feeds" / "chat.json")
MAIL_FEED = Path(_FEEDS.get("mail") or AGENT / "feeds" / "mail.json")
TP_PATH = STATE / "team-performance" / "team-performance.json"
DR_RAW = Path(_P.get("roster_pull_file") or STATE / "team-performance" / "directreports_raw.json")
# Last good directory pull, written only by _write_roster_copy from a pull that parsed.
ROSTER_COPY = STATE / "dashboard" / "roster-last-pull.json"
AGENDA_PATH = DASH / "one-on-one-agenda.json"
LEDGER_PATH = DASH / "one-on-one-topics.json"
STATUS_PATH = DASH / "one-on-ones.json"
# The calendar and meetings slots: commands (lists), none by default. See DESIGN.md section 12.14.
CAL_CMD = [str(a) for a in _P["calendar_cmd"]] if isinstance(_P.get("calendar_cmd"), list) else None
GM_CMD = [str(a) for a in _P["meetings_cmd"]] if isinstance(_P.get("meetings_cmd"), list) else None
AC_PATH = DASH / "action-center.json"
AC_HANDLED_PATH = DASH / "action-handled.json"
SEEN_PATH = DASH / "one-on-one-seen.json"

ME = str(_P.get("owner_name") or "the owner")
MY_EMAIL = str(_P.get("owner_email") or "").lower()
MEETING_SUBJECT = str(_P.get("meeting_subject") or "{owner} and {first}: 1:1")


def _roster_from_params():
    out = []
    for r in _P.get("roster") if isinstance(_P.get("roster"), list) else []:
        if isinstance(r, dict) and r.get("name"):
            row = dict(r)
            row["name"] = str(r["name"])
            row["first"] = str(r.get("first") or str(r["name"]).split()[0])
            out.append(row)
    return out


# Board scope: the owner's direct reports and standing partners from the parameters. Nobody else is tracked.
ROSTER = _roster_from_params()
GROUP_ORDER = {"report": 0, "partner": 1}

THREAD_GAP = dt.timedelta(minutes=45)  # chat messages closer than this form one thread
AUTO_WINDOW = dt.timedelta(days=14)  # how far back feed-derived topics stay on the board
HANDLED_KEEP = dt.timedelta(days=7)  # how long covered topics stay visible
LEDGER_KEEP = dt.timedelta(days=int(_P.get("retention_days") or 45))  # ledger retention
HARVEST_TTL = 60  # seconds between live re-parses
CAL_TTL = 600  # seconds between calendar pulls
UP_TTL = 600  # seconds between 3-week calendar pulls
ONE_ON_ONE_DAYS = 21  # a booked 1:1 this far out hides the Schedule button
BOOK_GUARD = 90  # seconds: refuse a second booking for the same person

VALID_STATES = ("open", "discussed", "not_needed")
SOURCE_ORDER = {"agenda": 0, "action": 1, "me": 2, "review": 3, "teams": 4, "mail": 5}
PRIO_ORDER = {"P1": 0, "P2": 1, "P3": 2}
AC_PRIO = {"critical": "P1", "high": "P1", "medium": "P2", "low": "P3"}

ACK_RE = re.compile(
    r"^\W*(ok(ay)?|k+|thanks?( you| man| bro)?|thx|ty|no prob(lem)?|np|yep|yup|yes|yeah|ya|no|nope|"
    r"sure|cool|got it|sounds good|will do|done|lol|haha+|perfect|great|awesome|nice|bet|"
    r"for sure|appreciate it|gm|good morning|morning)\W*$",
    re.I,
)
SIGNAL_RE = re.compile(
    r"\?|\b(block(ed|er|ing)?|urgent|asap|issue|problem|broke|broken|breaking|fail(ed|ing|ure|s)?|"
    r"down|outage|error|stuck|help|need(s|ed)?|waiting|approv\w*|deadline|escalat\w*|risk|concern\w*|"
    r"can you|could you|should we|do we|how do|license\w*|ticket|priorit\w*|deploy\w*|rollout|"
    r"freeze|incident|complain\w*|fyi|heads.?up)\b",
    re.I,
)
# "down" only counts when something is down ("people down", "site is down"),
# not "keep costs down".
HOT_RE = re.compile(
    r"\b(urgent|asap|outage|(?:people|users?|site|server|system|service|everything|it|is|are|was|went|still)"
    r"\s+down|broken|breaking|blocked|escalat\w*|unacceptable)\b",
    re.I,
)
TICKET_RE = re.compile(str(_P.get("ticket_regex") or r"\b([A-Z][A-Z0-9]{1,9}-\d{2,6})\b"))
JIRA_URL_RE = re.compile(
    str(_P.get("ticket_url_regex") or r"https?://\S*?/browse/([A-Z][A-Z0-9]{1,9}-\d{2,6})\S*")
)
URL_RE = re.compile(r"https?://\S+")
MAIL_NOISE_SUBJ = re.compile(
    str(
        _P.get("mail_noise_regex")
        or r"^(accepted|declined|tentative|canceled|cancelled|automatic reply|out of office|new time proposed)\b"
    ),
    re.I,
)
# A partner posts team wide (channels, invites), so for the partner group only 1:1 chats and real mail
# threads count; standing meeting invites do not.
PARTNER_INVITE_SUBJ = re.compile(
    str(
        _P.get("partner_invite_regex")
        or r"^(refinement|sprint planning|planning|retro\w*|stand-?up|daily|weekly|sync)\b"
    ),
    re.I,
)
# Short threads that only schedule time ("what time slots do you have?").
SCHED_RE = re.compile(
    r"\b(time slots?|free now|im free|i'm free|after \d|got pushed|are you free|"
    r"available (today|tomorrow|now)|reschedul\w*)\b",
    re.I,
)
MAIL_PREFIX_RE = re.compile(r"^\s*((re|fw|fwd|aw)\s*:\s*|\*ext\*\s*|\[ext\]\s*)+", re.I)
CAUTION_RE = re.compile(
    r"CAUTION:\s*Use caution when clicking on links or opening attachments in this external email\.?",
    re.I,
)

_LOCK = threading.RLock()
_state: dict = {
    "harvest_at": 0.0,
    "cal_at": 0.0,
    "cal": None,
    "cal_error": None,
    "up_at": 0.0,
    "up": None,
    "up_error": None,
    "up_good_at": 0.0,
    "booked": {},
    "up_pending": [],
    "up_refreshing": False,
}


class ScheduleError(Exception):
    """Calendar helper failure. code 2 = the owner's calendar sign-in needs a refresh."""

    def __init__(self, msg, code=3):
        super().__init__(msg)
        self.code = code


# ---------------------------------------------------------------- helpers
def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(d):
    return d.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(s):
    if not s or not isinstance(s, str):
        return None
    try:
        s2 = s.strip().replace("Z", "+00:00")
        # Some calendars emit 7 fractional digits; Python accepts at most 6.
        s2 = re.sub(r"(\.\d{6})\d+", r"\1", s2)
        d = dt.datetime.fromisoformat(s2)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d
    except ValueError:
        return None


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")
    os.replace(tmp, path)


def _h(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:14]


def _clean(v):
    if v is None:
        return ""
    s = str(v)
    return "" if s == "None" else s


def _tidy(text):
    t = JIRA_URL_RE.sub(r"\1", _clean(text))
    t = URL_RE.sub("[link]", t)
    t = (
        t.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )
    t = t.replace("\u2014", ", ").replace("\u2013", "-").replace("\u2026", "...")
    return re.sub(r"\s+", " ", t).strip()


def _title_from(text, limit=130):
    t = _tidy(text)
    m = re.match(r"(.{30,%d}?[.!?])(\s|$)" % limit, t)  # noqa: UP031
    if m:
        return m.group(1).strip()
    return t if len(t) <= limit else t[: limit - 3].rstrip() + "..."


def _refs(text):
    seen = []
    for k in TICKET_RE.findall(_clean(text)):
        if k not in seen:
            seen.append(k)
    return seen[:8]


def _roster_digest(people):
    return hashlib.sha256(
        json.dumps(people, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _read_roster_pull():
    """Directory pull as {displayName: row}, or None when the pull failed (missing, unreadable,
    not a list, or none of the roster's people in it), with the pull time from the file."""
    try:
        raw = json.loads(Path(DR_RAW).read_text(encoding="utf-8"))
        pulled = _iso(dt.datetime.fromtimestamp(Path(DR_RAW).stat().st_mtime, dt.timezone.utc))
    except (OSError, ValueError):
        return None, None
    rows = raw.get("value", raw) if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return None, None
    by_name = {r.get("displayName"): r for r in rows if isinstance(r, dict)}
    if not any(p["name"] in by_name for p in ROSTER):
        return None, None
    return by_name, pulled


def _read_roster_copy():
    """People from the last-pull copy, or {} when it is missing or its digest does not match
    (a copy edited by hand is never read)."""
    doc = _load(ROSTER_COPY, {})
    people = doc.get("people") if isinstance(doc, dict) else None
    if not isinstance(people, dict) or doc.get("digest") != _roster_digest(people):
        return {}
    return people


def _write_roster_copy(entries):
    """Merge entries taken from a successful pull into the copy. This is the only writer."""
    people = dict(_read_roster_copy())
    if all(people.get(k) == v for k, v in entries.items()):
        return
    people.update(entries)
    try:  # noqa: SIM105
        _save(
            ROSTER_COPY,
            {"source": "directreports pull", "people": people, "digest": _roster_digest(people)},
        )
    except OSError:
        pass  # the board still renders from the pull, the copy is only a fallback


def roster_state():
    """(people, meta). Each person's title and email come from the directory pull when it
    succeeded and from the last-pull copy only when it did not. meta says what the board shows:
    stale (any value came from the copy), as_of (oldest copy time used), names (who),
    missing (people with no directory value at all)."""
    by_name, pulled = _read_roster_pull()
    copy = _read_roster_copy()
    if by_name is not None:
        fresh = {}
        for p in ROSTER:
            g = by_name.get(p["name"])
            if g and (g.get("jobTitle") or g.get("mail")):
                fresh[p["name"]] = {
                    "title": g.get("jobTitle") or "",
                    "email": (g.get("mail") or "").lower(),
                    "pulled": pulled,
                }
        if fresh:
            _write_roster_copy(fresh)
            copy = {**copy, **fresh}
    out, stale_names, missing, ages = [], [], [], []
    for p in ROSTER:
        g = (by_name or {}).get(p["name"]) or {}
        c = copy.get(p["name"]) or {}
        title = g.get("jobTitle") or c.get("title") or p.get("title") or ""
        email = (g.get("mail") or c.get("email") or p.get("email") or "").lower()
        from_copy = (not g.get("jobTitle") and bool(c.get("title"))) or (
            not g.get("mail") and bool(c.get("email"))
        )
        if from_copy and not p.get("title") and not p.get("email"):
            stale_names.append(p["name"])
            ages.append(c.get("pulled") or "")
        elif not title and not email:
            missing.append(p["name"])
        out.append({**p, "group": p.get("group", "report"), "title": title, "email": email})
    meta = {
        "stale": bool(stale_names),
        "as_of": (min(ages) or None) if ages else None,
        "names": stale_names,
        "missing": missing,
        "pull_ok": by_name is not None,
    }
    return out, meta


def roster():
    """ROSTER with title and mail from the directory pull, else the last-pull copy."""
    return roster_state()[0]


def _who(name, people):
    n = _clean(name).strip().lower()
    for p in people:
        if n == p["name"].lower():
            return p["name"]
    return None


# ---------------------------------------------------------------- harvesters
def _harvest_teams(people):
    feed = _load(CHAT_FEED, {})
    items = []
    for x in feed.get("items", []):
        ts = _parse_ts(x.get("created")) if isinstance(x, dict) else None
        if ts is not None:
            items.append({**x, "_t": ts})
    items.sort(key=lambda x: x["_t"])
    by_chat = {}
    for x in items:
        by_chat.setdefault(
            _clean(x.get("chat_id")) or ("ch:" + _clean(x.get("channel"))), []
        ).append(x)

    partners = {p["name"] for p in people if p.get("group") == "partner"}
    topics = []
    for chat_id, msgs in by_chat.items():
        authors = {_who(m.get("from_name"), people) for m in msgs} - {None}
        if not authors:
            continue
        chat_type = _clean(msgs[0].get("chat_type")) or _clean(msgs[0].get("surface"))
        names = {_clean(m.get("from_name")) for m in msgs}
        one_on_one = chat_type == "oneOnOne" and names <= ({ME} | authors) and len(authors) == 1
        # split the chat into threads on time gaps
        threads, cur, last = [], [], None
        for m in msgs:
            t = m["_t"]
            if cur and last is not None and t - last > THREAD_GAP:
                threads.append(cur)
                cur = []
            cur.append(m)
            last = t
        if cur:
            threads.append(cur)
        for th in threads:
            for person in authors:
                if person in partners and not one_on_one:
                    continue
                mine = [m for m in th if _who(m.get("from_name"), people) == person]
                if not mine:
                    continue
                text = " ".join(_tidy(m.get("text")) for m in mine)
                if len(text) < 160 and SCHED_RE.search(text) and not TICKET_RE.search(text):
                    continue
                substantive = [m for m in mine if not ACK_RE.match(_tidy(m.get("text")) or "ok")]
                if not substantive:
                    continue
                if one_on_one:
                    if len(text) < 50 and not SIGNAL_RE.search(text):
                        continue
                    keep = th
                else:
                    # shared chats: only what the report said, and only with a signal
                    if not SIGNAL_RE.search(text) or len(text) < 30:
                        continue
                    keep = mine
                lead = next(
                    (
                        m
                        for m in substantive
                        if len(_tidy(m.get("text"))) >= 40
                        and SIGNAL_RE.search(_tidy(m.get("text")))
                    ),
                    max(substantive, key=lambda m: len(_tidy(m.get("text")))),
                )
                label = ""
                if not one_on_one:
                    label = (
                        _clean(msgs[0].get("chat_topic"))
                        or _clean(msgs[0].get("channel"))
                        or (
                            "group chat"
                            if chat_type == "group"
                            else "meeting chat"
                            if chat_type == "meeting"
                            else "channel"
                        )
                    )
                topics.append(
                    {
                        "fp": "tm:" + _h(chat_id, keep[0].get("id"), person),
                        "person": person,
                        "source": "teams",
                        "kind": "1:1 chat" if one_on_one else label,
                        "title": _title_from(lead.get("text")),
                        "refs": _refs(" ".join(_clean(m.get("text")) for m in keep)),
                        "hot": bool(HOT_RE.search(text)),
                        "first_at": _iso(keep[0]["_t"]),
                        "last_at": _iso(mine[-1]["_t"]),
                        "messages": [
                            {
                                "id": _clean(m.get("id")),
                                "at": _iso(m["_t"]),
                                "who": "me"
                                if _clean(m.get("from_name")) == ME
                                else (
                                    "them"
                                    if _who(m.get("from_name"), people) == person
                                    else _clean(m.get("from_name"))
                                ),
                                "text": _tidy(m.get("text"))[:700],
                            }
                            for m in keep
                        ][-14:],
                        "link": _clean(lead.get("web_url")) or None,
                    }
                )
    return topics


def _harvest_mail(people):
    feed = _load(MAIL_FEED, {})
    emails = {p["email"]: p["name"] for p in people}
    partners = {p["name"] for p in people if p.get("group") == "partner"}
    convs = {}
    for x in feed.get("items", []):
        if not isinstance(x, dict):
            continue
        person = emails.get(_clean(x.get("from_addr")).lower()) or _who(x.get("from_name"), people)
        if not person:
            continue
        subj = _clean(x.get("subject"))
        if MAIL_NOISE_SUBJ.search(subj) or "noreply" in _clean(x.get("from_addr")).lower():
            continue
        if (
            person in partners
            and not MAIL_PREFIX_RE.match(subj)
            and PARTNER_INVITE_SUBJ.search(subj)
        ):
            continue
        t = _parse_ts(x.get("received"))
        if not t:
            continue
        key = (person, _clean(x.get("conversation_id")) or MAIL_PREFIX_RE.sub("", subj).lower())
        convs.setdefault(key, []).append((t, x))
    topics = []
    for (person, conv), rows in convs.items():
        rows.sort(key=lambda r: r[0])
        subj = MAIL_PREFIX_RE.sub("", _clean(rows[-1][1].get("subject"))).strip() or "(no subject)"
        body = " ".join(_tidy(CAUTION_RE.sub("", _clean(r[1].get("preview")))) for r in rows)
        topics.append(
            {
                "fp": "ml:" + _h(person, conv),
                "person": person,
                "source": "mail",
                "kind": "email" + (f" ({len(rows)})" if len(rows) > 1 else ""),
                "title": _tidy(subj)[:140],
                "refs": _refs(subj + " " + body),
                "hot": bool(HOT_RE.search(subj + " " + body)),
                "first_at": _iso(rows[0][0]),
                "last_at": _iso(rows[-1][0]),
                "messages": [
                    {
                        "id": _clean(r[1].get("id"))[-24:],
                        "at": _iso(r[0]),
                        "who": "them",
                        "text": _tidy(CAUTION_RE.sub("", _clean(r[1].get("preview"))))[:700],
                    }
                    for r in rows
                ][-10:],
                "link": _clean(rows[-1][1].get("web_link")) or None,
            }
        )
    return topics


def harvest(force=False):
    """Merge fresh feed-derived topics into the ledger. Idempotent, cheap."""
    with _LOCK:
        if not force and time.time() - _state["harvest_at"] < HARVEST_TTL:
            return
        people = roster()
        ledger = _load(LEDGER_PATH, {"topics": {}})
        topics = ledger.setdefault("topics", {})
        msg_index = {}
        for fp, t in topics.items():
            for m in t.get("messages", []):
                if m.get("id"):
                    msg_index[(t.get("person"), m["id"])] = fp
        for t in _harvest_teams(people) + _harvest_mail(people):
            # A thread can re-split when the feed window drops its first message;
            # fold it back into the topic that already owns any of its messages.
            owner = next(
                (
                    msg_index[(t["person"], m["id"])]
                    for m in t["messages"]
                    if m.get("id") and (t["person"], m["id"]) in msg_index
                ),
                None,
            )
            fp = owner or t["fp"]
            prev = topics.get(fp)
            if prev:
                ids = {m.get("id") for m in prev.get("messages", [])}
                merged = prev.get("messages", []) + [
                    m for m in t["messages"] if m.get("id") not in ids
                ]
                merged.sort(key=lambda m: m.get("at") or "")
                t = {
                    **prev,
                    **{k: t[k] for k in ("refs", "hot", "link", "kind")},
                    "fp": fp,
                    "first_at": min(prev.get("first_at") or t["first_at"], t["first_at"]),
                    "last_at": max(prev.get("last_at") or t["last_at"], t["last_at"]),
                    "messages": merged[-14:],
                }
                if not prev.get("title_locked"):
                    t["title"] = prev.get("title") or t["title"]
            topics[fp] = t
            for m in t["messages"]:
                if m.get("id"):
                    msg_index[(t["person"], m["id"])] = fp
        cutoff = _iso(_now() - LEDGER_KEEP)
        ledger["topics"] = {k: v for k, v in topics.items() if (v.get("last_at") or "") >= cutoff}
        ledger["updated"] = _iso(_now())
        _save(LEDGER_PATH, ledger)
        _state["harvest_at"] = time.time()


# ---------------------------------------------------------------- calendar
def _calendar():
    with _LOCK:
        if _state["cal"] is not None and time.time() - _state["cal_at"] < CAL_TTL:
            return _state["cal"]
    events, err = [], None
    if not CAL_CMD:
        err = "calendar slot not configured"
    else:
        try:
            r = subprocess.run(CAL_CMD, capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                data = json.loads(r.stdout or "[]")
                events = data if isinstance(data, list) else data.get("value", [])
            else:
                err = (r.stderr or r.stdout or "calendar exit %d" % r.returncode)[-200:]  # noqa: UP031
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            err = str(exc)[:200]

    def _wall(ev, k):
        v = ev.get(k)
        d = _parse_ts(v.get("dateTime")) if isinstance(v, dict) else None
        # The calendar returns wall clock time in calendar_tz with no offset.
        return d.replace(tzinfo=ET) if d else None

    out = []
    for ev in events:
        if not isinstance(ev, dict) or ev.get("isCancelled"):
            continue
        start, end = _wall(ev, "start"), _wall(ev, "end")
        if not start:
            continue
        att = [
            ((a.get("emailAddress") or {}).get("address") or "").lower()
            for a in (ev.get("attendees") or [])
            if isinstance(a, dict)
        ]
        out.append(
            {
                "subject": _clean(ev.get("subject")),
                "start": start.isoformat(),
                "end": end.isoformat() if end else None,
                "attendees": att,
                "link": _clean((ev.get("onlineMeeting") or {}).get("joinUrl"))
                or _clean(ev.get("webLink"))
                or None,
            }
        )
    with _LOCK:
        if err and _state["cal"] is not None:
            out = _state["cal"]  # keep the last good pull on a transient failure
        _state.update(cal=out, cal_at=time.time(), cal_error=err)
    return out


def _meeting_for(person, events):
    first = re.escape(person["first"])
    for e in events:
        subj = e["subject"]
        if (
            person["email"] in e["attendees"]
            or re.search(r"\(\s*%s\b[^)]*\)" % first, subj, re.I)  # noqa: UP031
            or (
                re.search(r"\b(1:1|1on1|one on one|catch.?up)\b", subj, re.I)
                and re.search(r"\b%s\b" % first, subj, re.I)  # noqa: UP031
            )
        ):
            return {k: e[k] for k in ("subject", "start", "end", "link")}
    return None


# ---------------------------------------------------------------- 3-week calendar + scheduling
ONE_RE = re.compile(r"\b(1:1|1on1|1-on-1|one on one|catch.?up|check.?in)\b", re.I)
_BOOK_LOCK = threading.Lock()


def _gm(args, payload=None, timeout=90):
    """Run the meetings slot command (GM_CMD plus the arguments); the last stdout line is the JSON result.
    Exit codes: 0 ok, 2 sign-in needs a refresh, 3 service error, 4 bad input. An error prints {"error": ...}."""
    if not GM_CMD:
        raise ScheduleError("meetings slot not configured", 4)
    try:
        r = subprocess.run(
            GM_CMD + list(args),
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise ScheduleError("calendar helper timed out") from None
    except OSError as exc:
        raise ScheduleError("calendar helper did not start: %s" % exc) from None  # noqa: UP031
    out = (r.stdout or "").strip()
    try:
        data = json.loads(out.splitlines()[-1]) if out else {}
    except ValueError:
        data = {}
    if r.returncode != 0 or not isinstance(data, dict) or "error" in data:
        msg = (
            (data.get("error") if isinstance(data, dict) else None)
            or (r.stderr or "").strip()[-300:]
            or "calendar helper exit %d" % r.returncode  # noqa: UP031
        )
        raise ScheduleError(msg, r.returncode if r.returncode in (2, 4) else 3)
    return data


def _pull_upcoming():
    try:
        events, err = (
            _gm(["upcoming", "--days", str(ONE_ON_ONE_DAYS)], timeout=60).get("events") or [],
            None,
        )
    except ScheduleError as exc:
        events, err = None, str(exc)[:200]
    with _LOCK:
        if events is not None:
            # Keep meetings the owner just booked until the calendar returns them on its own.
            ids = {e.get("id") for e in events}
            pending = [
                e
                for e in _state["up_pending"]
                if e.get("id") not in ids and time.time() - e.get("_at", 0) < 900
            ]
            _state.update(up=events + pending, up_pending=pending, up_good_at=time.time())
        _state.update(up_at=time.time(), up_error=err, up_refreshing=False)


def _upcoming():
    """The owner's calendar from now through ONE_ON_ONE_DAYS out; None until the first good pull.
    Stale data is served while a background refresh runs, so the board stays fast."""
    with _LOCK:
        ttl = UP_TTL if _state["up_error"] is None else 60
        have = _state["up"] is not None
        if time.time() - _state["up_at"] < ttl or (have and _state["up_refreshing"]):
            return _state["up"]
        if have:
            _state["up_refreshing"] = True
    if have:
        threading.Thread(target=_pull_upcoming, daemon=True).start()
    else:
        _pull_upcoming()
    with _LOCK:
        return _state["up"]


def _is_one_on_one(person, ev):
    """Me plus exactly this person (rooms excluded), or a small invite whose subject reads as their 1:1."""
    if ev.get("cancelled") or ev.get("response") == "declined":
        return False
    others = set(ev.get("attendees") or [])
    if ev.get("organizer"):
        others.add(ev["organizer"])
    others.discard(MY_EMAIL)
    others.discard("")
    email = person["email"]
    if others == {email}:
        return True
    subj = ev.get("subject") or ""
    return (
        email in others
        and len(others) <= 2
        and bool(ONE_RE.search(subj))
        and bool(re.search(r"\b%s\b" % re.escape(person["first"]), subj, re.I))  # noqa: UP031
    )


def _next_one_on_one(person, events, now):
    if events is None:
        return None
    horizon = now + dt.timedelta(days=ONE_ON_ONE_DAYS)
    for e in sorted(events, key=lambda e: _parse_ts(e.get("start")) or now):
        s, en = _parse_ts(e.get("start")), _parse_ts(e.get("end"))
        if not s or (en or s) <= now or s > horizon or not _is_one_on_one(person, e):
            continue
        return {
            "subject": e.get("subject") or "",
            "start": e.get("start"),
            "end": e.get("end"),
            "link": e.get("link"),
        }
    return None


def _person(name):
    want = str(name or "").strip().lower()
    for p in roster():
        if want and want in (p["name"].lower(), p["first"].lower()):
            if not p["email"]:
                raise ValueError("no directory address for this person yet")
            return p
    raise ValueError("unknown person")


def availability(name, minutes: "int | str" = 30):
    """Free/busy for me and the person over the next two weeks, with suggested slots."""
    p = _person(name)
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        raise ValueError("minutes must be a number")  # noqa: B904
    if minutes not in (15, 30, 45, 60):
        raise ValueError("minutes must be 15, 30, 45 or 60")
    data = _gm(
        ["availability", "--email", p["email"], "--days", "14", "--minutes", str(minutes)],
        timeout=60,
    )
    return {
        "person": p["name"],
        "first": p["first"],
        "email": p["email"],
        "subject": MEETING_SUBJECT.format(owner=ME, first=p["first"], name=p["name"]),
        "next_1on1": _next_one_on_one(p, _upcoming(), _now()),
        **data,
    }


def schedule(payload):
    """Create the 1:1 invite (subject from meeting_subject) as an online meeting with transcription on.
    The invite goes out to the person immediately; the agenda is the invite body."""
    if not isinstance(payload, dict):
        raise ValueError("object required")
    p = _person(payload.get("person"))
    start = str(payload.get("start") or "")
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", start):
        raise ValueError("start must be YYYY-MM-DDTHH:MM in the calendar zone")
    try:
        minutes = int(payload.get("minutes") or 30)
    except (TypeError, ValueError):
        raise ValueError("minutes must be a number")  # noqa: B904
    if minutes not in (15, 30, 45, 60):
        raise ValueError("minutes must be 15, 30, 45 or 60")
    raw = payload.get("agenda") or []
    if not isinstance(raw, list):
        raise ValueError("agenda must be a list of lines")
    agenda = []
    for line in raw[:40]:
        t = re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", _tidy(line)).strip()[:300]
        if t:
            agenda.append(t)
    dry, self_test = bool(payload.get("what_if")), bool(payload.get("self_test"))
    req = {
        "email": p["email"],
        "first": p["first"],
        "name": p["name"],
        "start": start,
        "minutes": minutes,
        "agenda": agenda,
        "auto_transcribe": bool(payload.get("auto_transcribe", True)),
        "what_if": dry,
        "no_attendee": self_test,
    }
    with _BOOK_LOCK:
        last = _state["booked"].get(p["name"])
        if not (dry or self_test) and last and time.time() - last < BOOK_GUARD:
            raise ValueError(
                "a 1:1 with %s was just booked; refresh before booking another" % p["first"]  # noqa: UP031
            )  # noqa: UP031
        res = _gm(["create"], payload=req, timeout=120)
        if dry:
            return res
        now = time.time()
        with _LOCK:
            if not self_test:
                _state["booked"][p["name"]] = now
                ev = {
                    "id": res.get("id"),
                    "subject": res.get("subject"),
                    "start": res.get("start"),
                    "end": res.get("end"),
                    "attendees": [p["email"]],
                    "organizer": MY_EMAIL,
                    "is_organizer": True,
                    "response": "organizer",
                    "cancelled": False,
                    "link": res.get("join_url"),
                    "_at": now,
                }
                _state["up_pending"].append(ev)
                if _state["up"] is not None:
                    _state["up"] = _state["up"] + [ev]
            store = _status_store()
            store.setdefault("scheduled", []).append(
                {
                    "person": p["name"],
                    "subject": res.get("subject"),
                    "start": res.get("start"),
                    "minutes": minutes,
                    "agenda_items": len(agenda),
                    "event_id": res.get("id"),
                    "transcription": (res.get("transcription") or {}).get("applied"),
                    "self_test": self_test,
                    "at": _iso(_now()),
                }
            )
            store["scheduled"] = store["scheduled"][-50:]
            _save(STATUS_PATH, store)
    return res


# ---------------------------------------------------------------- monitor-flagged items
def _owners(owner, people):
    """'A Name / B Name' -> roster names, in order."""
    out = []
    for part in re.split(r"\s*(?:/|,|&|\+|\band\b)\s*", str(owner or "")):
        part = part.strip()
        if not part:
            continue
        for p in people:
            last = p["name"].split()[-1]
            if p["name"] not in out and (
                part.lower() == p["name"].lower()
                or re.search(r"\b%s\b" % re.escape(last), part, re.I)  # noqa: UP031
            ):
                out.append(p["name"])
    return out


# ---------------------------------------------------------------- action link
# Agenda items carrying my_action also live on the Action Center (key
# "oo-<agenda id>"). Resolving there marks the 1:1 item done-but-untold; it closes
# itself once the owner has written to that person after the resolve, else the owner closes it
# in the 1:1. Marking the 1:1 item Not needed drops the Action Center twin. A card whose
# person the owner already wrote to about it (after the card's topic date) leaves the Action Center
# as Replied, and an item that flags no decision owed never raises one.
LINK_SINCE = "2026-10-06T00:00:00Z"
AGENDA_AC_PRIO = {"P1": "high", "P2": "medium", "P3": "low"}


def _board_fingerprint():
    """The board's own fingerprint function (engine/board_build.py ac_fingerprint, the single definition, so ids match
    the Action Center's), or None when the board composer is not in the tree."""
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "board_build_fp",
            str(Path(__file__).resolve().parent.parent / "engine" / "board_build.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.ac_fingerprint
    except Exception:  # noqa: BLE001
        return None


def _agenda_ac_fp(agenda_id):
    fn = _board_fingerprint()
    return fn({"key": "oo-" + agenda_id}) if fn else "ac_" + _h("oo-" + agenda_id)


# An agenda item says no decision is owed with decision_owed: false, or with this wording in
# my_action. Such an item is an acknowledge-at-the-1:1 note and never raises a card.
NO_DECISION_RE = re.compile(
    r"\b(no decision (is |was )?(owed|needed|required)|just acknowledge|nothing (is )?owed)\b", re.I
)
REPLIED_MIN_PHRASE = (
    4  # shorter match phrases (san, err, tog) hit unrelated chat, so they never count as a reply
)


def no_decision_owed(a):
    """True when the agenda item flags that nothing is owed beyond an acknowledgement."""
    if a.get("decision_owed") is False or a.get("no_decision") is True:
        return True
    return bool(NO_DECISION_RE.search(a.get("my_action") or ""))


def _agenda_since(a, reopened_at=None):
    """The card's topic date (the board's own first_at for an agenda item), or the moment the owner
    reopened it when that is later."""
    added = a.get("added") or ""
    base = added + "T12:00:00Z" if added else ""
    return max(base, reopened_at or "")


def _phrase_rx(a):
    phrases = [
        p.strip()
        for p in (a.get("match") or [])
        if isinstance(p, str) and len(p.strip()) >= REPLIED_MIN_PHRASE
    ]
    if not phrases:
        return None
    return re.compile(r"\b(" + "|".join(re.escape(p) for p in phrases) + r")\b", re.I)


def agenda_cards():
    """Every agenda item that carries my_action with the state of its Action Center card.

    state: open (raises a card), replied (the owner already wrote to that person about it after the
    card's topic date, reopenable), no_decision (flagged nothing owed, never a card) or
    not_needed (the owner closed it on the 1:1 board). Replied is computed from the chat and mail
    ledger every time, so it needs no stored state. Reopen stores a time and only a message
    written after it counts as a reply again."""
    agenda = _load(AGENDA_PATH, {"items": []})
    store = _status_store()
    status, reopen = store["status"], store.get("ac_reopen") or {}
    ledger = _load(LEDGER_PATH, {"topics": {}})
    out = []
    for a in agenda.get("items", []):
        act = (a.get("my_action") or "").strip()
        if not act:
            continue
        card = {"item": a, "state": "open", "replied_at": None}
        if (status.get("ag:" + a["id"]) or {}).get("state") == "not_needed":
            card["state"] = "not_needed"
        elif no_decision_owed(a):
            card["state"] = "no_decision"
        else:
            told = _told_after(
                a.get("person"),
                _agenda_since(a, reopen.get(a["id"])),
                a.get("refs"),
                _phrase_rx(a),
                ledger,
                None,
            )
            if told:
                card["state"], card["replied_at"] = "replied", told
        out.append(card)
    return out


def agenda_action_items():
    """Action Center items for the owner's open agenda actions (consumed by bundle_data). A replied,
    no-decision or not-needed item is left out. Replied ones stay reachable through
    agenda_replied_items so one click reopens them."""
    firsts = {p["name"]: p.get("first") for p in roster()}
    out = []
    for c in agenda_cards():
        if c["state"] != "open":
            continue
        a = c["item"]
        act = (a.get("my_action") or "").strip()
        first = firsts.get(a.get("person")) or (a.get("person") or "").split(" ")[0]
        out.append(
            {
                "key": "oo-" + a["id"],
                "priority": AGENDA_AC_PRIO.get(a.get("priority") or "", "medium"),
                "title": a.get("title", ""),
                "why": _tidy(a.get("detail", ""))[:600],
                "action": act,
                "owner": "",
                "refs": a.get("refs", []),
                "sources": ["1:1 agenda"],
                "one_on_one": {"person": a.get("person"), "first": first, "id": a["id"]},
            }
        )
    return out


def agenda_replied_items():
    """The cards that left the Action Center because the owner already replied (small Replied chips)."""
    firsts = {p["name"]: p.get("first") for p in roster()}
    out = []
    for c in agenda_cards():
        if c["state"] != "replied":
            continue
        a = c["item"]
        out.append(
            {
                "id": a["id"],
                "key": "oo-" + a["id"],
                "person": a.get("person"),
                "first": firsts.get(a.get("person")) or (a.get("person") or "").split(" ")[0],
                "title": a.get("title", ""),
                "replied_at": c["replied_at"],
            }
        )
    out.sort(key=lambda r: r["replied_at"] or "", reverse=True)
    return out


def reopen_replied(agenda_id):
    """Put a replied card back on the Action Center. Only a reply after this moment closes it again."""
    ids = {a.get("id") for a in _load(AGENDA_PATH, {"items": []}).get("items", [])}
    if agenda_id not in ids:
        raise ValueError("unknown agenda item")
    with _LOCK:
        store = _status_store()
        store.setdefault("ac_reopen", {})[agenda_id] = _iso(_now())
        _save(STATUS_PATH, store)
    return store["ac_reopen"][agenda_id]


def _told_after(person, since, refs, rx, ledger, absorbed):
    """When the owner last wrote to this person about it after `since` (absorbed thread
    evidence, or any of the owner's messages naming the ticket or a match phrase)."""
    best = ""
    for m in absorbed or []:
        if m.get("who") == "me" and (m.get("at") or "") > since:
            best = max(best, m["at"])
    refs = [r.upper() for r in refs or []]
    for t in ledger.get("topics", {}).values():
        if t.get("person") != person:
            continue
        for m in t.get("messages", []):
            if m.get("who") != "me" or (m.get("at") or "") <= since:
                continue
            text = m.get("text") or ""
            if any(r in text.upper() for r in refs) or (rx and rx.search(text)):
                best = max(best, m["at"])
    return best or None


def _action_topics(people, now):
    """Action Center items owned by someone on the board. The Action Center run has
    already analyzed the chat and mail traffic, so these carry the why and the ask.
    A resolved item stays (marked done) until the owner has told that person; ignored
    items drop."""
    ac = _load(AC_PATH, {})
    items = [i for i in ac.get("items") or [] if isinstance(i, dict) and not i.get("one_on_one")]
    if not items:
        return []
    handled = (_load(AC_HANDLED_PATH, {}) or {}).get("handled") or {}
    ac_fingerprint = _board_fingerprint()  # must match the Action Center's own ids
    gen = ac.get("generated_utc")
    out = []
    with _LOCK:
        boot = not SEEN_PATH.exists()
        seen = _load(SEEN_PATH, {})
        changed = boot
        live_fps = set()
        for it in items:
            live_fps.add(
                ac_fingerprint(it)
                if ac_fingerprint
                else "ac_" + _h(it.get("key") or it.get("title"))
            )
        # Resolved items fall out of action-center.json on the next analysis run;
        # the handled store keeps a snapshot, so they stay on the 1:1 until told.
        for hfp, h in handled.items():
            snap = h.get("item") if isinstance(h, dict) else None
            if (
                h.get("act") == "resolved"
                and isinstance(snap, dict)
                and hfp not in live_fps
                and not snap.get("one_on_one")
                and (h.get("at") or "") >= max(_iso(now - dt.timedelta(days=21)), LINK_SINCE)
            ):
                items.append({**snap, "_fp": hfp})
        for it in items:
            acfp = it.get("_fp") or (
                ac_fingerprint(it)
                if ac_fingerprint
                else "ac_" + _h(it.get("key") or it.get("title"))
            )
            h = handled.get(acfp) or {}
            if h.get("act") in ("ignored", "ignored_forever"):
                continue  # the owner dismissed it; nothing to tell anyone
            level = str(it.get("priority") or "").lower()
            for name in _owners(it.get("owner"), people):
                fp = "ac:" + _h(name, acfp)
                if fp not in seen:
                    # First run: items already in the Action Center predate the board.
                    seen[fp], changed = ("2000-01-01T00:00:00Z" if boot else _iso(now)), True
                out.append(
                    {
                        "fp": fp,
                        "person": name,
                        "source": "action",
                        "kind": "flagged by monitor",
                        "title": _tidy(it.get("title"))[:220],
                        "detail": _tidy(it.get("action"))[:900],
                        "context": _tidy(it.get("why"))[:900],
                        "priority": AC_PRIO.get(level),
                        "refs": [str(r).upper() for r in it.get("refs") or [] if r][:8],
                        "first_at": seen[fp],
                        "last_at": gen,
                        "messages": [],
                        "hot": level == "critical",
                        "ac_fp": acfp,
                        "action_done_at": h.get("at") if h.get("act") == "resolved" else None,
                    }
                )
        live = {t["fp"] for t in out}
        cut = _iso(now - dt.timedelta(days=60))
        stale = [k for k, v in seen.items() if k not in live and (v or "") < cut]
        for k in stale:
            seen.pop(k, None)
        if changed or stale:
            _save(SEEN_PATH, seen)
    return out


# ---------------------------------------------------------------- board
def _status_store():
    s = _load(STATUS_PATH, {})
    s.setdefault("status", {})
    s.setdefault("manual", [])
    return s


def _absorb(into, t):
    """Attach a raw thread or a duplicate flag to the analyzed topic that covers it."""
    into.setdefault("related", []).append(t["fp"])
    if t.get("messages"):
        into["messages"] = sorted(
            into["messages"] + t["messages"], key=lambda m: m.get("at") or ""
        )[-20:]
    if not into.get("link") and t.get("link"):
        into["link"], into["link_source"] = t["link"], t.get("link_source") or t["source"]
    if t["source"] in ("teams", "mail"):
        into["feed_last_at"] = max(into.get("feed_last_at") or "", t.get("last_at") or "")
    else:
        into["flagged"] = True
        if t.get("action_done_at") and not into.get("action_done_at"):
            into["action_done_at"], into["ac_fp"] = t["action_done_at"], t.get("ac_fp")
        if not into.get("context") and t.get("context"):
            into["context"] = t["context"]
        if PRIO_ORDER.get(t.get("priority") or "", 3) < PRIO_ORDER.get(
            into.get("priority") or "", 3
        ):
            into["priority"] = t["priority"]
    into["hot"] = bool(into.get("hot") or t.get("hot"))


def board():
    """Full 1:1 Board payload for the API.

    Only analyzed topics are listed: the owner's curated agenda, Action Center items owned by
    someone on the board, weekly-assessment items, and topics the owner adds. Raw chat and mail
    threads never become topics on their own; a thread is attached as evidence to
    the analyzed topic it belongs to (shared ticket, or one of the agenda item's
    match phrases) and reopens that topic when they write again."""
    harvest()
    people, roster_meta = roster_state()
    names = {p["name"] for p in people}
    now = _now()
    store = _status_store()
    status = store["status"]
    ledger = _load(LEDGER_PATH, {"topics": {}})
    agenda = _load(AGENDA_PATH, {"items": []})
    tp = _load(TP_PATH, {})
    events = _calendar()
    upcoming = _upcoming()

    topics = []
    agenda_added = {}
    ac_handled = (_load(AC_HANDLED_PATH, {}) or {}).get("handled") or {}
    for a in agenda.get("items", []):
        if a.get("person") not in names:
            continue
        added = a.get("added") or ""
        agenda_added[a["person"]] = max(agenda_added.get(a["person"], ""), added)
        link = {}
        if a.get("my_action"):
            acfp = _agenda_ac_fp(a["id"])
            h = ac_handled.get(acfp) or {}
            link = {
                "my_action": a["my_action"],
                "ac_fp": acfp,
                "action_done_at": h.get("at") if h.get("act") == "resolved" else None,
            }
        topics.append(
            {
                "fp": "ag:" + a["id"],
                "person": a["person"],
                "source": "agenda",
                "kind": "agenda",
                "title": a.get("title", ""),
                "detail": a.get("detail", ""),
                "priority": a.get("priority"),
                "refs": a.get("refs", []),
                "first_at": added + "T12:00:00Z" if added else None,
                "last_at": added + "T12:00:00Z" if added else None,
                "messages": [],
                "hot": False,
                **link,
            }
        )
    # Weekly assessment action items. A curated agenda written after the
    # assessment ran has already absorbed that run's items for that person.
    tp_gen = (tp.get("generated_utc") or "")[:10]
    for person, items in (tp.get("action_items") or {}).items():
        if person not in names or (agenda_added.get(person, "") >= tp_gen and tp_gen):
            continue
        for a in items or []:
            topics.append(
                {
                    "fp": "rv:" + _h(person, a.get("title")),
                    "person": person,
                    "source": "review",
                    "kind": "weekly assessment",
                    "title": a.get("title", ""),
                    "detail": a.get("action", ""),
                    "priority": a.get("priority"),
                    "refs": _refs(a.get("title", "") + " " + a.get("action", "")),
                    "first_at": tp.get("generated_utc"),
                    "last_at": tp.get("generated_utc"),
                    "messages": [],
                    "hot": False,
                }
            )
    for m in store["manual"]:
        if m.get("person") in names:
            topics.append(
                {
                    "fp": m["fp"],
                    "person": m["person"],
                    "source": "me",
                    "kind": "added by me",
                    "title": m.get("title", ""),
                    "detail": m.get("detail", ""),
                    "priority": None,
                    "refs": _refs(m.get("title", "")),
                    "first_at": m.get("added"),
                    "last_at": m.get("added"),
                    "messages": [],
                    "hot": False,
                }
            )

    agenda_rx = {}
    for a in agenda.get("items", []):
        phrases = [p for p in (a.get("match") or []) if isinstance(p, str) and p.strip()]
        if phrases:
            agenda_rx["ag:" + a["id"]] = re.compile(
                r"\b(" + "|".join(re.escape(p.strip()) for p in phrases) + r")\b", re.I
            )

    def _home(t, hay, pool):
        """The analyzed topic that already covers t: shared ticket first, then match phrase."""
        mine = [a for a in pool if a["person"] == t["person"] and a["fp"] != t["fp"]]
        refs = set(t.get("refs") or [])
        for a in mine:
            if refs and refs & set(a.get("refs") or []):
                return a
        for a in mine:
            rx = agenda_rx.get(a["fp"])
            if rx and rx.search(hay):
                return a
        return None

    # Monitor-flagged items already on the owner's curated agenda fold into that item, unless
    # the flag first showed up after the owner closed that item (then it is new business).
    for t in _action_topics(people, now):
        home = _home(
            t,
            " ".join((t["title"], t["detail"], t.get("context") or "")),
            [a for a in topics if a["source"] == "agenda"],
        )
        closed_at = (status.get(home["fp"]) or {}).get("at") if home else None
        if home and not (closed_at and (t.get("first_at") or "") > closed_at):
            _absorb(home, t)
        else:
            topics.append(t)

    # Topics the owner decided never belong on the 1:1 board (excluded_title_regex, optional): none from an
    # analyzed source lists. Topics the owner adds by hand stay. Matched on the title only, so an item that just
    # mentions the subject in its detail survives.
    if _P.get("excluded_title_regex"):
        excl = re.compile(str(_P["excluded_title_regex"]), re.I)
        topics = [t for t in topics if t["source"] == "me" or not excl.search(t.get("title") or "")]

    # Raw threads are evidence only. Unmatched chatter is not a discussion topic.
    auto_cut = _iso(now - AUTO_WINDOW)
    heard_from = {}
    for t in ledger.get("topics", {}).values():
        if t.get("person") not in names:
            continue
        heard_from[t["person"]] = max(heard_from.get(t["person"], ""), t.get("last_at") or "")
        if (t.get("last_at") or "") < auto_cut:
            continue
        hay = t.get("title", "") + " " + " ".join(m.get("text", "") for m in t.get("messages", []))
        home = _home(t, hay, topics)
        if home:
            _absorb(home, t)

    handled_cut = _iso(now - HANDLED_KEEP)
    new_cut = _iso(now - dt.timedelta(hours=24))
    out_topics = []
    for t in topics:
        st = status.get(t["fp"]) or {}
        state = st.get("state", "open")
        reopened = False
        if state != "open" and t.get("feed_last_at") and t["feed_last_at"] > (st.get("at") or ""):
            state, reopened = "open", True  # they wrote again after the owner closed it
        told_at = None
        if t.get("action_done_at"):
            told_at = _told_after(
                t["person"],
                t["action_done_at"],
                t.get("refs"),
                agenda_rx.get(t["fp"]),
                ledger,
                t.get("messages"),
            )
            if state == "open" and told_at and not reopened:
                # Action done in the Action Center and the owner already told them: closes itself.
                state, st = (
                    "discussed",
                    {"at": told_at, "note": "Done and the owner told them in chat or mail"},
                )
        if state != "open" and (st.get("at") or "") < handled_cut:
            continue
        out_topics.append(
            {
                **t,
                "state": state,
                "state_at": st.get("at"),
                "note": st.get("note"),
                "reopened": reopened,
                "told_at": told_at,
            }
        )

    out_topics.sort(
        key=lambda t: (
            0 if t["state"] == "open" else 1,
            0 if t.get("hot") or t.get("reopened") else 1,
            PRIO_ORDER.get(t.get("priority") or "", 3),
            SOURCE_ORDER.get(t["source"], 9),
        )
    )
    out_people = []
    for p in people:
        mine = [t for t in out_topics if t["person"] == p["name"]]
        open_t = [t for t in mine if t["state"] == "open"]
        handled = sorted(
            [t for t in mine if t["state"] != "open"],
            key=lambda t: t.get("state_at") or "",
            reverse=True,
        )
        nxt = _next_one_on_one(p, upcoming, now)
        out_people.append(
            {
                **{k: p[k] for k in ("name", "first", "title", "email", "group")},
                "meeting": _meeting_for(p, events),
                "next_1on1": nxt,
                "schedule_needed": upcoming is not None and nxt is None,
                "last_contact": heard_from.get(p["name"]) or None,
                "counts": {
                    "open": len(open_t),
                    "discussed": sum(1 for t in handled if t["state"] == "discussed"),
                    "not_needed": sum(1 for t in handled if t["state"] == "not_needed"),
                    "new": sum(
                        1
                        for t in open_t
                        if t.get("reopened")
                        or (
                            t["source"] in ("action", "agenda")
                            and (t.get("first_at") or "") >= new_cut
                        )
                    ),
                },
                "topics": open_t + handled,
            }
        )
    out_people.sort(
        key=lambda p: (
            GROUP_ORDER.get(p["group"], 9),
            p["meeting"] is None,
            (p["meeting"] or {}).get("start") or "",
            [r["name"] for r in ROSTER].index(p["name"]),
        )
    )
    teams_feed = _load(CHAT_FEED, {})
    mail_feed = _load(MAIL_FEED, {})
    ac = _load(AC_PATH, {})
    return {
        "generated_utc": _iso(now),
        "people": out_people,
        "roster": roster_meta,
        "sources": {
            "teams_updated": teams_feed.get("updated"),
            "mail_updated": mail_feed.get("updated"),
            "assessment_utc": tp.get("generated_utc"),
            "agenda_items": len(agenda.get("items", [])),
            "action_center_utc": ac.get("generated_utc"),
            "calendar_ok": _state.get("cal_error") is None,
            "upcoming_ok": upcoming is not None and _state.get("up_error") is None,
            "one_on_one_days": ONE_ON_ONE_DAYS,
        },
    }


def set_status(fp, state, note=None):
    if state not in VALID_STATES or not isinstance(fp, str) or not fp or len(fp) > 80:
        raise ValueError("bad fp/state")
    with _LOCK:
        store = _status_store()
        if state == "open":
            store["status"].pop(fp, None)
        else:
            entry = {"state": state, "at": _iso(_now())}
            if note:
                entry["note"] = str(note)[:400]
            store["status"][fp] = entry
        _save(STATUS_PATH, store)
        return store["status"].get(fp, {"state": "open"})


def add_topic(person, title, detail=""):
    names = {p["name"] for p in ROSTER}
    title = _tidy(title)[:200]
    if person not in names or not title:
        raise ValueError("unknown person or empty title")
    with _LOCK:
        store = _status_store()
        fp = "mn:" + _h(person, title, time.time())
        store["manual"].append(
            {
                "fp": fp,
                "person": person,
                "title": title,
                "detail": _tidy(detail)[:600],
                "added": _iso(_now()),
            }
        )
        _save(STATUS_PATH, store)
        return fp


def remove_topic(fp):
    with _LOCK:
        store = _status_store()
        before = len(store["manual"])
        store["manual"] = [m for m in store["manual"] if m.get("fp") != fp]
        store["status"].pop(fp, None)
        _save(STATUS_PATH, store)
        return before != len(store["manual"])


if __name__ == "__main__":
    harvest(force=True)
    b = board()
    for p in b["people"]:
        print(
            f"{p['name']:<18} open={p['counts']['open']:<2} meeting={(p['meeting'] or {}).get('start')}"
        )
        for t in p["topics"][:12]:
            print(
                f"   [{t['source']:<6}] {t['state']:<10} {t.get('priority') or '  '} {t['title'][:90]}"
            )
