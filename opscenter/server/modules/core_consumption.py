"""
core_consumption.py
Purpose: Core consumption panel (build-standards-core local-ops-app.md section 19). Reads ONLY
         ~/.config/build-standards-core/consumption.json (format build-standards-consumption/1) and
         turns it into rows the panel renders. The read path makes no gh call. Any other format
         value is an error state with no rows. Approvals are the only writes and each one is a
         single gh call: `pr ready`, `pr merge` (only when live checks pass, by the repo's
         declared method, pinned to the head the owner saw) or `issue comment` posting the owner's decision text.
         Never git push, never writes another app's files, never bypasses a merge gate.
Env:     CORE_CONSUMPTION_FILE (the feed), CORE_CONSUMPTION_GH (the gh binary), for tests.
Date:    2026-10-21
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import swr

FORMAT = "build-standards-consumption/1"
CACHE_KEY = "core-consumption:feed"
TTL_S = 60  # the feed is rewritten nightly, the panel never reads it more than once a minute
GH_TIMEOUT_S = 40
CI_STATES = ("pass", "fail", "pending", "none")
ITEM_ID = re.compile(r"^[A-Z]-\d{3,4}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


# Server-side tombstones (live-actions 1.2): an approval the owner just made stays shown as done until the next
# feed (a new generated_at) replaces the snapshot that still lists the item. target -> generated_at.
_done: dict = {}


class ConsumptionError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def feed_path() -> Path:
    env = os.environ.get("CORE_CONSUMPTION_FILE")
    if env:
        return Path(env)
    return Path.home() / ".config" / "build-standards-core" / "consumption.json"


def gh_bin() -> str:
    return os.environ.get("CORE_CONSUMPTION_GH", "gh")


# ---------------------------------------------------------------- read path (no gh)


def _read_raw() -> dict:
    """The raw feed, or an error envelope. Never raises."""
    p = feed_path()
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {
            "error": "missing",
            "message": "consumption.json is not there yet. The core nightly writes it.",
        }
    except OSError as e:
        return {"error": "unreadable", "message": f"Could not read consumption.json: {e}"}
    try:
        doc = json.loads(text)
    except ValueError as e:
        return {"error": "invalid", "message": f"consumption.json is not valid JSON: {e}"}
    if not isinstance(doc, dict):
        return {"error": "invalid", "message": "consumption.json is not an object."}
    fmt = doc.get("format")
    if fmt != FORMAT:
        return {
            "error": "format",
            "message": f"consumption.json has format {fmt!r}, this panel reads only {FORMAT}. Showing nothing rather than stale rows.",
        }
    return {"doc": doc}


def approval_for(c: dict, done: bool = False) -> dict:
    """The approval control state for one consumer row. kind is none (no control), enabled or disabled."""
    target = f"{c.get('repo')}"
    if c.get("mode") == "ops-center" or c.get("class") == "apply-at-once":
        return {"kind": "none", "reason": "Takes every release at once behind its own gate."}
    pr = c.get("sync_pr")
    if not pr:
        return {"kind": "none", "reason": "No sync pull request is open."}
    target = f"{c.get('repo')}#{pr.get('number')}"
    if done:
        return {
            "kind": "done",
            "reason": "Approved here, the next nightly feed confirms it.",
            "target": target,
        }
    if c.get("report_only"):
        return {
            "kind": "disabled",
            "reason": "Report only, this repo is not approved from here.",
            "target": target,
        }
    ci = pr.get("ci")
    if ci == "fail":
        return {
            "kind": "disabled",
            "reason": "Checks fail. Nothing to approve until they pass.",
            "target": target,
        }
    # The feed is a nightly snapshot, so a pending or unreported state stays clickable and the server
    # re-reads the checks live at click time (it merges only when they pass).
    return {"kind": "enabled", "reason": "", "target": target}


def _row(c: dict, stamp: Any = None) -> dict:
    status = c.get("status") if isinstance(c.get("status"), dict) else None
    pr = c.get("sync_pr") if isinstance(c.get("sync_pr"), dict) else None
    ci = pr.get("ci") if pr else None
    if pr and ci not in CI_STATES:
        ci = "none"
    mode = c.get("mode")
    row = {
        "repo": c.get("repo"),
        "label": c.get("label") or c.get("repo"),
        "mode": mode,
        "class": c.get("class") or ("apply-at-once" if mode == "ops-center" else "approval-gated"),
        "report_only": bool(c.get("report_only")),
        "pinned": c.get("pinned"),
        "latest": c.get("latest"),
        "behind": c.get("behind"),
        # A row for the ops center never shows a sync PR, a vendored or workflow row shows one or "none open".
        "sync_pr": None
        if mode == "ops-center" or not pr
        else {
            "number": pr.get("number"),
            "url": pr.get("url"),
            "head": pr.get("head"),
            "created_at": pr.get("created_at"),
            "ci": ci,
        },
        "sync_applies": mode != "ops-center",
        "status": status,
        "ui_verdict": c.get("ui_verdict"),
        "adoption": [
            {
                "part": a.get("part"),
                "file": a.get("file"),
                "kit_part": a.get("kit_part"),
                "relation": a.get("relation"),
                "risk": a.get("risk"),
            }
            for a in (c.get("adoption") or [])
            if isinstance(a, dict)
        ],
        "not_collected": [str(x) for x in (c.get("not_collected") or [])],
    }
    pr_no = pr.get("number") if pr else None
    row["approval"] = approval_for(
        c, _done.get(f"{c.get('repo')}#{pr_no}") == stamp and stamp is not None
    )
    return row


def build_view(raw: dict) -> dict:
    if "error" in raw:
        return {"state": "error", "error": raw["error"], "message": raw["message"], "consumers": []}
    doc = raw["doc"]
    acct = doc.get("account") if isinstance(doc.get("account"), dict) else {}
    peers = doc.get("peers") if isinstance(doc.get("peers"), dict) else {}
    stamp = doc.get("generated_at")
    consumers = [_row(c, stamp) for c in (doc.get("consumers") or []) if isinstance(c, dict)]
    awaiting = [x for x in (acct.get("awaiting_decision") or []) if isinstance(x, dict)]
    suggestions = [x for x in (peers.get("suggestions") or []) if isinstance(x, dict)]
    # The awaiting item an approval would answer, with whether its control can run (the id is well formed).
    for a in awaiting:
        a["done"] = (
            stamp is not None and _done.get(f"{a.get('id')} on issue #{a.get('issue')}") == stamp
        )
        a["can_approve"] = (
            bool(ITEM_ID.match(str(a.get("id", ""))))
            and isinstance(a.get("issue"), int)
            and not a["done"]
        )
    return {
        "state": "ok",
        "generated_at": doc.get("generated_at"),
        "core_repo": doc.get("core_repo"),
        "latest": doc.get("latest"),
        "consumers": consumers,
        "account": {
            "report_issue": acct.get("report_issue"),
            "awaiting_decision": awaiting,
            "approved_unopened": [
                x for x in (acct.get("approved_unopened") or []) if isinstance(x, dict)
            ],
        },
        "peers": {
            "issues": [x for x in (peers.get("issues") or []) if isinstance(x, dict)],
            "suggestions": suggestions,
            "new_count": sum(1 for s in suggestions if s.get("new")),
        },
        "not_collected": [str(x) for x in (doc.get("not_collected") or [])],
        "needs_me": sum(
            1
            for r in consumers
            if r["approval"]["kind"] == "enabled" and r["sync_pr"]["ci"] == "pass"
        )
        + sum(1 for a in awaiting if a["can_approve"]),
    }


def get(fresh: bool = False) -> dict:
    """The panel payload. Served from a 60 second cache, so polling never rereads more than once a minute."""
    return swr.cached(CACHE_KEY, TTL_S, lambda: build_view(_read_raw()), fresh=fresh)


def badge() -> int:
    """Sidebar count: approvals the owner can act on right now. A badge never raises."""
    try:
        return int(get().get("needs_me") or 0)
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------- write path (gh, owner action only)


def _gh(args: list, json_out: bool = False) -> Any:
    """The one gh helper: argument list, timeout, errors become ConsumptionError."""
    try:
        p = subprocess.run([gh_bin(), *args], capture_output=True, text=True, timeout=GH_TIMEOUT_S)
    except FileNotFoundError:
        raise ConsumptionError("gh is not installed", 502) from None
    except subprocess.TimeoutExpired:
        raise ConsumptionError("gh timed out", 504) from None
    if p.returncode != 0:
        raise ConsumptionError((p.stderr or p.stdout).strip()[:300] or "gh failed", 502)
    if not json_out:
        return p.stdout.strip()
    try:
        return json.loads(p.stdout or "null")
    except ValueError:
        raise ConsumptionError("gh returned unreadable output", 502) from None


def _checks_state(rollup) -> str:
    """pass only when at least one check exists and every newest check succeeded."""
    newest = {}
    for c in rollup or []:
        k = (c.get("workflowName") or "", c.get("name") or c.get("context") or "")
        ts = c.get("startedAt") or c.get("completedAt") or ""
        if k not in newest or ts >= (
            newest[k].get("startedAt") or newest[k].get("completedAt") or ""
        ):
            newest[k] = c
    if not newest:
        return "none"
    state = "pass"
    for c in newest.values():
        res = (c.get("conclusion") or c.get("state") or "").upper()
        status = (c.get("status") or "").upper()
        if res in (
            "FAILURE",
            "ERROR",
            "TIMED_OUT",
            "CANCELLED",
            "ACTION_REQUIRED",
            "STARTUP_FAILURE",
        ):
            return "fail"
        if status in ("QUEUED", "IN_PROGRESS", "PENDING", "WAITING") or res in (
            "PENDING",
            "EXPECTED",
            "",
        ):
            state = "pending"
        elif res not in ("SUCCESS", "NEUTRAL", "SKIPPED"):
            return "fail"
    return state


def _merge_flag(repo: str) -> str:
    """The repo's declared merge method. Squash when allowed, else rebase, else merge."""
    info = _gh(
        [
            "repo",
            "view",
            repo,
            "--json",
            "squashMergeAllowed,rebaseMergeAllowed,mergeCommitAllowed",
        ],
        json_out=True,
    )
    if info.get("squashMergeAllowed"):
        return "--squash"
    if info.get("rebaseMergeAllowed"):
        return "--rebase"
    if info.get("mergeCommitAllowed"):
        return "--merge"
    raise ConsumptionError("the repo declares no merge method", 409)


