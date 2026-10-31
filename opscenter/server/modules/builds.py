"""
builds.py
Purpose: Live Builds page: the release, build and rollout runs of a repository's configured pipelines, with job and step progress,
         the reason a run failed, the environment a waiting run needs, and what actually landed (read live, not assumed).
         Read only. Approvals stay on the existing privileged lane, this module only links to the waiting card.
         Code host budget: one runs call per pipeline per poll, job reads only when a run's updated_at moves, completed runs cached for
         the process lifetime. 8 s TTL while anything runs or waits, 60 s idle. Landed facts refresh every 10 minutes, and at once when a
         run of that product completes.
         A deploy of a pipeline marked `refusal` that the branch guard refused because the branch is behind main shows "Refused:
         <branch> is N commits behind main" with the live count. On the owner's own branches (head commit or PR author) the card offers
         "Update from main and redeploy", which merges main into the branch through the code host's merge API (no checkout), and the push
         redeploys. Other people's branches get the plain message and no button.

Parameters (BUILDS_CONFIG, a JSON file, default <state>/builds-config.json; every key optional, no pipeline means an empty page):
  repo              owner/name of the repository whose runs are shown
  owner             the owner's login (only the owner's own branches get the update button)
  branch_regex      which branches may be updated from here (default ^[a-z]+-\\d+-)
  pipelines         [{"key", "product", "label", "workflow", "refusal": bool, "summary": bool}]
  summary_regex     for a pipeline with summary true: the regex whose first group is the result line a successful run prints
  landed            {"<product>": [command list]}: a command that prints the JSON facts of what landed for that product (recorded
                    versus live, drift lines); none for a product means no landed block. The command is the consumer's (it may read a
                    release record, a device management service or a storage account)
  privileged_queue  the privileged approvals queue file (default <state>/tf-review/privileged-queue.json)
  dispatch_gap_s    seconds a repeat start of the same workflow with the same inputs is answered as already started (default 20)

Run contract (the server side of the Run workflow button, DESIGN.md 12.49). A pipeline entry may declare what a start may carry:
  "ref": "main" | "branch"      where it may run: main only, or main or a branch matching branch_regex (default main)
  "inputs": [{"name", "type": "boolean"|"choice"|"string", "default", "options", "pattern", "required", "help",
              "publishes_when": the value that makes a run publish (true for a flag, a choice value), none: the input never does}]
  "paused": true                a paused pipeline refuses a start (409)
The inputs are a fixed copy of the workflow's own inputs. POST /api/builds/dispatch {pipeline, ref?, inputs?} refuses an unknown
pipeline (404), an unknown input name (400 naming it), a value that is not valid for its input (400), a ref the workflow may not run
from (400), a paused pipeline or a run already queued or running on that ref (409 with the reason); the same pipeline, ref and
inputs inside dispatch_gap_s answers {started: false, already: true}. Left out, an input takes its default, and the form's defaults
are the safe ones (a dry run). The answer says whether the run publishes. Environment approvals still gate every job that writes:
this only queues the run.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ghview as infra  # noqa: E402  # _gh, _job_view, _utc_now, _safe, GH
import paths  # noqa: E402
import swr  # noqa: E402


def _config():
    f = os.environ.get("BUILDS_CONFIG") or str(paths.state_dir() / "builds-config.json")
    try:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


_C = _config()
REPO = str(_C.get("repo") or "owner/repo")
OWNER = str(
    _C.get("owner") or "owner-account"
)  # automation scope rule: only the owner's own branches get the update button
PRIV_QUEUE = Path(
    _C.get("privileged_queue") or paths.state_dir() / "tf-review" / "privileged-queue.json"
)
PIPELINES = [
    p for p in _C.get("pipelines", []) if isinstance(p, dict) and p.get("key") and p.get("workflow")
]
for _p in PIPELINES:
    _p.setdefault("product", _p["key"])
    _p.setdefault("label", _p["key"])
DISPATCH = {
    p["key"]: {
        "ref": "branch" if p.get("ref") == "branch" else "main",
        "inputs": [i for i in (p.get("inputs") or []) if isinstance(i, dict) and i.get("name")],
        "paused": bool(p.get("paused")),
    }
    for p in PIPELINES
}
RUNS_PER_PIPELINE = 6
BRANCH_OK = re.compile(str(_C.get("branch_regex") or r"^[a-z]+-\d+-"))
SUMMARY_RE = re.compile(str(_C["summary_regex"])) if _C.get("summary_regex") else None
LANDED_CMDS = {
    str(k): [str(a) for a in v]
    for k, v in (_C.get("landed") or {}).items()
    if isinstance(v, list) and v
}
REFUSED = re.compile(r"^(?:##\[error\]|::error::)?(\S+) is (\d+) commit\(s\) behind main\b")
PENDING_TTL_S = 600  # an accepted update has this long to show a new run before it is flagged
BEHIND_TTL_S = 60
DISPATCH_GAP_S = int(_C.get("dispatch_gap_s") or 20)
_RUNNING = ("in_progress", "queued", "requested", "pending", "waiting")


def _refusal_workflows():
    return {p["workflow"] for p in PIPELINES if p.get("refusal")}


_done_jobs = {}  # (run id, attempt) -> jobs, completed runs never change
_seen_jobs = {}  # (run id, attempt) -> (updated_at, jobs, epoch)
_done_reason = {}  # run id -> failure reason
_rollout_line = {}  # run id -> "version x: n release row(s), ring broad ..."
_last_done = {}  # product -> newest completed run id, to refresh landed facts on change
_behind = {}  # head sha -> (epoch, behind_by) read live from the compare API
_own = {}  # head sha -> True/False, who wrote the branch head never changes for a sha
_pending = {}  # run id -> {"sha", "at", "how"} update accepted, waiting for the new run to show
_conflicts = {}  # head sha -> files changed on both sides (None when they could not be listed)
_errors = {}  # head sha -> last error line from an update attempt
_action_lock = threading.Lock()
_dispatched = {}  # (pipeline key, ref, inputs) -> epoch of the last accepted start (stops double clicks)


def _gh_text(path, timeout=25):
    p = subprocess.run(
        [infra.GH, "api", "--allow-escape-sequences", path],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip()[:300])
    # Drop the runner timestamp prefix and ANSI colors.
    return "\n".join(_ANSI.sub("", _TS.sub("", ln)) for ln in p.stdout.splitlines())


_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_TS = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ")
_GENERIC = re.compile(r"^(##\[error\])?Process completed with exit code \d+\.?$")
_ERRLINE = re.compile(r"^(##\[error\]|ERROR\b|Error\b|error:|::error|fatal:|failed to )")


def _log_error(job_id):
    """The error line a failed job printed just before it gave up (the annotation is usually only
    "Process completed with exit code 1")."""
    lines = _gh_text(f"repos/{REPO}/actions/jobs/{job_id}/logs", timeout=40).splitlines()
    cut = next((i for i, ln in enumerate(lines) if _GENERIC.match(ln.strip())), len(lines))
    hits = [ln.strip() for ln in lines[:cut] if _ERRLINE.match(ln.strip())]
    if not hits:
        hits = [
            ln.strip()
            for ln in lines
            if _ERRLINE.match(ln.strip()) and not _GENERIC.match(ln.strip())
        ]
    return re.sub(r"^##\[error\]", "", hits[-1]) if hits else None


def _jobs(r):
    key = (r["id"], r.get("run_attempt"))
    if key in _done_jobs:
        return _done_jobs[key]
    seen = _seen_jobs.get(key)
    if seen and seen[0] == r.get("updated_at") and time.time() - seen[2] < 30:
        return seen[1]
    data = infra._gh(["api", f"repos/{REPO}/actions/runs/{r['id']}/jobs?per_page=50"])
    jobs = [infra._job_view(j) for j in data.get("jobs", [])]
    if r.get("status") == "completed":
        _done_jobs[key] = jobs
        _seen_jobs.pop(key, None)
    else:
        _seen_jobs[key] = (r.get("updated_at"), jobs, time.time())
    return jobs


def _failure_reason(r, jobs):
    """The first error annotation on a failed job, else the failed job and step names."""
    if r["id"] in _done_reason:
        return _done_reason[r["id"]]
    failed = [j for j in jobs if j.get("conclusion") in ("failure", "timed_out")]
    if not failed:
        return None
    j = failed[0]
    step = next(
        (s["name"] for s in j["steps"] if s.get("conclusion") in ("failure", "timed_out")), None
    )
    where = f"{j['name']}" + (f', step "{step}"' if step else "")
    text = None
    try:
        notes = infra._gh(["api", f"repos/{REPO}/check-runs/{j['id']}/annotations?per_page=20"])
        msgs = [
            (a.get("message") or "").strip()
            for a in notes
            if a.get("annotation_level") == "failure" and (a.get("message") or "").strip()
        ]
        specific = [m for m in msgs if not _GENERIC.match(m)]
        text = specific[0] if specific else None
    except (RuntimeError, subprocess.TimeoutExpired, ValueError, OSError):
        text = None
    if not text:
        try:
            text = _log_error(j["id"])
        except (RuntimeError, subprocess.TimeoutExpired, OSError):
            text = None
    out = {"where": where, "message": (text or "")[:600]}
    _done_reason[r["id"]] = out
    return out


def _rollout_summary(r, jobs):
    """A rollout run prints one result line; the pipeline's summary_regex (group 1) finds it in the log of a successful job."""
    if r["id"] in _rollout_line:
        return _rollout_line[r["id"]]
    line = None
    job = next((j for j in jobs if j.get("conclusion") == "success"), None)
    if job and SUMMARY_RE:
        try:
            log = _gh_text(f"repos/{REPO}/actions/jobs/{job['id']}/logs", timeout=30)
            for ln in log.splitlines():
                m = SUMMARY_RE.search(ln)
                if m:
                    line = m.group(1).strip()
        except (RuntimeError, subprocess.TimeoutExpired, OSError):
            line = None
    _rollout_line[r["id"]] = line
    return line


