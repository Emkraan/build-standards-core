#!/usr/bin/env python3
# =====================================================================
# tfplan_gate.py
# Purpose: Gated deploys lane: the infrastructure plan gate (opscenter/DESIGN.md section 12.3, item 9).
#          Finds workflow runs of the platform repo waiting on the plan environment. Ordinary
#          pull request plans are approved automatically. Pull requests that change how the
#          infrastructure pipeline works (workflow code, the owners file, the exclusions list, or
#          Terraform constructs that run code or reach the network during plan) are HELD in
#          <state>/tf-review/queue.json for the owner's review in the ops center. The agent is woken
#          only to write a private assessment for a held PR and sha that has none yet.
#
# Wake-gate contract: always exit 0; last stdout line {"wakeAgent": false}
# skips the agent, anything else wakes it with stdout in its prompt.
# FAILS CLOSED: on any gh error nothing is approved; a health counter wakes
# the agent after 3 consecutive failures, then backs off (1h, then 4h).
#
# Config (env):
#   TFGATE_REPO         owner/name of the repo whose runs are gated (required in practice)
#   TFGATE_ENV_NAME     the plan environment name (default terraform-plan)
#   TFGATE_SELF_LOGIN   the owner's login: the author whose PRs get the own PR rules
#   TFGATE_STATE_DIR    queue.json / decisions.jsonl dir (default ~/.opscenter/state/tf-review)
#   TFGATE_CACHE_DIR    health/lock dir (default ~/.opscenter/cache/tfplan-gate)
#   TFGATE_GH_BIN       gh binary (default gh on PATH)
#   TFGATE_STATE_DB     the agent runtime's session database, read only (default ~/.opscenter/state.db)
#   TFGATE_DRY_RUN=1    never POST; log would-approve decisions instead
#   TFGATE_PASS_ONLY=1  the fast pass: no assessment wakes, no health counters, no alerts
# Plug-ins: set_signoff_store(module) replaces the reference sign-off store (signoff_store.py) with one
# that has active(pr, lane=, head_sha=), covers(record, hit) and the OWN and ENGINEER lane names;
# set_privileged_gate(module) turns the privileged lane on (run_pass, set_assessment and
# spawn_secrets_refresh). Without it that lane is off.
# =====================================================================
import datetime as dt
import difflib
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# ---------------------------------------------------------------------
# Policy: allowlist / denylist (edit here)
# ---------------------------------------------------------------------
REPO = os.environ.get("TFGATE_REPO", "owner/repo")
ENV_NAME = os.environ.get("TFGATE_ENV_NAME", "terraform-plan")
ALLOWED_WORKFLOWS = {".github/workflows/terraform-ci.yml", ".github/workflows/terraform-drift.yml"}
ALLOWED_EVENTS = {"pull_request"}
APPROVE_COMMENT = "Approved: no workflow or plan-time execution changes"

# Changed paths that always hold (regex on the repo-relative path).
HOLD_PATHS = [
    (r"^\.github/", "changes .github/ (workflows, actions, scripts can request the environment)"),
    (r"(^|/)CODEOWNERS$", "changes CODEOWNERS"),
    (
        r"^infrastructure/terraform-exclusions\.json$",
        "changes infrastructure/terraform-exclusions.json",
    ),
    (r"\.tf\.json$", "adds/changes a .tf.json file (not used in this repo)"),
    (
        r"(^|/)(\.terraformrc|terraform\.rc|[^/]*\.tfrc)$",
        "changes a Terraform CLI config (provider installation)",
    ),
    # The grafana root plans with a Grafana Admin token (only Admin can read
    # permissions), so PR code there must never get it without a human read.
    (
        r"^infrastructure/terraform/grafana/",
        "changes the grafana root (its plan runs with a Grafana Admin token)",
    ),
]
FUNC_PROVIDERS = re.compile(r"^functions/[^/]+/infra/providers\.tf$")
FUNC_PARTIAL_BACKEND = re.compile(r'^\s*backend\s+"azurerm"\s*\{\s*\}\s*$')
# (2026-10-16), narrow rules. Each one releases a hold ONLY when it can prove the change is
# inert at plan time, and any doubt (read error, odd shape) keeps the hold.
#  1. Backend: a `backend "azurerm"` block added in a .tf file is allowed when it equals the
#     standard read from main (every root on main declares the partial block, the pipeline
#     supplies resource group, account, container and key at init). See backend_standard().
#  2. Grafana root: dashboards.tf and the other plain resource .tf files are allowed when providers,
#     versions, backend, tfvars and the lockfile are untouched and no changed line carries a provider,
#     url, token, auth, backend or data external/http construct.
#  3. .github/scripts/tests/**: allowed when the PR changes no workflow or action AND no workflow in
#     the PR head that requests the terraform-plan environment runs pytest or those paths (directly or
#     through a script or action it calls). See tests_rule_ok().
# (2026-10-16), rule 4: infrastructure/terraform-exclusions.json is allowed when, between the PR's
#     merge base with main and its head, the change ONLY appends new entries of the existing schema. See
#     exclusions_allowed(). Anything else, any parse error and any fetch error keeps the hold.
EXCLUSIONS_PATH = "infrastructure/terraform-exclusions.json"
EXCLUSIONS_RULE = "terraform-exclusions.json"  # substring of the HOLD_PATHS reason
GRAFANA_ROOT = "infrastructure/terraform/grafana/"
GRAFANA_RULE = "grafana root"  # substring of the HOLD_PATHS reason
GRAFANA_RESOURCE_RE = re.compile(r"^infrastructure/terraform/grafana/[^/]+\.tf$")
GRAFANA_NEVER_FILES = {"providers.tf", "versions.tf", "backend.tf", "terraform.tf"}
GRAFANA_LINE_DENY = [
    re.compile(r"^\s*provider\b"),
    re.compile(r"\burl\b"),
    re.compile(r"\btoken\b", re.I),
    re.compile(r"\bauth\b", re.I),
    re.compile(r"\bbackend\b"),
    re.compile(r'\bdata\s+"(external|http)"'),
]
TESTS_PATH = re.compile(r"^\.github/scripts/tests/")
WORKFLOW_PATH = re.compile(r"^\.github/(workflows|actions)/")
TEST_RUNNER_RE = re.compile(
    r"pytest|py\.test|unittest|scripts/tests|conftest|\btox\b|\bnox\b|(?:from|import)\s+tests\b"
)
GH_REF_RE = re.compile(r"\.github/(?:scripts|actions)/[\w./-]+")
# Fingerprints: approvals carry to a new head only for hits whose content is identical.
CARRY_COMMENT = "Approved: no new held changes since the owner's review"

# File types whose ADDED lines are scanned.
SCAN_SUFFIXES = (".tf", ".tf.json", ".hcl")
# Added-line patterns that hold.
DENY_LINE = [
    (r'data\s+"external"', 'data "external"'),
    (r'data\s+"http"', 'data "http"'),
    (r'provider\s+"external"', 'provider "external"'),
    (r'provider\s+"http"', 'provider "http"'),
    (r"hashicorp/external\b", "hashicorp/external"),
    (r"hashicorp/http\b", "hashicorp/http"),
    (r"local-exec", "local-exec"),
    (r"remote-exec", "remote-exec"),
    (r"terraform_remote_state", "terraform_remote_state"),
    (r'\bbackend\s+"', "backend block"),
    (r"^\s*cloud\s*\{", "cloud block"),
    (
        r'source\s*=\s*"(git::|hg::|s3::|gcs::|https?:|github\.com/|bitbucket\.org/)',
        "non-relative module source",
    ),
]
# A `source =` value that is not a relative path is held unless it is one
# of these provider sources (required_providers). Module registry
# addresses (ns/name/provider) are therefore held.
PROVIDER_SOURCE_ALLOW = {
    "hashicorp/azurerm",
    "azure/azapi",
    "hashicorp/azuread",
    "hashicorp/random",
    "hashicorp/time",
}
SOURCE_RE = re.compile(r'^\s*source\s*=\s*"([^"]*)"')
LOCK_PROVIDER_RE = re.compile(r'^\s*provider\s+"([^"]+)"')

# ---------------------------------------------------------------------
HOME = Path.home()
STATE_DIR = Path(os.environ.get("TFGATE_STATE_DIR", HOME / ".opscenter" / "state" / "tf-review"))
CACHE_DIR = Path(os.environ.get("TFGATE_CACHE_DIR", HOME / ".opscenter" / "cache" / "tfplan-gate"))
GH = os.environ.get("TFGATE_GH_BIN", "gh")
DRY_RUN = os.environ.get("TFGATE_DRY_RUN") == "1"
# Fast pass (a scheduler job every 60 s): a scheduler tick can land late and a pass can end past the
# minute, so a "* * * * *" job may still run only every 2 minutes. The fast pass approves, holds, cancels and queues
# exactly like the cron pass, but never stamps assessment wakes (nobody reads its output, so the
# cron pass keeps waking the agent) and never touches the health counters or alerts.
PASS_ONLY = os.environ.get("TFGATE_PASS_ONLY") == "1"
QUEUE = STATE_DIR / "queue.json"
DECISIONS = STATE_DIR / "decisions.jsonl"
HEALTH = CACHE_DIR / "health.json"
MAIN_PROVIDERS = CACHE_DIR / "main-providers.json"
MAIN_BACKENDS = CACHE_DIR / "main-backends.json"  # backend blocks on main, per blob sha
WF_VERDICTS = CACHE_DIR / "head-workflow-verdicts.json"  # tests rule verdict per head .github tree
BACKEND_FILE_NAMES = {"providers.tf", "main.tf", "versions.tf", "backend.tf", "terraform.tf"}
LOCK = CACHE_DIR / "queue.lock"  # shared with set-assessment and the Ops Center server
REWAKE_SECONDS = 1800  # re-wake for a still-unassessed item at most every 30 min
CLEARED_KEEP_DAYS = 14

# a held plan on one of the owner's PRs is parked (no card, no assessment, no
# ping) while something else is still moving the PR, so the owner only see it when the owner's
# approval is the real next step. No timers: the park lifts on the first pass
# (2 min) after the blocker goes away. Never auto-approves anything.
# The do-not-merge label no longer parks: it is a merge hold that no
# automation lifts, so a park on it hid the plan approval indefinitely. A held plan on a do-not-merge PR shows on Needs me like any other.
# A hold label also cancels the AI-review park: the own-PR fixer never works a held PR and the
# The owner's PRs card shows only the label, so nothing would move it or show it (#349, same day).
SELF_LOGIN = os.environ.get("TFGATE_SELF_LOGIN", "owner-login")
HOLD_LABELS = ("do-not-merge", "hold")  # same list as own_pr_merge.hold_labels in the lane policy
AI_REVIEW_CHECK = "ai-review result"
AI_REVIEW_RED = ("failure", "timed_out", "action_required", "startup_failure")
STATE_DB = Path(os.environ.get("TFGATE_STATE_DB", str(HOME / ".opscenter" / "state.db")))
SESSION_MENTION_S = 1800  # the mid-turn session touched the PR in the last 30 min
# NOTHING IS HIDDEN ANY MORE. park_reason() still runs, but its answer is only a note on the
# card (`working`), never a reason to keep the plan off Needs me. Every held plan shows on the
# first gate pass (2 min). This supersedes the parking above.
SUPERSEDED_MIN_AGE_S = 180  # a waiting run this young on a non-head sha gets one more pass

