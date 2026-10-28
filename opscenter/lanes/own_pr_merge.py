#!/usr/bin/env python3
"""
own_pr_merge.py
Purpose: Auto-merge lane for the owner's own the primary repository PRs (author
         the owner's account). GitHub never lets me approve the owner's own PR, so the engineer
         review lane cannot approve these; they only merge with the owner's maintainer
         bypass. Every review-gate tick this lane rebase-merges one of the owner's PRs
         with that bypass (--admin --match-head-commit) ONLY when ALL hold:
           - open, not a draft, not a model-bump PR (that lane owns those),
             no hold label (policy own_pr_merge.hold_labels)
           - no merge conflict
           - every check finished and green, including `ai-review result`
           - the PR review verdict for this head has 0 blocking and at most
             own_pr_merge.max_high high findings (default 0), unless the owner's
             the owner's account comments after that review carry <!-- triage:<head> H1 H2 -->
             markers whose ids together name every high finding (H1..Hn) and,
             on the override path, every blocking one (B1..Bn). A bare marker
             with no ids covers nothing.
           - the engineer-lane check (pr_review.py check) raises no
             escalation: policy.json path/line rules, the tfplan matcher,
             plan destroy/replace, blocking review; and 0 unresolved threads
           - no change-freeze window is active (state/change-freeze.json)
         Everything else stays on Ops Center The owner's PRs with the reason.
Date:    2026-10-09

         Targets: primary (default) and secondary (--target secondary, policy
         <state dir>/secondary-review/own-pr-policy.json, which inherits the
         primary IaC line rules). A PR whose AI review was skipped by the
         workflow's own path filter (docs only) counts as reviewed-clean.
         Auto-fix: every held PR with a fixable problem goes to
         autofix.consider() on the same pass, which starts one fix session
         at once. Only the owner's PRs: the list is --author me and the fixer re-checks.
         a red terraform-drift coverage check counts as resolved when the sweep
         failed only on unmanaged ids and every one is imported by a successful
         terraform-ci plan job of the same tier on this head (the apply clears it).

         PIPELINE V2: (a) destroys in the plan that only another open PR of
         mine declares (its branch applied them) are "waits on #n", never a sign-off, (b) a red
         check whose failed jobs all show infrastructure noise is re-run (failed jobs only, max
         own_pr_merge.max_noise_retries per head) instead of starting a fix session, (c) a policy
         hold the owner already signed off for this head in an Ops Center decision card
         (own-pr-signoffs.json, written only by the Ops Center) merges on the next pass.

Usage:   own_pr_merge.py tick [--target secondary]   (called by the review-gate scripts)
         own_pr_merge.py status [--target secondary]
         own_pr_merge.py check <pr> [--target secondary]   (read-only: prints the decision)
Output:  tick prints nothing unless something needs me (a failed merge, a
         failing lane, or notify_on_merge=true); lines start with
         [primary the owner's PR].
Exit:    0 always for tick.
Test hooks: OPRG_GH_BIN, OPRG_STATE_DIR, OPRG_CACHE_DIR (as the engine),
            OPRG_DRY_RUN=1 (never merges; logs would_merge),
            OWNPR_FREEZE_FILE (change-freeze.json path).
System python3 is 3.9: no 3.10+ syntax.
"""

import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import paths
from gh_run_jobs import run_jobs

HOME = Path.home()
HERE = Path(__file__).resolve().parent
ENGINE_PY = HERE / "pr_review.py"
FIXER_PY = HERE / "autofix.py"
# The target must be set before the engine loads: it reads OPRG_* once at import.
_ARGS = sys.argv[1:]
TARGET = (
    _ARGS[_ARGS.index("--target") + 1]
    if "--target" in _ARGS and _ARGS.index("--target") + 1 < len(_ARGS)
    else "primary"
)
if TARGET == "secondary":
    os.environ.setdefault(
        "OPRG_POLICY", str(paths.state_dir() / "secondary-review" / "own-pr-policy.json")
    )
    os.environ.setdefault("OPRG_STATE_DIR", str(paths.state_dir() / "secondary-review"))
    os.environ.setdefault("OPRG_CACHE_DIR", str(paths.agent_home() / "cache" / "secondary-own-pr"))
elif TARGET != "primary":
    sys.exit(f"unknown --target {TARGET}")
FREEZE_FILE = Path(
    os.environ.get("OWNPR_FREEZE_FILE", str(paths.state_dir() / "change-freeze.json"))
)
TAG = f"[{TARGET} the owner's PR]"
BUMP_MARK = "-review-model-bump-"
RECHECK_HELD_S = 1800  # re-run the deep check on an unchanged held head at most every 30 min
# A triage reply counts only with this hidden marker naming the reviewed head and the review
# table ids it answers: <!-- triage:<sha> H1 H3 B1 -->, case-insensitive, space or comma
# separated. A bare marker names no ids, so it clears nothing.
TRIAGE_RE = re.compile(r"<!--\s*triage:([0-9a-fA-F]{7,40})((?:[\s,]+[HhBb]\d+)*)[\s,]*-->")
TRIAGE_ID_RE = re.compile(r"[HhBb]\d+")
SIGNOFF_FILE = None  # set after the engine loads (cache dir per target)
NEVER_SIGNOFF = {
    "plan-destroy",
    "plan-replace",
}  # deletes go through Approve and merge (destroy routing)
NOISE_RE = re.compile(
    r"toomanyrequests|pull rate limit|429 Too Many Requests|ECONNRESET|connection reset by peer|socket hang up"
    r"|ETIMEDOUT|EAI_AGAIN|Could not resolve host|TLS handshake timeout|i/o timeout|The operation was canceled"
    r"|runner has received a shutdown signal|lost communication with the server|502 Bad Gateway"
    r"|503 Service Unavailable|504 Gateway Time-?out|AADSTS700024|not within its valid time range",
    re.I,
)
RESOURCE_RE = re.compile(r'^[+-]\s*resource\s+"([^"]+)"\s+"([^"]+)"')
DEFAULTS = {
    "enabled": True,
    "max_noise_retries": 2,
    "hold_labels": ["do-not-merge", "hold"],
    "max_high": 0,
    "respect_freeze": True,
    "notify_on_merge": False,
}


def _engine():
    spec = importlib.util.spec_from_file_location("pr_review", str(ENGINE_PY))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


eng = _engine()
GhError = eng.GhError
_engine_policy = eng.policy


