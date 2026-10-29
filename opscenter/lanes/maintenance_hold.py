"""
maintenance_hold.py
Purpose: The review pages' side of the maintenance-window hold.
         - held_cards(): the "Waiting for the maintenance window" cards (In progress tab) from the held-for-window
           file the engineer-PR lane and approve() below write.
         - need_view(): what an engineer PR's approval would do right now (held or not), for the Needs me card.
         - hold(): approve without enqueue, record the hold, post the one window comment.
         - override(): "Merge now (emergency override)" on a held card, pinned to the held head, reason required,
           recorded in the overrides sidecar and the decisions log.
         Window math and wording come from lanes/maintenance_window.py, the same module the lane uses, so the card
         and the lane always agree. The callers pass cfg_io (gh, repo, log, held_path, overrides_path, verify_head,
         set_queue, self_login); nothing here names a repo, a login or a path.
Date:    2026-10-15
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

import maintenance_window
import merge_queue

# Words a public comment must never carry (the consumer may extend the list with OPSCENTER_COMMENT_FORBIDDEN, a regex).
FORBIDDEN = re.compile(
    r"\bbot\b|\bAI\b|assistant|co-authored-by"
    + (
        "|" + os.environ["OPSCENTER_COMMENT_FORBIDDEN"]
        if os.environ.get("OPSCENTER_COMMENT_FORBIDDEN")
        else ""
    ),
    re.I,
)


class HoldError(Exception):
    def __init__(self, msg, code=409):
        super().__init__(msg)
        self.code = code
        self.status = code


def mw():
    return maintenance_window


def now_utc():
    v = os.environ.get("OPRG_NOW")
    if v:
        return dt.datetime.strptime(v[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


def _iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def _parse(s):
    try:
        return dt.datetime.strptime((s or "")[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=dt.timezone.utc
        )
    except ValueError:
        return None


def _load(p, default):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


def _save(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, p)


def _cfg(pol):
    return mw().cfg_of(pol)


def _sentence(s):
    s = (s or "").strip().rstrip(".")
    return (s[:1].upper() + s[1:] + ".") if s else ""


def window_view(pol, cls, hits, held_at=None, now=None):
    """Plain-prose view of one downtime change against its window."""
    m = mw()
    cfg = _cfg(pol)
    now = now or now_utc()
    cls = cls or "both"
    cur = m.current(cfg, cls, now)
    nxt = m.next_open(cfg, cls, now)
    label = m.class_label(cls)
    reasons = [h.get("reason") for h in hits or [] if h.get("reason")]
    down = (
        "Merging it "
        + ". It also ".join(reasons[:3])
        + (f", plus {len(reasons) - 3} more" if len(reasons) > 3 else "")
        + "."
        if reasons
        else "Merging it takes a production system down briefly."
    )
    cls_why = {
        "standard": f"It does not touch a restricted system, so it uses the standard window ({m.windows_words(cfg, 'standard')}).",
        "restricted": f"It touches a restricted system, so it uses the restricted window ({m.windows_words(cfg, 'restricted')}).",
        "both": "It could not tell which systems this touches, so it waits for a time when both the restricted and the standard windows are open.",
    }.get(cls, "")
    if cur:
        when = f"The {label} window is open now, until {m.when_words(cfg, cur[1], now)}, so the merge queue takes it on the next pass."
    elif nxt:
        when = f"It merges in the next {label} window, {m.when_words(cfg, nxt[0], now)}, as long as the head is unchanged and every check is still green."
    else:
        when = f"No {label} window is configured yet, so it stays held until one is or you override it."
    stale = bool(held_at and m.stale(cfg, cls, held_at, now))
    if stale:
        when += " A full window already passed and it is still here, so something stopped it. Check the last re-check below."
    return {
        "class": cls,
        "class_label": label,
        "in_window": bool(cur),
        "opens_utc": _iso(nxt[0]) if nxt else None,
        "opens_words": m.when_words(cfg, nxt[0], now) if nxt else None,
        "phrase": m.window_phrase(cfg, cls, now),
        "stale": stale,
        "reasons": reasons,
        "brief": {
            "down": down + " " + cls_why,
            "when": when,
            "override": (
                "Merge now (emergency override) is an emergency change. It queues the merge right away at this head, outside "
                "the window, and records your reason with the time. Use it only when the change cannot wait."
            ),
        },
    }


def need_view(pol, item, author, self_login, now=None):
    """For an engineer PR on Needs me: what Approve would do now. None when it would merge as usual."""
    if author == self_login or not _cfg(pol).get("enabled"):
        return None
    d = item.get("downtime")
    if not d:
        return None
    if d.get("unknown"):
        v = window_view(
            pol, "both", [{"reason": "it could not check what this change takes down"}], now=now
        )
        v["unknown"] = True
    elif not d.get("downtime"):
        return None
    else:
        v = window_view(pol, d.get("class"), d.get("hits"), now=now)
    v["held_on_approve"] = not v["in_window"]
    return v


def held_cards(pol, held_path, heads, now=None):
    """Cards for PRs approved but waiting for their window. heads: {pr: head} of open PRs or None."""
    now = now or now_utc()
    out = []
    for k, it in sorted((_load(held_path, {}).get("items") or {}).items(), key=lambda x: int(x[0])):
        pr = int(k)
        phase = "held"
        note = None
        if heads is not None:
            if pr not in heads:
                phase, note = (
                    "gone",
                    "The PR is no longer open. The lane clears it on its next pass.",
                )
            elif heads[pr] != it.get("head_sha"):
                phase, note = (
                    "in_flight",
                    "New commits landed after the approval. The hold drops and the PR gets a fresh review.",
                )
        v = window_view(
            pol, it.get("class"), it.get("hits"), held_at=_parse(it.get("held_at")), now=now
        )
        out.append(
            {
                "pr": pr,
                "title": it.get("title"),
                "author": it.get("author"),
                "url": it.get("url"),
                "head_sha": it.get("head_sha"),
                "held_at": it.get("held_at"),
                "approved_by": it.get("approved_by"),
                "hits": it.get("hits") or [],
                "last_check": it.get("last_check"),
                "last_check_at": it.get("last_check_at"),
                "comment_posted_at": it.get("comment_posted_at"),
                "phase": phase,
                "note": note,
                "window": v,
            }
        )
    return out


def hold(cfg_io, pol, pr, head, live, dtm, text=""):
    """Approve as me without enqueueing, record the hold, post the window comment once per head.
    cfg_io: gh, log, held_path, set_queue, self_login. Returns the done list."""
    m = mw()
    now = now_utc()
    cls = dtm.get("class") or "both"
    hits = dtm.get("hits") or []
    gh = cfg_io["gh"]
    done = []
    body = text or "Looks good to me. Approving."
    gh(["pr", "review", str(pr), "-R", cfg_io["repo"], "--approve", "--body", body], raw=True)
    done.append("approved review")
    held = _load(cfg_io["held_path"], {"items": {}})
    prev = (held.get("items") or {}).get(str(pr)) or {}
    posted = prev.get("comment_posted_at") if prev.get("head_sha") == head else None
    if not posted:
        comment = m.pr_comment(_cfg(pol), cls, hits, now)
        if FORBIDDEN.search(comment) or ";" in comment or "\u2014" in comment:
            raise HoldError("window comment failed the wording check", 500)
        try:
            gh(["pr", "comment", str(pr), "-R", cfg_io["repo"], "--body", comment], raw=True)
            posted = _iso(now)
            done.append("posted the window comment")
        except Exception as e:  # noqa: BLE001 - the approval stands, the card says the comment failed
            done.append(f"window comment not posted: {str(e)[:120]}")
    nxt = m.next_open(_cfg(pol), cls, now)
    held.setdefault("items", {})[str(pr)] = {
        "pr": pr,
        "title": live.get("title"),
        "author": (live.get("user") or {}).get("login"),
        "url": live.get("html_url"),
        "head_sha": head,
        "class": cls,
        "hits": hits,
        "held_at": prev.get("held_at") if prev.get("head_sha") == head else _iso(now),
        "approved_by": cfg_io["self_login"],
        "window_opens": _iso(nxt[0]) if nxt else None,
        "comment_posted_at": posted,
    }
    held["updated"] = _iso(now)
    _save(cfg_io["held_path"], held)
    done.append(f"held, merges in {m.window_phrase(_cfg(pol), cls, now)}")
    cfg_io["log"](
        {
            "pr": pr,
            "decision": "approved_held_for_window",
            "lane": "maintenance-window",
            "sha": head,
            "class": cls,
            "by": cfg_io["self_login"],
        }
    )
    return done


def record_override(cfg_io, pr, head, reason, cls, hits, via):
    """Sidecar + decisions log for an emergency override. Who, when, why, at which head."""
    now = now_utc()
    side = _load(cfg_io["overrides_path"], {"items": []})
    rec = {
        "pr": pr,
        "head_sha": head,
        "by": cfg_io["self_login"],
        "at": _iso(now),
        "reason": reason,
        "class": cls,
        "systems": sorted({h.get("system") or "unknown" for h in hits or []}),
        "via": via,
    }
    side.setdefault("items", []).append(rec)
    side["items"] = side["items"][-500:]
    side["updated"] = rec["at"]
    _save(cfg_io["overrides_path"], side)
    cfg_io["log"](
        dict(
            {"decision": "window_override", "lane": "maintenance-window", "sha": head},
            **{k: v for k, v in rec.items() if k != "head_sha"},
        )
    )
    return rec


def clean_reason(payload):
    reason = " ".join(str(payload.get("reason") or payload.get("override_reason") or "").split())
    if len(reason) < 8:
        raise HoldError("an emergency override needs a short reason (at least 8 characters)", 400)
    if len(reason) > 300:
        raise HoldError("keep the override reason under 300 characters", 400)
    return reason


def override(cfg_io, payload):
    """Merge now (emergency override) on a held card. Same-origin is checked by the server gate."""
    try:
        pr = int(payload.get("pr"))
    except (TypeError, ValueError):
        raise HoldError("pr required", 400) from None
    head = payload.get("head_sha") or ""
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise HoldError("head_sha required (40 hex)", 400)
    reason = clean_reason(payload)
    held = _load(cfg_io["held_path"], {"items": {}})
    it = (held.get("items") or {}).get(str(pr))
    if not it:
        raise HoldError(f"PR #{pr} is not waiting for the maintenance window", 404)
    if it.get("head_sha") != head:
        raise HoldError(
            f"the hold is for {str(it.get('head_sha'))[:8]}, not {head[:8]}. Refresh first", 409
        )
    live = cfg_io["verify_head"](pr, head)  # raises on closed or moved
    try:
        queued = merge_queue.enqueue(
            cfg_io["repo"], pr, head, gh=cfg_io["gh"], accept_own_threads=cfg_io["self_login"]
        )
    except merge_queue.MergeQueueError as e:
        raise HoldError(str(e), 409) from e
    held = _load(cfg_io["held_path"], {"items": {}})
    if (held.get("items") or {}).get(str(pr), {}).get("head_sha") == head:
        held["items"].pop(str(pr), None)
        held["updated"] = _iso(now_utc())
        _save(cfg_io["held_path"], held)
    rec = record_override(cfg_io, pr, head, reason, it.get("class"), it.get("hits"), "held-card")
    cfg_io["set_queue"](
        pr,
        {
            "status": "approved",
            "approved_by": cfg_io["self_login"],
            "last_action": f"Merge {queued['text']} now on an emergency override by {cfg_io['self_login']}: {reason}",
            "override": rec,
        },
    )
    return {
        "pr": pr,
        "done": [f"{queued['text']}, now (emergency override)", f"recorded reason: {reason}"],
        "queue": queued,
        "title": live.get("title"),
    }