WAITING_RUNS = []  # set by run_pass; reused by the privileged lane
PRIV_HEALTH = CACHE_DIR / "privileged-health.json"

NOW = time.time()
NOW_ISO = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
SILENT = '{"wakeAgent": false}'


class GhError(Exception):
    pass


def gh(args, timeout=60, raw=False):
    try:
        p = subprocess.run([GH] + args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GhError(f"{' '.join(args[:3])}: {e}") from e
    if p.returncode != 0:
        raise GhError(f"{' '.join(args[:3])}: rc={p.returncode} {p.stderr.strip()[:400]}")
    if raw:
        return p.stdout
    try:
        return json.loads(p.stdout) if p.stdout.strip() else None
    except ValueError as e:
        raise GhError(f"{' '.join(args[:3])}: bad json {e}") from e


def gh_paged_list(path):
    """--paginate concatenates arrays; --slurp is not available everywhere, so use jq per item."""
    out = gh(["api", "--paginate", path, "--jq", ".[] | @json"], raw=True)
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


def write_json(p, data):
    p = Path(p)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, p)


def log_decision(rec):
    rec = dict({"ts": NOW_ISO}, **rec)
    with open(DECISIONS, "a") as f:
        f.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------------
# Hold analysis
# ---------------------------------------------------------------------
def parse_diff(text):
    """Return {path: [added lines]} from a unified diff."""
    added, cur = {}, None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*) b/(.*)$", line)
            cur = m.group(2) if m else None
            if cur is not None:
                added.setdefault(cur, [])
            continue
        if cur is None or line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added[cur].append(line[1:])
    return added


def main_providers():
    """Provider addresses present in main's lockfiles (cached per main sha)."""
    sha = gh(["api", f"repos/{REPO}/commits/main", "--jq", ".sha"], raw=True).strip()
    cache = load_json(MAIN_PROVIDERS, {})
    if cache.get("sha") == sha:
        return set(cache.get("providers", []))
    tree = gh(["api", f"repos/{REPO}/git/trees/{sha}?recursive=1"])
    provs = set()
    for t in tree.get("tree", []):
        if t.get("path", "").endswith(".terraform.lock.hcl"):
            txt = gh(
                [
                    "api",
                    f"repos/{REPO}/contents/{t['path']}?ref={sha}",
                    "-H",
                    "Accept: application/vnd.github.raw",
                ],
                raw=True,
            )
            for line in txt.splitlines():
                m = LOCK_PROVIDER_RE.match(line)
                if m:
                    provs.add(m.group(1).lower())
    write_json(MAIN_PROVIDERS, {"sha": sha, "providers": sorted(provs), "at": NOW_ISO})
    return provs


# ---- helpers: backend standard, head workflow reading ----
def parse_diff_full(text):
    """{path: {"added": [...], "removed": [...], "header": [...]}} from a unified diff. Renames are
    reachable under both the old and the new path."""
    out, cur = {}, None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*) b/(.*)$", line)
            if not m:
                cur = None
                continue
            ent = {"added": [], "removed": [], "header": []}
            out[m.group(2)] = ent
            out.setdefault(m.group(1), ent)
            cur = ent
            continue
        if cur is None:
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("@@"):
            continue  # hunk headers carry line numbers: never part of a fingerprint
        if line.startswith("+"):
            cur["added"].append(line[1:].rstrip())
        elif line.startswith("-"):
            cur["removed"].append(line[1:].rstrip())
        elif line.startswith("\\"):
            continue
        elif not line.startswith(" "):
            cur["header"].append(line.rstrip())
    return out


def _fp(rule, path, content):
    return hashlib.sha256(json.dumps([rule, path, content]).encode()).hexdigest()[:24]


def _cfp(path, content):
    """rule-agnostic fingerprint of one file's changed content. The plan card and the policy
    card flag the same file under two rule names, so a sign-off matches them by this."""
    return hashlib.sha256(json.dumps(["file", path, content]).encode()).hexdigest()[:24]


def content_fps(diff):
    """{path: cfp} for every file in a unified diff."""
    full = parse_diff_full(diff)
    return {p: _cfp(p, _file_content(full, p)) for p in full}


class Hits:
    """Ordered hold hits: one per distinct reason, each with a content fingerprint (None when the
    reason cannot be fingerprinted, which never carries forward)."""

    def __init__(self):
        self.order, self.d = [], {}

    def add(self, reason, rule, path, content):
        ent = self.d.get(reason)
        if ent is None:
            ent = self.d[reason] = {"rule": rule, "path": path, "content": [], "ok": True}
            self.order.append(reason)
        if content is None:
            ent["ok"] = False
        else:
            ent["content"].extend(content)

    def out(self):
        res = []
        for r in self.order:
            e = self.d[r]
            res.append(
                {
                    "reason": r,
                    "fp": _fp(e["rule"], e["path"], e["content"]) if e["ok"] else None,
                    "cfp": _cfp(e["path"], e["content"]) if e["ok"] else None,
                    "path": e["path"],
                }
            )
        return res


def _file_content(full, path):
    """Whole-file hit content: the file's added and removed lines (no line numbers, no hunk
    headers). A file with no text lines (binary, mode change) uses its diff header lines."""
    ent = full.get(path)
    if ent is None:
        return None
    lines = ["+" + x for x in ent["added"]] + ["-" + x for x in ent["removed"]]
    return lines if lines else ["#" + x for x in ent["header"]]


def _strip_comment(ln):
    return re.sub(r"(^|\s)(#|//).*$", "", ln)


def _backend_blocks(text):
    """[(type, {attr: raw value})] for every backend block in HCL text."""
    out = []
    clean = "\n".join(_strip_comment(x) for x in text.splitlines())
    for m in re.finditer(r'\bbackend\s+"([^"]+)"\s*\{', clean):
        depth, i = 1, m.end()
        while i < len(clean) and depth:
            depth += {"{": 1, "}": -1}.get(clean[i], 0)
            i += 1
        body = clean[m.end() : i - 1] if depth == 0 else None
        if body is None:
            out.append((m.group(1), None))
            continue
        attrs = {}
        for ln in body.splitlines():
            am = re.match(r"^\s*([A-Za-z_][\w-]*)\s*=\s*(.+?)\s*$", ln)
            if am:
                attrs[am.group(1)] = am.group(2)
        out.append((m.group(1), attrs))
    return out


def backend_standard():
    """The standard backend, read from main. Returns {"type", "attrs" (without key),
    "key": bool (main roots set a key)} or None when main has no single consistent standard.
    Per-path results are cached by blob sha, so a pass reads only files that changed on main."""
    sha = gh(["api", f"repos/{REPO}/commits/main", "--jq", ".sha"], raw=True).strip()
    tree = gh(["api", f"repos/{REPO}/git/trees/{sha}?recursive=1"])
    cache = load_json(MAIN_BACKENDS, {"files": {}})
    files = cache.setdefault("files", {})
    want = {}
    for t in tree.get("tree", []):
        path = t.get("path", "")
        if (
            t.get("type") == "blob"
            and path.endswith(".tf")
            and path.rsplit("/", 1)[-1] in BACKEND_FILE_NAMES
        ):
            want[path] = t["sha"]

    def load(path):
        blob = want[path]
        if files.get(path, {}).get("blob") == blob:
            return path, files[path]
        txt = gh(
            [
                "api",
                f"repos/{REPO}/contents/{path}?ref={sha}",
                "-H",
                "Accept: application/vnd.github.raw",
            ],
            raw=True,
        )
        return path, {"blob": blob, "backends": _backend_blocks(txt)}

    with ThreadPoolExecutor(max_workers=8) as pool:
        got = dict(pool.map(load, sorted(want)))
    cache["files"] = got
    write_json(MAIN_BACKENDS, cache)
    forms, key_seen = set(), set()
    for ent in got.values():
        for typ, attrs in ent["backends"]:
            if attrs is None:
                return None  # a block on main we cannot read: no standard
            rest = {k: v for k, v in attrs.items() if k != "key"}
            forms.add((typ, json.dumps(rest, sort_keys=True)))
            key_seen.add("key" in attrs)
    if len(forms) != 1 or len(key_seen) != 1:
        return None
    typ, rest = next(iter(forms))
    return {"type": typ, "attrs": json.loads(rest), "key": next(iter(key_seen))}


def _root_name(path):
    parts = path.split("/")
    for top in (("functions",), ("apps",), ("infrastructure", "terraform"), ("infrastructure",)):
        if tuple(parts[: len(top)]) == top and len(parts) > len(top):
            return parts[len(top)]
    return None


def backend_line_ok(path, lines, idx, std):
    """True when the backend block starting at lines[idx] (the added lines of path) equals the
    standard: same type, same attributes apart from key, nothing else on its lines, and a key (only
    if main's roots set one) named after this root. A block that does not close inside the added
    lines is unreadable and holds."""
    if not std or not path.endswith(".tf") or not re.match(r'^\s*backend\s+"', lines[idx]):
        return False
    text, depth, opened = [], 0, False
    for ln in lines[idx:]:
        text.append(ln)
        c = _strip_comment(ln)
        depth += c.count("{") - c.count("}")
        opened = opened or "{" in c
        if opened and depth <= 0:
            break
    if not opened or depth != 0:
        return False
    tail = _strip_comment(text[-1]).strip()
    if len(text) == 1:
        if not re.fullmatch(r'backend\s+"[^"]*"\s*\{\s*\}', tail):
            return False
    elif tail != "}":
        return False
    blocks = _backend_blocks("\n".join(text))
    if len(blocks) != 1 or blocks[0][1] is None:
        return False
    typ, attrs = blocks[0]
    if typ != std["type"] or {k: v for k, v in attrs.items() if k != "key"} != std["attrs"]:
        return False
    if "key" not in attrs:
        return not std["key"]
    name = _root_name(path)
    m = re.fullmatch(r'"([^"]+)"', attrs["key"])
    return bool(
        std["key"]
        and name
        and m
        and re.fullmatch(re.escape(name) + r"(/[\w-]+)?\.tfstate", m.group(1))
    )


def grafana_allowed(files, full):
    """rule 2. True when every changed file under the grafana root is a plain resource .tf
    file and no changed line (added or removed) carries a provider, url, token, auth, backend or data
    external/http construct."""
    touched = [p for p in files if p.startswith(GRAFANA_ROOT)]
    if not touched:
        return True
    for p in touched:
        if not GRAFANA_RESOURCE_RE.match(p) or p.rsplit("/", 1)[-1] in GRAFANA_NEVER_FILES:
            return False
        ent = full.get(p)
        if ent is None:
            return False
        for ln in ent["added"] + ent["removed"]:
            code = _strip_comment(ln)
            if any(rx.search(code) for rx in GRAFANA_LINE_DENY):
                return False
    return True