def _policy_with_inheritance():
    """The target policy, plus the IaC line rules it inherits (secondary inherits primary)."""
    pol = _engine_policy()
    src = pol.get("inherit_line_rules_from")
    if src:
        base_path = Path(os.path.expanduser(src))
        base_raw = (
            base_path if base_path.is_absolute() else paths.state_dir() / base_path
        ).read_bytes()
        base = json.loads(base_raw)
        pol["line_rules"] = list(base.get("line_rules") or []) + list(pol.get("line_rules") or [])
        if base.get("role_assignment_scope") and not pol.get("role_assignment_scope"):
            pol["role_assignment_scope"] = base["role_assignment_scope"]
        # A change to the inherited rules must invalidate the lane cache too.
        pol["_sha"] = hashlib.sha1((pol["_sha"]).encode() + base_raw).hexdigest()[:12]
    return pol


eng.policy = (
    _policy_with_inheritance  # eng.check() resolves policy() from the module, so it sees this too
)


def _fixer():
    spec = importlib.util.spec_from_file_location("autofix", str(FIXER_PY))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fixer = _fixer()
STATE_FILE = eng.CACHE_DIR / "own-pr-merge.json"
SIGNOFF_FILE = eng.CACHE_DIR / "own-pr-signoffs.json"
NOW = dt.datetime.now(dt.timezone.utc)
NOW_ISO = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}
RED = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"}


def config(pol):
    cfg = dict(DEFAULTS)
    cfg.update(pol.get("own_pr_merge") or {})
    cfg["ignore_checks_regex"] = pol.get("ignore_checks_regex") or ""
    return cfg


def load_state():
    return eng.load_json(STATE_FILE, {"prs": {}})


def save_state(st):
    st["updated"] = NOW_ISO
    eng.write_json(STATE_FILE, st)


def log(rec):
    eng.log_decision(dict({"lane": "own-pr"}, **rec))


def rollup_state(rollup, ignore=""):
    """(red, pending, ai_result) from a gh pr list statusCheckRollup. Checks whose name
    matches `ignore` (policy ignore_checks_regex, e.g. Vercel on secondary) never count."""
    best = {}
    for c in rollup or []:
        name = c.get("name") or c.get("context") or "?"
        if ignore and re.search(ignore, name):
            continue
        wf = c.get("workflowName") or ""
        key = f"{wf}/{name}" if wf else name
        val = (c.get("conclusion") or c.get("state") or c.get("status") or "PENDING").upper()
        ts = c.get("startedAt") or ""
        if key not in best or ts >= best[key][0]:
            best[key] = (ts, val)
    vals = {k: v for k, (_, v) in best.items()}
    red = sorted(k for k, v in vals.items() if v in RED)
    pending = sorted(k for k, v in vals.items() if v not in OK and v not in RED)
    ai = None
    for k, v in vals.items():
        if k.endswith("ai-review result"):
            ai = v
    return red, pending, ai


def active_freeze(now_utc=None):
    """The active change-freeze window dict, or None. Windows are local wall
    times in the file's timezone."""
    data = eng.load_json(FREEZE_FILE, {})
    windows = data.get("windows") or []
    if not windows:
        return None
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(data.get("timezone") or "America/New_York")
    except Exception:  # noqa: BLE001 - fall back to EDT offset if tzdata is missing
        tz = dt.timezone(dt.timedelta(hours=-4))
    local = (now_utc or NOW).astimezone(tz).replace(tzinfo=None)
    for w in windows:
        try:
            start = dt.datetime.fromisoformat(w["start"])
            end = dt.datetime.fromisoformat(w["end"])
        except (KeyError, ValueError):
            continue
        if start <= local <= end:
            return w
    return None


def cheap_gate(pr, cfg):
    """Decision from the PR list data alone: (status, reason). status is
    'skip' (not this lane), 'waiting' (checks still running) or 'held', or
    None when it passes to the deep check."""
    if BUMP_MARK in (pr.get("headRefName") or ""):
        return "skip", "model bump lane"
    if pr.get("isDraft"):
        return "held", "draft"
    labels = {(lbl.get("name") or "").lower() for lbl in pr.get("labels") or []}
    hit = sorted(labels & {h.lower() for h in cfg["hold_labels"]})
    if hit:
        return "held", f"label {hit[0]}"
    if pr.get("mergeable") == "CONFLICTING":
        return "held", "merge conflict with main"
    red, pending, ai = rollup_state(pr.get("statusCheckRollup"), cfg.get("ignore_checks_regex", ""))
    # A red terraform plan may be only terraform-ci's destroy guard. That is the owner's sign-off, not a
    # fix, and only the deep check (plan logs) can tell, so those reds go on to it. A red
    # coverage sweep may be only the objects this PR imports, same reasoning.
    if red and not all(guard_candidate(k) or coverage_candidate(k) for k in red):
        return "held", "checks red: " + ", ".join(red)[:200]
    if pending:
        return "waiting", f"{len(pending)} check(s) running"
    if ai != "SUCCESS":
        return "waiting", "ai-review result not reported yet"
    return None, ""


def guard_candidate(key):
    """A red check that could be terraform-ci's destroy guard (a plan job or its result rollup)."""
    return key == "terraform-ci/terraform-ci result" or key.startswith(
        "terraform-ci/terraform plan ("
    )


# the coverage sweep compares live objects to tfstate, so a PR that imports hand-made
# objects stays red there until its own apply runs. A coverage red counts as resolved only when
# the sweep failed on unmanaged ids alone and the head's terraform-ci plan imports every one of
# them in a plan job of the same tier that succeeded. Any read error or other failure = not
# resolved (the hold stays).
COVERAGE_KEY = re.compile(r"^terraform-drift/coverage \((dev-tier|platform)\)$")
PLAN_JOB = re.compile(r"^terraform plan \((\S+) (dev-tier|platform)\)$")
IMPORT_ID = re.compile(r"Preparing import\.\.\. \[id=([^\]\s]+)\]")
ERROR_LINE = re.compile(r"^##\[error\](.*)$")
UNMANAGED_ERR = re.compile(r"^(dev-tier|platform) (/subscriptions/\S+)$")
EXIT_ERR = "Process completed with exit code 1."


def coverage_candidate(key):
    return bool(COVERAGE_KEY.match(key))


def _norm_id(rid):
    """Lowercase ARM id with the subscription segment masked (job logs print it as ***) and
    any query suffix dropped (azapi import ids carry ?api-version=, coverage ids never do)."""
    rid = rid.strip().split("?", 1)[0]
    return re.sub(r"^/subscriptions/[^/]+", "/subscriptions/*", rid.lower())


