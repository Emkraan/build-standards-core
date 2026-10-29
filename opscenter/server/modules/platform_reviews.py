"""
platform_reviews.py
Purpose: The platform reviews page backend. Merges, for the repo named by `plan_repo` in review_config:
           - the review lane's escalations, in-progress and shipped items (<state>/platform-review/queue.json, written by
             the consumer's review script and its agent)
           - held plan runs (<state>/tf-review/queue.json, tf_reviews.py)
           - privileged deployments (privileged_reviews.py) and owner applies (owner_roots.py)
           - the owner's own PRs (hold classification, sign-off, Approve and merge) and the PR review verdict
         Actions (approve, request changes, sign off, accept the risk, release deletes) go through the code host as the
         configured owner. Every estate value (repo, owner login, tier names, workflow names, label and marker strings,
         the review script) is the `platform` object of the review config (DESIGN.md 12.47) and has a null default;
         with no repo configured the page is empty and a write answers 501.
Date:    2026-10-06
"""

import base64
import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import decision_cards
import label_hold
import live_truth
import maintenance_hold
import merge_queue
import own_lane
import owner_roots
import paths
import pr_deps
import pr_landing
import privileged_reviews
import review_acted
import review_config as rcfg
import review_threads
import runbook_releases
import tf_reviews

HOME = Path.home()
STATE = Path(os.environ.get("OPRG_STATE_DIR", str(paths.state_dir() / "platform-review")))
CACHE = Path(
    os.environ.get("OPRG_CACHE_DIR", str(paths.agent_home() / "cache" / "platform-pr-review"))
)
QUEUE = STATE / "queue.json"
DECISIONS = STATE / "decisions.jsonl"
POLICY = Path(os.environ.get("OPRG_POLICY", str(STATE / "policy.json")))
HELD = STATE / "held-for-window.json"  # written by the lane and by decide() below
WINDOW_OVERRIDES = STATE / "window-overrides.json"  # ECR overrides: who, when, why, head
THREAD_WAITS = (
    STATE / "thread-waits.json"
)  # the owner's approvals held on open review conversations
LOCK = CACHE / "queue.lock"
HEALTH = CACHE / "health.json"
GH = os.environ.get("OPRG_GH_BIN", paths.which("gh"))
SHIPPED_DAYS = int(rcfg.platform("shipped_days", 14))


def _P(key, default=None):
    """One platform setting (review_config `platform` object) with a null default."""
    return rcfg.platform(key, default)


def _repo():
    return rcfg.need(rcfg.plan_repo(), "plan_repo")


def _self():
    return rcfg.need(rcfg.owner(), "owner")


def _tier(role):
    """The consumer's tier name for the `prod` or `dev` role (default: the role name)."""
    t = _P("tiers", {})
    return str(t.get(role) or role) if isinstance(t, dict) else role


def _forbidden(text):
    """True when the text names the tooling (the `forbidden_text_pattern` setting; none: no filter)."""
    pat = _P("forbidden_text_pattern", "")
    return bool(pat) and bool(re.search(pat, text or "", re.I))


def _default_changes_text():
    return str(_P("default_changes_text", "") or "")


def _label(key, default=""):
    return str(_P(key, default) or "")


def _assistant():
    return str(_P("assistant_name", "the assistant"))


def _operator():
    return str(_P("operator_display_name", "the owner"))


class ReviewError(Exception):
    def __init__(self, msg, code=502):
        super().__init__(msg)
        self.code = code


class AlreadyClosed(ReviewError):
    """The PR is no longer open. merged tells a merge (often the own-PR lane or auto-merge got there
    first) from a close. Callers treat a merge as done, never as an error."""

    def __init__(self, pr, merged, title=""):
        super().__init__(f"PR #{pr} is already {'merged' if merged else 'closed'}", 409)
        self.pr = pr
        self.merged = merged
        self.title = title


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(s):
    try:
        return (
            dt.datetime.strptime((s or "")[:19], "%Y-%m-%dT%H:%M:%S")
            .replace(tzinfo=dt.timezone.utc)
            .timestamp()
        )
    except ValueError:
        return 0


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


def _load(p, default):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


def _save_queue(q):
    tmp = QUEUE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(q, indent=2) + "\n")
    os.replace(tmp, QUEUE)


def _log(rec):
    STATE.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS, "a") as f:
        f.write(json.dumps(dict({"ts": _now()}, **rec)) + "\n")


def _tf_breakdown(it):
    a = it.get("assessment")
    if not a:
        return None
    return {
        "summary": a.get("summary"),
        "changes": a.get("changes", []),
        "plan": None,
        "risk": a.get("risk"),
        # after an earlier approval of this PR, only the hits that are new since it are marked.
        "rules": [
            (
                "plan hold (new since the owner's approval): "
                if r in (it.get("new_held") or [])
                else "plan hold: "
            )
            + r
            for r in it.get("held_reasons", [])
        ],
        "recommendation": a.get("recommendation"),
        "checked_at": a.get("checked_at"),
    }


# ---- the owner's own PRs (hold classification, Approve and merge) and the PR review verdict ----
MY_CACHE = CACHE / "my-prs.json"
MY_TTL_S = 60
BUMP_STATE = CACHE / "model-bump.json"
OWN_STATE = CACHE / "own-pr-merge.json"  # auto-merge lane for the owner's own PRs
NAMES = CACHE / "principal-names.json"  # object id -> display name, for plain-English grant text
NAMES_TTL_S = 86400
_TF_GRANT = re.compile(
    r'"([0-9a-fA-F-]{36})"\s*=\s*\{[^}]*?role\s*=\s*"([^"]+)"[^}]*?principal_type\s*=\s*"(User|Group|ServicePrincipal)"'
)
_MAIN_PENDING = ("main not applied:", "plans predate main's last apply:")


def _engine_main_pending(c):
    """The engine's main-pending hold reason for a live check, or None."""
    return (c or {}).get("main_pending_reason") or None


def _main_pending_view(why):
    """a waiting card with no merge button. It names what main still has to apply and what
    happens next, so it never reads as stalled or as a sign-off the owner owe."""
    if why.startswith("plans predate"):
        return {
            "kind": "waiting",
            "summary": "Its terraform plans ran before main's last apply, so they still show main's old destroys "
            "or replaces as if they were this PR's. " + why[:1].upper() + why[1:] + ".",
            "next": "The lane re-runs the failed plan jobs. The card shows the real sign-off once they finish.",
        }
    return {
        "kind": "waiting",
        "parked": "main",
        "summary": "The plan's destroys or replaces are main's own change that has not applied yet, not this PR's. "
        + why[:1].upper()
        + why[1:]
        + ". Merging now would only repeat main's failure.",
        "next": "Clear it on Needs me (the failed main apply or the Owner apply). The lane re-runs this PR's plans "
        "once main applies.",
    }


GATE_EVERY_MIN = int(rcfg.platform("own_lane_every_min", 10))  # the own-PR lane cadence


