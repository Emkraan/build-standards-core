"""Tombstones for review actions the owner took in the Ops Center.

GitHub's `gh pr list` reads a search index that lags direct reads by seconds to minutes, and the
review lanes (escalation cards, own-PR lane state) only catch up on their next pass. Without this,
a PR the owner just merged or approved is listed again on the next refresh, and a second click fails with
"PR is closed". A tombstone hides the PR from Needs me and The owner's PRs until GitHub agrees or the TTL
passes. A new push (different head) brings the PR back, since that is new work for the owner.

Store: state/dashboard/review-acted.json {"items": {"<repo>#<pr>": {...}}}. Python 3.9.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path

import paths

STORE = Path(os.environ.get("REVIEW_ACTED_STORE", str(paths.dashboard_dir() / "review-acted.json")))
# merged: GitHub catches up within minutes. approved: an engineer PR can wait on checks for a while
# before auto-merge or the lane merges it, so it stays hidden longer, but never past a new push.
TTL_S = {"merged": 30 * 60, "approved": 3 * 3600, "closed": 30 * 60}
# An expired record stays in the store this much longer so a PR that comes back (the action did not
# land) can say so (live-actions rule 3). active() never returns it, so hiding is unchanged.
EXPIRED_KEEP_S = 6 * 3600
_gen = 0  # bumped by every write, so a read that started before it can tell and not cache itself
_logged = set()


def generation() -> int:
    """Counts writes in this process. A list build compares it before and after (live-actions rule 8)."""
    return _gen


def bump() -> None:
    global _gen
    _gen += 1


def _key(repo: str, pr: int) -> str:
    return f"{repo}#{int(pr)}"


def _read() -> dict:
    try:
        return json.loads(STORE.read_text())
    except (OSError, ValueError):
        return {"items": {}}


def _write(d: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    os.replace(tmp, STORE)


def record(repo: str, pr: int, head: str, outcome: str, note: str = "", title: str = "") -> None:
    """outcome: merged (merge done or already merged), approved (approval posted, merge pending),
    closed (closed without merge)."""
    lock = STORE.with_suffix(".lock")
    STORE.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        d = _read()
        items = d.setdefault("items", {})
        now = time.time()
        for k in [
            k
            for k, v in items.items()
            if now - v.get("at", 0) > TTL_S.get(v.get("outcome"), 1800) + EXPIRED_KEEP_S
        ]:
            items.pop(k, None)
        items[_key(repo, pr)] = {
            "repo": repo,
            "pr": int(pr),
            "head": head or "",
            "outcome": outcome,
            "note": note[:300],
            "title": title[:200],
            "at": now,
        }
        _write(d)
    bump()


def active(repo: str) -> dict:
    """{pr: record} for live tombstones of one repo."""
    now = time.time()
    out = {}
    for v in _read().get("items", {}).values():
        if v.get("repo") == repo and now - v.get("at", 0) <= TTL_S.get(v.get("outcome"), 1800):
            out[int(v["pr"])] = v
    return out


def missed(repo: str) -> dict:
    """{pr: record} for merged or closed tombstones of one repo that expired while the PR is still
    listed. The caller only flags a PR that is open at the recorded head (live-actions rule 3)."""
    now = time.time()
    out = {}
    for v in _read().get("items", {}).values():
        if v.get("repo") != repo or v.get("outcome") not in ("merged", "closed"):
            continue
        if now - v.get("at", 0) > TTL_S.get(v.get("outcome"), 1800):
            out[int(v["pr"])] = v
    return out


def flag_missed(rows: list, repo: str, pr_key: str = "pr", head_key: str = "head_sha") -> None:
    """A row for a PR whose merge or close tombstone expired with the PR still open at the same head
    gets last_action_missed (outcome, note, at) and one log line. Adds a field, hides nothing."""
    gone = missed(repo)
    if not gone:
        return
    for row in rows:
        try:
            rec = gone.get(int(row.get(pr_key)))
        except (TypeError, ValueError):
            continue
        head = row.get(head_key)
        if not rec or (head and rec.get("head") and rec["head"] != head):
            continue
        row["last_action_missed"] = {
            "outcome": rec.get("outcome"),
            "at": rec.get("at"),
            "note": f"The last action on this PR ({rec.get('outcome')}) did not land. GitHub still shows it open.",
        }
        mark = (repo, rec["pr"], rec.get("at"))
        if mark not in _logged:
            _logged.add(mark)
            print(
                f"review_acted: {repo}#{rec['pr']} {rec.get('outcome')} tombstone expired unconfirmed, PR is open again"
            )


def hides(tomb: dict, pr, head) -> bool:
    """True when a tombstone covers this PR at this head. A different head is new work."""
    try:
        rec = tomb.get(int(pr))
    except (TypeError, ValueError):
        return False
    if not rec:
        return False
    return not head or not rec.get("head") or rec.get("head") == head


def approved_what(note: str) -> str:
    """What an "approved" tombstone actually approved: "plan" when the only things done were
    terraform-plan run approvals (the owner's own PRs, where GitHub never lets me approve the PR itself), else
    "pr". A plan approval is not a merge, so the UI must not say the PR merges."""
    parts = [x.strip() for x in (note or "").split(";") if x.strip()]
    if parts and all("terraform-plan run" in x and x.startswith("approved") for x in parts):
        return "plan"
    return "pr"


def public(tomb: dict, open_prs=None, needs_me_prs=None) -> list:
    """What the UI shows under 'Just acted on' so a hidden PR is never a mystery. open_prs (the set of
     open PR numbers from a live read, None when unknown) marks a merge or close as confirmed.
     needs_me_prs (PRs that still have a Needs me card) marks an approval whose PR still waits on me
    , so the row points at that card instead of reading as done."""
    now = time.time()
    still = set(needs_me_prs or ())
    rows = []
    for rec in sorted(tomb.values(), key=lambda r: r.get("at", 0), reverse=True):
        approved = rec.get("outcome") == "approved"
        rows.append(
            {
                "pr": rec["pr"],
                "title": rec.get("title", ""),
                "outcome": rec.get("outcome"),
                "note": rec.get("note", ""),
                "age_s": int(now - rec.get("at", now)),
                "confirmed": bool(
                    open_prs is not None
                    and rec.get("outcome") in ("merged", "closed")
                    and rec["pr"] not in open_prs
                ),
                "what": approved_what(rec.get("note", "")) if approved else None,
                "still_needs_me": bool(approved and rec["pr"] in still),
            }
        )
    return rows