def _log_bodies(log):
    for line in (log or "").splitlines():
        body = re.sub(r"^\S+Z ", "", line)
        yield re.sub(r"\x1b\[[0-9;]*m", "", body).rstrip()


def _head_run(pol, head, workflow_file):
    runs = eng.gh(["api", f"repos/{pol['repo']}/actions/runs?head_sha={head}&per_page=50"]) or {}
    found = [
        r
        for r in runs.get("workflow_runs", [])
        if (r.get("path") or "").endswith(workflow_file) and r.get("event") == "pull_request"
    ]
    if not found:
        return None
    run = sorted(found, key=lambda r: r.get("created_at") or "")[-1]
    return run if run.get("status") == "completed" else None


def _run_jobs(pol, run):
    return run_jobs(eng.gh, pol["repo"], run["id"])


def _job_log(pol, job):
    return eng.gh(
        ["api", f"repos/{pol['repo']}/actions/jobs/{job['id']}/logs", "--allow-escape-sequences"],
        raw=True,
        timeout=90,
    )


def plan_imports(pol, head):
    """{tier: set(normalized ids)} imported by successful terraform-ci plan jobs on this head."""
    run = _head_run(pol, head, "terraform-ci.yml")
    out = {}
    if not run:
        return out
    for j in _run_jobs(pol, run):
        m = PLAN_JOB.match(j.get("name") or "")
        if not m or j.get("conclusion") != "success":
            continue
        ids = {
            _norm_id(x.group(1))
            for b in _log_bodies(_job_log(pol, j))
            for x in [IMPORT_ID.search(b)]
            if x
        }
        out.setdefault(m.group(2), set()).update(ids)
    return out


def coverage_unmanaged(pol, head, tier):
    """Normalized unmanaged ids from the failed coverage job of this tier, or None when the
    job failed for any other reason (a read error, an unparsed error line, nothing listed)."""
    run = _head_run(pol, head, "terraform-drift.yml")
    if not run:
        return None
    job = next((j for j in _run_jobs(pol, run) if j.get("name") == f"coverage ({tier})"), None)
    if not job or job.get("conclusion") != "failure":
        return None
    ids, other = [], False
    for b in _log_bodies(_job_log(pol, job)):
        m = ERROR_LINE.match(b)
        if not m:
            continue
        msg = m.group(1).strip()
        u = UNMANAGED_ERR.match(msg)
        if u and u.group(1) == tier:
            ids.append(_norm_id(u.group(2)))
        elif msg != EXIT_ERR:
            other = True
    return None if other or not ids else ids


MAIN_RERUNS_FILE = (
    eng.CACHE_DIR / "main-pending-reruns.json"
)  # {pr: "run_id:started_at"} re-run once
MAIN_PENDING_PREFIXES = ("main not applied:", "plans predate main's last apply:")
COVERED = {}  # (pr, head) -> coverage check keys resolved by the head's own imports, for the lane state


def import_resolved(pol, head, red):
    """(covered keys, total covered ids) for the coverage reds this head's own imports resolve."""
    keys = [k for k in red if coverage_candidate(k)]
    if not keys:
        return [], 0
    try:
        imports = plan_imports(pol, head)
        covered, n_ids = [], 0
        for k in keys:
            tier = COVERAGE_KEY.match(k).group(1)
            ids = coverage_unmanaged(pol, head, tier)
            if ids and set(ids) <= imports.get(tier, set()):
                covered.append(k)
                n_ids += len(set(ids))
        return covered, n_ids
    except GhError:
        return [], 0


