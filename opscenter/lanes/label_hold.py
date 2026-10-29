"""why one of the owner's PRs sits on a hold label, and what still stands behind it.

The lane's reason for a label hold is only "label do-not-merge", so the owner's PRs card said nothing
about who placed the hold, why, or what clearing it would do. This module answers those three
from data we already have: the label event on the PR timeline, the newest decisions-log entry
that names the PR, and the live engine check plus the owner's triage markers for the head.

Pure helpers take their inputs as arguments so the tests run on synthetic data only.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import time
from pathlib import Path

import paths

try:
    from zoneinfo import ZoneInfo

    _ET = ZoneInfo(os.environ.get("OPSCENTER_TZ", "UTC"))  # the display zone (the name is historic)
except Exception:  # noqa: BLE001 - no tz database: fall back to UTC text
    _ET = None

HOLD_LABELS = tuple(
    x for x in os.environ.get("OPSCENTER_HOLD_LABELS", "do-not-merge").split(",") if x
)
OVERRIDE_LABEL = os.environ.get("OPSCENTER_OVERRIDE_LABEL", "ai-review-override")
LOG = Path(os.environ.get("OPRG_DECISIONS_LOG", str(paths.state_dir() / "decisions-log.md")))
EVENT_TTL_S = 600
_EVENTS = {}  # (pr, label) -> (epoch, event or None)
_NOTES = {}  # (path, mtime, pr) -> note or None
_LOCK = threading.Lock()

_TRIAGE_RE = re.compile(r"<!--\s*triage:([0-9a-fA-F]{7,40})((?:[\s,]+[HhBb]\d+)*)[\s,]*-->")
_TRIAGE_ID_RE = re.compile(r"[HhBb]\d+")
_AI_MARKER = "<!-- ai-review:v1 -->"
_ENTRY_SPLIT = re.compile(r"\n\s*\n|\n(?=(?:\*\*|- |#{2,3} )?20\d\d-\d\d-\d\d)")
_DATE = re.compile(r"(20\d\d-\d\d-\d\d)(?:[^\n\d]{0,4}(\d\d:\d\d))?")
_HOLD_WORDS = re.compile(r"do-not-merge|\bheld\b|\bhold\b", re.I)


def hold_label(labels):
    """The first hold label on the PR, or None."""
    for name in labels or []:
        if name in HOLD_LABELS:
            return name
    return None


def _clean(s):
    s = re.sub(r"[*`]", "", s)
    s = s.replace("\u2014", ",").replace("\u2013", "-").replace(";", ",")
    s = s.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s).strip()


def _sentences(s):
    return [x for x in re.split(r"(?<=[.!?])\s+(?=[A-Z(#])", s) if x]


def note_from_text(text, pr, limit=420):
    """{at, text} from the newest log entry naming the PR (entries with hold words win), or None."""
    ref = re.compile(rf"(?:#|\bPR\s*#?|\bpr\s+){int(pr)}\b")
    best = None
    for i, chunk in enumerate(_ENTRY_SPLIT.split(text or "")):
        if not ref.search(chunk):
            continue
        m = _DATE.search(chunk)
        if not m:
            continue
        rank = (1 if _HOLD_WORDS.search(chunk) else 0, m.group(1), m.group(2) or "", i)
        if best is None or rank > best[0]:
            best = (rank, chunk, m)
    if not best:
        return None
    _, chunk, m = best
    body = _clean(chunk[m.end() :].lstrip(" |-~UTC*"))
    sents = _sentences(body)
    hit = next((k for k, s in enumerate(sents) if ref.search(s)), 0)
    out = ""
    for s in sents[hit:]:
        if out and len(out) + len(s) + 1 > limit:
            break
        out = (out + " " + s).strip()
    if len(out) > limit:
        out = out[: limit - 3].rstrip() + "..."
    return {"at": m.group(1) + (f" {m.group(2)}" if m.group(2) else ""), "text": out}


def note_for(pr, path=None):
    """note_from_text over the decisions log, cached by file mtime. None on a read error."""
    p = Path(path or LOG)
    try:
        mt = p.stat().st_mtime
    except OSError:
        return None
    key = (str(p), mt, int(pr))
    with _LOCK:
        if key in _NOTES:
            return _NOTES[key]
    try:
        note = note_from_text(p.read_text(encoding="utf-8", errors="replace"), pr)
    except OSError:
        note = None
    with _LOCK:
        _NOTES[key] = note
    return note


def label_event(gh, repo, pr, label):
    """{actor, at} of the newest 'labeled' event for this label (cached 10 min). None on error."""
    key = (int(pr), label)
    with _LOCK:
        hit = _EVENTS.get(key)
    if hit and time.time() - hit[0] < EVENT_TTL_S:
        return hit[1]
    try:
        out = gh(
            [
                "api",
                "--paginate",
                f"repos/{repo}/issues/{pr}/events?per_page=100",
                "--jq",
                ".[] | @json",
            ],
            raw=True,
        )
    except Exception:  # noqa: BLE001 - the card still shows, without who and when
        return None
    ev = None
    for line in (out or "").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("event") == "labeled" and (e.get("label") or {}).get("name") == label:
            ev = {
                "actor": (e.get("actor") or {}).get("login") or "",
                "at": e.get("created_at") or "",
            }
    with _LOCK:
        _EVENTS[key] = (time.time(), ev)
    return ev


def forget(pr):
    with _LOCK:
        for k in [k for k in _EVENTS if k[0] == int(pr)]:
            _EVENTS.pop(k, None)


def triaged_from_comments(lines, head, self_login):
    """Finding ids the owner's triage markers name for this head, posted after the newest review comment
    for this head. Mirrors review_and_triage in the own-PR lane."""
    review_ts, mine = "", []
    for line in lines:
        if not line.strip():
            continue
        try:
            c = json.loads(line)
        except ValueError:
            continue
        body = c.get("body") or ""
        login = (c.get("user") or {}).get("login")
        ts = max(c.get("updated_at") or "", c.get("created_at") or "")
        if (
            login == "github-actions[bot]"
            and body.startswith(_AI_MARKER)
            and f"`{head[:7]}`" in body
        ):
            review_ts = max(review_ts, ts)
        elif login == self_login:
            ids = set()
            for m in _TRIAGE_RE.finditer(body):
                if head.startswith(m.group(1).lower()):
                    ids |= {x.upper() for x in _TRIAGE_ID_RE.findall(m.group(2) or "")}
            if ids:
                mine.append((c.get("created_at") or "", ids))
    return (
        set().union(*[ids for ts, ids in mine if review_ts and ts > review_ts]) if mine else set()
    )


def triaged_ids(gh, repo, pr, head, self_login):
    """None when the comments cannot be read (the card then says it could not check)."""
    try:
        out = gh(
            [
                "api",
                "--paginate",
                f"repos/{repo}/issues/{pr}/comments?per_page=100",
                "--jq",
                ".[] | @json",
            ],
            raw=True,
        )
    except Exception:  # noqa: BLE001
        return None
    return triaged_from_comments((out or "").splitlines(), head, self_login)


def comment_lines(gh, repo, pr):
    """The PR's issue comments as JSON lines, or None when they cannot be read."""
    try:
        out = gh(
            [
                "api",
                "--paginate",
                f"repos/{repo}/issues/{pr}/comments?per_page=100",
                "--jq",
                ".[] | @json",
            ],
            raw=True,
        )
    except Exception:  # noqa: BLE001
        return None
    return (out or "").splitlines()