def _excl_pattern_problem(pat, existing):
    """None when a NEW exclusion pattern is narrow enough, else why not. The sweep fnmatch-es each
    pattern against the lowercased ARM id, so the schema is /subscriptions/<sub>/resourcegroups/<rg>/
    providers/<ns>/<type>/<name>. Conservative: the resource type must be literal and the final
    segment needs at least 4 literal characters (existing '.../systemtopics/*' style entries were
    reviewed by hand, a new one that broad waits for me)."""
    if not isinstance(pat, str) or not pat.strip() or pat != pat.strip():
        return "empty or padded pattern"
    if pat != pat.lower():
        return "pattern is not lowercase (the sweep matches lowercased ids)"
    if "**" in pat or "[" in pat or "]" in pat:
        return "pattern uses ** or a character class"
    if not re.fullmatch(r"[\x21-\x7e ]+", pat):
        return "pattern has odd characters"
    if (
        not pat.startswith("/subscriptions/")
        or "/resourcegroups/" not in pat
        or "/providers/" not in pat
    ):
        return "pattern is not a subscription, resource group and provider scoped id"
    tail = pat.rsplit("/providers/", 1)[1].split("/")
    if (
        len(tail) < 3
        or not re.fullmatch(r"microsoft\.[a-z0-9.]+", tail[0])
        or not re.fullmatch(r"[a-z0-9.]+", tail[1])
    ):
        return "provider namespace or resource type is not literal"
    literal = re.sub(r"[*?]", "", tail[-1])
    if len(literal) < 4:
        return "final segment is too broad"
    # would it match every existing entry (read as a sample id)? then it excludes everything
    samples = [e["pattern"] for e in existing]
    if len(samples) >= 2 and all(fnmatch.fnmatchcase(x, pat) for x in samples):
        return "pattern matches every existing entry"
    return None


def exclusions_allowed(head_sha):
    """rule 4. (ok, why). True only when head = base + new entries of the same schema, with
    every base entry still present, unchanged and in order, and every other top-level key unchanged.
    Any fetch or parse problem, or any doubt, is (False, why)."""
    if not head_sha:
        return False, "no head sha to read the exclusions file from"
    try:
        cmp_ = gh(["api", f"repos/{REPO}/compare/main...{head_sha}?per_page=1"]) or {}
        base_sha = (cmp_.get("merge_base_commit") or {}).get("sha")
        if not base_sha or not re.fullmatch(r"[0-9a-f]{40}", base_sha):
            return False, "no merge base with main"
        base = json.loads(_raw(EXCLUSIONS_PATH, base_sha))
        head = json.loads(_raw(EXCLUSIONS_PATH, head_sha))
    except (GhError, ValueError, TypeError, AttributeError, KeyError) as e:
        return False, f"could not read the exclusions file at base and head: {e}"
    try:
        if not isinstance(base, dict) or not isinstance(head, dict):
            return False, "exclusions file is not an object"
        if set(base) != set(head) or "exclusions" not in base:
            return False, "top-level keys changed"
        for k in base:
            if k != "exclusions" and base[k] != head[k]:
                return False, f"top-level key {k} changed"
        b, h = base["exclusions"], head["exclusions"]
        if not isinstance(b, list) or not isinstance(h, list):
            return False, "exclusions is not a list"

        def shape_ok(e):
            return (
                isinstance(e, dict)
                and set(e) == {"pattern", "reason"}
                and all(isinstance(e[k], str) for k in e)
                and e["reason"].strip() != ""
            )

        if not all(
            isinstance(e, dict)
            and set(e) == {"pattern", "reason"}
            and all(isinstance(e[k], str) for k in e)
            for e in b
        ):
            return False, "existing entries do not share one schema"
        # every base entry must survive unchanged, in order (subsequence), the rest are the additions
        added, i = [], 0
        for e in h:
            if i < len(b) and e == b[i]:
                i += 1
            else:
                added.append(e)
        if i != len(b):
            return False, "an existing entry was removed, edited or reordered"
        if len(h) == len(b):
            return False, "no new entries"
        seen = {e["pattern"] for e in b}
        for e in added:
            if not shape_ok(e):
                return False, "new entry does not match the existing schema"
            if e["pattern"] in seen:
                return False, "new entry repeats an existing pattern"
            seen.add(e["pattern"])
            why = _excl_pattern_problem(e["pattern"], b)
            if why:
                return False, f"new entry pattern rejected: {why}"
        return True, f"{len(added)} new entries appended"
    except (KeyError, TypeError, AttributeError, re.error) as e:
        return False, f"could not judge the exclusions change: {e}"


def _job_blocks(text):
    """[(job name, [lines])] from a workflow file, by indentation (no YAML parser needed)."""
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines) and not re.match(r"^jobs:\s*(#.*)?$", lines[i]):
        i += 1
    i += 1
    indent, cur = None, None
    for ln in lines[i:]:
        if not ln.strip() or ln.lstrip().startswith("#"):
            if cur:
                cur[1].append(ln)
            continue
        ind = len(ln) - len(ln.lstrip(" "))
        if ind == 0:
            break
        if indent is None:
            indent = ind
        if ind == indent:
            m = re.match(r"^\s*([\w.-]+)\s*:", ln)
            if not m:
                return None
            cur = (m.group(1), [])
            out.append(cur)
        elif cur:
            cur[1].append(ln)
    return out, indent


def workflow_env_jobs(text):
    """For one workflow file: ([(job, requests_env, block_text, nonlocal_uses)], parsed_ok)."""
    pj = _job_blocks(text)
    if pj is None:
        return [], False
    jobs, indent = pj
    if not jobs and re.search(r"\benvironment\b", text):
        return [], False
    res = []
    for name, blk in jobs:
        pad = " " * ((indent or 2) + 2)
        envtxt, grab = [], False
        for ln in blk:
            if re.match(r"^" + pad + r"environment\s*:", ln):
                envtxt, grab = [ln], True
                continue
            if grab:
                ind = len(ln) - len(ln.lstrip(" "))
                if ln.strip() and ind <= len(pad):
                    grab = False
                else:
                    envtxt.append(ln)
        env = "\n".join(envtxt)
        requests = bool(env) and ("terraform-plan" in env or "${{" in env)
        uses = [
            m.group(1) for ln in blk for m in [re.match(r"^" + pad + r"uses\s*:\s*(\S+)", ln)] if m
        ]
        nonlocal_uses = any(not u.startswith("./") for u in uses)
        res.append((name, requests, "\n".join(blk), nonlocal_uses))
    return res, True


def _raw(path, sha):
    return gh(
        [
            "api",
            f"repos/{REPO}/contents/{path}?ref={sha}",
            "-H",
            "Accept: application/vnd.github.raw",
        ],
        raw=True,
    )


def tests_rule_ok(files, head_sha):
    """rule 3. (ok, why). Unsure -> (False, why)."""
    if not head_sha:
        return False, "no head sha to read workflows from"
    if any(WORKFLOW_PATH.match(p) for p in files):
        return False, "PR changes a workflow or action"
    try:
        top = gh(["api", f"repos/{REPO}/contents/.github?ref={head_sha}"]) or []
        key = json.dumps(
            sorted(
                (e["name"], e["sha"])
                for e in top
                if e.get("name") in ("workflows", "scripts", "actions")
            )
        )
        cache = load_json(WF_VERDICTS, {})
        if key in cache:
            v = cache[key]
            return bool(v["ok"]), v["why"]
        ok, why = _head_workflows_verdict(head_sha)
        cache[key] = {"ok": ok, "why": why, "at": NOW_ISO}
        if len(cache) > 60:
            for k in sorted(cache, key=lambda k: cache[k].get("at", ""))[: len(cache) - 60]:
                del cache[k]
        write_json(WF_VERDICTS, cache)
        return ok, why
    except (GhError, KeyError, TypeError, ValueError, OSError) as e:
        return False, f"could not read head workflows: {e}"