def review_and_triage(pol, n, head):
    """(verdict for this head or None, triaged ids) from one comments read. triaged
    ids = the union of finding ids (upper case, for example {"H1", "B2"}) named by
    `<!-- triage:<head sha, 7+ hex> H1 B2 -->` markers in the owner's account comments posted
    after the newest PR review comment for this head. A plain comment (for example
    asking for a fix) or a bare marker with no ids never counts as triage."""
    out = eng.gh(
        [
            "api",
            "--paginate",
            f"repos/{pol['repo']}/issues/{n}/comments?per_page=100",
            "--jq",
            ".[] | @json",
        ],
        raw=True,
    )
    verdict, review_ts, mine = None, "", []
    for line in out.splitlines():
        if not line.strip():
            continue
        c = json.loads(line)
        body = c.get("body") or ""
        login = (c.get("user") or {}).get("login")
        if (
            login == "github-actions[bot]"
            and body.startswith(eng.AI_REVIEW_MARKER)
            and eng.AI_REVIEW_DATA_PREFIX in body
        ):
            blob = body.split(eng.AI_REVIEW_DATA_PREFIX, 1)[1].split(eng.AI_REVIEW_DATA_SUFFIX, 1)[
                0
            ]
            try:
                v = json.loads(eng.base64.b64decode(blob).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if v.get("head_sha") == head:
                verdict, review_ts = v, max(c.get("updated_at") or "", c.get("created_at") or "")
        elif login == pol["self_login"]:
            ids = set()
            for m in TRIAGE_RE.finditer(body):
                if head.startswith(m.group(1).lower()):
                    ids |= {x.upper() for x in TRIAGE_ID_RE.findall(m.group(2) or "")}
            if ids:
                mine.append((c.get("created_at") or "", ids))
    triaged = set()
    if review_ts:
        for ts, ids in mine:
            if ts > review_ts:
                triaged |= ids
    return verdict, triaged


def _id_key(x):
    return (x[0], int(x[1:]))


def required_ids(prefix, count):
    """The review table ids for count findings of one severity: B1..Bn or H1..Hn."""
    return {f"{prefix}{i}" for i in range(1, max(0, int(count or 0)) + 1)}


def coverage_note(need, triaged, lead="triage reply"):
    """Hold text for a partial triage: 'triage reply covers H2 only (missing H1)'."""
    have = sorted(need & triaged, key=_id_key)
    miss = ", ".join(sorted(need - triaged, key=_id_key))
    if not have:
        return f"no triage reply from me on this head (missing {miss})"
    return f"{lead} covers {', '.join(have)} only (missing {miss})"


OVERRIDE_LABEL = "ai-review-override"
OVERRIDE_RULE = "ai-review-override"


def override_by_me(pol, pr):
    """True when the override label is on the PR and the newest labeled event for it
    was mine. The repo removes the label on every push, so it always belongs to the
    current head. Any read error = False (no exception, no merge button)."""
    labels = {(lbl.get("name") or "").lower() for lbl in pr.get("labels") or []}
    if OVERRIDE_LABEL not in labels:
        return False
    try:
        out = eng.gh(
            [
                "api",
                "--paginate",
                f"repos/{pol['repo']}/issues/{pr['number']}/events?per_page=100",
                "--jq",
                ".[] | @json",
            ],
            raw=True,
        )
    except GhError:
        return False
    actor = None
    for line in (out or "").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if (
            e.get("event") == "labeled"
            and ((e.get("label") or {}).get("name") or "").lower() == OVERRIDE_LABEL
        ):
            actor = (e.get("actor") or {}).get("login")
    return actor == pol["self_login"]


def review_skipped(pr):
    """True when the AI review workflow passed its result check but skipped the review job
    for this head (its own path filter, e.g. a docs-only PR). Then there is no verdict
    comment by design."""
    best = {}
    for c in pr.get("statusCheckRollup") or []:
        key = (c.get("workflowName") or "", c.get("name") or c.get("context") or "")
        ts = c.get("startedAt") or ""
        if key not in best or ts >= best[key][0]:
            best[key] = (ts, (c.get("conclusion") or c.get("status") or "").upper())
    for (wf, name), (_, val) in best.items():
        if name == "ai-review result" and val == "SUCCESS":
            return best.get((wf, "review"), ("", ""))[1] == "SKIPPED"
    return False


# ---------------------------------------------------------------- pipeline v2 helpers


def _addr_key(addr):
    """(type, name) of a Terraform resource address, without module path or instance key.
    module.x.azurerm_role_assignment.r["k"] -> ("azurerm_role_assignment", "r"). None for data."""
    a = re.sub(r"\[[^\]]*\]", "", addr or "")
    parts = [p for p in a.split(".") if p]
    while len(parts) >= 2 and parts[0] == "module":
        parts = parts[2:]
    if len(parts) != 2 or parts[0] == "data":
        return None
    return parts[0], parts[1]


def _diff_resources(diff):
    """{(type, name)} of resource blocks a diff adds or removes."""
    out = set()
    for line in (diff or "").splitlines():
        m = RESOURCE_RE.match(line)
        if m:
            out.add((m.group(1), m.group(2)))
    return out


DIFFS = {}  # (repo, pr, head) -> diff text, one read per PR head per pass


def _pr_diff(repo, n, head):
    key = (repo, int(n), head)
    if key not in DIFFS:
        DIFFS[key] = eng.gh(["pr", "diff", str(n), "-R", repo], raw=True, timeout=120)
    return DIFFS[key]


def list_open_all(pol):
    """Every open PR in the repo (any author), number and head only. [] on a read failure."""
    try:
        return (
            eng.gh(
                [
                    "pr",
                    "list",
                    "-R",
                    pol["repo"],
                    "--state",
                    "open",
                    "--limit",
                    "100",
                    "--json",
                    "number,headRefOid",
                ]
            )
            or []
        )
    except GhError:
        return []


def guard_roots(plan, red):
    """Root names of the plan jobs that are red only on the destroy guard, e.g. {"platform-core"}.
    Empty when any of them cannot be named."""
    roots, names = set(), set()
    for r in (plan or {}).get("roots") or []:
        if r.get("guard_only"):
            m = PLAN_JOB.match(r.get("job") or "")
            if not m:
                return set()
            roots.add(m.group(1))
            names.add("terraform-ci/" + r["job"])
    return roots if names else set()


def touches_roots(pol, pr, roots):
    """True when this PR's diff changes a file under any of these roots, or a module one of them
    sources. Any read failure counts as True (the hold stays)."""
    try:
        diff = _pr_diff(pol["repo"], pr["number"], pr["headRefOid"])
    except GhError:
        return True
    files = set(re.findall(r"^diff --git a/(\S+) ", diff or "", re.M))
    mods = {
        f.split("/")[3]
        for f in files
        if f.startswith("infrastructure/terraform/modules/") and f.count("/") >= 4
    }
    for root in roots:
        base = f"infrastructure/terraform/{root}/"
        if any(f.startswith(base) for f in files):
            return True
        for mod in mods:
            try:
                hit = (
                    eng.gh(["api", f"search/code?q=modules/{mod}+repo:{pol['repo']}+path:{base}"])
                    or {}
                )
            except GhError:
                return True
            if int(hit.get("total_count") or 0) > 0:
                return True
    return False


def _instance_key(addr):
    """The for_each key of an address: x.y["jsm-mail-relay"] -> "jsm-mail-relay". None without one."""
    m = re.search(r'\["([^"]+)"\]\s*$', addr or "")
    return m.group(1) if m else None


def _declares(diff, addr):
    """True when a diff's added or removed lines declare this destroyed object: its resource block,
    or (for a for_each instance) its key as a whole token, e.g. a new app entry in deploy.json. A composite key with a pipe
    ("avd|GET") counts as declared when its first segment is declared as a whole token."""
    k = _addr_key(addr)
    if k and k in _diff_resources(diff):
        return True
    key = _instance_key(addr)
    if not key:
        return False
    # A composite key ("avd|GET") is built from an app and another part, and only the app is ever
    # written in a diff, so the first segment stands for it. Same whole-token boundary rules.
    key = key.split("|", 1)[0]
    if not key:
        return False
    tok = re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(key) + r"(?![A-Za-z0-9_-])")
    return any(
        tok.search(line)
        for line in (diff or "").splitlines()
        if line[:1] in "+-" and line[:3] not in ("+++", "---")
    )


def foreign_destroys(pol, pr, destroyed, others):
    """Open PRs (any author, not this one) whose diffs declare every object the plan destroys,
    when this PR's own diff declares none of them. Their branches applied the objects into
    shared state, so this plan reads them as deletes. Returns sorted PR numbers, or [] when
    any destroy is this PR's own, unattributed, or a read failed (then the normal hold stays)."""
    addrs = [a for a in destroyed or [] if a]
    if not addrs:
        return []
    try:
        own = _pr_diff(pol["repo"], pr["number"], pr["headRefOid"])
        if any(_declares(own, a) for a in addrs):
            return []
        owners = {}
        for other in others:
            if other["number"] == pr["number"]:
                continue
            diff = _pr_diff(pol["repo"], other["number"], other["headRefOid"])
            for a in addrs:
                if _declares(diff, a):
                    owners.setdefault(a, set()).add(other["number"])
    except GhError:
        return []
    if set(owners) != set(addrs):
        return []
    return sorted({n for s in owners.values() for n in s})


