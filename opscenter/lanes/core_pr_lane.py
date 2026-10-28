#!/usr/bin/env python3
"""
core_pr_lane.py
Purpose: Merge lane for the owner's green PRs on the core repository. Green core PRs
         opened by other sessions sat unmerged (for example #69) until the owner noticed them. Every pass
         this lane lists the open PRs, keeps only mine (author the owner's account, base main, not draft, no hold
         label, branch not denied) and decides each one, first failing reason wins:
           1. every check on the head SUCCESS (ci required, visual and kit when present), none pending
           2. mergeStateStatus CLEAN
           3. quiet period: the head commit is at least quiet_min old (committer date) and the same
              head was already seen on the previous pass, so a session still pushing is never
              merged under it
           4. local checks on the head in a temporary detached worktree: checks/check-sanitised.py,
              check-ascii.py, check-links.py, check-rules.py, check-hermes-skills.py (whichever
              exist) and a semicolon scan of added prose lines in .md files (code fences and code
              spans excluded)
           5. CHANGELOG.md adds exactly one version heading, greater than the newest tag and not
              tagged yet. Two PRs claiming one version: the older PR keeps it, the other is held.
         It merges at most ONE PR per pass (squash, pinned to the head), confirms MERGED, pulls the
         local clone only when it is on main and clean, releases vX.Y.Z from main with the notes of
         that CHANGELOG entry, confirms the tag points at the merge commit and runs the core skills
         sync. A failure after the merge is recorded and reported once, never retried.
         The local clone's branch and working tree are never changed (refs under refs/corelane/
         and a temporary worktree only, both removed after the pass).
Date:    2026-10-14

Usage:   core_pr_lane.py tick          (cron, every 5 min, prints merges and what needs me)
         core_pr_lane.py status        (prints the state file)
         core_pr_lane.py check <pr>    (read-only: prints the decision, merges nothing)
Policy:  <state dir>/core-review/lane-policy.json (kill switch enabled, quiet_min, hold_labels,
         branch_deny). A missing file means the defaults below. An unreadable file fails closed
         (nothing merged, counted as a lane error). Hold one PR by adding the label do-not-merge.
Output:  tick prints "[CORE LANE] merged #n vX.Y.Z <title>" per merge, and lines only for problems
         that need me: a PR held 2 hours or more on a reason a person must fix (at most once per PR
         and reason every 12 hours), a failure after a merge, or 3 lane errors in a row.
Exit:    0 always for tick (the cron must stay quiet), 1 when check fails, 2 on bad usage.
Test hooks: CORELANE_GH_BIN (fake gh), CORELANE_REPO_DIR (local clone), CORELANE_CACHE_DIR,
            CORELANE_POLICY, CORELANE_NOW (ISO UTC), CORELANE_SYNC_CMD (shell command run after a
            release), CORELANE_DRY_RUN=1 (decides and prints would_merge, never merges or releases),
            CORELANE_FIXER (autofix.py path). The fixer's own hooks apply (OWNPR_FIX_SPAWN=record).
Auto-fix: every pass hands each of the owner's PRs to autofix.consider() (target
         core), the same starter the other lanes use. A hold a session can fix (red
         checks, a conflict or a branch behind main, a taken or stale version, failing local checks, a
         bad CHANGELOG entry) starts ONE fix session at once. A refused merge or another merge state
         stays mine. The fixer's caps, give-up line and kill switch (policy autofix.enabled) apply, and
         the held alert stays quiet while a session is on it. A dry run never starts a session.
Owner mode (2026-10-22, owner decision on core issue 117: the owner merges the owner's core PRs by hand in
         version order and every one carries do-not-merge): policy merge_mode "owner" keeps every check,
         the quiet rule and the auto-fix, but NEVER merges or releases. The owner_label (do-not-merge) is
         expected, not a hold, and the lane adds it to any of the owner's open PRs that lack it. A PR that clears
         every gate is recorded as status "owner" with its place in version order (queue) and the lower
         versions still held ahead of it (blocked_by), so the ops center shows it as with the owner.
System python3 is 3.9: no 3.10+ syntax.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import paths

HOME = Path.home()
TAG = "[CORE LANE]"
POLICY_FILE = Path(
    os.environ.get("CORELANE_POLICY", str(paths.state_dir() / "core-review" / "lane-policy.json"))
)
CACHE_DIR = Path(
    os.environ.get("CORELANE_CACHE_DIR", str(paths.agent_home() / "cache" / "core-pr-lane"))
)
STATE_FILE = CACHE_DIR / "lane-state.json"
DECISIONS = CACHE_DIR / "decisions.jsonl"
LOCK_FILE = CACHE_DIR / "lane.lock"
REPO_DIR = Path(os.environ.get("CORELANE_REPO_DIR", str(paths.repos_dir() / "core")))
GH = os.environ.get("CORELANE_GH_BIN") or paths.which("gh")
SYNC_CMD = os.environ.get(
    "CORELANE_SYNC_CMD", ""
)  # run after a release (the consumer's skills sync); none by default
DRY_RUN = os.environ.get("CORELANE_DRY_RUN") == "1"
FIXER_PY = Path(
    os.environ.get("CORELANE_FIXER", str(Path(__file__).resolve().parent / "autofix.py"))
)
FIX_TARGET = "core"
PY = sys.executable or "/usr/bin/python3"
DEFAULTS = {
    "enabled": True,
    "repo": "owner/core",
    "self_login": "owner-account",
    "base": "main",
    "quiet_min": 15,
    "hold_labels": ["do-not-merge", "hold"],
    "branch_deny": [],
    "required_checks": ["ci"],
    "hold_alert_min": 120,
    "alert_every_h": 12,
    "autofix": {"enabled": True, "max_sessions_per_day": 3, "run_budget_s": 5400},
    "merge_mode": "lane",
    "owner_label": "do-not-merge",
}
LOCAL_CHECKS = [
    "check-sanitised.py",
    "check-ascii.py",
    "check-links.py",
    "check-rules.py",
    "check-hermes-skills.py",
]
OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}
RED = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR", "STALE"}
# Hold kinds a person must fix. Only these raise a line after hold_alert_min.
PERSON_KINDS = {
    "checks-red",
    "merge-state",
    "local-checks",
    "changelog",
    "version",
    "merge-refused",
}
ERROR_ALERT_FIRST, ERROR_ALERT_EVERY = 3, 144  # 3 passes in a row, then every 12 hours at 5 min
HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2}) \(v(\d+\.\d+\.\d+)\b")
TAGNAME = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


class GhError(Exception):
    pass


class PolicyError(Exception):
    pass


class LaneError(Exception):
    pass


def now_utc():
    raw = os.environ.get("CORELANE_NOW")
    if raw:
        return dt.datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s):
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def gh(args, timeout=90, raw=False):
    """Parsed JSON (or raw stdout) from gh. Any failure raises GhError."""
    try:
        # cwd is the cache dir (not a git repo), so --delete-branch never touches a local checkout.
        p = subprocess.run(
            [GH] + list(args), capture_output=True, text=True, timeout=timeout, cwd=str(CACHE_DIR)
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise GhError(f"gh {' '.join(args[:2])}: {type(e).__name__}: {e}")  # noqa: B904
    if p.returncode != 0:
        raise GhError(
            f"gh {' '.join(args[:2])} exit {p.returncode}: {(p.stderr or p.stdout).strip()[:300]}"
        )
    if raw:
        return p.stdout
    try:
        return json.loads(p.stdout) if p.stdout.strip() else None
    except ValueError as e:
        raise GhError(f"gh {' '.join(args[:2])}: unreadable JSON: {e}")  # noqa: B904


def git(args, cwd=None, timeout=120, check=True):
    p = subprocess.run(
        ["git", "-C", str(cwd or REPO_DIR)] + list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and p.returncode != 0:
        raise LaneError(f"git {' '.join(args[:2])} exit {p.returncode}: {p.stderr.strip()[:300]}")
    return p.stdout


def load_policy():
    pol = json.loads(json.dumps(DEFAULTS))
    if not POLICY_FILE.exists():
        return pol
    try:
        raw = json.loads(POLICY_FILE.read_text())
    except (OSError, ValueError) as e:
        raise PolicyError(f"policy {POLICY_FILE} unreadable: {e}")  # noqa: B904
    if not isinstance(raw, dict):
        raise PolicyError(f"policy {POLICY_FILE} is not an object")
    pol.update(raw)
    return pol


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, data):
    """Atomic write: temp file in the same folder, fsync, replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        try:  # noqa: SIM105
            os.unlink(tmp)
        except OSError:
            pass
        raise


