"""other_reviews.py - the second repo's PR reviews for the Reviews hub (its own sub-tab).

Live, read-mostly view of the pull requests of `other_repo` (review_config), shaped like the plan sub-tab so the hub
reads the same:

- Needs me: engineer PRs the repo's review lane escalated to the owner, the owner's own PRs the own-PR lane holds
  for the owner's sign-off on a policy rule (kind signoff), and the owner's own PRs auto-fix gave up on (kind
  direction, no merge button).
- In progress: every other open PR. The owner's own PRs show what the own-PR lane is doing (it merges them once
  green and starts an auto-fix session at once for a fixable problem). If that lane has not run in 15 minutes, the
  owner's green PRs fall back to kind ready_to_merge.
- Recently shipped: merged in the last 14 days.

The consumer supplies what only it knows, all optional (null default: no escalations, no live lane check):
  OPSCENTER_ESCALATIONS_CMD   a command printing JSON [{"pr": n, "card": id, "reason": s, "recommendation": s,
                              "status": s, "head": sha}] of PRs its review lane escalated
  OPSCENTER_OWN_LANE_CMD      a command taking `check <pr> --target <lane>` and printing {head, status, reason};
                              default: lanes/own_pr_merge.py from this tree
  OPSCENTER_OTHER_POLICY      the own-PR policy file (rule ids to plain reasons)
The lane target name is `other_lane` in review_config (default "other"). With no `other_repo` the page is empty and
a write answers 501.

Writes (same-origin, loopback only, enforced by the server gate):
- merge(payload): rebase-merge one of the owner's PRs with the maintainer bypass, pinned to the head the owner
  saw (--match-head-commit). While the own-PR lane runs, it re-checks the PR live with the
  lane and only merges a pure sign-off hold (or a PR that already passes everything).
- approve(payload): approve an escalated engineer PR as the owner, pinned to the head the owner saw. The
  lane merges it on its next poll once it is clean.
"""

import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

import decision_cards
import own_lane
import paths
import review_acted
import review_config as rcfg
import swr

GH = os.environ.get("OTHER_REVIEWS_GH_BIN", paths.which("gh"))
SHIPPED_DAYS = 14
LANES = Path(__file__).resolve().parents[2] / "lanes"
STATE_NAME = "other-review"


def _repo():
    return rcfg.need(rcfg.other_repo(), "other_repo")


def _self():
    return rcfg.owner()


def _lane():
    return rcfg.lane_name()


def _policy_path():
    return Path(
        os.environ.get("OPSCENTER_OTHER_POLICY")
        or paths.state_dir() / STATE_NAME / "own-pr-policy.json"
    )


def _decisions():
    return paths.state_dir() / STATE_NAME / "decisions.jsonl"


TTL_S = 60
_OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_RED = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"}
_cache = {"at": 0.0, "data": None}
_lock = threading.Lock()


class ReviewError(Exception):
    def __init__(self, msg, code=502):
        super().__init__(msg)
        self.code = code
        self.status = code


class AlreadyClosed(ReviewError):
    """The PR is no longer open (merged by the lane or closed). A merge counts as done."""

    def __init__(self, pr, merged):
        super().__init__(f"PR #{pr} is already {'merged' if merged else 'closed'}", 409)
        self.pr = pr
        self.merged = merged