def noise_retry(pol, pr, rec, cfg):
    """Re-run the failed jobs of this head when every failed job's log tail shows infrastructure
    noise (rate limits, resets, runner loss, expired OIDC assertion). Returns the waiting reason,
    or None when any failure looks real, the retry budget for this head is spent, or a read failed.
    Never reruns a check that is red for a reason it cannot name (core rule 1.12)."""
    done = int(rec.get("noise_retries") or 0)
    if done >= int(cfg.get("max_noise_retries", 2)):
        return None
    head = pr["headRefOid"]
    try:
        runs = (
            eng.gh(["api", f"repos/{pol['repo']}/actions/runs?head_sha={head}&per_page=50"]) or {}
        ).get("workflow_runs", [])
        latest = {}
        for r in runs:
            key = r.get("path") or r.get("name")
            if key not in latest or (r.get("created_at") or "") > (
                latest[key].get("created_at") or ""
            ):
                latest[key] = r
        failing = [
            r
            for r in latest.values()
            if r.get("status") == "completed" and r.get("conclusion") in ("failure", "timed_out")
        ]
        if not failing:
            return None
        hits = []
        for r in failing:
            jobs = [j for j in _run_jobs(pol, r) if j.get("conclusion") in ("failure", "timed_out")]
            if not jobs:
                return None
            for j in jobs:
                tail = "\n".join(list(_log_bodies(_job_log(pol, j)))[-200:])
                m = NOISE_RE.search(tail)
                if not m:
                    return None
                hits.append(f"{j.get('name')}: {m.group(0)}")
    except GhError:
        return None
    reason = f"re-running {len(hits)} job(s) that failed on infrastructure noise ({'; '.join(hits)[:160]})".replace(
        ";", ","
    )
    if eng.DRY_RUN:
        return "would be " + reason
    for r in failing:
        eng.gh(["run", "rerun", str(r["id"]), "--failed", "-R", pol["repo"]], raw=True)
    rec["noise_retries"] = done + 1
    log(
        {
            "pr": pr["number"],
            "decision": "noise-retry",
            "sha": head,
            "detail": reason,
            "attempt": done + 1,
        }
    )
    return reason


def signed_off(n, head, reason):
    """True when the owner signed off every rule of this 'needs me' hold for this exact head in an Ops
    Center decision card. Deletes and replaces never count (they need Approve and merge, which
    routes the destroy release). Any read error is False."""
    if not reason.startswith("needs me: "):
        return False
    rules = {r.strip() for r in reason[len("needs me: ") :].split(",") if r.strip()}
    rec = (eng.load_json(SIGNOFF_FILE, {}).get("prs") or {}).get(str(n)) or {}
    if rec.get("head") != head or not rules or rules & NEVER_SIGNOFF:
        return False
    return rules <= set(rec.get("rules") or [])


CARRIED = {}  # (pr, head) -> {"id", "from_head"}: heads that merge on the owner's earlier sign-off


def carry_signoff(n, head, c):
    """the owner's one sign-off on this PR carries to this head when the head raises no hit it does not
    cover (same rule and file content, or the same .github content from the plan card) and its plan
    adds no destroy, no replace and no new grant. Any error means no carry. Never used for the
    review-override rule, which is bound to the owner's triage on one head."""
    try:
        so = eng._tfgate().load_signoff()
        rec = so.active(n, lane=so.OWN)
        if not rec:
            return None
        r = so.review(rec, c.get("escalations") or [], c.get("plan"))
        if r["ok"]:
            return {"id": rec["id"], "from_head": rec["head_sha"]}
        # a .github file the sign-off does not cover by content may still be covered when its delta
        # since the head the owner signed adds or removes nothing sensitive. The plan guard stays as it was.
        if r["plan_new"] or not r["new"]:
            return None
        tf = eng._tfgate()
        paths = []
        for h in r["new"]:
            path = h.get("path") or so.path_of(h.get("where"))
            if (
                h.get("rule") != "github-dir"
                or not h.get("fp")
                or not str(path or "").startswith(".github/")
            ):
                return None
            ok, why = tf.delta_release(path, rec["head_sha"], head)
            if not ok:
                print(f"delta carry held PR #{n}: {path}: {why}", file=sys.stderr)
                return None
            paths.append(path)
        return {"id": rec["id"], "from_head": rec["head_sha"], "delta_paths": sorted(set(paths))}
    except Exception as e:  # noqa: BLE001 - fail closed
        print(f"sign-off carry check failed for PR #{n}: {e}", file=sys.stderr)
        return None


def signoff_newer(n, since_epoch):
    try:
        return eng._tfgate().load_signoff().latest_epoch(n) > float(since_epoch or 0)
    except Exception:  # noqa: BLE001
        return False


GATE_EVERY_S = 600  # a draft's gate is re-checked at most every 10 minutes per head and body
# Optional draft gate plug-in: a module named by OPSCENTER_DRAFT_GATE (a file path). Absent means a draft is
# never checked here and the lane leaves it alone.
GATE_PY = (
    Path(os.environ["OPSCENTER_DRAFT_GATE"]) if os.environ.get("OPSCENTER_DRAFT_GATE") else None
)


