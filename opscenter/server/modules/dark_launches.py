"""Dark launches: acting automation that ships with its action off.

Acting automation (unattended deletes, applies, lock lifts, access changes) merges with its action
OFF and runs in report mode. It reads an enable switch, a code host variable such as
DRIFT_REMEDIATION_ENABLED, where unset or anything but "true" means dry run. The owner turns it on
with one Enable click on the board after reviewing a dry run. This module is the backend of that card.
It is the standard way an acting rule goes live (opscenter/DESIGN.md sections 2.5 and 12.3, item 11).

Registry (config the owner edits, atomic, one writer): <state_dir>/dashboard/dark-launches.json
  {"launches": [{id, repo, environment, variable, workflow, title, status, dry_run_input?}]}
  status: dark (shipped, action off), enabled (turned on), retired (hidden).
Log (append only): <state_dir>/dashboard/dark-launches-log.jsonl.

Buttons (the server wires the routes, same-origin and loopback only):
  dry-run  gh workflow run <workflow> -R <repo> --ref main -f dry_run=true
  enable   gh variable set <VAR> --body true [--env <env>] -R <repo>   (typed variable name, and the
           newest dry run for it must have finished green, read live, never trusted from the browser)
  disable  gh variable set <VAR> --body false ...                        (the safe direction, no gate)
The live variable is the truth. The registry status only records what was last done. A failed read is
"unknown", never "off": Enable is refused on unknown, Disable is always allowed.

Environment: OPSCENTER_STATE_DIR (state tree, default ~/.opscenter/state), DARK_LAUNCH_REGISTRY and
DARK_LAUNCH_LOG (override the two files), OPSCENTER_GH_BIN (the gh binary, default the one on PATH).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

STATE = Path(os.environ.get("OPSCENTER_STATE_DIR", Path.home() / ".opscenter" / "state"))
DASH = STATE / "dashboard"
REGISTRY = Path(os.environ.get("DARK_LAUNCH_REGISTRY", DASH / "dark-launches.json"))
LOG = Path(os.environ.get("DARK_LAUNCH_LOG", DASH / "dark-launches-log.jsonl"))
GH = os.environ.get("OPSCENTER_GH_BIN") or shutil.which("gh") or "gh"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,60}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ENV_RE = re.compile(r"^[A-Za-z0-9_.-]{1,60}$")
VAR_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,60}$")
WF_RE = re.compile(r"^[A-Za-z0-9_.-]+\.ya?ml$")
INPUT_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
STATUSES = ("dark", "enabled", "retired")
DRY_RUN_MAX_AGE_S = 7 * 86400
CACHE_S = 20

_lock = threading.Lock()
_cache = {"at": 0.0, "data": None}


class DarkError(Exception):
    def __init__(self, msg, code=409):
        super().__init__(msg)
        self.code = code


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
        return 0.0


def _gh(args, timeout=60):
    """Run gh. Returns stdout. Raises DarkError(502) on a missing binary, a timeout or a non-zero exit."""
    try:
        p = subprocess.run([GH] + args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise DarkError(f"gh failed: {e}", 502) from e
    if p.returncode != 0:
        raise DarkError(
            "gh {}: {}".format(" ".join(args[:3]), (p.stderr or p.stdout).strip()[:300]), 502
        )
    return p.stdout


# ---- registry ---------------------------------------------------------------------------------


def _clean(rec):
    """One validated registry entry, or raises ValueError naming the problem."""
    if not isinstance(rec, dict):
        raise ValueError("entry must be an object")
    out = {
        k: str(rec.get(k) or "").strip()
        for k in ("id", "repo", "environment", "variable", "workflow", "title")
    }
    out["status"] = str(rec.get("status") or "dark").strip()
    out["dry_run_input"] = str(rec.get("dry_run_input") or "dry_run").strip()
    if not ID_RE.match(out["id"]):
        raise ValueError("bad id {!r}".format(out["id"]))
    if not REPO_RE.match(out["repo"]):
        raise ValueError("{}: bad repo".format(out["id"]))
    if out["environment"] and not ENV_RE.match(out["environment"]):
        raise ValueError("{}: bad environment".format(out["id"]))
    if not VAR_RE.match(out["variable"]):
        raise ValueError("{}: bad variable name".format(out["id"]))
    if not WF_RE.match(out["workflow"]):
        raise ValueError("{}: bad workflow file name".format(out["id"]))
    if not INPUT_RE.match(out["dry_run_input"]):
        raise ValueError("{}: bad dry_run_input".format(out["id"]))
    if not out["title"]:
        raise ValueError("{}: title required".format(out["id"]))
    if out["status"] not in STATUSES:
        raise ValueError("{}: status must be one of {}".format(out["id"], ", ".join(STATUSES)))
    return out


def load_registry():
    """Validated entries. A missing file is an empty registry. A malformed one raises DarkError(503)
    so nothing acts on a half-read registry."""
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        raise DarkError(f"dark-launches.json unreadable: {e}", 503) from e
    rows = data.get("launches") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise DarkError("dark-launches.json needs a launches list", 503)
    out, seen = [], set()
    for r in rows:
        try:
            c = _clean(r)
        except ValueError as e:
            raise DarkError(f"dark-launches.json: {e}", 503) from e
        if c["id"] in seen:
            raise DarkError("dark-launches.json: duplicate id {}".format(c["id"]), 503)
        seen.add(c["id"])
        out.append(c)
    return out


def _save_status(launch_id, status):
    """Rewrite the registry with one entry's status changed (atomic, other entries kept)."""
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for r in data.get("launches") or []:
        if r.get("id") == launch_id:
            r["status"] = status
    tmp = REGISTRY.with_name(f".{REGISTRY.name}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(tmp, REGISTRY)


def _log(rec):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict({"ts": _now()}, **rec), ensure_ascii=True) + "\n")