def _head_workflows_verdict(sha):
    listing = gh(["api", f"repos/{REPO}/contents/.github/workflows?ref={sha}"]) or []
    names = [
        e["path"]
        for e in listing
        if e.get("type") == "file" and e["name"].endswith((".yml", ".yaml"))
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        texts = list(pool.map(lambda p: _raw(p, sha), names))
    refs = set()
    for path, text in zip(names, texts):
        jobs, parsed = workflow_env_jobs(text)
        if not parsed:
            return False, f"cannot parse {path}"
        for name, requests, blk, nonlocal_uses in jobs:
            if nonlocal_uses:
                return False, f"{path} job {name} calls an external workflow"
            if not requests:
                continue
            if TEST_RUNNER_RE.search(blk):
                return False, f"{path} job {name} requests {ENV_NAME} and runs tests"
            refs.update(m.group(0).rstrip(".,;:)\"'") for m in GH_REF_RE.finditer(blk))
    for ref in sorted(refs):
        cands = (
            [ref]
            if re.search(r"\.[A-Za-z0-9]+$", ref)
            else [ref.rstrip("/") + "/action.yml", ref.rstrip("/") + "/action.yaml"]
        )
        txt = None
        for c in cands:
            try:
                txt = _raw(c, sha)
                break
            except GhError:
                continue
        if txt is None:
            return False, f"cannot read {ref} used by a {ENV_NAME} job"
        if TEST_RUNNER_RE.search(txt):
            return False, f"{ref} (used by a {ENV_NAME} job) runs tests"
    return True, f"no {ENV_NAME} job runs tests ({len(names)} workflows read)"


# ---------------------------------------------------------------------
# own PRs only. A .github/ edit is held when it can matter for security and released when it
# is plain script, prompt, test or workflow-step logic. Engineer PRs never reach this code (own=False).
# ---------------------------------------------------------------------
GH_NEVER = re.compile(
    r"(^|/)CODEOWNERS$|^\.github/terraform-roots\.json$|^\.github/forbidden-patterns\.json$"
    r"|^\.github/dependabot\.ya?ml$|terraform-exclusions\.json$"
)
GH_RELEASABLE = re.compile(
    r"^\.github/(workflows/[^/]+\.ya?ml|actions/.+|scripts/.+|prompts/.+|ISSUE_TEMPLATE/.+|pull_request_template\.md|[^/]+\.md)$"
)
GH_WORKFLOW_FILE = re.compile(r"^\.github/workflows/[^/]+\.ya?ml$")
GH_ACTION_FILE = re.compile(r"^\.github/actions/.+")
GH_SENSITIVE = [
    (re.compile(r"^\s*-?\s*permissions\s*:"), "permissions"),
    (re.compile(r"\bid-token\b"), "id-token"),
    (re.compile(r"\benvironment\s*:"), "environment key"),
    (re.compile(r"\bsecrets\s*(\.|\[)|\bsecrets\s*:\s*inherit"), "secrets reference"),
    (
        re.compile(r"pull_request_target|workflow_run"),
        "pull_request_target or workflow_run trigger",
    ),
]
GH_USES_RE = re.compile(r"^\s*-?\s*uses\s*:\s*['\"]?([^\s'\"#]+)")
GH_SCRIPT_TEXT = re.compile(r"\.(py|sh|bash|ps1|js|mjs|ts|rb|yml|yaml|json|md|txt)$", re.I)
GH_IMPORTS_RE = re.compile(
    r"(^|\s)(import|from|require|source)\s|\brequire\(|\bdirname\b|__file__|\$PSScriptRoot|\bBASH_SOURCE\b|^\s*\.\s+\S",
    re.M,
)
_MAIN_USES = {}
_SURFACE = {}


def _main_uses():
    """The set of `uses:` values in main's workflows and actions (memo per main sha). Raises GhError."""
    sha = gh(["api", f"repos/{REPO}/commits/main", "--jq", ".sha"], raw=True).strip()
    if sha in _MAIN_USES:
        return _MAIN_USES[sha]
    names = []
    for d in ("workflows",):
        for e in gh(["api", f"repos/{REPO}/contents/.github/{d}?ref={sha}"]) or []:
            if e.get("type") == "file" and e["name"].endswith((".yml", ".yaml")):
                names.append(e["path"])
    uses = set()
    for path in names:
        for ln in _raw(path, sha).splitlines():
            m = GH_USES_RE.match(ln)
            if m:
                uses.add(m.group(1))
    _MAIN_USES.clear()
    _MAIN_USES[sha] = uses
    return uses


def _uses_ok(val, removed_uses):
    """One added `uses:` value. Local paths are fine. A remote one needs a full sha pin and an owner main
    already uses, or the exact same value already on main or on a removed line of this diff."""
    if val.startswith("./"):
        return True, ""
    if val.startswith("docker://") or "@" not in val:
        return False, f"uses {val} is not a sha-pinned action"
    if val in removed_uses:
        return True, ""
    known = _main_uses()
    if val in known:
        return True, ""
    ref = val.rsplit("@", 1)[1]
    owner = val.split("/", 1)[0].lower()
    if not re.fullmatch(r"[0-9a-f]{40}", ref):
        return False, f"uses {val} is not sha-pinned"
    if owner not in {u.split("/", 1)[0].lower() for u in known if not u.startswith("./")}:
        return False, f"uses {val} is from a new owner"
    return True, ""


def _env_surface(head_sha):
    """(ok, why, texts, env_workflows): everything a job that requests terraform-plan can run, as far as it
    can be read from the head tree. texts is {path: text} for the referenced scripts and actions and
    the files they reference in turn (3 levels). Any read or parse problem is (False, why, ...)."""
    if head_sha in _SURFACE:
        return _SURFACE[head_sha]
    out = (False, "unread", {}, [])
    try:
        listing = gh(["api", f"repos/{REPO}/contents/.github/workflows?ref={head_sha}"]) or []
        names = [
            e["path"]
            for e in listing
            if e.get("type") == "file" and e["name"].endswith((".yml", ".yaml"))
        ]
        with ThreadPoolExecutor(max_workers=8) as pool:
            texts = list(pool.map(lambda p: _raw(p, head_sha), names))
        refs, env_wfs, blocks = set(), [], []
        for path, text in zip(names, texts):
            jobs, parsed = workflow_env_jobs(text)
            if not parsed:
                out = (False, f"cannot parse {path}", {}, [])
                raise StopIteration
            for _name, requests, blk, _nonlocal_uses in jobs:
                if requests:
                    env_wfs.append(path)
                    blocks.append(blk)
                    refs.update(m.group(0).rstrip(".,;:)\"'") for m in GH_REF_RE.finditer(blk))
        got, queue_ = {}, sorted(refs)
        for _depth in range(3):
            nxt = []
            for ref in queue_:
                if ref in got:
                    continue
                if re.search(r"\.[A-Za-z0-9]+$", ref):
                    cands = [ref]
                else:
                    cands = [ref.rstrip("/") + "/action.yml", ref.rstrip("/") + "/action.yaml"]
                txt = None
                for c in cands:
                    try:
                        txt = _raw(c, head_sha)
                        got[c] = txt
                        got.setdefault(ref, txt)
                        break
                    except GhError:
                        continue
                if txt is None:
                    out = (False, f"cannot read {ref} used by a {ENV_NAME} job", {}, [])
                    raise StopIteration
                nxt += [m.group(0).rstrip(".,;:)\"'") for m in GH_REF_RE.finditer(txt)]
            queue_ = sorted(set(nxt) - set(got))
        if queue_:
            out = (False, "script references nest deeper than the owner can follow", {}, [])
            raise StopIteration
        out = (True, "read", got, sorted(set(env_wfs)))
        out[2]["__blocks__"] = "\n".join(blocks)
    except StopIteration:
        pass
    except (GhError, KeyError, TypeError, ValueError, OSError) as e:
        out = (False, f"could not read head workflows: {e}", {}, [])
    if len(_SURFACE) > 40:
        _SURFACE.clear()
    _SURFACE[head_sha] = out
    return out


def _surface_touches(path, head_sha):
    """(touches, why). True when a job that requests terraform-plan could run or read this file."""
    ok, why, texts, env_wfs = _env_surface(head_sha)
    if not ok:
        return True, why
    base, d = path.rsplit("/", 1)[-1], path.rsplit("/", 1)[0]
    stem = re.sub(r"\.[^.]+$", "", base)
    if path in env_wfs:
        return True, "this workflow has a job that requests terraform-plan"
    blocks = texts.get("__blocks__", "")
    for name, txt in texts.items():
        if name == "__blocks__":
            continue
        if (
            name == path
            or path.startswith(name.rstrip("/") + "/")
            or (name.rstrip("/") + "/").startswith(path.rstrip("/") + "/")
        ):
            return True, f"a terraform-plan job runs {name}"
        if "/" in name and name.rsplit("/", 1)[0] == d and GH_IMPORTS_RE.search(txt):
            return (
                True,
                f"{path} sits beside {name}, which a terraform-plan job runs and which can load sibling files",
            )
        if stem and re.search(r"(?<![\w-])" + re.escape(stem) + r"(?![\w-])", txt):
            return True, f"a script a terraform-plan job runs mentions {base}"
    if stem and re.search(r"(?<![\w-])" + re.escape(stem) + r"(?![\w-])", blocks):
        return True, f"a terraform-plan job mentions {base}"
    if path in blocks:
        return True, "a terraform-plan job mentions this file"
    return False, ""


def github_release(path, full, mode, head_sha=None):
    """(released, why) for one changed .github/ path of one of the owner's PRs. mode 'policy' is the
    engine's github-dir rule, 'tfplan' is the plan-environment matcher, which also has to prove the file
    cannot change what runs in a job that requests terraform-plan. Fail closed on any doubt."""
    try:
        if GH_NEVER.search(path) or not GH_RELEASABLE.match(path):
            return False, "a security-relevant or unrecognised .github/ file"
        ent = full.get(path)
        if not ent:
            return False, "no diff for this file"
        hdr = " ".join(ent["header"])
        if re.search(
            r"new file mode|deleted file mode|rename (from|to)|old mode|Binary files|GIT binary patch",
            hdr,
        ) and (
            GH_WORKFLOW_FILE.match(path)
            or GH_ACTION_FILE.match(path)
            or "Binary" in hdr
            or "binary" in hdr
        ):
            return False, "adds, removes, renames or retypes a workflow or action"
        if not ent["added"] and not ent["removed"]:
            return False, "no text change the owner can read"
        lines = ent["added"] + ent["removed"]
        for ln in lines:
            for rx, what in GH_SENSITIVE:
                if rx.search(ln):
                    return False, f"touches {what}"
        yml = bool(GH_WORKFLOW_FILE.match(path) or GH_ACTION_FILE.match(path))
        if yml:
            removed_uses = {
                m.group(1) for ln in ent["removed"] for m in [GH_USES_RE.match(ln)] if m
            }
            for ln in ent["added"]:
                m = GH_USES_RE.match(ln)
                if m:
                    ok, why = _uses_ok(m.group(1), removed_uses)
                    if not ok:
                        return False, why
        if mode == "tfplan":
            if not head_sha:
                return False, "no head sha to read workflows from"
            if GH_WORKFLOW_FILE.match(path):
                text = _raw(path, head_sha)
                jobs, parsed = workflow_env_jobs(text)
                if not parsed:
                    return False, f"cannot parse {path}"
                if any(req or nl for _n, req, _b, nl in jobs):
                    return False, "a job requests an environment or calls an external workflow"
            touched, why = _surface_touches(path, head_sha)
            if touched:
                return False, why
        return True, "plain script, prompt, test or step logic"
    except (GhError, KeyError, TypeError, ValueError, OSError) as e:
        return False, f"could not verify: {e}"


# ---------------------------------------------------------------------
# own PRs only. A .github/ file the owner already approved is not asked again when the DELTA since the owner's
# last manual look adds or removes no sensitive line. Fail closed on any doubt.
# ---------------------------------------------------------------------
DELTA_MAX_BYTES = 1000000


def _delta_text(path, sha):
    """(text or None, existed). Missing at a sha that exists is (None, False). Any other read problem
    raises, so the caller holds."""
    try:
        return _raw(path, sha), True
    except GhError as e:
        if re.search(r"HTTP 404|Not Found", str(e), re.I):
            return None, False
        raise


def delta_release(path, base_sha, head_sha):
    """(released, why): the change to one .github/ file between base_sha (the head of the owner's latest
    MANUAL approval or sign-off) and head_sha adds or removes nothing sensitive. Same sensitive-line and
    uses: rules as github_release, applied to the delta only. Holds a security file, a new or deleted
    workflow or action, a binary or oversized file and every read error."""
    try:
        if not base_sha or not head_sha or base_sha == head_sha:
            return False, "no earlier approved head to compare with"
        if GH_NEVER.search(path) or not GH_RELEASABLE.match(path) or ".." in path.split("/"):
            return False, "a security-relevant or unrecognised .github/ file"
        # the base commit must be readable, or a missing file could just mean the commit is gone
        gh(["api", f"repos/{REPO}/commits/{base_sha}", "--jq", ".sha"], raw=True)
        old, old_ok = _delta_text(path, base_sha)
        new, new_ok = _delta_text(path, head_sha)
        yml = bool(GH_WORKFLOW_FILE.match(path) or GH_ACTION_FILE.match(path))
        if not new_ok:
            return False, "the file is deleted at this head"
        if not old_ok and yml:
            return False, "a new workflow or action file"
        old = old or ""
        for t in (old, new):
            if "\x00" in t or len(t) > DELTA_MAX_BYTES:
                return False, "binary or oversized file"
        if old == new:
            return True, "byte-identical to the approved head"
        a = [x.rstrip() for x in old.splitlines()]
        b = [x.rstrip() for x in new.splitlines()]
        added, removed = [], []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, a, b, autojunk=False
        ).get_opcodes():
            if tag in ("replace", "delete"):
                removed += a[i1:i2]
            if tag in ("replace", "insert"):
                added += b[j1:j2]
        if not added and not removed:
            return True, "whitespace only"
        for ln in added + removed:
            for rx, what in GH_SENSITIVE:
                if rx.search(ln):
                    # In a plain script a bare `secrets.x` is prose or a module name (a comment naming
                    # secrets.tf, Python's secrets module). Only a workflow expression is a GitHub
                    # secrets reference there, so a script line needs the `${{` to count.
                    if what == "secrets reference" and not yml and "${{" not in ln:
                        continue
                    return False, f"the change touches {what}"
        if yml:
            removed_uses = {m.group(1) for ln in removed for m in [GH_USES_RE.match(ln)] if m}
            for ln in added:
                m = GH_USES_RE.match(ln)
                if m:
                    ok, why = _uses_ok(m.group(1), removed_uses)
                    if not ok:
                        return False, why
        return True, f"{len(added)} line(s) added and {len(removed)} removed, none sensitive"
    except Exception as e:  # noqa: BLE001 - fail closed
        return False, f"could not verify: {e}"


def _epoch_of(stamp):
    try:
        return (
            dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
            .replace(tzinfo=dt.timezone.utc)
            .timestamp()
        )
    except (TypeError, ValueError):
        return 0.0