def triage_replies(lines, head, self_login, limit=700):
    """The owner's triage replies for this head, oldest first: [{ids, text, at, after_review}]. text is the reply
    without the marker. after_review is true when it was posted after the newest review of this head,
    which is the only kind the lane counts. Used by the approval brief."""
    review_ts, mine = "", []
    for line in lines or []:
        if not line.strip():
            continue
        try:
            c = json.loads(line)
        except ValueError:
            continue
        body = c.get("body") or ""
        login = (c.get("user") or {}).get("login")
        ts = max(c.get("updated_at") or "", c.get("created_at") or "")
        if (
            login == "github-actions[bot]"
            and body.startswith(_AI_MARKER)
            and f"`{head[:7]}`" in body
        ):
            review_ts = max(review_ts, ts)
        elif login == self_login:
            ids = set()
            for m in _TRIAGE_RE.finditer(body):
                if head.startswith(m.group(1).lower()):
                    ids |= {x.upper() for x in _TRIAGE_ID_RE.findall(m.group(2) or "")}
            if ids:
                text = re.sub(r"\s+", " ", _TRIAGE_RE.sub("", body)).strip()
                mine.append(
                    {
                        "ids": sorted(ids, key=lambda x: (x[0], int(x[1:]))),
                        "text": text[:limit],
                        "at": c.get("created_at") or "",
                    }
                )
    for r in mine:
        r["after_review"] = bool(review_ts and r["at"] > review_ts)
    return sorted(mine, key=lambda r: r["at"])