def _log_rows(launch_id):
    try:
        lines = LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("id") == launch_id:
            out.append(r)
    return out


# ---- live reads -------------------------------------------------------------------------------


def _var_args(lc, verb):
    a = ["variable", verb, lc["variable"], "-R", lc["repo"]]
    if lc["environment"]:
        a += ["--env", lc["environment"]]
    return a


def live_value(lc):
    """'on', 'off' or 'unknown'. An unset variable is off (default dry run). Any other read error is unknown."""
    try:
        out = _gh(_var_args(lc, "get"))
    except DarkError as e:
        msg = str(e)
        if "HTTP 404" in msg or "Not Found" in msg or "could not find" in msg.lower():
            return "off"
        return "unknown"
    return "on" if out.strip().lower() == "true" else "off"


def dry_run_state(lc):
    """Newest dry run this module dispatched for this launch: {state: none|running|passed|failed|unknown, url, at}.
    Read live from the workflow runs, only counting a workflow_dispatch run on main created at or after
    its recorded dispatch time."""
    sent = [r for r in _log_rows(lc["id"]) if r.get("event") == "dry_run_dispatched"]
    if not sent:
        return {"state": "none"}
    at = sent[-1]["ts"]
    if time.time() - _ts(at) > DRY_RUN_MAX_AGE_S:
        return {"state": "none", "at": at, "stale": True}
    try:
        out = _gh(
            [
                "run",
                "list",
                "-R",
                lc["repo"],
                "--workflow",
                lc["workflow"],
                "--event",
                "workflow_dispatch",
                "--branch",
                "main",
                "--limit",
                "10",
                "--json",
                "databaseId,status,conclusion,createdAt,url",
            ]
        )
        runs = json.loads(out or "[]")
    except (DarkError, ValueError):
        return {"state": "unknown", "at": at}
    mine = [r for r in runs if _ts(r.get("createdAt")) >= _ts(at) - 30]
    if not mine:
        return {"state": "running", "at": at}  # dispatched, run not listed yet
    r = max(mine, key=lambda x: x.get("createdAt") or "")
    if r.get("status") != "completed":
        return {"state": "running", "at": at, "url": r.get("url")}
    return {
        "state": "passed" if r.get("conclusion") == "success" else "failed",
        "at": at,
        "url": r.get("url"),
    }