def log(rec, now):
    DECISIONS.parent.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS, "a") as fh:
        fh.write(
            json.dumps(dict({"at": iso(now), "lane": "core-pr-lane", "dry_run": DRY_RUN}, **rec))
            + "\n"
        )


def vkey(v):
    return tuple(int(x) for x in v.split("."))


# ---------------------------------------------------------------- gh and git reads


def list_open(pol):
    prs = gh(
        [
            "pr",
            "list",
            "-R",
            pol["repo"],
            "--state",
            "open",
            "--limit",
            "50",
            "--json",
            "number,title,url,author,baseRefName,headRefName,headRefOid,isDraft,labels,"
            "mergeStateStatus,statusCheckRollup,createdAt",
        ]
    )
    if not isinstance(prs, list):
        raise GhError("gh pr list returned no list")
    return prs


def eligible(pr, pol):
    """None when the lane owns this PR, else why it is skipped."""
    author = (pr.get("author") or {}).get("login")
    if author != pol["self_login"]:
        return f"not my PR (author {author})"
    if (pr.get("baseRefName") or "") != pol["base"]:
        return f"base is {pr.get('baseRefName')}"
    if pr.get("isDraft"):
        return "draft"
    labels = {(lbl.get("name") or "").lower() for lbl in pr.get("labels") or []}
    holds = {h.lower() for h in pol.get("hold_labels") or []}
    if owner_mode(pol):
        holds.discard(
            str(pol.get("owner_label") or "").lower()
        )  # expected on every PR in owner mode
    hit = sorted(labels & holds)
    if hit:
        return f"label {hit[0]}"
    if (pr.get("headRefName") or "") in set(pol.get("branch_deny") or []):
        return f"branch {pr.get('headRefName')} denied by policy"
    return None


