"""Open PRs in the owner's other repos (the ones the consumer lists in review_config) that need me.

Repos come from `repo_reviews` in review_config (none configured is an empty page). A PR needs me when a check is failing,
when it is green and mergeable but nothing merged it for 30 minutes, or when the owner's review is requested.
For each failing check the job log is read once per head and the files it names are listed, so the
card says exactly what holds the PR. Read only: no writes to GitHub from here. Python 3.9.

Open issues: every open issue the owner opened or am assigned in these repos, with who moves next.
The last human comment is someone else's -> Needs me ("replied"). Mine and quiet for ISSUE_QUIET_DAYS ->
Needs me ("quiet", nudge or close). Otherwise it waits on the other side. Read only, like the PRs.

GET /api/repo-reviews -> {generated_utc, repos: [{repo, error, needs_me, in_progress, acted,
                          issues_need, issues_waiting, issues_error}], counts}
counts.needs_me and counts.in_progress include the issue rows, so the badge counts them.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import threading
import time

import own_lane
import paths
import review_acted
import review_config as cfg
import swr

GH = os.environ.get("REPO_REVIEWS_GH_BIN", paths.which("gh"))
SHIPPED_DAYS = 14
# The core merge lane (the consumer's core_pr_lane, every 5 min) checks the owner's core PRs. In lane mode
# it merges green ones after a quiet period. In owner mode the core owner merges by hand in version order:
# a PR that clears every gate is status "owner", work in flight on the owner's side, never mine. A PR it
# waits on is moving, a PR it holds needs me with the lane's reason.
CORE_LANE_STATE = os.environ.get("CORE_LANE_STATE") or str(
    paths.agent_home() / "cache" / "core-pr-lane" / "lane-state.json"
)
CORE_LANE_FRESH_S = 900  # 3 missed passes means the lane is not running
TTL_S = 60
ISSUE_QUIET_DAYS = int(os.environ.get("REPO_REVIEWS_ISSUE_QUIET_DAYS", "7"))
ISSUE_FIELDS = "number,title,url,author,assignees,comments,createdAt,updatedAt,labels"
STALE_GREEN_S = 30 * 60
# Aggregate jobs only restate the others, so their logs name no files of their own.
AGGREGATE = {"gate", "changes"}
_EXT = r"(?:py|ps1|psm1|sh|ts|tsx|js|mjs|css|json|ya?ml|md|tf)"
_PATH = r"((?:[\w.-]+/)*[\w.-]+\." + _EXT + r")"
# Finding-shaped mentions only. The command line that starts a linter names every input file,
# so a bare path is not evidence. These shapes are what ruff, biome, shellcheck, eslint and
# PSScriptAnalyzer print for a real finding.
FINDING_RES = [
    re.compile(r"(?:^|\s)" + _PATH + r":\d+"),  # path:line (ruff, shellcheck, tsc, eslint)
    re.compile(r"(?:Would reformat:|-->|In)\s+" + _PATH),  # ruff format, ruff full, shellcheck tty
    re.compile(r"^\s*" + _PATH + r"\s+(?:format|lint|assist)\b"),  # biome
]
BASENAME_ROW = re.compile(
    r"\b([\w.-]+\.(?:ps1|psm1))\s+\d+\s"
)  # PSScriptAnalyzer table: ScriptName Line
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s?")

_lock = threading.Lock()
_cache = {"at": 0.0, "data": None}
_logs = {}  # (repo, job id) -> files


class RepoReviewError(Exception):
    pass


def _self():
    return cfg.owner()


def _repos():
    return cfg.repo_reviews()


def _slugs():
    return {r.split("/", 1)[1].lower(): r for r in _repos()}


def _autofix_lanes():
    return cfg.map_of("autofix_lanes")


def _core_repo():
    return cfg.core_lane_repo()


def _gh(args, timeout=60, raw=False):
    try:
        p = subprocess.run([GH] + args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RepoReviewError(f"gh failed: {e}") from e
    if p.returncode != 0:
        raise RepoReviewError(f"gh {' '.join(args[:3])}: {p.stderr.strip()[:300]}")
    if raw:
        return p.stdout
    return json.loads(p.stdout) if p.stdout.strip() else {}


def _ts(s):
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _checks(rollup):
    newest = {}
    for c in rollup or []:
        name = c.get("name") or c.get("context") or "?"
        when = c.get("completedAt") or c.get("startedAt") or ""
        if name not in newest or when >= newest[name]["when"]:
            state = (c.get("conclusion") or c.get("state") or c.get("status") or "").upper()
            newest[name] = {
                "name": name,
                "when": when,
                "state": state,
                "url": c.get("detailsUrl") or "",
            }
    red_states = (
        "FAILURE",
        "ERROR",
        "TIMED_OUT",
        "CANCELLED",
        "ACTION_REQUIRED",
        "STARTUP_FAILURE",
    )
    ok_states = ("SUCCESS", "NEUTRAL", "SKIPPED", "STALE")
    red = [v for v in newest.values() if v["state"] in red_states]
    pending = [
        v for v in newest.values() if v["state"] not in red_states and v["state"] not in ok_states
    ]
    return list(newest.values()), red, pending


def _core_lane(now=None):
    """Per-PR records of the core merge lane. {} when absent, stale, failing, off or a dry run.
    Owner mode records carry status "owner" with queue, queue_of, blocked_by and queue_text."""
    try:
        with open(CORE_LANE_STATE) as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        return {}
    if (
        not isinstance(st, dict)
        or st.get("disabled")
        or st.get("dry_run")
        or int(st.get("error_count") or 0)
    ):
        return {}
    if (now if now is not None else time.time()) - _ts(st.get("updated")) > CORE_LANE_FRESH_S:
        return {}
    return st.get("prs") or {}


def _core_owner_mode():
    """True when the core lane runs in owner mode (the core owner merges, the lane never does)."""
    try:
        with open(CORE_LANE_STATE) as fh:
            return str((json.load(fh) or {}).get("merge_mode") or "") == "owner"
    except (OSError, ValueError, AttributeError):
        return False


def _pr_files(repo, pr):
    out = _gh(
        ["api", f"repos/{repo}/pulls/{pr}/files", "--paginate", "--jq", ".[].filename"],
        raw=True,
        timeout=90,
    )
    return set(out.split())


def _failing_files(repo, pr, check, files_cache):
    """Files a failing job's log names that the PR also changes (newest log, cached per job)."""
    m = re.search(r"/job/(\d+)", check.get("url") or "")
    if not m or check["name"] in AGGREGATE:
        return []
    key = (repo, m.group(1))
    if key not in _logs:
        try:
            log = _gh(
                ["api", f"repos/{repo}/actions/jobs/{m.group(1)}/logs", "--allow-escape-sequences"],
                raw=True,
                timeout=90,
            )
            log = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", log)
        except RepoReviewError:
            return []
        if "files" not in files_cache:
            try:
                files_cache["files"] = _pr_files(repo, pr)
            except RepoReviewError:
                files_cache["files"] = set()
        changed = files_cache["files"]
        by_base = {}
        for f in changed:
            by_base.setdefault(f.rsplit("/", 1)[-1], []).append(f)
        hits = []
        for line in log.splitlines():
            line = STAMP.sub("", line)
            found = [m.group(1) for rx in FINDING_RES for m in rx.finditer(line)]
            found += [x for b in BASENAME_ROW.findall(line) for x in by_base.get(b, [])]
            for f in found:
                f = f.lstrip("./")
                if (not changed or f in changed) and f not in hits:
                    hits.append(f)
        _logs[key] = hits[:12]
    return _logs[key]


