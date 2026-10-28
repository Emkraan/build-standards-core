"""
Deterministic match between board items and the owner's Resolve, Ignore and Snooze decisions.

Why: the analysis job re-derives a key for an item every run once the owner has handled it (the item leaves
previous_items, so the model has no key to reuse). Repeats came back under new keys, including RESOLVED
items, and an ignored ask came back as "[resurfaced: ...]" on a state note with no new message from its
sender. The prompt rule alone never held, so the match is code.

Rules (automation-safety 1.6, a dismissed item stays dismissed until its problem changes):
  - Every decision aliases: resolved (for RESOLVED_WINDOW_DAYS), ignored, ignored_forever and
    in-window snoozed.
  - The problem changed only when there is NEW SOURCE EVIDENCE: one of the item's source ids (cids)
    carries a message received after the owner's decision. Then the item shows as new. Model prose
    ("[resurfaced: ...]", a state note) is not evidence. ignored_forever never comes back.
  - When the evidence report cannot be read, resolved matches show (unknown never hides) and
    ignore and snooze matches stay hidden as before.
  - Deterministic items (oo-, auto-, file-, jira-, doc-) have stable keys and their own lifecycle, so
    they never alias.
  - Match order: same key, same primary ref, same sources (every cid of the item was already a cid of
    the decision and every ref already one of its refs, and only for an item that first reached the
    board after the owner's decision, so a second ask already on the board stays), then title
    similarity at or above TITLE_THRESHOLD. Ref and source matches also need topic_overlap >=
    TOPIC_MIN, because one ticket or one 1:1 thread carries unrelated asks and the model sometimes
    mis-cites them.
  - A matched item takes the handled fingerprint (fp) and keeps its own in fp_alias_of, so the app
    files it with that decision instead of showing it as new, and Restore still works.
"""

from __future__ import annotations

import datetime as dt
import re

ALIAS_ACTS = ("resolved", "ignored", "ignored_forever", "snoozed")
DETERMINISTIC_PREFIXES = ("oo-", "auto-", "file-", "jira-", "doc-")
TITLE_THRESHOLD = 0.7
TOPIC_MIN = 0.2
TITLE_WINDOW_DAYS = 30
RESOLVED_WINDOW_DAYS = 30
MIN_TOKENS = 3

# Words that carry status or tone, not the issue. The model changes these run to run.
STOP = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "into",
    "is",
    "it",
    "its",
    "the owner's",
    "no",
    "not",
    "now",
    "of",
    "on",
    "or",
    "our",
    "the",
    "to",
    "with",
    "still",
    "again",
    "yet",
    "new",
    "day",
    "days",
    "second",
    "third",
    "week",
    "weeks",
    "unconfirmed",
    "unresolved",
    "pending",
    "open",
    "needs",
    "need",
    "me",
    "i",
    "after",
    "before",
    "past",
    "since",
    "without",
    "any",
    "also",
    "same",
}


def _tokens(title: str) -> set:
    t = re.sub(r"[^a-z0-9 ]", " ", str(title or "").lower())
    return {w for w in t.split() if len(w) > 1 and w not in STOP and not w.isdigit()}


def title_similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if len(ta) < MIN_TOKENS or len(tb) < MIN_TOKENS:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _parse(ts):
    if not ts:
        return None
    try:
        d = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def _active(rec: dict, now: dt.datetime) -> bool:
    act = rec.get("act")
    if act not in ALIAS_ACTS:
        return False
    if act == "snoozed":
        until = _parse(rec.get("until"))
        return bool(until and until > now)
    if act == "resolved":
        at = _parse(rec.get("at"))
        return bool(at and (now - at).days <= RESOLVED_WINDOW_DAYS)
    return True


def _primary_ref(item: dict) -> str:
    refs = [str(r).upper().strip() for r in (item.get("refs") or []) if r]
    return refs[0] if refs else ""


def is_deterministic(item: dict) -> bool:
    return str(item.get("key") or "").strip().lower().startswith(DETERMINISTIC_PREFIXES)


def evidence_from_report(report: dict | None) -> dict | None:
    """{cid: newest received iso} from ac-routing-report.json considered_list. None when the
    report is missing or has no list, so callers can tell unknown from nothing new."""
    if not isinstance(report, dict) or not isinstance(report.get("considered_list"), list):
        return None
    out = {}
    for c in report["considered_list"]:
        cid, rcv = (c or {}).get("cid"), (c or {}).get("received")
        if cid and rcv and (cid not in out or str(rcv) > str(out[cid])):
            out[cid] = rcv
    return out


def has_new_evidence(item: dict, rec: dict, evidence: dict | None):
    """True when a source of the item got a message after the owner's decision, False when not,
    None when the evidence report is unreadable."""
    if evidence is None:
        return None
    at = _parse(rec.get("at"))
    if not at:
        return None
    for cid in item.get("cids") or []:
        rcv = _parse(evidence.get(cid))
        if rcv and rcv > at:
            return True
    return False