def triage_context(gh, repo, pr, head, self_login, labels=None):
    """What the approval brief needs about a blocked review the owner answered: the owner's triage replies on this head and who
    applied ai-review-override and when. override is None when the label is not on (labels given) or the event
    cannot be read. None overall when nothing is known."""
    lines = comment_lines(gh, repo, pr)
    replies = triage_replies(lines, head, self_login) if lines is not None else []
    override = None
    if labels is None or OVERRIDE_LABEL in labels:
        override = label_event(gh, repo, pr, OVERRIDE_LABEL)
    if not replies and not override:
        return None
    return {"replies": replies, "override": override}


def _when(iso):
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return ""
    if _ET:
        t = t.astimezone(_ET)
        return f"{t.month}/{t.day} {t.strftime('%I:%M %p').lstrip('0')} {t.tzname()}"
    return f"{t.month}/{t.day} {t.strftime('%H:%M')} UTC"


def blocking_ids(item):
    """Blocking finding ids of the review on this head: B1..Bn from the verdict counts plus any blocking
    row of the findings table. Same set the own-PR lane requires the owner's triage to name (required_ids B)."""
    ids = {f"B{i}" for i in range(1, int((item.get("counts") or {}).get("blocking") or 0) + 1)}
    ids |= {
        str(f.get("id")).upper()
        for f in item.get("findings") or []
        if f.get("severity") == "blocking" and f.get("id")
    }
    return ids


def _id_key(x):
    return (x[0], int(x[1:]))


def accept_risk(item, triaged):
    """Can the owner accept the risk on this card: apply ai-review-override for blocking findings the owner's
    triage already answers on this exact head? Returns {ok, ids, missing, reason}. ok only when the
    review verdict for this head is blocked, there is at least one blocking id, the owner's triage names every
    one of them, and the override label is not on yet. triaged is None when the replies could not be read."""
    labels = item.get("labels") or []
    need = sorted(blocking_ids(item), key=_id_key)
    out = {"ok": False, "ids": need, "missing": [], "reason": ""}
    if item.get("verdict") != "blocked":
        out["reason"] = "the PR review for this head is not blocked"
    elif not need:
        out["reason"] = "the review lists no blocking findings"
    elif OVERRIDE_LABEL in labels:
        out["reason"] = f"{OVERRIDE_LABEL} is already on"
    elif triaged is None:
        out["reason"] = "the triage replies could not be read"
    else:
        out["missing"] = [i for i in need if i not in triaged]
        if out["missing"]:
            out["reason"] = f"my triage on this head does not name {', '.join(out['missing'])}"
        else:
            out["ok"] = True
    return out