def _pending_envs(r):
    try:
        pend = infra._gh(["api", f"repos/{REPO}/actions/runs/{r['id']}/pending_deployments"]) or []
    except (RuntimeError, subprocess.TimeoutExpired, ValueError, OSError):
        return []
    return sorted(
        {str((p.get("environment") or {}).get("name") or "") for p in pend if p.get("environment")}
        - {""}
    )


def _priv_pending():
    try:
        q = json.loads(PRIV_QUEUE.read_text())
    except (OSError, ValueError):
        return set()
    return {k for k, v in (q.get("items") or {}).items() if v.get("status") == "pending"}


def _run_view(p, r, priv):
    jobs, err = infra._safe(_jobs, r)
    jobs = jobs or []
    view = {
        "id": r["id"],
        "attempt": r.get("run_attempt"),
        "status": r.get("status"),
        "conclusion": r.get("conclusion"),
        "event": r.get("event"),
        "branch": r.get("head_branch"),
        "sha": (r.get("head_sha") or "")[:8],
        "actor": (r.get("triggering_actor") or r.get("actor") or {}).get("login"),
        "created": r.get("created_at"),
        "started": r.get("run_started_at"),
        "updated": r.get("updated_at"),
        "url": r.get("html_url"),
        "jobs": jobs,
        "error": err,
        "waiting_on": [],
        "approve_here": [],
        "reason": None,
        "summary": None,
    }
    if r.get("status") == "waiting":
        envs = _pending_envs(r)
        view["waiting_on"] = envs
        view["approve_here"] = [e for e in envs if f"{e}:{r['id']}" in priv]
    if r.get("status") == "completed" and r.get("conclusion") in ("failure", "timed_out"):
        view["reason"] = _failure_reason(r, jobs)
    if p.get("summary") and r.get("conclusion") == "success":
        view["summary"] = _rollout_summary(r, jobs)
    if p.get("refusal") and view["reason"]:
        view["refusal"] = _refusal(r, view["reason"])
    return view