def _repo(repo):
    fields = (
        "number,title,url,author,headRefOid,isDraft,mergeable,mergeStateStatus,"
        "reviewRequests,statusCheckRollup,createdAt,updatedAt,autoMergeRequest"
    )
    prs = (
        _gh(["pr", "list", "-R", repo, "--state", "open", "--limit", "50", "--json", fields]) or []
    )
    tomb = review_acted.active(repo)
    lane_target = _autofix_lanes().get(repo)
    lane_st = own_lane.load(lane_target) if lane_target else {}
    lane_live = bool(lane_target) and own_lane.fresh(lane_st)
    core_lane = _core_lane() if _core_repo() and repo == _core_repo() else {}
    core_owner = bool(_core_repo()) and repo == _core_repo() and _core_owner_mode()
    needs, progress = [], []
    now = time.time()
    for p in prs:
        if review_acted.hides(tomb, p.get("number"), p.get("headRefOid")):
            continue
        allc, red, pending = _checks(p.get("statusCheckRollup"))
        files_cache = {}
        row = {
            "repo": repo,
            "slug": repo.split("/", 1)[1].lower(),
            "pr": p["number"],
            "title": p.get("title") or "",
            "url": p.get("url") or "",
            "author": (p.get("author") or {}).get("login") or "",
            "mine": (p.get("author") or {}).get("login") == _self(),
            "head_sha": p.get("headRefOid") or "",
            "draft": bool(p.get("isDraft")),
            "updated": p.get("updatedAt"),
            "created": p.get("createdAt"),
            "auto_merge": bool(p.get("autoMergeRequest")),
            "checks": {"total": len(allc), "red": len(red), "pending": len(pending)},
            "failing": [
                {
                    "name": c["name"],
                    "url": c["url"],
                    "files": _failing_files(repo, p["number"], c, files_cache),
                }
                for c in red
                if c["name"] not in AGGREGATE
            ],
            "running": [c["name"] for c in pending],
        }
        asked = any(
            (r.get("login") or r.get("name")) == _self() for r in p.get("reviewRequests") or []
        )
        green = not red and not pending
        af = (
            own_lane.autofix(lane_st, p["number"], row["head_sha"])
            if lane_live and row["mine"]
            else None
        )
        if af:
            # The lane never merges here: GitHub (the ops center) or the core owner (core) does.
            after = cfg.map_of("autofix_after").get(lane_target, "")
            af = dict(
                af, text=af["text"].replace("The lane merges it once it clears.", after).strip()
            )
        row["autofix"] = af
        cl = core_lane.get(str(p["number"])) if row["mine"] else None
        if cl and cl.get("head") != row["head_sha"]:
            cl = None  # recorded for an older head, the lane has not seen this push yet
        if af and af["state"] in ("running", "deferred"):
            row.update(
                state="auto-fixing" if af["state"] == "running" else "session on it", working=True
            )
            progress.append(row)
        elif (
            af
            and af["state"] in ("gave_up", "waiting_on")
            and (red or p.get("mergeable") == "CONFLICTING")
        ):
            row.update(kind="checks" if red else "conflict", why=af["text"])
            needs.append(row)
        elif cl and cl.get("status") == "owner" and not red:
            where = cl.get("queue_text") or "in version order"
            row.update(
                state=f"with the core owner: v{cl.get('version')}, {where}",
                owner_queue={
                    "version": cl.get("version"),
                    "place": cl.get("queue"),
                    "of": cl.get("queue_of"),
                    "blocked_by": cl.get("blocked_by") or [],
                },
            )
            progress.append(row)
        elif cl and cl.get("status") in ("waiting", "ready") and not red:
            verb = "lane checking" if core_owner else "merging soon (lane)"
            row.update(state=f"{verb}: {cl.get('reason') or 'waiting'}")
            progress.append(row)
        elif cl and cl.get("status") == "held":
            kind = (
                "checks" if red else "conflict" if p.get("mergeable") == "CONFLICTING" else "stale"
            )
            row.update(
                kind=kind, why=f"Merge lane holds it: {cl.get('reason') or 'no reason recorded'}."
            )
            needs.append(row)
        elif row["draft"]:
            row.update(state="draft")
            progress.append(row)
        elif red:
            names = ", ".join(c["name"] for c in row["failing"]) or ", ".join(
                c["name"] for c in red
            )
            row.update(kind="checks", why=f"Checks failing: {names}.")
            needs.append(row)
        elif asked:
            row.update(kind="review", why="The owner's review is requested.")
            needs.append(row)
        elif pending:
            row.update(state=f"checks running ({len(pending)})")
            progress.append(row)
        elif (
            green
            and p.get("mergeable") != "CONFLICTING"
            and now - _ts(p.get("updatedAt")) > STALE_GREEN_S
            and not row["auto_merge"]
        ):
            row.update(kind="stale", why="Green for over 30 minutes and nothing merged it.")
            needs.append(row)
        elif p.get("mergeable") == "CONFLICTING":
            row.update(kind="conflict", why="Merge conflict.")
            needs.append(row)
        else:
            row.update(state="green, merging" if row["auto_merge"] else "green")
            progress.append(row)
    review_acted.flag_missed(needs + progress, repo)
    return {
        "repo": repo,
        "slug": repo.split("/", 1)[1].lower(),
        "error": None,
        "needs_me": needs,
        "in_progress": progress,
        "acted": review_acted.public(tomb, {p.get("number") for p in prs}),
    }


