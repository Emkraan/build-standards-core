"""
privileged_reviews.py
Purpose: Ops Center backend for the private privileged-environment lane of the plan gate (the environments the owner
         decides by hand: governance, identity consent, destroy and the like, named in review_config).
         Reads <state>/tf-review/privileged-queue.json (written by the consumer's gate) and the cached pending vendor
         secrets list. Approve / reject re-verify that the run is still waiting on that environment at the queued
         commit, then decide the pending deployment through the code host as the owner. Nothing here is ever decided
         automatically. With no repo configured the page is empty and a decision answers 501.
Date:    2026-10-06
"""

import datetime as dt
import fcntl
import json
import os
import re
import subprocess
from pathlib import Path

import live_truth
import paths
import review_config as cfg

STATE = Path(os.environ.get("TFGATE_STATE_DIR", paths.state_dir() / "tf-review"))
CACHE = Path(os.environ.get("TFGATE_CACHE_DIR", paths.agent_home() / "cache" / "tfplan-gate"))
QUEUE = STATE / "privileged-queue.json"
DECISIONS = STATE / "decisions.jsonl"
LOCK = CACHE / "queue.lock"
SECRETS = CACHE / "secrets-pending.json"
PRIV_HEALTH = CACHE / "privileged-health.json"
GH = os.environ.get("TFGATE_GH_BIN", paths.which("gh"))


def _repo():
    return cfg.need(cfg.plan_repo(), "plan_repo")


def _self():
    return cfg.need(cfg.owner(), "owner")


COMMENTS = {"approved": "Approved after review", "rejected": "Changes requested"}
BLOCKED = "blocked_failed_apply"  # same plan as an approved run whose apply failed


class ReviewError(Exception):
    def __init__(self, msg, code=502):
        super().__init__(msg)
        self.code = code
        self.status = code


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gh(args, timeout=40):
    try:
        p = subprocess.run([GH] + args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ReviewError(f"gh failed: {e}") from e
    if p.returncode != 0:
        raise ReviewError(f"gh {' '.join(args[:3])}: {p.stderr.strip()[:300]}")
    return json.loads(p.stdout) if p.stdout.strip() else {}


def _load(p, default):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


def _save(q):
    tmp = QUEUE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(q, indent=2) + "\n")
    os.replace(tmp, QUEUE)


def _log(rec):
    with open(DECISIONS, "a") as f:
        f.write(json.dumps(dict({"ts": _now(), "lane": "privileged"}, **rec)) + "\n")


def _view(it):
    a = it.get("assessment")
    if a and (
        a.get("head_sha") != it.get("head_sha") or a.get("run_id") not in (None, it.get("run_id"))
    ):
        a = None
    plan = it.get("plan") or None
    return {
        "key": it["key"],
        "environment": it["environment"],
        "env_label": cfg.privileged_envs().get(it["environment"], it["environment"]),
        "workflow": it.get("workflow"),
        "workflow_name": it.get("workflow_name"),
        "run_id": it.get("run_id"),
        "run_attempt": it.get("run_attempt"),
        "run_url": it.get("run_url"),
        "event": it.get("event"),
        "head_branch": it.get("head_branch"),
        "head_sha": it.get("head_sha"),
        "actor": it.get("actor"),
        "pr": it.get("pr"),
        "unexpected": bool(it.get("unexpected")),
        "held_reasons": it.get("held_reasons", []),
        "plan_source": it.get("plan_source"),
        "plan": plan,
        "entra": it.get("entra", []),
        "data_loss": it.get("data_loss", []),
        "governance": it.get("governance", []),
        "release": it.get("release"),
        "pool_roll": it.get("pool_roll"),
        "auto_risk": it.get("auto_risk"),
        "confirm_name": it.get("confirm_name"),
        "typed_confirm": it["environment"] in cfg.typed_confirm(),
        "since": it.get("first_seen"),
        "assessment": a,
        "status": it.get("status"),
        "fingerprint": it.get("fingerprint"),
        "failed_apply": it.get("failed_apply") if it.get("status") == BLOCKED else None,
    }