def manual_base(items, pr_num, sha):
    """the head of the owner's latest MANUAL approval or sign-off on this PR (never a carried head and
    never the current head), or None. A later rejection of the PR voids it. Deltas are therefore
    cumulative since the owner's last real look and cannot be chained."""
    cands = []
    rejected = 0.0
    for it in items.values():
        if it.get("pr") != pr_num:
            continue
        ts = _epoch_of(it.get("decided_at"))
        if (
            it.get("approval_source") == "manual"
            and it.get("approved_fps")
            and it.get("head_sha") not in (None, sha)
        ):
            cands.append((ts, it["head_sha"]))
        if it.get("status") == "rejected":
            rejected = max(rejected, ts)
    so = load_signoff()
    rec = so.active(pr_num, lane=so.OWN)
    if rec and rec.get("head_sha") and rec["head_sha"] != sha and not rec.get("revoked"):
        cands.append((_epoch_of(rec.get("signed_at")), rec["head_sha"]))
    if not cands:
        return None
    ts, base = max(cands)
    return None if rejected > ts else base


def is_github_path_hit(h):
    return bool(
        h.get("fp")
        and str(h.get("path") or "").startswith(".github/")
        and str(h.get("reason") or "").startswith("changes .github/")
    )


def delta_carry(pr_num, author, head_sha, new_hits, base_sha):
    """(paths or None, why). The owner's own PR only. Carries only when EVERY uncovered hit is a .github/
    path-rule hit whose file delta since base_sha passes delta_release. Any other kind of hit holds."""
    if author != SELF_LOGIN or not new_hits or not base_sha or base_sha == head_sha:
        return None, "not eligible"
    paths = []
    for h in new_hits:
        if not is_github_path_hit(h):
            return None, f"hit is not a .github file rule: {h.get('reason')}"
        ok, why = delta_release(h["path"], base_sha, head_sha)
        if not ok:
            return None, f"{h['path']}: {why}"
        paths.append(h["path"])
    return sorted(set(paths)), "ok"


# ---------------------------------------------------------------------
# (2026-10-22): any PR. A .github/scripts Python file whose change between the merge base and
# the head touches only comments and docstrings runs exactly the same code, so it cannot change what a
# terraform-plan job executes. Proven by comparing the AST of both versions with docstrings removed.
# Holds a new or deleted file, a shebang or encoding line change, a script that can read its own source
# or docstrings, any parse error (including syntax newer than this interpreter) and any read error.
# ---------------------------------------------------------------------
GH_PY_SCRIPT = re.compile(r"^\.github/scripts/(?:[^/]+/)*[^/]+\.py$")
PY_SELF_READ = re.compile(
    r"__doc__|\bgetdoc\b|\bgetsource|\bgetcomments\b|\blinecache\b|__loader__|\btokenize\b"
    r"|\bopen\(\s*__file__|Path\(\s*__file__\s*\)\s*\.\s*(read_text|read_bytes|open)\b"
)
PY_DOC_HELP = re.compile(r"\b(description|epilog|usage)\s*=\s*__doc__\b")


def _py_shape(text):
    """ast.dump of the module with every docstring removed. Comments never reach the AST, and the dump
    carries no line numbers. Raises SyntaxError or ValueError on code this interpreter cannot parse."""
    import ast

    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:]
    return ast.dump(tree)


def comment_only_release(path, head_sha):
    """(released, why) for one changed .github/scripts/*.py path. Fail closed on any doubt."""
    try:
        if not head_sha or not GH_PY_SCRIPT.match(path) or ".." in path.split("/"):
            return False, "not a .github/scripts Python file"
        cmp_ = gh(["api", f"repos/{REPO}/compare/main...{head_sha}?per_page=1"]) or {}
        base_sha = (cmp_.get("merge_base_commit") or {}).get("sha")
        if not base_sha or base_sha == head_sha:
            return False, "no merge base to compare with"
        old, old_ok = _delta_text(path, base_sha)
        new, new_ok = _delta_text(path, head_sha)
        if not old_ok or not new_ok:
            return False, "the file is new or deleted"
        for t in (old, new):
            if "\x00" in t or len(t) > DELTA_MAX_BYTES:
                return False, "binary or oversized file"
        if old == new:
            return False, "no change the owner can see between the merge base and the head"
        # argparse help text (description=__doc__) only prints the docstring, it never runs it.
        if any(PY_SELF_READ.search(PY_DOC_HELP.sub("", t)) for t in (old, new)):
            return False, "the script can read its own source or docstrings"

        def header(t):
            return [ln for ln in t.splitlines()[:2] if ln.startswith("#")]

        if header(old) != header(new):
            return False, "changes the shebang or encoding line"
        if _py_shape(old) != _py_shape(new):
            return False, "changes code, not only comments or docstrings"
        return True, "comments and docstrings only"
    except Exception as e:  # noqa: BLE001 - any failure keeps the hold (fail closed)
        return False, f"could not verify: {e}"


# ---- hold analysis ----
def assess_pr_detail(pr_num, head_sha=None, own=False):
    """Return (files, hits). hits = [{"reason", "fp"}]. Raises GhError on fetch failure."""
    files = []
    for f in gh_paged_list(f"repos/{REPO}/pulls/{pr_num}/files?per_page=100"):
        files.append(f["filename"])
        if f.get("previous_filename"):
            files.append(f["previous_filename"])
    pre = []
    if len(files) >= 3000:
        pre.append("file list truncated at 3000 (cannot verify)")
    try:
        diff = gh(["pr", "diff", str(pr_num), "-R", REPO], timeout=120, raw=True)
    except GhError as e:
        if re.search(r"too large|406|maximum number of (lines|files)", str(e), re.I):
            rs = pre + path_reasons(files) + ["diff too large to verify"]
            return sorted(set(files)), [{"reason": r, "fp": None} for r in rs]
        raise
    if not head_sha and (
        own
        or any(TESTS_PATH.match(p) or p == EXCLUSIONS_PATH or GH_PY_SCRIPT.match(p) for p in files)
    ):
        head_sha = (gh(["api", f"repos/{REPO}/pulls/{pr_num}"]) or {}).get("head", {}).get("sha")
    return sorted(set(files)), [{"reason": r, "fp": None} for r in pre] + assess_hits(
        files, diff, head_sha, own
    )


def assess_pr(pr_num):
    """Return (files, reasons). Raises GhError on fetch failure. Signature kept for the
    review engine."""
    files, hits = assess_pr_detail(pr_num)
    return files, [h["reason"] for h in hits]


def path_reasons(files):
    out = []
    for path in files:
        for rx, why in HOLD_PATHS:
            if re.search(rx, path):
                out.append(f"{why}: {path}")
    return out


def assess_diff(files, diff, head_sha=None):
    """Hold reasons for a file list and a unified diff. Shared by assess_pr and the local
    pre-PR check (pr_preflight.py), so both apply exactly the same rules. Without a head_sha the
    tests rule cannot read the head workflows and stays held."""
    return [h["reason"] for h in assess_hits(files, diff, head_sha)]


def assess_hits(files, diff, head_sha=None, own=False):
    hits = Hits()
    full = parse_diff_full(diff)
    graf_ok = grafana_allowed(files, full)
    tests_ok = None
    excl_ok = None
    for path in files:
        for i, (rx, why) in enumerate(HOLD_PATHS):
            if not re.search(rx, path):
                continue
            if GRAFANA_RULE in why and graf_ok:
                continue
            if why.startswith("changes .github/") and TESTS_PATH.match(path):
                if tests_ok is None:
                    tests_ok = tests_rule_ok(files, head_sha)[0]
                if tests_ok:
                    continue
            if (
                own
                and why.startswith("changes .github/")
                and github_release(path, full, "tfplan", head_sha)[0]
            ):
                continue
            if (
                why.startswith("changes .github/")
                and GH_PY_SCRIPT.match(path)
                and comment_only_release(path, head_sha)[0]
            ):
                continue
            if EXCLUSIONS_RULE in why:
                if excl_ok is None:
                    excl_ok = exclusions_allowed(head_sha)[0]
                if excl_ok:
                    continue
            hits.add(f"{why}: {path}", f"path{i}", path, _file_content(full, path))
    added = parse_diff(diff)
    need_main, std, std_read = False, None, False
    for path, lines in added.items():
        if not path.endswith(SCAN_SUFFIXES):
            continue
        for idx, ln in enumerate(lines):
            for rx, why in DENY_LINE:
                if re.search(rx, ln):
                    if why == "backend block":
                        # The standard empty partial backend of a function app root
                        # is routine (the pipeline fills it from deploy.json). any root whose
                        # added backend block equals main's standard is the same thing.
                        if FUNC_PARTIAL_BACKEND.match(ln) and FUNC_PROVIDERS.match(path):
                            continue
                        if not std_read:
                            std, std_read = backend_standard(), True
                        if backend_line_ok(path, lines, idx, std):
                            continue
                    hits.add(f"{why} added in {path}", f"line:{why}", path, [ln.strip()])
            m = SOURCE_RE.match(ln)
            if m and not path.endswith(".terraform.lock.hcl"):
                val = m.group(1).strip()
                if (
                    not (val.startswith("./") or val.startswith("../"))
                    and val.lower() not in PROVIDER_SOURCE_ALLOW
                ):
                    hits.add(
                        f'non-relative source "{val}" added in {path}',
                        "line:source",
                        path,
                        [ln.strip()],
                    )
            if path.endswith(".terraform.lock.hcl") and LOCK_PROVIDER_RE.match(ln):
                need_main = True
    if need_main:
        known = main_providers()
        for path, lines in added.items():
            if not path.endswith(".terraform.lock.hcl"):
                continue
            for ln in lines:
                m = LOCK_PROVIDER_RE.match(ln)
                if m and m.group(1).lower() not in known:
                    hits.add(
                        f'lockfile adds provider not on main "{m.group(1)}" in {path}',
                        "lockfile-provider",
                        path,
                        _file_content(full, path),
                    )
    return hits.out()


# ---------------------------------------------------------------------
# an approval of an earlier head carries to a new head with no new held content
# ---------------------------------------------------------------------
def approved_fp_map(items, pr_num):
    """{fp: approved head sha} for one PR from the owner's manual decisions only. Auto approvals are never
    queue items and carried approvals store no fingerprints, so neither can be a source. For each
    fingerprint the latest decision wins and a tie goes to the rejection."""
    events = {}  # fp -> (decided_at, rank, sha)
    for it in items.values():
        if it.get("pr") != pr_num:
            continue
        ts = it.get("decided_at") or ""
        if it.get("approval_source") == "manual":
            for fp in it.get("approved_fps") or []:
                ev = (ts, 0, it.get("head_sha"))
                if fp not in events or ev[:2] > events[fp][:2]:
                    events[fp] = ev
        for fp in it.get("rejected_fps") or []:
            ev = (ts, 1, it.get("head_sha"))
            if fp not in events or ev[:2] >= events[fp][:2]:
                events[fp] = ev
    return {fp: ev[2] for fp, ev in events.items() if ev[1] == 0}


def carry_decision(items, pr_num, hits):
    """(carried_from_sha or None, new_hits). Carries only when there is at least one hit, every
    hit has a fingerprint and every fingerprint was approved by me on an earlier head."""
    amap = approved_fp_map(items, pr_num)
    new = [h for h in hits if not h.get("fp") or h["fp"] not in amap]
    if not hits or new:
        return None, new
    src = max(
        (
            it
            for it in items.values()
            if it.get("pr") == pr_num
            and it.get("approval_source") == "manual"
            and set(it.get("approved_fps") or []) & {h["fp"] for h in hits}
        ),
        key=lambda it: it.get("decided_at") or "",
        default=None,
    )
    return (src or {}).get("head_sha") or next(iter(amap.values())), []