def _gh(args, timeout=60, raw=False):
    try:
        p = subprocess.run([GH] + args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ReviewError(f"gh failed: {e}") from e
    if p.returncode != 0:
        raise ReviewError(f"gh {' '.join(args[:3])}: {p.stderr.strip()[:300]}")
    if raw:
        return p.stdout
    return json.loads(p.stdout) if p.stdout.strip() else {}


def _rollup(rollup):
    """Newest result per check name -> (counts, failing names, pending names)."""
    newest = {}
    for c in rollup or []:
        name = c.get("name") or c.get("context") or "?"
        when = c.get("completedAt") or c.get("startedAt") or ""
        if name not in newest or when >= newest[name][0]:
            state = c.get("conclusion") or c.get("state") or c.get("status") or ""
            newest[name] = (when, (state or "").upper())
    red = sorted(n for n, (_, s) in newest.items() if s in _RED)
    # WAITING = the job waits on an environment approval. Nothing is running.
    pending = sorted(
        n for n, (_, s) in newest.items() if s not in _RED and s not in _OK and s != "WAITING"
    )
    waiting = sorted(n for n, (_, s) in newest.items() if s == "WAITING")
    return {"total": len(newest), "red": red, "pending": pending, "waiting": waiting}


def _escalations():
    """Open escalations from the consumer's review lane: {pr: {card, reason, recommendation, status, head}}.
    No OPSCENTER_ESCALATIONS_CMD is the null default (none)."""
    cmd = os.environ.get("OPSCENTER_ESCALATIONS_CMD")
    if not cmd:
        return {}, None
    try:
        p = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=30)
        rows = json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}, "escalations unreadable"
    out = {}
    for c in rows if isinstance(rows, list) else []:
        try:
            n = int(c.get("pr"))
        except (TypeError, ValueError, AttributeError):
            continue
        out[n] = {
            "card": c.get("card"),
            "reason": str(c.get("reason") or c.get("status") or "")[:200],
            "recommendation": str(c.get("recommendation") or ""),
            "status": str(c.get("status") or ""),
            "head": str(c["head"]) if c.get("head") else None,
        }
    return out, None


def _rule_reasons():
    """Rule id -> plain reason from the own-PR policy and any policy file it inherits line rules from."""
    out = {}
    try:
        pol = json.loads(_policy_path().read_text())
        rules = list(pol.get("path_rules") or []) + list(pol.get("line_rules") or [])
        src = pol.get("inherit_line_rules_from")
        if src:
            base = json.loads(Path(os.path.expanduser(src)).read_text())
            rules += list(base.get("line_rules") or [])
            if base.get("role_assignment_scope"):
                rules.append(base["role_assignment_scope"])
        for r in rules:
            if r.get("id"):
                out[r["id"]] = r.get("reason") or r["id"]
    except (OSError, ValueError, AttributeError):
        pass
    return out


def _signoff_rules(reason):
    ids = [x.strip() for x in reason.split(":", 1)[-1].split(",") if x.strip()]
    plain = _rule_reasons()
    return [(plain.get(i, i)[:1].upper() + plain.get(i, i)[1:]) for i in ids]