def _phase(v):
    """needs_me only when decide() could go through. The queue lags the run by up to one gate pass
    (2 min), so the run is read live (live_truth, 20 s, background) before a card offers buttons."""
    if not v.get("assessment") and not v.get("unexpected") and v.get("status") != BLOCKED:
        return "in_flight", "the assessment is still being written"
    live = live_truth.run(cfg.plan_repo(), v["run_id"]) if v.get("run_id") else None
    if live is None:
        return "needs_me", None  # unknown: show it, decide() re-verifies at click time
    if live.get("status") != "waiting" or v["environment"] not in (live.get("envs") or []):
        return "gone", f"the run is {live.get('status')} and no longer waits on {v['env_label']}"
    if live.get("head_sha") != v.get("head_sha") or live.get("run_attempt") not in (
        None,
        v.get("run_attempt"),
    ):
        return "in_flight", "the run moved to a new attempt or commit, the gate re-queues it"
    return "needs_me", None


def get():
    q = _load(QUEUE, {"items": {}})
    pending = []
    for it in q.get("items", {}).values():
        if it.get("status") not in ("pending", BLOCKED):
            continue
        v = _view(it)
        v["phase"], v["blocked"] = _phase(v)
        if v["phase"] != "gone":
            pending.append(v)
    pending.sort(key=lambda x: x.get("since") or "")
    recent = [
        dict(_view(it), decided_at=it.get("decided_at"), decided_by=it.get("decided_by"))
        for it in q.get("items", {}).values()
        if it.get("status") in ("approved", "rejected")
    ]
    recent.sort(key=lambda x: x.get("decided_at") or "", reverse=True)
    s = _load(SECRETS, {})
    h = _load(PRIV_HEALTH, {})
    return {
        "queue_updated": q.get("updated"),
        "pending": pending,
        "recent": recent[:10],
        "secrets": {
            "status": s.get("status", "never_run"),
            "updated": s.get("updated"),
            "last_ok": s.get("last_ok"),
            "error": s.get("error"),
            "items": s.get("secrets", []),
        },
        "health": {
            "failures": h.get("failures", 0),
            "last_error": h.get("last_error"),
            "updated": h.get("updated"),
        },
    }