def _hhmm(iso):
    try:
        t = dt.datetime.strptime(str(iso)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return ""
    return t.astimezone().strftime("%-I:%M %p")


def _draft_view(am):
    """a draft is parked on purpose until the gate in its description is met. The lane checks
    the gate and marks it ready itself, so the card shows the checks and when they run next, never
    "needs a fix" and never a merge or plan button."""
    why = (am or {}).get("reason") or ""
    g = (am or {}).get("gate") or {}
    checks = [
        {"label": r.get("label"), "ok": bool(r.get("ok")), "detail": r.get("detail")}
        for r in g.get("results") or []
    ]
    if not am:
        return {
            "kind": "waiting",
            "summary": "Draft. The lane has not checked it yet. It runs every 3 minutes.",
        }
    if am.get("status") != "held" and why.startswith("gate met"):
        return {
            "kind": "waiting",
            "summary": "Its gate is met. The lane marked it ready for review and takes it from here.",
        }
    if why.startswith("draft: no gate block"):
        return {
            "kind": "problem",
            "parked": "nogate",
            "summary": "Draft with no gate. Nothing tells the lane when it is ready, so it stays parked until it is "
            "marked ready by hand.",
            "next": "Add a gate block to the description (Discuss with "
            + _assistant()
            + " writes it), or mark it ready "
            "for review.",
        }
    if checks:
        met = sum(1 for c in checks if c["ok"])
        at = _hhmm(g.get("at"))
        nxt = ""
        with contextlib.suppress(KeyError, TypeError, ValueError):
            nxt = _hhmm(
                (
                    dt.datetime.strptime(g["at"][:19], "%Y-%m-%dT%H:%M:%S")
                    + dt.timedelta(minutes=GATE_EVERY_MIN)
                ).strftime("%Y-%m-%dT%H:%M:%S")
            )
        return {
            "kind": "waiting",
            "parked": "gate",
            "gate": checks,
            "gate_met": met,
            "summary": f"Parked as a draft until its gate is met: {met} of {len(checks)} checks pass"
            + (f" (checked {at})." if at else "."),
            "next": "The lane re-checks the gate every 10 minutes"
            + (f" (next about {nxt})" if nxt else "")
            + " and marks it ready for review itself once every check passes. Plan approvals wait until then.",
        }
    return {
        "kind": "waiting",
        "summary": "Draft. " + (why[:1].upper() + why[1:] if why else "The lane is checking it."),
    }


# Next step for each kind of lane hold that is a real problem (no merge button for these).
_PROBLEM_NEXT = (
    ("checks red", "It needs a fix pushed to the branch. The lane merges it once checks pass."),
    ("merge conflict", "It needs a rebase on main. The lane merges it once it is clean."),
    (
        "no triage reply",
        "Each high finding needs a fix or a triage reply on the PR. The lane merges it after that.",
    ),
    (
        "triage reply covers",
        "The triage reply names only some high findings. Each missing id needs a fix or a triage reply naming it.",
    ),
    (
        "blocking finding",
        "The blocking findings need a fix on the branch. The lane merges it once the review is clean.",
    ),
    (
        "unresolved review thread",
        "The open review threads need a fix or a reply. The lane merges it after that.",
    ),
    ("label ", "Remove the hold label when it can go. The lane merges it after that."),
    ("change freeze", "The lane merges it after the freeze."),
    ("draft", "Mark it ready for review when it is done."),
    (
        "PR review verdict",
        "The automated review did not pass for this head. It needs a fix on the branch.",
    ),
    (
        "no PR review verdict",
        "The automated review has not posted for this head yet. The lane re-checks every 3 minutes.",
    ),
    ("merge failed", "The lane tried to merge and GitHub refused. Open the PR to see why."),
    ("lane error", "The auto-merge lane hit an error on this PR. It retries every 3 minutes."),
)


def _principal_name(oid, ptype):
    """Display name for an object id (cached a day) through tf_context's provider (TF_CONTEXT_PROVIDER). With none
    configured the short id is shown."""
    names = _load(NAMES, {})
    hit = names.get(oid)
    if hit and time.time() - hit.get("at", 0) < NAMES_TTL_S:
        return hit["name"]
    try:
        import tf_context

        got = tf_context.resolve_principal(oid)
    except Exception:  # noqa: BLE001 - a name is cosmetic
        got = None
    name = (got or {}).get("name") or ""
    if not name:
        return oid[:8]
    names[oid] = {"name": name, "at": time.time()}
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = NAMES.with_suffix(".tmp")
    tmp.write_text(json.dumps(names))
    os.replace(tmp, NAMES)
    return name


def _plain_rule(e):
    """One plain-English line for a policy rule hit."""
    m = _TF_GRANT.search(e.get("detail") or "")
    if m:
        oid, role, ptype = m.groups()
        return f"Grants {role} to {_principal_name(oid.lower(), ptype)} ({ptype.lower()})"
    reason = e.get("reason") or e.get("rule") or "policy rule"
    return reason[:1].upper() + reason[1:]


ENGINE_TIMEOUT_S = 180
ENGINE_FAIL_SHOW = 2  # failures in a row on one head before the row says the check is failing
ENGINE_FAILS = CACHE / "engine-check-fails.json"  # pr -> {head, count, reason, at}
# A passing engine check is reused for this long on the same head. The page refresh no longer
# re-runs every check (about 40 s each) once a minute. Approve and merge always runs it live.
ENGINE_CACHE_S = 300
_ENGINE_MEMO = {}  # (pr, head) -> (epoch, check output)
_ENGINE_LOCK = threading.Lock()
_FAIL_LOCK = threading.Lock()
_LIVE = threading.local()  # .fresh = True makes _engine_check skip the memo (live re-derive)


def _engine_fail_record(n, head, reason):
    """Count a failed engine check for this PR and head, and log why."""
    with _FAIL_LOCK:
        _engine_fail_record_locked(n, head, reason)


def _engine_fail_record_locked(n, head, reason):
    fails = _load(ENGINE_FAILS, {})
    prev = fails.get(str(n)) or {}
    count = (prev.get("count", 0) if prev.get("head") == head else 0) + 1
    fails[str(n)] = {"head": head, "count": count, "reason": reason[:300], "at": _now()}
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = ENGINE_FAILS.with_suffix(".tmp")
        tmp.write_text(json.dumps(fails, indent=1))
        os.replace(tmp, ENGINE_FAILS)
    except OSError as e:
        print(f"[engine-check] could not save failure state: {e}", file=sys.stderr, flush=True)
    print(
        f"[engine-check] pr={n} head={(head or '?')[:8]} fail#{count}: {reason[:300]}",
        file=sys.stderr,
        flush=True,
    )


def _engine_fail_clear(n):
    with _FAIL_LOCK:
        _engine_fail_clear_locked(n)


def _engine_fail_clear_locked(n):
    fails = _load(ENGINE_FAILS, {})
    if str(n) not in fails:
        return
    fails.pop(str(n), None)
    try:
        tmp = ENGINE_FAILS.with_suffix(".tmp")
        tmp.write_text(json.dumps(fails, indent=1))
        os.replace(tmp, ENGINE_FAILS)
    except OSError as e:
        print(f"[engine-check] could not clear failure state: {e}", file=sys.stderr, flush=True)


def engine_failure(n, head):
    """The recorded failure streak for this PR at this head, or None."""
    f = _load(ENGINE_FAILS, {}).get(str(n))
    return f if f and f.get("head") == head else None


def _engine_check(n, head=None):
    """Read-only engine check for one PR (escalations, threads, checks, plan). A failure is
    recorded with its reason (rc, stderr tail, elapsed) so the row can say why."""
    key = (str(n), head or "")
    if head and not getattr(_LIVE, "fresh", False):
        with _ENGINE_LOCK:
            hit = _ENGINE_MEMO.get(key)
        if hit and time.time() - hit[0] < ENGINE_CACHE_S:
            return hit[1]
    script = _P("review_script_path", "")
    if not script:
        return None  # no review script configured: the engine checks are off
    env = dict(os.environ, OPRG_GH_BIN=GH)
    t0 = time.time()
    try:
        r = subprocess.run(
            [sys.executable, str(Path(script).expanduser()), "check", str(n)],
            capture_output=True,
            text=True,
            timeout=ENGINE_TIMEOUT_S,
            env=env,
        )
    except subprocess.TimeoutExpired:
        _engine_fail_record(n, head, f"timed out after {ENGINE_TIMEOUT_S}s")
        return None
    except OSError as e:
        _engine_fail_record(n, head, f"could not start the engine: {e}")
        return None
    took = f"{time.time() - t0:.0f}s"
    err = " ".join((r.stderr or "").strip().splitlines()[-3:])
    if r.returncode != 0:
        _engine_fail_record(
            n, head, f"exit {r.returncode} after {took}" + (f": {err}" if err else "")
        )
        return None
    try:
        out = json.loads(r.stdout) if r.stdout.strip() else None
    except ValueError:
        out = None
    if not isinstance(out, dict):
        _engine_fail_record(n, head, f"no usable output after {took}" + (f": {err}" if err else ""))
        return None
    _engine_fail_clear(n)
    if head:
        with _ENGINE_LOCK:
            _ENGINE_MEMO[key] = (time.time(), out)
    return out


def _hold(item):
    """_hold_base plus the auto-fix lane: a problem the fixer is working says so, and a problem
    it gave up on becomes kind 'direction' (needs me, still no merge button)."""
    h = _hold_base(item)
    af = item.get("autofix")
    if af and af.get("session") and h.get("kind") != "problem":
        # A live session is working the PR (a delegated fix, a Discuss session): whatever the hold
        # reads now can change under it, so the card says who is on it and locks its buttons.
        return dict(h, autofix=af, next=af["text"])
    if af and af.get("state") == "waiting_on" and h.get("kind") in ("problem", "policy"):
        # what blocks it are the open PRs it waits on, which carry their own holds. A
        # plan-destroy sign-off here would delete their live objects, so no Approve and merge.
        was = h.get("kind")
        h = dict(h, kind="waiting", autofix=af)
        if was == "policy":
            h.pop("rules", None)
            h["summary"] = (
                "Its plan destroys are objects the PRs it waits on applied, so merging it now would delete them. "
                + af["text"]
            )
        else:
            h["summary"] = h["summary"].rstrip() + " " + af["text"]
        h.pop("next", None)
        return h
    ch = own_lane.choice("prod", item["pr"], item["head_sha"])
    unc = own_lane.uncovered_rules((item.get("auto_merge") or {}).get("reason"), ch) if ch else []
    if ch and ch["kind"] == "override" and unc and h.get("kind") in ("problem", "policy"):
        # #484: the lane still holds this head for rules the owner's decision card did not sign off. Never a silent
        # wait: it is on Needs me with exactly those rules and Approve and merge (which re-checks live).
        have = {(r.get("rule") if isinstance(r, dict) else r): r for r in h.get("rules") or []}
        rules = [have.get(r) or {"rule": r, "where": "", "detail": "", "plain": r} for r in unc]
        out = dict(
            h,
            kind="policy",
            rules=rules,
            summary=f'You chose "{ch.get("label")}" for the review findings. It still waits on your sign-off '
            "for: " + ", ".join(unc) + ".",
        )
        if h.get("kind") == "problem":
            out["next"] = h.get("summary") or ""
        return out
    if ch and ch["kind"] == "override" and h.get("kind") == "policy":
        # The override answers the review findings only. Policy rules beyond it (.github, the
        # tfplan matcher, RBAC) still need the owner's Approve and merge, so the hold stays actionable.
        rest = [
            r
            for r in h.get("rules") or []
            if (r.get("rule") if isinstance(r, dict) else r) != OVERRIDE_LABEL
        ]
        if rest:
            return dict(
                h,
                summary=f'You chose "{ch.get("label")}" for the review findings. It still waits on your sign-off '
                "for the change below.",
            )
    if ch and ch["kind"] == "override" and h.get("kind") in ("problem", "policy"):
        # Pipeline v2: the owner accepted the risk in the decision card. The lane merges this head once
        # the review check turns green on the override label, so it is in flight, not actionable.
        return {
            "kind": "waiting",
            "summary": f'You chose "{ch.get("label")}" for this head. The lane merges it once the review check '
            "turns green on the override.",
        }
    if h.get("kind") != "problem" or not af:
        return h
    h["autofix"] = af
    if af["state"] == "gave_up":
        h["kind"] = "direction"
        h["summary"] = h["summary"].rstrip() + " " + af["text"].rstrip(".") + "."
        h["next"] = "It needs your direction. Any push to the branch lets auto-fix try again."
        _attach_plan(h, item)
        if af.get("decision"):
            # Pipeline v2: the fix session left a structured decision. The card's buttons ARE the
            # direction, so the next line says so instead of asking for a push.
            h["decision"] = af["decision"]
            h["next"] = "Pick one option below. Your click is the sign-off for this head only."
    else:
        h["next"] = af["text"]
    return h


def _attach_plan(h, item):
    """a direction card gets a written brief, so it needs the plan facts too. The plan comes
    from the engine check on this exact head (the same read the policy hold uses, cached). When that
    read fails, plan_unread tells the brief it does not know, so it never says no plan ran."""
    if h.get("plan_detail"):
        return h
    c = _engine_check(item["pr"], item.get("head_sha"))
    if not c or c.get("head_sha") != item.get("head_sha"):
        h["plan_unread"] = True
        return h
    plan = c.get("plan") or {}
    h["plan_detail"] = _plan_detail(plan)
    if plan.get("ran"):
        h["plan"] = (
            f"Terraform plan: {plan.get('add', 0)} add, {plan.get('change', 0)} change, "
            f"{plan.get('destroy', 0)} destroy, {plan.get('import', 0)} import"
        )
    return h


def _plan_detail(plan):
    """The plan run and the roots it changes, so the approval brief can read the exact resources
    from that run's job logs (approval_brief.py). None when terraform-ci did not run."""
    if not plan or not plan.get("ran"):
        return None
    keys = ("run_id", "run_url", "add", "change", "destroy", "import", "replace")
    roots = [
        {
            "job": r.get("job"),
            "summary": r.get("summary"),
            "branch_drift": r.get("branch_drift") or 0,
        }
        for r in plan.get("roots") or []
        if r.get("job") and not str(r.get("summary") or "").startswith("No changes")
    ]
    # per-root counts and the resource list, so the card's landing table is built from facts.
    # deletes the review classified as branch drift (objects another open PR applied from its
    # branch. The apply skips them and never destroys them) are already out of the destroy count above.
    drift = [
        {k: d.get(k) for k in ("address", "root", "app", "pr", "branch")}
        for d in plan.get("branch_drift") or []
        if isinstance(d, dict)
    ]
    return dict(
        {k: plan.get(k) for k in keys},
        roots=roots,
        branch_drift=drift,
        plan_rows=pr_landing.compact_plan(plan),
    )


def _hold_base(item):
    """Why one of the owner's PRs is not merged yet. kind:
    policy  = everything passes and only policy rules wait on the owner's sign-off (Approve and merge)
    problem = something is wrong and needs a fix, never a merge button
    waiting = the lane is still working (checks running, merges on its next pass)"""
    am = item.get("auto_merge")
    if item.get("model_bump"):
        if item.get("red"):
            return {
                "kind": "problem",
                "summary": "Model bump with failing checks: " + ", ".join(item["red"])[:200] + ".",
                "next": "The model-bump lane leaves it for a fix on the branch.",
            }
        return {
            "kind": "waiting",
            "summary": "The model-bump lane owns this PR and merges it once it is green.",
        }
    if item.get("draft"):
        return _draft_view(am)
    if not am:
        return {
            "kind": "waiting",
            "summary": "The auto-merge lane has not checked this head yet. It runs every 3 minutes.",
        }
    st, why = am.get("status"), am.get("reason") or ""
    if st in ("ready", "would_merge"):
        return {
            "kind": "waiting",
            "summary": "Everything passes. The lane merges it on its next pass.",
        }
    if st == "waiting":
        if item.get("waiting") and not item.get("pending"):
            # plan_wait: get() rewrites the text from the live plan gate queue, because
            # this row is cached and the gate may still park the hold or auto-approve the run.
            return {
                "kind": "waiting",
                "plan_wait": True,
                "summary": f"{len(item['waiting'])} terraform check(s) wait on my plan approval. Nothing is running.",
                "next": "Approve the plan runs on Needs me. The lane takes it from there.",
            }
        return {
            "kind": "waiting",
            "summary": why[:1].upper() + why[1:] + ". The lane merges it once they finish.",
        }
    if st == "held" and why.startswith(_MAIN_PENDING):
        # the plan's destroys or replaces are main's own unapplied change. Nothing on the
        # branch fixes that and Approve and merge would only repeat main's failure, so no button.
        return _main_pending_view(why)
    if st == "held" and why.startswith("needs me"):
        c = _engine_check(item["pr"], item["head_sha"])
        if not c:
            f = engine_failure(item["pr"], item["head_sha"])
            if f and f.get("count", 0) >= ENGINE_FAIL_SHOW:
                return {
                    "kind": "problem",
                    "summary": f"The live check for this head failed {f['count']} times in a row ({f['reason']}).",
                    "next": "Approve and merge comes back once the check passes. Use Discuss with "
                    + _assistant()
                    + " if it keeps failing.",
                }
            return {"kind": "waiting", "summary": "Re-checking this head. Refresh in a minute."}
        if c.get("head_sha") != item["head_sha"]:
            return {"kind": "waiting", "summary": "Re-checking this head. Refresh in a minute."}
        mp_why = _engine_main_pending(c)
        if mp_why:
            # The live check already sees main's pending change. The lane's next pass holds it the same way.
            return _main_pending_view(mp_why)
        other = []
        if int(c.get("unresolved_threads") or 0):
            other.append(f"{c['unresolved_threads']} unresolved review thread(s)")
        ch = c.get("checks") or {}
        covered = set(am.get("import_covered") or [])
        red_rest = [k for k in ch.get("red") or [] if k not in covered]
        green = ch.get("green") or (bool(covered) and not red_rest and not ch.get("pending"))
        if not green and not ch.get("destroy_guard_only"):
            other.append(
                "checks not green: " + ", ".join(red_rest + (ch.get("pending") or []))[:150]
            )
        if c.get("mergeable") == "CONFLICTING":
            other.append("merge conflict with main")
        escs = c.get("escalations") or []
        rules = [
            {
                "rule": e.get("rule"),
                "where": e.get("where"),
                "detail": e.get("detail"),
                "plain": _plain_rule(e),
                "fp": e.get("fp"),
                "cfp": e.get("cfp"),
                "path": e.get("path"),
            }
            for e in escs
        ]
        if OVERRIDE_LABEL and OVERRIDE_LABEL in why:
            # the lane only says this after it confirmed the owner's override label and
            # the owner's triage reply on this exact head. Merging is the owner's sign-off on it.
            rules.insert(
                0,
                {
                    "rule": OVERRIDE_LABEL,
                    "where": "",
                    "detail": "",
                    "plain": "Merges past a blocking review finding the owner triaged and overrode on this head",
                },
            )
        plan = c.get("plan") or {}
        plan_txt = (
            (
                f"Terraform plan: {plan.get('add', 0)} add, {plan.get('change', 0)} change, "
                f"{plan.get('destroy', 0)} destroy, {plan.get('import', 0)} import"
            )
            if plan.get("ran")
            else ""
        )
        if other:
            return {
                "kind": "problem",
                "summary": "Also held: " + ", ".join(other) + ".",
                "next": "Fix those first. Then it only waits on your sign-off.",
                "rules": rules,
                "plan_detail": _plan_detail(plan),
            }
        hold = {
            "kind": "policy",
            "summary": "Everything passes. It waits only on your sign-off for the change below.",
            "rules": rules,
            "plan": plan_txt,
            "plan_detail": _plan_detail(plan),
        }
        # one sign-off per PR. What the owner already signed off is not asked again, the card names
        # only what is new, and what Approve and merge will record is everything the owner see here.
        hold = _signoff_card(item, c, escs, rules, plan, hold)
        if ch.get("destroy_guard_only"):
            routed = _route_destroys(item["pr"], _guard_roots(plan))
            hold["destroy_roots"] = [
                {"tool": r["tool"], "tier": r["tier"]} for r in routed if r["route"] == "dispatch"
            ]
            hold["destroy_routes"] = routed
            hold["plan_run_id"] = plan.get("run_id")
            hold["summary"] = (
                "Everything else passes. terraform-ci held the plan because it deletes resources, "
                "so it waits on your sign-off for the change below."
            )
            hold["next"] = _destroy_next(routed)
        return hold
    if why.startswith("label ") and label_hold.hold_label(item.get("labels")):
        return _label_hold_view(item, am)
    nxt = next((t for k, t in _PROBLEM_NEXT if k in why), "Open the PR to see what it needs.")
    return {
        "kind": "problem",
        "summary": (why[:1].upper() + why[1:]).rstrip(".") + ".",
        "next": nxt,
    }


def _label_hold_view(item, am):
    """a hold label says who placed it, why (newest decisions-log note), and what still
    stands once it is gone, so the card carries a real next step instead of 'remove the label'."""
    label = label_hold.hold_label(item.get("labels"))
    ev = label_hold.label_event(_gh, _repo(), item["pr"], label)
    note = label_hold.note_for(item["pr"])
    triaged = (
        label_hold.triaged_ids(_gh, _repo(), item["pr"], item["head_sha"], _self())
        if item.get("findings")
        else set()
    )
    c = _engine_check(item["pr"], item["head_sha"])
    if c and c.get("head_sha") != item["head_sha"]:
        c = None
    rest = label_hold.behind(item, c, triaged, (am or {}).get("import_covered") or [])
    summary, nxt, block = label_hold.describe(item, label, ev, note, rest, _self())
    return {"kind": "problem", "summary": summary, "next": nxt, "label_hold": block}


def remove_hold_label(payload):
    """The owner's click on Remove hold label for one of the owner's PRs. Pinned to the head the owner saw, only labels in
    label_hold.HOLD_LABELS, and 'already gone' is a success."""
    _repo()
    _self()  # the null default: nothing configured is a 501 before anything is read
    try:
        pr = int(payload.get("pr"))
    except (TypeError, ValueError):
        raise ReviewError("pr required", 400) from None
    head = payload.get("head_sha") or ""
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ReviewError("head_sha required (40 hex)", 400)
    label = payload.get("label") or ""
    if label not in label_hold.HOLD_LABELS:
        raise ReviewError(f"only {', '.join(label_hold.HOLD_LABELS)} can be removed here", 400)
    try:
        live = _verify_head(pr, head)
    except AlreadyClosed as e:
        _drop_my_cache()
        return {
            "pr": pr,
            "done": [f"#{pr} is already {'merged' if e.merged else 'closed'}"],
            "already": True,
        }
    if (live.get("user") or {}).get("login") != _self():
        raise ReviewError(f"PR #{pr} is not mine. Engineer PRs keep their own labels.", 403)
    names = [lbl.get("name") for lbl in live.get("labels") or []]
    if label in names:
        _gh(["api", "-X", "DELETE", f"repos/{_repo()}/issues/{pr}/labels/{label}"], raw=True)
    after = [lbl.get("name") for lbl in (_gh(["api", f"repos/{_repo()}/issues/{pr}/labels"]) or [])]
    if label in after:
        raise ReviewError(f"GitHub still shows {label} on #{pr}. Refresh and try again.", 502)
    label_hold.forget(pr)
    _log({"pr": pr, "decision": "removed_hold_label", "label": label, "sha": head, "by": _self()})
    _drop_my_cache()
    if label not in names:
        return {"pr": pr, "done": [f"{label} was already off #{pr}"], "already": True}
    return {
        "pr": pr,
        "done": [
            f"removed {label} from #{pr} at {head[:8]}, the lane re-checks it within 3 minutes"
        ],
    }


def accept_risk(payload):
    """The owner's click on Accept the risk for one of the owner's PRs: applies the override label as me for the
    blocking findings the owner's triage already answers on this exact head. It does not merge. The own-PR lane then
    turns it into a policy hold, so the card shows Approve and merge (or Remove hold label first). Pinned to
    the head the owner saw, refuses someone else's PR, a review that is not blocked, and a triage that misses any
    blocking id. The label already on is a success."""
    _repo()
    _self()  # the null default: nothing configured is a 501 before anything is read
    try:
        pr = int(payload.get("pr"))
    except (TypeError, ValueError):
        raise ReviewError("pr required", 400) from None
    head = payload.get("head_sha") or ""
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ReviewError("head_sha required (40 hex)", 400)
    try:
        live = _verify_head(pr, head)
    except AlreadyClosed as e:
        _drop_my_cache()
        return {
            "pr": pr,
            "done": [f"#{pr} is already {'merged' if e.merged else 'closed'}"],
            "already": True,
        }
    if (live.get("user") or {}).get("login") != _self():
        raise ReviewError(
            f"PR #{pr} is not mine. Engineer PRs get the override through Approve.", 403
        )
    names = [lbl.get("name") for lbl in live.get("labels") or []]
    if OVERRIDE_LABEL in names:
        _drop_my_cache()
        return {"pr": pr, "done": [f"{OVERRIDE_LABEL} was already on #{pr}"], "already": True}
    v = _ai_verdict(pr)
    if not v or v.get("head_sha") != head:
        raise ReviewError(f"The PR review has not run on {head[:8]} yet. Wait for it first.", 409)
    item = {
        "verdict": v.get("verdict"),
        "counts": v.get("counts") or {},
        "findings": v.get("findings") or [],
        "labels": names,
    }
    triaged = label_hold.triaged_ids(_gh, _repo(), pr, head, _self())
    ar = label_hold.accept_risk(item, triaged)
    if not ar["ok"]:
        raise ReviewError(f"Cannot accept the risk on #{pr} at {head[:8]}: {ar['reason']}.", 409)
    _gh(["pr", "edit", str(pr), "-R", _repo(), "--add-label", OVERRIDE_LABEL], raw=True)
    after = [lbl.get("name") for lbl in (_gh(["api", f"repos/{_repo()}/issues/{pr}/labels"]) or [])]
    if OVERRIDE_LABEL not in after:
        raise ReviewError(
            f"GitHub does not show {OVERRIDE_LABEL} on #{pr}. Refresh and try again.", 502
        )
    label_hold.forget(pr)
    _log(
        {
            "pr": pr,
            "decision": "accepted_risk",
            "label": OVERRIDE_LABEL,
            "sha": head,
            "by": _self(),
            "ids": ar["ids"],
        }
    )
    _drop_my_cache()
    return {
        "pr": pr,
        "done": [
            f"applied {OVERRIDE_LABEL} to #{pr} at {head[:8]} for {', '.join(ar['ids'])}, "
            "the lane re-checks it within 3 minutes. Nothing is merged"
        ],
    }


def _guard_job():
    """The destroy-guard plan job name pattern: `guard_job_regex` with {tiers} replaced by the two tier names (default
    `terraform plan (<tool> <tier>)`)."""
    tiers = "|".join(re.escape(_tier(r)) for r in ("prod", "dev"))
    pat = str(_P("guard_job_regex", r"^terraform plan \((\S+) ({tiers})\)$"))
    return re.compile(pat.replace("{tiers}", tiers))


def _guard_roots(plan):
    """[(tool, tier)] of the plan jobs that failed only on terraform-ci's destroy guard."""
    out = []
    for r in (plan or {}).get("roots") or []:
        m = _guard_job().match(r.get("job") or "")
        if r.get("guard_only") and m and m.groups() not in out:
            out.append(m.groups())
    return out


ROOTS_CACHE = CACHE / "terraform-roots.json"
ROOTS_TTL_S = 3600


# Who applies a root the destroy workflow cannot reach (it only resolves roots applied by the pipeline).
def _applier_text(applier):
    """How a root the destroy workflow cannot reach gets applied: the `applier_texts` setting, else a plain sentence."""
    t = _P("applier_texts", {})
    return (
        str(t.get(applier)) if isinstance(t, dict) and t.get(applier) else f"{applier} applies it"
    )


def _platform_roots():
    """{name: root spec} from the roots manifest (`roots_manifest_path`) on the default branch (cached an hour)."""
    hit = _load(ROOTS_CACHE, None)
    if hit and time.time() - hit.get("at", 0) < ROOTS_TTL_S:
        return hit["roots"]
    raw = _gh(
        [
            "api",
            f"repos/{_repo()}/contents/{_P('roots_manifest_path', '.github/terraform-roots.json')}?ref={_P('default_branch', 'main')}",
            "--jq",
            ".content",
        ],
        raw=True,
    )
    data = json.loads(base64.b64decode(raw.strip()).decode("utf-8"))
    roots = {r["name"]: r for r in data.get("roots") or []}
    CACHE.mkdir(parents=True, exist_ok=True)
    ROOTS_CACHE.write_text(json.dumps({"at": time.time(), "roots": roots}))
    return roots


def _route_destroys(pr, roots):
    """decide, per destroy-guarded root, whether Approve and merge should start
    the destroy workflow. route:
    dispatch = the PR changes that root and the destroy workflow can reach it
    applier  = the destroy workflow cannot reach it (Owner, governance, Entra or runbooks applier)
    main     = the PR does not change that root, so the deletes are already pending on main
               (or the branch is behind), and a destroy run belongs to the PR that made them"""
    try:
        cfg = _platform_roots()
    except (ReviewError, ValueError, KeyError) as e:
        return [
            {"tool": t, "tier": tier, "route": "dispatch", "note": f"roots unreadable: {e}"[:150]}
            for t, tier in roots
        ]
    files = None
    out = []
    for tool, tier in roots:
        spec = cfg.get(tool)
        if not spec:  # app root, always reachable and always the PR's own
            out.append({"tool": tool, "tier": tier, "route": "dispatch"})
            continue
        applier = spec.get("applied_by", "tfapply" if spec.get("apply") else "owner")
        if applier not in ("tfapply", "runbooks"):
            out.append({"tool": tool, "tier": tier, "route": "applier", "applier": applier})
            continue
        if files is None:
            files = [
                f.get("path") or ""
                for f in (_gh(["pr", "view", str(pr), "-R", _repo(), "--json", "files"]) or {}).get(
                    "files"
                )
                or []
            ]
        root = (spec.get("tiers") or {}).get(tier, {}).get("root", "").rstrip("/") + "/"
        watch = [root] + list(spec.get("watch") or [])
        touched = any(f.startswith(w) or f == w for f in files for w in watch)
        if (
            spec.get("inputs")
            and _P("app_manifest_name", "")
            and any(f.endswith(_P("app_manifest_name")) for f in files)
        ):
            touched = True
        if applier == "runbooks":
            # The runbook deploy only runs when the PR changes runbook files. An untouched runbooks root
            # has deletes already pending on main, and no run from this PR will ever stop on them.
            touched = touched or runbook_releases.touches(files)
            out.append(
                {
                    "tool": tool,
                    "tier": tier,
                    "route": "applier" if touched else "main",
                    "applier": applier,
                }
            )
            continue
        out.append({"tool": tool, "tier": tier, "route": "dispatch" if touched else "main"})
    return out


def _destroy_next(routed):
    parts = []
    disp = [f"{r['tool']} ({r['tier']})" for r in routed if r["route"] == "dispatch"]
    if disp:
        parts.append(
            f"Approve and merge merges it and starts the destroy workflow for {', '.join(disp)}. Nothing is deleted "
            "until you approve that run's plan under "
            + _label("privileged_label", "Privileged")
            + " (destroy environment)."
        )
    else:
        parts.append("Approve and merge merges it. It starts no destroy run.")
    for r in routed:
        if r["route"] == "applier":
            parts.append(
                f"{r['tool']} ({r['tier']}) is not reachable by the destroy workflow: "
                f"{_applier_text(r['applier'])}. Its deletes wait for that apply."
            )
        elif r["route"] == "main":
            parts.append(
                f"This PR does not change {r['tool']} ({r['tier']}), so those deletes are already pending on main "
                "or the branch is behind. Nothing is started for them."
            )
    return " ".join(parts)


def _dispatch_destroys(pr, roots):
    """Start the destroy workflow (`destroy_workflow`) for each destroy-guarded root after the owner's sign-off merged the PR.
    The workflow plans from the default branch and waits in the destroy environment for the owner's approval. Tiers not in
    `dispatch_tiers` (default: the prod tier) are left to their own branch's apply. No workflow configured: nothing starts."""
    done = []
    for r in roots or []:
        tool, tier = r.get("tool"), r.get("tier")
        wf = _P("destroy_workflow", "")
        if not wf:
            done.append(f"{tool} ({tier}) destroy not started: no destroy workflow is configured")
            continue
        if tier not in (_P("dispatch_tiers") or [_tier("prod")]):
            done.append(
                f"{tool} ({tier}) destroy not started: that tier's destroys run from the branch"
            )
            continue
        try:
            _gh(
                [
                    "workflow",
                    "run",
                    wf,
                    "-R",
                    _repo(),
                    "--ref",
                    str(_P("default_branch", "main")),
                    "-f",
                    f"tool={tool}",
                    "-f",
                    f"tier={tier}",
                ],
                raw=True,
            )
            _log(
                {
                    "pr": pr,
                    "decision": "destroy_dispatched",
                    "tool": tool,
                    "tier": tier,
                    "by": _self(),
                }
            )
            done.append(
                f"started the destroy workflow for {tool} ({tier}), approve its plan under {_label('privileged_label', 'Privileged')}"
            )
        except ReviewError as e:
            _log(
                {
                    "pr": pr,
                    "decision": "destroy_dispatch_failed",
                    "tool": tool,
                    "tier": tier,
                    "detail": str(e)[:300],
                }
            )
            done.append(
                f"the destroy workflow for {tool} ({tier}) did not start ({str(e)[:150]}), run it from Actions"
            )
    return done


def _own_note(rec, head):
    """{status, reason} from the own-PR auto-merge lane for this head, else None."""
    if not rec or rec.get("head") != head or not rec.get("status"):
        return None
    return {
        "status": rec["status"],
        "reason": rec.get("reason", ""),
        # coverage reds the lane proved are only this head's own imports.
        "import_covered": list(rec.get("import_covered") or []),
        # the last check of a draft's gate (results, when it ran).
        "gate": rec.get("gate") or None,
    }


def _own_shipped(now):
    out = []
    for n, r in (_load(OWN_STATE, {}).get("prs") or {}).items():
        if r.get("status") != "merged" or now - _ts(r.get("merged_at")) > SHIPPED_DAYS * 86400:
            continue
        out.append(
            {
                "pr": int(n),
                "title": r.get("title"),
                "author": _self(),
                "url": r.get("url"),
                "head_sha": r.get("head"),
                "status": "merged",
                "when": r.get("merged_at"),
                "merged_at": r.get("merged_at"),
                "approved_by": "auto-merge",
            }
        )
    return out


AI_MARKER = str(rcfg.platform("ai_review_marker", ""))
AI_DATA_PREFIX = str(rcfg.platform("ai_review_data_prefix", ""))
AI_DATA_SUFFIX = " -->"
OVERRIDE_LABEL = str(rcfg.platform("override_label", ""))
_OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_RED = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"}


def _ai_verdict(pr):
    """Newest verdict embedded by the PR review workflow (github-actions[bot] only). No marker configured: None."""
    if not AI_MARKER or not AI_DATA_PREFIX:
        return None
    out = _gh(
        [
            "api",
            "--paginate",
            f"repos/{_repo()}/issues/{pr}/comments?per_page=100",
            "--jq",
            ".[] | @json",
        ],
        raw=True,
    )
    found = None
    for line in out.splitlines():
        if not line.strip():
            continue
        c = json.loads(line)
        body = c.get("body") or ""
        if (
            (c.get("user") or {}).get("login") == "github-actions[bot]"
            and body.startswith(AI_MARKER)
            and AI_DATA_PREFIX in body
        ):
            blob = body.split(AI_DATA_PREFIX, 1)[1].split(AI_DATA_SUFFIX, 1)[0]
            try:
                found = json.loads(base64.b64decode(blob).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                found = None
            if isinstance(found, dict):
                found["findings"] = [
                    {
                        "id": m.group(1),
                        "severity": m.group(2).lower(),
                        "title": m.group(3).strip(),
                        "location": m.group(4),
                    }
                    for m in _FINDING_ROW.finditer(body)
                ]
    return found


# One row of the review comment's findings table: | H1 | HIGH | title | `where` | reviewers |
_FINDING_ROW = re.compile(
    r"^\| ([BHML]\d+) \| (BLOCKING|HIGH|MEDIUM|LOW) \| (.+?) \| `([^`]*)` \|", re.M
)
TRIAGE_VERDICTS = {
    "accepted": "accepted",
    "refuted": "refuted",
    "fixed": "fixed on this branch",
    "deferred": "accepted for now, follow-up tracked",
}


def _review_verdict_ids(pr):
    """The newest verdict plus the high and blocking ids of its findings table (decision cards)."""
    v = _ai_verdict(pr)
    if v:
        v["finding_ids"] = [
            f["id"] for f in v.get("findings") or [] if f.get("severity") in ("blocking", "high")
        ]
    return v


def triage(payload):
    """The owner's triage reply on one of the owner's PRs, posted as me with the triage marker the
    own-PR lane reads. The reply is the owner's sign-off on the whole review, so the marker names every high and
    blocking id of this head (the lane clears only the ids a marker names). Every blocking and high finding of the review on this exact head needs a
    verdict and a reason. Refuses a moved head, someone else's PR, or a review for another head."""
    _repo()
    _self()  # the null default: nothing configured is a 501 before anything is read
    try:
        pr = int(payload.get("pr"))
    except (TypeError, ValueError):
        raise ReviewError("pr required", 400) from None
    head = payload.get("head_sha") or ""
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ReviewError("head_sha required (40 hex)", 400)
    live = _verify_head(pr, head)
    if (live.get("user") or {}).get("login") != _self():
        raise ReviewError(f"PR #{pr} is not mine. Engineer PRs get triaged by their author.", 403)
    v = _ai_verdict(pr)
    if not v or v.get("head_sha") != head:
        raise ReviewError(
            f"The PR review has not run on {head[:8]} yet. Wait for it, then triage.", 409
        )
    need = [f for f in v.get("findings") or [] if f["severity"] in ("blocking", "high")]
    if not need:
        raise ReviewError("No blocking or high findings on this head, nothing to triage.", 409)
    got = {str(x.get("id")): x for x in payload.get("items") or [] if isinstance(x, dict)}
    lines = []
    for f in need:
        x = got.get(f["id"])
        verdict = (x or {}).get("verdict")
        reason = " ".join(str((x or {}).get("reason") or "").split())
        if verdict not in TRIAGE_VERDICTS or len(reason) < 10:
            raise ReviewError(
                f"{f['id']} needs a verdict and a reason of at least 10 characters.", 400
            )
        if _forbidden(reason):
            raise ReviewError(
                f"{f['id']}: the reason names tooling that never goes on a PR. Reword it.", 400
            )
        if not reason.endswith((".", "?", ")")):
            reason += "."
        lines.append(
            f"{f['id']} ({f['title'][:1].lower() + f['title'][1:]}): {TRIAGE_VERDICTS[verdict]}. {reason}"
        )
    n = len(need)
    body = (
        f"Triage of the {'finding' if n == 1 else f'{n} findings'} on this head.\n\n"
        + "\n\n".join(lines)
        + "\n\n"
        + decision_cards.triage_marker(
            head, decision_cards.marker_ids(v.get("counts"), [f["id"] for f in need])
        )
    )
    _gh(
        ["api", "-X", "POST", f"repos/{_repo()}/issues/{pr}/comments", "-f", f"body={body}"],
        raw=True,
    )
    _log(
        {
            "pr": pr,
            "decision": "triaged",
            "sha": head,
            "by": _self(),
            "items": {f["id"]: got[f["id"]]["verdict"] for f in need},
        }
    )
    with contextlib.suppress(OSError):
        MY_CACHE.unlink()
    return {
        "pr": pr,
        "done": [
            f"posted my triage of {', '.join(f['id'] for f in need)} on {head[:8]}",
            "the auto-merge lane re-checks it within 3 minutes",
        ],
    }


def _rollup(rollup):
    best = {}
    for c in rollup or []:
        name = c.get("name") or c.get("context") or "?"
        val = (c.get("conclusion") or c.get("state") or c.get("status") or "PENDING").upper()
        ts = c.get("startedAt") or ""
        if name not in best or ts >= best[name][0]:
            best[name] = (ts, val)
    vals = {k: v for k, (_, v) in best.items()}
    red = sorted(k for k, v in vals.items() if v in _RED)
    # WAITING = the job waits on an environment approval (a held terraform plan). Nothing is running.
    pending = sorted(
        k for k, v in vals.items() if v not in _OK and v not in _RED and v != "WAITING"
    )
    return vals, red, pending


MY_STALE_MAX_S = 15 * 60  # past this the cached list is too old to show, so the request waits
_MY_REFRESH = threading.Lock()


def _refresh_my_prs_bg():
    """Rebuild the The owner's PRs cache in the background, one rebuild at a time."""
    if not _MY_REFRESH.acquire(blocking=False):
        return

    def run():
        try:
            _build_my_prs(False)
        except Exception as e:  # noqa: BLE001 - the next request retries, the old list stays up
            print(f"[my-prs] background refresh failed: {e}", file=sys.stderr, flush=True)
        finally:
            _MY_REFRESH.release()

    threading.Thread(target=run, daemon=True).start()


def my_prs_epoch():
    return (_load(MY_CACHE, None) or {}).get("epoch")


def my_prs(force=False):
    """The owner's open PRs with their hold. Serves the cached list at once and refreshes it in the
    background once it is MY_TTL_S old, so the page never waits minutes on the engine checks.
    force=True (Approve and merge, triage) always re-derives everything live."""
    cached = _load(MY_CACHE, None)
    if cached and not force:
        age = time.time() - cached.get("epoch", 0)
        if age < MY_TTL_S:
            return cached["items"]
        if age < MY_STALE_MAX_S:
            _refresh_my_prs_bg()
            return cached["items"]
    return _build_my_prs(force)


def _signoff_card(item, c, escs, rules, plan, hold):
    """Records on the hold what a sign-off will bind to (signoff_hits, signoff_plan) and, when
    the owner already signed this PR off on an earlier head, narrows the card to what is new since."""
    try:
        so = tf_reviews.signoff_mod()
        hold["signoff_hits"] = [
            {k: e.get(k) for k in ("rule", "reason", "path", "fp", "cfp")} for e in escs
        ]
        hold["signoff_plan"] = so.plan_facts(plan)
        hold["signoff_confirm"] = so.confirm_needed(plan, item["pr"])
        rec = so.active(item["pr"], lane=so.OWN)
        if not rec:
            return hold
        rev = so.review(rec, escs, plan)
        if not rev["carried"]:
            return hold
        base = rec["head_sha"]
        hold["new_since"] = base
        hold["compare_url"] = f"https://github.com/{_repo()}/compare/{base}...{item['head_sha']}"
        hold["carried_rules"] = [r["plain"] for r, e in zip(rules, escs) if so.covers(rec, e)]
        hold["rules"] = [r for r, e in zip(rules, escs) if not so.covers(rec, e)]
        hold["plan_new"] = rev["plan_new"]
        if rev["ok"]:
            return {
                "kind": "waiting",
                "summary": f"My sign-off on {base[:8]} covers every held change on this head and its plan adds "
                "no destroy, replace or grant. The lane merges it on its next pass.",
            }
        bits = [r["plain"] for r in hold["rules"]] + [f"the plan {p}" for p in rev["plan_new"]]
        hold["summary"] = (
            f"Everything passes. It waits only on your sign-off for what is new since my review of {base[:8]}: "
            + ", ".join(bits)[:400]
            + "."
        )
        return hold
    except Exception as e:  # noqa: BLE001 - display only, the full card still shows
        hold["signoff_error"] = str(e)[:150]
        return hold


def _accept_risk_flag(it):
    """it['can_accept_risk'] is true when the review for this head is blocked, the owner's triage on this
    head names every blocking id and the override label is not on yet. A read error leaves it false and
    the click re-verifies anyway. Once the label is on and the triage covers it, a stale lane hold says so."""
    it["can_accept_risk"] = False
    if it.get("verdict") != "blocked":
        return
    lines = label_hold.comment_lines(_gh, _repo(), it["pr"])
    triaged = (
        None if lines is None else label_hold.triaged_from_comments(lines, it["head_sha"], _self())
    )
    ar = label_hold.accept_risk(it, triaged)
    try:
        # the approval brief reads the owner's triage replies and who applied the override from here.
        it["triage"] = label_hold.triage_context(
            _gh, _repo(), it["pr"], it["head_sha"], _self(), it.get("labels") or []
        )
    except Exception:  # noqa: BLE001 - context for the brief only
        it["triage"] = None
    it["can_accept_risk"] = ar["ok"]
    hold = it.get("hold") or {}
    if (
        ar["ok"]
        and hold.get("kind") == "problem"
        and not hold.get("label_hold")
        and "blocking finding" in (hold.get("summary") or "")
    ):
        hold["next"] = (
            f"My triage answers {', '.join(ar['ids'])} on this head. Accept the risk applies {OVERRIDE_LABEL}, "
            "then the card shows Approve and merge."
        )
    elif (
        OVERRIDE_LABEL in (it.get("labels") or [])
        and triaged is not None
        and not ar["missing"]
        and hold.get("kind") == "problem"
    ):
        hold["next"] = (
            f"{OVERRIDE_LABEL} is on and my triage covers it. The lane re-checks within 3 minutes."
        )


def _mine_needs_me(m):
    """One of the owner's own PRs that has an action for me right now, so it is on Needs me and in its
    counts. Mirrors olyMineNeedsMe in src/lib/ownPrs.ts: a policy hold (Approve and merge), a direction or
    decision card, a blocked review the owner's triage covers (Accept the risk), or a hold label with nothing else
    behind it (Remove hold label). Checks running, a live session on the PR, auto-fix running and a wait
    on another PR keep it off (the waiting ones are listed apart and not counted)."""
    h = m.get("hold") or {}
    kind = h.get("kind")
    if kind not in ("policy", "direction", "problem") or m.get("pending") or m.get("deps"):
        return False
    af = m.get("autofix") or {}
    if af.get("session") or (h.get("autofix") or {}).get("session"):
        return False
    if kind in ("policy", "direction"):
        return True
    if (h.get("autofix") or af).get("state") in ("running", "deferred"):
        return False
    if not m.get("verdict") and not m.get("ai_result"):
        return False
    return bool(m.get("can_accept_risk") or (h.get("label_hold") or {}).get("clear"))


def _hold_one(it, fresh):
    _LIVE.fresh = fresh
    try:
        it["hold"] = _hold(it)
        _accept_risk_flag(it)
    except Exception as e:  # noqa: BLE001 - one bad PR must not take the tab down
        it["hold"] = {"kind": "waiting", "summary": f"Could not classify this PR: {str(e)[:150]}"}
    finally:
        _LIVE.fresh = False


def _build_my_prs(force):
    prs = _gh(
        [
            "pr",
            "list",
            "-R",
            _repo(),
            "--author",
            _self(),
            "--state",
            "open",
            "--limit",
            "50",
            "--json",
            "number,title,url,headRefOid,headRefName,isDraft,mergeStateStatus,mergeable,statusCheckRollup,labels,createdAt",
        ]
    )
    bump = _load(BUMP_STATE, {}).get("prs", {})
    own_st = _load(OWN_STATE, {})
    own = own_st.get("prs", {})
    items = []
    for p in prs:
        # gh pr list caps the rollup at 100 contexts. Past that the newest results
        # can be missing, so read the full list from gh pr view.
        if len(p.get("statusCheckRollup") or []) >= 100:
            full = (
                _gh(["pr", "view", str(p["number"]), "-R", _repo(), "--json", "statusCheckRollup"])
                or {}
            )
            if full.get("statusCheckRollup"):
                p["statusCheckRollup"] = full["statusCheckRollup"]
        vals, red, pending = _rollup(p.get("statusCheckRollup"))
        try:
            v = _ai_verdict(p["number"])
        except ReviewError:
            v = None
        if v and v.get("head_sha") != p["headRefOid"]:
            v = None
        is_bump = "-review-model-bump-" in (p.get("headRefName") or "")
        note = (bump.get(str(p["number"])) or {}).get("reported", "") if is_bump else ""
        items.append(
            {
                "pr": p["number"],
                "title": p["title"],
                "url": p["url"],
                "head_sha": p["headRefOid"],
                "branch": p.get("headRefName"),
                "draft": p.get("isDraft"),
                "created": p.get("createdAt"),
                "merge_state": p.get("mergeStateStatus"),
                "mergeable": p.get("mergeable"),
                "labels": [lbl.get("name") for lbl in p.get("labels") or []],
                "ai_result": vals.get(_P("ai_review_check_name", "")),
                "verdict": (v or {}).get("verdict"),
                "counts": (v or {}).get("counts") or {},
                "blocking": (v or {}).get("blocking") or [],
                "findings": [
                    f
                    for f in (v or {}).get("findings") or []
                    if f["severity"] in ("blocking", "high")
                ],
                "red": red,
                "pending": pending,
                "waiting": sorted(k for k, val in vals.items() if val == "WAITING"),
                "model_bump": is_bump,
                "bump_note": note.split(":", 1)[0] if note else "",
                "auto_merge": _own_note(own.get(str(p["number"])), p["headRefOid"]),
                "autofix": own_lane.autofix_or_session(
                    own_st, p["number"], p["headRefOid"], "prod", p.get("headRefName")
                ),
            }
        )
    # The engine checks are independent subprocesses, so run them side by side.
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda it: _hold_one(it, force), items))
    items.sort(key=lambda x: x.get("created") or "", reverse=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = MY_CACHE.with_suffix(f".{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps({"epoch": time.time(), "items": items}))
    os.replace(tmp, MY_CACHE)
    return items


def approve_merge(payload):
    """The owner's sign-off on one of the owner's PRs that waits only on policy rules (for example a role grant to a
    user or group). Re-derives the hold live and refuses anything that is a real problem (red
    checks, untriaged findings, conflict, open threads, draft). Merges with the maintainer bypass,
    pinned to the head the owner saw."""
    _repo()
    _self()  # the null default: nothing configured is a 501 before anything is read
    try:
        pr = int(payload.get("pr"))
    except (TypeError, ValueError):
        raise ReviewError("pr required", 400) from None
    head = payload.get("head_sha") or ""
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ReviewError("head_sha required (40 hex)", 400)
    try:
        live = _verify_head(pr, head)
    except AlreadyClosed as e:
        if e.merged:
            _drop_my_cache()
            return {"pr": pr, "done": [f"#{pr} was already merged"], "already": True}
        raise
    if (live.get("user") or {}).get("login") != _self():
        raise ReviewError(f"PR #{pr} is not mine. Engineer PRs go through Approve.", 403)
    item = next((x for x in my_prs(force=True) if x.get("pr") == pr), None)
    if not item or item.get("head_sha") != head:
        raise ReviewError(f"PR #{pr} moved since you loaded it. Refresh first.", 409)
    hold = item.get("hold") or {}
    if hold.get("kind") != "policy":
        raise ReviewError(
            f"PR #{pr} is not waiting on a sign-off. {hold.get('summary', '')} {hold.get('next', '')}".strip(),
            409,
        )
    dep_guard(pr, payload)
    # this click is the one sign-off for the PR. Record it bound to what the card showed, then
    # approve the PR's plan waits on this head with it (no second click). Neither can block
    # the merge: it is already the owner's explicit decision.
    notes, so_id = [], None
    try:
        so = tf_reviews.signoff_mod()
        # the merge below is pinned to this head, so the plan on this card (rebuilt live for this
        # exact head just above) is the plan of the merged head. The sign-off also covers the post-merge
        # privileged apply when that plan is final and readable, and (destroys or Entra types) only when
        # the confirm name was typed. The card keeps Approve and merge off until it is typed.
        facts = hold.get("signoff_plan")
        need = hold.get("signoff_confirm")
        typed = (payload.get("confirm_name") or "").strip()
        apply_ok, apply_why = (
            bool(facts and facts.get("final") and not facts.get("unverifiable")),
            None,
        )
        if not apply_ok:
            apply_why = "no final readable plan on this head"
        elif need and typed != need:
            apply_ok, apply_why = (
                False,
                f"the plan holds destroys or Entra grants, type {need} to cover the apply",
            )
        so_id = so.record(
            pr,
            head,
            so.OWN,
            "approve_merge",
            hold.get("signoff_hits") or hold.get("rules") or [],
            facts,
            extra={
                "apply_ok": apply_ok,
                "apply_why": apply_why,
                "confirm_name": need if (need and typed == need) else None,
                "plan_head": head,
            },
        )["id"]
    except Exception as e:  # noqa: BLE001
        notes.append(f"could not record the sign-off: {e}"[:200])
    try:
        line = tf_reviews.approve_for_signoff(pr, head)
        if line:
            notes.append(line)
    except Exception as e:  # noqa: BLE001
        notes.append(f"could not approve the plan waits: {e}"[:200])
    _gh(
        [
            "pr",
            "merge",
            str(pr),
            "-R",
            _repo(),
            *[str(f) for f in _P("merge_flags", ["--rebase", "--admin"])],
            "--match-head-commit",
            head,
        ],
        raw=True,
    )
    review_acted.record(_repo(), pr, head, "merged", title=item.get("title") or "")
    _log(
        {
            "pr": pr,
            "decision": "approved_policy_hold",
            "sha": head,
            "by": _self(),
            "rules": [r.get("rule") for r in hold.get("rules") or []],
            **({"signoff": so_id} if so_id else {}),
        }
    )
    done = (
        [f"approved and merged #{pr} at {head[:8]}"]
        + notes
        + _dispatch_destroys(pr, hold.get("destroy_roots"))
    )
    # runbook-root deletes are released from Needs me once the main deploy run stops on its guard.
    for r in hold.get("destroy_routes") or []:
        if r.get("route") == "applier" and r.get("applier") == "runbooks":
            try:
                done.append(
                    runbook_releases.record(
                        pr,
                        item.get("title"),
                        item.get("url"),
                        r.get("tier"),
                        hold.get("plan_run_id"),
                        head,
                    )
                )
            except Exception as e:  # noqa: BLE001 - the merge already happened, never fail the response
                done.append(f"could not record the runbook deletes: {e}"[:200])
    _drop_my_cache()
    return {"pr": pr, "done": done}


def _drop_my_cache():
    live_truth.invalidate()
    pr_deps.invalidate()
    with contextlib.suppress(OSError):
        MY_CACHE.unlink()


def _needs_override(pr, head):
    """True when the PR review gate is red on a blocked verdict for this head."""
    v = _gh(["pr", "view", str(pr), "-R", _repo(), "--json", "statusCheckRollup,labels"])
    vals, _, _ = _rollup(v.get("statusCheckRollup"))
    if vals.get(_P("ai_review_check_name", "")) not in _RED:
        return False
    if OVERRIDE_LABEL in [lbl.get("name") for lbl in v.get("labels") or []]:
        return False
    verdict = _ai_verdict(pr)
    return bool(
        verdict
        and verdict.get("head_sha") == head
        and verdict.get("verdict") in ("blocked", "unavailable")
    )


def _need_phase(n, heads):
    """needs_me only when Approve as me / Request changes could go through right now.
    gone = the PR closed or merged. in_flight = a new head waits on the review lane, or the held plan
    run stopped waiting (the gate clears or re-queues it within one pass). Unknown = show it."""
    pr = n.get("pr")
    if heads is not None and pr is not None:
        if pr not in heads:
            return "gone", "the PR is no longer open"
        if heads[pr] != n.get("head_sha"):
            return (
                "in_flight",
                f"new commits ({heads[pr][:8]}) since this was queued, the review lane re-checks them",
            )
    tfp = n.get("tfplan")
    if tfp and tfp.get("run_ids") and n.get("sources") == ["tfplan"]:
        states = [live_truth.run(_repo(), r) for r in tfp["run_ids"][-3:]]
        if all(s is not None for s in states) and not any(
            s.get("status") == "waiting" and _P("plan_environment", "") in (s.get("envs") or [])
            for s in states
        ):
            return (
                "in_flight",
                "the plan run no longer waits on approval, the gate clears it on its next pass",
            )
    return "needs_me", None


def _plan_gate_text(mine, tf):
    """say where a plan approval on one of the owner's PRs really sits. The gate either shows it on
    Needs me (pending), keeps it off while a session works the PR (parked), or has not seen the run
    yet (it auto-approves ordinary plans every 2 minutes). Returns new rows, never mutates input."""
    pending = {(p.get("pr"), p.get("head_sha")) for p in tf.get("pending") or []}
    parked = {(p.get("pr"), p.get("head_sha")): p.get("why") or "" for p in tf.get("parked") or []}
    out = []
    for m in mine:
        h = m.get("hold") or {}
        if not h.get("plan_wait"):
            # another hold (do-not-merge, a review problem) owns the row text, but a plan
            # approval waiting on me must still say so on the row.
            n = len(m.get("waiting") or [])
            if n and h:
                key = (m.get("pr"), m.get("head_sha"))
                h = dict(h)
                if key in pending:
                    h["plan_line"] = (
                        f"{n} terraform check(s) wait on my plan approval. The card is on Needs me."
                    )
                else:
                    h["plan_line"] = (
                        f"{n} terraform check(s) wait on the plan environment. The plan gate takes them "
                        "within 2 minutes (ordinary plans are approved on their own, held ones go to Needs me)."
                    )
                out.append(dict(m, hold=h))
                continue
            out.append(m)
            continue
        key = (m.get("pr"), m.get("head_sha"))
        n = len(m.get("waiting") or [])
        h = dict(h)
        if key in pending:
            pass
        elif key in parked:
            why = parked[key].rstrip(".")
            h["plan_parked"] = why
            h["summary"] = (
                f"{n} terraform check(s) wait on my plan approval. The plan gate keeps the card off "
                f"Needs me for now: {why}."
            )
            h["next"] = (
                "Nothing to click yet. The card shows on Needs me within 2 minutes of that ending."
            )
        else:
            h["summary"] = (
                f"{n} terraform check(s) wait on the plan environment. The plan gate has not taken this "
                "run yet. It checks every 2 minutes and approves ordinary plans on its own."
            )
            h["next"] = "Nothing to click unless it lands on Needs me."
        out.append(dict(m, hold=h))
    return out


def _superseded(n, heads):
    """A plan-only card queued for a head the PR has moved past. Unknown heads keep it."""
    pr = n.get("pr")
    return bool(
        heads is not None
        and pr in heads
        and heads[pr] != n.get("head_sha")
        and n.get("sources") == ["tfplan"]
    )


def needs_me_rows(need_list, mine_need, priv_need, owner_need, release_need):
    """One row per Needs me item, the same items counts.needs_me adds up, so the Action
    Center lists each one (what it is and what the owner have to do) and links to its card on Reviews. A row
    leaves the moment its card leaves Needs me. Never raises on a missing field."""
    rows = []
    for n in need_list:
        plan_only = (n.get("sources") or []) == ["tfplan"]
        rows.append(
            {
                "kind": "plan" if plan_only else "review",
                "pr": n.get("pr"),
                "title": n.get("title") or "",
                "what": "Approve its terraform plan run"
                if plan_only
                else "Review the escalated PR",
            }
        )
    for m in mine_need:
        h = m.get("hold") or {}
        what = {
            "policy": "Approve and merge (the owner's PR, held by policy)",
            "direction": "Give the decision it asks for"
            if h.get("decision")
            else "Give it direction",
        }.get(
            h.get("kind"),
            "Accept the risk" if m.get("can_accept_risk") else "Remove the hold label",
        )
        rows.append(
            {"kind": "mine", "pr": m.get("pr"), "title": m.get("title") or "", "what": what}
        )
    for p in priv_need:
        rows.append(
            {
                "kind": "privileged",
                "pr": _priv_pr(p),
                "title": p.get("workflow_name") or p.get("workflow") or "",
                "what": f"Approve the {p.get('env_label') or p.get('environment') or 'privileged'} run",
            }
        )
    for o in owner_need:
        rows.append(
            {
                "kind": "owner",
                "pr": None,
                "title": f"{o.get('name') or 'root'} ({o.get('tier') or ''})",
                "what": "Owner apply only the owner can run",
            }
        )
    for r in release_need:
        rows.append(
            {
                "kind": "release",
                "pr": r.get("pr"),
                "title": r.get("title") or "",
                "what": "Release its runbook deletes",
            }
        )
    return rows


def _priv_pr(p):
    v = p.get("pr")
    return v.get("number") if isinstance(v, dict) else v


def _dep_views(mine, needs, priv, owner_items):
    """{pr: dependency view} for every PR that waits on an unmet parent (pr_deps). Never raises."""
    try:
        return pr_deps.evaluate(pr_deps.snapshot(), owner_items or [], mine, needs, priv)
    except Exception as e:  # noqa: BLE001 - unknown never hides a card, so no view means no hold
        print(f"[pr-deps] evaluate failed: {e}", file=sys.stderr, flush=True)
        return {}


def _draft_plan_line(m):
    """A parked draft's plan line says the approvals come after its gate, never a click now."""
    h = dict(m.get("hold") or {})
    n = len(m.get("waiting") or [])
    for k in ("plan_line", "plan_wait"):
        h.pop(k, None)
    if n:
        h["plan_line"] = (
            f"{n} terraform check(s) wait on the plan gate. They come after the draft's gate, nothing to approve now."
        )
    return dict(m, hold=h)


def _split_waiting(need_list, deps):
    """Needs me cards whose PR waits on another PR move to needs_waiting (phase waiting_dep)."""
    keep, waiting = [], []
    for n in need_list:
        v = deps.get(n.get("pr"))
        if v:
            waiting.append(dict(n, phase="waiting_dep", deps=v, blocked=v["lines"][0]))
        else:
            keep.append(n)
    return keep, waiting


def _mine_deps(mine, deps, carded=()):
    """The owner's PRs rows carry their dependency view, and the plan line no longer says the card is on
    Needs me when it waits on another PR. Returns new rows, never mutates input."""
    out = []
    for m in mine:
        v = deps.get(m.get("pr"))
        if not v:
            out.append(m)
            continue
        h = dict(m.get("hold") or {})
        first = ", ".join("#" + str(x) for x in v["first"])
        n = len(m.get("waiting") or [])
        if n and (h.get("plan_line") or h.get("plan_wait")):
            where = (
                "so the card is off the Needs me count. Approve anyway is on Needs me under Waiting on another PR."
                if m.get("pr") in carded
                else "so nothing needs a click yet. The plan gate holds the runs."
            )
            line = f"{n} terraform check(s) wait on my plan approval, but this PR waits on {first} first, {where}"
            if h.get("plan_wait"):
                h["summary"] = line
                h["next"] = f"Do {first} first. The plan card returns on Needs me once it clears."
            else:
                h["plan_line"] = line
        out.append(dict(m, hold=h, deps=v))
    return out


def dep_guard(pr, payload):
    """Click-time guard: a plan approval or merge for a PR that waits on an unmet parent
    goes through only as Approve anyway. A failed read lets it through (the card was shown)."""
    if not pr or (payload or {}).get("anyway"):
        return
    try:
        snap = pr_deps.snapshot()
        own = (owner_roots.get() or {}).get("items") or []
        st = own_lane.load("prod")
        rec_head = ((st.get("prs") or {}).get(str(pr)) or {}).get("head")
        af = own_lane.autofix(st, pr, rec_head, "prod") if rec_head else None
        waits = pr_deps.blocking(int(pr), snap, own, (af or {}).get("waits_on"))
    except Exception:  # noqa: BLE001 - fail open, the card was already shown as actionable
        return
    if waits:
        names = ", ".join(f"#{w}" for w in waits)
        raise ReviewError(
            f"PR #{pr} waits on {names}, so its plan will likely fail or be redone. Use Approve anyway if you mean it.",
            409,
        )


def _merge_pending_view(it):
    """live-actions 1.9. An approval the backend accepted for later (merge queue, auto-merge) is not
    shipped yet. A direct read of the PR decides what the row is: ("pending", text) while it sits in
    the queue or has auto-merge armed (an unreadable PR stays pending, unknown never hides),
    ("ejected", text) when it is open at the same head and neither, None once it is merged or closed
    or has a new head (the end state, the normal shipped or new-work paths take over)."""
    mp = it.get("merge_pending")
    if it.get("status") != "approved" or not mp or mp.get("head") != it.get("head_sha"):
        return None
    st = live_truth.pr_state(_repo(), it.get("pr"))
    if st is None:
        return (
            "pending",
            f"{mp.get('text') or 'merge accepted'}, waiting for GitHub to confirm the end state",
        )
    if st.get("state") != "OPEN" or st.get("head_sha") != mp.get("head"):
        return None
    if st.get("in_queue") or st.get("auto_merge"):
        pos = st.get("position")
        what = (
            f"in the merge queue (position {pos})"
            if st.get("in_queue") and pos
            else mp.get("text") or "merge accepted"
        )
        return "pending", f"{what}, it leaves this list when GitHub shows it merged"
    return "ejected", "left the merge queue without merging, approve again to requeue it"


def _newest(*stamps):
    vals = [s for s in stamps if s]
    return max(vals) if vals else None


def _empty_page():
    counts = {
        k: 0
        for k in (
            "needs_me",
            "runbook_releases",
            "owner_roots",
            "my_prs_need",
            "prs",
            "privileged",
            "apply_failed",
            "in_progress",
            "held_for_window",
            "shipped",
            "my_prs",
            "waiting_on_prs",
            "secrets_pending",
        )
    }
    page = {
        k: []
        for k in (
            "my_prs",
            "needs_me",
            "needs_in_flight",
            "needs_waiting",
            "needs_threads",
            "superseded_runs",
            "in_progress",
            "held_for_window",
            "shipped",
            "privileged",
            "privileged_recent",
            "runbook_releases",
            "acted",
            "needs_me_rows",
        )
    }
    return dict(
        page,
        counts=counts,
        generated_utc=_now(),
        configured=False,
        my_prs_error=None,
        my_prs_refreshed=None,
        queue_updated=None,
        deps={},
        held_for_window_error=None,
        privileged_health={},
        waiting_on_others={"secrets": {}},
        owner_roots=None,
        runbook_releases_error=None,
    )


def get():
    if not rcfg.plan_repo():
        return _empty_page()  # the null default: nothing configured
    q = _load(QUEUE, {"items": {}})
    tf = tf_reviews.get()
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    needs, progress, shipped = {}, [], []
    for k, it in q.get("items", {}).items():
        st = it.get("status")
        base = {
            k2: it.get(k2)
            for k2 in (
                "pr",
                "title",
                "author",
                "url",
                "head_sha",
                "open_findings",
                "last_action",
                "last_action_at",
                "rounds",
                "plan",
                "first_seen",
                "confirm_needed",
                "merge_error",
            )
        }
        if st == "escalated":
            esc = it.get("escalation") or {}
            needs[str(it["pr"])] = dict(
                base,
                key=f"review-{k}",
                sources=["review"],
                since=it.get("escalated_at") or it.get("updated"),
                breakdown=esc,
                tfplan=None,
                window=_need_window(it),
            )
        elif st in ("in_progress", "changes_requested"):
            progress.append(dict(base, status=st, findings=it.get("findings", [])))
        elif st in ("approved", "merged"):
            mpv = _merge_pending_view(it) if st == "approved" else None
            if mpv:
                kind, text = mpv
                mp = it["merge_pending"]
                row = dict(
                    base,
                    key=f"review-{k}",
                    sources=["review"],
                    since=mp.get("at") or it.get("updated"),
                    breakdown=it.get("escalation") or {},
                    tfplan=None,
                    merge_pending=dict(mp, text=text, state=kind),
                )
                if kind == "ejected":
                    row["merge_error"] = [text]
                    row["window"] = _need_window(it)
                needs[str(it["pr"])] = row
                continue
            when = it.get("merged_at") or it.get("shipped_at") or it.get("updated")
            if now - _ts(when) <= SHIPPED_DAYS * 86400:
                shipped.append(
                    dict(
                        base,
                        status=st,
                        when=when,
                        merged_at=it.get("merged_at"),
                        approved_by=it.get("approved_by", "automation"),
                    )
                )
    for it in tf.get("pending", []):
        key = it["key"] if it.get("pr") is None else str(it["pr"])
        tfp = {
            "key": it["key"],
            "held_reasons": it.get("held_reasons", []),
            "files": it.get("files", []),
            "run_ids": it.get("run_ids", []),
            "assessment": it.get("assessment"),
            "head_sha": it.get("head_sha"),
            # The gate never hides a held plan any more (10/16). A session working the PR is a note.
            "working": it.get("working"),
            "new_held": it.get("new_held"),
            # the newly held files' diff since the owner's approved head (display only).
            "held_delta": it.get("held_delta"),
        }
        if key in needs:
            n = needs[key]
            n["sources"].append("tfplan")
            n["tfplan"] = tfp
            if _ts(it.get("first_seen")) and _ts(it.get("first_seen")) < _ts(n.get("since")):
                n["since"] = it.get("first_seen")
        else:
            needs[key] = {
                "key": f"tfplan-{it['key']}",
                "pr": it.get("pr"),
                "title": it.get("title"),
                "author": it.get("author"),
                "url": it.get("url"),
                "head_sha": it.get("head_sha"),
                "sources": ["tfplan"],
                "since": it.get("first_seen"),
                "breakdown": _tf_breakdown(it),
                "tfplan": tfp,
                "plan": None,
            }
    # Tombstones: a PR the owner just merged or approved stays hidden until GitHub and the lanes agree.
    tomb = review_acted.active(_repo())
    heads = live_truth.pr_heads(_repo())
    need_list, need_flight, superseded = [], [], []
    for n in sorted(needs.values(), key=lambda x: x.get("since") or ""):
        mpend = n.get("merge_pending")
        if mpend and mpend.get("state") == "pending":
            # live-actions 1.9: queued for merge, in flight with no actions until the end state.
            n["phase"], n["blocked"] = "in_flight", mpend["text"]
            need_flight.append(n)
            continue
        if not mpend and review_acted.hides(tomb, n.get("pr"), n.get("head_sha")):
            continue
        if _superseded(n, heads):
            # plan runs of an older head can never be the ones that merge. Only the current
            # head's runs are shown, and the gate queues those as their own card.
            superseded += [int(r) for r in (n.get("tfplan") or {}).get("run_ids") or []]
            continue
        n["phase"], n["blocked"] = _need_phase(n, heads)
        if n["phase"] == "needs_me":
            need_list.append(n)
        elif n["phase"] == "in_flight":
            need_flight.append(n)
    try:
        priv = privileged_reviews.get()
    except Exception as e:  # noqa: BLE001 - never take the page down over the privileged lane
        priv = {
            "pending": [],
            "recent": [],
            "secrets": {"status": "error", "error": str(e), "items": []},
            "health": {},
        }
    progress.sort(key=lambda x: x.get("last_action_at") or "", reverse=True)
    # engineer PRs approved but waiting for their maintenance window.
    try:
        held, held_err = maintenance_hold.held_cards(_load(POLICY, {}), HELD, heads), None
    except Exception as e:  # noqa: BLE001 - never take the page down over this list
        held, held_err = [], str(e)[:300]
    held_prs = {h["pr"] for h in held}
    progress = [p for p in progress if p.get("pr") not in held_prs]
    seen_shipped = {s.get("pr") for s in shipped}
    shipped += [s for s in _own_shipped(now) if s["pr"] not in seen_shipped]
    shipped.sort(key=lambda x: x.get("when") or "", reverse=True)
    health = _load(HEALTH, {})
    pol = _load(POLICY, {})
    try:
        mine, mine_err = my_prs(), None
    except Exception as e:  # noqa: BLE001 - never take the page down over this tab
        mine, mine_err = [], str(e)[:300]
    # Only a merge or a close ends one of the owner's PRs. An "approved" tombstone on the owner's PR means the owner approved
    # its held plan runs (GitHub never lets me approve the owner's own PR), so the PR stays on The owner's PRs.
    mine_tomb = {k: v for k, v in tomb.items() if v.get("outcome") in ("merged", "closed")}
    mine = [m for m in mine if not review_acted.hides(mine_tomb, m.get("pr"), m.get("head_sha"))]
    mine = _plan_gate_text(mine, tf)
    # Owner-applied roots with a pending plan, a failed plan or apply, or an expired
    # sign-in are the owner's action (only the owner apply account can apply them).
    try:
        owner = owner_roots.get()
    except Exception as e:  # noqa: BLE001 - never take the page down over this lane
        owner = {"items": [], "running": False, "error": str(e)[:300]}
    owner_need = owner_roots.needs_me(owner)
    # a plan approval or a merge for a PR that waits on another PR cannot pass yet. Those
    # cards leave Needs me and its count, say what to do first, and keep only Approve anyway.
    deps = _dep_views(mine, need_list, priv.get("pending", []), owner.get("items"))
    need_list, need_waiting = _split_waiting(need_list, deps)
    need_list, need_threads = _split_threads(need_list, _load(THREAD_WAITS, {"items": {}}))
    for p in priv.get("pending", []):
        v = deps.get(_priv_pr(p))
        if (
            v
            and p.get("phase", "needs_me") == "needs_me"
            and p.get("status") != "blocked_failed_apply"
        ):
            p["phase"], p["deps"], p["blocked"] = "waiting_dep", v, v["lines"][0]
    priv_need = [p for p in priv.get("pending", []) if p.get("phase", "needs_me") == "needs_me"]
    mine = _mine_deps(mine, deps, {n.get("pr") for n in need_waiting})
    # a draft is parked until its gate is met, so its plan approvals are not the owner's
    # action yet. They leave Needs me and the row says they come after the gate.
    drafts = {m.get("pr") for m in mine if m.get("draft")}
    need_list = [
        n for n in need_list if not (n.get("pr") in drafts and n.get("sources") == ["tfplan"])
    ]
    need_waiting = [
        n for n in need_waiting if not (n.get("pr") in drafts and n.get("sources") == ["tfplan"])
    ]
    mine = [_draft_plan_line(m) if m.get("draft") else m for m in mine]
    # The owner's PRs the own-PR lane holds for me by policy ("needs me: RULE"), and the ones auto-fix gave
    # up on, are the owner's action too, so they count toward Needs me (sidebar badge, Action Center banner)
    # and render on the Needs me tab. Not while checks still run: the hold can change when they finish.
    # Not while it waits on another PR either: the row shows Approve anyway instead.
    mine_need = [
        m
        for m in mine
        if _mine_needs_me(m)
        and not (heads and m.get("pr") in heads and heads[m["pr"]] != m.get("head_sha"))
    ]
    # runbook-root deletes waiting on Release deletes (or a release that went wrong).
    try:
        releases, releases_err = runbook_releases.items(), None
    except Exception as e:  # noqa: BLE001 - never take the page down over this lane
        releases, releases_err = [], str(e)[:300]
    release_need = runbook_releases.needs_me(releases)
    rows_need = needs_me_rows(need_list, mine_need, priv_need, owner_need, release_need)
    return {
        "my_prs": mine,
        "my_prs_error": mine_err,
        "my_prs_refreshed": my_prs_epoch(),
        "generated_utc": _now(),
        # the review queue file is gone since pipeline v2, so the footer read "never".
        # Show the newest write of either queue (the plan gate writes its own every 2 minutes).
        "queue_updated": _newest(q.get("updated"), tf.get("queue_updated")),
        "needs_me": need_list,
        "needs_in_flight": need_flight,
        # cards whose PR waits on another PR (not counted), and the superseded runs hidden.
        "needs_waiting": need_waiting,
        "needs_threads": need_threads,
        "superseded_runs": sorted(set(superseded)),
        "deps": {str(k): v for k, v in deps.items()},
        "in_progress": progress,
        "held_for_window": held,
        "held_for_window_error": held_err,
        "shipped": shipped,
        "privileged": priv.get("pending", []),
        "privileged_recent": priv.get("recent", []),
        "privileged_health": priv.get("health", {}),
        "waiting_on_others": {"secrets": priv.get("secrets", {})},
        "owner_roots": owner,
        "runbook_releases": releases,
        "runbook_releases_error": releases_err,
        "acted": review_acted.public(
            tomb,
            set(heads) if heads is not None else None,
            {r["pr"] for r in rows_need if r.get("pr")},
        ),
        "needs_me_rows": rows_need,
        "counts": {
            "needs_me": len(need_list)
            + len(priv_need)
            + len(mine_need)
            + len(owner_need)
            + len(release_need),
            "runbook_releases": len(release_need),
            "owner_roots": len(owner_need),
            "my_prs_need": len(mine_need),
            "prs": len(need_list),
            "privileged": len(priv_need),
            # Apply failed cards (a plan the owner already approved whose apply failed). They are on
            # Needs me and in its count, this is the split.
            "apply_failed": len(
                [p for p in priv_need if p.get("status") == "blocked_failed_apply"]
            ),
            "in_progress": len(progress),
            "held_for_window": len([h for h in held if h["phase"] == "held"]),
            "shipped": len(shipped),
            "my_prs": len(mine),
            "waiting_on_prs": len(need_waiting)
            + len([p for p in priv.get("pending", []) if p.get("phase") == "waiting_dep"])
            + len(
                [
                    m
                    for m in mine
                    if m.get("deps")
                    and (m.get("hold") or {}).get("kind") in ("policy", "direction")
                ]
            ),
            "secrets_pending": len((priv.get("secrets") or {}).get("items", [])),
        },
        "gate": {
            "failures": health.get("failures", 0),
            "updated": health.get("updated"),
            "last_error": health.get("last_error"),
            "last_audit_date": health.get("last_audit_date"),
        },
        "policy": {"path": str(POLICY), "version": pol.get("version")},
        "tf_decisions": tf.get("decisions", [])[:10],
    }


def _need_window(it):
    """what Approve would do on this engineer PR right now (held for the window or not)."""
    try:
        return maintenance_hold.need_view(_load(POLICY, {}), it, it.get("author"), _self())
    except Exception:  # noqa: BLE001 - the card still renders, decide() re-checks live
        return {"unknown": True, "held_on_approve": True, "brief": None}


def _set_queue_locked(pr, fields):
    """Caller holds LOCK."""
    q = _load(QUEUE, {"items": {}})
    it = q.setdefault("items", {}).get(str(pr)) or {"pr": pr, "first_seen": _now(), "history": []}
    it.update(fields)
    it["updated"] = _now()
    it["last_action_at"] = _now()
    if it.get("status") == "approved":
        it.setdefault("shipped_at", _now())
    it.setdefault("history", []).append(
        {
            "at": _now(),
            "status": it.get("status"),
            "action": fields.get("last_action", ""),
            "sha": it.get("head_sha"),
        }
    )
    it["history"] = it["history"][-30:]
    q["items"][str(pr)] = it
    q["updated"] = _now()
    _save_queue(q)


def _hold_io():
    return {
        "gh": _gh,
        "log": _log,
        "repo": _repo(),
        "self_login": _self(),
        "held_path": HELD,
        "overrides_path": WINDOW_OVERRIDES,
        "verify_head": _verify_head,
        "set_queue": _set_queue_locked,
    }


def _live_downtime(pr, head):
    """Downtime verdict for this head from a live engine check. Fails closed: an unreadable
    check is treated as downtime with an unknown system (waits for a window open to both classes)."""
    pol = _load(POLICY, {})
    if not (pol.get("maintenance_window") or {}).get("enabled"):
        return {"downtime": False}
    c = _engine_check(pr, head)
    d = (c or {}).get("downtime") if c and c.get("head_sha") == head else None
    if not d:
        d = {
            "downtime": True,
            "class": "both",
            "hits": [
                {
                    "kind": "check-failed",
                    "system": None,
                    "reason": "the owner could not re-check what this change takes down",
                }
            ],
        }
    if d.get("downtime"):
        d["in_window"] = maintenance_hold.mw().in_window(
            maintenance_hold.mw().cfg_of(pol), d.get("class") or "both", maintenance_hold.now_utc()
        )
    return d


def window_override(payload):
    """Merge now (ECR override) on a held card."""
    _repo()
    _self()  # the null default: nothing configured is a 501 before anything is read
    CACHE.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            r = maintenance_hold.override(_hold_io(), payload)
        except maintenance_hold.HoldError as e:
            raise ReviewError(str(e), e.code) from e
    review_acted.record(
        _repo(),
        r["pr"],
        payload.get("head_sha"),
        "approved",
        "ECR override",
        title=r.get("title") or "",
    )
    return r


def _verify_head(pr, head_sha):
    live = _gh(["api", f"repos/{_repo()}/pulls/{pr}"])
    if live.get("state") != "open":
        merged = bool(live.get("merged"))
        review_acted.record(
            _repo(), pr, head_sha, "merged" if merged else "closed", title=live.get("title") or ""
        )
        raise AlreadyClosed(pr, merged, live.get("title") or "")
    if head_sha and live["head"]["sha"] != head_sha:
        raise ReviewError(
            f"PR #{pr} head moved to {live['head']['sha'][:8]} since this was queued; wait for the next review pass",
            409,
        )
    return live


def _engineer_signoff(pr, head, rit, tf_pending, payload):
    """The owner's approval of an engineer PR is the one sign-off for it: the review, its terraform-plan
    waits on this head and its post-merge privileged apply when that apply's plan fingerprint equals the
    plan the owner saw here. If the plan holds destroys or Entra grants, the apply is only covered when the owner typed
    the confirm name on this card (the privileged card then does not ask again). Never blocks the
    approval. Returns lines for the response."""
    try:
        so = tf_reviews.signoff_mod()
        chk = _engine_check(pr, head) or {}
        plan = chk.get("plan") if isinstance(chk.get("plan"), dict) else None
        facts = so.plan_facts(plan)
        hits = [dict(h) for h in (rit or {}).get("escalations") or chk.get("escalations") or []]
        for it in tf_pending:
            hits += [dict(h) for h in it.get("hits") or []]
        need = so.confirm_needed(plan, pr)
        typed = (payload.get("confirm_name") or "").strip()
        ok, why = bool(facts and facts["final"] and not facts["unverifiable"]), None
        if not ok:
            why = "no final readable plan on this head"
        elif need and typed != need:
            ok, why = (
                False,
                f"the plan holds destroys or Entra grants, type {need} on this card to cover the apply",
            )
        so.record(
            pr,
            head,
            so.ENGINEER,
            "approve_card",
            hits,
            facts,
            extra={
                "apply_ok": ok,
                "apply_why": why,
                "confirm_name": need if (need and typed == need) else None,
            },
        )
        return [
            f"recorded my sign-off on {head[:8]}"
            + (" (covers the post-merge apply of the same plan)" if ok else "")
        ]
    except Exception as e:  # noqa: BLE001
        return [f"could not record the sign-off: {e}"[:200]]


def _split_threads(need_list, waits):
    """a card whose approval the owner gave while someone else's conversation was open moves to
    needs_threads (phase waiting_threads, not counted). It shows each open conversation with a
    Resolve button. A wait for another head is stale and stays off (the tick drops it)."""
    items = (waits or {}).get("items") or {}
    keep, waiting = [], []
    for n in need_list:
        w = items.get(str(n.get("pr")))
        if w and w.get("head_sha") == n.get("head_sha"):
            names = sorted(
                {t.get("starter") for t in w.get("threads") or [] if not t.get("automated")}
            )
            line = (
                f"I approved this. It merges once {len(w.get('threads') or [])} open conversation(s) are resolved"
                + (f" (waiting on {', '.join(names)})." if names else ".")
            )
            waiting.append(dict(n, phase="waiting_threads", threads_wait=w, blocked=line))
        else:
            keep.append(n)
    return keep, waiting


def _save_waits(w):
    STATE.mkdir(parents=True, exist_ok=True)
    w["updated"] = _now()
    tmp = THREAD_WAITS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(w, indent=2) + "\n")
    os.replace(tmp, THREAD_WAITS)


def _drop_wait(pr, why=None):
    """Caller holds LOCK."""
    w = _load(THREAD_WAITS, {"items": {}})
    if (w.get("items") or {}).pop(str(pr), None) is not None:
        _save_waits(w)
        if why:
            _log({"pr": pr, "decision": "thread_wait_dropped", "lane": "threads", "why": why})


def _thread_gate(pr, head, payload):
    """caller holds LOCK, before any GitHub write. None = no open conversation from anyone
    else, go ahead. Otherwise the owner's approval is held (nothing posted as a review), the authors are
    tagged once in one PR comment, and the response says so."""
    try:
        open_ = review_threads.read(_gh, _repo(), pr)
    except review_threads.ThreadError as e:
        raise ReviewError(f"{e}. Nothing was posted", 502) from e
    theirs = review_threads.others(open_, _self())
    if not theirs:
        _drop_wait(pr)
        return None
    done = []
    try:
        tagged = review_threads.notify(_gh, _repo(), pr, head, theirs, _self())
        if tagged:
            done.append("posted one comment on the PR tagging " + ", ".join(tagged))
        else:
            done.append("every open conversation was already named in the owner's earlier comment")
    except review_threads.ThreadError as e:
        done.append(str(e))
    keep = {
        k: payload.get(k)
        for k in ("text", "ecr_reason", "confirm_name", "anyway")
        if payload.get(k)
    }
    w = _load(THREAD_WAITS, {"items": {}})
    prev = (w.get("items") or {}).get(str(pr)) or {}
    w.setdefault("items", {})[str(pr)] = {
        "pr": pr,
        "head_sha": head,
        "by": _self(),
        "at": prev.get("at") if prev.get("head_sha") == head else _now(),
        "checked_at": _now(),
        "payload": keep,
        "threads": theirs,
    }
    _save_waits(w)
    names = sorted({t["starter"] for t in theirs if not t.get("automated")})
    _log(
        {
            "pr": pr,
            "decision": "approve_waiting_threads",
            "lane": "threads",
            "sha": head,
            "threads": [
                {"id": t["id"], "starter": t["starter"], "path": t["path"], "line": t["line"]}
                for t in theirs
            ],
        }
    )
    head_line = (
        f"not approved on GitHub yet: {len(theirs)} open conversation(s)"
        + (f" from {', '.join(names)}" if names else "")
        + ". Your approval is held and posts itself, with the merge, once they are resolved"
    )
    return {"pr": pr, "act": "approve", "done": [head_line] + done, "waiting_threads": True}


def resolve_thread(payload):
    """Resolve on a card, as me. Only an open thread on that PR. When it was the last open
    conversation of a held approval, the approval posts and the merge queues right away."""
    _repo()
    _self()  # the null default: nothing configured is a 501 before anything is read
    try:
        pr = int(payload.get("pr"))
    except (TypeError, ValueError):
        raise ReviewError("pr required", 400) from None
    tid = str(payload.get("thread_id") or "")
    CACHE.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            t = review_threads.resolve(_gh, _repo(), pr, tid)
        except review_threads.ThreadError as e:
            raise ReviewError(
                str(e), 409 if "not open" in str(e) else 400 if "required" in str(e) else 502
            ) from e
        _log(
            {
                "pr": pr,
                "decision": "thread_resolved_by_me",
                "lane": "threads",
                "thread": tid,
                "starter": t["starter"],
            }
        )
        w = _load(THREAD_WAITS, {"items": {}})
        it = (w.get("items") or {}).get(str(pr))
        if it:
            it["threads"] = [x for x in it.get("threads") or [] if x.get("id") != tid]
            _save_waits(w)
    done = [f"resolved {t['starter']}'s conversation on {t.get('path') or 'the PR'}"]
    if it is not None and not it["threads"]:
        done += _follow_through(pr)
    return {"pr": pr, "done": done}


def _follow_through(pr):
    """Re-run the owner's held approval for `pr` (decide re-checks everything, threads included).
    Never holds LOCK itself. Returns lines."""
    w = _load(THREAD_WAITS, {"items": {}})
    it = (w.get("items") or {}).get(str(pr))
    if not it:
        return []
    try:
        r = decide(dict(it.get("payload") or {}, pr=pr, head_sha=it["head_sha"]), "approve")
    except ReviewError as e:
        with open(LOCK, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            if e.code in (404, 409):
                _drop_wait(pr, f"held approval no longer applies: {e}")
            else:
                w = _load(THREAD_WAITS, {"items": {}})
                cur = (w.get("items") or {}).get(str(pr))
                if cur:
                    cur["last_error"] = str(e)[:300]
                    cur["tries"] = int(cur.get("tries") or 0) + 1
                    _save_waits(w)
        return [f"held approval did not go through: {e}"]
    if r.get("waiting_threads"):
        return ["still waiting: " + r["done"][0]]
    _log(
        {
            "pr": pr,
            "decision": "approved_after_threads",
            "lane": "threads",
            "sha": it["head_sha"],
            "done": r["done"],
        }
    )
    return ["conversations resolved, posted the owner's held approval: " + "; ".join(r["done"])]


def thread_wait_tick():
    """Server background pass. For each held approval: PR closed or a new push drops it
    (a new head comes back to me as a normal card), new open conversations get named once, and
    no open conversation from anyone else posts the approval and queues the merge."""
    w = _load(THREAD_WAITS, {"items": {}})
    out = []
    for k, it in list((w.get("items") or {}).items()):
        pr = int(k)
        try:
            live = _gh(["api", f"repos/{_repo()}/pulls/{pr}"])
        except ReviewError:
            continue
        if live.get("state") != "open" or (live.get("head") or {}).get("sha") != it.get("head_sha"):
            why = (
                "PR is no longer open"
                if live.get("state") != "open"
                else "new commits, the approval needs me again"
            )
            with open(LOCK, "w") as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                _drop_wait(pr, why)
            out.append(f"#{pr}: {why}")
            continue
        try:
            theirs = review_threads.others(review_threads.read(_gh, _repo(), pr), _self())
        except review_threads.ThreadError:
            continue
        if theirs:
            with contextlib.suppress(review_threads.ThreadError):
                review_threads.notify(_gh, _repo(), pr, it["head_sha"], theirs, _self())
            with open(LOCK, "w") as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                cur_all = _load(THREAD_WAITS, {"items": {}})
                cur = (cur_all.get("items") or {}).get(k)
                if cur and cur.get("head_sha") == it.get("head_sha"):
                    cur["threads"], cur["checked_at"] = theirs, _now()
                    _save_waits(cur_all)
            continue
        out.append(f"#{pr}: " + "; ".join(_follow_through(pr)))
    return out


def decide(payload, act):
    _repo()
    _self()  # the null default: nothing configured is a 501 before anything is read
    if act not in ("approve", "request-changes"):
        raise ReviewError("bad action", 400)
    try:
        pr = int(payload.get("pr"))
    except (TypeError, ValueError):
        raise ReviewError("pr required", 400) from None
    head = payload.get("head_sha") or ""
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ReviewError("head_sha required (40 hex)", 400)
    text = (payload.get("text") or "").strip()
    if text and _forbidden(text):
        raise ReviewError("text contains tool/assistant wording; rewrite it in your own voice", 400)
    if len(text) > 4000:
        raise ReviewError("text too long", 400)
    # an engineer PR that takes a system down merges in its window unless the owner file an ECR.
    ecr = None
    if act == "approve" and (payload.get("ecr_reason") or "").strip():
        try:
            ecr = maintenance_hold.clean_reason(payload)
        except maintenance_hold.HoldError as e:
            raise ReviewError(str(e), e.code) from e
    dtm = {"downtime": False}
    if act == "approve":
        try:
            pre_author = (
                (_gh(["api", f"repos/{_repo()}/pulls/{pr}"]) or {}).get("user") or {}
            ).get("login")
        except ReviewError:
            pre_author = None
        if pre_author != _self():
            dtm = _live_downtime(pr, head)

    CACHE.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        q = _load(QUEUE, {"items": {}})
        rit = q.get("items", {}).get(str(pr))
        # An approved PR that left the merge queue unmerged comes back with its actions (live-actions 1.9).
        rev_pending = bool(
            rit
            and (
                rit.get("status") == "escalated"
                or (rit.get("status") == "approved" and rit.get("merge_pending"))
            )
        )
        tf_pending = [it for it in tf_reviews.get().get("pending", []) if it.get("pr") == pr]
        if not rev_pending and not tf_pending:
            raise ReviewError(f"nothing for PR #{pr} is waiting on you", 404)
        if act == "approve":
            dep_guard(pr, payload)
        if rev_pending and rit.get("head_sha") and rit["head_sha"] != head:
            raise ReviewError(
                f"queued review is for {rit['head_sha'][:8]}, not {head[:8]}; refresh", 409
            )
        if tf_pending and not rev_pending and tf_pending[-1].get("head_sha") != head:
            raise ReviewError(
                f"queued plan hold is for {tf_pending[-1]['head_sha'][:8]}, not {head[:8]}; refresh",
                409,
            )
        try:
            live = _verify_head(pr, head)
        except AlreadyClosed as e:
            if rev_pending:
                rit["status"] = "merged" if e.merged else "closed"
                rit["updated"] = _now()
                rit["last_action"] = (
                    f"{'Merged' if e.merged else 'Closed'} before my decision landed"
                )
                if e.merged:
                    rit.setdefault("merged_at", _now())
                _save_queue(q)
            if e.merged and act == "approve":
                return {"pr": pr, "done": [f"#{pr} was already merged"], "already": True}
            raise
        author = (live.get("user") or {}).get("login")
        if act == "approve" and author != _self():
            waiting = _thread_gate(pr, head, payload)
            if waiting is not None:
                return waiting
        elif act != "approve":
            _drop_wait(pr, "the owner requested changes")
        done, step_failed = [], False
        held_now = False
        merge_pending = None
        if act == "approve":
            if author != _self() and _needs_override(pr, head):
                # The owner's approval of a PR the review gate blocked is the owner's override.
                _gh(["pr", "edit", str(pr), "-R", _repo(), "--add-label", OVERRIDE_LABEL], raw=True)
                done.append(f"applied {OVERRIDE_LABEL} (PR review gate was red)")
            held_now = (
                author != _self() and dtm.get("downtime") and not dtm.get("in_window") and not ecr
            )
            if held_now:
                try:
                    done += maintenance_hold.hold(
                        _hold_io(), _load(POLICY, {}), pr, head, live, dtm, text
                    )
                except maintenance_hold.HoldError as e:
                    raise ReviewError(str(e), e.code) from e
            elif author != _self():
                body = text or "Looks good to me. Approving."
                _gh(["pr", "review", str(pr), "-R", _repo(), "--approve", "--body", body], raw=True)
                done.append("approved review")
                try:
                    queued = merge_queue.enqueue(
                        _repo(), pr, head, gh=_gh, accept_own_threads=_self()
                    )
                    done.append(
                        queued["text"]
                        + (", now (ECR override)" if ecr and dtm.get("downtime") else "")
                    )
                    if queued.get("status") in ("queued", "auto"):
                        # live-actions 1.9: the merge was accepted for later, so the row is in flight
                        # until a direct read shows the end state (see _merge_pending_view).
                        merge_pending = {
                            "kind": queued["status"],
                            "head": head,
                            "text": queued["text"],
                            "position": queued.get("position"),
                            "at": _now(),
                        }
                    if ecr and dtm.get("downtime") and not dtm.get("in_window"):
                        maintenance_hold.record_override(
                            _hold_io(),
                            pr,
                            head,
                            ecr,
                            dtm.get("class"),
                            dtm.get("hits"),
                            "needs-me-card",
                        )
                        done.append(f"recorded ECR reason: {ecr}")
                except merge_queue.MergeQueueError as e:
                    # The card stays on Needs me with the reason, never a silent success.
                    step_failed = True
                    done.append(f"merge not queued: {e}")
            if author != _self() and not held_now:
                done += _engineer_signoff(pr, head, rit, tf_pending, payload)
            if tf_pending:
                try:
                    r = tf_reviews.decide(pr, "approved")
                    done.append(f"approved {len(r['runs'])} terraform-plan run(s)")
                except tf_reviews.ReviewError as e:
                    # A run still waits, so the card must stay on Needs me (no tombstone below).
                    step_failed = True
                    done.append(f"plan: {e}")
        else:
            with contextlib.suppress(
                Exception
            ):  # revoking is best effort, a sign-off is also head-pinned
                tf_reviews.signoff_mod().revoke(pr, "changes requested")
            if author != _self():
                body = text or _default_changes_text()
                _gh(
                    ["pr", "review", str(pr), "-R", _repo(), "--request-changes", "--body", body],
                    raw=True,
                )
                done.append("requested changes")
            if tf_pending:
                try:
                    r = tf_reviews.decide(pr, "rejected")
                    done.append(f"rejected {len(r['runs'])} terraform-plan run(s)")
                except tf_reviews.ReviewError as e:
                    done.append(f"plan: {e}")
        if rev_pending:
            q = _load(QUEUE, {"items": {}})
            it = q["items"][str(pr)]
            it["status"] = "approved" if act == "approve" else "changes_requested"
            it.pop("merge_error", None)
            it.pop("merge_pending", None)
            if merge_pending and not step_failed:
                it["merge_pending"] = merge_pending
            if act == "approve" and step_failed:
                # the approval posted but the merge did not queue. Stay on Needs me with the
                # reason, never in Recently shipped (a merged PR once looked shipped while it sat).
                it["status"] = "escalated"
                it["merge_error"] = [
                    d for d in done if d.startswith(("merge not queued", "plan:"))
                ] or done
            if act == "approve" and held_now:
                it["status"] = "held_for_window"
                it["downtime"] = dtm
            it["approved_by"] = _self() if act == "approve" else None
            it["decision"] = {
                "by": _self(),
                "act": act,
                "at": _now(),
                "sha": head,
                "text": text,
                "done": done,
            }
            it["last_action"] = (
                f"owner {'approved' if act == 'approve' else 'requested changes'} in the Ops Center"
            )
            it["last_action_at"] = _now()
            it["updated"] = _now()
            if act == "approve" and not step_failed:
                it.setdefault("shipped_at", _now())
            it.setdefault("history", []).append(
                {"at": _now(), "status": it["status"], "action": "; ".join(done), "sha": head}
            )
            _save_queue(q)
        if act == "approve" and not step_failed:
            review_acted.record(
                _repo(), pr, head, "approved", "; ".join(done), title=live.get("title") or ""
            )
        _log({"pr": pr, "decision": f"manual_{act}", "sha": head, "done": done})
    return {"pr": pr, "act": act, "done": done}


DIRECTIONS, SIGNOFFS = decision_cards.side_paths(OWN_STATE)


def _write_side(path, n, rec):
    decision_cards.write_side(path, n, rec)


def decide_fix(payload):
    """The owner's choice on a pipeline v2 decision card for one of the owner's PRs (decision_cards.decide)."""
    _repo()
    _self()  # the null default: nothing configured is a 501 before anything is read
    cfg = {
        "repo": _repo(),
        "self_login": _self(),
        "lane_state": OWN_STATE,
        "gh": _gh,
        "verify_head": _verify_head,
        "closed_exc": AlreadyClosed,
        "log": _log,
        "drop_cache": _drop_my_cache,
        "review_verdict": _review_verdict_ids,
    }
    try:
        return decision_cards.decide(cfg, payload)
    except decision_cards.DecisionError as e:
        raise ReviewError(str(e), e.code) from e