def _gate_module():
    if GATE_PY is None:
        return None
    spec = importlib.util.spec_from_file_location("draft_gate_plugin", str(GATE_PY))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def draft_gate(pr, rec, pol, gatemod=None, now=None):
    """(status, reason) for one of the owner's drafts. A draft that declares a gate block is
    checked against live data and, once every check passes, marked ready for review with the evidence
    posted on the PR. From the next pass the normal lane takes it (rebase, plans, policy holds).
    rec["gate"] keeps the last results for the Ops Center card. Every reason starts with "draft" so
    the auto-fixer never treats it as a fixable problem."""
    gatemod = gatemod or _gate_module()
    if gatemod is None:
        return "held", "draft: no draft gate plug-in is configured (OPSCENTER_DRAFT_GATE)"
    now = now or NOW
    body = pr.get("body") or ""
    gate = gatemod.parse(body)
    if gate is None:
        rec.pop("gate", None)
        return "held", "draft: no gate block, nothing tells the lane when it is ready"
    key = hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]
    g = rec.get("gate") or {}
    if g.get("key") == key and now.timestamp() - float(g.get("at_epoch") or 0) < GATE_EVERY_S:
        results = g.get("results") or []
    else:
        results = gatemod.evaluate(gate, pol["repo"], gh=eng.GH)
        g = {
            "key": key,
            "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "at_epoch": now.timestamp(),
            "results": results,
        }
        rec["gate"] = g
    met, total, first = gatemod.summary(results)
    if first:
        return (
            "held",
            f"draft: gate {met} of {total} met, waiting on {first['label']} ({first['detail']})",
        )
    if eng.DRY_RUN:
        return "held", f"draft: gate met ({total} of {total}), would mark it ready for review"
    lines = "\n".join(f"- {r['label']}: {r['detail']}" for r in results)
    eng.gh(["pr", "ready", str(pr["number"]), "-R", pol["repo"]], raw=True)
    try:  # noqa: SIM105
        eng.gh(
            [
                "pr",
                "comment",
                str(pr["number"]),
                "-R",
                pol["repo"],
                "--body",
                f"Every check in the gate passes, so I am marking this ready for review.\n\n{lines}",
            ],
            raw=True,
        )
    except GhError:
        pass  # the evidence is also in decisions.jsonl and on the card
    log(
        {
            "pr": pr["number"],
            "decision": "gate-cleared",
            "sha": pr["headRefOid"],
            "detail": lines[:600],
        }
    )
    return (
        "waiting",
        f"gate met ({total} of {total}): marked ready for review, the lane takes it from the next pass",
    )


def main_pending_hold(pol, pr, c):
    """the hold reason when the plan's destroys or replaces are main's own unapplied change,
    else None. A stale plan (it ran before main applied) gets its failed jobs re-run once per plan run,
    so the PR re-arms itself instead of showing a sign-off for changes it does not make."""
    plan = c.get("plan") or {}
    why = eng.main_pending_reason(plan)
    if not why:
        return None
    mp = plan.get("main_pending") or {}
    if mp.get("state") != "stale":
        return why
    run_id = mp.get("run_id") or plan.get("run_id")
    key = f"{run_id}:{plan.get('started_at')}"
    try:
        done = json.loads(MAIN_RERUNS_FILE.read_text()) if MAIN_RERUNS_FILE.exists() else {}
    except (OSError, ValueError):
        done = {}
    if done.get(str(pr["number"])) == key or eng.DRY_RUN:
        return why
    try:
        eng.gh(["run", "rerun", str(run_id), "--failed", "-R", pol["repo"]], raw=True)
    except GhError as e:
        return f"{why} (the re-run failed: {str(e)[:120]})"
    done[str(pr["number"])] = key
    try:  # noqa: SIM105
        MAIN_RERUNS_FILE.write_text(json.dumps(done))
    except OSError:
        pass
    log(
        {
            "pr": pr["number"],
            "decision": "main-pending-rerun",
            "sha": pr["headRefOid"],
            "detail": why,
        }
    )
    return why


def deep_gate(pr, cfg, pol, mine=None):
    """Verdict + engineer-lane check. Returns (ok, reason)."""
    n, head = pr["number"], pr["headRefOid"]
    verdict, triaged = review_and_triage(
        pol, n, head
    )  # triaged = finding ids the owner's triage replies name
    if not verdict and review_skipped(pr):
        verdict = {
            "verdict": "clean",
            "counts": {},
        }  # the workflow skipped the review (docs-only paths) and passed
    if not verdict:
        return False, "no PR review verdict for this head yet"
    counts = verdict.get("counts") or {}
    # a blocked verdict the owner overrode (label applied by me) and triaged on this
    # head is the owner's sign-off to give, never the lane's: it becomes a policy hold, so the
    # Ops Center offers Approve and merge and the lane itself never merges it.
    # the triage must name every blocking id (B1..Bn) for the override to count.
    overridden = False
    if verdict.get("verdict") == "blocked" or int(counts.get("blocking", 0)) > 0:
        need_b = required_ids("B", counts.get("blocking", 0))
        if (
            verdict.get("verdict") in ("blocked", "findings")
            and need_b <= triaged
            and override_by_me(pol, pr)
        ):
            overridden = True
        else:
            if verdict.get("verdict") not in ("clean", "findings"):
                why = f"PR review verdict {verdict.get('verdict')}"
            else:
                why = f"{counts.get('blocking')} blocking finding(s)"
            if need_b & triaged:
                # "override triage covers" keeps autofix mapping this to blocking-findings
                why += ", " + coverage_note(need_b, triaged, "override triage")
            return False, why
    elif verdict.get("verdict") not in ("clean", "findings"):
        return False, f"PR review verdict {verdict.get('verdict')}"
    highs = int(counts.get("high", 0))
    need_h = required_ids("H", highs)
    if highs > int(cfg["max_high"]) and not need_h <= triaged:
        return False, f"{highs} high finding(s), " + coverage_note(need_h, triaged)
    c = eng.check(n)
    if c.get("head_sha") != head:
        return False, "head moved during the check"
    held_main = main_pending_hold(pol, pr, c)
    if held_main:
        return False, held_main
    ch = c.get("checks") or {}
    covered, n_cov = import_resolved(pol, head, ch.get("red") or [])
    COVERED[(n, head)] = covered
    rest = [k for k in ch.get("red") or [] if k not in covered]
    guard_only = ch.get("destroy_guard_only")
    if covered and rest:
        guard_only = eng.destroy_guard_only(
            {"red": rest, "pending": ch.get("pending")}, c.get("plan")
        )
    plan = c.get("plan") or {}
    passed_foreign = None
    if plan.get("destroyed") and (guard_only or not rest):
        others = list_open_all(pol) or mine or []
        waits = foreign_destroys(pol, pr, plan["destroyed"], others)
        if waits:
            tags = ", ".join(f"#{x}" for x in waits)
            roots = guard_roots(plan, rest)
            if roots and not touches_roots(pol, pr, roots):
                # Every destroy belongs to another open branch and this PR does not change the
                # roots that plan them, so merging it never applies those deletes.
                passed_foreign = (
                    f"destroys in {', '.join(sorted(roots))} belong to {tags}, root not in this PR"
                )
                guard = {
                    "terraform-ci/" + r["job"]
                    for r in plan.get("roots") or []
                    if r.get("guard_only")
                }
                rest = [k for k in rest if k not in guard and k != eng.TF_CI_RESULT]
            else:
                return False, (
                    f"waits on {tags}: the plan destroys {len(plan['destroyed'])} object(s) only their branches "
                    f"declare ({', '.join(plan['destroyed'][:3])})"
                )[:300]
    if rest and not guard_only:
        return False, "checks red: " + ", ".join(rest)[:200]
    carried = None
    if (c.get("escalate") or overridden) and not overridden:
        carried = carry_signoff(n, head, c)
        if carried:
            CARRIED[(n, head)] = carried
    if (c.get("escalate") or overridden) and not carried:
        rules = sorted({e.get("rule", "?") for e in c.get("escalations") or []})
        if overridden:
            rules = [OVERRIDE_RULE] + rules
        return False, "needs me: " + ", ".join(rules)[:200]
    if int(c.get("unresolved_threads") or 0) > 0:
        return False, f"{c['unresolved_threads']} unresolved review thread(s)"
    green = ch.get("green") or (
        (bool(covered) or bool(passed_foreign)) and not rest and not ch.get("pending")
    )
    if not green:
        return False, "checks not green: " + ", ".join(rest + (ch.get("pending") or []))[:200]
    hi = f"{highs} high triaged" if highs else "0 high"
    cov = f", coverage red only on {n_cov} object(s) this PR imports" if covered else ""
    if passed_foreign:
        cov += ", " + passed_foreign
    if carried:
        dnote = (
            " (no sensitive change in " + ", ".join(carried["delta_paths"]) + ")"
            if carried.get("delta_paths")
            else ""
        )
        return (
            True,
            f"all checks green{cov}, 0 blocking, {hi}, carried the owner's sign-off from {carried['from_head'][:8]}{dnote}",
        )
    return True, f"all checks green{cov}, 0 blocking, {hi}, no policy flag"


