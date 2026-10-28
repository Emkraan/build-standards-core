#!/usr/bin/env python3
# =====================================================================
# pr_review.py
#
# Purpose: Review engine for the primary-repo PR review cron (engineer PRs on
#          the repository named by the policy "repo" key). Subcommands:
#            gate                 wake gate (default; see contract below)
#            check <pr>           deterministic policy check + terraform-ci
#                                 plan summary + check/thread state (JSON)
#            record <pr> <file>   upsert the queue item for <pr> from a JSON
#                                 file (status, findings, escalation breakdown)
#            approve <pr> --sha S --body-file F [--no-merge]
#                                 the ONLY approve path for the agent: re-runs
#                                 check, refuses on any escalation rule, red or
#                                 pending checks, unresolved threads or a moved
#                                 head, then approves as me and enqueues a
#                                 rebase merge (merge queue, never --admin)
#            status               print the queue summary
#            window               print the held-for-window list
#          Policy lives in <state dir>/review/policy.json (one
#          file, read on every call). The tfplan gate's matcher is reused.
# Date:    2026-10-06
#
# Wake-gate contract: always exit 0; last stdout line {"wakeAgent": false}
# skips the agent, anything else wakes it with stdout in its prompt.
# Fails closed: on any gh error nothing is acted on; a health counter wakes
# after 3 consecutive failures, then 1h, then every 4h. One forced daily
# self-audit wake (first run after midnight local).
#
# Test hooks (env):
#   OPRG_STATE_DIR  queue/decisions dir (default <state dir>/review)
#   OPRG_CACHE_DIR  fingerprint/health/lock dir (default <agent home>/cache/primary-pr-review)
#   OPRG_POLICY     policy.json path (default <STATE_DIR>/policy.json, falling
#                   back to the real policy when a scratch STATE_DIR has none)
#   OPRG_GH_BIN     gh binary (default gh on PATH)
#   OPRG_DRY_RUN=1  approve never calls gh write endpoints; logs would_approve
#   OPRG_NO_AUDIT=1 suppress the daily self-audit wake (dry runs)
#   OPRG_NOW        ISO UTC time used for maintenance-window math (tests)
#
# Maintenance window: an engineer PR that would take a production
# system down on merge (maintenance_window.py) is approved but not enqueued
# outside the window of its change class. It is recorded in
# <STATE_DIR>/held-for-window.json and the gate enqueues it inside the window
# once its approved head is still the head and every gate still passes. A new
# push drops the hold. the owner's own PRs never reach this path.
# =====================================================================
import base64
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from gh_run_jobs import run_jobs

sys.path.insert(0, str(Path(__file__).resolve().parent))
import merge_queue as mqueue  # noqa: E402
import paths

HOME = Path.home()
REAL_STATE = paths.state_dir() / "review"
STATE_DIR = Path(os.environ.get("OPRG_STATE_DIR", str(REAL_STATE)))
CACHE_DIR = Path(
    os.environ.get("OPRG_CACHE_DIR", str(paths.agent_home() / "cache" / "primary-pr-review"))
)
_pol = STATE_DIR / "policy.json"
POLICY_PATH = Path(
    os.environ.get("OPRG_POLICY", str(_pol if _pol.exists() else REAL_STATE / "policy.json"))
)
GH = os.environ.get("OPRG_GH_BIN", "gh")
LANE = os.environ.get(
    "OPSCENTER_LANE_LABEL", "primary"
)  # the label in the gate lines and card tags
BRANCH_PREFIX = os.environ.get(
    "OPSCENTER_BRANCH_PREFIX", "ticket-"
)  # engineer branches (drift rule)
DRY_RUN = os.environ.get("OPRG_DRY_RUN") == "1"
NO_AUDIT = os.environ.get("OPRG_NO_AUDIT") == "1"
QUEUE = STATE_DIR / "queue.json"
DECISIONS = STATE_DIR / "decisions.jsonl"
FP_FILE = CACHE_DIR / "fingerprint.json"
HEALTH = CACHE_DIR / "health.json"
LOCK = CACHE_DIR / "queue.lock"  # shared with the Ops Center server
TFGATE_PY = Path(__file__).resolve().parent / "tfplan_gate.py"
HELD = STATE_DIR / "held-for-window.json"
SPECS_CACHE = CACHE_DIR / "deploy-specs.json"
SPECS_TTL_S = 600
WINDOW_RECHECK_S = 600
SHIPPED_KEEP_DAYS = 30

NOW = time.time()
NOW_ISO = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
TODAY = dt.date.today().isoformat()
SILENT = '{"wakeAgent": false}'
STATUSES = (
    "in_progress",
    "escalated",
    "approved",
    "merged",
    "closed",
    "changes_requested",
    "held_for_window",
)
FORBIDDEN_WORDS = re.compile(
    "|".join(
        filter(
            None,
            [
                r"\bbot\b|\bAI\b|assistant|co-authored-by",
                os.environ.get("OPSCENTER_FORBIDDEN_WORDS", ""),
            ],
        )
    ),
    re.I,
)