def decide(payload, act, guard=None):
    """guard(pr number, payload) runs before an approve and raises to refuse it (the PR
    waits on another PR and the click was not Approve anyway).
    act retry approves a run whose plan equals one the owner approved earlier whose apply failed
    (status blocked_failed_apply). It keeps every re-check of approve (typed confirm_name, sha, live
    waiting, run attempt, main branch, env ids) and skips only the assessment (the gate never
    assesses a blocked card) and the PR-dependency guard (the card has no Approve anyway)."""
    if act not in ("approve", "reject", "retry"):
        raise ReviewError("bad action", 400)
    retry = act == "retry"
    state = "rejected" if act == "reject" else "approved"
    key = str(payload.get("key") or "")
    head = str(payload.get("head_sha") or "")
    confirm = str(payload.get("confirm") or "").strip()
    repo = _repo()
    _self()
    envs = cfg.need(cfg.privileged_envs(), "privileged_envs")
    if not re.fullmatch(r"(" + "|".join(re.escape(e) for e in envs) + r"):\d+", key):
        raise ReviewError("key required (<env>:<run id>)", 400)
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ReviewError("head_sha required (40 hex)", 400)
    CACHE.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        q = _load(QUEUE, {"items": {}})
        it = q.get("items", {}).get(key)
        status = (it or {}).get("status")
        if not it or status not in ("pending", BLOCKED):
            raise ReviewError(f"{key} is not waiting on you", 404)
        if retry and status != BLOCKED:
            raise ReviewError(f"{key} has no failed apply to retry; use Approve", 409)
        if status == BLOCKED and act == "approve":
            fa = it.get("failed_apply") or {}
            raise ReviewError(
                f"this plan is identical to run {fa.get('run_id')} whose apply failed ({str(fa.get('error'))[:120]}); "
                "use Retry with the owner's earlier approval or Request changes",
                409,
            )
        if retry:
            fa = it.get("failed_apply") or {}
            rec = (q.get("apply_failures") or {}).get(it.get("fingerprint") or "")
            if not fa or not rec or rec.get("cleared_at"):
                raise ReviewError("the failure for this plan cleared or moved; refresh", 409)
        env, rid = it["environment"], it["run_id"]
        if it.get("head_sha") != head:
            raise ReviewError(
                f"queued commit is {it['head_sha'][:8]}, not {head[:8]}; refresh", 409
            )
        if (
            state == "approved"
            and env in cfg.typed_confirm()
            and confirm != (it.get("confirm_name") or "")
        ):
            raise ReviewError(f"type {it.get('confirm_name')} to confirm", 400)
        if state == "approved" and guard and not retry:
            num = (
                (it.get("pr") or {}).get("number")
                if isinstance(it.get("pr"), dict)
                else it.get("pr")
            )
            try:
                guard(num, payload)
            except Exception as e:  # noqa: BLE001 - the guard's own error type, re-raised as ours
                raise ReviewError(str(e), getattr(e, "code", 409)) from e
        if state == "approved":
            if it.get("unexpected"):
                raise ReviewError(
                    f"run is on {it.get('head_branch')}, not main; {env} is main-only, reject it",
                    409,
                )
            if not it.get("assessment") and not retry:
                raise ReviewError("no assessment yet; wait for it or decide in GitHub", 409)
        run = _gh(["api", f"repos/{repo}/actions/runs/{rid}"])
        if run.get("status") != "waiting":
            raise ReviewError(f"run {rid} is {run.get('status')}, no longer waiting", 409)
        if run.get("head_sha") != it["head_sha"]:
            raise ReviewError(f"run {rid} commit changed to {str(run.get('head_sha'))[:8]}", 409)
        if run.get("run_attempt") not in (None, it.get("run_attempt")):
            raise ReviewError(
                f"run {rid} is on attempt {run.get('run_attempt')}; wait for the gate to re-queue it",
                409,
            )
        if state == "approved" and run.get("head_branch") != "main":
            raise ReviewError(f"run {rid} is on {run.get('head_branch')}, not main", 409)
        pend = _gh(["api", f"repos/{repo}/actions/runs/{rid}/pending_deployments"]) or []
        env_ids = sorted(
            {
                p["environment"]["id"]
                for p in pend
                if (p.get("environment") or {}).get("name") == env
            }
        )
        if not env_ids:
            raise ReviewError(f"run {rid} is not waiting on {env}", 409)
        args = [
            "api",
            "-X",
            "POST",
            f"repos/{repo}/actions/runs/{rid}/pending_deployments",
            "-f",
            f"state={state}",
            "-f",
            f"comment={COMMENTS[state]}",
        ]
        for e in env_ids:
            args += ["-F", f"environment_ids[]={e}"]
        _gh(args)
        live_truth.invalidate()
        it["status"] = state
        it["decided_at"] = _now()
        it["decided_by"] = _self()
        if state == "approved":
            # the fingerprint the owner approved, so a later failed apply is tied to it.
            it["approved_fingerprint"] = it.get("fingerprint")
            it.pop("apply_outcome", None)
            if retry:
                it["retry_of_run"] = (it.get("failed_apply") or {}).get("run_id")
        _save(q)
        a = it.get("assessment") or {}
        _log(
            {
                "run": rid,
                "environment": env,
                "workflow": it.get("workflow"),
                "sha": head,
                "pr": (it.get("pr") or {}).get("number"),
                "decision": f"manual_{state}",
                "risk": (a.get("risk") or {}).get("level"),
                "recommendation": (a.get("recommendation") or {}).get("action"),
                "plan": {k: (it.get("plan") or {}).get(k) for k in ("add", "change", "destroy")},
                **(
                    {
                        "via": "retry_failed_apply",
                        "failed_run": it.get("retry_of_run"),
                        "fingerprint": it.get("fingerprint"),
                    }
                    if retry
                    else {}
                ),
            }
        )
    return {"key": key, "status": state, "run": rid, "environment": env}