def last_approved_head(items, pr_num, head_sha):
    """the head of the owner's latest manual approval on this PR (never the current head)."""
    best = None
    for it in items.values():
        if (
            it.get("pr") == pr_num
            and it.get("approval_source") == "manual"
            and it.get("approved_fps")
            and it.get("head_sha")
            and it.get("head_sha") != head_sha
            and (best is None or (it.get("decided_at") or "") > (best.get("decided_at") or ""))
        ):
            best = it
    return (best or {}).get("head_sha")


def held_delta(base_sha, head_sha, paths):
    """what changed in the newly held files between the owner's approved head and this head.
    Display only, it never decides anything. Raises GhError on a failed read (the caller keeps the
    compare link and retries next pass)."""
    url = f"https://github.com/{REPO}/compare/{base_sha}...{head_sha}"
    data = gh(["api", f"repos/{REPO}/compare/{base_sha}...{head_sha}"]) or {}
    listed = data.get("files") or []
    by = {}
    for f in listed:
        by[f.get("filename")] = f
        if f.get("previous_filename"):
            by.setdefault(f["previous_filename"], f)
    truncated = len(listed) >= 300  # the compare API lists at most 300 files
    out = {
        "base_sha": base_sha,
        "head_sha": head_sha,
        "paths": sorted(paths),
        "compare_url": url,
        "files": [],
        "unchanged": [],
        "unknown": [],
    }
    for path in sorted(paths):
        f = by.get(path)
        if f:
            out["files"].append(
                {
                    "path": path,
                    "status": f.get("status"),
                    "additions": f.get("additions", 0),
                    "deletions": f.get("deletions", 0),
                    "url": url + "#diff-" + hashlib.sha256(path.encode()).hexdigest(),
                }
            )
        elif truncated:
            out["unknown"].append(path)
        else:
            out["unchanged"].append(path)
    return out


# ---------------------------------------------------------------------
# Main pass
# ---------------------------------------------------------------------
RECENT_RUN_WINDOW_S = 6 * 3600  # how far back queue items are re-read directly


_signoff = None
_privileged = None


def set_signoff_store(mod):
    """Plug in the review engine's shared sign-off store (see the header)."""
    global _signoff
    _signoff = mod


def set_privileged_gate(mod):
    """Plug in the privileged lane (governance, identity and destroy plans, never auto approved)."""
    global _privileged
    _privileged = mod


def load_signoff():
    """The plugged in sign-off store, else the reference store next to this file."""
    if _signoff is not None:
        return _signoff
    import signoff_store

    return signoff_store


def signoff_for(pr_num, author, sha):
    """The owner's live sign-off that applies to this PR and head, or None. Own PRs carry to later heads (a plan
    check at merge time guards the plan). Engineer PRs use it for the exact head only."""
    try:
        so = load_signoff()
        if author == SELF_LOGIN:
            return so.active(pr_num, lane=so.OWN)
        return so.active(pr_num, lane=so.ENGINEER, head_sha=sha)
    except Exception as e:  # noqa: BLE001 - fail closed: no sign-off
        print(f"sign-off read failed for PR #{pr_num}: {e}", file=sys.stderr)
        return None


def signoff_carry(pr_num, author, sha, hits):
    """(sign-off record or None, new hits). Carries only when there is a hit, every hit has a
    fingerprint and the owner's sign-off covers all of them."""
    rec = signoff_for(pr_num, author, sha)
    if not rec or not hits:
        return None, hits
    so = load_signoff()
    new = [h for h in hits if not so.covers(rec, h)]
    return (None if new else rec), new


def _age_s(stamp):
    try:
        return (
            NOW
            - dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
            .replace(tzinfo=dt.timezone.utc)
            .timestamp()
        )
    except (TypeError, ValueError):
        return None


def recent_queue_runs(known_ids):
    """Runs of approved/pending queue items active in the last 6 h that the
    ?status=waiting list did not return, fetched by id, kept only if waiting."""
    queue = load_json(QUEUE, {"items": {}})
    want = []
    for it in queue.get("items", {}).values():
        if it.get("status") not in ("approved", "pending"):
            continue
        ages = [
            a
            for a in (_age_s(it.get(k)) for k in ("decided_at", "last_seen", "first_seen"))
            if a is not None
        ]
        if not ages or min(ages) > RECENT_RUN_WINDOW_S:
            continue
        for rid in (it.get("run_ids") or [])[-3:]:
            if rid not in known_ids:
                known_ids.add(rid)
                want.append(rid)
    # Parallel reads (the gate runs every minute, and sequential calls were most of a pass). Any GhError still propagates, so the pass fails closed as before.
    with ThreadPoolExecutor(max_workers=8) as pool:
        got = list(pool.map(lambda rid: gh(["api", f"repos/{REPO}/actions/runs/{rid}"]), want))
    return [r for r in got if r and r.get("status") == "waiting"]


def working_session(pr_num, branch):
    """(id, title) of a non-cron session that is MID-TURN right now (live turn lease) and
    is working this PR: either it is dedicated to it (an Ops Center "Discuss" session or a
    lane "Auto-fix" session for this PR number), or it pushed to the PR branch (a git push
    with a <src>:<branch> refspec) in the last
    SESSION_MENTION_S. Reading or mentioning the PR is not working it (a triage session
    must not hide the card). Leases are keyed by the root of a compression chain, so the
    chain is walked down to its live segments. A state.db error counts as nobody, so the
    card shows rather than hides."""
    title_rx = re.compile(rf"^(Discuss\b.*\bPR #{pr_num}\b|Auto-fix PR #{pr_num}\b)")
    try:
        con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        leases = [
            r[0]
            for r in con.execute(
                "SELECT conversation_id FROM session_turn_leases WHERE expires_at > ? "
                "AND conversation_id NOT LIKE 'cron_%'",
                (NOW,),
            ).fetchall()
        ]
        for root in leases:
            rows = con.execute(
                "WITH RECURSIVE chain(id) AS (SELECT ? UNION SELECT s.id FROM sessions s "
                "JOIN chain c ON s.parent_session_id = c.id JOIN sessions p ON p.id = c.id "
                "WHERE p.end_reason = 'compression') SELECT s.id, COALESCE(s.title, '') FROM chain "
                "JOIN sessions s ON s.id = chain.id",
                (root,),
            ).fetchall()
            titles = [t for _, t in rows if t]
            label = titles[0] if titles else root
            if any(title_rx.search(t) for t in titles):
                return root, label
            if not branch or len(branch) < 8:
                continue
            # The LIKE is only a prefilter. The branch must end at the refspec boundary, or a
            # push to a branch with an access suffix parks the stacked PR on its base branch.
            exact = re.compile(r":" + re.escape(branch) + r"(?![A-Za-z0-9._/-])")
            for sid, _ in rows:
                for (calls,) in con.execute(
                    "SELECT tool_calls FROM messages WHERE session_id = ? AND timestamp > ? "
                    "AND tool_calls LIKE '%git push%' AND tool_calls LIKE ?",
                    (sid, NOW - SESSION_MENTION_S, f"%:{branch}%"),
                ).fetchall():
                    if exact.search(calls or ""):
                        return sid, label
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return None


def park_reason(pr, sha):
    """Why a session or the AI review is moving the owner's own PR right now (a note on the card), else None.
    Engineer PRs are never parked: their waiting work is mine to direct."""
    if ((pr.get("user") or {}).get("login") or "").lower() != SELF_LOGIN:
        return None
    busy = working_session(pr.get("number"), (pr.get("head") or {}).get("ref"))
    if busy:
        return f"session '{busy[1] or busy[0]}' is working the PR"
    labels = {(lbl.get("name") or "").lower() for lbl in pr.get("labels") or []}
    if labels & set(HOLD_LABELS):
        return None  # held on purpose: no fixer runs, so the plan approval must show
    try:
        runs = (
            gh(
                [
                    "api",
                    f"repos/{REPO}/commits/{sha}/check-runs?check_name="
                    + AI_REVIEW_CHECK.replace(" ", "%20")
                    + "&per_page=20",
                ]
            )
            or {}
        )
    except GhError:
        return None  # cannot tell: show the card
    # Only the newest run counts: an override or a re-run leaves the older red
    # run on the same sha, and that must not keep the plan hidden.
    named = [cr for cr in runs.get("check_runs", []) if cr.get("name") == AI_REVIEW_CHECK]
    if named:
        newest = max(named, key=lambda cr: (cr.get("started_at") or "", cr.get("id") or 0))
        if newest.get("conclusion") in AI_REVIEW_RED:
            return "AI review is blocking (the review card carries it)"
    return None


def cancel_orphan(r, commit_prs):
    """a gated run whose PR is already merged or closed can never matter, so cancel it
    instead of putting it on Needs me. Orphan = the commit's PRs and the branch's PRs are all
    closed (at least one exists). Returns True when the run was cancelled (or would be, dry run)."""
    branch = r.get("head_branch") or ""
    owner = REPO.split("/")[0]
    try:
        by_branch = (
            (gh(["api", f"repos/{REPO}/pulls?head={owner}:{branch}&state=all"]) or [])
            if branch
            else []
        )
    except GhError:
        return False
    prs = {p["number"]: p for p in list(commit_prs or []) + list(by_branch)}
    if not prs or any(p.get("state") == "open" for p in prs.values()):
        return False
    nums = sorted(prs)
    rec = {
        "run": r["id"],
        "workflow": r.get("path", ""),
        "event": r.get("event"),
        "pr": nums[-1],
        "decision": "cancelled_orphan",
        "reasons": [f"PR #{n} closed" for n in nums],
        "files_changed": 0,
    }
    if DRY_RUN:
        log_decision(dict(rec, decision="would_cancel_orphan"))
        return True
    try:
        gh(["api", "-X", "POST", f"repos/{REPO}/actions/runs/{r['id']}/cancel"], raw=True)
    except Exception as e:  # noqa: BLE001 - surface the run as before rather than lose it
        log_decision(dict(rec, decision="cancel_orphan_failed", reasons=[str(e)[:200]]))
        return False
    log_decision(rec)
    return True


def cancel_superseded(r, open_prs):
    """A gated run on a sha that is no longer the head of any open PR can never gate a merge
    (each new head gets its own run), yet it waits on the environment until GitHub times it out
    and no card carries it. Cancel it. (A run can sit on a merged PR's old head when the same commit is also in a stacked PR.) Returns True when cancelled (or would
    be, dry run). False means the caller must keep the run visible."""
    heads = ", ".join(
        f"#{p.get('number')} head {((p.get('head') or {}).get('sha') or '?')[:8]}" for p in open_prs
    )
    rec = {
        "run": r["id"],
        "workflow": r.get("path", ""),
        "event": r.get("event"),
        "pr": (open_prs[0].get("number") if open_prs else None),
        "decision": "cancelled_superseded",
        "reasons": [
            f"run sha {r.get('head_sha', '')[:8]} is no open PR head ({heads or 'no open PR'})"
        ],
        "files_changed": 0,
    }
    if DRY_RUN:
        log_decision(dict(rec, decision="would_cancel_superseded"))
        return True
    try:
        gh(["api", "-X", "POST", f"repos/{REPO}/actions/runs/{r['id']}/cancel"], raw=True)
    except Exception as e:  # noqa: BLE001 - keep the run visible rather than lose it
        log_decision(
            dict(rec, decision="cancel_superseded_failed", reasons=rec["reasons"] + [str(e)[:200]])
        )
        return False
    log_decision(rec)
    return True


