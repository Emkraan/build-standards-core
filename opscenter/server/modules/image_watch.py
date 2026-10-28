#!/usr/bin/env python3
"""
image_watch.py

Purpose: A failed desktop image build (image-build.yml on the platform repo (IMAGE_WATCH_REPO),
         event workflow_dispatch or schedule, branch main, latest attempt concluded failure)
         raises one Action Center item (automation_actions, key auto-image-failed-<run>-a<n>)
         with the failing job and step, the IMAGE-RESULT or ERROR line from the failed log,
         whether the master image-master-01 is running, and the buttons Rerun failed jobs, Close the
         window and Open run. Nothing here ever reruns or closes by itself: the two buttons post
         to /api/automation/approve, which calls act() below after a fresh live re-read.
         The item closes when a newer attempt or a newer run of the workflow succeeds, or when a
         new attempt is running. Dismissing it on the board hides it by fingerprint.

Usage:   image_watch.py sync [--dry-run]      raise or close the item (run by the data refresh)
         image_watch.py show                  print what the card would carry, no write
         image_watch.py act rerun|close --run-id N --attempt N [--dry-run]
Exit:    0 on success, 1 on failure.
Test hooks: IMAGE_WATCH_GH, IMAGE_WATCH_AZ (binaries), IMAGE_WATCH_DASH (state dir for the cache file), IMAGE_WATCH_REPO, IMAGE_WATCH_WORKFLOW, IMAGE_WATCH_RG, IMAGE_WATCH_MASTER,
            OPSCENTER_ROOT (automation_actions store).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import paths

REPO = os.environ.get("IMAGE_WATCH_REPO", "owner/repo")
WORKFLOW = os.environ.get("IMAGE_WATCH_WORKFLOW", "image-build.yml")
RG = os.environ.get("IMAGE_WATCH_RG", "image-rg")
MASTER = os.environ.get("IMAGE_WATCH_MASTER", "image-master-01")
GH = os.environ.get("IMAGE_WATCH_GH") or paths.which("gh")
AZ = os.environ.get("IMAGE_WATCH_AZ") or paths.which("az")
DASH = Path(os.environ.get("IMAGE_WATCH_DASH") or paths.dashboard_dir())
CACHE = DASH / "image-watch.json"

EVENTS = ("workflow_dispatch", "schedule")
ITEM_PREFIX = "image-failed-"  # automation_actions id prefix (shown as auto-image-failed-...)
VM_TTL_S = 300
# A rerun and a build both run the workflow file and the scripts of the commit the run started
# on, so a change to any of these on main after that commit means a new build is needed.
BUILD_PATHS = (
    ".github/workflows/image-build.yml",
    ".github/scripts/image",
    "infrastructure/terraform/image/",
)
# Docs, tests and the window log (manual-installs.json, written by every build) are not a fix.
NOT_A_FIX = re.compile(r"(\.md$|/tests/|manual-installs\.json$)")
LOG_LINE_MAX = 400
LOG_LINES = 3

RERUN_LABEL = "Rerun failed jobs"
CLOSE_LABEL = "Close the window"


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(cmd, timeout=60):
    """One helper for every external command. Returns (rc, stdout, stderr), rc -1 on a missing
    binary or a timeout, so a failed read is an error value and never 'nothing found'."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout}s"
    except OSError as e:
        return -1, "", str(e)