# ---- Refused for being behind main ---------------------------------------------------


class BuildsError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


def parse_refusal(reason):
    """(branch, behind at the time) from the guard's error line, else None."""
    m = REFUSED.match(((reason or {}).get("message") or "").strip())
    return (m.group(1), int(m.group(2))) if m else None


def _gh_status(args, timeout=40):
    """gh api with the HTTP status. (status or None, body text, error line). 204 has no body."""
    p = subprocess.run(
        [infra.GH, "api", "-i", *args], capture_output=True, text=True, timeout=timeout
    )
    m = re.match(r"HTTP/\S+ (\d{3})", p.stdout or "")
    if not m:
        m = re.search(r"\(HTTP (\d{3})\)", p.stderr or "")
    status = int(m.group(1)) if m else None
    body = re.split(r"\r?\n\r?\n", p.stdout or "", maxsplit=1)[-1] if m and p.stdout else ""
    msg = ""
    try:  # noqa: SIM105
        msg = str(json.loads(body).get("message") or "")
    except (ValueError, AttributeError):
        pass
    return status, body, (msg or (p.stderr or "").strip() or (p.stdout or "").strip())[:300]


def _gh_rerun(run_id, timeout=40):
    p = subprocess.run(
        [infra.GH, "run", "rerun", str(run_id), "-R", REPO],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip()[:300] or "gh run rerun failed")


