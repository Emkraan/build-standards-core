"""
tf_reviews.py
Purpose: Ops Center backend for the private plan review queue (written by the consumer's plan gate).
         GET returns pending held PRs + recent gate decisions; approve / reject re-verify that the runs are
         still waiting on the current head sha and then decide the pending plan deployments through the code
         host, as the owner. The repo, environment and owner login are review_config values (none configured:
         an empty page and a 501 on a decision).
Date:    2026-10-06
"""

import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import time
from pathlib import Path

import paths
import review_config as cfg

STATE = Path(os.environ.get("TFGATE_STATE_DIR", paths.state_dir() / "tf-review"))
CACHE = Path(os.environ.get("TFGATE_CACHE_DIR", paths.agent_home() / "cache" / "tfplan-gate"))
QUEUE = STATE / "queue.json"
DECISIONS = STATE / "decisions.jsonl"
LOCK = CACHE / "queue.lock"
GH = os.environ.get("TFGATE_GH_BIN", paths.which("gh"))
COMMENTS = {"approved": "Approved after review", "rejected": "Changes requested"}


def _repo():
    return cfg.need(cfg.plan_repo(), "plan_repo")


def _env():
    return cfg.need(cfg.plan_env(), "plan_env")


def _self():
    return cfg.need(cfg.owner(), "owner")


def signoff_mod():
    """The sign-off store the consumer wired: lanes/signoff_store.py, or the module named by
    OPSCENTER_SIGNOFF_MODULE (it must offer record, revoke and OWN)."""
    import importlib

    return importlib.import_module(os.environ.get("OPSCENTER_SIGNOFF_MODULE") or "signoff_store")


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


def _post_retry(args, tries=3):
    """A pending_deployments POST, retried on GitHub 5xx answers (seen live as HTTP 502)."""
    for n in range(tries):
        try:
            return _gh(args)
        except ReviewError as e:
            if n == tries - 1 or not re.search(
                r"HTTP 5\d\d|Server Error|Bad Gateway|timed out", str(e)
            ):
                raise
            time.sleep(2 * (n + 1))


def _load():
    try:
        return json.loads(QUEUE.read_text())
    except (OSError, ValueError):
        return {"items": {}}


def _save(q):
    tmp = QUEUE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(q, indent=2) + "\n")
    os.replace(tmp, QUEUE)


def _decisions(n=20):
    try:
        lines = DECISIONS.read_text().splitlines()
    except OSError:
        return []
    out = []
    for ln in reversed(lines):
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if rec.get("lane") == "privileged":
            continue  # shown by privileged_reviews, not the plan auto-approvals list
        out.append(rec)
        if len(out) >= n:
            break
    return out


def get():
    q = _load()
    pending, parked = [], []
    for key, it in q.get("items", {}).items():
        if it.get("status") == "pending":
            a = it.get("assessment")
            if a and a.get("head_sha", it.get("head_sha")) != it.get("head_sha"):
                a = None  # stale assessment from an older sha
            # a parked hold (the owner's PR still being moved by something else) is not mine yet.
            (parked if it.get("parked") else pending).append(dict(it, key=key, assessment=a))
    pending.sort(key=lambda x: x.get("first_seen") or "")
    return {
        "generated_utc": _now(),
        "queue_updated": q.get("updated"),
        "pending": pending,
        "parked": [
            {"pr": p.get("pr"), "head_sha": p.get("head_sha"), "why": p.get("parked")}
            for p in parked
        ],
        "decisions": _decisions(20),
    }