def _lane_check(n):
    """Live, read-only own-PR lane decision for one of the owner's PRs: {head, status, reason} or None."""
    cmd = os.environ.get("OPSCENTER_OWN_LANE_CMD")
    argv = shlex.split(cmd) if cmd else [sys.executable, str(LANES / "own_pr_merge.py")]
    env = dict(os.environ, OPRG_GH_BIN=GH)
    try:
        r = subprocess.run(
            argv + ["check", str(n), "--target", _lane()],
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _log(rec):
    try:
        _decisions().parent.mkdir(parents=True, exist_ok=True)
        with _decisions().open("a") as f:
            f.write(
                json.dumps(
                    dict(
                        {
                            "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "lane": "ops-center",
                        },
                        **rec,
                    )
                )
                + "\n"
            )
    except OSError:
        pass


def _triage_context(r):
    """The owner's triage replies on this head and who applied ai-review-override, so the approval brief
    can say a triaged blocker is the owner's accepted risk. Advisory: a read error leaves it out."""
    try:
        import label_hold

        r["triage"] = label_hold.triage_context(_gh, _repo(), r["pr"], r["head_sha"], _self())
    except Exception:  # noqa: BLE001
        r["triage"] = None


def _mine(r, lst):
    """Place one of the owner's PRs from the own-PR lane state. Returns 'needs' or 'progress'."""
    ln = own_lane.lane(lst, r["pr"], r["head_sha"])
    af = own_lane.autofix_or_session(lst, r["pr"], r["head_sha"], _lane(), r.get("branch"))
    r["autofix"] = af
    why = (ln or {}).get("reason", "")
    ch = own_lane.choice(_lane(), r["pr"], r["head_sha"])
    unc = own_lane.uncovered_rules(why, ch) if ch and ch["kind"] == "override" else []
    if ch and ch["kind"] == "override" and ln and ln["status"] == "held" and not unc:
        # Pipeline v2: the owner accepted the risk in the decision card, the lane merges it once green.
        # Only when that sign-off covers every rule the lane holds it for (#484).
        r["state"] = (
            f'you chose "{ch.get("label")}", the lane merges it once the review check turns green'
        )
        return "progress"
    if af and af.get("session"):
        # A live session is working the PR (a delegated fix, a Discuss session): whatever the hold reads now
        # can change under it, so it is in progress with its buttons locked, not on Needs me.
        r["state"] = af["text"]
        return "progress"
    if af and af["state"] == "gave_up":
        _triage_context(r)
        r.update(
            kind="direction",
            why=((why[:1].upper() + why[1:]).rstrip(".") + ". " if why else "") + af["text"],
            recommendation="It needs your direction. Any push to the branch lets auto-fix try again.",
        )
        if af.get("decision"):
            r["decision"] = af["decision"]
            r["recommendation"] = (
                "Pick one option below. Your click is the sign-off for this head only."
            )
        return "needs"
    if ln and ln["status"] == "held" and why.startswith("needs me"):
        _triage_context(r)
        r.update(
            kind="signoff",
            why="Everything passes. It waits only on your sign-off for:",
            rules=_signoff_rules("needs me: " + ", ".join(unc) if unc else why),
        )
        return "needs"
    if r["draft"]:
        r["state"] = "draft"
    elif not ln:
        r["state"] = "the auto-merge lane checks this head on its next pass"
    elif ln["status"] in ("ready", "would_merge"):
        r["state"] = "everything passes, the lane merges it on its next pass"
    elif ln["status"] == "merged":
        r["state"] = "merged by the lane"
    else:
        r["state"] = why or ln["status"]
    if af:
        r["state"] += ". " + af["text"]
    return "progress"


def _row(pr, checks):
    return {
        "pr": pr["number"],
        "title": pr["title"],
        "url": pr["url"],
        "author": (pr.get("author") or {}).get("login") or "?",
        "mine": (pr.get("author") or {}).get("login") == _self(),
        "head_sha": pr["headRefOid"],
        "branch": pr.get("headRefName"),
        "draft": bool(pr.get("isDraft")),
        "merge_state": pr.get("mergeStateStatus"),
        "mergeable": pr.get("mergeable"),
        "review": pr.get("reviewDecision"),
        "checks": checks,
        "created": pr.get("createdAt"),
        "updated": pr.get("updatedAt"),
    }


def _build():
    fields = (
        "number,title,url,author,headRefOid,headRefName,isDraft,mergeable,mergeStateStatus,"
        "reviewDecision,statusCheckRollup,createdAt,updatedAt"
    )
    open_prs = (
        _gh(["pr", "list", "-R", _repo(), "--state", "open", "--limit", "100", "--json", fields])
        or []
    )
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=SHIPPED_DAYS)).strftime(
        "%Y-%m-%d"
    )
    merged = (
        _gh(
            [
                "pr",
                "list",
                "-R",
                _repo(),
                "--state",
                "merged",
                "--limit",
                "50",
                "--search",
                f"merged:>={since}",
                "--json",
                "number,title,url,author,mergedAt,mergeCommit",
            ]
        )
        or []
    )
    esc, esc_err = _escalations()
    lst = own_lane.load(_lane())
    lane_live = own_lane.fresh(lst)
    own_err = (
        None
        if lane_live
        else (
            f"The own-PR lane has not run since {lst.get('updated')}{' (' + lst['last_error'] + ')' if lst.get('last_error') else ''}, "
            "so the owner's green PRs need the owner's merge here."
            if lst
            else "The own-PR lane has not run yet, so the owner's green PRs need the owner's merge here."
        )
    )
    needs, progress = [], []
    # Tombstones: a PR the owner just merged or approved stays hidden until GitHub and the lane agree.
    tomb = review_acted.active(_repo())
    open_nums = {p.get("number") for p in open_prs}
    open_prs = [
        p for p in open_prs if not review_acted.hides(tomb, p.get("number"), p.get("headRefOid"))
    ]
    for pr in open_prs:
        checks = _rollup(pr.get("statusCheckRollup"))
        r = _row(pr, checks)
        green = not checks["red"] and not checks["pending"]
        e_head = (esc.get(pr["number"]) or {}).get("head")
        if (
            pr["number"] in esc
            and not r["mine"]
            and e_head
            and not pr["headRefOid"].startswith(e_head)
        ):
            # Escalated on an older head: Approve as me would approve commits nobody reviewed.
            r["state"] = (
                f"new commits since the escalation on {e_head[:8]}, the review lane re-checks them"
            )
            r["working"] = True
            progress.append(r)
        elif pr["number"] in esc and not r["mine"]:
            r.update(
                kind="escalated",
                why=esc[pr["number"]]["reason"],
                recommendation=esc[pr["number"]]["recommendation"],
            )
            needs.append(r)
        elif r["mine"] and lane_live:
            dest = _mine(r, lst)
            # A hold is not final while checks still run, so it is not the owner's action yet.
            (needs if dest == "needs" and not checks["pending"] else progress).append(r)
        elif (
            r["mine"]
            and not r["draft"]
            and green
            and r["mergeable"] != "CONFLICTING"
            and r["merge_state"] in ("BLOCKED", "CLEAN", "HAS_HOOKS", "UNSTABLE")
        ):
            r.update(
                kind="ready_to_merge",
                why="Green. The own-PR lane is not running, so it needs the owner's admin merge.",
            )
            needs.append(r)
        else:
            if r["draft"]:
                r["state"] = "draft"
            elif checks["red"]:
                r["state"] = "checks failing: " + ", ".join(checks["red"][:3])
            elif checks["pending"]:
                r["state"] = f"checks running ({len(checks['pending'])})"
            elif r["mergeable"] == "CONFLICTING":
                r["state"] = "merge conflict"
            elif not r["mine"] and esc_err:
                # live-actions 1.14: the pr-reviews board could not be read, so the owner cannot tell whether
                # the review lane escalated this engineer PR. Unknown never hides it, it stays on
                # Needs me marked unknown and approve re-verifies the board at click time.
                r.update(
                    kind="escalated",
                    unknown=True,
                    why=f"The review board is unreadable ({esc_err}), so I cannot tell if the review lane escalated this PR. "
                    "the owner verify it again when the owner act on it.",
                    recommendation="",
                )
                needs.append(r)
                continue
            elif not r["mine"]:
                r["state"] = "in the review loop" + (
                    f" ({r['review'].lower().replace('_', ' ')})" if r["review"] else ""
                )
            else:
                r["state"] = (r["merge_state"] or "open").lower()
            progress.append(r)
    shipped = [
        {
            "pr": m["number"],
            "title": m["title"],
            "url": m["url"],
            "author": (m.get("author") or {}).get("login") or "?",
            "merged": m.get("mergedAt"),
            "sha": ((m.get("mergeCommit") or {}).get("oid") or "")[:8],
        }
        for m in sorted(merged, key=lambda m: m.get("mergedAt") or "", reverse=True)
    ]
    review_acted.flag_missed(needs + progress, _repo())
    return {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "repo": _repo(),
        "needs_me": needs,
        "in_progress": progress,
        "shipped": shipped,
        "acted": review_acted.public(tomb, open_nums),
        "counts": {"needs_me": len(needs), "in_progress": len(progress), "shipped": len(shipped)},
        "lane_error": esc_err,
        "own_lane_error": own_err,
    }