def hold_run_item(items, live_keys, r, reason, base):
    """Queue a run with no usable PR as its own Needs me card (run-<id>)."""
    key = f"run-{r['id']}"
    live_keys.add(key)
    it = items.get(key)
    if not it:
        items[key] = it = {
            "pr": None,
            "title": r.get("display_title") or r.get("name"),
            "author": (r.get("actor") or {}).get("login"),
            "url": r.get("html_url"),
            "head_sha": r.get("head_sha"),
            "run_ids": [r["id"]],
            "held_reasons": [reason],
            "files": [],
            "first_seen": NOW_ISO,
            "assessment": None,
            "status": "pending",
        }
        log_decision(
            dict(base, pr=None, decision="hold", reasons=it["held_reasons"], files_changed=0)
        )
    it["status"] = "pending"
    it["last_seen"] = NOW_ISO


def run_pass():
    """Returns list of wake lines (empty -> silent)."""
    runs = []
    page = 1
    while True:
        d = gh(["api", f"repos/{REPO}/actions/runs?status=waiting&per_page=100&page={page}"])
        batch = d.get("workflow_runs", []) if d else []
        runs.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    # GitHub's ?status=waiting list can omit a run that is in fact waiting
    # (seen 2026-10-09: drift run 37942107563 sat on its second coverage wave
    # for 50 min, invisible to the list). Re-read the runs of recently active
    # queue items directly so an approved run's follow-up wave and a held
    # run's pending state are never missed.
    runs.extend(recent_queue_runs({r["id"] for r in runs}))

    global WAITING_RUNS
    WAITING_RUNS = runs
    waiting = []  # (run, env_ids)
    with ThreadPoolExecutor(max_workers=8) as pool:
        pends = list(
            pool.map(
                lambda r: (
                    gh(["api", f"repos/{REPO}/actions/runs/{r['id']}/pending_deployments"]) or []
                ),
                runs,
            )
        )
    for r, pend in zip(runs, pends):
        env_ids = sorted(
            {
                p["environment"]["id"]
                for p in pend
                if (p.get("environment") or {}).get("name") == ENV_NAME
            }
        )
        if env_ids:
            waiting.append((r, env_ids))

    queue = load_json(QUEUE, {"items": {}})
    items = queue.setdefault("items", {})
    wake = []
    live_keys = set()
    pr_cache = {}
    assessed = {}

    for r, env_ids in waiting:
        wf = r.get("path", "")
        base = {"run": r["id"], "workflow": wf, "event": r.get("event")}
        unexpected = r.get("event") not in ALLOWED_EVENTS or wf not in ALLOWED_WORKFLOWS

        prs = [p["number"] for p in (r.get("pull_requests") or [])]
        found = []
        if not prs:
            found = gh(["api", f"repos/{REPO}/commits/{r['head_sha']}/pulls"]) or []
            prs = [p["number"] for p in found if p.get("state") == "open"]
        if not prs and not unexpected and cancel_orphan(r, found):
            continue
        if not prs:
            hold_run_item(
                items,
                live_keys,
                r,
                "unexpected workflow" if unexpected else "no PR found for run",
                base,
            )
            continue
        # The run belongs to the open PR whose head IS this sha. A commit can sit in several PRs
        # (stacked branches), so prs[0] is not enough.
        for n in prs:
            if n not in pr_cache:
                pr_cache[n] = gh(["api", f"repos/{REPO}/pulls/{n}"])
        live = [pr_cache[n] for n in prs if (pr_cache[n] or {}).get("state") == "open"]
        match = [p for p in live if (p.get("head") or {}).get("sha") == r["head_sha"]]
        if not match:
            # Superseded: a newer run on the current head carries the plan. Never silently skip
            # it (it would wait unseen until GitHub times it out): cancel it, or show it. A run
            # younger than SUPERSEDED_MIN_AGE_S is left one more pass, so a PR head read that
            # lags a fresh push can never cancel the new head's run.
            created = r.get("created_at") or ""
            try:
                age = (
                    NOW
                    - dt.datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ")
                    .replace(tzinfo=dt.timezone.utc)
                    .timestamp()
                )
            except ValueError:
                age = SUPERSEDED_MIN_AGE_S
            if age < SUPERSEDED_MIN_AGE_S:
                continue
            if not unexpected and cancel_superseded(r, live):
                continue
            hold_run_item(
                items,
                live_keys,
                r,
                (
                    f"unexpected workflow: {wf} ({r.get('event')}) on a superseded sha"
                    if unexpected
                    else "superseded run (no open PR has this sha as its head) and the cancel failed"
                ),
                base,
            )
            continue
        pr = match[0]
        pr_num = pr["number"]
        sha = r["head_sha"]
        key = f"{pr_num}@{sha}"

        if key not in assessed:
            assessed[key] = assess_pr_detail(
                pr_num, sha, own=((pr.get("user") or {}).get("login") == SELF_LOGIN)
            )
        files, hits = assessed[key]
        if unexpected:
            hits = hits + [{"reason": f"unexpected workflow: {wf} ({r.get('event')})", "fp": None}]
        reasons = [h["reason"] for h in hits]

        existing = items.get(key)
        if existing and existing.get("status") in ("approved", "rejected"):
            live_keys.add(key)
            if r["id"] in existing.get("decided_runs", existing.get("run_ids", [])):
                # Same run, same sha, waiting again: a later job wave (drift
                # coverage after coverage-ids). The owner's Ops Center approval covers
                # it; a rejected run never reaches a second wave.
                if existing["status"] == "approved" and not DRY_RUN:
                    args = [
                        "api",
                        "-X",
                        "POST",
                        f"repos/{REPO}/actions/runs/{r['id']}/pending_deployments",
                        "-f",
                        "state=approved",
                        "-f",
                        "comment="
                        + (
                            CARRY_COMMENT
                            if existing.get("approval_source") == "carried"
                            else "Approved after review"
                        ),
                    ]
                    for eid in env_ids:
                        args += ["-F", f"environment_ids[]={eid}"]
                    gh(args)
                    log_decision(
                        dict(
                            base,
                            pr=pr_num,
                            decision="approved_followup_wave",
                            reasons=reasons,
                            files_changed=len(files),
                        )
                    )
                continue
            # A re-run on a sha the owner already decided: hold it again (assessment kept,
            # so no new wake) and let me decide again in the Ops Center.
            existing["status"] = "pending"

        # a held head whose every hit the owner already approved (same content) on an earlier head of
        # this PR is approved with no new click. Any error here keeps the hold (fail closed).
        carried_from, new_hits = None, hits
        if reasons:
            try:
                carried_from, new_hits = carry_decision(items, pr_num, hits)
            except Exception as e:  # noqa: BLE001 - fail closed: hold
                print(f"carry check failed for PR #{pr_num}: {e}", file=sys.stderr)
                carried_from, new_hits = None, hits
        so_rec = None
        if reasons and not carried_from:
            try:
                so_rec, so_new = signoff_carry(
                    pr_num, (pr.get("user") or {}).get("login"), sha, hits
                )
            except Exception as e:  # noqa: BLE001 - fail closed: hold
                print(f"sign-off carry failed for PR #{pr_num}: {e}", file=sys.stderr)
                so_rec, so_new = None, hits
            if so_rec:
                carried_from = so_rec["head_sha"]
            elif so_new is not hits:
                new_hits = [h for h in new_hits if h in so_new]
        delta_paths = None
        if (
            reasons
            and not carried_from
            and new_hits
            and (pr.get("user") or {}).get("login") == SELF_LOGIN
        ):
            # only .github files left, and none of their changes since the owner's last manual look is sensitive
            try:
                d_base = manual_base(items, pr_num, sha)
                d_paths, d_why = delta_carry(pr_num, SELF_LOGIN, sha, new_hits, d_base)
                if d_paths:
                    carried_from, delta_paths = d_base, d_paths
                else:
                    print(f"delta carry held PR #{pr_num}: {d_why}", file=sys.stderr)
            except Exception as e:  # noqa: BLE001 - fail closed: hold
                print(f"delta carry failed for PR #{pr_num}: {e}", file=sys.stderr)
                carried_from, delta_paths = None, None
        if carried_from:
            live_keys.add(key)
            if DRY_RUN:
                log_decision(
                    dict(
                        base,
                        pr=pr_num,
                        decision="would_approve_carried_signoff"
                        if so_rec
                        else (
                            "would_approve_carried_delta"
                            if delta_paths
                            else "would_approve_carried"
                        ),
                        carried_from=carried_from,
                        **({"delta_paths": delta_paths} if delta_paths else {}),
                        reasons=reasons,
                        files_changed=len(files),
                    )
                )
                continue
            args = [
                "api",
                "-X",
                "POST",
                f"repos/{REPO}/actions/runs/{r['id']}/pending_deployments",
                "-f",
                "state=approved",
                "-f",
                f"comment={CARRY_COMMENT}",
            ]
            for eid in env_ids:
                args += ["-F", f"environment_ids[]={eid}"]
            gh(args)
            log_decision(
                dict(
                    base,
                    pr=pr_num,
                    decision="approved_carried_signoff"
                    if so_rec
                    else ("approved_carried_delta" if delta_paths else "approved_carried"),
                    carried_from=carried_from,
                    **({"delta_paths": delta_paths} if delta_paths else {}),
                    reasons=reasons,
                    files_changed=len(files),
                )
            )
            if existing:
                # A card that was already queued for this head is closed by the carry. It stores no
                # fingerprints, so it can never be a carry source itself.
                existing.update(
                    {
                        "status": "approved",
                        "approval_source": "carried",
                        "carried_from": carried_from,
                        "carried_signoff": bool(so_rec),
                        "carried_delta": bool(delta_paths),
                        "decided_at": NOW_ISO,
                        "decided_runs": sorted(set(existing.get("decided_runs", [])) | {r["id"]}),
                    }
                )
                existing.pop("approved_fps", None)
                existing.pop("new_held", None)
                existing.pop("held_delta", None)
            continue

        if not reasons:
            if DRY_RUN:
                log_decision(
                    dict(
                        base,
                        pr=pr_num,
                        decision="would_approve",
                        reasons=[],
                        files_changed=len(files),
                    )
                )
                continue
            args = [
                "api",
                "-X",
                "POST",
                f"repos/{REPO}/actions/runs/{r['id']}/pending_deployments",
                "-f",
                "state=approved",
                "-f",
                f"comment={APPROVE_COMMENT}",
            ]
            for eid in env_ids:
                args += ["-F", f"environment_ids[]={eid}"]
            gh(args)
            log_decision(
                dict(base, pr=pr_num, decision="approved", reasons=[], files_changed=len(files))
            )
            continue

        live_keys.add(key)
        it = existing
        if not it:
            it = items[key] = {
                "pr": pr_num,
                "title": pr.get("title"),
                "author": (pr.get("user") or {}).get("login"),
                "url": pr.get("html_url"),
                "head_sha": sha,
                "run_ids": [],
                "held_reasons": reasons,
                "files": files,
                "first_seen": NOW_ISO,
                "assessment": None,
                "status": "pending",
            }
        it.update(
            {
                "title": pr.get("title"),
                "held_reasons": reasons,
                "hits": hits,  # per-hit content fingerprints, copied to approved_fps on approval
                "files": files,
                "status": "pending",
                "last_seen": NOW_ISO,
            }
        )
        # with an earlier approval on this PR, the card shows only the hits that are new.
        try:
            had_approval = bool(approved_fp_map(items, pr_num)) or bool(
                signoff_for(pr_num, (pr.get("user") or {}).get("login"), sha)
            )
        except Exception:  # noqa: BLE001
            had_approval = False
        if had_approval and new_hits:
            it["new_held"] = [h["reason"] for h in new_hits]
            # the card links only the newly held files' diff since the owner's approved head.
            try:
                base_sha = last_approved_head(items, pr_num, sha)
                if not base_sha:
                    so_prev = signoff_for(pr_num, (pr.get("user") or {}).get("login"), sha)
                    base_sha = (so_prev or {}).get("head_sha")
                    base_sha = base_sha if base_sha != sha else None
                paths = sorted({h["path"] for h in new_hits if h.get("path")})
                prev = it.get("held_delta") or {}
                if not base_sha or not paths:
                    it.pop("held_delta", None)
                elif (prev.get("base_sha"), prev.get("head_sha"), prev.get("paths")) != (
                    base_sha,
                    sha,
                    paths,
                ) or prev.get("error"):
                    try:
                        it["held_delta"] = held_delta(base_sha, sha, paths)
                    except GhError as e:
                        it["held_delta"] = {
                            "base_sha": base_sha,
                            "head_sha": sha,
                            "paths": paths,
                            "files": [],
                            "unchanged": [],
                            "unknown": paths,
                            "error": str(e)[:200],
                            "compare_url": f"https://github.com/{REPO}/compare/{base_sha}...{sha}",
                        }
            except Exception as e:  # noqa: BLE001 - display only, never blocks the hold
                print(f"held delta failed for PR #{pr_num}: {e}", file=sys.stderr)
        else:
            it.pop("new_held", None)
            it.pop("held_delta", None)
        if r["id"] not in it["run_ids"]:
            it["run_ids"].append(r["id"])
            log_decision(
                dict(base, pr=pr_num, decision="hold", reasons=reasons, files_changed=len(files))
            )
        working = park_reason(pr, sha)
        if working != it.get("working"):
            log_decision(
                dict(
                    base,
                    pr=pr_num,
                    decision="working" if working else "idle",
                    reasons=[working or it.get("working")],
                    files_changed=len(files),
                )
            )
        it.pop("parked", None)
        it.pop("park_first_epoch", None)
        if working:
            it["working"] = working
        else:
            it.pop("working", None)

    # Reconcile: anything pending that is no longer waiting -> cleared.
    for key, it in list(items.items()):
        if it.get("status") == "pending" and key not in live_keys:
            it["status"] = "cleared"
            it["cleared_at"] = NOW_ISO
        if it.get("status") in ("cleared", "approved", "rejected"):
            stamp = it.get("cleared_at") or it.get("decided_at") or it.get("first_seen")
            try:
                age = (
                    NOW
                    - dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
                    .replace(tzinfo=dt.timezone.utc)
                    .timestamp()
                )
            except (TypeError, ValueError):
                age = 0
            if age > CLEARED_KEEP_DAYS * 86400:
                del items[key]

    # Wake only for pending items with no assessment for their sha.
    for key, it in items.items():
        if it.get("status") != "pending":
            continue
        a = it.get("assessment")
        if a and a.get("head_sha", it["head_sha"]) == it["head_sha"]:
            continue
        if PASS_ONLY or NOW - it.get("last_wake_epoch", 0) < REWAKE_SECONDS:
            continue
        it["last_wake_epoch"] = NOW
        wake.append(
            {
                "key": key,
                "pr": it["pr"],
                "sha": it["head_sha"],
                "title": it["title"],
                "url": it["url"],
                "reasons": it["held_reasons"],
                "files": it["files"],
            }
        )

    queue["updated"] = NOW_ISO
    write_json(QUEUE, queue)
    return wake