def _load_mw():
    spec = importlib.util.spec_from_file_location(
        "maintenance_window", str(Path(__file__).resolve().parent / "maintenance_window.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mw = _load_mw()


def now_utc():
    v = os.environ.get("OPRG_NOW")
    if v:
        return dt.datetime.strptime(v[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


class GhError(Exception):
    pass


def gh(args, timeout=60, raw=False):
    try:
        p = subprocess.run([GH] + args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GhError(f"{' '.join(args[:3])}: {e}")  # noqa: B904
    if p.returncode != 0:
        raise GhError(f"{' '.join(args[:3])}: rc={p.returncode} {p.stderr.strip()[:400]}")
    if raw:
        return p.stdout
    try:
        return json.loads(p.stdout) if p.stdout.strip() else None
    except ValueError as e:
        raise GhError(f"{' '.join(args[:3])}: bad json {e}")  # noqa: B904


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


def write_json(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, p)


def log_decision(rec):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS, "a") as f:
        f.write(json.dumps(dict({"ts": NOW_ISO}, **rec)) + "\n")


def policy():
    pol = json.loads(POLICY_PATH.read_text())
    pol["_sha"] = hashlib.sha1(POLICY_PATH.read_bytes()).hexdigest()[:12]
    return pol


def repo_parts(pol):
    owner, name = pol["repo"].split("/", 1)
    return owner, name


def is_skipped_author(login, typename, pol):
    if not login:
        return True
    if login == pol["self_login"] or typename == "Bot":
        return True
    return bool(re.search(pol.get("skip_authors_regex", r"\[bot\]$"), login, re.I))


# ---------------------------------------------------------------------
# Live PR state (one GraphQL call)
# ---------------------------------------------------------------------
PR_FIELDS = """
number title url isDraft headRefOid mergeable mergeStateStatus reviewDecision
author{login __typename}
comments(last:50){nodes{author{login}}}
reviews(last:50){nodes{author{login} state commit{oid}}}
reviewThreads(first:50){nodes{isResolved resolvedBy{login} comments(first:20){nodes{author{login}}}}}
commits(last:1){nodes{commit{statusCheckRollup{state contexts(first:100){nodes{__typename
  ... on CheckRun{name conclusion status startedAt checkSuite{workflowRun{workflow{name}}}}
  ... on StatusContext{context state createdAt}}}}}}}
"""
OPEN_QUERY = (
    "query($owner:String!,$name:String!){repository(owner:$owner,name:$name){pullRequests(states:OPEN,first:50){nodes{"
    + PR_FIELDS
    + "}}}}"
)
ONE_QUERY = (
    "query($owner:String!,$name:String!,$n:Int!){repository(owner:$owner,name:$name){pullRequest(number:$n){state mergedAt "
    + PR_FIELDS
    + "}}}"
)


def checks_of(node):
    """Newest result per (workflow, check name) -> {key: conclusion|status}."""
    rollup = (((node.get("commits") or {}).get("nodes") or [{}])[0].get("commit") or {}).get(
        "statusCheckRollup"
    ) or {}
    best = {}
    for c in (rollup.get("contexts") or {}).get("nodes") or []:
        if c.get("__typename") == "CheckRun":
            wf = (((c.get("checkSuite") or {}).get("workflowRun") or {}).get("workflow") or {}).get(
                "name"
            ) or ""
            key = f"{wf}/{c.get('name')}" if wf else c.get("name")
            val = (c.get("conclusion") or c.get("status") or "PENDING").upper()
            ts = c.get("startedAt") or ""
        else:
            key = c.get("context")
            val = (c.get("state") or "PENDING").upper()
            ts = c.get("createdAt") or ""
        if key not in best or ts >= best[key][0]:
            best[key] = (ts, val)
    return {k: v for k, (_, v) in sorted(best.items())}


def summarize_checks(checks):
    ok = {"SUCCESS", "NEUTRAL", "SKIPPED"}
    red = sorted(
        k
        for k, v in checks.items()
        if v
        in (
            "FAILURE",
            "TIMED_OUT",
            "ACTION_REQUIRED",
            "STARTUP_FAILURE",
            "ERROR",
            "CANCELLED_REQUIRED",
        )
    )
    pending = sorted(
        k
        for k, v in checks.items()
        if v in ("PENDING", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED", "EXPECTED")
    )
    tf = None
    for k, v in checks.items():
        if k.endswith("terraform-ci result"):
            tf = v
    # Cancelled runs are superseded re-runs once a newer one exists (dedupe
    # above keeps the newest), so a remaining CANCELLED is treated as red.
    red += sorted(k for k, v in checks.items() if v == "CANCELLED")
    green = not red and not pending and all(v in ok for v in checks.values())
    return {
        "green": green,
        "red": red,
        "pending": pending,
        "terraform_ci": tf,
        "count": len(checks),
    }


def fp_of(node, pol):
    me = pol["self_login"]
    others = lambda nodes: [n for n in nodes if ((n.get("author") or {}).get("login") or "") != me]  # noqa: E731
    threads = node["reviewThreads"]["nodes"]
    checks = checks_of(node)
    return {
        "number": node["number"],
        "head": node["headRefOid"],
        "author": (node.get("author") or {}).get("login"),
        "draft": node.get("isDraft"),
        "mergeable": node.get("mergeable"),
        "comments": len(others(node["comments"]["nodes"])),
        "reviews": len(others(node["reviews"]["nodes"])),
        "thread_comments": sum(len(others(t["comments"]["nodes"])) for t in threads),
        "resolved_by_others": sum(
            1
            for t in threads
            if t["isResolved"] and ((t.get("resolvedBy") or {}).get("login") or "") != me
        ),
        "checks": checks,
        "terraform_ci": summarize_checks(checks)["terraform_ci"],
    }


def engineer_nodes(nodes, pol):
    out = []
    for n in nodes:
        a = n.get("author") or {}
        if is_skipped_author(a.get("login"), a.get("__typename"), pol):
            continue
        if pol.get("skip_drafts", True) and n.get("isDraft"):
            continue
        out.append(n)
    return out


# ---------------------------------------------------------------------
# Deterministic policy check
# ---------------------------------------------------------------------
def _tfgate():
    spec = importlib.util.spec_from_file_location("tfplan_gate", str(TFGATE_PY))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.GH = GH  # same gh binary (test hooks)
    return mod


def parse_diff(text):
    """{path: [(new_line_no, text)]} for added lines."""
    added, cur, ln = {}, None, 0
    for line in text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*) b/(.*)$", line)
            cur = m.group(2) if m else None
            if cur is not None:
                added.setdefault(cur, [])
            continue
        if cur is None:
            continue
        if line.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", line)
            ln = int(m.group(1)) if m else 0
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added[cur].append((ln, line[1:]))
            ln += 1
        elif line.startswith("-"):
            continue
        else:
            ln += 1
    return added


def _app_grant_ok(path, scope, body, rule):
    """the owner 2026-10-16: a function app root's own grants (functions/<app>/infra/) are routine
    when BOTH the scope and the role match one listed pair in rule['path_exceptions']. Any other
    role or scope in that root still escalates, and a privileged role is caught by line_rules."""
    for ex in rule.get("path_exceptions", []):
        if not re.search(ex["path_regex"], path):
            continue
        for pair in ex["pairs"]:
            if re.search(pair["scope_regex"], scope) and re.search(pair["role_regex"], body):
                return True
    return False


def role_assignment_hits(path, lines, rule):
    """Find added role assignment blocks whose scope is not app-owned."""
    hits = []
    allow = re.compile(rule["allowed_scope_regex"], re.I)
    i = 0
    while i < len(lines):
        no, txt = lines[i]
        if re.search(r'resource\s+"(azurerm_role_assignment|azapi_resource)"', txt):
            block, depth, j = [], 0, i
            while j < len(lines):
                t = lines[j][1]
                block.append(t)
                depth += t.count("{") - t.count("}")
                j += 1
                if depth <= 0 and len(block) > 1:
                    break
            body = "\n".join(block)
            is_ra = "azurerm_role_assignment" in block[0] or "roleAssignments" in body
            if is_ra:
                m = re.search(r"^\s*(scope|parent_id)\s*=\s*(.+)$", body, re.M)
                scope = m.group(2).strip() if m else "(no scope found)"
                if not allow.search(scope) and not _app_grant_ok(path, scope, body, rule):
                    hits.append(
                        {
                            "rule": rule["id"],
                            "reason": rule["reason"],
                            "where": f"{path}:{no}",
                            "detail": scope[:160],
                        }
                    )
            i = j
            continue
        i += 1
    return hits


def _added_block(lines, idx):
    """Added lines from idx to the end of the block that line opens (or sits in)."""
    out, depth = [], 0
    for _no, t in lines[idx:]:
        out.append(t)
        depth += t.count("{") - t.count("}")
        if depth < 0 or (depth == 0 and len(out) > 1 and "}" in t):
            break
    return "\n".join(out)


def _line_exempt(rule, path, txt, lines, idx):
    """the owner 2026-10-20: a line rule may list path_exceptions for shapes every app of one kind
    has by design (a Flex function app's own FC1 plan and its system-assigned identity under
    functions/<app>/infra/). An exception needs the path to match AND, when given, the line
    (line_regex) and the enclosing added block (block_regex). Anything else still escalates."""
    for ex in rule.get("path_exceptions") or []:
        if not re.search(ex["path_regex"], path):
            continue
        if ex.get("line_regex") and not re.search(ex["line_regex"], txt):
            continue
        if ex.get("block_regex") and not re.search(ex["block_regex"], _added_block(lines, idx)):
            continue
        return True
    return False


def policy_hits(pol, files, diff_text, own=False):
    """own: this is one of the owner's PRs. Only then can the github-dir rule release a plain script, prompt, test
    or workflow-step edit. Engineer PRs keep every .github/ hold."""
    hits = []
    gh_full, gh_mod = None, None
    for path in files:
        for r in pol.get("path_rules", []):
            if re.search(r["pattern"], path, re.I):
                if own and r["id"] == "github-dir":
                    if gh_mod is None:
                        gh_mod = _tfgate()
                        gh_full = gh_mod.parse_diff_full(diff_text or "")
                    if gh_mod.github_release(path, gh_full, "policy")[0]:
                        continue
                hits.append({"rule": r["id"], "reason": r["reason"], "where": path})
    added = parse_diff(diff_text)
    suffixes = tuple(pol.get("scan_suffixes", [".tf", ".tf.json", ".hcl"]))
    for path, lines in added.items():
        if not path.endswith(suffixes):
            continue
        block = (
            ""  # resource type of the enclosing added block, so an update is not read as a create
        )
        for idx, (no, txt) in enumerate(lines):
            m = re.match(r'\s*resource\s+"([a-z0-9_]+)"', txt)
            if m:
                block = m.group(1)
            for r in pol.get("line_rules", []):
                if re.search(r["pattern"], txt, re.I):
                    if _line_exempt(r, path, txt, lines, idx):
                        continue
                    # azapi_update_resource changes an existing resource. Its type line names the ARM
                    # type (e.g. Microsoft.DBforPostgreSQL/flexibleServers@) but creates nothing.
                    if (
                        block == "azapi_update_resource"
                        and re.match(r"\s*type\s*=", txt)
                        and r["id"].startswith("new-")
                    ):
                        continue
                    hits.append(
                        {
                            "rule": r["id"],
                            "reason": r["reason"],
                            "where": f"{path}:{no}",
                            "detail": txt.strip()[:160],
                        }
                    )
        ras = pol.get("role_assignment_scope")
        if ras:
            hits += role_assignment_hits(path, lines, ras)
    return hits


def _runbook_shaped(path, roots, exts):
    parts = (path or "").split("/")
    return len(parts) == 3 and parts[0] in roots and parts[2].lower().endswith(exts)


def new_file_hits(tr, owner_repo, files, renamed=None):
    """File-level new-thing check: a runbook is a FILE,
    runbooks/<automation account>/<name>.ps1, so a new runbook is a source file directly inside
    an account folder that main does not have (a new account folder makes every file in it new).
    One contents listing per folder on main. 404 = new folder. Any other error escalates as
    trust-check-failed, so an outage never turns into an approval. Files deeper down (tests/)
    and files without a listed extension (manifest.json, README.md) are not runbooks.
    A rename is not new: `renamed` maps a PR file the files API reports as
    status 'renamed' to its previous_filename, and a candidate whose previous path was itself a
    runbook source file under a new_file_roots folder is skipped without a listing. Anything
    else (added, a rename from outside the runbook folders or from tests/) still takes the main
    listing check."""
    hits = []
    roots = tr.get("new_file_roots") or []
    exts = tuple(x.lower() for x in (tr.get("new_file_extensions") or [".ps1", ".py"]))
    renamed = renamed or {}
    cand = {}
    for f in files:
        if _runbook_shaped(f, roots, exts):
            # The previous name itself stays in `files` and takes the listing (it is on main).
            if _runbook_shaped(renamed.get(f), roots, exts):
                continue
            parts = f.split("/")
            cand.setdefault((parts[0], parts[1]), set()).add(parts[2])
    for (root, folder), names in sorted(cand.items()):
        try:
            out = gh(
                [
                    "api",
                    f"repos/{owner_repo}/contents/{root}/{folder}?ref=main",
                    "--jq",
                    '.[] | select(.type=="file") | .name',
                ],
                raw=True,
            )
            existing = set(x.strip() for x in out.splitlines() if x.strip())
        except GhError as e:
            if re.search(r"404|Not Found", str(e)):
                existing = set()
            else:
                hits.append(
                    {
                        "rule": "trust-check-failed",
                        "reason": f"could not list {root}/{folder}/ on main to spot a new runbook",
                        "where": f"{root}/{folder}/",
                    }
                )
                continue
        for n in sorted(names - existing):
            hits.append(
                {
                    "rule": "new-runbook-first-pr",
                    "reason": "creates a new runbook, its first PR goes to owner",
                    "where": f"{root}/{folder}/{n}",
                }
            )
    return hits


def trust_hits(pol, owner_repo, author, files, renamed=None):
    """Escalations that come from who and what, not from the diff content:
    the PR that creates a new app (a new folder under a deployable root that main does not have
    yet, e.g. the UC portal migration), and each engineer's first N merged PRs. A lookup that
    fails escalates, so an outage never turns into an approval."""
    tr = pol.get("trust_rules") or {}
    hits = []
    # Engineer PRs only. The owner's own PRs go through the own-PR lane, which reads this same check.
    if author and author.lower() == str(pol.get("self_login") or "").lower():
        return hits
    # Device-shipping apps (for example an endpoint agent): anyone may build them, but an engineer's
    # merge to main always comes to the owner.
    for prefix in tr.get("approval_paths") or []:
        touched = sorted(f for f in files if f.startswith(prefix))
        if touched:
            hits.append(
                {
                    "rule": "approval-path",
                    "reason": f"changes {prefix}, engineer merges there go to owner",
                    "where": touched[0],
                }
            )
    roots = tr.get("new_app_roots") or []
    new_dirs = {}
    for f in files:
        parts = f.split("/")
        if len(parts) >= 3 and parts[0] in roots:
            new_dirs.setdefault(parts[0], set()).add(parts[1])
    for root, dirs in sorted(new_dirs.items()):
        try:
            out = gh(
                [
                    "api",
                    f"repos/{owner_repo}/contents/{root}?ref=main",
                    "--jq",
                    '.[] | select(.type=="dir") | .name',
                ],
                raw=True,
            )
            existing = set(x.strip() for x in out.splitlines() if x.strip())
        except GhError as e:
            if re.search(r"404|Not Found", str(e)):
                existing = set()
            else:
                hits.append(
                    {
                        "rule": "trust-check-failed",
                        "reason": f"could not list {root}/ on main to spot a new app",
                        "where": root,
                    }
                )
                continue
        for d in sorted(dirs - existing):
            hits.append(
                {
                    "rule": "new-app-first-pr",
                    "reason": "creates a new app, its first PR goes to owner",
                    "where": f"{root}/{d}/",
                }
            )
    hits += new_file_hits(tr, owner_repo, files, renamed)
    n_first = int(tr.get("first_prs_to_review") or 0)
    if n_first > 0 and author:
        try:
            out = gh(
                [
                    "api",
                    "-X",
                    "GET",
                    "search/issues",
                    "-f",
                    f"q=repo:{owner_repo} is:pr is:merged author:{author}",
                    "--jq",
                    ".total_count",
                ],
                raw=True,
            )
            merged = int(out.strip() or "0")
        except (GhError, ValueError):
            hits.append(
                {
                    "rule": "trust-check-failed",
                    "reason": f"could not count merged PRs for {author}",
                    "where": author,
                }
            )
        else:
            if merged < n_first:
                hits.append(
                    {
                        "rule": "new-contributor",
                        "reason": f"{author} has {merged} merged PR(s), the first {n_first} go to owner",
                        "where": author,
                    }
                )
    return hits


def _file_at(owner_repo, path, ref):
    """Raw file text at a ref. None on 404 (file absent), GhError on anything else."""
    try:
        return gh(
            [
                "api",
                f"repos/{owner_repo}/contents/{path}?ref={ref}",
                "-H",
                "Accept: application/vnd.github.raw",
            ],
            raw=True,
        )
    except GhError as e:
        if re.search(r"404|Not Found", str(e)):
            return None
        raise


def _infra_tiers(text):
    d = json.loads(text)
    infra = d.get("infra") or {}
    return d.get("kind"), set(infra) if isinstance(infra, dict) else set()


def prod_wiring_hits(pol, owner_repo, author, files, head_sha):
    """the owner 2026-10-20: a new app's dev-only PRs pass the trust rules, so the PR that first
    wires the prod tier into an existing app's deploy.json (infra.<prod_tier> added) is the one
    that comes to the owner. A read failure escalates as trust-check-failed."""
    tr = pol.get("trust_rules") or {}
    ho = tr.get("dev_tier_only") or {}
    if not ho.get("enabled") or not head_sha:
        return []
    if author and author.lower() == str(pol.get("self_login") or "").lower():
        return []
    prod = ho.get("prod_tier", "prod")
    roots = tr.get("new_app_roots") or []
    hits = []
    for f in sorted(files):
        parts = f.split("/")
        if not (len(parts) == 3 and parts[0] in roots and parts[2] == "deploy.json"):
            continue
        try:
            base = _file_at(owner_repo, f, "main")
            if base is None:
                continue  # new app: new-app-first-pr covers it
            head = _file_at(owner_repo, f, head_sha)
            if head is None:
                continue  # deleted
            if prod not in _infra_tiers(base)[1] and prod in _infra_tiers(head)[1]:
                hits.append(
                    {
                        "rule": "prod-wiring-first-pr",
                        "reason": f"wires the {prod} (prod) tier into {parts[0]}/{parts[1]} for the first time",
                        "where": f,
                    }
                )
        except (GhError, ValueError) as e:
            hits.append(
                {
                    "rule": "trust-check-failed",
                    "reason": f"could not compare {f} with main: {str(e)[:120]}",
                    "where": f,
                }
            )
    return hits


WAIVABLE_TRUST = ("new-app-first-pr", "new-contributor")
# the owner 2026-10-20: "dev tier only branches do not need to come to me, only if they are affecting
# prod/primary resources". These rules only matter for prod resources, so a provably dev-only PR
# drops them. Rules with tenant-wide or cross-tier reach stay: Entra/Graph grants, federated
# credentials, custom roles, RBAC outside the app, the shared Postgres server, policy, plan
# destroy/replace/error, tfplan-matcher (plan-time execution), approval paths, ai-review blocks.
WAIVABLE_dev_tier = WAIVABLE_TRUST + (
    "new-identity",
    "new-system-identity",
    "new-storage-account",
    "new-app-service-plan",
    "new-key-vault",
    "new-front-door",
    "new-apim",
    "rbac-user-or-group",
    "rbac-user-or-group-lookup",
    "rbac-privileged-role",
    "check-waiver",
    "lifecycle-weakened",
)


def include_conflict(owner_repo, refs, roots, apps, files):
    """the owner 2026-10-20: a dev-only folder must not reach prod through another app's
    deploy.include (function apps copy those repo paths into their package). Returns a reason
    when any other app's deploy.json, on main or at the head, includes a path that equals, sits
    under or contains a changed file or one of the touched app folders. Any read or parse
    error is a reason too (fail closed). None when clean."""
    changed = [f for f in files if not f.endswith(".md")]
    for ref in refs:
        for root in roots:
            try:
                listing = gh(["api", f"repos/{owner_repo}/contents/{root}?ref={ref}"])
            except GhError as e:
                if re.search(r"404|Not Found", str(e)):
                    continue
                return f"could not list {root}/ at {ref[:12]} for deploy.include: {str(e)[:120]}"
            if not isinstance(listing, list):
                return f"could not list {root}/ at {ref[:12]} for deploy.include"
            for ent in listing:
                if (ent or {}).get("type") != "dir":
                    continue
                folder = f"{root}/{ent.get('name')}/"
                if folder in apps:
                    continue
                try:
                    text = _file_at(owner_repo, folder + "deploy.json", ref)
                    d = json.loads(text) if text is not None else {}
                except (GhError, ValueError) as e:
                    return f"could not read {folder}deploy.json at {ref[:12]}: {str(e)[:120]}"
                dep = d.get("deploy") if isinstance(d, dict) else None
                incs = []
                for src in (d if isinstance(d, dict) else {}, dep if isinstance(dep, dict) else {}):
                    v = src.get("include")
                    if isinstance(v, list):
                        incs += [str(x).strip("/") for x in v if x]
                    elif v:
                        return f"{folder}deploy.json at {ref[:12]} has a deploy.include that is not a list"
                for inc in incs:
                    hit = [f for f in changed if f == inc or f.startswith(inc + "/")]
                    hit += [a for a in apps if inc.startswith(a) or a.startswith(inc + "/")]
                    if hit:
                        return f"{hit[0]} is shipped by {folder.rstrip('/')} via deploy.include"
    return None


def dev_tier_only_waiver(pol, owner_repo, head_sha, files, hits, plan):
    """the owner 2026-10-20: a PR that cannot reach prod does not come to the owner. The rules in
    WAIVABLE_dev_tier are waived when ALL of these hold, otherwise nothing changes (fail closed):
    every non-Markdown file sits in an app folder (<new_app_root>/<app>/), no file is on an
    approval path, each touched app's deploy.json at the head is a dev-gated kind with no prod
    tier and, when main has it, main declares no prod tier either (removing prod is a prod change),
    and terraform-ci finished green with every prod-tier root parsed as No changes and no prod
    resource in the plan. While the plan is still running the waivable hits are dropped with
    pending: true (approve() refuses on pending). Returns (hits, waiver info or None)."""
    tr = pol.get("trust_rules") or {}
    ho = tr.get("dev_tier_only") or {}
    if not ho.get("enabled") or not any(h["rule"] in WAIVABLE_dev_tier for h in hits):
        return hits, None
    prod = ho.get("prod_tier", "prod")
    kinds = set(ho.get("kinds") or ["function-app", "app-service", "container-app"])
    roots = set(tr.get("new_app_roots") or [])
    approval = [p for p in (tr.get("approval_paths") or []) if p]
    apps, why = set(), None
    for f in files:
        if any(f.startswith(p) for p in approval):
            why = f"{f} is on an approval path"
            break
        if f.endswith(".md"):
            continue
        parts = f.split("/")
        if len(parts) < 3 or parts[0] not in roots:
            why = "files outside an app folder"
            break
        apps.add(parts[0] + "/" + parts[1] + "/")
    if why is None and not apps:
        why = "no app folder"
    if why is None:
        for a in sorted(apps):
            try:
                text = _file_at(owner_repo, a + "deploy.json", head_sha)
                kind, tiers = _infra_tiers(text) if text is not None else (None, {prod})
                base = _file_at(owner_repo, a + "deploy.json", "main")
                base_tiers = _infra_tiers(base)[1] if base is not None else set()
            except (GhError, ValueError):
                kind, tiers, base_tiers = None, {prod}, {prod}
            if kind not in kinds:
                why = f"{a} kind {kind} is not dev-prefix-gated"
                break
            if prod in tiers:
                why = f"{a} declares the {prod} tier"
                break
            if prod in base_tiers:
                why = f"{a} declares the {prod} tier on main"
                break
    if why is None:
        why = include_conflict(owner_repo, ("main", head_sha), sorted(roots), apps, files)
    if why is None:
        prod_roots = [r for r in plan.get("roots") or [] if r.get("tier") == prod]
        has_infra = any(f.startswith(a + "infra/") for a in apps for f in files)
        # the owner 2026-10-20: a plan still running (or not started on a PR with infra) waits
        # instead of escalating. approve() refuses while any check is pending, and the gate wakes
        # on the terraform-ci result, which re-runs this with the final plan.
        if (plan.get("ran") and plan.get("status") != "completed") or (
            not plan.get("ran") and has_infra
        ):
            kept = [h for h in hits if h["rule"] not in WAIVABLE_dev_tier]
            return kept, {
                "waived": False,
                "pending": True,
                "why": "terraform-ci still running, waiting for the plan",
            }
        if not (
            plan.get("ran")
            and plan.get("status") == "completed"
            and plan.get("conclusion") == "success"
        ):
            why = "terraform-ci not finished green"
        elif plan.get("errors"):
            why = "plan errors"
        elif any(r.get("tier") == prod for r in plan.get("resources") or []):
            why = f"plan changes {prod} resources"
        elif any(not r.get("parsed") or r.get("summary") != "No changes" for r in prod_roots):
            why = f"a {prod} root does not plan No changes"
    if why is not None:
        return hits, {"waived": False, "why": why}
    kept = [h for h in hits if h["rule"] not in WAIVABLE_dev_tier]
    gone = sorted({h["rule"] for h in hits if h["rule"] in WAIVABLE_dev_tier})
    return kept, {"waived": True, "rules": gone, "apps": sorted(apps)}


def tfplan_matcher_hits(pr_num, own=False, head_sha=None):
    """Reuse the tfplan gate's hold rules verbatim (assess_pr). own releases what the gate releases for
    the owner's own PRs."""
    mod = _tfgate()
    _files, gate_hits = mod.assess_pr_detail(pr_num, head_sha if own else None, own=own)
    out = []
    for h in gate_hits:
        # name the matched file so the card shows where the hold came from.
        e = {"rule": "tfplan-matcher", "reason": h["reason"], "where": h.get("path") or ""}
        # the gate's own fingerprints, so a sign-off on the plan card and on the policy card
        # are the same sign-off.
        for k in ("fp", "cfp", "path"):
            if h.get(k):
                e[k] = h[k]
        out.append(e)
    return out


def _confirm_needed(plan, pr_num):
    """the name the owner type on the PR card when the plan holds destroys or Entra grants, so the
    post-merge privileged apply of the same plan does not ask me again. None when not needed or
    when the sign-off module cannot be read (the privileged card then asks as before)."""
    try:
        return _tfgate().load_signoff().confirm_needed(plan, pr_num)
    except Exception:  # noqa: BLE001 - optional, the privileged card keeps its own confirm
        return None


def annotate_fps(pol, hits, diff):
    """content fingerprints on the hits whose meaning is a pure function of the diff (the path
    rules, the line rules and the role-assignment scope rule). Everything else, trust and prod wiring
    rules, plan rules, review rules, keeps no fingerprint and so never carries."""
    carry = {r["id"] for r in pol.get("path_rules", [])} | {
        r["id"] for r in pol.get("line_rules", [])
    }
    if (pol.get("role_assignment_scope") or {}).get("id"):
        carry.add(pol["role_assignment_scope"]["id"])
    mod = _tfgate()
    so = mod.load_signoff()
    cmap = None
    for h in hits:
        if h.get("rule") not in carry or h.get("fp"):
            continue
        path = so.path_of(h.get("where"))
        if cmap is None:
            try:
                cmap = mod.content_fps(diff) if diff else {}
            except Exception:  # noqa: BLE001 - no fingerprint, no carry
                cmap = {}
        cfp = cmap.get(path)
        if cfp:
            h["path"], h["cfp"], h["fp"] = path, cfp, so.hit_fp(h["rule"], path, cfp)
    return hits


PLAN_LINE = re.compile(
    r"Plan: (\d+) to import, (\d+) to add, (\d+) to change, (\d+) to destroy|Plan: (\d+) to add, (\d+) to change, (\d+) to destroy"
)
DESTROY_GUARD = "Plan destroys resources. Destroys need a reviewed change"
GUARD_EXIT = "Process completed with exit code 1"
TF_CI_RESULT = "terraform-ci/terraform-ci result"


def destroy_guard_only(summary, plan):
    """True when every red check is terraform-ci's destroy guard (plan jobs that failed only
    because the plan deletes something, plus the terraform-ci result rollup), nothing else is
    red and nothing is still running. Such a PR waits on the owner's sign-off, not on a fix."""
    red = summary.get("red") or []
    if not red or summary.get("pending") or not (plan or {}).get("ran"):
        return False
    guard = {"terraform-ci/" + r["job"] for r in plan.get("roots") or [] if r.get("guard_only")}
    if not guard:
        return False
    return all(k in guard or k == TF_CI_RESULT for k in red)


RES_LINE = re.compile(
    r"#\s+(\S+)\s+(will be created|will be destroyed|will be updated in-place|must be replaced|will be read during apply|will be imported)"
)
ROOT_JOB = re.compile(r"^terraform plan \((\S+) (\S+)\)")
RES_ACTION = {
    "will be created": "create",
    "will be destroyed": "destroy",
    "will be updated in-place": "update",
    "must be replaced": "replace",
}
ATTR_LINE = re.compile(r'^\s*([~+-])\s+"?([A-Za-z0-9_.\-]+)"?\s*(=|\{)')
NAME_LINE = re.compile(r'^\s+name\s*=\s*"([^"]+)"')
MAX_RESOURCES = 200


def _open_branch_apps(owner_repo, pr_num, roots):
    """{app: (root, pr, branch)} for app folders whose deploy.json is in the changed files of
    another open <branch prefix>* pull request. GhError propagates (callers fail closed)."""
    out = gh(
        [
            "api",
            "--paginate",
            f"repos/{owner_repo}/pulls?state=open&per_page=100",
            "--jq",
            ".[] | @json",
        ],
        raw=True,
    )
    apps = {}
    for line in (out or "").splitlines():
        if not line.strip():
            continue
        p = json.loads(line)
        n = p.get("number")
        branch = ((p.get("head") or {}).get("ref")) or ""
        if n == pr_num or not branch.startswith(BRANCH_PREFIX):
            continue
        if ((p.get("head") or {}).get("repo") or {}).get("full_name") != owner_repo:
            continue
        files = gh(
            [
                "api",
                "--paginate",
                f"repos/{owner_repo}/pulls/{n}/files?per_page=100",
                "--jq",
                ".[].filename",
            ],
            raw=True,
        )
        for f in (files or "").splitlines():
            parts = f.strip().split("/")
            if len(parts) == 3 and parts[2] == "deploy.json" and parts[0] in roots:
                apps.setdefault(parts[1], (parts[0], n, branch))
    return apps


DRIFT_KEY = re.compile(r'\["([^"]+)"\]$')


def apply_branch_drift(pol, owner_repo, pr_num, head_sha, plan, branch_apps=None, file_at=None):
    """the owner 2026-10-21: "one engineer's work should not hold up another's". dev tier is
    one shared environment and <branch prefix> branches apply to it, so a new app's pieces in a shared root
    (a shared gateway API, app secrets) show as destroys on every PR cut from main. A planned
    change is branch drift only when it is on the dev tier tier (never the prod tier), a pure destroy
    (a replace never is), its for_each key is <app> or starts with <app>-, and <app> has no
    deploy.json at this PR's head while another open <branch prefix>* PR adds <root>/<app>/deploy.json.
    Drift leaves destroyed/resources/counts and is listed in plan['branch_drift']. Any read error
    leaves the plan untouched (fail closed). Computed here from live GitHub data, never from
    the PR's own CI output, which the PR controls."""
    if not plan.get("ran") or not plan.get("destroyed"):
        return plan
    tr = pol.get("trust_rules") or {}
    tier = (tr.get("dev_tier_only") or {}).get("dev_tier", "dev")
    prod = (tr.get("dev_tier_only") or {}).get("prod_tier", "prod")
    if tier == prod:
        return plan
    roots = set(tr.get("new_app_roots") or [])
    by_addr = {}
    for r in plan.get("resources") or []:
        by_addr.setdefault(r.get("address"), []).append(r)
    cands = [
        r
        for r in plan.get("resources") or []
        if r.get("action") == "destroy"
        and r.get("tier") == tier
        and DRIFT_KEY.search(r.get("address") or "")
    ]
    if not cands or not roots:
        return plan
    file_at = file_at or _file_at
    try:
        apps = (
            branch_apps if branch_apps is not None else _open_branch_apps(owner_repo, pr_num, roots)
        )
        drift = []
        absent = {}
        for r in cands:
            # The same address must not also appear on another tier or with another action.
            if any(
                o.get("tier") != tier or o.get("action") != "destroy"
                for o in by_addr.get(r["address"], [])
            ):
                continue
            key = DRIFT_KEY.search(r["address"]).group(1)
            match = sorted(
                (a for a in apps if key == a or key.startswith(a + "-")), key=len, reverse=True
            )
            if not match:
                continue
            app = match[0]
            root_dir, n, branch = apps[app]
            if app not in absent:
                absent[app] = file_at(owner_repo, f"{root_dir}/{app}/deploy.json", head_sha) is None
            if absent[app]:
                drift.append(
                    {
                        "address": r["address"],
                        "root": r.get("root"),
                        "app": app,
                        "pr": n,
                        "branch": branch,
                    }
                )
    except (GhError, ValueError, KeyError, AttributeError) as e:
        plan = dict(plan)
        plan["branch_drift_error"] = str(e)[:200]
        return plan
    if not drift:
        return plan
    plan = dict(plan)
    gone = {d["address"] for d in drift}
    destroyed = list(plan.get("destroyed") or [])
    for a in gone:
        if a in destroyed:
            destroyed.remove(a)
    plan["destroyed"] = destroyed
    plan["destroy"] = max(0, int(plan.get("destroy") or 0) - len(gone))
    plan["resources"] = [
        r
        for r in plan.get("resources") or []
        if not (r.get("address") in gone and r.get("tier") == tier)
    ]
    roots_out = []
    for rt in plan.get("roots") or []:
        n_drift = sum(1 for d in drift if d["root"] == rt.get("root") and rt.get("tier") == tier)
        if n_drift:
            rt = dict(
                rt, destroy=max(0, int(rt.get("destroy") or 0) - n_drift), branch_drift=n_drift
            )
        roots_out.append(rt)
    plan["roots"] = roots_out
    plan["branch_drift"] = drift
    return plan


BASELINE_ACTIONS = ("update", "create")
BASELINE_MAX_AGE_H = 36
DRIFT_JOB = re.compile(r"^drift \((\S+) (\S+)\)$")


def _clean_log_line(line):
    return re.sub(r"\x1b\[[0-9;]*m", "", re.sub(r"^\S+Z ", "", line))


def resource_diffs(log):
    """{address: (action, sha256 of its whole diff block)} for one terraform plan log. The same
    parser reads the PR plan job and the main drift job, so equal digests mean the same change,
    values included, not just the same attribute names."""
    out = {}
    cur, buf = None, []

    def flush():
        if cur:
            out[cur[0]] = (cur[1], hashlib.sha256("\n".join(buf).encode()).hexdigest())

    for line in (log or "").splitlines():
        body = _clean_log_line(line)
        r = RES_LINE.search(body)
        if r:
            flush()
            act = RES_ACTION.get(r.group(2))
            cur, buf = ((r.group(1), act) if act else None), []
            continue
        if PLAN_LINE.search(body) or body.startswith("No changes."):
            flush()
            cur, buf = None, []
            continue
        if cur and body.strip():
            buf.append(" ".join(body.split()))
    flush()
    return out


def _summary_counts(summary):
    m = PLAN_LINE.search(summary or "")
    if not m:
        return None
    g = [int(x) for x in m.groups() if x is not None]
    return g[-3:]


def _main_drift_run(owner_repo):
    runs = (
        gh(
            [
                "api",
                f"repos/{owner_repo}/actions/workflows/terraform-drift.yml/runs?branch=main&status=completed&per_page=5",
            ]
        )
        or {}
    )
    for r in runs.get("workflow_runs") or []:
        if r.get("head_branch") == "main" and r.get("event") in ("schedule", "workflow_dispatch"):
            return r
    return None


def main_baseline_diffs(owner_repo, roots_needed):
    """{(root, tier): diffs} from the latest completed nightly drift run on main, only for the roots
    asked for. Raises on read errors (callers fail closed). Empty when the run is too old."""
    run = _main_drift_run(owner_repo)
    if not run:
        raise ValueError("no completed terraform-drift run on main")
    made = dt.datetime.strptime(run["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=dt.timezone.utc
    )
    age_h = (dt.datetime.now(dt.timezone.utc) - made).total_seconds() / 3600
    if age_h > BASELINE_MAX_AGE_H:
        raise ValueError(f"main drift run {run['id']} is {int(age_h)}h old")
    jobs = {"jobs": run_jobs(gh, owner_repo, run["id"])}
    out = {}
    for j in jobs.get("jobs") or []:
        m = DRIFT_JOB.match(j.get("name") or "")
        if not m or (m.group(1), m.group(2)) not in roots_needed:
            continue
        cache = CACHE_DIR / f"main-baseline-{run['id']}-{j['id']}.json"
        if cache.exists():
            out[(m.group(1), m.group(2))] = {
                k: tuple(v) for k, v in json.loads(cache.read_text()).items()
            }
            continue
        log = gh(
            ["api", f"repos/{owner_repo}/actions/jobs/{j['id']}/logs", "--allow-escape-sequences"],
            raw=True,
            timeout=90,
        )
        d = resource_diffs(log)
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(d))
        except OSError:
            pass
        out[(m.group(1), m.group(2))] = d
    return out, run


def apply_main_baseline(pol, owner_repo, plan, files, baseline=None, pr_log=None):
    """the owner 2026-10-21: "one engineer's work should not hold up another's", primary
    included. Every PR plans every root, so a change that main itself would make (live drift, or a
    merged change not applied yet) shows on every open PR and breaks the dev-only waiver for
    unrelated work. A PR's planned change is main baseline drift only when it is a create or an
    in-place update (never a destroy or replace), the nightly terraform-drift run on main (36h max)
    plans the same address with the same action and an identical diff block, and the PR touches no
    file of that root or of the shared Terraform modules. A root whose every change matched (and the
    count matches its Plan line) reads No changes. Any read error leaves the plan untouched and is
    recorded in plan['main_baseline_error'] (fail closed). Computed from live GitHub logs, never from
    anything the PR prints about itself."""
    if not plan.get("ran"):
        return plan

    def touches(root):
        return any(
            f.startswith("infrastructure/terraform/modules/") or f"/{root}/" in "/" + f
            for f in files or []
        )

    cands = [
        r
        for r in plan.get("roots") or []
        if r.get("parsed")
        and r.get("summary") not in ("", "No changes")
        and r.get("root")
        and not touches(r["root"])
    ]
    if not cands:
        return plan
    plan = dict(plan)
    try:
        if baseline is None:
            baseline, run = main_baseline_diffs(owner_repo, {(r["root"], r["tier"]) for r in cands})
            plan["main_baseline_run"] = run.get("html_url")
        matched_all = []
        roots_out = []
        for rt in plan.get("roots") or []:
            if rt not in cands or (rt["root"], rt["tier"]) not in baseline:
                roots_out.append(rt)
                continue
            log = (
                pr_log(rt)
                if pr_log
                else gh(
                    [
                        "api",
                        f"repos/{owner_repo}/actions/jobs/{rt['job_id']}/logs",
                        "--allow-escape-sequences",
                    ],
                    raw=True,
                    timeout=90,
                )
            )
            pr = resource_diffs(log)
            base = baseline[(rt["root"], rt["tier"])]
            hit = sorted(
                a
                for a, (act, dg) in pr.items()
                if act in BASELINE_ACTIONS and base.get(a) == (act, dg)
            )
            if not hit:
                roots_out.append(rt)
                continue
            rt = dict(rt, baseline_drift=hit)
            counts = _summary_counts(rt.get("summary"))
            if counts and len(hit) == len(pr) == sum(counts) and not rt.get("destroy"):
                rt["summary_raw"], rt["summary"] = rt["summary"], "No changes"
            for a in hit:
                act = pr[a][0]
                plan["add" if act == "create" else "change"] = max(
                    0, int(plan.get("add" if act == "create" else "change") or 0) - 1
                )
                matched_all.append(
                    {"root": rt["root"], "tier": rt["tier"], "address": a, "action": act}
                )
            roots_out.append(rt)
    except (GhError, ValueError, KeyError, TypeError, OSError) as e:
        plan["main_baseline_error"] = str(e)[:200]
        return plan
    if not matched_all:
        return plan
    keys = {(m["root"], m["tier"], m["address"]) for m in matched_all}
    plan["resources"] = [
        r
        for r in plan.get("resources") or []
        if (r.get("root"), r.get("tier"), r.get("address")) not in keys
    ]
    plan["roots"] = roots_out
    plan["main_baseline"] = matched_all
    return plan


OWNER_STATUS = paths.agent_home() / "cache" / "owner-roots" / "status.json"
MAIN_PENDING_ACTIONS = ("destroy", "replace")


def _iso_epoch(s):
    try:
        return (
            dt.datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S")
            .replace(tzinfo=dt.timezone.utc)
            .timestamp()
        )
    except (TypeError, ValueError):
        return 0.0


def _main_apply_runs(owner_repo):
    """Completed terraform-apply runs on main, newest first (failed, success and cancelled alike)."""
    runs = (
        gh(
            [
                "api",
                f"repos/{owner_repo}/actions/workflows/terraform-apply.yml/runs?branch=main&status=completed&per_page=10",
            ]
        )
        or {}
    )
    out = [r for r in runs.get("workflow_runs") or [] if r.get("head_branch") == "main"]
    return sorted(out, key=lambda r: r.get("updated_at") or "", reverse=True)


def _failed_apply_pending(owner_repo, run):
    """{address: action} the plan jobs of a failed main apply planned, so a PR plan showing the same
    destroy or replace is main's leftover, not the PR's own change."""
    jobs = {"jobs": run_jobs(gh, owner_repo, run["id"])}
    out = {}
    for j in jobs.get("jobs") or []:
        if " plan" not in (j.get("name") or "") or j.get("conclusion") != "success":
            continue
        cache = CACHE_DIR / f"main-apply-{run['id']}-{j['id']}.json"
        if cache.exists():
            d = json.loads(cache.read_text())
        else:
            log = gh(
                [
                    "api",
                    f"repos/{owner_repo}/actions/jobs/{j['id']}/logs",
                    "--allow-escape-sequences",
                ],
                raw=True,
                timeout=90,
            )
            d = {a: act for a, (act, _dg) in resource_diffs(log).items()}
            try:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(d))
            except OSError:
                pass
        out.update(d)
    return out


def apply_main_pending(
    pol, owner_repo, plan, files, owner_status=None, apply_runs=None, apply_pending=None
):
    """. Every PR plans every root, so when
    main has a change it could not apply (its terraform-apply failed, or a root waits on its Owner
    apply), every open PR shows that change as its own destroy or replace and the card offered
    Approve and merge, which only repeats main's failure. Sets plan['main_pending']:
      state 'blocked': a destroy or replace in a root this PR does not touch is still pending on main
        (same address and action in the latest failed main apply plan, or in a pending Owner root plan).
      state 'stale': the plan ran before main's last successful apply or that root's last Owner apply,
        so the destroys are main's old leftovers and a re-run of the failed plan jobs clears them.
    Never changes the counts or the holds. Any read error leaves the plan untouched (the policy hold
    stays) and is recorded in plan['main_pending_error']."""
    if not plan.get("ran") or plan.get("status") != "completed":
        return plan

    def touches(root):
        return any(
            f.startswith("infrastructure/terraform/modules/") or f"/{root}/" in "/" + f
            for f in files or []
        )

    cands = [
        r
        for r in plan.get("resources") or []
        if r.get("action") in MAIN_PENDING_ACTIONS and r.get("root") and not touches(r["root"])
    ]
    if not cands:
        return plan
    plan = dict(plan)
    try:
        if owner_status is None:
            owner_status = (
                json.loads(OWNER_STATUS.read_text()).get("items", {})
                if OWNER_STATUS.exists()
                else {}
            )
        if apply_runs is None:
            apply_runs = _main_apply_runs(owner_repo)
        last = next((r for r in apply_runs if r.get("conclusion") in ("success", "failure")), None)
        failed = last if last and last.get("conclusion") == "failure" else None
        if failed and apply_pending is None:
            apply_pending = _failed_apply_pending(owner_repo, failed)
        apply_pending = apply_pending or {}
        blocked, stale = [], []
        started = _iso_epoch(plan.get("started_at"))
        ok_main = max(
            (
                _iso_epoch(r.get("updated_at"))
                for r in apply_runs
                if r.get("conclusion") == "success"
            ),
            default=0.0,
        )
        for r in cands:
            own = owner_status.get(f"{r['root']}:{r.get('tier')}") or {}
            own_res = {(x.get("address"), x.get("action")) for x in own.get("resources") or []}
            src = None
            if own.get("state") in ("pending", "planning", "applying", "error") and (
                (r["address"], r["action"]) in own_res or own.get("state") != "pending"
            ):
                src = {"kind": "owner", "root": r["root"], "tier": r.get("tier")}
            elif failed and apply_pending.get(r["address"]) == r["action"]:
                src = {
                    "kind": "main_apply",
                    "run_id": failed["id"],
                    "run_url": failed.get("html_url"),
                }
            if src:
                blocked.append(dict(r, source=src))
                continue
            owner_at = _iso_epoch((own.get("last_apply") or {}).get("at"))
            if started and (owner_at > started or ok_main > started):
                stale.append(r)
    except (GhError, ValueError, KeyError, TypeError, OSError) as e:
        plan["main_pending_error"] = str(e)[:200]
        return plan
    if blocked:
        plan["main_pending"] = {"state": "blocked", "resources": blocked}
    elif stale and len(stale) == len(cands):
        plan["main_pending"] = {"state": "stale", "resources": stale, "run_id": plan.get("run_id")}
    return plan


def main_pending_reason(plan):
    """The lane's hold reason for plan['main_pending'], or None. Worded so the auto-fixer never maps
    it to a fixable problem: nothing on the branch can fix main."""
    mp = (plan or {}).get("main_pending") or {}
    res = mp.get("resources") or []
    if not res:
        return None
    roots = ", ".join(sorted({f"{r['root']} {r.get('tier')}" for r in res}))
    n = len(res)
    if mp.get("state") == "stale":
        return f"plans predate main's last apply: {n} destroy or replace in {roots} only main had, re-running the plan"
    srcs = []
    for r in res:
        s = r["source"]
        t = (
            f"the Owner apply of {s['root']} {s['tier']}"
            if s["kind"] == "owner"
            else f"main terraform-apply run {s['run_id']} (failed)"
        )
        if t not in srcs:
            srcs.append(t)
    return f"main not applied: {n} destroy or replace in {roots} are main's pending change, waits on {' and '.join(srcs)}"


def plan_summary(pol, sha):
    """Read the terraform-ci plan jobs for this head sha."""
    owner, name = repo_parts(pol)
    runs = gh(["api", f"repos/{owner}/{name}/actions/runs?head_sha={sha}&per_page=50"]) or {}
    tf = [
        r
        for r in runs.get("workflow_runs", [])
        if r.get("path", "").endswith("terraform-ci.yml") and r.get("event") == "pull_request"
    ]
    if not tf:
        return {
            "ran": False,
            "note": "terraform-ci did not run on this head (no Terraform paths changed)",
        }
    run = sorted(tf, key=lambda r: r.get("created_at") or "")[-1]
    out = {
        "ran": True,
        "run_id": run["id"],
        "run_url": run.get("html_url"),
        "started_at": run.get("run_started_at") or run.get("created_at"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "add": 0,
        "change": 0,
        "destroy": 0,
        "import": 0,
        "replace": 0,
        "roots": [],
        "destroyed": [],
        "replaced": [],
        "errors": [],
        "resources": [],
    }
    if run.get("status") != "completed":
        out["note"] = f"terraform-ci is {run.get('status')} (plan not final)"
        return out
    jobs = {"jobs": run_jobs(gh, f"{owner}/{name}", run["id"])}
    for j in jobs.get("jobs", []):
        if not j.get("name", "").startswith("terraform plan"):
            continue
        root = {
            "job": j["name"],
            "job_id": j.get("id"),
            "conclusion": j.get("conclusion"),
            "summary": "",
            "destroy": 0,
            "guard_only": False,
        }
        rj = ROOT_JOB.match(j["name"])
        root["root"], root["tier"] = (rj.group(1), rj.group(2)) if rj else (None, None)
        job_errors = []
        cur = None
        if j.get("conclusion") in ("success", "failure"):
            try:
                log = gh(
                    [
                        "api",
                        f"repos/{owner}/{name}/actions/jobs/{j['id']}/logs",
                        "--allow-escape-sequences",
                    ],
                    raw=True,
                    timeout=90,
                )
            except GhError as e:
                root["summary"] = f"log unavailable: {str(e)[:120]}"
                log = ""
            for line in log.splitlines():
                body = re.sub(r"^\S+Z ", "", line)
                body = re.sub(r"\x1b\[[0-9;]*m", "", body)
                m = PLAN_LINE.search(body)
                if m and "grep" not in body:
                    g = [int(x) for x in m.groups() if x is not None]
                    if len(g) == 4:
                        imp, a, c, d = g
                    else:
                        imp, (a, c, d) = 0, g
                    out["import"] += imp
                    out["add"] += a
                    out["change"] += c
                    out["destroy"] += d
                    root["destroy"] += d
                    root["summary"] = body.strip()
                    root["parsed"] = True
                    cur = None
                elif body.startswith("No changes.") and not root["summary"]:
                    root["summary"] = "No changes"
                    root["parsed"] = True
                r = RES_LINE.search(body)
                if r:
                    if r.group(2) == "will be destroyed":
                        out["destroyed"].append(r.group(1))
                    elif r.group(2) == "must be replaced":
                        out["replaced"].append(r.group(1))
                    act = RES_ACTION.get(r.group(2))
                    cur = None
                    if act and len(out["resources"]) < MAX_RESOURCES:
                        cur = {
                            "root": root["root"],
                            "tier": root["tier"],
                            "address": r.group(1),
                            "action": act,
                            "attrs": [],
                            "names": [],
                        }
                        out["resources"].append(cur)
                elif cur is not None and cur["action"] in ("update", "replace"):
                    a = ATTR_LINE.match(body)
                    if (
                        a
                        and a.group(2) != "resource"
                        and len(cur["attrs"]) < 40
                        and a.group(2) not in cur["attrs"]
                    ):
                        cur["attrs"].append(a.group(2))
                    nm = NAME_LINE.match(body)
                    if nm and not cur["names"]:
                        cur["names"].append(nm.group(1))
                if body.startswith("Error:") or "##[error]" in body:
                    out["errors"].append(f"{j['name']}: {body.strip()[:200]}")
                    job_errors.append(body.strip())
        # The job failed only on terraform-ci's destroy guard: the plan itself is fine, it
        # deletes something, and the guard sends that to a reviewed change (the owner's sign-off).
        root.setdefault("parsed", False)
        root["guard_only"] = bool(
            j.get("conclusion") == "failure"
            and root["destroy"] > 0
            and any(DESTROY_GUARD in e for e in job_errors)
            and all(DESTROY_GUARD in e or GUARD_EXIT in e for e in job_errors)
        )
        out["roots"].append(root)
    out["replace"] = len(set(out["replaced"]))
    out["destroyed"] = sorted(set(out["destroyed"]))
    out["replaced"] = sorted(set(out["replaced"]))
    out["errors"] = out["errors"][:10]
    return out


def fetch_one(pol, pr_num):
    owner, name = repo_parts(pol)
    d = gh(
        [
            "api",
            "graphql",
            "-f",
            f"query={ONE_QUERY}",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"n={pr_num}",
        ]
    )
    node = d["data"]["repository"]["pullRequest"]
    if not node:
        raise GhError(f"PR #{pr_num} not found")
    return complete_rollup(pol, node)


ROLLUP_CAP = 100


def complete_rollup(pol, node):
    """The GraphQL query reads the first 100 check contexts, oldest first. Re-runs and
    cancelled runs can push a PR past that, which drops the newest results and leaves a
    superseded CANCELLED or FAILURE as the latest. At the cap, read the full rollup
    (gh pr view pages it) and rewrite it in the GraphQL node shape."""
    try:
        rollup = node["commits"]["nodes"][0]["commit"]["statusCheckRollup"]
        ctx = rollup["contexts"]["nodes"]
    except (KeyError, IndexError, TypeError):
        return node
    if len(ctx) < ROLLUP_CAP:
        return node
    full = (
        gh(["pr", "view", str(node["number"]), "-R", pol["repo"], "--json", "statusCheckRollup"])
        or {}
    )
    items = full.get("statusCheckRollup") or []
    if len(items) <= len(ctx):
        return node
    out = []
    for c in items:
        if c.get("__typename") == "StatusContext":
            out.append(
                {
                    "__typename": "StatusContext",
                    "context": c.get("context"),
                    "state": c.get("state"),
                    "createdAt": c.get("startedAt") or c.get("createdAt"),
                }
            )
        else:
            out.append(
                {
                    "__typename": "CheckRun",
                    "name": c.get("name"),
                    "conclusion": c.get("conclusion") or None,
                    "status": c.get("status"),
                    "startedAt": c.get("startedAt"),
                    "checkSuite": {
                        "workflowRun": {"workflow": {"name": c.get("workflowName") or ""}}
                    },
                }
            )
    rollup["contexts"]["nodes"] = out
    return node


AI_REVIEW_MARKER = "<!-- ai-review:v1 -->"
AI_REVIEW_DATA_PREFIX = "<!-- ai-review-data:v2 "
AI_REVIEW_DATA_SUFFIX = " -->"


def ai_review_verdict(owner_repo, pr_num):
    """Newest verdict embedded by the primary PR Review workflow (github-actions[bot] only)."""
    out = gh(
        [
            "api",
            "--paginate",
            f"repos/{owner_repo}/issues/{pr_num}/comments?per_page=100",
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
            and body.startswith(AI_REVIEW_MARKER)
            and AI_REVIEW_DATA_PREFIX in body
        ):
            blob = body.split(AI_REVIEW_DATA_PREFIX, 1)[1].split(AI_REVIEW_DATA_SUFFIX, 1)[0]
            try:
                found = json.loads(base64.b64decode(blob).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                found = None
    return found


def ai_review_blocking_hits(owner_repo, pr_num, sha, checks):
    """A red `ai-review result` on a confirmed blocking verdict for the
    current head is binding: escalate, never approve. An override label applied
    by a maintainer turns the check green, which clears this automatically.
    An unavailable verdict (provider outage) is not escalated; the check stays
    red and the approve path waits."""
    state = None
    for k, v in checks.items():
        if k.endswith("ai-review result"):
            state = v
    if state not in ("FAILURE", "ERROR"):
        return []
    try:
        verdict = ai_review_verdict(owner_repo, pr_num)
    except GhError:
        return []
    if not verdict or verdict.get("verdict") != "blocked" or verdict.get("head_sha") != sha:
        return []
    items = verdict.get("blocking") or []
    detail = "; ".join(f"{i.get('id')}: {i.get('title')} ({i.get('location')})" for i in items[:5])
    return [
        {
            "rule": "ai-review-blocking",
            "reason": f"PR review found {(verdict.get('counts') or {}).get('blocking', len(items))} confirmed blocking finding(s)",
            "where": "",
            "detail": detail[:300],
        }
    ]


# ---------------------------------------------------------------------
# Maintenance window
# ---------------------------------------------------------------------
def deploy_specs(pol):
    """apps/*/deploy.json from main (what tf-discover reads on a push to main). Cached by the
    main tree sha for SPECS_TTL_S. Raises GhError/ValueError on any read failure (fail closed)."""
    cache = load_json(SPECS_CACHE, None)
    if (
        cache
        and NOW - float(cache.get("epoch", 0)) < SPECS_TTL_S
        and isinstance(cache.get("specs"), list)
    ):
        return cache["specs"]
    owner, name = repo_parts(pol)
    tree = gh(["api", f"repos/{owner}/{name}/git/trees/main?recursive=1"]) or {}
    if tree.get("truncated") or not tree.get("sha"):
        raise ValueError("main tree listing is truncated or empty")
    if (
        cache
        and cache.get("sha") == tree["sha"]
        and cache.get("v") == 2
        and isinstance(cache.get("specs"), list)
    ):
        cache["epoch"] = NOW
        write_json(SPECS_CACHE, cache)
        return cache["specs"]
    specs = []
    for t in tree.get("tree") or []:
        path = t.get("path") or ""
        if t.get("type") != "blob" or not re.fullmatch(
            r"(apps|functions)/[^/]+/deploy\.json", path
        ):
            continue
        blob = gh(["api", f"repos/{owner}/{name}/git/blobs/{t['sha']}"]) or {}
        d = json.loads(base64.b64decode(blob.get("content") or "").decode("utf-8"))
        d["_dir"] = path.rsplit("/", 1)[0]
        d["_file"] = path
        specs.append(d)
    if not specs:
        raise ValueError("no apps/*/deploy.json found on main")
    write_json(SPECS_CACHE, {"sha": tree["sha"], "v": 2, "epoch": NOW, "specs": specs})
    return specs


def downtime(pol, files, plan, now=None):
    """Downtime verdict for a PR: hits (plain reasons naming each system), change class,
    whether its window is open now, and when the next one opens."""
    cfg = mw.cfg_of(pol)
    if not cfg.get("enabled"):
        return {"enabled": False, "downtime": False, "hits": []}
    try:
        specs, err = deploy_specs(pol), None
    except (GhError, ValueError, KeyError, TypeError) as e:
        specs, err = [], e
    try:
        hits = mw.classify(pol, files, plan, specs, err)
    except Exception as e:  # noqa: BLE001 - a classifier bug must never let a downtime change through
        hits = [
            {
                "kind": "classifier-error",
                "system": None,
                "reason": "the owner could not work out what this change takes down, so the owner treat it as taking a system down",
                "where": f"{type(e).__name__}: {e}"[:200],
            }
        ]
    out = {"enabled": True, "downtime": bool(hits), "hits": hits, "class": None}
    if hits:
        now = now or now_utc()
        cls = mw.change_class(pol, hits)
        nxt = mw.next_open(cfg, cls, now)
        out.update(
            {
                "class": cls,
                "class_label": mw.class_label(cls),
                "in_window": mw.in_window(cfg, cls, now),
                "next_open": iso(nxt[0]) if nxt else None,
                "window_phrase": mw.window_phrase(cfg, cls, now),
            }
        )
    return out


def load_held():
    return load_json(HELD, {"items": {}})


def save_held(h):
    h["updated"] = NOW_ISO
    write_json(HELD, h)


def post_window_comment(pr_num, body):
    """One plain comment in the owner's voice. Refuses tool wording, em dashes and semicolons."""
    if FORBIDDEN_WORDS.search(body) or ";" in body or "\u2014" in body or "\u2013" in body:
        raise SystemExit("window comment failed the wording check")
    pol = policy()
    owner, name = repo_parts(pol)
    f = CACHE_DIR / f"window-comment-{pr_num}.md"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f.write_text(body + "\n")
    try:
        gh(["pr", "comment", str(pr_num), "-R", f"{owner}/{name}", "--body-file", str(f)], raw=True)
    finally:
        f.unlink(missing_ok=True)


def _set_queue(pr_num, fields, action):
    q = load_queue()
    it = q.setdefault("items", {}).get(str(pr_num)) or {
        "pr": int(pr_num),
        "first_seen": NOW_ISO,
        "history": [],
    }
    it.update(fields)
    it["updated"] = NOW_ISO
    it["last_action_at"] = NOW_ISO
    it.setdefault("history", []).append(
        {"at": NOW_ISO, "status": it.get("status"), "action": action, "sha": it.get("head_sha")}
    )
    it["history"] = it["history"][-30:]
    q["items"][str(pr_num)] = it
    q["updated"] = NOW_ISO
    write_json(QUEUE, q)


def _window_gates(c, sha, accept_threads=False):
    """The normal approve gates, re-run inside the window. Empty list = clear to enqueue.
    accept_threads: the hold is the owner's own approval, so open threads are left to the enqueue,
    which resolves the ones he started and refuses on anyone else's (PR 461)."""
    why = []
    if c["state"] != "OPEN":
        why.append(f"PR is {c['state']}")
    if c["head_sha"] != sha:
        why.append(f"head moved to {c['head_sha'][:8]}")
    if c["skipped_author"]:
        why.append("author is me or a bot")
    if c["draft"]:
        why.append("PR is a draft")
    if c["escalate"]:
        why.append("policy escalation: " + ", ".join(h["rule"] for h in c["escalations"]))
    if not c["checks"]["green"]:
        why.append(f"checks not green: red={c['checks']['red']} pending={c['checks']['pending']}")
    if c["unresolved_threads"] and not accept_threads:
        why.append(f"{c['unresolved_threads']} unresolved review thread(s)")
    if c["mergeable"] == "CONFLICTING":
        why.append("merge conflict")
    if "APPROVED" not in (c.get("my_reviews_at_head") or []):
        why.append("the owner's approval is not on this head")
    return why


def window_pass(pol, nodes, now=None):
    """Each gate pass: drop holds whose PR closed or got a new push, enqueue held PRs whose
    window is open and whose gates still pass, flag holds that outlived a full window.
    Returns gate output lines (each one wakes the agent to relay it)."""
    cfg = mw.cfg_of(pol)
    now = now or now_utc()
    lines = []
    with Locked():
        held = load_held()
    items = held.get("items") or {}
    if not items:
        return lines
    orig = {k: dict(v) for k, v in items.items()}
    owner, name = repo_parts(pol)
    heads = {n["number"]: n.get("headRefOid") for n in nodes}
    changed = False
    for k in sorted(items, key=int):
        it = items[k]
        n = int(k)
        cls = it.get("class") or "both"
        if n not in heads:
            del items[k]
            changed = True
            log_decision(
                {
                    "pr": n,
                    "decision": "hold_closed",
                    "lane": "maintenance-window",
                    "sha": it.get("head_sha"),
                }
            )
            continue
        if heads[n] != it.get("head_sha"):
            del items[k]
            changed = True
            with Locked():
                _set_queue(
                    n,
                    {
                        "status": "in_progress",
                        "head_sha": heads[n],
                        "last_action": "new commits after the window hold, reviewing again",
                    },
                    "window hold dropped on a new push",
                )
            log_decision(
                {
                    "pr": n,
                    "decision": "hold_dropped_new_push",
                    "lane": "maintenance-window",
                    "sha": it.get("head_sha"),
                    "new_sha": heads[n],
                }
            )
            lines.append(
                f"[{LANE} WINDOW] PR #{n} {it.get('title', '')[:60]}: new push, the window hold dropped and it needs a fresh review"
            )
            continue
        if not mw.in_window(cfg, cls, now):
            if not it.get("stale_alerted") and mw.stale(cfg, cls, mw_parse(it.get("held_at")), now):
                it["stale_alerted"] = NOW_ISO
                changed = True
                lines.append(
                    f"[{LANE} WINDOW] PR #{n} {it.get('title', '')[:60]}: still held after a full {mw.class_label(cls)} window passed"
                    + (f" (last check: {it.get('last_check')})" if it.get("last_check") else "")
                )
            continue
        if NOW - float(it.get("last_check_epoch") or 0) < WINDOW_RECHECK_S:
            continue
        it["last_check_epoch"] = NOW
        it["last_check_at"] = NOW_ISO
        changed = True
        try:
            c = check(n)
        except GhError as e:
            it["last_check"] = f"check failed: {str(e)[:160]}"
            continue
        mine = str(it.get("approved_by") or "").lower() == str(pol.get("self_login") or "").lower()
        why = _window_gates(c, it["head_sha"], accept_threads=mine)
        dtm = c.get("downtime") or {}
        if dtm.get("downtime") and dtm.get("class") and dtm["class"] != cls:
            it["class"] = dtm["class"]
            if not mw.in_window(cfg, dtm["class"], now):
                it["last_check"] = (
                    f"class is now {mw.class_label(dtm['class'])}, waiting for that window"
                )
                continue
        if why:
            it["last_check"] = ", ".join(why)[:300]
            continue
        sha = it["head_sha"]
        if DRY_RUN:
            log_decision(
                {
                    "pr": n,
                    "decision": "would_window_enqueue",
                    "lane": "maintenance-window",
                    "sha": sha,
                }
            )
            it["last_check"] = "dry run: would enqueue"
            continue
        try:
            queued = mqueue.enqueue(
                f"{owner}/{name}",
                n,
                sha,
                gh=gh,
                accept_own_threads=pol.get("self_login") if mine else None,
            )
        except mqueue.MergeQueueError as e:
            it["last_check"] = f"enqueue failed: {str(e)[:200]}"
            log_decision(
                {
                    "pr": n,
                    "decision": "window_enqueue_failed",
                    "lane": "maintenance-window",
                    "sha": sha,
                    "error": str(e)[:300],
                }
            )
            lines.append(
                f"[{LANE} WINDOW] PR #{n} {it.get('title', '')[:60]}: enqueue in the window failed: {str(e)[:160]}"
            )
            continue
        del items[k]
        with Locked():
            _set_queue(
                n,
                {
                    "status": "approved",
                    "last_action": f"merge {queued['text']} in the {mw.class_label(cls)} maintenance window at {sha[:8]}",
                },
                "merge queued in the maintenance window",
            )
        log_decision(
            {
                "pr": n,
                "decision": "window_enqueued",
                "lane": "maintenance-window",
                "sha": sha,
                "class": cls,
            }
        )
        lines.append(
            f"[{LANE} WINDOW] PR #{n} {it.get('title', '')[:60]}: merge queued in the {mw.class_label(cls)} maintenance window"
        )
    if changed:
        with Locked():
            # Merge under the lock: the owner's result wins for the PRs the owner looked at (same head as when the owner
            # read them), anything the Ops Center added or replaced meanwhile stays.
            cur = load_held()
            cur_items = cur.setdefault("items", {})
            for k, was in orig.items():
                now_it = cur_items.get(k)
                if now_it is not None and now_it.get("head_sha") != was.get("head_sha"):
                    continue
                if k in items:
                    cur_items[k] = items[k]
                else:
                    cur_items.pop(k, None)
            save_held(cur)
    return lines


def mw_parse(s):
    try:
        return dt.datetime.strptime((s or "")[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=dt.timezone.utc
        )
    except ValueError:
        return now_utc()


def parse_pr_files(out):
    """PR files API lines (one JSON object per line) -> (sorted paths incl. previous names,
    {filename: previous_filename} for status 'renamed'). A bad line raises, so a short or garbled
    read fails the check instead of hiding a file."""
    files = []
    renamed = {}
    for line in out.splitlines():
        if line.strip():
            f = json.loads(line)
            files.append(f["filename"])
            if f.get("previous_filename"):
                files.append(f["previous_filename"])
                if f.get("status") == "renamed":
                    renamed[f["filename"]] = f["previous_filename"]
    return sorted(set(files)), renamed


def check(pr_num):
    pol = policy()
    owner, name = repo_parts(pol)
    node = fetch_one(pol, pr_num)
    sha = node["headRefOid"]
    owner_repo = f"{owner}/{name}"
    out = gh(
        [
            "api",
            "--paginate",
            f"repos/{owner_repo}/pulls/{pr_num}/files?per_page=100",
            "--jq",
            ".[] | @json",
        ],
        raw=True,
    )
    files, renamed = parse_pr_files(out)
    try:
        diff = gh(["pr", "diff", str(pr_num), "-R", owner_repo], timeout=120, raw=True)
        diff_ok = True
    except GhError as e:
        if re.search(r"too large|406|maximum number", str(e), re.I):
            diff, diff_ok = "", False
        else:
            raise
    own = ((node.get("author") or {}).get("login") or "").lower() == (
        pol.get("self_login") or ""
    ).lower()
    hits = policy_hits(pol, files, diff, own=own)
    hits += trust_hits(pol, owner_repo, (node.get("author") or {}).get("login"), files, renamed)
    hits += prod_wiring_hits(pol, owner_repo, (node.get("author") or {}).get("login"), files, sha)
    if not diff_ok:
        hits.append({"rule": "diff-too-large", "reason": "diff too large to verify", "where": ""})
    if pol.get("reuse_tfplan_gate_matcher", True):
        hits += tfplan_matcher_hits(pr_num, own=own, head_sha=sha)
    plan = plan_summary(pol, sha)
    plan = apply_branch_drift(pol, owner_repo, pr_num, sha, plan)
    plan = apply_main_baseline(pol, owner_repo, plan, files)
    plan = apply_main_pending(pol, owner_repo, plan, files)
    pr_rules = pol.get("plan_rules", {})
    if plan.get("ran"):
        if plan.get("destroy", 0) > 0 or plan.get("destroyed"):
            hits.append(
                {
                    "rule": pr_rules.get("destroy", {}).get("id", "plan-destroy"),
                    "reason": pr_rules.get("destroy", {}).get("reason", "plan destroys resources"),
                    "where": plan.get("run_url", ""),
                    "detail": ", ".join(plan.get("destroyed", [])[:10]),
                }
            )
        if plan.get("replace", 0) > 0:
            hits.append(
                {
                    "rule": pr_rules.get("replace", {}).get("id", "plan-replace"),
                    "reason": pr_rules.get("replace", {}).get("reason", "plan replaces resources"),
                    "where": plan.get("run_url", ""),
                    "detail": ", ".join(plan.get("replaced", [])[:10]),
                }
            )
        if plan.get("errors") and pr_rules.get("plan_error", {}).get("escalate"):
            hits.append(
                {
                    "rule": "plan-error",
                    "reason": pr_rules["plan_error"]["reason"],
                    "where": plan.get("run_url", ""),
                }
            )
    if pol.get("ai_review", {}).get("escalate_blocking", True):
        hits += ai_review_blocking_hits(owner_repo, pr_num, sha, checks_of(node))
    hits, trust_waiver = dev_tier_only_waiver(pol, owner_repo, sha, files, hits, plan)
    # de-dupe
    seen, uniq = set(), []
    for h in hits:
        k = (h["rule"], h["reason"], h.get("where", ""))
        if k not in seen:
            seen.add(k)
            uniq.append(h)
    uniq = annotate_fps(pol, uniq, diff if diff_ok else "")
    checks = checks_of(node)
    me = pol["self_login"]
    unresolved = sum(1 for t in node["reviewThreads"]["nodes"] if not t["isResolved"])
    a = node.get("author") or {}
    return {
        "pr": pr_num,
        "title": node["title"],
        "url": node["url"],
        "author": a.get("login"),
        "skipped_author": is_skipped_author(a.get("login"), a.get("__typename"), pol),
        "state": node.get("state"),
        "draft": node.get("isDraft"),
        "head_sha": sha,
        "mergeable": node.get("mergeable"),
        "merge_state": node.get("mergeStateStatus"),
        "review_decision": node.get("reviewDecision"),
        "my_reviews_at_head": [
            r["state"]
            for r in node["reviews"]["nodes"]
            if ((r.get("author") or {}).get("login") == me)
            and ((r.get("commit") or {}).get("oid") == sha)
        ],
        "unresolved_threads": unresolved,
        "files": files,
        "escalations": uniq,
        "escalate": bool(uniq),
        "trust_waiver": trust_waiver,
        "plan": plan,
        "confirm_needed": _confirm_needed(plan, pr_num),
        "main_pending_reason": main_pending_reason(plan),
        "downtime": downtime(pol, files, plan),
        "checks": dict(
            summarize_checks(checks),
            destroy_guard_only=destroy_guard_only(summarize_checks(checks), plan),
        ),
        "check_detail": checks,
        "policy_version": pol.get("version"),
        "policy_sha": pol["_sha"],
        "checked_at": NOW_ISO,
    }


# ---------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------
class Locked:
    def __enter__(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.f = open(LOCK, "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        self.f.close()


def load_queue():
    return load_json(QUEUE, {"items": {}})


RISKS = ("low", "medium", "high")
RECS = ("approve", "request changes", "reject")


def validate_escalation(e):
    for f in ("summary", "changes", "plan", "risk", "rules", "recommendation"):
        if f not in e or e[f] in (None, "", []):
            raise SystemExit(f"escalation missing field: {f}")
    if not isinstance(e["changes"], list) or not all(
        isinstance(c, (str, dict)) for c in e["changes"]
    ):
        raise SystemExit(
            "escalation.changes must be a list of 'file -> behaviour' strings or {file, behaviour}"
        )
    if (
        not isinstance(e["risk"], dict)
        or e["risk"].get("level") not in RISKS
        or not e["risk"].get("why")
    ):
        raise SystemExit('escalation.risk must be {"level": low|medium|high, "why": "..."}')
    if (
        not isinstance(e["recommendation"], dict)
        or e["recommendation"].get("action") not in RECS
        or not e["recommendation"].get("why")
    ):
        raise SystemExit(
            'escalation.recommendation must be {"action": approve|request changes|reject, "why": "..."}'
        )
    if not isinstance(e["rules"], list):
        raise SystemExit("escalation.rules must be a list")
    if not isinstance(e["plan"], (dict, str)):
        raise SystemExit(
            "escalation.plan must be an object {add, change, destroy, replace, summary} or a string"
        )


MINOR_SEVERITIES = ("NIT", "LOW", "INFO", "STYLE", "MINOR")


def defer_escalation(upd):
    """the owner 2026-10-20: an escalation recorded while the review still has open
    findings goes to the engineer first. The item is stored as changes_requested with the
    escalation kept as pending_escalation, so no approve card reaches the owner for a PR the review
    says is not ready. The next review round on a fixed head records escalated again and surfaces
    it. A reject recommendation still escalates at once. Only nits open never defer. Returns
    (status, upd) with upd changed in place when deferred."""
    if upd.get("status") != "escalated":
        return upd.get("status"), upd
    esc = upd.get("escalation") or {}
    if ((esc.get("recommendation") or {}).get("action") or "").lower() == "reject":
        return "escalated", upd
    try:
        n_open = int(upd.get("open_findings") or 0)
    except (TypeError, ValueError):
        n_open = 0
    if n_open <= 0:
        return "escalated", upd
    findings = upd.get("findings")
    if isinstance(findings, list) and findings:
        real = [
            f
            for f in findings
            if str((f or {}).get("severity") or "").upper() not in MINOR_SEVERITIES
        ]
        if not real:
            return "escalated", upd
    upd["status"] = "changes_requested"
    upd["pending_escalation"] = esc
    upd.pop("escalation", None)
    tail = "escalation deferred until the engineer resolves the open findings"
    la = upd.get("last_action") or ""
    upd["last_action"] = f"{la}, {tail}" if la else tail
    return "changes_requested", upd


def record(pr_num, path):
    upd = json.loads(Path(path).read_text())
    st = upd.get("status")
    if st not in STATUSES:
        raise SystemExit(f"status must be one of {STATUSES}")
    if st == "escalated":
        validate_escalation(upd.get("escalation") or {})
        st, upd = defer_escalation(upd)
    if st == "escalated" and ("downtime" not in upd or "confirm_needed" not in upd):
        try:
            c = check(int(pr_num))
            upd.setdefault("downtime", c.get("downtime"))
            upd.setdefault("confirm_needed", c.get("confirm_needed"))
        except (GhError, KeyError, TypeError, ValueError) as e:
            upd.setdefault("downtime", {"enabled": True, "unknown": True, "error": str(e)[:200]})
            upd.setdefault("confirm_needed", None)
    with Locked():
        q = load_queue()
        items = q.setdefault("items", {})
        it = items.get(str(pr_num)) or {
            "pr": int(pr_num),
            "first_seen": NOW_ISO,
            "history": [],
            "rounds": 0,
        }
        prev = it.get("status")
        for k in (
            "title",
            "author",
            "url",
            "head_sha",
            "open_findings",
            "last_action",
            "findings",
            "plan",
            "rounds",
            "escalation",
            "pending_escalation",
            "note",
            "downtime",
            "confirm_needed",
        ):
            if k in upd:
                it[k] = upd[k]
        it["status"] = st
        if st != "changes_requested":
            it.pop("pending_escalation", None)
        elif "pending_escalation" in upd:
            it.pop("escalation", None)
        it["updated"] = NOW_ISO
        it["last_action_at"] = NOW_ISO
        if st == "escalated" and prev != "escalated":
            it["escalated_at"] = NOW_ISO
        if st in ("approved", "merged"):
            it.setdefault("shipped_at", NOW_ISO)
        if st == "in_progress":
            it.pop("escalation", None) if upd.get("clear_escalation") else None
        it.setdefault("history", []).append(
            {
                "at": NOW_ISO,
                "status": st,
                "action": upd.get("last_action", ""),
                "sha": upd.get("head_sha", it.get("head_sha")),
            }
        )
        it["history"] = it["history"][-30:]
        items[str(pr_num)] = it
        q["updated"] = NOW_ISO
        write_json(QUEUE, q)
    log_decision(
        {
            "pr": int(pr_num),
            "decision": st,
            "action": upd.get("last_action", ""),
            "sha": upd.get("head_sha"),
        }
    )
    print(f"recorded PR #{pr_num}: {st}")


def _hold_for_window(pol, pr_num, sha, c, dtm, approved_by):
    """Approved, not enqueued: record the hold, post the one window comment for this head."""
    cfg = mw.cfg_of(pol)
    now = now_utc()
    cls = dtm.get("class") or "both"
    with Locked():
        held = load_held()
        prev = (held.get("items") or {}).get(str(pr_num)) or {}
    posted = prev.get("comment_posted_at") if prev.get("head_sha") == sha else None
    comment_err = None
    if not posted:
        try:
            post_window_comment(pr_num, mw.pr_comment(cfg, cls, dtm.get("hits") or [], now))
            posted = NOW_ISO
        except GhError as e:
            comment_err = str(e)[:200]
    nxt = mw.next_open(cfg, cls, now)
    rec = {
        "pr": int(pr_num),
        "title": c["title"],
        "author": c["author"],
        "url": c["url"],
        "head_sha": sha,
        "class": cls,
        "hits": dtm.get("hits") or [],
        "held_at": prev.get("held_at") if prev.get("head_sha") == sha else iso(now),
        "approved_by": approved_by,
        "window_opens": iso(nxt[0]) if nxt else None,
        "comment_posted_at": posted,
    }
    if comment_err:
        rec["comment_error"] = comment_err
    with Locked():
        held = load_held()
        held.setdefault("items", {})[str(pr_num)] = rec
        save_held(held)
        _set_queue(
            pr_num,
            {
                "title": c["title"],
                "author": c["author"],
                "url": c["url"],
                "head_sha": sha,
                "status": "held_for_window",
                "open_findings": 0,
                "plan": c.get("plan"),
                "downtime": dtm,
                "last_action": f"approved at {sha[:8]}, merges in {mw.window_phrase(cfg, cls, now)}",
            },
            "approved, held for the maintenance window",
        )
    log_decision(
        {
            "pr": pr_num,
            "decision": "approved_held_for_window",
            "lane": "maintenance-window",
            "sha": sha,
            "class": cls,
            "systems": sorted({h.get("system") or "unknown" for h in rec["hits"]}),
            "window_opens": rec["window_opens"],
        }
    )
    print(
        json.dumps(
            {
                "approved": True,
                "merge": "held for the maintenance window",
                "window": mw.window_phrase(cfg, cls, now),
            }
        )
    )


def approve(pr_num, sha, body_file, merge=True):
    pol = policy()
    owner, name = repo_parts(pol)
    c = check(pr_num)
    why = []
    if c["state"] != "OPEN":
        why.append(f"PR is {c['state']}")
    if c["head_sha"] != sha:
        why.append(f"head moved to {c['head_sha'][:8]} (asked for {sha[:8]})")
    if c["skipped_author"]:
        why.append(f"author {c['author']} is me or a bot; this lane never approves those")
    if c["draft"]:
        why.append("PR is a draft")
    if (c.get("trust_waiver") or {}).get("pending"):
        why.append("terraform-ci plan not final yet (dev-prefix-only waiver pending)")
    if c["escalate"]:
        why.append(
            "policy escalation: "
            + "; ".join(f"{h['rule']} ({h.get('where') or h['reason']})" for h in c["escalations"])
        )
    if not c["checks"]["green"]:
        why.append(f"checks not green: red={c['checks']['red']} pending={c['checks']['pending']}")
    if c["unresolved_threads"]:
        why.append(f"{c['unresolved_threads']} unresolved review thread(s)")
    if c["mergeable"] == "CONFLICTING":
        why.append("merge conflict")
    if why:
        print(json.dumps({"approved": False, "refused": why}, indent=2))
        raise SystemExit(3)
    body = Path(body_file).read_text()
    if FORBIDDEN_WORDS.search(body):
        raise SystemExit(
            "review body contains forbidden wording (assistant/bot/tool names); rewrite in the owner's voice"
        )
    repo = f"{owner}/{name}"
    # a downtime change outside its window is approved now and merged in the window.
    dtm = c.get("downtime") or {}
    hold = bool(merge and dtm.get("downtime") and not dtm.get("in_window"))
    prev_hold = (load_held().get("items") or {}).get(str(pr_num)) or {}
    if prev_hold.get("head_sha") == sha:
        print(
            json.dumps(
                {
                    "approved": True,
                    "already": "approved and held for the maintenance window at this head",
                }
            )
        )
        return
    if DRY_RUN:
        log_decision(
            {"pr": pr_num, "decision": "would_approve", "sha": sha, "merge": merge, "hold": hold}
        )
        would = ["gh pr review --approve"]
        if hold:
            would += ["gh pr comment (approved, merges in the window)", "record held-for-window"]
        elif merge:
            would.append("gh pr merge --rebase --auto")
        print(json.dumps({"approved": False, "dry_run": True, "would": would, "downtime": dtm}))
        return
    gh(
        ["pr", "review", str(pr_num), "-R", repo, "--approve", "--body-file", str(body_file)],
        raw=True,
    )
    if hold:
        return _hold_for_window(pol, pr_num, sha, c, dtm, approved_by="automation")
    merged = None
    if merge:
        args = [
            "pr",
            "merge",
            str(pr_num),
            "-R",
            repo,
            "--rebase",
            "--auto",
            "--match-head-commit",
            sha,
        ]
        if pol.get("merge", {}).get("admin"):
            args.append("--admin")
        try:
            if "--admin" in args:
                gh(args, raw=True)  # an admin merge bypasses the queue on purpose, not in scope for
                merged = "queued"
            else:
                merged = mqueue.enqueue(repo, pr_num, sha, gh=gh)["text"]
        except (GhError, mqueue.MergeQueueError) as e:
            merged = f"enqueue failed: {str(e)[:200]}"
    log_decision({"pr": pr_num, "decision": "approved", "sha": sha, "merge": merged})
    with Locked():
        q = load_queue()
        it = q.setdefault("items", {}).get(str(pr_num)) or {
            "pr": pr_num,
            "first_seen": NOW_ISO,
            "history": [],
        }
        it.update(
            {
                "title": c["title"],
                "author": c["author"],
                "url": c["url"],
                "head_sha": sha,
                "status": "approved",
                "open_findings": 0,
                "last_action": f"approved at {sha[:8]}; merge {merged}",
                "last_action_at": NOW_ISO,
                "updated": NOW_ISO,
                "plan": c["plan"],
            }
        )
        it.setdefault("shipped_at", NOW_ISO)
        it.setdefault("history", []).append(
            {"at": NOW_ISO, "status": "approved", "action": f"merge {merged}", "sha": sha}
        )
        q["items"][str(pr_num)] = it
        q["updated"] = NOW_ISO
        write_json(QUEUE, q)
    print(json.dumps({"approved": True, "merge": merged}))


# ---------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------
def reconcile_closed(pol, open_numbers):
    """Queue items whose PR left the open set -> merged / closed."""
    changed = []
    q = load_queue()
    items = q.get("items", {})
    for k, it in items.items():
        if it.get("status") in ("merged", "closed") or int(k) in open_numbers:
            continue
        node = fetch_one(pol, int(k))
        if node.get("state") == "MERGED":
            it["status"], it["merged_at"] = "merged", node.get("mergedAt") or NOW_ISO
            it.setdefault("shipped_at", it["merged_at"])
        elif node.get("state") == "CLOSED":
            it["status"] = "closed"
        else:
            continue
        it["updated"] = NOW_ISO
        changed.append((k, it["status"]))
    # prune old terminal items
    for k in list(items):
        it = items[k]
        if it.get("status") in ("merged", "closed"):
            stamp = it.get("merged_at") or it.get("updated") or NOW_ISO
            try:
                age = (
                    NOW
                    - dt.datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")
                    .replace(tzinfo=dt.timezone.utc)
                    .timestamp()
                )
            except ValueError:
                age = 0
            if age > SHIPPED_KEEP_DAYS * 86400:
                del items[k]
    if changed:
        q["updated"] = NOW_ISO
        write_json(QUEUE, q)
        for k, st in changed:
            log_decision({"pr": int(k), "decision": st, "action": "reconciled by gate"})
    return changed


def gate_pass(pol, health):
    owner, name = repo_parts(pol)
    d = gh(
        [
            "api",
            "graphql",
            "-f",
            f"query={OPEN_QUERY}",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
        ]
    )
    nodes = d["data"]["repository"]["pullRequests"]["nodes"]
    eng = [complete_rollup(pol, n) for n in engineer_nodes(nodes, pol)]
    new = {
        "policy_sha": pol["_sha"],
        "prs": sorted([fp_of(n, pol) for n in eng], key=lambda x: x["number"]),
    }
    with Locked():
        closed = reconcile_closed(pol, {n["number"] for n in nodes})
    window_lines = window_pass(pol, nodes)
    old = load_json(FP_FILE, None)
    audit_due = (health.get("last_audit_date") != TODAY) and not NO_AUDIT
    lines = []
    if old is None:
        write_json(FP_FILE, new)
        if new["prs"] or audit_due:
            lines.append(
                f"[{LANE} PR GATE] {NOW_ISO} - baseline established. Engineer PRs open: {len(new['prs'])}"
            )
    else:
        # transient UNKNOWN mergeable keeps the cached value
        om = {p["number"]: p for p in old.get("prs", [])}
        for p in new["prs"]:
            if p["mergeable"] == "UNKNOWN" and p["number"] in om:
                p["mergeable"] = om[p["number"]]["mergeable"]
        nm = {p["number"]: p for p in new["prs"]}
        delta = []
        if old.get("policy_sha") != new["policy_sha"]:
            delta.append(
                f"- policy.json changed ({old.get('policy_sha')} -> {new['policy_sha']}): re-evaluate every open item"
            )
        for n, p in nm.items():
            if n not in om:
                delta.append(f"- PR #{n}: OPENED by {p['author']} (head {p['head'][:8]})")
                continue
            o = om[n]
            if o == p:
                continue
            parts = []
            if o["head"] != p["head"]:
                parts.append(f"new commits {o['head'][:8]} -> {p['head'][:8]}")
            for k in (
                "comments",
                "reviews",
                "thread_comments",
                "resolved_by_others",
                "mergeable",
                "draft",
                "terraform_ci",
            ):
                if o.get(k) != p.get(k):
                    parts.append(f"{k} {o.get(k)} -> {p.get(k)}")
            if o.get("checks") != p.get("checks"):
                ch = [f"{k}={v}" for k, v in p["checks"].items() if o.get("checks", {}).get(k) != v]
                parts.append("checks: " + ", ".join(ch[:8]) + (" ..." if len(ch) > 8 else ""))
            delta.append(f"- PR #{n} ({p['author']}): " + "; ".join(parts))
        only_closed = all(n not in nm for n in om) and not [
            x for x in delta if x.startswith("- PR") or x.startswith("- policy")
        ]
        write_json(FP_FILE, new)
        if delta:
            lines.append(f"[{LANE} PR GATE] {NOW_ISO} - engineer PR state changed.")
            lines.append("Delta:")
            lines += delta
        elif audit_due:
            lines.append(f"[{LANE} PR GATE] {NOW_ISO} - no PR state change.")
        _ = only_closed
    if closed:
        # merged/closed reconciliation is bookkeeping, not a wake
        pass
    if audit_due:
        lines.append(
            "[DAILY SELF-AUDIT] Forced daily wake (first run after midnight). Reconcile queue.json against live PRs, re-check escalated items still match policy, confirm gate health."
        )
        health["last_audit_date"] = TODAY
    if window_lines:
        if not lines:
            lines.append(f"[{LANE} PR GATE] {NOW_ISO} - maintenance window events.")
        lines += window_lines
    if lines:
        q = load_queue()
        lines.append(f"Engineer PRs open: {len(new['prs'])}")
        lines.append(json.dumps(new["prs"]))
        lines.append(
            "Queue: "
            + json.dumps(
                {
                    k: {"status": v.get("status"), "head_sha": (v.get("head_sha") or "")[:8]}
                    for k, v in q.get("items", {}).items()
                }
            )
        )
    return lines


def classify(err):
    if re.search(r"HTTP 401|Bad credentials|authentication|not logged in|token expired", err, re.I):
        return "AUTH"
    if re.search(r"could not resolve|timed out|timeout|connection|network|dial tcp", err, re.I):
        return "NETWORK"
    return "API"


def gate():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    health = load_json(HEALTH, {})
    failures = int(health.get("failures", 0))
    alert_count = int(health.get("alert_count", 0))
    last_alert = float(health.get("last_alert_epoch", 0))
    run_lock = open(CACHE_DIR / "gate.lock", "w")  # noqa: SIM115 -- flock held for the whole run
    try:
        fcntl.flock(run_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(SILENT)
        return
    err = None
    try:
        pol = policy()
        lines = gate_pass(pol, health)
    except GhError as e:
        err = str(e)
    except Exception as e:  # noqa: BLE001 - fail closed on any bug
        err = f"gate error {type(e).__name__}: {e}"
    if err is not None:
        failures += 1
        alert = failures == 3 or (
            failures > 3
            and (
                (alert_count == 1 and NOW - last_alert >= 3600)
                or (alert_count >= 2 and NOW - last_alert >= 14400)
            )
        )
        if alert:
            alert_count += 1
            last_alert = NOW
        health.update(
            {
                "failures": failures,
                "alert_count": alert_count,
                "last_alert_epoch": last_alert,
                "updated": NOW_ISO,
                "last_error": err[:500],
            }
        )
        write_json(HEALTH, health)
        if alert:
            print(f"[{LANE} PR GATE ALERT] {NOW_ISO}")
            print(
                f"{LANE} engineer-PR state fetch is FAILING ({classify(err)}). Consecutive failures: {failures}."
            )
            print(f"Error (first 500 chars): {err[:500]}")
            print(f"Failing CLOSED: no {LANE} PR reviews or approvals run while this persists.")
            print(
                "Action: diagnose (gh auth status, curl api.github.com) and report in one short line. Do not review or approve anything."
            )
        else:
            print(SILENT)
        return
    streak = failures
    health.update(
        {"failures": 0, "alert_count": 0, "last_alert_epoch": last_alert, "updated": NOW_ISO}
    )
    health.pop("last_error", None)
    write_json(HEALTH, health)
    if not lines:
        print(SILENT)
        return
    if streak:
        lines.insert(
            1,
            f"[CATCH-UP] gh had failed {streak} time(s) before this run; the delta covers everything that moved while blind.",
        )
    print("\n".join(lines))


def status():
    q = load_queue()
    for k, it in sorted(q.get("items", {}).items(), key=lambda x: int(x[0])):
        print(
            f"#{k} {it.get('status'):<17} {(it.get('head_sha') or '')[:8]} findings={it.get('open_findings', 0)} {it.get('title', '')[:60]}"
        )
    if not q.get("items"):
        print("queue empty")


def main():
    a = sys.argv[1:]
    if not a or a[0] == "gate":
        return gate()
    if a[0] == "check" and len(a) == 2:
        print(json.dumps(check(int(a[1])), indent=2))
        return
    if a[0] == "record" and len(a) == 3:
        return record(int(a[1]), a[2])
    if a[0] == "approve" and len(a) >= 2:
        pr = int(a[1])
        sha = a[a.index("--sha") + 1] if "--sha" in a else ""
        bf = a[a.index("--body-file") + 1] if "--body-file" in a else ""
        if not sha or not bf:
            raise SystemExit("usage: approve <pr> --sha <head_sha> --body-file <file> [--no-merge]")
        return approve(pr, sha, bf, merge="--no-merge" not in a)
    if a[0] == "status":
        return status()
    if a[0] == "window":
        pol = policy()
        cfg = mw.cfg_of(pol)
        items = load_held().get("items") or {}
        for k, it in sorted(items.items(), key=lambda x: int(x[0])):
            print(
                f"#{k} {it.get('class')} {(it.get('head_sha') or '')[:8]} held {it.get('held_at')} "
                f"merges in {mw.window_phrase(cfg, it.get('class') or 'both', now_utc())} | {it.get('last_check') or ''}"
            )
        if not items:
            print("nothing held for the maintenance window")
        return
    raise SystemExit(
        __doc__
        or "usage: pr_review.py [gate|check <pr>|record <pr> <file>|approve <pr> --sha S --body-file F|status]"
    )


if __name__ == "__main__":
    try:
        main()
    except GhError as e:
        print(f"gh error: {e}", file=sys.stderr)
        sys.exit(2)