def _empty():
    return {
        "generated_utc": None,
        "repo": "",
        "needs_me": [],
        "in_progress": [],
        "shipped": [],
        "acted": [],
        "counts": {"needs_me": 0, "in_progress": 0, "shipped": 0},
        "lane_error": None,
        "own_lane_error": None,
        "configured": False,
    }


def get(force=False):
    if not rcfg.other_repo():
        return _empty()  # the null default: nothing configured
    gen = review_acted.generation()
    with _lock:
        if not force and _cache["data"]:
            age = time.time() - _cache["at"]
            if age < TTL_S:
                return _cache["data"]
            if age < swr.MAX_STALE_S:
                # Serve the last view at once and refresh it in the background (one at a time).
                swr.kick(__name__, lambda: get(force=True))
                return _cache["data"]
    try:
        data = _build()
        if gen != review_acted.generation():
            data = _build()  # a write landed while the first read was in flight, read again past it
    except ReviewError as e:
        if _cache["data"]:
            stale = dict(_cache["data"])
            stale["error"] = str(e)
            return stale
        return {
            "generated_utc": None,
            "repo": _repo(),
            "needs_me": [],
            "in_progress": [],
            "shipped": [],
            "counts": {"needs_me": 0, "in_progress": 0, "shipped": 0},
            "error": str(e),
        }
    with _lock:
        if gen == review_acted.generation():
            _cache.update(at=time.time(), data=data)
    return data


