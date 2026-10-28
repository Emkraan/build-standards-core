"""
pr_deps.py
Purpose: One dependency model for the open PRs, so the ops center never asks the owner to
         approve a plan or a merge that cannot pass yet because the PR waits on another one.

         Sources of a dependency (child waits on parent):
           body      a line in the child's PR body: "Waits on #N", "Lands after #N" or "Stacked on #N"
                     (case-insensitive, "the" allowed before the number, lists such as "#1, #2 and #3")
           branch    the child's commits contain the head commit of another open PR (stacked branch)
           destroys  the own-PR lane attributed the child's plan destroys to the parent

         What the parent must reach (kind, read from the same sentence of the body line):
           merged          the parent is merged
           merged_applied  merged, and the terraform-apply run on main for its merge commit succeeded
                           (the sentence says apply or applied)
           owner_applied   merged, and every Owner-applied root it touches shows an apply after the
                           merge (the sentence says Owner apply or Owner-applied)

         Owner apply evidence, most reliable first:
           1. owner_roots status.json records a verified Owner apply of that root after the merge
              (the Owner roots card), or
           2. owner_roots planned that root from main after the merge and the plan was clean
              (No changes), which also covers an apply run by hand from the CLI.
           3. Only when the parent touches no Owner root the Ops Center plans: a marker in the
              parent body, a line "Owner applied: <what and when>" or <!-- owner-applied -->.

         Read failures never hide a card: a parent whose state cannot be read counts as met and the
         view says so (core live-actions 1.14). Everything is cached (swr, 60 s) and refreshed in
         the background, so a page GET never waits on GitHub once warm.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import paths
import swr

REPO = os.environ.get("PRDEPS_REPO", "owner/repo")
GH = os.environ.get("PRDEPS_GH_BIN", paths.which("gh"))
CACHE = Path(
    os.environ.get("PRDEPS_CACHE_DIR", str(paths.agent_home() / "cache" / "pr-review" / "pr-deps"))
)
ROOTS_CACHE = Path(
    os.environ.get(
        "PRDEPS_ROOTS", str(paths.agent_home() / "cache" / "pr-review" / "terraform-roots.json")
    )
)
TTL_S = 60
CLOSED_TTL_S = 600
APPLY_WORKFLOW = "terraform-apply.yml"
NO_APPLY_GRACE_S = (
    30 * 60
)  # merged this long with no main terraform-apply run at all: nothing to wait for

_KEY = re.compile(
    r"\b(waits?\s+on|waiting\s+on|lands?\s+after|stacked\s+on(?:\s+top\s+of)?)\s+"
    r"((?:the\s+)?#\d+(?:\s*(?:,|\band\b|&|/|\+)\s*(?:the\s+)?#\d+)*)",
    re.I,
)
_NUM = re.compile(r"#(\d+)")
_OWNER = re.compile(r"\bowner[- ]?(?:appl(?:y|ied|ies)|apply)\b", re.I)
_APPLY = re.compile(r"\bappl(?:y|ied|ies)\b", re.I)
_SENT_END = re.compile(r"(?<=[.!?])\s|\n")
_OWNER_MARK = re.compile(r"<!--\s*owner-applied\b|^\s*owner[- ]applied\s*:", re.I | re.M)
_FENCE = re.compile(r"```.*?```", re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
KIND_RANK = {"merged": 0, "merged_applied": 1, "owner_applied": 2}
KIND_TEXT = {
    "merged": "merge",
    "merged_applied": "merge and finish its main terraform-apply",
    "owner_applied": "merge and be Owner-applied",
}


# ---- helpers ------------------------------------------------------------------------------------


def _gh(args, timeout=40):
    """One helper for every gh call. Raises RuntimeError on any failure (callers fail open per item)."""
    try:
        p = subprocess.run([GH] + args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"gh failed: {e}") from e
    if p.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {p.stderr.strip()[:200]}")
    return json.loads(p.stdout) if p.stdout.strip() else None


def _ts(s):
    try:
        return (
            dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
            .replace(tzinfo=dt.timezone.utc)
            .timestamp()
        )
    except (TypeError, ValueError):
        return 0.0


_file_lock = threading.Lock()


def _store_load():
    try:
        return json.loads((CACHE / "store.json").read_text())
    except (OSError, ValueError):
        return {}


def _store_save(d):
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = CACHE / f"store.{threading.get_ident()}.tmp"
    tmp.write_text(json.dumps(d))
    os.replace(tmp, CACHE / "store.json")


# ---- parsing ------------------------------------------------------------------------------------


def parse_body(body, self_n=None):
    """[{pr, kind, source: 'body', text}] from the dependency lines of one PR body."""
    text = _FENCE.sub(" ", body or "")
    text = _COMMENT.sub(" ", text)
    out = {}
    for m in _KEY.finditer(text):
        end = _SENT_END.search(text, m.end())
        sentence = text[m.start() : end.start() if end else len(text)].strip()
        kind = (
            "owner_applied"
            if _OWNER.search(sentence)
            else "merged_applied"
            if _APPLY.search(sentence)
            else "merged"
        )
        for num in _NUM.findall(m.group(2)):
            n = int(num)
            if n == self_n:
                continue
            prev = out.get(n)
            if not prev or KIND_RANK[kind] > KIND_RANK[prev["kind"]]:
                out[n] = {"pr": n, "kind": kind, "source": "body", "text": sentence[:300]}
    return list(out.values())


def owner_marker(body):
    return bool(_OWNER_MARK.search(body or ""))


def ancestry(commits):
    """{child: [parent]} where the child's commits contain the head commit of another open PR.
    commits = {pr: {"head": sha, "shas": [sha...]}}"""
    out = {}
    for child, c in commits.items():
        shas = set(c.get("shas") or [])
        for parent, p in commits.items():
            if parent == child or not p.get("head") or p.get("head") == c.get("head"):
                continue
            if p["head"] in shas:
                out.setdefault(child, []).append(parent)
    return out


def merge_deps(*lists):
    """One dep per parent, the strongest kind wins, sources accumulate."""
    by = {}
    for lst in lists:
        for d in lst or []:
            cur = by.get(d["pr"])
            if not cur:
                by[d["pr"]] = dict(d, sources=[d["source"]])
                continue
            if d["source"] not in cur["sources"]:
                cur["sources"].append(d["source"])
            if KIND_RANK[d["kind"]] > KIND_RANK[cur["kind"]]:
                cur["kind"] = d["kind"]
                cur["text"] = d.get("text") or cur.get("text")
            if not cur.get("text") and d.get("text"):
                cur["text"] = d["text"]
    return sorted(by.values(), key=lambda x: x["pr"])


# ---- live reads (cached) ------------------------------------------------------------------------


def _gh_lines(args, timeout=60):
    try:
        p = subprocess.run([GH] + args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"gh failed: {e}") from e
    if p.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {p.stderr.strip()[:200]}")
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]


def _commits(n, head, store):
    key = f"{n}@{head}"
    hit = store.setdefault("commits", {}).get(key)
    if hit is not None:
        return hit
    shas = _gh_lines(
        ["api", "--paginate", f"repos/{REPO}/pulls/{n}/commits?per_page=100", "--jq", ".[].sha"]
    )
    store["commits"][key] = shas
    return shas


def _files(n, head, store):
    key = f"{n}@{head}"
    hit = store.setdefault("files", {}).get(key)
    if hit is not None:
        return hit
    files = _gh_lines(
        ["api", "--paginate", f"repos/{REPO}/pulls/{n}/files?per_page=100", "--jq", ".[].filename"]
    )
    store["files"][key] = files
    return files


def _closed_pr(n, store):
    """State of a PR that is not open. Merged is final, closed is re-read every CLOSED_TTL_S."""
    hit = store.setdefault("closed", {}).get(str(n))
    if hit and (hit.get("state") == "merged" or time.time() - hit.get("at", 0) < CLOSED_TTL_S):
        return hit
    r = _gh(["api", f"repos/{REPO}/pulls/{n}"]) or {}
    st = "merged" if r.get("merged") else (r.get("state") or "unknown")
    rec = {
        "state": st,
        "title": r.get("title") or "",
        "url": r.get("html_url") or f"https://github.com/{REPO}/pull/{n}",
        "head": (r.get("head") or {}).get("sha"),
        "merged_at": r.get("merged_at"),
        "merge_commit": r.get("merge_commit_sha"),
        "body": r.get("body") or "",
        "author": (r.get("user") or {}).get("login"),
        "at": time.time(),
    }
    store["closed"][str(n)] = rec
    return rec


def _apply_runs():
    """{head_sha: run} of recent push runs of terraform-apply on main (newest attempt per sha)."""
    rows = _gh(["api", f"repos/{REPO}/actions/runs?branch=main&event=push&per_page=60"]) or {}
    out = {}
    for r in rows.get("workflow_runs") or []:
        if not str(r.get("path") or "").endswith(APPLY_WORKFLOW):
            continue
        out.setdefault(r.get("head_sha"), _run_view(r))
    return out


def _run_view(r):
    return {
        "id": r.get("id"),
        "status": r.get("status"),
        "conclusion": r.get("conclusion"),
        "url": r.get("html_url"),
        "created": r.get("created_at"),
    }


def _apply_for(sha, runs, store):
    """The main terraform-apply run for one merge commit. A success is cached for good."""
    done = store.setdefault("applied", {})
    if sha in done:
        return done[sha]
    r = runs.get(sha)
    if r is None:
        rows = _gh(["api", f"repos/{REPO}/actions/runs?head_sha={sha}&per_page=20"]) or {}
        cands = [
            x
            for x in rows.get("workflow_runs") or []
            if str(x.get("path") or "").endswith(APPLY_WORKFLOW)
        ]
        r = (
            _run_view(cands[0])
            if cands
            else {"id": None, "status": "none", "conclusion": None, "url": None}
        )
    if not (r.get("status") == "completed" and r.get("conclusion") == "success") and r.get(
        "created"
    ):
        # A later successful push run covers this commit: its diff base is the last successful run,
        # which predates a commit whose own run failed, was cancelled or still waits. Re-running the
        # old run instead replays an old commit against newer state (it planned deletes on 10/16).
        later = [
            x
            for x in runs.values()
            if x.get("conclusion") == "success" and (x.get("created") or "") > r["created"]
        ]
        if later:
            r = dict(min(later, key=lambda x: x["created"]), covers=r.get("id"))
    if r.get("status") == "completed" and r.get("conclusion") == "success":
        done[sha] = r
    return r


def _roots_cfg():
    try:
        d = json.loads(ROOTS_CACHE.read_text())
        return d.get("roots") or {}
    except (OSError, ValueError):
        return {}


def owner_roots_touched(files, roots=None):
    """[(root name, [tiers])] of the applied_by owner roots the files change."""
    roots = roots if roots is not None else _roots_cfg()
    out = []
    for name, spec in roots.items():
        applier = spec.get("applied_by", "tfapply" if spec.get("apply") else "owner")
        if applier != "owner":
            continue
        tiers = []
        for tier, t in (spec.get("tiers") or {}).items():
            root = (t.get("root") or "").rstrip("/") + "/"
            watch = [root] + list(spec.get("watch") or [])
            if any(f.startswith(w) or f == w for f in files for w in watch):
                tiers.append(tier)
        if tiers:
            out.append((name, sorted(tiers)))
    return out


# ---- snapshot -----------------------------------------------------------------------------------


def _build():
    """Everything the evaluation needs from GitHub, in one cached snapshot."""
    with _file_lock:
        store = _store_load()
        errors = []
        rows = _gh(
            [
                "pr",
                "list",
                "-R",
                REPO,
                "--state",
                "open",
                "--limit",
                "100",
                "--json",
                "number,headRefOid,body,title,url,author,isDraft",
            ]
        )
        if rows is None:
            raise RuntimeError("gh pr list returned nothing")
        open_prs = {}
        commits = {}
        for r in rows:
            n = int(r["number"])
            open_prs[n] = {
                "state": "open",
                "head": r.get("headRefOid"),
                "title": r.get("title") or "",
                "url": r.get("url") or f"https://github.com/{REPO}/pull/{n}",
                "author": (r.get("author") or {}).get("login"),
                "body": r.get("body") or "",
            }
            try:
                commits[n] = {
                    "head": r.get("headRefOid"),
                    "shas": _commits(n, r.get("headRefOid"), store),
                }
            except RuntimeError as e:
                errors.append(f"#{n} commits: {e}"[:200])
        anc = ancestry(commits)
        deps = {}
        for n, p in open_prs.items():
            lst = parse_body(p["body"], n)
            br = [
                {"pr": a, "kind": "merged", "source": "branch", "text": ""} for a in anc.get(n, [])
            ]
            m = merge_deps(lst, br)
            if m:
                deps[n] = m
        # Every parent named anywhere, plus its own state, files (for Owner roots) and apply run.
        prs = dict(open_prs)
        want = {d["pr"] for lst in deps.values() for d in lst}
        try:
            runs = _apply_runs()
        except RuntimeError as e:
            runs, errors = {}, errors + [f"apply runs: {e}"[:200]]
        seen = set()
        while want - seen:
            n = min(want - seen)
            seen.add(n)
            if n not in prs:
                try:
                    prs[n] = _closed_pr(n, store)
                except RuntimeError as e:
                    prs[n] = {"state": "unknown", "error": str(e)[:200]}
                    errors.append(f"#{n}: {e}"[:200])
                    continue
                # A merged parent can itself wait on something (a chain through a merged PR's apply).
                if prs[n].get("state") == "merged":
                    sub = parse_body(prs[n].get("body"), n)
                    if sub:
                        deps.setdefault(n, merge_deps(sub))
                        want |= {d["pr"] for d in sub}
        files = {}
        applies = {}
        for lst in deps.values():
            for d in lst:
                p = prs.get(d["pr"]) or {}
                if d["kind"] == "owner_applied" and p.get("head") and d["pr"] not in files:
                    try:
                        files[d["pr"]] = _files(d["pr"], p["head"], store)
                    except RuntimeError as e:
                        errors.append(f"#{d['pr']} files: {e}"[:200])
                if (
                    d["kind"] in ("merged_applied", "owner_applied")
                    and p.get("state") == "merged"
                    and p.get("merge_commit")
                    and p["merge_commit"] not in applies
                ):
                    try:
                        applies[p["merge_commit"]] = _apply_for(p["merge_commit"], runs, store)
                    except RuntimeError as e:
                        errors.append(f"#{d['pr']} apply run: {e}"[:200])
        _store_save(store)
    for p in prs.values():
        p["owner_marker"] = owner_marker(p.get("body"))
        p.pop("body", None)
    snap = {
        "at": time.time(),
        "prs": {str(k): v for k, v in prs.items()},
        "deps": {str(k): v for k, v in deps.items()},
        "files": {str(k): v for k, v in files.items()},
        "applies": applies,
        "roots": _roots_cfg(),
        "errors": errors,
    }
    tmp = CACHE / f"snapshot.{threading.get_ident()}.tmp"
    tmp.write_text(json.dumps(snap))
    os.replace(tmp, CACHE / "snapshot.json")
    return snap


DISK_MAX_S = (
    1800  # a snapshot written by the previous server process is served this long after a restart
)


def snapshot(fresh=False):
    """The cached dependency snapshot, or None when it cannot be read (then nothing is held).
    After a server restart the last snapshot on disk is served while one background build runs, so
    the first page load neither waits on GitHub nor shows a held card as actionable."""
    if not fresh and swr.peek("pr-deps") is None:
        try:
            disk = json.loads((CACHE / "snapshot.json").read_text())
        except (OSError, ValueError):
            disk = None
        if disk and time.time() - float(disk.get("at") or 0) < DISK_MAX_S:
            swr.kick("pr-deps-warm", lambda: swr.cached_at("pr-deps", TTL_S, _build))
            return disk
    try:
        return swr.cached_at("pr-deps", TTL_S, _build, fresh=fresh)[0]
    except Exception as e:  # noqa: BLE001 - unknown never hides a card
        print(f"[pr-deps] snapshot failed: {e}", flush=True)
        return None


def invalidate():
    with contextlib.suppress(AttributeError):
        swr.invalidate("pr-deps")


def downstream_of_root(n, name, tier, snap=None):
    """The merged PR (number) whose Owner apply of root name/tier PR n waits on, directly or through
    its chain, else None. Such a PR is built on top of that apply, so it is never a reason to hold
    the apply back (holding it would deadlock: the PR waits on the apply, the apply on the PR)."""
    snap = snap if snap is not None else snapshot()
    if not snap:
        return None
    deps, prs = snap.get("deps") or {}, snap.get("prs") or {}
    todo, seen = [int(n)], set()
    while todo:
        cur = todo.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for d in deps.get(str(cur)) or []:
            p = prs.get(str(d["pr"])) or {}
            if d.get("kind") == "owner_applied" and p.get("state") == "merged":
                files = (snap.get("files") or {}).get(str(d["pr"])) or []
                for root, tiers in owner_roots_touched(files, snap.get("roots") or {}):
                    if root == name and tier in tiers:
                        return d["pr"]
            todo.append(d["pr"])
    return None


# ---- evaluation ---------------------------------------------------------------------------------


def _owner_evidence(n, p, snap, owner_items):
    """(met, missing roots text, how) for an owner_applied parent that is merged."""
    merged_at = _ts(p.get("merged_at"))
    files = (snap.get("files") or {}).get(str(n))
    touched = owner_roots_touched(files or [], snap.get("roots") or {}) if files is not None else []
    tracked = {(i.get("name"), i.get("tier")): i for i in owner_items or []}
    missing, how = [], []
    for name, tiers in touched:
        for tier in tiers:
            it = tracked.get((name, tier))
            if it is None:
                missing.append((name, tier, False))
                continue
            la = it.get("last_apply") or {}
            if la.get("verified") and _ts(la.get("at")) >= merged_at:
                how.append(f"{name} ({tier}) Owner apply recorded")
            elif it.get("state") == "clean" and _ts(it.get("started")) >= merged_at:
                how.append(f"{name} ({tier}) plans clean on main")
            else:
                missing.append((name, tier, True))
    untracked = [m for m in missing if not m[2]]
    if not touched or untracked:
        # Nothing the Ops Center plans: the marker in the parent body is the evidence.
        if p.get("owner_marker"):
            return True, "", ["Owner apply marked in its body"]
        if not touched:
            return (
                False,
                "the Owner apply (record it with a line Owner applied: in its PR body)",
                how,
            )
    tracked_missing = [f"{a} ({b})" for a, b, t in missing if t]
    if untracked and not p.get("owner_marker"):
        tracked_missing += [f"{a} ({b})" for a, b, t in untracked]
    if tracked_missing:
        return False, "the Owner apply of " + _join(tracked_missing), how
    return True, "", how


def _join(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def status_of(n, kind, snap, owner_items, now=None):
    """(met, stage, detail) for one parent. stage: open, apply, owner, closed, unknown, met."""
    now = now if now is not None else time.time()
    p = (snap.get("prs") or {}).get(str(n))
    if not p or p.get("state") == "unknown":
        return True, "unknown", f"I could not read #{n}, so this card is not held on it"
    st = p.get("state")
    if st == "open":
        return False, "open", ""
    if st == "closed":
        return True, "closed", f"#{n} was closed without merging"
    if kind == "merged":
        return True, "met", "merged"
    if kind == "merged_applied":
        r = (snap.get("applies") or {}).get(p.get("merge_commit") or "")
        merged = f"Merged {_et(p.get('merged_at'))}. Still owed: "
        if r and r.get("status") == "completed" and r.get("conclusion") == "success":
            if r.get("covers"):
                return True, "met", "merged, and a later main terraform-apply applied it"
            return True, "met", "merged and its main terraform-apply succeeded"
        if r is None or r.get("status") == "none":
            if now - _ts(p.get("merged_at")) > NO_APPLY_GRACE_S:
                return True, "met", "merged, and no main terraform-apply ran for it"
            return False, "apply", merged + "its main terraform-apply (not started yet)"
        return False, "apply", merged + _apply_text(r)
    met, missing, how = _owner_evidence(n, p, snap, owner_items)
    # The main terraform-apply of the merge commit (pipeline roots such as policy) is owed too while
    # it is running, waiting on an approval or failed. No run at all means no pipeline root to apply.
    r = (snap.get("applies") or {}).get(p.get("merge_commit") or "") or {}
    # The Owner apply goes first: it grants the pipeline identities their roles, so a main apply that
    # failed before it (403 on its new scopes) only passes on a re-run after it.
    owed = [] if met else [missing]
    if r.get("status") not in (None, "none") and not (
        r.get("status") == "completed" and r.get("conclusion") == "success"
    ):
        owed.append(_apply_text(r))
    if not owed:
        return True, "met", "merged and Owner-applied (" + _join(how) + ")"
    stage = "owner" if not met else "apply"
    return False, stage, f"Merged {_et(p.get('merged_at'))}. Still owed: " + ", then ".join(owed)


def _apply_text(r):
    st = str(r.get("status") or "")
    if st == "completed":
        return f"its main terraform-apply (ended {r.get('conclusion')}, re-run it)"
    if st == "waiting":
        return "its main terraform-apply (waiting on an approval)"
    return f"its main terraform-apply ({st.replace('_', ' ')})"


def _et(iso):
    """A merge time as Eastern wall clock: 'today 1:46 PM ET' or 'Oct 15 1:46 PM ET'."""
    t = _ts(iso)
    if not t:
        return "earlier"
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    when = dt.datetime.fromtimestamp(t, et)
    clock = when.strftime("%I:%M %p").lstrip("0")
    if when.date() == dt.datetime.now(et).date():
        return f"today {clock} ET"
    return when.strftime("%b %d ") + clock + " ET"


# Short name of what a parent still owes, for the tag and the first line ("#347 Owner apply").
STEP_TEXT = {"open": "", "apply": "main apply", "owner": "Owner apply"}


def step_label(w):
    s = STEP_TEXT.get(w.get("stage") or "", "")
    return f"#{w['pr']} {s}" if s else f"#{w['pr']}"


def _open_steps(n, ctx):
    """What an open parent needs next, from its own hold and its own cards."""
    steps = []
    card = (ctx.get("cards") or {}).get(n)
    if card:
        steps.append(card)
    row = (ctx.get("mine") or {}).get(n)
    hold = (row or {}).get("hold") or {}
    labels = [lbl for lbl in (row or {}).get("labels") or [] if lbl in ("do-not-merge", "hold")]
    if row is not None:
        if labels:
            steps.append(f"remove its {labels[0]} label")
        elif hold.get("kind") == "policy" and not card:
            steps.append("sign off on it (Approve and merge on Needs me)")
        elif hold.get("parked") == "gate":
            # the lane clears a parked draft itself once its gate passes. Nothing to click.
            steps.append(
                f"pass its gate ({hold.get('gate_met', 0)} of {len(hold.get('gate') or [])} checks, "
                "the lane marks it ready itself)"
            )
        elif hold.get("kind") in ("problem", "direction"):
            steps.append(
                "clear its hold (" + str(hold.get("summary") or "").strip().rstrip(".")[:160] + ")"
            )
        elif hold.get("kind") == "waiting" and (row.get("pending") or []):
            steps.append("let its checks finish")
    if not (card and "merge" in card):
        steps.append("merge it")
    return steps


def view_for(n, snap, owner_items, ctx=None, autofix_waits=None, _seen=None):
    """The dependency view of one PR, or None when nothing it waits on is unmet.
    {waiting: [{pr, title, url, kind, need, sources, text}], chain: [pr...], first: [pr...], lines: [..],
     notes: [..]}"""
    if not snap:
        return None
    ctx = ctx or {}
    _seen = set(_seen or ()) | {n}
    deps = list((snap.get("deps") or {}).get(str(n)) or [])
    if autofix_waits:
        deps = merge_deps(
            deps,
            [
                {"pr": int(w), "kind": "merged", "source": "destroys", "text": ""}
                for w in autofix_waits
            ],
        )
    waiting, notes, chain, step_map = [], [], [], {}
    for d in deps:
        if d["pr"] in _seen:
            continue  # a cycle in the declared deps never holds a card on itself
        met, stage, detail = status_of(d["pr"], d["kind"], snap, owner_items)
        p = (snap.get("prs") or {}).get(str(d["pr"])) or {}
        if met:
            if stage in ("unknown", "closed"):
                notes.append(detail + ".")
            continue
        sub = view_for(d["pr"], snap, owner_items, ctx, None, _seen) if stage == "open" else None
        if stage == "open":
            if sub:
                sub_by = {w["pr"]: w for w in sub["waiting"]}
                firsts = _join(
                    step_label(sub_by[x]) if x in sub_by else "#" + str(x) for x in sub["first"]
                )
                steps = [f"it waits on {firsts} first", "merge it"]
            else:
                steps = _open_steps(d["pr"], ctx)
            if d["kind"] == "merged_applied":
                steps.append("its main terraform-apply")
            elif d["kind"] == "owner_applied":
                owner = _owner_after_merge(d["pr"], p, snap)
                steps.append(owner)
        else:
            steps = [detail]
        need = ", then ".join(s for s in steps if s)
        need = need[:1].upper() + need[1:] + "."
        w = {
            "pr": d["pr"],
            "title": p.get("title") or "",
            "url": p.get("url") or f"https://github.com/{REPO}/pull/{d['pr']}",
            "kind": d["kind"],
            "kind_text": KIND_TEXT[d["kind"]],
            "stage": stage,
            "step": STEP_TEXT.get(stage, ""),
            "merged": p.get("state") == "merged",
            "need": need,
            "sources": d.get("sources") or [d.get("source")],
            "text": d.get("text") or "",
        }
        waiting.append(w)
        step_map.update((sub or {}).get("steps") or {})
        if w["step"]:
            step_map[str(d["pr"])] = w["step"]
        for x in (sub or {}).get("chain") or []:
            if x not in chain:
                chain.append(x)
        if d["pr"] not in chain:
            chain.append(d["pr"])
    if not waiting:
        return None
    firsts = [x for x in chain if not view_for_cached(x, snap, owner_items, ctx, _seen)]
    lines = [f"Waiting on #{w['pr']}: {w['need']}" for w in waiting]
    return {
        "waiting": waiting,
        "chain": chain,
        "first": firsts or chain[:1],
        "lines": lines,
        "notes": notes,
        # {pr: what a merged PR in the chain still owes}, e.g. {"347": "Owner apply"}, for "#347 Owner apply".
        "steps": step_map,
    }


def view_for_cached(n, snap, owner_items, ctx, seen):
    """True when n itself waits on an unmet parent (only open PRs and unapplied ones can)."""
    p = (snap.get("prs") or {}).get(str(n)) or {}
    if p.get("state") != "open":
        return False
    return bool(view_for(n, snap, owner_items, ctx, None, set(seen) - {n}))


def _owner_after_merge(n, p, snap):
    files = (snap.get("files") or {}).get(str(n))
    touched = owner_roots_touched(files or [], snap.get("roots") or {}) if files is not None else []
    names = [f"{a} ({_join(t)})" for a, t in touched]
    if names:
        return "the Owner apply of " + _join(names)
    return "its Owner apply"


def summary_line(v):
    """One line for a card: what to do first and in what order."""
    if not v:
        return ""
    steps = v.get("steps") or {}
    label = lambda x: f"#{x} {steps[str(x)]}" if steps.get(str(x)) else f"#{x}"  # noqa: E731
    first = _join(label(x) for x in v["first"])
    order = v["chain"]
    if len(order) > 1:
        return (
            f"Do this first: {first}. Order: "
            + ", then ".join(label(x) for x in order)
            + ", then this PR."
        )
    return f"Do this first: {first}."


def evaluate(snap, owner_items, mine=None, needs=None, priv=None):
    """{pr: view} for every open PR that waits on something unmet. mine, needs and priv are the
    rows the page shows, used only for the plain text of what each parent needs next."""
    if not snap:
        return {}
    mine_map = {m.get("pr"): m for m in mine or []}
    cards = {}
    for n in needs or []:
        if n.get("pr") is None:
            continue
        if "tfplan" in (n.get("sources") or []):
            cards[n["pr"]] = "approve its terraform-plan runs on Needs me"
        else:
            cards[n["pr"]] = "review it on Needs me"
    for p in priv or []:
        num = (p.get("pr") or {}).get("number") if isinstance(p.get("pr"), dict) else p.get("pr")
        if num is not None and num not in cards:
            cards[num] = (
                f"approve its {p.get('env_label') or p.get('environment')} deployment on Needs me"
            )
    for m in mine or []:
        if (m.get("hold") or {}).get("kind") == "policy" and m.get("pr") not in cards:
            cards[m["pr"]] = "approve and merge it on Needs me"
    ctx = {"mine": mine_map, "cards": cards}
    out = {}
    nums = {int(k) for k in (snap.get("deps") or {})} | {
        m.get("pr") for m in mine or [] if (m.get("autofix") or {}).get("waits_on")
    }
    for n in sorted(x for x in nums if x is not None):
        p = (snap.get("prs") or {}).get(str(n)) or {}
        if p.get("state") not in ("open", None) and n not in mine_map:
            continue
        waits = (mine_map.get(n, {}).get("autofix") or {}).get("waits_on")
        v = view_for(n, snap, owner_items, ctx, waits)
        if v:
            v["first_line"] = summary_line(v)
            out[n] = v
    return out


def blocking(n, snap, owner_items, autofix_waits=None):
    """Unmet parents of one PR (numbers), for the click-time guard. [] when unknown."""
    v = view_for(n, snap, owner_items, None, autofix_waits) if snap else None
    return [w["pr"] for w in (v or {}).get("waiting") or []]