def decide(pr, state, via=None, record_signoff=True):
    if state not in COMMENTS:
        raise ReviewError("bad state", 400)
    repo, env_name, me = _repo(), _env(), _self()
    try:
        pr = int(pr)
    except (TypeError, ValueError):
        raise ReviewError("pr required", 400) from None
    CACHE.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        q = _load()
        cands = [
            (k, it)
            for k, it in q.get("items", {}).items()
            if it.get("pr") == pr and it.get("status") == "pending"
        ]
        if not cands:
            raise ReviewError(f"no pending review for PR #{pr}", 404)
        key, it = cands[-1]
        live = _gh(["api", f"repos/{repo}/pulls/{pr}"])
        if live.get("state") != "open":
            raise ReviewError(f"PR #{pr} is {live.get('state')}", 409)
        if live["head"]["sha"] != it["head_sha"]:
            raise ReviewError(
                f"PR #{pr} head moved to {live['head']['sha'][:8]} since review; wait for the gate to re-queue it",
                409,
            )
        done, failed = [], []
        for rid in it.get("run_ids", []):
            run = _gh(["api", f"repos/{repo}/actions/runs/{rid}"])
            if run.get("status") != "waiting" or run.get("head_sha") != it["head_sha"]:
                continue
            pend = _gh(["api", f"repos/{repo}/actions/runs/{rid}/pending_deployments"]) or []
            env_ids = sorted(
                {
                    p["environment"]["id"]
                    for p in pend
                    if (p.get("environment") or {}).get("name") == env_name
                }
            )
            if not env_ids:
                continue
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
            try:
                _post_retry(args)
            except ReviewError as e:
                # Keep going so one GitHub hiccup does not strand the other runs, but never mark the
                # card decided while a run still waits (the card would vanish with a run held).
                failed.append(f"run {rid}: {e}")
                continue
            done.append(rid)
            with open(DECISIONS, "a") as f:
                f.write(
                    json.dumps(
                        {
                            "ts": _now(),
                            "pr": pr,
                            "run": rid,
                            "workflow": run.get("path"),
                            "decision": f"manual_{state}",
                            "reasons": it.get("held_reasons", []),
                            "files_changed": len(it.get("files", [])),
                            **({"via": via} if via else {}),
                        }
                    )
                    + "\n"
                )
        if failed:
            ok = f" (done: {', '.join(map(str, done))})" if done else ""
            raise ReviewError(
                f"GitHub did not take the decision for {'; '.join(failed)}{ok}. Retry from the card.",
                502,
            )
        if not done:
            raise ReviewError(f"no runs for PR #{pr} are still waiting on {env_name}", 409)
        it["status"] = state
        it["decided_at"] = _now()
        it["decided_runs"] = done
        # the owner's decision is the only source an approval can carry from. Store the content
        # fingerprint of every hold hit the owner just decided on. A rejection records its own set so a
        # rejected head never carries, and it revokes the same fingerprints from earlier approvals.
        fps = sorted({h["fp"] for h in it.get("hits") or [] if h.get("fp")})
        if state == "approved":
            it["approval_source"] = "manual"
            it["approved_fps"] = fps
            it.pop("rejected_fps", None)
        else:
            it["rejected_fps"] = fps
            it.pop("approved_fps", None)
            it.pop("approval_source", None)
        _save(q)
    # the owner's click on a plan card of the owner's own PR is the one sign-off for that PR. Recorded after
    # the lock is released (the store has its own lock). A rejection revokes every earlier one.
    try:
        so = signoff_mod()
        if not record_signoff:
            pass
        elif state == "approved" and it.get("author") == me:
            so.record(pr, it["head_sha"], so.OWN, "plan_card", it.get("hits") or [], None)
        elif state == "rejected":
            so.revoke(pr, "rejected on the plan card")
    except Exception as e:  # noqa: BLE001 - the decision already went through, never fail the response
        return {"pr": pr, "key": key, "status": state, "runs": done, "signoff_error": str(e)[:200]}
    return {"pr": pr, "key": key, "status": state, "runs": done}


def approve_for_signoff(pr, head_sha):
    """The owner's sign-off on a PR also approves that PR's plan waits on the same
    head, so there is no second click. Only a pending card for this exact head is touched. Returns a
    short line for the response, or None when nothing waited."""
    q = _load()
    cands = [
        it
        for it in q.get("items", {}).values()
        if it.get("pr") == int(pr)
        and it.get("status") == "pending"
        and it.get("head_sha") == head_sha
    ]
    if not cands:
        return None
    try:
        r = decide(pr, "approved", via="signoff", record_signoff=False)
    except ReviewError as e:
        return f"could not approve the plan waits: {e}"[:240]
    return f"approved {len(r.get('runs') or [])} plan wait(s) with the same sign-off"