def _is_bot(login):
    login = str(login or "")
    return login.endswith("[bot]") or login.startswith("app/") or login in ("github-actions",)


def _issue_row(repo, i, now):
    """One open issue -> (bucket, row). bucket is need or waiting."""
    comments = [
        c for c in i.get("comments") or [] if not _is_bot((c.get("author") or {}).get("login"))
    ]
    last = comments[-1] if comments else None
    last_by = (
        ((last or {}).get("author") or {}).get("login")
        or (i.get("author") or {}).get("login")
        or ""
    )
    last_at = (last or {}).get("createdAt") or i.get("createdAt") or ""
    owner = repo.split("/", 1)[0]
    row = {
        "repo": repo,
        "slug": repo.split("/", 1)[1].lower(),
        "issue": i["number"],
        "title": i.get("title") or "",
        "url": i.get("url") or "",
        "author": (i.get("author") or {}).get("login") or "",
        "comments": len(comments),
        "last_by": last_by,
        "last_at": last_at,
        "updated": i.get("updatedAt"),
    }
    days = (now - _ts(last_at)) / 86400 if last_at else 0
    if last_by and last_by != _self():
        body = " ".join(str((last or {}).get("body") or "").split())
        row.update(kind="replied", why=f"{last_by} has the last word.", excerpt=body[:220])
        return "need", row
    if days >= ISSUE_QUIET_DAYS:
        row.update(kind="quiet", why=f"No reply in {int(days)} days. Nudge it or close it.")
        return "need", row
    waits = owner if owner != _self() else "a reply"
    row.update(state=f"waiting on {waits}")
    return "waiting", row