def _tombstone(target: str, stamp: Any) -> None:
    _done[target] = stamp
    swr.invalidate(CACHE_KEY)


def _consumer(repo: str, number: int) -> tuple:
    """(consumer row, feed stamp) whose sync PR this is. Anything else is refused."""
    raw = _read_raw()
    if "error" in raw:
        raise ConsumptionError(raw["message"], 409)
    for c in raw["doc"].get("consumers") or []:
        pr = c.get("sync_pr") or {}
        if c.get("repo") == repo and pr.get("number") == number:
            return c, raw["doc"].get("generated_at")
    raise ConsumptionError(
        "that pull request is not a sync pull request in the consumption feed", 404
    )


def approve_pr(payload: dict) -> dict:
    """Mark a sync PR ready, or merge it once its live checks pass. One call per click."""
    repo, number, confirm = payload.get("repo"), payload.get("number"), payload.get("confirm")
    if (
        not isinstance(repo, str)
        or not REPO_RE.match(repo)
        or not isinstance(number, int)
        or isinstance(number, bool)
    ):
        raise ConsumptionError("repo and number are required")
    target = f"{repo}#{number}"
    if confirm != target:
        raise ConsumptionError(f"confirmation must name {target}")
    c, raw_stamp = _consumer(repo, number)
    appr = approval_for(c)
    if appr["kind"] != "enabled":
        raise ConsumptionError(appr["reason"], 409)
    # Live read right before the write (automation-safety 1.4). The feed is a snapshot.
    live = _gh(
        [
            "pr",
            "view",
            str(number),
            "-R",
            repo,
            "--json",
            "state,isDraft,headRefName,headRefOid,statusCheckRollup",
        ],
        json_out=True,
    )
    if live.get("state") != "OPEN":
        _tombstone(target, raw_stamp)
        return {
            "done": [f"{target} is already {str(live.get('state')).lower()}"],
            "already": True,
            "target": target,
        }
    want_head = (c.get("sync_pr") or {}).get("head")
    if want_head and live.get("headRefName") != want_head:
        raise ConsumptionError("Refresh first: the pull request head moved", 409)
    ci = _checks_state(live.get("statusCheckRollup"))
    if ci != "pass":
        raise ConsumptionError(f"checks are {ci}, nothing is approved until they pass", 409)
    if live.get("isDraft"):
        _gh(["pr", "ready", str(number), "-R", repo])
        done = f"marked {target} ready for review"
    else:
        flag = _merge_flag(repo)
        _gh(
            [
                "pr",
                "merge",
                str(number),
                "-R",
                repo,
                flag,
                "--match-head-commit",
                str(live.get("headRefOid")),
            ]
        )
        done = f"merged {target} ({flag[2:]})"
    _tombstone(target, raw_stamp)
    return {"done": [done], "target": target}