def _behind_live(sha):
    """How far the branch head is behind main right now, cached per head for BEHIND_TTL_S."""
    hit = _behind.get(sha)
    if hit and time.time() - hit[0] < BEHIND_TTL_S:
        return hit[1]
    n = infra._gh(["api", f"repos/{REPO}/compare/main...{sha}", "--jq", ".behind_by"])
    n = int(n)
    _behind[sha] = (time.time(), n)
    return n


def _is_own(sha, branch):
    """True when the head commit author or the PR author is me. Unknown (None) on a failed read, so
    no button shows (fail closed). Cached per head, who wrote a commit never changes."""
    if sha in _own:
        return _own[sha]
    commit = infra._gh(["api", f"repos/{REPO}/commits/{sha}", "--jq", "{login: .author.login}"])
    own = (commit or {}).get("login") == OWNER
    if not own:
        q = urllib.parse.quote(f"{REPO.split('/')[0]}:{branch}", safe="")
        prs = infra._gh(
            [
                "api",
                f"repos/{REPO}/pulls?head={q}&state=all&per_page=5",
                "--jq",
                "[.[] | {login: .user.login}]",
            ]
        )
        own = any((x or {}).get("login") == OWNER for x in prs or [])
    _own[sha] = own
    return own


def _refusal(r, reason):
    parsed = parse_refusal(reason)
    if not parsed:
        return None
    branch, then = parsed
    sha = r.get("head_sha") or ""
    out = {
        "branch": branch,
        "behind": then,
        "behind_live": None,
        "head": sha,
        "own": None,
        "phase": "info",
    }
    out["behind_live"], err = infra._safe(_behind_live, sha)
    if err:
        out["behind_live"] = None
    own, err = infra._safe(_is_own, sha, branch)
    out["own"] = None if err else own
    return out


def _finalize(feed):
    """Apply the live action state on top of the cached feed: working while an accepted update has
    not produced its new run yet (never optimistic, the next poll shows the run), superseded when a
    newer run exists, conflict with the files, else needs_action on the owner's own branch. Never mutates the cache."""
    now = time.time()
    pipes = []
    for p in feed["pipelines"]:
        runs = p["runs"]
        if not p.get("refusal") or not any(r.get("refusal") for r in runs):
            pipes.append(p)
            continue
        newest = {}
        for r in runs:
            newest[r["branch"]] = max(newest.get(r["branch"], 0), r["id"])
        new_runs = []
        for r in runs:
            ref = r.get("refusal")
            if not ref:
                new_runs.append(r)
                continue
            ref = dict(ref)
            pend = _pending.get(r["id"])
            if pend and r["id"] != newest[r["branch"]]:
                _pending.pop(r["id"], None)  # the new run showed up, the action landed
                pend = None
            if pend and now - pend["at"] > PENDING_TTL_S:
                _pending.pop(r["id"], None)
                _errors[pend["sha"]] = (
                    "The last update did not start a new run. Check the branch on GitHub."
                )
                pend = None
            sha = ref["head"]
            ref["error"] = _errors.get(sha)
            ref["files"] = _conflicts.get(sha)
            if pend:
                ref["phase"] = "working"
            elif r["id"] != newest[r["branch"]]:
                ref["phase"] = "superseded"
            elif sha in _conflicts:
                ref["phase"] = "conflict"
            elif ref["own"] is True:
                ref["phase"] = "needs_action"
            new_runs.append(dict(r, refusal=ref))
        pipes.append(dict(p, runs=new_runs))
    return dict(feed, pipelines=pipes)