def _issues(repo):
    """(need, waiting) issue rows for repo: opened by me or assigned to me, newest activity first."""
    seen = {}
    if not _self():
        return [], []  # no owner configured: whose issues is not known
    for flag in ("--author", "--assignee"):
        rows = _gh(
            [
                "issue",
                "list",
                "-R",
                repo,
                "--state",
                "open",
                flag,
                _self(),
                "--limit",
                "30",
                "--json",
                ISSUE_FIELDS,
            ]
        )
        for i in rows or []:
            seen[i["number"]] = i
    need, waiting = [], []
    now = time.time()
    for i in sorted(seen.values(), key=lambda x: x.get("updatedAt") or "", reverse=True):
        bucket, row = _issue_row(repo, i, now)
        (need if bucket == "need" else waiting).append(row)
    return need, waiting


def _shipped(repo):
    """PRs merged in the last SHIPPED_DAYS days, newest first."""
    rows = _gh(
        [
            "pr",
            "list",
            "-R",
            repo,
            "--state",
            "merged",
            "--limit",
            "100",
            "--json",
            "number,title,url,author,mergedAt,mergeCommit",
        ]
    )
    cutoff = time.time() - SHIPPED_DAYS * 86400
    out = []
    for p in rows or []:
        if _ts(p.get("mergedAt")) < cutoff:
            continue
        out.append(
            {
                "pr": p["number"],
                "title": p.get("title") or "",
                "url": p.get("url") or "",
                "author": (p.get("author") or {}).get("login") or "",
                "merged": p.get("mergedAt"),
                "sha": ((p.get("mergeCommit") or {}).get("oid") or "")[:8],
            }
        )
    return sorted(out, key=lambda x: x["merged"] or "", reverse=True)


def _lane_status(repo):
    """Which lane works this repo and whether it is healthy, for the tab footer and alert banner."""
    if repo == _core_repo():
        try:
            with open(CORE_LANE_STATE) as fh:
                st = json.load(fh)
        except (OSError, ValueError):
            st = {}
        name = "core lane, owner mode" if st.get("merge_mode") == "owner" else "core merge lane"
    elif repo in _autofix_lanes():
        st = own_lane.load(_autofix_lanes()[repo])
        name = "own-PR auto-fix lane"
    else:
        return {"name": None, "updated": None, "error": None}
    err = None
    if not st:
        err = f"The {name} has no state yet."
    elif st.get("disabled"):
        err = f"The {name} is switched off in its policy."
    elif int(st.get("error_count") or 0):
        err = f"The {name} is failing: {st.get('last_error') or 'no error recorded'}"
    elif time.time() - _ts(st.get("updated")) > CORE_LANE_FRESH_S:
        err = f"The {name} has not run for over 15 minutes."
    return {"name": name, "updated": st.get("updated"), "error": err}