def behind(item, check, triaged, covered=()):
    """What still holds the PR once the label is gone: list of {kind, text}. kind is 'problem'
    (needs a fix or a triage), 'signoff' (the owner's Approve and merge after the label) or 'unknown'."""
    out = []
    fids = [f.get("id") for f in item.get("findings") or [] if f.get("id")]
    if triaged is None and fids:
        out.append(
            {"kind": "unknown", "text": f"Could not read the triage replies for {', '.join(fids)}."}
        )
    elif fids:
        miss = [i for i in fids if i not in triaged]
        if miss:
            out.append(
                {
                    "kind": "problem",
                    "text": f"{', '.join(miss)} {'has' if len(miss) == 1 else 'have'} no triage reply on this head. "
                    "Triage findings answers them.",
                }
            )
    ar = accept_risk(item, triaged)
    if ar["ok"]:
        out.append(
            {
                "kind": "covered",
                "text": f"{', '.join(ar['ids'])} {'is' if len(ar['ids']) == 1 else 'are'} blocking and covered by my "
                f"triage on this head. Accept the risk applies {OVERRIDE_LABEL} for {'it' if len(ar['ids']) == 1 else 'them'}.",
            }
        )
    if not check:
        if item.get("red"):
            out.append(
                {
                    "kind": "unknown",
                    "text": f"{len(item['red'])} check(s) red ({', '.join(item['red'])[:160]}). "
                    "The live check has not read their cause yet.",
                }
            )
        return out
    ch = check.get("checks") or {}
    red = [k for k in ch.get("red") or [] if k not in set(covered)]
    if red and ch.get("destroy_guard_only"):
        out.append(
            {
                "kind": "signoff",
                "text": f"{', '.join(red)[:160]} {'fails' if len(red) == 1 else 'fail'} only on the destroy guard "
                "(the plan deletes resources). That is a sign-off, not a fix: Approve and merge shows once the "
                "label is off.",
            }
        )
    elif red:
        out.append({"kind": "problem", "text": f"Checks red: {', '.join(red)[:200]}."})
    if int(check.get("unresolved_threads") or 0):
        out.append(
            {
                "kind": "problem",
                "text": f"{check['unresolved_threads']} unresolved review thread(s).",
            }
        )
    if check.get("mergeable") == "CONFLICTING":
        out.append({"kind": "problem", "text": "Merge conflict with main."})
    rules = sorted({e.get("rule") or "?" for e in check.get("escalations") or []})
    if rules:
        out.append(
            {
                "kind": "signoff",
                "text": "Policy sign-off after the label: " + ", ".join(rules) + ".",
            }
        )
    return out


def describe(item, label, event, note, rest, self_login):
    """The label_hold block for the card plus summary and next lines."""
    who = ""
    if event:
        who = "you" if event.get("actor") == self_login else event.get("actor") or "someone"
        when = _when(event.get("at") or "")
        summary = f"Held on purpose: {who} added {label}" + (f" on {when}." if when else ".")
    else:
        summary = f"Held on purpose with {label}."
    problems = [r for r in rest if r["kind"] in ("problem", "unknown")]
    signoffs = [r for r in rest if r["kind"] == "signoff"]
    covered = [r for r in rest if r["kind"] == "covered"]
    if covered and not problems:
        nxt = (
            f"Accept the risk applies {OVERRIDE_LABEL} for the triaged blocking finding. "
            "Remove the label when it can go. The card then shows Approve and merge."
        )
    elif not rest:
        nxt = "Nothing else holds it. Remove the label when it can go and the lane merges it within 3 minutes."
    elif not problems:
        nxt = "Remove the label when it can go. The card then shows Approve and merge for the sign-off above."
    else:
        nxt = (
            "Removing the label alone will not merge it. Clear the items above first, "
            "or remove it now and the card shows the next hold."
        )
    block = {
        "label": label,
        "by": event.get("actor") if event else None,
        "at": event.get("at") if event else None,
        "why": note.get("text") if note else None,
        "why_at": note.get("at") if note else None,
        "behind": rest,
        "clear": not problems,
        "signoff_after": bool(signoffs),
    }
    return summary, nxt, block