def owner_mode(pol):
    return str(pol.get("merge_mode") or "lane").lower() == "owner"


def has_label(pr, name):
    return str(name).lower() in {(lbl.get("name") or "").lower() for lbl in pr.get("labels") or []}


def ensure_owner_label(pr, pol, now):
    """Owner mode: add the owner label to the owner's PR when it is missing. Idempotent. (added, error)."""
    name = pol.get("owner_label") or "do-not-merge"
    if has_label(pr, name):
        return False, None
    n = int(pr["number"])
    if DRY_RUN:
        log({"pr": n, "decision": "would_label", "sha": pr.get("headRefOid"), "detail": name}, now)
        return False, None
    try:
        gh(["pr", "edit", str(n), "-R", pol["repo"], "--add-label", name], raw=True)
    except GhError as e:
        return False, str(e)[:200]
    pr.setdefault("labels", []).append({"name": name})
    log({"pr": n, "decision": "labelled", "sha": pr.get("headRefOid"), "detail": name}, now)
    return True, None


def owner_order(prs_state, claims, prs):
    """Owner mode: place in version order for each PR that is with the owner, plus the lower versions
    still held or waiting ahead of it. Updates the records in place."""
    ranked = []
    for p in prs:
        n = int(p["number"])
        v = (claims.get(n) or (None, None))[0]
        if v and claims.get(("owner", v)) == n:
            ranked.append((vkey(v), n))
    ranked.sort()
    for rec in prs_state.values():
        for k in ("queue", "queue_of", "blocked_by", "queue_text"):
            rec.pop(k, None)
    for i, (_, n) in enumerate(ranked):
        rec = prs_state.get(str(n)) or {}
        if rec.get("status") != "owner":
            continue
        ahead = [m for _, m in ranked[:i] if (prs_state.get(str(m)) or {}).get("status") != "owner"]
        rec["queue"] = i + 1
        rec["queue_of"] = len(ranked)
        rec["blocked_by"] = ahead
        where = "next in version order" if i == 0 else f"number {i + 1} in version order"
        if ahead:
            where += ", after " + ", ".join(f"#{m}" for m in ahead) + " clear"
        rec["queue_text"] = where


def checks(rollup, required):
    """(red, pending, missing) for the head: newest result per (workflow, check name)."""
    best = {}
    for c in rollup or []:
        name = c.get("name") or c.get("context") or "?"
        key = (c.get("workflowName") or "", name)
        when = c.get("completedAt") or c.get("startedAt") or ""
        val = (c.get("conclusion") or c.get("state") or c.get("status") or "PENDING").upper()
        if key not in best or when >= best[key][0]:
            best[key] = (when, val)
    red = sorted({k[1] for k, (_, v) in best.items() if v in RED})
    pending = sorted({k[1] for k, (_, v) in best.items() if v not in RED and v not in OK})
    names = {k[1] for k in best}
    missing = sorted(set(required or []) - names)
    return red, pending, missing


def fetch_heads(prs):
    """Fetch main and every PR head into refs/corelane/ (never a branch, never the working tree)."""
    specs = ["+refs/heads/main:refs/corelane/main"]
    specs += [f"+refs/pull/{p['number']}/head:refs/corelane/pr/{p['number']}" for p in prs]
    git(["fetch", "-q", "--no-tags", "origin"] + specs, timeout=180)