def _gh_json(args, timeout=60):
    rc, out, err = _run([GH] + args, timeout)
    if rc != 0:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def _load():
    try:
        with open(CACHE, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except (OSError, ValueError):
        pass
    return {}


def _save(data):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(CACHE.parent), prefix=".image-watch.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, CACHE)


# ---------------------------------------------------------------- reads


def list_runs():
    """Newest main runs of the workflow, or None when the read failed."""
    d = _gh_json(["api", f"repos/{REPO}/actions/workflows/{WORKFLOW}/runs?branch=main&per_page=20"])
    if not isinstance(d, dict) or not isinstance(d.get("workflow_runs"), list):
        return None
    runs = [
        r for r in d["workflow_runs"] if r.get("head_branch") == "main" and r.get("event") in EVENTS
    ]
    return sorted(runs, key=lambda r: r.get("created_at") or "", reverse=True)


def pick_failure(runs):
    """The run to show, or None. The newest completed failed run, unless a newer run of the
    workflow succeeded (a newer attempt of the same run shows as a success on the run itself)."""
    failed = next(
        (r for r in runs if r.get("status") == "completed" and r.get("conclusion") == "failure"),
        None,
    )
    if not failed:
        return None
    for r in runs:
        newer_success = (r.get("created_at") or "") > (failed.get("created_at") or "") and r.get(
            "conclusion"
        ) == "success"
        if newer_success and built(r.get("id")):
            return None
    return failed


CAPTURE_JOB_PREFIX = "job 3"


def built(run_id):
    """True only when the run's capture job concluded success. A scheduled run outside the
    Patch Tuesday window concludes success with every build job skipped, which must not
    clear a real failure. A failed read keeps the item (never assume built)."""
    if not run_id:
        return False
    d = _gh_json(["api", f"repos/{REPO}/actions/runs/{run_id}/jobs?per_page=50"])
    if not isinstance(d, dict):
        return False
    return any(
        (j.get("name") or "").startswith(CAPTURE_JOB_PREFIX) and j.get("conclusion") == "success"
        for j in d.get("jobs") or []
    )


def active_runs(runs, after=""):
    return [
        r for r in runs if r.get("status") != "completed" and (r.get("created_at") or "") >= after
    ]


def failing_step(run_id):
    """(job name, step name) of the first failed step of the latest attempt, or (None, None)."""
    d = _gh_json(["api", f"repos/{REPO}/actions/runs/{run_id}/jobs?per_page=50"])
    if not isinstance(d, dict):
        return None, None
    for j in d.get("jobs") or []:
        if j.get("conclusion") == "failure":
            for st in j.get("steps") or []:
                if st.get("conclusion") == "failure":
                    return j.get("name"), st.get("name")
            return j.get("name"), None
    return None, None


LOG_PREFIX_RE = re.compile(r"^.*?\t.*?\t\d{4}-\d{2}-\d{2}T[\d:.]+Z ?")


def log_lines(text):
    """IMAGE-RESULT line first, then ERROR lines, then ##[error] lines, trimmed and unique."""
    result, errs, gha = [], [], []
    for raw in (text or "").splitlines():
        line = LOG_PREFIX_RE.sub("", raw, count=1).strip()
        if not line:
            continue
        if "IMAGE-RESULT" in line:
            result.append(line)
        elif re.search(r"\bERROR\b", line) and not line.startswith("##[error]"):
            errs.append(line)
        elif line.startswith("##[error]"):
            gha.append(line)
    out = []
    # A bare "Process completed with exit code" adds nothing when a real line exists.
    pool = result + errs + [g for g in gha if not (result or errs) or "exit code" not in g]
    for ln in pool:
        ln = ln[:LOG_LINE_MAX]
        if ln not in out:
            out.append(ln)
    return out[:LOG_LINES]


def failure_detail(run_id, attempt, cache):
    """Failing job, step and log lines for one attempt. Cached forever: a completed attempt never
    changes. Nothing is cached when a read failed, so the next pass retries."""
    key = f"{run_id}:{attempt}"
    hit = (cache.get("details") or {}).get(key)
    if hit:
        return hit
    job, step = failing_step(run_id)
    rc, out, err = _run(
        [GH, "run", "view", str(run_id), "-R", REPO, "--attempt", str(attempt), "--log-failed"], 90
    )
    lines = log_lines(out) if rc == 0 else []
    detail = {"job": job, "step": step, "lines": lines, "log_read": rc == 0}
    if job and rc == 0:
        cache.setdefault("details", {})[key] = detail
    return detail


def master_state(cache, fresh=False, now=None):
    """running, deallocated, stopped or unknown. A failed read is unknown, never stopped. Cached
    for VM_TTL_S so the 10 minute refresh and a burst of card opens cost one call."""
    now = now or _now()
    vm = cache.get("vm") or {}
    if not fresh and vm.get("state") and vm.get("read_at"):
        try:
            age = (
                now - dt.datetime.fromisoformat(vm["read_at"].replace("Z", "+00:00"))
            ).total_seconds()
        except ValueError:
            age = VM_TTL_S + 1
        if 0 <= age < VM_TTL_S:
            return vm["state"]
    rc, out, _ = _run(
        [
            AZ,
            "vm",
            "get-instance-view",
            "-g",
            RG,
            "-n",
            MASTER,
            "--query",
            "instanceView.statuses[?starts_with(code,'PowerState/')].code | [0]",
            "-o",
            "tsv",
        ],
        60,
    )
    code = (out or "").strip() if rc == 0 else ""
    m = re.fullmatch(r"PowerState/(\w+)", code)
    state = "unknown"
    if m:
        p = m.group(1)
        state = {
            "running": "running",
            "starting": "running",
            "deallocated": "deallocated",
            "deallocating": "deallocated",
        }.get(p, "stopped" if p == "stopped" else "unknown")
    if state == "unknown" and vm.get("state") and not fresh:
        return "unknown"  # a failed read never reuses an older answer as if it were current
    cache["vm"] = {"state": state, "read_at": _iso(now), "code": code}
    return state


def fix_since(head_sha):
    """Files of the build that changed on main after the run's commit. Returns (files, error)."""
    d = _gh_json(["api", f"repos/{REPO}/compare/{head_sha}...main"])
    if not isinstance(d, dict) or not isinstance(d.get("files"), list):
        return [], "could not read main"
    hit = [
        f.get("filename", "")
        for f in d["files"]
        if any(f.get("filename", "").startswith(p) for p in BUILD_PATHS)
        and not NOT_A_FIX.search(f.get("filename", ""))
    ]
    return hit, ""


# ---------------------------------------------------------------- the card


def build_card(run, active, detail, vm, changed, changed_err):
    """Pure: the item fields from already-read facts."""
    rid, attempt = run["id"], run.get("run_attempt") or 1
    url = run.get("html_url") or f"https://github.com/{REPO}/actions/runs/{rid}"
    when = (run.get("updated_at") or run.get("created_at") or "")[:16].replace("T", " ") + " UTC"
    where = detail.get("job") or "an unknown job"
    if detail.get("step"):
        where += ", step '{}'".format(detail["step"])
    parts = [
        "Desktop image build run {} attempt {} ({} on main, commit {}) failed at {} in {}.".format(
            rid, attempt, run.get("event"), (run.get("head_sha") or "")[:7], when, where
        ),
    ]
    if detail.get("lines"):
        parts.append("Log: " + " | ".join(detail["lines"]))
    else:
        parts.append("Log: no error line could be read, open the run.")
    if vm == "running":
        parts.append(
            f"The master {MASTER} is RUNNING after this failure. It costs money and its rotated admin password may "
            "still sit in the run's state. Close the window rotates the password and deallocates it."
        )
    elif vm == "deallocated":
        parts.append(f"The master {MASTER} is deallocated.")
    elif vm == "stopped":
        parts.append(
            f"The master {MASTER} is stopped but not deallocated, so compute is still billed."
        )
    else:
        parts.append(
            f"The master {MASTER} state could not be read (unknown), treat it as possibly running."
        )
    new_build = bool(changed)
    if changed:
        parts.append(
            "A new build is needed, not a rerun: %d file(s) of the build changed on main after this run started (%s), "  # noqa: UP031
            "and a rerun uses the workflow file and scripts of the original commit."
            % (len(changed), ", ".join(changed[:3]))
        )
    elif changed_err:
        parts.append(
            "Could not check whether a fix merged to main since this run started, so confirm before rerunning."
        )
    if active:
        parts.append(
            "Run {} is in progress now, so rerun and close are held until it ends.".format(
                active[0].get("id")
            )
        )
    if new_build:
        action = "Fix is already on main. Start a new build (gh workflow run image-build.yml --ref main), then approve it. Rerun is not offered."
    else:
        action = (
            "Fix the cause shown above, then Rerun failed jobs. Nothing reruns or closes by itself."
        )
    actions = []
    if not new_build and not active:
        actions.append(
            {"kind": "image-rerun", "label": RERUN_LABEL, "run_id": rid, "attempt": attempt}
        )
    if vm in ("running", "unknown", "stopped") and not active:
        actions.append(
            {"kind": "image-close", "label": CLOSE_LABEL, "run_id": rid, "attempt": attempt}
        )
    return {
        "id": f"{ITEM_PREFIX}{rid}-a{attempt}",
        "title": "Desktop image build failed%s"
        % (", master still running" if vm == "running" else ""),
        "why": " ".join(parts),
        "action": action,
        "priority": "critical" if vm == "running" else "high",
        "links": [{"label": "Open run", "url": url}],
        "actions": actions,
        "new_build_needed": new_build,
    }


def collect(cache=None, fresh_vm=False):
    """Read everything and return {'run': ..., 'card': ...} or {'error': ...}. Fails closed."""
    cache = cache if cache is not None else _load()
    runs = list_runs()
    if runs is None:
        return {"error": "could not read the workflow runs"}
    run = pick_failure(runs)
    if not run:
        return {"run": None, "card": None, "newest": runs[0] if runs else None}
    run = dict(run, id=run.get("id"))
    attempt = run.get("run_attempt") or 1
    detail = failure_detail(run["id"], attempt, cache)
    vm = master_state(cache, fresh=fresh_vm)
    changed, cerr = fix_since(run.get("head_sha") or "")
    active = active_runs(runs, run.get("created_at") or "")
    return {"run": run, "card": build_card(run, active, detail, vm, changed, cerr), "cache": cache}


def sync(dry_run=False):
    """Raise or update the item for the failed run, close items that no longer apply."""
    import automation_actions

    cache = _load()
    res = collect(cache)
    if "error" in res:
        return {"error": res["error"], "raised": 0, "closed": 0}  # fail closed: change nothing
    store = automation_actions._load()["items"]
    card = res["card"]
    raised = closed = 0
    for iid, e in store.items():
        if iid.startswith(ITEM_PREFIX) and not e.get("closed") and (not card or iid != card["id"]):
            reason = (
                "A newer attempt or run succeeded, or a new attempt is running."
                if not card
                else ("A newer attempt or run replaced this failure.")
            )
            if not dry_run:
                automation_actions.close_item(iid, reason)
            closed += 1
    if card:
        prev = store.get(card["id"])
        same = (
            prev
            and not prev.get("closed")
            and prev.get("why") == automation_actions._ascii(card["why"])
            and (prev.get("actions") or []) == card["actions"]
            and prev.get("title") == automation_actions._ascii(card["title"])
        )
        if not same:
            if not dry_run:
                automation_actions.raise_item(
                    card["id"],
                    title=card["title"],
                    why=card["why"],
                    action=card["action"],
                    priority=card["priority"],
                    owner="owner",
                    refs=["image-build run {}".format(res["run"]["id"])],
                    links=card["links"],
                    source="Image watch",
                    extra={"actions": card["actions"]},
                )
            raised += 1
    if not dry_run:
        _save(cache)
    return {
        "failing": bool(card),
        "raised_or_updated": raised,
        "closed": closed,
        "dry_run": dry_run,
    }


# ---------------------------------------------------------------- the two buttons


def act(kind, run_id, attempt, dry_run=False):
    """Run one button after a fresh live re-read. Returns (http code, body). Never called by a
    timer: only the server's approve route, from a click. A moved run answers 409 with no write."""
    if kind not in ("image-rerun", "image-close"):
        return 400, {"error": "unsupported action"}
    cache = _load()
    runs = list_runs()
    if runs is None:
        return 503, {"error": "could not read the workflow runs, nothing was changed"}
    failed = pick_failure(runs)
    if (
        not failed
        or str(failed.get("id")) != str(run_id)
        or str(failed.get("run_attempt") or 1) != str(attempt)
    ):
        return 409, {"error": "Refresh first: the failed run changed since this card was drawn"}
    active = active_runs(runs, failed.get("created_at") or "")
    if active:
        return 409, {
            "error": "Run {} is in progress, wait for it to end".format(active[0].get("id"))
        }
    if kind == "image-rerun":
        changed, _ = fix_since(failed.get("head_sha") or "")
        if changed:
            return 409, {
                "error": "A fix merged after this run started, a rerun would use the old workflow. Start a new build."
            }
        cmd = [GH, "run", "rerun", str(run_id), "--failed", "-R", REPO]
        done = "Reran the failed jobs of run %s (attempt %d)" % (run_id, int(attempt) + 1)  # noqa: UP031
    else:
        if master_state(cache, fresh=True) == "deallocated":
            _save(cache)
            return 409, {"error": "The master is already deallocated, nothing to close"}
        cmd = [GH, "workflow", "run", WORKFLOW, "--ref", "main", "-f", "mode=close", "-R", REPO]
        done = f"Started the close mode run (rotate the password, deallocate {MASTER})"
    if dry_run:
        return 200, {"ok": True, "dry_run": True, "would_run": " ".join(cmd)}
    rc, out, err = _run(cmd, 60)
    if rc != 0:
        msg = (err or out or "no output").strip()
        if kind == "image-rerun" and re.search(r"already|in progress|running", msg, re.I):
            return 200, {"ok": True, "already": True, "summary": done}  # idempotent success
        return 422, {"error": msg[:300]}
    cache.pop("vm", None)
    _save(cache)
    try:
        sync()
    except Exception as e:  # noqa: BLE001 - the click succeeded, the next refresh will sync
        print(f"image watch sync after act failed: {e}", file=sys.stderr)
    return 200, {"ok": True, "summary": done}


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "show"
    dry = "--dry-run" in argv
    try:
        if cmd == "sync":
            res = sync(dry_run=dry)
            print(json.dumps(res))
            return 1 if res.get("error") else 0
        if cmd == "show":
            res = collect()
            r = res.get("run") or {}
            print(
                json.dumps(
                    {
                        "error": res.get("error"),
                        "run": r.get("id"),
                        "attempt": r.get("run_attempt"),
                        "card": res.get("card"),
                    },
                    indent=1,
                )
            )
            return 1 if res.get("error") else 0
        if cmd == "act" and len(argv) > 2:

            def opt(name):
                return argv[argv.index(name) + 1] if name in argv else ""

            code, body = act("image-" + argv[2], opt("--run-id"), opt("--attempt"), dry_run=dry)
            print(json.dumps(body))
            return 0 if code == 200 else 1
    except Exception as e:  # noqa: BLE001 - report and exit non-zero, the refresh carries on
        print(f"image watch failed: {e}", file=sys.stderr)
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