def _card(lc):
    live = live_value(lc)
    dry = dry_run_state(lc)
    return {
        "id": lc["id"],
        "title": lc["title"],
        "repo": lc["repo"],
        "environment": lc["environment"],
        "variable": lc["variable"],
        "workflow": lc["workflow"],
        "status": lc["status"],
        "live": live,
        "dry_run": dry,
        "can_dry_run": dry.get("state") != "running",
        "can_enable": live == "off" and dry.get("state") == "passed",
        "can_disable": live != "off",
    }


def get(force=False):
    """The cards for every registered dark launch that is not retired. Cached briefly, failed reads
    leave a card with live: unknown, never hide it."""
    with _lock:
        if not force and _cache["data"] is not None and time.time() - _cache["at"] < CACHE_S:
            return _cache["data"]
    try:
        rows = [lc for lc in load_registry() if lc["status"] != "retired"]
        data = {"launches": [_card(lc) for lc in rows], "error": None}
    except DarkError as e:
        data = {"launches": [], "error": str(e)}
    with _lock:
        _cache.update(at=time.time(), data=data)
    return data


def _drop_cache():
    with _lock:
        _cache["data"] = None


# ---- actions ----------------------------------------------------------------------------------


def _find(payload):
    lid = str((payload or {}).get("id") or "")
    for lc in load_registry():
        if lc["id"] == lid and lc["status"] != "retired":
            return lc
    raise DarkError(f"no dark launch {lid!r}. Refresh first.", 404)


def dry_run(payload):
    lc = _find(payload)
    if dry_run_state(lc).get("state") == "running":
        return {"id": lc["id"], "done": ["a dry run is already running"], "already": True}
    _gh(
        [
            "workflow",
            "run",
            lc["workflow"],
            "-R",
            lc["repo"],
            "--ref",
            "main",
            "-f",
            "{}=true".format(lc["dry_run_input"]),
        ]
    )
    _log(
        {
            "id": lc["id"],
            "event": "dry_run_dispatched",
            "repo": lc["repo"],
            "workflow": lc["workflow"],
        }
    )
    _drop_cache()
    return {
        "id": lc["id"],
        "done": ["started {} as a dry run on main in {}".format(lc["workflow"], lc["repo"])],
    }


def enable(payload):
    lc = _find(payload)
    if str((payload or {}).get("confirm") or "").strip() != lc["variable"]:
        raise DarkError("Type {} to confirm.".format(lc["variable"]), 400)
    live = live_value(lc)
    if live == "unknown":
        raise DarkError("Could not read {} live. Not enabling.".format(lc["variable"]), 409)
    if live == "on":
        _drop_cache()
        return {
            "id": lc["id"],
            "done": ["{} is already on".format(lc["variable"])],
            "already": True,
        }
    dry = dry_run_state(lc)
    if dry.get("state") != "passed":
        raise DarkError(
            "Run a dry run first and let it finish green (now: {}).".format(dry.get("state")), 409
        )
    _gh(_var_args(lc, "set") + ["--body", "true"])
    if live_value(lc) != "on":
        raise DarkError(
            "Set {} but a read back did not show true. Check it in GitHub.".format(lc["variable"]),
            502,
        )
    with _lock:
        _save_status(lc["id"], "enabled")
    _log({"id": lc["id"], "event": "enabled", "variable": lc["variable"], "dry_run": dry})
    _drop_cache()
    return {
        "id": lc["id"],
        "done": ["{} is now true, {} acts on its next run".format(lc["variable"], lc["workflow"])],
    }


def disable(payload):
    lc = _find(payload)
    live = live_value(lc)
    if live == "off":
        with _lock:
            if lc["status"] == "enabled":
                _save_status(lc["id"], "dark")
        _drop_cache()
        return {
            "id": lc["id"],
            "done": ["{} is already off".format(lc["variable"])],
            "already": True,
        }
    _gh(_var_args(lc, "set") + ["--body", "false"])
    if live_value(lc) != "off":
        raise DarkError(
            "Set {} to false but a read back did not confirm. Check it in GitHub.".format(
                lc["variable"]
            ),
            502,
        )
    with _lock:
        _save_status(lc["id"], "dark")
    _log({"id": lc["id"], "event": "disabled", "variable": lc["variable"]})
    _drop_cache()
    return {
        "id": lc["id"],
        "done": ["{} is now false, {} reports only".format(lc["variable"], lc["workflow"])],
    }