def merge(pr, repo):
    n, head = pr["number"], pr["headRefOid"]
    eng.gh(
        ["pr", "merge", str(n), "-R", repo, "--rebase", "--admin", "--match-head-commit", head],
        raw=True,
    )
    v = eng.gh(["pr", "view", str(n), "-R", repo, "--json", "state,mergedAt,mergeCommit"])
    if (v or {}).get("state") != "MERGED":
        return False, f"merge call returned but PR state is {(v or {}).get('state')}"
    return True, ((v.get("mergeCommit") or {}).get("oid") or "")[:7]


ROLLUP_CAP = 100


def list_mine(pol):
    prs = (
        eng.gh(
            [
                "pr",
                "list",
                "-R",
                pol["repo"],
                "--author",
                pol["self_login"],
                "--state",
                "open",
                "--limit",
                "50",
                "--json",
                "number,title,url,author,headRefOid,headRefName,isDraft,mergeable,statusCheckRollup,labels,updatedAt,body",
            ]
        )
        or []
    )
    # gh pr list returns at most ROLLUP_CAP check contexts per PR. Re-runs and
    # cancelled runs can push a PR past it, which hides the newest results (a green
    # ai-review result read as "not reported yet"). gh pr view pages the full list.
    for pr in prs:
        if len(pr.get("statusCheckRollup") or []) >= ROLLUP_CAP:
            full = (
                eng.gh(
                    [
                        "pr",
                        "view",
                        str(pr["number"]),
                        "-R",
                        pol["repo"],
                        "--json",
                        "statusCheckRollup",
                    ]
                )
                or {}
            )
            if full.get("statusCheckRollup"):
                pr["statusCheckRollup"] = full["statusCheckRollup"]
    return prs


def evaluate(pr, cfg, pol, rec, force=False, mine=None):
    """Returns (status, reason, merged_sha_or_None)."""
    author = (pr.get("author") or {}).get("login")
    if author and author != pol["self_login"]:
        return (
            "skip",
            f"not my PR (author {author})",
            None,
        )  # engineer PRs are never merged or fixed here
    status, reason = cheap_gate(pr, cfg)
    if status:
        return status, reason, None
    if cfg["respect_freeze"]:
        w = active_freeze()
        if w:
            return "held", f"change freeze {w.get('id', '')} until {w.get('end', '')}", None
    head = pr["headRefOid"]
    # A held head is re-checked every 30 min, or at once when the PR changes
    # (a new comment such as a triage reply, a label, a review bumps updatedAt).
    if (
        not force
        and rec.get("head") == head
        and rec.get("deep") == "held"
        and not str(rec.get("reason") or "").startswith(
            MAIN_PENDING_PREFIXES
        )  # re-arm within one tick
        and rec.get("policy_sha") == pol["_sha"]
        and rec.get("pr_updated") == pr.get("updatedAt")
        and (NOW.timestamp() - float(rec.get("deep_epoch", 0))) < RECHECK_HELD_S
        and not signoff_newer(pr["number"], rec.get("deep_epoch", 0))
    ):
        if signed_off(pr["number"], head, rec.get("reason", "")):
            return (
                "ready",
                "signed off by me in the decision card: " + rec.get("reason", "")[10:],
                None,
            )
        return "held", rec.get("reason", "held"), None
    ok, why = deep_gate(pr, cfg, pol, mine)
    rec.update(
        {
            "deep": "ok" if ok else "held",
            "deep_epoch": NOW.timestamp(),
            "policy_sha": pol["_sha"],
            "pr_updated": pr.get("updatedAt"),
            "import_covered": COVERED.get((pr["number"], head), []),
        }
    )
    if not ok:
        if signed_off(pr["number"], head, why):
            return "ready", "signed off by me in the decision card: " + why[10:], None
        return "held", why, None
    return "ready", why, None