def topic_overlap(item: dict, snap: dict) -> float:
    """How much the two items talk about the same thing: the better of title plus key token
    overlap and why-text Jaccard. A ticket or a chat thread shared by two unrelated asks
    scores near zero (0.00 to 0.10 on the 10/14 to 10/16 board history), a reworded repeat
    0.27 and up."""

    def tk(x):
        return _tokens(
            "{} {}".format(x.get("title") or "", str(x.get("key") or "").replace("-", " "))
        )

    ta, tb = tk(item), tk(snap)
    t = len(ta & tb) / min(len(ta), len(tb)) if ta and tb else 0.0
    wa, wb = _tokens(item.get("why") or ""), _tokens(snap.get("why") or "")
    w = len(wa & wb) / len(wa | wb) if wa and wb else 0.0
    return max(t, w)


def _match_reason(item, rec, key, ref, cids, title, first_seen_at, now):
    snap = rec.get("item") or {}
    if key and str(snap.get("key") or "").strip().lower() == key:
        return "key", 1.0
    at = _parse(rec.get("at"))
    # Tickets and chat threads are shared by unrelated asks (the model also mis-cites them),
    # so a ref or source match also needs the two items to be about the same thing.
    if (ref and _primary_ref(snap) == ref) or cids:
        topic = topic_overlap(item, snap)
        if ref and _primary_ref(snap) == ref and topic >= TOPIC_MIN:
            return "ref", 1.0
        # Every source behind the item was already behind this decision, and every ticket the
        # item names was named there too (a subset, not one shared thread), and the item first
        # reached the board after the owner's decision (a second ask already on the board stays).
        refs = {str(r).upper().strip() for r in (item.get("refs") or []) if r}
        snap_refs = {str(r).upper().strip() for r in (snap.get("refs") or []) if r}
        same_sources = cids and cids <= set(snap.get("cids") or []) and refs <= snap_refs
        if (
            same_sources
            and topic >= TOPIC_MIN
            and at
            and (first_seen_at is None or first_seen_at >= at)
        ):
            return "source", 0.9
    if at and (now - at).days > TITLE_WINDOW_DAYS:
        return None, 0.0
    score = title_similarity(title, snap.get("title") or "")
    if score >= TITLE_THRESHOLD:
        return f"title {score:.2f}", score
    return None, 0.0


def find_match(item: dict, handled: dict, now=None, evidence=None, first_seen=None):
    """Return (fp, reason) of the decision this item repeats, else (None, None)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if is_deterministic(item):
        return None, None
    key = str(item.get("key") or "").strip().lower()
    ref = _primary_ref(item)
    cids = set(item.get("cids") or [])
    title = item.get("title") or ""
    first_seen_at = _parse((first_seen or {}).get(item.get("fp_alias_of") or item.get("fp")))
    best, best_reason, best_score, rank = None, None, 0.0, {"key": 3, "ref": 2, "source": 1}
    for fp, rec in handled.items():
        if not isinstance(rec, dict) or not _active(rec, now):
            continue
        reason, score = _match_reason(item, rec, key, ref, cids, title, first_seen_at, now)
        if not reason:
            continue
        if rec.get("act") != "ignored_forever":
            fresh = has_new_evidence(item, rec, evidence)
            if fresh:
                continue  # the conversation moved on after the owner's decision, show it
            if fresh is None and rec.get("act") == "resolved":
                continue  # unknown never hides a resolved repeat
        s = rank.get(reason, 0) + score
        if s > best_score:
            best, best_reason, best_score = fp, reason, s
    return (best, best_reason) if best else (None, None)


def alias_items(items: list, handled: dict, now=None, evidence=None, first_seen=None) -> list:
    """Re-point items that repeat a handled decision at that decision's fp.
    Items must already carry their own "fp". Returns [(old_fp, new_fp, reason)]."""
    out = []
    for it in items:
        fp = it.get("fp")
        if not fp or fp in handled:
            continue
        match, reason = find_match(it, handled, now, evidence, first_seen)
        if match and match != fp:
            it["fp_alias_of"] = fp
            it["fp"] = match
            out.append((fp, match, reason))
    return out


def compact_for_bundle(handled: dict, now=None, resolved_days: int = 14) -> dict:
    """The handled map the analysis reads: key and title per decision so it can reuse the key
    and recognise a reworded repeat, without the full why/action text of 190 records."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out = {}
    for fp, rec in handled.items():
        if not isinstance(rec, dict):
            continue
        act = rec.get("act")
        at = _parse(rec.get("at"))
        if act == "resolved" and at and (now - at).days > resolved_days:
            continue
        if act == "snoozed" and not _active(rec, now):
            continue
        snap = rec.get("item") or {}
        row = {"act": act, "at": rec.get("at")}
        for k in ("until",):
            if rec.get(k):
                row[k] = rec[k]
        for k in ("key", "title", "refs"):
            if snap.get(k):
                row[k] = snap[k]
        out[fp] = row
    return out
