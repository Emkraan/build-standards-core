#!/usr/bin/env python3
"""
ref_status.py

Purpose: Live status of the pull requests and tracker tickets named in a block of text, so anything that summarizes state files
         (the Action Center analysis, the morning sitrep) can tell work that is already finished from work that is still open.
         State live notes lag: a closing session may log the outcome in a decisions log and never supersede the live note, and a
         summarizer that trusts the note re-surfaces finished work. This is the plug-in behind OPSCENTER_REF_STATUS
         (resolve, done_lines, finished).

Stdlib only. Read only. Reads the code host through the gh CLI and the tracker through a driver command. Results are cached for
CACHE_TTL_S in <agent home>/cache/ref-status.json.

Parameters (environment):
  REF_STATUS_REPOS    JSON {"<prefix>": "owner/repo", "default": "owner/repo"}: the name written before "PR #12" in a text and the
                      repository it means; "default" is the repository of a bare "PR #12" (default {"default": "owner/primary"})
  REF_STATUS_KEY_REGEX the ticket key pattern (default KEY-123 style)
  REF_STATUS_TRACKER_CMD a JSON list that runs one tracker call (`<cmd> <tool> '<json args>'`, DESIGN.md 12.15); none means ticket
                      lookups are skipped and reported as an error
  REF_STATUS_SITE     the tracker site id the calls take
  REF_STATUS_APPLY_WORKFLOW the apply workflow name checked for an "approve the apply" item (default terraform-apply)

CLI:
  ref_status.py [--json] [file ...]   text from files, or stdin when none given
  --json prints {"refs": {...}, "done": [...], "errors": [...]}
  default prints a compact block of the refs that are finished.

Test hooks: REF_STATUS_GH (gh binary), REF_STATUS_CACHE (cache file), REF_STATUS_NO_CACHE=1.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time


def _read(path):
    with open(path, errors="ignore") as fh:
        return fh.read()


def _json_env(name, default):
    try:
        v = json.loads(os.environ.get(name) or "null")
    except ValueError:
        v = None
    return v if v is not None else default


HOME = os.path.expanduser("~")
GH = os.environ.get("REF_STATUS_GH") or shutil.which("gh") or "gh"
AGENT_HOME = os.environ.get("OPSCENTER_AGENT_HOME") or os.path.join(
    os.environ.get("OPSCENTER_ROOT") or os.path.join(HOME, ".opscenter"), "agent"
)
CACHE = os.environ.get("REF_STATUS_CACHE") or os.path.join(AGENT_HOME, "cache", "ref-status.json")
CACHE_TTL_S = 600
CLOUD = os.environ.get("REF_STATUS_SITE", "")
TRACKER_CMD = [str(a) for a in _json_env("REF_STATUS_TRACKER_CMD", [])]

_REPOS = _json_env("REF_STATUS_REPOS", {"default": "owner/primary"})
_DEFAULT_REPO = str(_REPOS.get("default") or "owner/primary")
REPOS = {str(k).lower(): str(v) for k, v in _REPOS.items() if k != "default"}
REPOS.setdefault("default", _DEFAULT_REPO)
# "<prefix> PR #215", "<prefix> #217", "PR #215" (the default repository). Longest names first so a longer name wins over its prefix.
_PREFIXES = (
    "|".join(sorted((re.escape(k) for k in REPOS if k != "default"), key=len, reverse=True))
    or "(?!)"
)
PR_RE = re.compile(r"\b(?:(" + _PREFIXES + r")\s+(?:PRs?\s*)?|PRs?\s+)#(\d{1,5})\b", re.I)
JIRA_RE = re.compile(os.environ.get("REF_STATUS_KEY_REGEX") or r"\b([A-Z][A-Z0-9]{1,9}-\d{2,6})\b")
JIRA_DONE = {
    "done",
    "closed",
    "resolved",
    "canceled",
    "cancelled",
    "completed",
    "won't do",
    "rejected",
}


# Items an automation raised write PR numbers loosely ("#340", "PR 229", "PRs 229 and 230"), always in the default repository.
# Only the auto- close check reads them, the shared PR_RE stays strict.
_BARE_HASH_RE = re.compile(r"(?<![\w&/#])#(\d{2,5})\b")
_PR_LIST_RE = re.compile(r"\bPRs?\s+#?\d{1,5}(?:\s*(?:,|and|&)\s*#?\d{1,5})*", re.I)


def extract_loose_prs(text):
    """PR numbers an automation item names without a repo prefix, in the default repository, as (repo, number)."""
    nums = set()
    for m in _BARE_HASH_RE.finditer(text or ""):
        nums.add(int(m.group(1)))
    for m in _PR_LIST_RE.finditer(text or ""):
        nums.update(int(n) for n in re.findall(r"\d{1,5}", m.group(0)))
    return {(_DEFAULT_REPO, n) for n in nums}


def extract_refs(text):
    """Return (prs, keys): prs is a set of (repo_full, number), keys a set of Jira keys."""
    prs, keys = set(), set()
    for m in PR_RE.finditer(text or ""):
        repo = REPOS.get((m.group(1) or "default").lower(), _DEFAULT_REPO)
        prs.add((repo, int(m.group(2))))
    for m in JIRA_RE.finditer(text or ""):
        keys.add(m.group(1).upper())
    return prs, keys


def _load_cache():
    if os.environ.get("REF_STATUS_NO_CACHE"):
        return {}
    try:
        with open(CACHE) as fh:
            data = json.load(fh)
        now = time.time()
        return {k: v for k, v in data.items() if now - v.get("at", 0) < CACHE_TTL_S}
    except (OSError, ValueError):
        return {}


def _save_cache(data):
    if os.environ.get("REF_STATUS_NO_CACHE"):
        return
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        tmp = CACHE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, CACHE)
    except OSError:
        pass


def _run(cmd, timeout=60):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def _gh_status(prs, errors):
    """One GraphQL call per repo. Returns {ref: {...}}."""
    out = {}
    by_repo = {}
    for repo, n in prs:
        by_repo.setdefault(repo, []).append(n)
    for repo, nums in by_repo.items():
        owner, name = repo.split("/")
        parts = [
            "n%d: pullRequest(number: %d) { state mergedAt closedAt title }" % (n, n)  # noqa: UP031
            for n in sorted(nums)
        ]
        q = 'query { repository(owner: "%s", name: "%s") { %s } }' % (owner, name, " ".join(parts))  # noqa: UP031
        try:
            rc, so, se = _run([GH, "api", "graphql", "-f", "query=" + q])
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append("gh %s: %s" % (repo, exc))  # noqa: UP031
            continue
        try:
            data = json.loads(so or "{}")
        except ValueError:
            data = {}
        repo_data = ((data.get("data") or {}).get("repository")) or {}
        if rc != 0 and not repo_data:
            errors.append("gh %s rc=%s %s" % (repo, rc, (se or so)[:160].strip()))  # noqa: UP031
            continue
        short = name.lower()
        for n in nums:
            pr = repo_data.get("n%d" % n)  # noqa: UP031
            ref = "%s PR #%d" % (short, n)  # noqa: UP031
            if not pr:
                out[ref] = {"kind": "pr", "state": "NOT_FOUND", "done": False}
                continue
            state = pr.get("state")
            out[ref] = {
                "kind": "pr",
                "state": state,
                "done": state in ("MERGED", "CLOSED"),
                "when": pr.get("mergedAt") or pr.get("closedAt"),
                "title": (pr.get("title") or "")[:90],
            }
    return out


def _jira_query(keys):
    """One JQL search. Returns the issues list, or None when the query failed."""
    args = {
        "cloudId": CLOUD,
        "jql": "key in (%s)" % ",".join(sorted(keys)),  # noqa: UP031
        "fields": [
            "status",
            "resolution",
            "assignee",
            "summary",
            "statuscategorychangedate",
            "issuetype",
        ],
        "maxResults": 100,
    }
    try:
        if not TRACKER_CMD:
            return None
        rc, so, se = _run([*TRACKER_CMD, "searchJiraIssuesUsingJql", json.dumps(args)], timeout=90)
        payload = json.loads(json.loads(so)["result"]["content"][0]["text"])
    except Exception:  # driver error text, transport failure or shape change
        return None
    if not isinstance(payload, dict) or "issues" not in payload:
        return None
    return payload["issues"]


def _jira_issues(keys, errors, depth=0):
    """Search in one call; when JQL rejects the batch (one unknown key fails the whole
    query), split it in half and retry, so one bad key costs a few calls, not all."""
    issues = _jira_query(keys)
    if issues is not None:
        return issues
    if len(keys) == 1 or depth > 6:
        if len(keys) > 1:
            errors.append("jira: query failed for %d keys" % len(keys))  # noqa: UP031
        return []
    ks = sorted(keys)
    mid = len(ks) // 2
    return _jira_issues(set(ks[:mid]), errors, depth + 1) + _jira_issues(
        set(ks[mid:]), errors, depth + 1
    )


def _jira_status(keys, errors):
    out = {}
    if not keys:
        return out
    found = set()
    for issue in _jira_issues(set(keys), errors):
        f = issue.get("fields") or {}
        status = ((f.get("status") or {}).get("name")) or ""
        cat = (((f.get("status") or {}).get("statusCategory")) or {}).get("key")
        key = issue.get("key")
        found.add(key)
        out[key] = {
            "kind": "jira",
            "state": status,
            "done": status.lower() in JIRA_DONE or cat == "done",
            "assignee": ((f.get("assignee") or {}).get("displayName")),
            "title": (f.get("summary") or "")[:90],
            "status_changed": f.get("statuscategorychangedate") or "",
            "type": ((f.get("issuetype") or {}).get("name")) or "",
        }
    # A JQL "key in" with one unknown key fails the whole query, so an empty result
    # with keys asked is reported, not treated as "all open".
    if not found and keys:
        errors.append("jira: no issues returned for %d keys" % len(keys))  # noqa: UP031
    return out


# --- "approve the apply" items --------------------------------------------------
# A merged PR is finished as a PR, but an item whose next step is to approve the apply or
# deployment may still be real (a gated run waits) or already gone (an ungated root applies on
# merge, so nobody ever had to approve). The terraform-apply run for the merge commit decides.
APPROVE_APPLY_RE = re.compile(
    r"\bapprov\w*\b[^.\n]{0,80}?\b(?:apply|applies|deployments?|deploy)\b"
    r"|\b(?:apply|applies|deployments?|deploy)\b[^.\n]{0,40}?\bapproval\b",
    re.I,
)
APPLY_WORKFLOW = os.environ.get("REF_STATUS_APPLY_WORKFLOW", "terraform-apply")


def _gh_json(args, timeout=60):
    rc, so, se = _run([GH] + args, timeout=timeout)
    if rc != 0:
        raise RuntimeError("gh rc=%s %s" % (rc, (se or so)[:160].strip()))  # noqa: UP031
    return json.loads(so or "null")


def _apply_status(repo, number, errors):
    """State of the terraform-apply run for the merge commit of repo PR number.
    Returns {"state": applied|pending|failed|no_run|unknown, "run": id, ...}. Only a completed
    success with no pending_deployments is "applied". Any read error is "unknown" (an item
    never closes on a failed read)."""
    try:
        pr = _gh_json(["api", "repos/%s/pulls/%d" % (repo, number)])  # noqa: UP031
        sha = (pr or {}).get("merge_commit_sha") if (pr or {}).get("merged") else None
        if not sha:
            return {"state": "unknown", "why": "no merge commit"}
        runs = (
            _gh_json(
                [
                    "run",
                    "list",
                    "-R",
                    repo,
                    "--commit",
                    sha,
                    "--limit",
                    "30",
                    "--json",
                    "databaseId,workflowName,status,conclusion,createdAt",
                ]
            )
            or []
        )
        applies = sorted(
            (r for r in runs if r.get("workflowName") == APPLY_WORKFLOW),
            key=lambda r: r.get("createdAt") or "",
        )
        if not applies:
            return {"state": "no_run", "sha": sha[:10]}
        run = applies[-1]
        out = {
            "run": run["databaseId"],
            "sha": sha[:10],
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "when": run.get("createdAt"),
        }
        if run.get("status") != "completed":
            out["state"] = "pending"
            return out
        if run.get("conclusion") != "success":
            out["state"] = "failed"
            return out
        pend = _gh_json(
            ["api", "repos/%s/actions/runs/%s/pending_deployments" % (repo, run["databaseId"])]  # noqa: UP031
        )
        if not isinstance(pend, list):
            out["state"] = "unknown"
            return out
        out["pending"] = len(pend)
        out["state"] = "applied" if not pend else "pending"
        return out
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        errors.append("apply %s#%d: %s" % (repo.split("/")[1], number, exc))  # noqa: UP031
        return {"state": "unknown"}


def item_scopes(text):
    """Split a text block into per-item scopes: [(action_text, whole_item_text)]. A JSON
    block yields one scope per dict that has an action or next step, other text one scope per
    line (the CLI and the sitrep feed prose)."""
    out = []

    def walk(o):
        if isinstance(o, dict):
            act = o.get("action") or o.get("next") or o.get("next_step")
            if isinstance(act, str):
                parts = [str(v) for v in o.values() if isinstance(v, (str, int))]
                parts += [
                    str(x)
                    for v in o.values()
                    if isinstance(v, list)
                    for x in v
                    if isinstance(x, (str, int))
                ]
                out.append((act, " ".join(parts)))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    try:
        walk(json.loads(text))
    except (ValueError, TypeError):
        out = [(ln, ln) for ln in (text or "").splitlines() if ln.strip()]
    return out


def _approve_apply_prs(text):
    """Default repository PRs named in the scope of an item whose next step approves an apply."""
    found = set()
    for act, whole in item_scopes(text):
        if APPROVE_APPLY_RE.search(act):
            found.update(pr for pr in extract_refs(whole)[0] if pr[0] == _DEFAULT_REPO)
    return found


def resolve(text):
    """Live status for every PR and ticket named in text: {refs, done, errors, apply}.
    apply maps "<repo> PR #N" to the terraform-apply verdict for merged PRs that an item's next
    step wants approved. A completed apply with nothing pending marks that ref
    finished_apply, and the analysis drops the item."""
    prs, keys = extract_refs(text)
    cache = _load_cache()
    refs, errors = {}, []
    want_prs = set()
    for repo, n in prs:
        ref = "%s PR #%d" % (repo.split("/")[1].lower(), n)  # noqa: UP031
        if ref in cache:
            refs[ref] = cache[ref]["v"]
        else:
            want_prs.add((repo, n))
    want_keys = {k for k in keys if k not in cache}
    for k in keys - want_keys:
        refs[k] = cache[k]["v"]
    fresh = {}
    fresh.update(_gh_status(want_prs, errors))
    fresh.update(_jira_status(want_keys, errors))
    now = time.time()
    for k, v in fresh.items():
        cache[k] = {"at": now, "v": v}
    refs.update(fresh)
    # apply verdict for merged default repository PRs whose item next step is "approve the apply".
    apply = {}
    for repo, n in sorted(_approve_apply_prs(text)):
        ref = "%s PR #%d" % (repo.split("/")[1].lower(), n)  # noqa: UP031
        if (refs.get(ref) or {}).get("state") != "MERGED":
            continue
        ck = "apply:" + ref
        if ck in cache:
            apply[ref] = cache[ck]["v"]
        else:
            apply[ref] = _apply_status(repo, n, errors)
            if apply[ref].get("state") != "unknown":
                cache[ck] = {"at": now, "v": apply[ref]}
                fresh[ck] = apply[ref]
        refs[ref]["apply"] = apply[ref]
        refs[ref]["finished_apply"] = apply[ref].get("state") == "applied"
    if fresh:
        _save_cache(cache)
    done = sorted(k for k, v in refs.items() if v.get("done"))
    return {"refs": refs, "done": done, "errors": errors, "apply": apply}


# --- automation cards close when their cause is finished ---------------------------
# auto- items are raised by crons and sessions and merged onto the board by bundle_data, so the
# analysis' live ref check never saw them. A card whose every linked PR is MERGED (a CLOSED PR
# was not merged) and every linked ticket is done has no cause left. No resolvable ref means no
# close, a failed read means no close, and cards that carry their own buttons or close
# themselves (UI standard, cron alerts) are left to their owners.
AUTO_PREFIX = "auto-"
AUTO_SELF_CLOSING = ("auto-ui-standard-", "auto-alert-")


def _auto_text(item):
    parts = [str(item.get(k) or "") for k in ("title", "why", "action")]
    parts += [str(r) for r in (item.get("refs") or [])]
    return "\n".join(parts)


def auto_item_refs(item):
    """(prs, keys) an auto- item names: strict refs plus loose default-repository PR numbers."""
    text = _auto_text(item)
    prs, keys = extract_refs(text)
    # Blank what the strict pattern already claimed ("alt PR #9" is the alt repo, never also
    # the default repo #9) before reading the loose forms.
    rest = PR_RE.sub(" ", text)
    return prs | extract_loose_prs(rest), keys


def finished(items, result=None):
    """Which auto- items have every linked ref finished. items is a list of Action Center
    items, result an optional resolve() result (tests). Returns {key: reason} for the items to
    close. Never raises on a lookup problem: an unreadable ref keeps its item open."""
    cand = {}
    for it in items or []:
        key = str(it.get("key") or "")
        if not key.lower().startswith(AUTO_PREFIX) or key.lower().startswith(AUTO_SELF_CLOSING):
            continue
        if it.get("draft") or it.get("approve") or it.get("actions"):
            continue
        prs, keys = auto_item_refs(it)
        if prs or keys:
            cand[key] = (prs, keys)
    if not cand:
        return {}
    if result is None:
        blob = " ".join(
            ["%s PR #%d" % (repo.split("/")[1], n) for prs, _ in cand.values() for repo, n in prs]  # noqa: UP031
            + [k for _, keys in cand.values() for k in keys]
        )
        result = resolve(blob)
    refs = result.get("refs") or {}
    out = {}
    for key, (prs, keys) in cand.items():
        names = ["%s PR #%d" % (repo.split("/")[1].lower(), n) for repo, n in sorted(prs)] + sorted(  # noqa: UP031
            keys
        )
        ok, bits = True, []
        for name in names:
            v = refs.get(name) or {}
            if name in keys or v.get("kind") == "jira":
                good = bool(v.get("done"))
            else:
                good = v.get("state") == "MERGED"
            if not good:
                ok = False
                break
            bits.append("%s %s" % (name, (v.get("state") or "done")))  # noqa: UP031
        if ok and names:
            out[key] = "all linked refs finished: " + ", ".join(bits)
    return out


def done_lines(result):
    """Compact human lines for finished refs."""
    lines = []
    for k in result["done"]:
        v = result["refs"][k]
        when = (" " + v["when"][:16].replace("T", " ") + " UTC") if v.get("when") else ""
        extra = ""
        ap = v.get("apply")
        if ap:
            extra = " | apply %s" % ap.get("state")  # noqa: UP031
            if ap.get("run"):
                extra += " (terraform-apply %s, %s)" % (  # noqa: UP031
                    ap["run"],
                    ap.get("conclusion") or ap.get("status"),
                )
        lines.append("- %s: %s%s (%s)%s" % (k, v.get("state"), when, v.get("title", ""), extra))  # noqa: UP031
    return lines


def main(argv):
    as_json = "--json" in argv
    files = [a for a in argv if a != "--json"]
    text = "".join(_read(f) for f in files) if files else sys.stdin.read()
    result = resolve(text)
    if as_json:
        print(json.dumps(result, ensure_ascii=True))
        return 0
    print(
        "LIVE REF STATUS (checked %s): %d refs, %d finished"  # noqa: UP031
        % (time.strftime("%Y-%m-%d %H:%M"), len(result["refs"]), len(result["done"]))
    )
    for line in done_lines(result):
        print(line)
    for e in result["errors"]:
        print("- check error: %s" % e)  # noqa: UP031
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