def _pin(payload):
    _repo()
    rcfg.need(rcfg.owner(), "owner")
    try:
        pr = int(payload.get("pr"))
    except (TypeError, ValueError):
        raise ReviewError("pr required", 400) from None
    head = payload.get("head_sha") or ""
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ReviewError("head_sha required (40 hex)", 400)
    live = _gh(
        [
            "pr",
            "view",
            str(pr),
            "-R",
            _repo(),
            "--json",
            "state,isDraft,headRefOid,author,mergeable,statusCheckRollup,title",
        ]
    )
    if live.get("state") != "OPEN":
        merged = live.get("state") == "MERGED"
        review_acted.record(
            _repo(), pr, head, "merged" if merged else "closed", title=live.get("title") or ""
        )
        _drop_cache()
        raise AlreadyClosed(pr, merged)
    if live.get("headRefOid") != head:
        raise ReviewError(
            f"PR #{pr} moved to {str(live.get('headRefOid'))[:8]} since you loaded it. Refresh first.",
            409,
        )
    if live.get("isDraft"):
        raise ReviewError(f"PR #{pr} is a draft", 409)
    return pr, head, live


def merge(payload):
    """Rebase-merge one of the owner's PRs with the maintainer bypass, pinned to the head the owner saw. While the
    own-PR lane runs, only a pure sign-off hold (or a PR that already passes everything) merges:
    the lane re-checks it live and anything else is refused with what is wrong."""
    try:
        pr, head, live = _pin(payload)
    except AlreadyClosed as e:
        if e.merged:
            return {"pr": e.pr, "done": [f"#{e.pr} was already merged"], "already": True}
        raise
    if (live.get("author") or {}).get("login") != _self():
        raise ReviewError(f"PR #{pr} is not mine. The review lane merges engineer PRs.", 403)
    rules = []
    if own_lane.fresh(own_lane.load(_lane())):
        d = _lane_check(pr)
        if not d or d.get("head") != head:
            raise ReviewError(
                f"Could not re-check PR #{pr} with the lane. Refresh and try again.", 409
            )
        st, why = d.get("status"), d.get("reason") or ""
        if st == "held" and why.startswith("needs me"):
            rules = _signoff_rules(why)
        elif st != "ready":
            raise ReviewError(
                f"Not merging PR #{pr}: {why or st}. That is a problem to fix, not a sign-off.", 409
            )
    # Vercel previews are expected noise on the other repo (fork protection), the lane ignores them too.
    checks = _rollup(
        [
            c
            for c in live.get("statusCheckRollup") or []
            if not re.match(r"^Vercel", c.get("name") or c.get("context") or "")
        ]
    )
    if checks["red"] or checks["pending"]:
        raise ReviewError(
            f"PR #{pr} is not green (failing {checks['red']}, running {checks['pending']})", 409
        )
    if live.get("mergeable") == "CONFLICTING":
        raise ReviewError(f"PR #{pr} has a merge conflict", 409)
    _gh(
        ["pr", "merge", str(pr), "-R", _repo(), "--rebase", "--admin", "--match-head-commit", head],
        raw=True,
        timeout=120,
    )
    review_acted.record(_repo(), pr, head, "merged", title=live.get("title") or "")
    _log(
        {
            "pr": pr,
            "decision": "approved_policy_hold" if rules else "manual_merge",
            "sha": head,
            "rules": rules,
            "by": _self(),
        }
    )
    with _lock:
        _cache.update(at=0.0, data=None)
    return {
        "pr": pr,
        "done": [
            f"merged #{pr} at {head[:8]} with the maintainer bypass"
            + (" after your sign-off" if rules else "")
        ],
    }