def tick():
    pol = eng.policy()
    cfg = config(pol)
    st = load_state()
    prs_state = st.setdefault("prs", {})
    fix_state = st.setdefault("fix", {})
    out = []
    try:
        if not cfg["enabled"]:
            return
        mine = list_mine(pol)
        open_nums = set()
        for pr in mine:
            n = str(pr["number"])
            open_nums.add(n)
            rec = prs_state.setdefault(n, {})
            if rec.get("head") != pr["headRefOid"]:
                rec.clear()
                rec["head"] = pr["headRefOid"]
            rec["title"] = pr.get("title")
            rec["url"] = pr.get("url")
            try:
                if pr.get("isDraft") and BUMP_MARK not in (pr.get("headRefName") or ""):
                    status, reason = draft_gate(pr, rec, pol)
                else:
                    status, reason, _ = evaluate(pr, cfg, pol, rec, mine=mine)
                if status == "held" and reason.startswith("checks red"):
                    retry = noise_retry(pol, pr, rec, cfg)
                    if retry:
                        status, reason = "waiting", retry
                        rec.pop("deep", None)
            except Exception as e:  # noqa: BLE001 - one bad PR must not stop the lane or merge anything
                status, reason = "held", f"lane error: {type(e).__name__}: {str(e)[:200]}"
                key = f"error:{pr['headRefOid']}:{type(e).__name__}"
                if rec.get("reported") != key:
                    rec["reported"] = key
                    log(
                        {
                            "pr": pr["number"],
                            "decision": "lane-error",
                            "sha": pr["headRefOid"],
                            "detail": reason,
                        }
                    )
                rec.pop("deep", None)
            if status == "ready" and eng.DRY_RUN:
                if rec.get("status") != "would_merge":
                    log(
                        {
                            "pr": pr["number"],
                            "decision": "would_merge",
                            "sha": pr["headRefOid"],
                            "detail": reason,
                        }
                    )
                rec.update({"status": "would_merge", "reason": reason})
                continue
            if status == "ready":
                try:
                    ok, detail = merge(pr, pol["repo"])
                except GhError as e:
                    ok, detail = False, str(e)[:300]
                if ok:
                    rec.update(
                        {
                            "status": "merged",
                            "reason": reason,
                            "merged_at": NOW_ISO,
                            "merge_commit": detail,
                        }
                    )
                    carried = CARRIED.get((pr["number"], pr["headRefOid"]))
                    log(
                        dict(
                            {
                                "pr": pr["number"],
                                "decision": (
                                    "merged_carried_delta"
                                    if (carried or {}).get("delta_paths")
                                    else ("merged_carried_signoff" if carried else "merged")
                                ),
                                "sha": pr["headRefOid"],
                                "detail": reason,
                                "merge_commit": detail,
                            },
                            **(
                                {"carried_from": carried["from_head"], "signoff": carried["id"]}
                                if carried
                                else {}
                            ),
                            **(
                                {"delta_paths": carried["delta_paths"]}
                                if (carried or {}).get("delta_paths")
                                else {}
                            ),
                        )
                    )
                    if cfg["notify_on_merge"]:
                        out.append(
                            f"{TAG} PR #{n} {pr.get('title')}: merged ({reason}) - {pr.get('url')}"
                        )
                else:
                    key = f"merge-failed:{pr['headRefOid']}"
                    rec.update({"status": "held", "reason": f"merge failed: {detail}"})
                    if rec.get("reported") != key:
                        rec["reported"] = key
                        log(
                            {
                                "pr": pr["number"],
                                "decision": "merge-failed",
                                "sha": pr["headRefOid"],
                                "detail": detail,
                            }
                        )
                        out.append(
                            f"{TAG} PR #{n} {pr.get('title')}: ready but the merge failed ({detail[:200]}) - {pr.get('url')}"
                        )
                continue
            if status == "skip":
                prs_state.pop(n, None)
                continue
            if rec.get("status") != status or rec.get("reason") != reason:
                rec.update({"status": status, "reason": reason, "since": NOW_ISO})
                if status == "held":
                    log(
                        {
                            "pr": pr["number"],
                            "decision": "held",
                            "sha": pr["headRefOid"],
                            "detail": reason,
                        }
                    )
            frec = fix_state.setdefault(n, {})
            try:
                line = fixer.consider(
                    TARGET,
                    TAG,
                    pol["repo"],
                    pol["self_login"],
                    pr,
                    status,
                    reason,
                    frec,
                    cfg,
                    eng.CACHE_DIR / "autofix",
                    NOW,
                )
            except Exception as e:  # noqa: BLE001 - auto-fix must never break the merge lane
                line = None
                frec["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            if frec.get("running") and frec["running"].get("started") == NOW_ISO:
                log(
                    {
                        "pr": pr["number"],
                        "decision": "autofix-started",
                        "sha": pr["headRefOid"],
                        "detail": frec["running"]["problem"],
                        "pid": frec["running"]["pid"],
                    }
                )
            if line:
                log(
                    {
                        "pr": pr["number"],
                        "decision": "autofix-gave-up",
                        "sha": pr["headRefOid"],
                        "detail": line,
                    }
                )
                out.append(line)
        for n in list(fix_state):
            if n not in open_nums and not fixer.run_alive(fix_state[n].get("running")):
                del fix_state[n]
        try:
            for sid in fixer.archive_finished(NOW):
                log({"decision": "autofix-archived", "session": sid})
        except Exception:  # noqa: BLE001 - session cleanup must never break the merge lane
            pass
        # Keep merged records 14 days for the Recently shipped tab; drop the rest once closed.
        for n in list(prs_state):
            if n in open_nums:
                continue
            r = prs_state[n]
            if r.get("status") != "merged":
                del prs_state[n]
                continue
            try:
                age = (
                    NOW.timestamp()
                    - dt.datetime.strptime(r["merged_at"], "%Y-%m-%dT%H:%M:%SZ")
                    .replace(tzinfo=dt.timezone.utc)
                    .timestamp()
                )
            except (KeyError, ValueError):
                age = 0
            if age > 14 * 86400:
                del prs_state[n]
        st["error_count"] = 0
        st.pop("last_error", None)
    except Exception as e:  # noqa: BLE001 - any failure is fail-closed (no merge) and counted
        st["error_count"] = int(st.get("error_count", 0)) + 1
        st["last_error"] = f"{type(e).__name__}: {str(e)[:300]}"
        if st["error_count"] in (3, 20):
            out.append(
                f"{TAG} auto-merge lane failing ({st['error_count']} in a row): {st['last_error']}"
            )
    finally:
        save_state(st)
        if out:
            print("\n".join(out))


def check_one(n):
    pol = eng.policy()
    cfg = config(pol)
    allmine = list_mine(pol)
    prs = [p for p in allmine if p["number"] == n]
    if not prs:
        print(json.dumps({"pr": n, "status": "not an open PR of mine"}))
        return
    rec = {}
    status, reason, _ = evaluate(prs[0], cfg, pol, rec, force=True, mine=allmine)
    print(
        json.dumps(
            {"pr": n, "head": prs[0]["headRefOid"], "status": status, "reason": reason}, indent=2
        )
    )


def main():
    args = [
        a
        for i, a in enumerate(sys.argv[1:])
        if a != "--target" and (i == 0 or sys.argv[i] != "--target")
    ]
    cmd = args[0] if args else "tick"
    if cmd == "tick":
        tick()
    elif cmd == "status":
        print(json.dumps(load_state(), indent=2))
    elif cmd == "check" and len(args) == 2:
        check_one(int(args[1]))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