# ---------------------------------------------------------------------
# Health (fail closed)
# ---------------------------------------------------------------------
def classify(err):
    if re.search(r"HTTP 401|Bad credentials|authentication|not logged in|token expired", err, re.I):
        return "AUTH"
    if re.search(r"could not resolve|timed out|timeout|connection|network|dial tcp", err, re.I):
        return "NETWORK"
    return "API"


ASSESS_FIELDS = ("summary", "changes", "risk", "recommendation")
RISK_LEVELS = ("low", "medium", "high")
RECS = ("approve", "request changes", "reject")


def set_assessment(key, path):
    """Merge an assessment into queue.json under the shared lock (used by the agent)."""
    a = json.loads(Path(path).read_text())
    missing = [f for f in ASSESS_FIELDS if not a.get(f)]
    if missing:
        raise SystemExit(f"assessment missing fields: {missing}")
    if not isinstance(a["changes"], list):
        raise SystemExit("changes must be a list of strings")
    risk, rec = a["risk"], a["recommendation"]
    if not isinstance(risk, dict) or risk.get("level") not in RISK_LEVELS or not risk.get("why"):
        raise SystemExit('risk must be {"level": low|medium|high, "why": "..."}')
    if not isinstance(rec, dict) or rec.get("action") not in RECS or not rec.get("why"):
        raise SystemExit(
            'recommendation must be {"action": approve|request changes|reject, "why": "..."}'
        )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        queue = load_json(QUEUE, {"items": {}})
        it = queue.get("items", {}).get(key)
        if not it:
            raise SystemExit(f"no queue item {key}")
        a["head_sha"] = it["head_sha"]
        a.setdefault("checked_at", NOW_ISO)
        it["assessment"] = a
        write_json(QUEUE, queue)
    print(f"assessment stored for {key} (risk {risk['level']}, recommend {rec['action']})")


def privileged_pass():
    """governance / entra-privileged / destroy lane (never auto-approved). Returns
    (wake lines, alert text or None). Its own fail-closed counter so a bug here
    never blocks ordinary terraform-plan approvals."""
    priv = _privileged
    if priv is None:
        return [], None, 0
    h = load_json(PRIV_HEALTH, {})
    fails, alerts, last = (
        int(h.get("failures", 0)),
        int(h.get("alert_count", 0)),
        float(h.get("last_alert_epoch", 0)),
    )
    try:
        wake = priv.run_pass(WAITING_RUNS)
        write_json(
            PRIV_HEALTH,
            {"failures": 0, "alert_count": 0, "last_alert_epoch": last, "updated": NOW_ISO},
        )
        return wake, None, (fails if fails else 0)
    except Exception as e:  # noqa: BLE001 - fail closed (nothing is ever approved in this lane)
        err = f"{type(e).__name__}: {e}"
        if PASS_ONLY:
            print(f"privileged lane failed in the fast pass: {err[:300]}", file=sys.stderr)
            return [], None, 0
        fails += 1
        alert = fails == 3 or (
            fails > 3
            and ((alerts == 1 and NOW - last >= 3600) or (alerts >= 2 and NOW - last >= 14400))
        )
        if alert:
            alerts += 1
            last = NOW
        write_json(
            PRIV_HEALTH,
            {
                "failures": fails,
                "alert_count": alerts,
                "last_alert_epoch": last,
                "updated": NOW_ISO,
                "last_error": err[:500],
            },
        )
        return (
            [],
            (
                f"privileged-environment lane FAILING ({classify(err)}), {fails} in a row: {err[:300]}"
                if alert
                else None
            ),
            0,
        )
    finally:
        try:  # noqa: SIM105
            priv.spawn_secrets_refresh()
        except Exception:  # noqa: BLE001 - the cache just goes stale; the UI shows its age
            pass


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "set-assessment":
        if ":" in sys.argv[2]:
            if _privileged is None:
                print("no privileged lane plugged in", file=sys.stderr)
                return 1
            return _privileged.set_assessment(sys.argv[2], sys.argv[3])
        return set_assessment(sys.argv[2], sys.argv[3])
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    health = load_json(HEALTH, {})
    failures = int(health.get("failures", 0))
    alert_count = int(health.get("alert_count", 0))
    last_alert = float(health.get("last_alert_epoch", 0))

    lockf = open(LOCK, "w")  # noqa: SIM115 -- flock held for the whole run
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("[TFPLAN GATE] previous run still active; skipping")
        print(SILENT)
        return

    priv_wake, priv_alert = [], None
    try:
        wake = run_pass()
        err = None
        priv_wake, priv_alert, _ = privileged_pass()
    except GhError as e:
        err = str(e)
    except Exception as e:  # noqa: BLE001 - fail closed on any bug
        err = f"gate error {type(e).__name__}: {e}"

    if err is not None and PASS_ONLY:
        print(f"[TFPLAN GATE FAST PASS] {NOW_ISO} failed: {err[:500]}", file=sys.stderr)
        print(SILENT)
        return
    if PASS_ONLY:
        print(SILENT)
        return
    if err is not None:
        failures += 1
        alert = False
        if failures == 3:
            alert = True
        elif failures > 3:
            el = NOW - last_alert
            if (alert_count == 1 and el >= 3600) or (alert_count >= 2 and el >= 14400):
                alert = True
        if alert:
            alert_count += 1
            last_alert = NOW
        write_json(
            HEALTH,
            {
                "failures": failures,
                "alert_count": alert_count,
                "last_alert_epoch": last_alert,
                "updated": NOW_ISO,
                "last_error": err[:500],
            },
        )
        if alert:
            print(f"[TFPLAN GATE ALERT] {NOW_ISO}")
            print(f"The plan gate is FAILING ({classify(err)}). Consecutive failures: {failures}.")
            print(f"Error (first 500 chars): {err[:500]}")
            print(
                "Failing CLOSED: no terraform-plan approvals are being posted while this persists."
            )
            print("Action: report this to owner in one short message; do not write any assessment.")
        else:
            print(SILENT)
        return

    streak = failures
    write_json(
        HEALTH,
        {"failures": 0, "alert_count": 0, "last_alert_epoch": last_alert, "updated": NOW_ISO},
    )
    if not wake and not priv_wake and not priv_alert:
        print(SILENT)
        return
    if priv_alert:
        print(f"[PRIVILEGED GATE ALERT] {NOW_ISO}")
        print(priv_alert)
        print(
            "Nothing in the governance / entra-privileged / destroy lane is ever approved automatically; the queue is just stale."
        )
    if wake:
        print(f"[TFPLAN GATE] {NOW_ISO} - {len(wake)} held PR(s) need an assessment.")
        if streak:
            print(f"[CATCH-UP] gh had failed {streak} time(s) before this run.")
        print(f"Queue file: {QUEUE}")
        for w in wake:
            print(json.dumps(w))
    if priv_wake:
        print(
            f"[PRIVILEGED ENV] {NOW_ISO} - {len(priv_wake)} privileged deployment(s) need an assessment."
        )
        print(f"Queue file: {STATE_DIR / 'privileged-queue.json'}")
        for w in priv_wake:
            print("PRIV " + json.dumps(w))


if __name__ == "__main__":
    main()