def drop_refs():
    out = git(["for-each-ref", "--format=%(refname)", "refs/corelane/"], check=False)
    for ref in out.split():
        git(["update-ref", "-d", ref], check=False)


def remote_tags():
    out = git(["ls-remote", "--tags", "origin"], timeout=60)
    tags = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("refs/tags/"):
            name = parts[1][len("refs/tags/") :]
            if name.endswith("^{}"):
                tags[name[:-3]] = parts[0]  # peeled annotated tag wins
            else:
                tags.setdefault(name, parts[0])
    return tags


def latest_version(tags):
    vs = [m.groups() for m in (TAGNAME.match(t) for t in tags) if m]
    if not vs:
        return None
    return ".".join(max(vs, key=lambda g: tuple(int(x) for x in g)))


def merge_base(head):
    return git(["merge-base", "refs/corelane/main", head]).strip()


def changelog_claim(head):
    """(version or None, problem or None) from the CHANGELOG diff of the PR head against main."""
    base = merge_base(head)
    diff = git(["diff", "-U0", base, head, "--", "CHANGELOG.md"])
    added = [ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    removed = [
        ln[1:] for ln in diff.splitlines() if ln.startswith("-") and not ln.startswith("---")
    ]
    old = {HEADING.match(x).group(2) for x in removed if HEADING.match(x)}
    new = [HEADING.match(x).group(2) for x in added if HEADING.match(x)]
    new = [v for v in new if v not in old]  # a moved heading is not a new version
    if not new:
        return None, "CHANGELOG.md adds no '## YYYY-other-resource (vX.Y.Z, title)' heading"
    if len(new) > 1:
        return None, "CHANGELOG.md adds more than one version heading: " + ", ".join(
            "v" + v for v in new
        )
    return new[0], None


def changelog_notes(head, version, limit=20):
    text = git(["show", f"{head}:CHANGELOG.md"])
    lines, inside = [], False
    for ln in text.splitlines():
        m = HEADING.match(ln)
        if m:
            if inside:
                break
            inside = m.group(2) == version
            continue
        if inside:
            lines.append(ln)
    body = "\n".join(lines).strip().splitlines()[:limit]
    return ("\n".join(body) + "\n\nSee CHANGELOG.md.").strip()


def commit_time(head):
    return parse_ts(git(["show", "-s", "--format=%cI", head]).strip())


def semicolon_hits(wt, base, head):
    """Added prose lines with a semicolon in changed .md files (fences, code spans, entities skipped)."""
    hits = []
    names = git(
        ["diff", "--name-only", "--diff-filter=AM", base, head, "--", "*.md"], cwd=wt
    ).split()
    for name in names:
        diff = git(["diff", "-U0", base, head, "--", name], cwd=wt)
        added = set()
        for ln in diff.splitlines():
            m = HUNK.match(ln)
            if m:
                start, count = int(m.group(1)), int(m.group(2) or "1")
                added.update(range(start, start + count))
        try:
            lines = (Path(wt) / name).read_text(encoding="utf8").split("\n")
        except (OSError, UnicodeDecodeError):
            continue
        fence = None
        for i, line in enumerate(lines, 1):
            s = line.lstrip()
            if s.startswith("```") or s.startswith("~~~"):
                mark = s[:3]
                if fence is None:
                    fence = mark
                elif fence == mark:
                    fence = None
                continue
            if fence or i not in added:
                continue
            prose = re.sub(r"`[^`]*`", "", line)
            prose = re.sub(r"&#?\w+;", "", prose)
            if ";" in prose:
                hits.append(f"{name}:{i}")
    return hits


def run_local_checks(head):
    """(ok, detail). Runs in a temporary detached worktree that is always removed."""
    wt = Path(tempfile.mkdtemp(prefix="corelane-wt-"))
    shutil.rmtree(wt)
    git(["worktree", "add", "-q", "--detach", str(wt), head], timeout=180)
    try:
        failed = []
        for name in LOCAL_CHECKS:
            script = wt / "checks" / name
            if not script.is_file():
                continue
            try:
                p = subprocess.run(
                    [PY, str(script)], cwd=str(wt), capture_output=True, text=True, timeout=600
                )
            except (OSError, subprocess.SubprocessError) as e:
                failed.append(f"{name} did not run ({type(e).__name__})")
                continue
            if p.returncode != 0:
                tail = [x for x in (p.stdout + "\n" + p.stderr).splitlines() if x.strip()][-2:]
                failed.append(f"{name}: " + " | ".join(tail)[:200])
        base = merge_base(head)
        semi = semicolon_hits(wt, base, head)
        if semi:
            failed.append("semicolon in added prose: " + ", ".join(semi[:6]))
        return (not failed), " | ".join(failed)[:600] if failed else "local checks pass"
    finally:
        git(["worktree", "remove", "--force", str(wt)], check=False)
        shutil.rmtree(wt, ignore_errors=True)


# ---------------------------------------------------------------- decision


def decide(pr, pol, rec, prev_head, claims, tags, now, local_cache):
    """(status, kind, reason, version). status: waiting, held or ready."""
    head = pr["headRefOid"]
    n = int(pr["number"])
    red, pending, missing = checks(pr.get("statusCheckRollup"), pol.get("required_checks"))
    if red:
        return "held", "checks-red", "checks red: " + ", ".join(red), None
    if pending:
        return "waiting", "checks-pending", "checks running: " + ", ".join(pending), None
    if missing:
        return (
            "waiting",
            "checks-pending",
            "required check not reported yet: " + ", ".join(missing),
            None,
        )
    mss = (pr.get("mergeStateStatus") or "UNKNOWN").upper()
    if mss != "CLEAN":
        if mss in ("UNKNOWN",):
            return "waiting", "merge-state", "GitHub is still computing the merge state", None
        return "held", "merge-state", f"merge state {mss} (needs CLEAN)", None
    ct = commit_time(head)
    quiet = dt.timedelta(minutes=float(pol.get("quiet_min", 15)))
    if ct is None or now - ct < quiet:
        left = (
            int(((ct + quiet) - now).total_seconds() // 60) + 1
            if ct
            else int(pol.get("quiet_min", 15))
        )
        return "waiting", "quiet", f"quiet period, head is too new ({left} min left)", None
    if prev_head != head:
        why = "first pass on this head" if prev_head is None else "new push since the last pass"
        return "waiting", "quiet", f"quiet period, {why}", None
    loc = local_cache.get(head)
    if loc is None:
        ok, detail = run_local_checks(head)
        loc = {"ok": ok, "detail": detail}
        local_cache[head] = loc
    if not loc["ok"]:
        return "held", "local-checks", "local checks fail: " + loc["detail"], None
    version, problem = claims.get(n, (None, "CHANGELOG not read"))
    if problem:
        return "held", "changelog", problem, None
    owner = claims.get(("owner", version))
    if owner is not None and owner != n:
        return "held", "version", f"version v{version} taken by #{owner}, rebase and bump", version
    if ("v" + version) in tags:
        return "held", "version", f"version v{version} is already tagged, rebase and bump", version
    latest = latest_version(tags)
    if latest and vkey(version) <= vkey(latest):
        return (
            "held",
            "version",
            f"version v{version} is not greater than the latest tag v{latest}",
            version,
        )
    return "ready", "ready", f"green, quiet and v{version} is new", version


def gather(pol, prs):
    """Shared reads for a pass: heads fetched, tags, CHANGELOG claims with version ownership."""
    fetch_heads(prs)
    tags = remote_tags()
    claims = {}
    for p in sorted(prs, key=lambda x: int(x["number"])):
        got = git(["rev-parse", f"refs/corelane/pr/{p['number']}"]).strip()
        if got != p["headRefOid"]:
            raise LaneError(
                f"#{p['number']} fetched head {got[:8]} is not the listed head {p['headRefOid'][:8]}"
            )
        try:
            claims[int(p["number"])] = changelog_claim(p["headRefOid"])
        except LaneError as e:
            claims[int(p["number"])] = (None, f"CHANGELOG diff unreadable: {e}")
    # The oldest PR (lowest number) claiming a usable version keeps it.
    latest = latest_version(tags)
    for p in sorted(prs, key=lambda x: int(x["number"])):
        v = claims[int(p["number"])][0]
        usable = v and ("v" + v) not in tags and (not latest or vkey(v) > vkey(latest))
        if usable and ("owner", v) not in claims:
            claims[("owner", v)] = int(p["number"])
    return tags, claims


# ---------------------------------------------------------------- merge and release


def clone_on_clean_main():
    branch = git(["symbolic-ref", "-q", "--short", "HEAD"], check=False).strip()
    if branch != "main":
        return False, f"local clone is on {branch or 'a detached HEAD'}, pull skipped"
    if git(["status", "--porcelain"]).strip():
        return False, "local clone has uncommitted changes, pull skipped"
    return True, ""


def merge_and_release(pr, version, pol, now):
    """(lines, record). Runs the merge once. Every step after the merge is reported, never retried."""
    n, head, title = int(pr["number"]), pr["headRefOid"], pr.get("title") or ""
    repo = pol["repo"]
    tag = "v" + version
    rec = {"pr": n, "sha": head, "version": tag, "title": title, "at": iso(now)}
    notes = changelog_notes(head, version)
    try:
        gh(
            [
                "pr",
                "merge",
                str(n),
                "-R",
                repo,
                "--squash",
                "--delete-branch",
                "--match-head-commit",
                head,
            ],
            raw=True,
        )
    except GhError as e:
        rec.update(result="merge-refused", detail=str(e)[:300])
        log({"pr": n, "decision": "merge-refused", "sha": head, "detail": str(e)[:300]}, now)
        return [], rec
    try:
        v = gh(["pr", "view", str(n), "-R", repo, "--json", "state,mergeCommit"]) or {}
    except GhError as e:
        v = {"state": f"unreadable ({e})"}
    state = v.get("state")
    merge_sha = ((v.get("mergeCommit") or {}).get("oid")) or ""
    if state != "MERGED":
        rec.update(result="not-merged", detail=f"merge call returned but PR state is {state}")
        log({"pr": n, "decision": "merge-unconfirmed", "sha": head, "detail": rec["detail"]}, now)
        return [
            f"{TAG} #{n} {title}: merge call returned but the PR is {state}, release skipped"
        ], rec
    rec["merge_sha"] = merge_sha
    log({"pr": n, "decision": "merged", "sha": head, "merge_sha": merge_sha, "version": tag}, now)
    lines = [f"{TAG} merged #{n} {tag} {title}"]
    problems = []
    clean, why = clone_on_clean_main()
    if clean:
        try:
            git(["pull", "-q", "--ff-only"], timeout=180)
        except LaneError as e:
            problems.append(f"local pull failed: {e}")
    else:
        rec["pull"] = why
    released = False
    try:
        gh(
            [
                "release",
                "create",
                tag,
                "-R",
                repo,
                "--target",
                "main",
                "--title",
                tag,
                "--notes",
                notes,
            ],
            raw=True,
        )
        released = True
    except GhError as e:
        problems.append(f"release {tag} failed: {e}")
    if released:
        try:
            tags = remote_tags()
            if tags.get(tag) != merge_sha:
                problems.append(
                    f"tag {tag} points at {(tags.get(tag) or 'nothing')[:8]}, not the merge {merge_sha[:8]}"
                )
        except LaneError as e:
            problems.append(f"tag check failed: {e}")
        try:
            p = (
                subprocess.run(shlex.split(SYNC_CMD), capture_output=True, text=True, timeout=600)
                if SYNC_CMD
                else None
            )
            if p is not None and p.returncode != 0:
                tail = [x for x in (p.stdout + "\n" + p.stderr).splitlines() if x.strip()][-1:]
                problems.append(f"core skills sync exit {p.returncode}: {' '.join(tail)[:200]}")
        except (OSError, subprocess.SubprocessError) as e:
            problems.append(f"core skills sync did not run: {type(e).__name__}")
    rec.update(
        result="released" if released and not problems else "after-merge-problem", problems=problems
    )
    log(
        {
            "pr": n,
            "decision": "released" if released else "release-failed",
            "sha": head,
            "detail": problems,
        },
        now,
    )
    for prob in problems:
        lines.append(f"{TAG} #{n} {tag} merged, but {prob}. Not retried, fix by hand.")
    return lines, rec


# ---------------------------------------------------------------- auto-fix


def _fixer():
    """autofix.py loaded from its path (the lanes share one copy)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("autofix", str(FIXER_PY))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {FIXER_PY}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fix_reason(status, kind, reason):
    """The reason as the fixer reads it. Fixable holds get the fixer's problem wording, holds only
    the owner can clear get a "needs me:" prefix (the fixer never starts a session on those)."""
    if status != "held":
        return reason
    if kind == "checks-red":
        return reason  # "checks red: ..."
    if kind == "merge-state" and re.search(r"\b(DIRTY|BEHIND)\b", reason or ""):
        return f"merge conflict or behind main, rebase on origin/main: {reason}"
    if kind == "version":
        return f"version needs a bump: {reason}"
    if kind == "local-checks":
        return reason  # "local checks fail: ..."
    if kind == "changelog":
        return f"changelog entry: {reason}"
    return f"needs me: {reason}"


def fixing(frec, head):
    """True while a fix session runs or waits on another live session, or after it gave up on
    this head (the fixer printed its own line), so the generic held alert stays quiet."""
    if not frec:
        return False
    if frec.get("running"):
        return True
    return any((frec.get(k) or {}).get("head") == head for k in ("deferred", "gave_up"))


# ---------------------------------------------------------------- pass


def tick():
    now = now_utc()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("core PR lane: another pass is running, skipped", file=sys.stderr)
            return
        _tick_locked(now)


def _tick_locked(now):
    st = load_json(STATE_FILE, {})
    prs_state = st.setdefault("prs", {})
    alerts = st.setdefault("alerts", {})
    out = []
    try:
        pol = load_policy()
        if not pol.get("enabled", True):
            st["disabled"] = True
            return
        st.pop("disabled", None)
        fix_state = st.setdefault("fix", {})
        fixer = _fixer()
        prs = [p for p in list_open(pol) if eligible(p, pol) is None]
        owner = owner_mode(pol)
        if owner:
            for p in prs:
                _, err = ensure_owner_label(p, pol, now)
                if err:
                    out.append(
                        f"{TAG} #{p['number']} could not add the {pol.get('owner_label')} label: {err}"
                    )
        open_nums = {str(p["number"]) for p in prs}
        tags, claims = gather(pol, prs) if prs else ({}, {})
        merged_one = False
        for pr in sorted(prs, key=lambda x: int(x["number"])):
            n, head = str(pr["number"]), pr["headRefOid"]
            rec = prs_state.get(n) or {}
            prev_head = rec.get("head")
            if prev_head != head:
                rec = {"head": head}
            local_cache = {head: rec["local"]} if rec.get("local") else {}
            if rec.get("refused") == head:
                status, kind, reason, version = (
                    "held",
                    "merge-refused",
                    rec.get("reason", "merge refused"),
                    None,
                )
            else:
                status, kind, reason, version = decide(
                    pr, pol, rec, prev_head, claims, tags, now, local_cache
                )
            if head in local_cache:
                rec["local"] = local_cache[head]
            if status == "ready" and owner:
                # Owner mode: every gate passed, the owner merges it by hand in version order.
                status, kind, reason = (
                    "owner",
                    "owner-queue",
                    f"ready for the core owner (v{version})",
                )
                rec["version"] = version
            if status == "ready" and merged_one:
                status, kind, reason = "waiting", "queued", "ready, queued behind this pass's merge"
            rec.update({"title": pr.get("title"), "url": pr.get("url"), "seen": iso(now)})
            if rec.get("status") != status or rec.get("kind") != kind:
                rec["since"] = iso(now)
            if rec.get("reason") != reason or rec.get("status") != status:
                log(
                    {"pr": int(n), "decision": status, "kind": kind, "sha": head, "detail": reason},
                    now,
                )
            rec.update({"status": status, "kind": kind, "reason": reason})
            prs_state[n] = rec
            if status == "ready" and not merged_one:
                merged_one = True
                if DRY_RUN:
                    out.append(f"{TAG} would_merge #{n} v{version} {pr.get('title')}")
                    log(
                        {
                            "pr": int(n),
                            "decision": "would_merge",
                            "sha": head,
                            "version": "v" + version,
                        },
                        now,
                    )
                    continue
                lines, mrec = merge_and_release(pr, version, pol, now)
                out.extend(lines)
                st.setdefault("merges", []).append(mrec)
                st["merges"] = st["merges"][-20:]
                if mrec.get("result") == "merge-refused":
                    rec.update(
                        status="held",
                        kind="merge-refused",
                        reason="merge refused: " + mrec["detail"],
                        refused=head,
                        since=iso(now),
                    )
                elif mrec.get("result") == "not-merged":
                    rec.update(
                        status="held",
                        kind="merge-refused",
                        reason=mrec["detail"],
                        refused=head,
                        since=iso(now),
                    )
                else:
                    prs_state.pop(n, None)
                    open_nums.discard(n)
                continue
            frec = fix_state.setdefault(n, {})
            freason = fix_reason(status, kind, reason)
            if DRY_RUN:
                if fixer.problem_of(status, freason, FIX_TARGET) and not frec.get("running"):
                    out.append(
                        f"{TAG} would_autofix #{n} ({fixer.problem_of(status, freason, FIX_TARGET)}) {pr.get('title')}"
                    )
            else:
                try:
                    line = fixer.consider(
                        FIX_TARGET,
                        TAG,
                        pol["repo"],
                        pol["self_login"],
                        pr,
                        status,
                        freason,
                        frec,
                        pol,
                        CACHE_DIR / "autofix",
                        now,
                    )
                except Exception as e:  # noqa: BLE001 - one PR's fixer error must not stop the lane
                    line = None
                    frec["error"] = f"{type(e).__name__}: {str(e)[:200]}"
                run = frec.get("running")
                if run and run.get("started") == iso(now):
                    log(
                        {
                            "pr": int(n),
                            "decision": "autofix-started",
                            "sha": head,
                            "detail": run.get("problem"),
                            "pid": run.get("pid"),
                        },
                        now,
                    )
                if line:
                    log(
                        {"pr": int(n), "decision": "autofix-gave-up", "sha": head, "detail": line},
                        now,
                    )
                    out.append(line)
            if status == "held" and kind in PERSON_KINDS and not fixing(frec, head):
                since = parse_ts(rec.get("since")) or now
                key = f"{n}:{kind}"
                last = parse_ts(alerts.get(key))
                due = now - since >= dt.timedelta(minutes=float(pol.get("hold_alert_min", 120)))
                quiet = last and now - last < dt.timedelta(
                    hours=float(pol.get("alert_every_h", 12))
                )
                if due and not quiet:
                    hours = int((now - since).total_seconds() // 3600)
                    out.append(f"{TAG} #{n} {pr.get('title')} held {hours}h: {reason}")
                    alerts[key] = iso(now)
        for n in list(prs_state):
            if n not in open_nums:
                del prs_state[n]
        if owner:
            owner_order(prs_state, claims, prs)
        st["merge_mode"] = "owner" if owner else "lane"
        for key in list(alerts):
            if key.split(":", 1)[0] not in open_nums:
                del alerts[key]
        for n in list(fix_state):
            if n not in open_nums and not fixer.run_alive(fix_state[n].get("running")):
                del fix_state[n]
        st["error_count"] = 0
        st.pop("last_error", None)
    except (
        GhError,
        PolicyError,
        LaneError,
        OSError,
        ValueError,
        KeyError,
        ImportError,
        subprocess.SubprocessError,
    ) as e:
        # Fail closed: nothing merges on a failed read, and the error is counted and shown.
        st["error_count"] = int(st.get("error_count", 0)) + 1
        st["last_error"] = f"{type(e).__name__}: {str(e)[:300]}"
        c = st["error_count"]
        if c == ERROR_ALERT_FIRST or (
            c > ERROR_ALERT_FIRST and (c - ERROR_ALERT_FIRST) % ERROR_ALERT_EVERY == 0
        ):
            out.append(f"{TAG} merge lane failing ({c} passes in a row): {st['last_error']}")
    finally:
        try:  # noqa: SIM105
            drop_refs()
        except (LaneError, OSError, subprocess.SubprocessError):
            pass
        st["updated"] = iso(now)
        st["dry_run"] = DRY_RUN
        write_json(STATE_FILE, st)
        if out:
            print("\n".join(out))


def check_one(n):
    """Read-only decision for one PR. Uses the recorded state for the quiet rule, writes nothing."""
    now = now_utc()
    pol = load_policy()
    allp = list_open(pol)
    hit = [p for p in allp if int(p["number"]) == n]
    if not hit:
        print(json.dumps({"pr": n, "status": "not an open PR"}))
        return
    skip = eligible(hit[0], pol)
    if skip:
        print(json.dumps({"pr": n, "status": "skip", "reason": skip}, indent=2))
        return
    prs = [p for p in allp if eligible(p, pol) is None]
    st = load_json(STATE_FILE, {})
    rec = (st.get("prs") or {}).get(str(n)) or {}
    try:
        tags, claims = gather(pol, prs)
        head = hit[0]["headRefOid"]
        cache = {head: rec["local"]} if rec.get("head") == head and rec.get("local") else {}
        status, kind, reason, version = decide(
            hit[0], pol, rec, rec.get("head"), claims, tags, now, cache
        )
    finally:
        drop_refs()
    fixer = _fixer()
    frec = (st.get("fix") or {}).get(str(n)) or {}
    print(
        json.dumps(
            {
                "pr": n,
                "head": hit[0]["headRefOid"],
                "status": status,
                "kind": kind,
                "reason": reason,
                "version": version,
                "enabled": bool(pol.get("enabled", True)),
                "merge_mode": "owner" if owner_mode(pol) else "lane",
                "autofix_problem": fixer.problem_of(
                    status, fix_reason(status, kind, reason), FIX_TARGET
                ),
                "autofix": {k: frec[k] for k in ("running", "deferred", "gave_up") if frec.get(k)},
            },
            indent=2,
        )
    )


def main(argv):
    cmd = argv[0] if argv else "tick"
    if cmd == "tick" and len(argv) <= 1:
        tick()
        return 0
    if cmd == "status":
        print(json.dumps(load_json(STATE_FILE, {}), indent=2))
        return 0
    if cmd == "check" and len(argv) == 2 and argv[1].isdigit():
        try:
            check_one(int(argv[1]))
        except (GhError, PolicyError, LaneError, ImportError) as e:
            print(f"check failed: {e}", file=sys.stderr)
            return 1
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