def _with_issues(entry):
    """Adds the issue rows to a repo entry. An unreadable issue list never hides the PRs."""
    try:
        need, waiting = _issues(entry["repo"])
        entry.update(issues_need=need, issues_waiting=waiting, issues_error=None)
    except (RepoReviewError, KeyError, TypeError) as e:
        entry.update(issues_need=[], issues_waiting=[], issues_error=str(e)[:300])
    return entry


def get(force=False):
    gen = review_acted.generation()
    with _lock:
        if not force and _cache["data"]:
            age = time.time() - _cache["at"]
            if age < TTL_S:
                return _cache["data"]
            if age < swr.MAX_STALE_S:
                # Serve the last view at once and refresh it in the background (one at a time).
                swr.kick(__name__, lambda: get(force=True))
                return _cache["data"]
    data = _build()
    if gen != review_acted.generation():
        data = _build()  # a write landed while the first read was in flight, read again past it
    with _lock:
        if gen == review_acted.generation():
            _cache.update(at=time.time(), data=data)
    return data


def _build():
    repos = []
    for r in _repos():
        try:
            entry = _repo(r)
        except RepoReviewError as e:
            slug = r.split("/", 1)[1].lower()
            entry = {
                "repo": r,
                "slug": slug,
                "error": str(e),
                "needs_me": [],
                "in_progress": [],
                "acted": [],
            }
        entry = _with_issues(entry)
        try:
            entry["shipped"] = _shipped(r)
        except RepoReviewError:
            entry["shipped"] = []
        entry["label"] = cfg.map_of("repo_labels").get(r, entry["slug"])
        entry["lane"] = _lane_status(r)
        entry["counts"] = {
            "needs_me": len(entry["needs_me"]) + len(entry["issues_need"]),
            "in_progress": len(entry["in_progress"]) + len(entry["issues_waiting"]),
            "shipped": len(entry["shipped"]),
        }
        repos.append(entry)
    data = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "repos": repos,
        "counts": {
            "needs_me": sum(len(r["needs_me"]) + len(r["issues_need"]) for r in repos),
            "in_progress": sum(len(r["in_progress"]) + len(r["issues_waiting"]) for r in repos),
            "issues_need": sum(len(r["issues_need"]) for r in repos),
        },
    }
    with _lock:
        _cache.update(at=time.time(), data=data)
    return data


def find(slug, pr):
    """The live row for one PR, for Discuss with the ops center. None when it is not open."""
    for r in get(force=True)["repos"]:
        if r["slug"] == slug:
            for row in r["needs_me"] + r["in_progress"]:
                if row["pr"] == int(pr):
                    return row
    return None


def rerun(payload):
    """Re-run the failed jobs of every failing run at the head the owner saw (a flaky runner, a fixed key,
    a file another session has since fixed). Pinned: refused when the PR moved on."""
    slug = str(payload.get("repo") or "")
    repo = _slugs().get(slug)
    if not repo:
        raise ValueError(f"unknown repo {slug!r}")
    pr, head = int(payload.get("pr")), str(payload.get("head_sha") or "")
    live = _gh(["api", f"repos/{repo}/pulls/{pr}"])
    if live.get("state") != "open":
        merged = bool(live.get("merged"))
        review_acted.record(
            repo, pr, head, "merged" if merged else "closed", title=live.get("title") or ""
        )
        _cache.update(at=0.0, data=None)
        review_acted.bump()
        return {
            "pr": pr,
            "done": [f"#{pr} is already {'merged' if merged else 'closed'}"],
            "already": True,
        }
    if not head or (live.get("head") or {}).get("sha") != head:
        raise RepoReviewError(f"PR #{pr} moved on since I looked. Refresh and try again.")
    runs = _gh(
        [
            "api",
            f"repos/{repo}/actions/runs?head_sha={head}&per_page=30",
            "--jq",
            "[.workflow_runs[]|{id,conclusion}]",
        ]
    )
    failed = [
        r["id"]
        for r in runs or []
        if r.get("conclusion") in ("failure", "timed_out", "cancelled", "startup_failure")
    ]
    if not failed:
        return {"pr": pr, "done": ["Nothing failed at this head, nothing to re-run"]}
    for rid in failed:
        _gh(["run", "rerun", str(rid), "-R", repo, "--failed"], raw=True)
    _cache.update(at=0.0, data=None)
    review_acted.bump()
    return {"pr": pr, "done": [f"Re-running the failed jobs of {len(failed)} run(s)"]}


if __name__ == "__main__":
    print(json.dumps(get(force=True), indent=1)[:6000])