def approve_item(payload: dict) -> dict:
    """Post the owner's owner decision ('approve D-015') on the report issue for an item awaiting the owner's decision."""
    issue, item, confirm = payload.get("issue"), payload.get("id"), payload.get("confirm")
    if (
        not isinstance(issue, int)
        or isinstance(issue, bool)
        or not isinstance(item, str)
        or not ITEM_ID.match(item)
    ):
        raise ConsumptionError("issue and id are required")
    target = f"{item} on issue #{issue}"
    if confirm != target:
        raise ConsumptionError(f"confirmation must name {target}")
    raw = _read_raw()
    if "error" in raw:
        raise ConsumptionError(raw["message"], 409)
    doc = raw["doc"]
    repo = doc.get("core_repo")
    awaiting = (doc.get("account") or {}).get("awaiting_decision") or []
    if not isinstance(repo, str) or not REPO_RE.match(repo):
        raise ConsumptionError("the feed names no core repo", 409)
    if not any(a.get("issue") == issue and a.get("id") == item for a in awaiting):
        raise ConsumptionError("that item is not awaiting the owner's decision in the feed", 404)
    text = f"approve {item}"
    live = _gh(["issue", "view", str(issue), "-R", repo, "--json", "state,comments"], json_out=True)
    if live.get("state") != "OPEN":
        raise ConsumptionError("the report issue is not open", 409)
    mine = re.compile(rf"^\s*approve {re.escape(item)}\s*$", re.I)
    if any(mine.match(str(cm.get("body", ""))) for cm in live.get("comments") or []):
        _tombstone(target, doc.get("generated_at"))
        return {"done": [f"{target} was already approved"], "already": True, "target": target}
    _gh(["issue", "comment", str(issue), "-R", repo, "--body", text])
    _tombstone(target, doc.get("generated_at"))
    return {"done": [f"posted '{text}' on issue #{issue}"], "target": target}