def _both_sides(branch):
    """Files changed on the branch and on main since they diverged (where a merge can conflict)."""
    b = urllib.parse.quote(branch, safe="")

    def files(spec):
        return set(
            infra._gh(["api", f"repos/{REPO}/compare/{spec}", "--jq", "[.files[].filename]"]) or []
        )

    return sorted(files(f"main...{b}") & files(f"{b}...main"))


def update_from_main(payload):
    """POST /api/builds/update-from-main {run, branch, sha}. Merges main into the owner's own refused branch
    through the merge API. 201 merged (the push redeploys, nothing else is dispatched), 204 already
    up to date (re-run the failed run), 409 conflict (no change, files listed), else the error line."""
    payload = payload if isinstance(payload, dict) else {}
    branch, sha, run_id = payload.get("branch"), str(payload.get("sha") or ""), payload.get("run")
    if not isinstance(branch, str) or not BRANCH_OK.match(branch) or branch == "main":
        raise BuildsError(
            400, "Only branches named like " + BRANCH_OK.pattern + " can be updated from here"
        )
    if not isinstance(run_id, int) or isinstance(run_id, bool) or len(sha) < 7:
        raise BuildsError(400, "run (number) and sha are required")
    with _action_lock:
        if run_id in _pending:
            return {"result": "working", "already": True}
        # Re-read the live truth, the card is only a snapshot (live-actions 1.7, safety 1.4).
        try:
            run = infra._gh(["api", f"repos/{REPO}/actions/runs/{run_id}"])
            wf = str(run.get("path") or "").rsplit("/", 1)[-1]
            if wf not in _refusal_workflows():
                raise BuildsError(
                    400, "That run is not a deploy that can be refused for being behind main"
                )
            if (
                run.get("status") != "completed"
                or run.get("conclusion") != "failure"
                or run.get("head_branch") != branch
                or not str(run.get("head_sha") or "").startswith(sha)
            ):
                raise BuildsError(409, "Refresh first, that run changed")
            head = str(run["head_sha"])
            ref = infra._gh(
                [
                    "api",
                    f"repos/{REPO}/branches/{urllib.parse.quote(branch, safe='')}",
                    "--jq",
                    "{sha: .commit.sha}",
                ]
            )
            if (ref or {}).get("sha") != head:
                raise BuildsError(409, "Refresh first, the branch has a newer commit")
            q = urllib.parse.quote(branch, safe="")
            newest = infra._gh(
                [
                    "api",
                    f"repos/{REPO}/actions/workflows/{wf}/runs?branch={q}&per_page=1",
                    "--jq",
                    "[.workflow_runs[] | {id: .id}]",
                ]
            )
            if not newest or newest[0].get("id") != run_id:
                raise BuildsError(409, "Refresh first, a newer run exists")
            parsed = parse_refusal(_failure_reason(run, _jobs(run)))
            if not parsed or parsed[0] != branch:
                raise BuildsError(409, "That run was not refused for being behind main")
            if _is_own(head, branch) is not True:
                raise BuildsError(403, f"Only {OWNER} branches can be updated from here")
        except BuildsError:
            raise
        except (
            RuntimeError,
            subprocess.TimeoutExpired,
            ValueError,
            OSError,
            KeyError,
            TypeError,
            AttributeError,
        ) as exc:
            raise BuildsError(502, f"Could not verify the run on GitHub: {str(exc)[:200]}") from exc
        try:
            status, _body, msg = _gh_status(
                [
                    "-X",
                    "POST",
                    f"repos/{REPO}/merges",
                    "-f",
                    f"base={branch}",
                    "-f",
                    "head=main",
                    "-f",
                    f"commit_message=Merge main into {branch}",
                ]
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise BuildsError(502, f"Merge request failed: {str(exc)[:200]}") from exc
        _errors.pop(head, None)
        if status == 201:
            _pending[run_id] = {"sha": head, "at": time.time(), "how": "merged"}
            result = {"result": "merged"}
        elif status == 204:
            try:
                _gh_rerun(run_id)
            except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
                _errors[head] = f"Already up to date, but the re-run failed: {str(exc)[:200]}"
                raise BuildsError(502, _errors[head]) from exc
            _pending[run_id] = {"sha": head, "at": time.time(), "how": "rerun"}
            result = {"result": "rerun"}
        elif status == 409:
            files, err = infra._safe(_both_sides, branch)
            _conflicts[head] = None if err else files
            result = {"result": "conflict", "files": _conflicts[head]}
        else:
            _errors[head] = f"Merge API answered {status or 'no status'}: {msg}"
            raise BuildsError(502, _errors[head])
    _behind.pop(head, None)
    swr.kick("builds:refresh", lambda: swr.cached("builds:feed", 8, _feed, fresh=True))
    return result


# ---- What landed ------------------------------------------------------------------------------


def _landed_cmd(product):
    """Run the product's landed command and parse its JSON facts; a failure is reported in the block, never raised."""
    cmd = LANDED_CMDS[product]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if p.returncode != 0:
            raise RuntimeError(
                (p.stderr or p.stdout).strip().splitlines()[-1:] or ["landed command failed"]
            )
        out = json.loads(p.stdout or "{}")
        if not isinstance(out, dict):
            raise ValueError("landed command did not print an object")
        out.setdefault("errors", [])
        return out
    except (RuntimeError, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        return {"errors": [f"{product}: {str(exc)[:200]}"]}


LANDED = {product: (lambda product=product: _landed_cmd(product)) for product in LANDED_CMDS}


def _landed(product, fresh=False):
    key = f"builds:landed:{product}"
    if fresh:
        swr.invalidate(key)
    return swr.cached(key, 600, LANDED[product])


# ---- Feed -------------------------------------------------------------------------------------


def _dispatch_values(spec, raw):
    """Check every input against the fixed spec. Unknown names are refused, never passed through."""
    raw = raw if isinstance(raw, dict) else {}
    known = {i["name"] for i in spec["inputs"]}
    extra = sorted(set(raw) - known)
    if extra:
        raise BuildsError(400, f"Unknown input: {', '.join(extra)}")
    out = {}
    for i in spec["inputs"]:
        kind = i.get("type", "string")
        v = raw.get(i["name"], i.get("default"))
        if kind == "boolean":
            if not isinstance(v, bool):
                raise BuildsError(400, f"{i['name']} must be true or false")
            out[i["name"]] = "true" if v else "false"
            continue
        v = "" if v is None else v
        if not isinstance(v, str) or not v.isascii() or len(v) > 300 or "\n" in v:
            raise BuildsError(400, f"{i['name']} must be one line of plain text")
        v = v.strip()
        if kind == "choice" and v not in (i.get("options") or []):
            raise BuildsError(
                400, f"{i['name']} must be one of {', '.join(i.get('options') or [])}"
            )
        if i.get("required") and not v:
            raise BuildsError(400, f"{i['name']} is required")
        if v and i.get("pattern") and not re.match(i["pattern"], v):
            raise BuildsError(400, f"{i['name']} is not valid: {v}")
        if v or i.get("required"):
            out[i["name"]] = v
    return out


def _publishes(spec, values):
    """True when a value the spec marks as publishing is the one this start carries."""
    for i in spec["inputs"]:
        if "publishes_when" not in i or i["name"] not in values:
            continue
        want = i["publishes_when"]
        have = values[i["name"]]
        if (
            (have == "true")
            if want is True
            else (have == "false")
            if want is False
            else (have == str(want))
        ):
            return True
    return False


def _live_run(key, ref):
    """The newest cached run of the pipeline on `ref` when it is queued, running or waiting, else None. Cache only: a
    start never waits on the code host to be refused."""
    feed = swr.peek("builds:feed") or {}
    for p in feed.get("pipelines") or []:
        if p.get("key") != key:
            continue
        for r in p.get("runs") or []:
            if r.get("branch") == ref and r.get("status") in _RUNNING:
                return r
    return None


def dispatch(payload, run=None):
    """POST /api/builds/dispatch {pipeline, ref?, inputs?}. Starts the workflow through the code host. The module's docstring
    has the contract: fixed input spec, unknown inputs refused, safe defaults, dedupe, paused and running refusals."""
    payload = payload if isinstance(payload, dict) else {}
    key = payload.get("pipeline")
    pipe = next((p for p in PIPELINES if p["key"] == key), None)
    spec = DISPATCH.get(key) if pipe else None
    if not spec:
        raise BuildsError(404, "Unknown pipeline")
    ref = payload.get("ref") or "main"
    if not isinstance(ref, str) or not (
        ref == "main" or (spec["ref"] == "branch" and BRANCH_OK.match(ref))
    ):
        raise BuildsError(
            400,
            "This workflow runs from main"
            if spec["ref"] == "main"
            else "Ref must be main or a ticket branch",
        )
    values = _dispatch_values(spec, payload.get("inputs"))
    if spec["paused"]:
        raise BuildsError(409, f"{pipe['label']} is paused")
    live = _live_run(key, ref)
    if live:
        raise BuildsError(
            409, f"{pipe['label']} already has run {live.get('id')} {live.get('status')} on {ref}"
        )
    token = (key, ref, tuple(sorted(values.items())))
    with _action_lock:
        last = _dispatched.get(token)
        if last and time.time() - last < DISPATCH_GAP_S:
            return {"started": False, "already": True, "publishes": _publishes(spec, values)}
        argv = [infra.GH, "workflow", "run", pipe["workflow"], "-R", REPO, "--ref", ref]
        for k, v in values.items():
            argv += ["-f", f"{k}={v}"]
        p = (run or subprocess.run)(argv, capture_output=True, text=True, timeout=40)
        if p.returncode != 0:
            raise BuildsError(
                502,
                ((p.stderr or p.stdout) or "workflow run failed").strip().splitlines()[-1][:300],
            )
        _dispatched[token] = time.time()
    swr.kick("builds:refresh", lambda: swr.cached("builds:feed", 8, _feed, fresh=True))
    return {
        "started": True,
        "already": False,
        "workflow": pipe["workflow"],
        "ref": ref,
        "inputs": values,
        "publishes": _publishes(spec, values),
    }


def _feed():
    out = {"generated_utc": infra._utc_now(), "repo": REPO, "pipelines": [], "errors": []}
    priv = _priv_pending()

    def runs_for(p):
        d = infra._gh(
            [
                "api",
                f"repos/{REPO}/actions/workflows/{p['workflow']}/runs?per_page={RUNS_PER_PIPELINE}",
            ]
        )
        return d.get("workflow_runs", [])

    with ThreadPoolExecutor(max_workers=4) as pool:
        lists = list(pool.map(lambda p: infra._safe(runs_for, p), PIPELINES))
    work = []
    for p, (runs, err) in zip(PIPELINES, lists):
        if err:
            out["errors"].append(f"{p['label']}: {err}")
        work.append((p, runs or []))
    flat = [(p, r) for p, runs in work for r in runs]
    with ThreadPoolExecutor(max_workers=6) as pool:
        views = list(pool.map(lambda pr: _run_view(pr[0], pr[1], priv), flat))
    by_key = {}
    for (p, _), v in zip(flat, views):
        by_key.setdefault(p["key"], []).append(v)
    refresh = set()
    for p, _runs in work:
        rv = by_key.get(p["key"], [])
        newest_done = next((r["id"] for r in rv if r["status"] == "completed"), None)
        prev = _last_done.get(p["key"])
        if prev is not None and newest_done != prev:
            refresh.add(p["product"])
        _last_done[p["key"]] = newest_done
        rv.sort(
            key=lambda r: (r.get("updated") or r.get("created") or "", r["id"]), reverse=True
        )  # newest first
        out["pipelines"].append(
            {
                "state": pipeline_state(rv),
                "key": p["key"],
                "product": p["product"],
                "label": p["label"],
                "workflow": p["workflow"],
                "refusal": bool(p.get("refusal")),
                "dispatch": DISPATCH.get(p["key"]),
                "url": f"https://github.com/{REPO}/actions/workflows/{p['workflow']}",
                "runs": rv,
            }
        )
    out["landed"] = {}
    for prod in LANDED:
        val, err = infra._safe(_landed, prod, prod in refresh)
        out["landed"][prod] = val or {"errors": [err or "unavailable"]}
    # Cards by latest activity: a pipeline with a run in flight on top, then the newest run first.
    out["pipelines"].sort(
        key=lambda p: (
            bool(p["state"]["current"]),
            (p["runs"][0].get("updated") or p["runs"][0].get("created") or "") if p["runs"] else "",
        ),
        reverse=True,
    )
    allruns = [r for p in out["pipelines"] for r in p["runs"]]
    out["running"] = sum(
        1 for r in allruns if r["status"] in ("in_progress", "queued", "requested", "pending")
    )
    out["waiting"] = sum(1 for r in allruns if r["status"] == "waiting")
    out["active"] = bool(out["running"] or out["waiting"])
    return out


def get():
    last = swr.peek("builds:feed")
    ttl = (
        8 if (last is None or last.get("active") or _pending) else 60
    )  # poll fast until an update shows its run
    return _finalize(swr.cached("builds:feed", ttl, _feed))


FAILED = ("failure", "timed_out", "startup_failure")
_IN_FLIGHT = ("in_progress", "queued", "requested", "pending", "waiting")


def pipeline_state(runs):
    """Current state vs history for one pipeline's runs (newest first). `current` is the run in flight (queued, running or
    waiting), never counted as failed; `failed` is true only while the newest FINISHED run on main failed (a later green
    run on main clears it, a run on a branch never counts, cancelled is not a failure); `last_main` is that run; `history` is
    the ids of every older finished run, which the card folds away so a fixed failure never reads as current."""
    current = next((r for r in runs if r.get("status") in _IN_FLIGHT), None)
    finished = [r for r in runs if r.get("status") == "completed"]
    last_main = next((r for r in finished if r.get("branch") == "main"), None)
    newest = finished[0] if finished else None
    return {
        "current": current["id"] if current else None,
        "failed": bool(last_main and last_main.get("conclusion") in FAILED),
        "last_main": {"id": last_main["id"], "conclusion": last_main.get("conclusion")}
        if last_main
        else None,
        "history": [r["id"] for r in finished if newest is not None and r["id"] != newest["id"]],
    }


def main_failure_items(feed):
    """One item per pipeline whose newest finished run on main failed: {key, label, product, run, conclusion, url}."""
    out = []
    for p in (feed or {}).get("pipelines") or []:
        runs = p.get("runs") or []
        st = pipeline_state(runs)
        if st["failed"]:
            r = next(r for r in runs if r["id"] == st["last_main"]["id"])
            out.append(
                {
                    "key": p.get("key"),
                    "label": p.get("label"),
                    "product": p.get("product"),
                    "run": r["id"],
                    "conclusion": r.get("conclusion"),
                    "url": r.get("url"),
                }
            )
    return out


def main_failures(feed):
    """The same as text, one line per pipeline (the sidebar and the Overview read the items)."""
    return [f"{i['label']}: last main run {i['conclusion']}" for i in main_failure_items(feed)]


def badge():
    """Sidebar facts. Never blocks the badges call: a cold cache warms in the background and counts 0 until then, a warm one is
    served stale-while-revalidate. Running and waiting are a soft count, never a problem; `failed` is the lines of
    main_failures and `failed_items` the same as items."""
    last = swr.peek("builds:feed")
    if last is None:
        threading.Thread(target=get, daemon=True).start()
        return {"running": 0, "waiting": 0, "failed": [], "failed_items": []}
    last = get()
    return {
        "running": last.get("running", 0),
        "waiting": last.get("waiting", 0),
        "failed": main_failures(last),
        "failed_items": main_failure_items(last),
    }


if __name__ == "__main__":
    t = time.time()
    d = _feed()
    print(json.dumps(d, indent=1, default=str)[:200])
    for p in d["pipelines"]:
        print(
            p["label"],
            [
                (
                    r["id"],
                    r["status"],
                    r["conclusion"],
                    (r["reason"] or {}).get("message", "")[:80],
                    r["summary"],
                )
                for r in p["runs"][:3]
            ],
        )
    print(json.dumps(d["landed"], indent=1, default=str))
    print(d["errors"], "running", d["running"], "waiting", d["waiting"], f"{time.time() - t:.1f}s")