def approve(payload):
    """Approve an escalated engineer PR as me, pinned to the head the owner saw."""
    try:
        pr, head, live = _pin(payload)
    except AlreadyClosed as e:
        if e.merged:
            return {"pr": e.pr, "done": [f"#{e.pr} was already merged"], "already": True}
        raise
    if (live.get("author") or {}).get("login") == _self():
        raise ReviewError("the owner cannot approve the owner's own PR. Use Merge.", 403)
    if payload.get("unverified"):
        # live-actions 1.14: the row was shown while the board was unreadable. Re-read it now and
        # refuse unless the review lane really escalated this PR at this head.
        esc, esc_err = _escalations()
        if esc_err:
            raise ReviewError(
                f"Could not confirm PR #{pr} was escalated: {esc_err}. Try again once the board reads.",
                409,
            )
        rec = esc.get(pr)
        if not rec:
            raise ReviewError(
                f"PR #{pr} is not escalated to me, the review lane still has it. Refresh.", 409
            )
        if rec.get("head") and not head.startswith(rec["head"]):
            raise ReviewError(
                f"PR #{pr} was escalated on {rec['head'][:8]}, not {head[:8]}. Refresh.", 409
            )
    _gh(
        [
            "api",
            "-X",
            "POST",
            f"repos/{_repo()}/pulls/{pr}/reviews",
            "-f",
            f"commit_id={head}",
            "-f",
            "event=APPROVE",
            "-f",
            "body=Approved.",
        ],
        raw=True,
    )
    review_acted.record(
        _repo(),
        pr,
        head,
        "approved",
        "the review lane merges it on its next pass",
        live.get("title") or "",
    )
    _drop_cache()
    return {
        "pr": pr,
        "done": [f"approved #{pr} at {head[:8]}. The review lane merges it on its next pass."],
    }


def _drop_cache():
    with _lock:
        _cache.update(at=0.0, data=None)
    review_acted.bump()


def decide_fix(payload):
    """The owner's choice on a pipeline v2 decision card for one of the owner's the other repo PRs (decision_cards.decide)."""

    def verify(pr, head):
        live = _gh(["api", f"repos/{_repo()}/pulls/{pr}"])
        if live.get("state") != "open":
            merged = bool(live.get("merged"))
            review_acted.record(
                _repo(), pr, head, "merged" if merged else "closed", title=live.get("title") or ""
            )
            raise AlreadyClosed(pr, merged)
        if live["head"]["sha"] != head:
            raise ReviewError(
                f"PR #{pr} moved to {live['head']['sha'][:8]} since you loaded it. Refresh first.",
                409,
            )
        return live

    cfg = {
        "repo": _repo(),
        "self_login": _self(),
        "lane_state": own_lane.STATE.get(_lane()),
        "gh": _gh,
        "verify_head": verify,
        "closed_exc": AlreadyClosed,
        "log": _log,
        "drop_cache": _drop_cache,
        "review_verdict": lambda pr: decision_cards.review_verdict(_gh, _repo(), pr),
    }
    try:
        return decision_cards.decide(cfg, payload)
    except decision_cards.DecisionError as e:
        raise ReviewError(str(e), e.code) from e
