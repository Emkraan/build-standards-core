"""
plans.py
Purpose: Plans page backend. Indexes state/plans: one tracker per project we are actively
         building (projects/<slug>/tracker.md plus that project's documents), a library of
         standalone SBAR plans (library/*.md) and an archive. Markdown only, front matter is the
         source of every title, type, status and summary (format: state/plans/.format.md).
         Serves one file's text for the reader and moves a file or a whole project into
         archive/ (and back) on the owner's click. Nothing else writes. Messages never live here, they
         go straight to Teams, Outlook or the chat. Replaces the Drafts page (drafts.py).
         Freshness check: each active tracker is compared with the PRs on its tickets
         and its tickets' status changes. Anything that landed after the tracker was last written
         (mtime capped at its updated day) marks the card "behind", so a stale tracker
         shows before anyone relies on it.
Date:    2026-10-16
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import paths
import swr

ROOT = Path(os.environ.get("OPSCENTER_ROOT", paths.root()))
PLANS = Path(os.environ.get("PLANS_DIR") or (ROOT / "state" / "plans"))
SECTIONS = ("projects", "library")
ARCHIVE = "archive"
TRACKER = "tracker.md"
MAX_READ_BYTES = 1_000_000
HEAD_BYTES = 16384
JIRA_TTL_S = 600
FRESH_TTL_S = 1800
FRESH_RETRY_S = 120
RECENT_PRS = 100  # recent PRs per repo scanned for branch-name matches
GRACE = dt.timedelta(
    minutes=10
)  # a PR the own-PR lane merges minutes after the tracker edit is not drift
GH = os.environ.get("PLANS_GH") or paths.which("gh")
ENGINE = Path(__file__).resolve().parents[2] / "engine"


def _cfg():
    """PLANS_CONFIG (default <state>/plans-config.json): default_repo, untracked_repos, project, extra_prefixes,
    browse_url. project and browse_url fall back to the tracker parameters. Every key is optional."""
    f = os.environ.get("PLANS_CONFIG") or str(paths.state_dir() / "plans-config.json")
    try:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    try:
        tp = json.loads(
            Path(
                os.environ.get("OPSCENTER_TRACKER_PARAMS")
                or paths.state_dir() / "tracker-params.json"
            ).read_text()
        )
    except (OSError, ValueError):
        tp = {}
    tp = tp if isinstance(tp, dict) else {}
    d.setdefault("project", tp.get("project") or "")
    d.setdefault("browse_url", tp.get("browse_url") or "")
    return d


def _browse():
    return str(_cfg().get("browse_url") or "")


def _default_repo():
    return str(_cfg().get("default_repo") or "")


def _untracked_repos():
    v = _cfg().get("untracked_repos")
    return tuple(str(r) for r in v if "/" in str(r)) if isinstance(v, list) else ()


def _prefixes():
    c = _cfg()
    out = [str(c.get("project") or "")] + [str(x) for x in (c.get("extra_prefixes") or [])]
    return [re.escape(p) for p in out if re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,9}", p)]


def _key_alt():
    return "|".join(_prefixes()) or r"[A-Z][A-Z0-9]{1,9}"


def _ticket_re():
    return re.compile(r"\b(" + _key_alt() + r")-(\d{2,7})\b")


def _project_only(key):
    p = str(_cfg().get("project") or "")
    return key.startswith(p.upper() + "-") if p else True


REPO_LINK_RE = re.compile(r"https://github\.com/([A-Za-z0-9-]+/[A-Za-z0-9._-]+)/pull/\d+")
TYPES = ("tracker", "plan", "brief", "record", "doc")
TYPE_LABEL = {
    "tracker": "Tracker",
    "plan": "Plan",
    "brief": "Brief",
    "record": "Record",
    "doc": "Confluence",
}
SBAR = ("situation", "background", "assessment", "recommendation")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}\.md$")


class Conflict(Exception):
    """The file changed since the page loaded it (live-actions rule 1.7)."""

    status = 409


def _iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(v):
    v = re.split(r"\s+#\s", v or "", maxsplit=1)[0].strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        v = v[1:-1]
    return v.strip()


def _front_matter(text):
    """A leading --- block as a dict (lowercase keys) plus the body after it."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    fm = {}
    for i in range(1, min(len(lines), 80)):
        if lines[i].strip() == "---":
            return fm, "\n".join(lines[i + 1 :])
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", lines[i])
        if m:
            fm[m.group(1).lower()] = _clean(m.group(2))
    return {}, text


def _tickets(value):
    out = []
    for m in _ticket_re().finditer(value or ""):
        k = f"{m.group(1)}-{m.group(2)}"
        if k not in out:
            out.append(k)
    return out


def _heading(body):
    for line in body.split("\n")[:60]:
        m = re.match(r"^\s{0,3}#\s+(.+?)\s*#*\s*$", line)
        if m:
            return m.group(1).strip()
    return ""


def _humanize(name):
    stem = name[:-3] if name.endswith(".md") else name
    words = [w for w in re.split(r"[-_\s]+", stem) if w]
    text = " ".join(words) or name
    return text[0].upper() + text[1:]


def _progress(body):
    """Checkbox progress in the tracker's Next steps (all checkboxes when there is no such heading)."""
    m = re.search(r"^##\s+Next steps\s*$(.*?)(?=^##\s|\Z)", body, re.M | re.S | re.I)
    scope = m.group(1) if m else body
    done = len(re.findall(r"^\s*[-*]\s+\[[xX]\]", scope, re.M))
    open_ = len(re.findall(r"^\s*[-*]\s+\[ \]", scope, re.M))
    return {"done": done, "total": done + open_}


def _sbar(body):
    heads = {h.strip().lower() for h in re.findall(r"^##\s+(.+?)\s*$", body, re.M)}
    return all(s in heads for s in SBAR)


def _rel(p):
    return p.relative_to(PLANS.resolve()).as_posix()


def _place(rel):
    """(section, project) for a relative path. Archived files keep their original sub path."""
    parts = rel.split("/")
    archived = parts[0] == ARCHIVE
    if archived:
        parts = parts[1:]
    section = parts[0] if parts and parts[0] in SECTIONS else "library"
    project = parts[1] if section == "projects" and len(parts) >= 3 else ""
    return archived, section, project


def _item(p):
    st = p.stat()
    rel = _rel(p)
    with open(p, "rb") as fh:
        head = fh.read(HEAD_BYTES).decode("utf-8", errors="replace")
    fm, body = _front_matter(head)
    archived, section, project = _place(rel)
    kind = fm.get("type", "").lower()
    if kind not in TYPES:
        kind = "tracker" if p.name == TRACKER else "plan"
    title = fm.get("title") or _heading(body) or _humanize(p.name)
    updated = fm.get("updated") or fm.get("date") or ""
    if not re.match(r"^\d{4}-\d{2}-\d{2}", updated):
        updated = _iso(st.st_mtime)[:10]
    item = {
        "id": rel,
        "name": p.name,
        "path": str(p),
        "section": section,
        "project": project,
        "archived": archived,
        "type": kind,
        "type_label": TYPE_LABEL[kind],
        "title": title,
        "status": (fm.get("status") or ("active" if kind == "tracker" else "current")).lower(),
        "summary": fm.get("summary", ""),
        "next": fm.get("next", ""),
        "owner": fm.get("owner", ""),
        "updated": updated[:10],
        "tickets": _tickets(fm.get("tickets", "") + " " + fm.get("ticket", "")),
        "front_matter": bool(fm),
        "sbar": _sbar(body) if kind == "plan" else False,
        "version": str(st.st_mtime_ns),
        "mtime": _iso(st.st_mtime),
        "size": st.st_size,
    }
    if kind == "tracker":
        item["progress"] = _progress(body)
        item["repos"] = sorted(
            set(REPO_LINK_RE.findall(body)) | ({_default_repo()} if _default_repo() else set())
        )
        item["claimed"] = (
            updated[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", fm.get("updated") or "") else ""
        )
        item["cutoff"] = _written_cutoff(item["claimed"] or updated[:10], st.st_mtime)
    return item


def _end_of_local_day(day):
    """The last second of a YYYY-MM-DD local calendar day, as an aware datetime, or None."""
    try:
        d = dt.datetime.strptime(day[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    return (d + dt.timedelta(days=1, seconds=-1)).astimezone()


def _written_cutoff(day, mtime):
    """When the tracker was last written: the file mtime, capped at the end of its claimed
    updated day. Comparing whole days hid work that landed later the same day (a tracker
    written 16:30 with PRs merged at 17:07 and 17:28 stayed fresh). The day cap keeps a bare
    touch (git checkout, copy) from making an old tracker look current."""
    written = dt.datetime.fromtimestamp(mtime, dt.timezone.utc)
    end = _end_of_local_day(day)
    if end is not None and end < written:
        written = end
    return written.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_stamp(stamp):
    """An ISO timestamp (GitHub Z, Jira +hhmm) or a bare YYYY-MM-DD (end of that local day) as an
    aware datetime, or None when unreadable."""
    if not stamp:
        return None
    v = stamp.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return _end_of_local_day(v)
    v = re.sub(r"\.\d+", "", v.replace("Z", "+00:00"))
    v = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", v)
    try:
        t = dt.datetime.fromisoformat(v)
    except ValueError:
        return None
    return t if t.tzinfo else t.astimezone()


def _files():
    root = PLANS.resolve()
    if not root.is_dir():
        return []  # no plans folder yet: an empty page, not an error
    out = []
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root).parts
        if any(part.startswith(".") for part in rel) or len(rel) > 5 or not p.is_file():
            continue
        out.append(p)
    return out


# ---- live ticket status through ref_status.py, refreshed off the request path ----

_jira_lock = threading.Lock()
_jira = {"at": 0.0, "keys": (), "refs": {}, "errors": [], "state": "none"}


def _refresh_jira(keys):
    try:
        if str(ENGINE) not in sys.path:
            sys.path.insert(0, str(ENGINE))
        import ref_status  # noqa: E402  (shared live ref lookup with its own cache)

        res = ref_status.resolve(" ".join(keys))
        refs = dict(res.get("refs") or {})
        errors = list(res.get("errors") or [])
        state = "ok" if refs or not errors else "error"
    except Exception as e:  # noqa: BLE001 - the status chip degrades, the list still serves
        refs, errors, state = {}, [str(e)[:300]], "error"
    with _jira_lock:
        if state == "error" and _jira["refs"]:
            _jira.update(at=time.time(), keys=tuple(keys), errors=errors, state="stale")
        else:
            _jira.update(at=time.time(), keys=tuple(keys), refs=refs, errors=errors, state=state)


def _jira_status(keys):
    keys = tuple(sorted(set(keys)))
    with _jira_lock:
        snap = dict(_jira)
    if keys and (snap["keys"] != keys or time.time() - snap["at"] > JIRA_TTL_S):
        swr.kick("plans:jira", lambda: _refresh_jira(keys))
        if snap["state"] == "none":
            snap["state"] = "loading"
    return snap


# ---- freshness: is a tracker behind its PRs and tickets, refreshed off the request path ----

_fresh_lock = threading.Lock()
_fresh = {"at": 0.0, "sig": (), "results": {}, "errors": [], "state": "none"}


def _local_day(stamp):
    """An ISO timestamp (GitHub Z or Jira +hhmm) as the local calendar day, or '' when unreadable."""
    if not stamp:
        return ""
    v = stamp.strip().replace("Z", "+00:00")
    v = re.sub(r"\.\d+", "", v)
    v = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", v)
    try:
        return dt.datetime.fromisoformat(v).astimezone().strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _gh(query):
    """One GraphQL call through gh. Raises RuntimeError on any failure (fail closed)."""
    try:
        p = subprocess.run(
            [GH, "api", "graphql", "-f", "query=" + query],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"gh: {e}") from e
    try:
        data = json.loads(p.stdout or "{}")
    except ValueError as e:
        raise RuntimeError(f"gh rc={p.returncode} {(p.stderr or '')[:160].strip()}") from e
    if p.returncode != 0 or data.get("errors") or "data" not in data:
        msg = (data.get("errors") or [{}])[0].get("message") or (p.stderr or "")[:160]
        raise RuntimeError(f"gh rc={p.returncode} {msg}".strip())
    return data["data"]


def _names_key(n, key):
    """A PR belongs to a ticket when its title names the key (word boundary, so KEY-12 never
    matches KEY-123) or its branch starts with the key (KEY-<n>-<slug>)."""
    title = n.get("title") or ""
    branch = (n.get("headRefName") or "").upper()
    return (
        bool(re.search(rf"\b{re.escape(key)}\b", title))
        or branch == key
        or branch.startswith(key + "-")
    )


PR_FIELDS = "number title headRefName state url createdAt mergedAt repository { name }"


def _pr_events(spec):
    """{slug: [event]} for PRs opened or merged after each tracker's claimed day. spec rows are
    (slug, claimed_day, tickets, repos). One GraphQL call: one aliased title search per ticket, plus
    the most recently updated PRs per repo for branch-name matches (GitHub search has no branch prefix)."""
    parts, alias, repo_alias = [], {}, {}
    for slug, claimed, tickets, repos in spec:
        scope = " ".join(f"repo:{r}" for r in repos)
        for k in tickets:
            a = f"s{len(alias)}"
            alias[a] = (slug, claimed, k, repos)
            since = (_parse_stamp(claimed) or dt.datetime.now(dt.timezone.utc)).astimezone(
                dt.timezone.utc
            )
            # >= on the UTC date: a bare > excluded the tracker's own day, where same-day work lands.
            q = f"{scope} is:pr in:title {k} updated:>={since.strftime('%Y-%m-%d')}"
            parts.append(
                a + ": search(type: ISSUE, first: 30, query: " + json.dumps(q) + ") "
                "{ nodes { ... on PullRequest { " + PR_FIELDS + " } } }"
            )
        for r in repos:
            if r not in repo_alias:
                ra = f"r{len(repo_alias)}"
                repo_alias[r] = ra
                owner, name = r.split("/", 1)
                parts.append(
                    ra
                    + ": repository(owner: "
                    + json.dumps(owner)
                    + ", name: "
                    + json.dumps(name)
                    + ") "
                    "{ pullRequests(first: "
                    + str(RECENT_PRS)
                    + ", orderBy: {field: UPDATED_AT, direction: DESC}) "
                    "{ nodes { " + PR_FIELDS + " } } }"
                )
    out = {slug: [] for slug, *_ in spec}
    if not parts:
        return out
    data = _gh("query { " + " ".join(parts) + " }")
    recent = {
        r: (((data.get(ra) or {}).get("pullRequests") or {}).get("nodes")) or []
        for r, ra in repo_alias.items()
    }
    seen = set()
    for a, (slug, claimed, key, repos) in alias.items():
        nodes = list(((data.get(a) or {}).get("nodes")) or [])
        for r in repos:
            nodes += recent.get(r, [])
        for n in nodes:
            if not n or not n.get("number") or not _names_key(n, key):
                continue
            ref = f"{(n.get('repository') or {}).get('name', 'repo')} #{n['number']}"
            cut = _parse_stamp(claimed)
            merged_at, opened_at = (
                _parse_stamp(n.get("mergedAt") or ""),
                _parse_stamp(n.get("createdAt") or ""),
            )
            if cut is None:
                continue
            if merged_at and merged_at > cut + GRACE:
                kind, day = "merged", _local_day(n.get("mergedAt"))
            elif opened_at and opened_at > cut + GRACE:
                kind, day = "opened", _local_day(n.get("createdAt"))
            else:
                continue
            if (slug, ref) in seen:
                continue
            seen.add((slug, ref))
            out[slug].append(
                {
                    "kind": kind,
                    "ref": f"PR {ref}",
                    "day": day,
                    "title": (n.get("title") or "")[:120],
                    "url": n.get("url", ""),
                }
            )
    return out


def _ticket_events(spec, refs):
    """{slug: [event]} for tickets whose status category changed after the tracker's claimed day."""
    out = {slug: [] for slug, *_ in spec}
    for slug, claimed, tickets, _repos in spec:
        for k in tickets:
            r = refs.get(k) or {}
            changed, cut = _parse_stamp(r.get("status_changed", "")), _parse_stamp(claimed)
            day = _local_day(r.get("status_changed", ""))
            if changed and cut and changed > cut + GRACE:
                out[slug].append(
                    {
                        "kind": "status",
                        "ref": k,
                        "day": day,
                        "title": f"{k} moved to {r.get('state', '?')}",
                        "url": _browse() + k,
                    }
                )
    return out


def _refresh_fresh(spec, sig):
    results, errors = {}, []
    try:
        prs = _pr_events(spec)
        state = "ok"
    except RuntimeError as e:
        prs, state = {}, "error"
        errors.append(str(e)[:300])
    with _jira_lock:
        refs = dict(_jira["refs"])
    tix = _ticket_events(spec, refs)
    for slug, *_ in spec:
        ev = (prs.get(slug) or []) + (tix.get(slug) or [])
        ev.sort(key=lambda e: (e["day"], e["ref"]), reverse=True)
        results[slug] = ev
    with _fresh_lock:
        if state == "error":
            # Fail closed: never report "fresh" on a failed read. Keep the last good events, flagged.
            _fresh.update(at=time.time(), errors=errors, state="error")
        else:
            _fresh.update(at=time.time(), sig=sig, results=results, errors=errors, state=state)


def _freshness(projects):
    """Attach p["freshness"] = {state, behind, events, checked_utc} to every live active tracker."""
    spec = []
    for p in projects:
        t = p.get("tracker")
        if p["archived"] or not t or p["status"] != "active" or not t["tickets"]:
            continue
        spec.append(
            (
                p["slug"],
                t.get("cutoff") or t.get("claimed") or t["updated"],
                tuple(t["tickets"]),
                tuple(t["repos"]),
            )
        )
    sig = tuple(sorted(spec))
    with _fresh_lock:
        snap = dict(_fresh)
    with _jira_lock:
        jira_at = _jira["at"]
    age = time.time() - snap["at"]
    due = (
        snap["sig"] != sig
        or age > FRESH_TTL_S
        or (snap["state"] == "error" and age > FRESH_RETRY_S)
        or jira_at > snap["at"]  # ticket status landed after the last check, fold it in
    )
    if spec and due:
        swr.kick("plans:fresh", lambda: _refresh_fresh(spec, sig))
    claimed = {s[0]: s for s in spec}
    good = {s[0]: s for s in snap["sig"]}
    for p in projects:
        if p["slug"] not in claimed:
            continue
        current = good.get(p["slug"]) == claimed[p["slug"]]
        events = (snap["results"].get(p["slug"]) or []) if current else []
        if not current:
            state = "loading" if snap["state"] != "error" else "error"
        else:
            state = snap["state"]
        p["freshness"] = {
            "state": state,
            "behind": bool(events),
            "events": events[:8],
            "checked_utc": _iso(snap["at"]) if snap["at"] else "",
            "errors": snap["errors"] if state == "error" else [],
        }


# ---- untracked work: ticket keys with real PR activity that no tracker names ----

UNTRACKED_DAYS = 7
UNTRACKED_MIN_PRS = 3
UNTRACKED_TTL_S = 1800
IGNORE_FILE = ".untracked-ignore.json"
_untracked_lock = threading.Lock()
_untracked = {"at": 0.0, "rows": [], "errors": [], "state": "none"}


def _pr_keys(n):
    """Ticket keys a PR works on: the KEY-<n> branch prefix plus keys in its title."""
    keys = {f"{a}-{b}".upper() for a, b in _ticket_re().findall(n.get("title") or "")}
    m = re.match(r"^((?:" + _key_alt() + r")-\d{2,7})(?:-|$)", n.get("headRefName") or "", re.I)
    if m:
        keys.add(m.group(1).upper())
    return {k for k in keys if _project_only(k)}


def _refresh_untracked():
    if not _untracked_repos():
        with _untracked_lock:
            _untracked.update(at=time.time(), rows=[], errors=[], state="none")
        return
    try:
        parts = []
        for i, r in enumerate(_untracked_repos()):
            owner, name = r.split("/", 1)
            parts.append(
                f"r{i}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) "
                "{ pullRequests(first: "
                + str(RECENT_PRS)
                + ", orderBy: {field: UPDATED_AT, direction: DESC}) "
                "{ nodes { " + PR_FIELDS + " } } }"
            )
        data = _gh("query { " + " ".join(parts) + " }")
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=UNTRACKED_DAYS)
        by_key = {}
        for i, _r in enumerate(_untracked_repos()):
            for n in (((data.get(f"r{i}") or {}).get("pullRequests") or {}).get("nodes")) or []:
                if not n or not n.get("number"):
                    continue
                stamps = [
                    s
                    for s in (
                        _parse_stamp(n.get("createdAt") or ""),
                        _parse_stamp(n.get("mergedAt") or ""),
                    )
                    if s
                ]
                if not stamps or max(stamps) < since:
                    continue
                for k in _pr_keys(n):
                    by_key.setdefault(k, {})[
                        (n.get("repository") or {}).get("name", "repo") + f" #{n['number']}"
                    ] = {
                        "ref": (n.get("repository") or {}).get("name", "repo") + f" #{n['number']}",
                        "title": (n.get("title") or "")[:120],
                        "url": n.get("url", ""),
                        "state": (n.get("state") or "").lower(),
                        "day": _local_day(n.get("mergedAt") or n.get("createdAt")),
                    }
        rows = [
            {"key": k, "prs": sorted(v.values(), key=lambda e: (e["day"], e["ref"]), reverse=True)}
            for k, v in by_key.items()
            if len(v) >= UNTRACKED_MIN_PRS
        ]
        rows.sort(key=lambda r: (-len(r["prs"]), r["key"]))
        with _untracked_lock:
            _untracked.update(at=time.time(), rows=rows, errors=[], state="ok")
    except RuntimeError as e:
        with _untracked_lock:
            _untracked.update(at=time.time(), errors=[str(e)[:300]], state="error")


def _ignored():
    try:
        v = json.loads((PLANS / IGNORE_FILE).read_text(encoding="utf-8"))
        return {str(k).upper() for k in (v.get("keys") or [])} if isinstance(v, dict) else set()
    except (OSError, ValueError):
        return set()


def _untracked_candidates(rows):
    """Untracked rows from the last GitHub read, minus keys a plan names or that were dismissed."""
    with _untracked_lock:
        snap = dict(_untracked)
    if time.time() - snap["at"] > UNTRACKED_TTL_S or (
        snap["state"] == "error" and time.time() - snap["at"] > FRESH_RETRY_S
    ):
        swr.kick("plans:untracked", _refresh_untracked)
    skip = {k for r in rows for k in r["tickets"]} | _ignored()
    return snap, [dict(r) for r in snap["rows"] if r["key"] not in skip]


def _untracked_work(snap, out, refs):
    """Keys with UNTRACKED_MIN_PRS or more PRs opened or merged in the last UNTRACKED_DAYS days that no
    tracker or plan names.
    on a key whose ticket was about something else and never reached this page."""
    for r in out:
        ref = refs.get(r["key"]) or {}
        r["ticket_title"] = ref.get("title", "")
        r["ticket_status"] = ref.get("state", "")
        r["ticket_done"] = bool(ref.get("done"))
        r["url"] = _browse() + r["key"]
        r["slug"] = _suggest_slug(r)
    # A closed ticket with every PR merged or closed is history, not untracked work.
    out = [
        r for r in out if not (r["ticket_done"] and not any(p["state"] == "open" for p in r["prs"]))
    ]
    return {
        "state": "loading" if snap["state"] == "none" else snap["state"],
        "rows": out,
        "checked_utc": _iso(snap["at"]) if snap["at"] else "",
        "errors": snap["errors"],
        "window_days": UNTRACKED_DAYS,
        "min_prs": UNTRACKED_MIN_PRS,
    }


def _suggest_slug(r):
    words = re.findall(r"[a-z0-9]+", (r.get("ticket_title") or r["key"]).lower())
    stop = {"the", "a", "an", "and", "to", "for", "of", "on", "in", "with", "into", "add", "make"}
    slug = "-".join([w for w in words if w not in stop][:5]) or r["key"].lower()
    return slug[:60].strip("-")


def create_tracker(key, slug, title="", what_if=False):
    """Write a skeleton projects/<slug>/tracker.md for an untracked key. Refuses an existing project
    folder (never overwrites). The skeleton lists the PRs found, the session reconciling it fills the rest."""
    key = str(key or "").upper().strip()
    if not re.fullmatch(r"(?:" + _key_alt() + r")-\d{2,7}", key):
        raise ValueError("a ticket key like ABC-123 is required")
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise ValueError("slug must be lowercase letters, digits and dashes")
    title = re.sub(r"[\r\n]+", " ", str(title or "")).strip()[:120] or _humanize(slug)
    if not title.isascii():
        raise ValueError("title must be ASCII")
    root = PLANS.resolve()
    folder = root / "projects" / slug
    if folder.exists() or (root / ARCHIVE / "projects" / slug).exists():
        raise Conflict(f"projects/{slug} already exists. Pick another name.")
    with _untracked_lock:
        found = next((r for r in _untracked["rows"] if r["key"] == key), None)
    prs = (found or {}).get("prs") or []
    today = dt.datetime.now().astimezone().strftime("%Y-%m-%d")
    lines = [
        "---",
        f"title: {title}",
        "type: tracker",
        "status: active",
        f"summary: Created from untracked work on {key}. Reconcile against live before relying on it.",
        f"updated: {today}",
        f"tickets: {key}",
        "owner: owner-name",
        "next: Reconcile this tracker against the PRs, the ticket and Confluence.",
        "---",
        "",
        "## Where it stands",
        f"Created on {today} because {len(prs)} PRs on {key} in the last {UNTRACKED_DAYS} days were not named by any tracker.",
        "",
        "| PR | State | Day | Title |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| [{p['ref']}]({p['url']}) | {p['state']} | {p['day']} | {p['title'].replace('|', '/')} |"
        for p in prs
    ]
    lines += [
        "",
        "## Next steps",
        "- [ ] Reconcile this tracker against live state",
        "",
        "## Decisions",
        "",
        "## Log",
        f"- {today}: Tracker created from the Plans page untracked work strip.",
        "",
    ]
    text = "\n".join(lines)
    if not text.isascii():
        text = text.encode("ascii", "replace").decode("ascii")
    rel = f"projects/{slug}/{TRACKER}"
    if what_if:
        return {"created": False, "what_if": True, "path": rel, "text": text}
    folder.mkdir(parents=True)
    (folder / TRACKER).write_text(text, encoding="utf-8")
    return {"created": True, "path": rel, "id": f"projects/{slug}"}


def dismiss_untracked(key, what_if=False):
    """Stop listing a key as untracked (not a project). Kept in state/plans/.untracked-ignore.json."""
    key = str(key or "").upper().strip()
    if not re.fullmatch(r"(?:" + _key_alt() + r")-\d{2,7}", key):
        raise ValueError("a ticket key like ABC-123 is required")
    keys = sorted(_ignored() | {key})
    if what_if:
        return {"dismissed": False, "what_if": True, "key": key}
    p = PLANS / IGNORE_FILE
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"keys": keys}, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return {"dismissed": True, "key": key}


def items():
    rows = [_item(p) for p in _files()]
    usnap, ucand = _untracked_candidates(rows)
    # One Jira lookup for both the trackers and the untracked strip, so neither evicts the other's cache.
    keys = sorted({k for r in rows for k in r["tickets"]} | {r["key"] for r in ucand})
    js = _jira_status(keys)
    refs = js.get("refs") or {}
    for r in rows:
        r["ticket_status"] = {
            k: {
                "status": refs[k].get("state", ""),
                "done": bool(refs[k].get("done")),
                "intake": refs[k].get("type") == "Discovery",
                "url": _browse() + k,
            }
            for k in r["tickets"]
            if k in refs
        }
    projects = {}
    for r in rows:
        if r["section"] != "projects" or not r["project"]:
            continue
        key = (r["archived"], r["project"])
        pr = projects.setdefault(
            key, {"slug": r["project"], "archived": r["archived"], "tracker": None, "docs": []}
        )
        if r["name"] == TRACKER:
            pr["tracker"] = r
        else:
            pr["docs"].append(r)
    plist = []
    for pr in projects.values():
        pr["docs"].sort(key=lambda d: (TYPES.index(d["type"]), d["title"].lower()))
        t = pr["tracker"]
        pr["title"] = t["title"] if t else _humanize(pr["slug"])
        pr["status"] = t["status"] if t else "active"
        if pr["status"] == "done" and t and t["progress"]["done"] < t["progress"]["total"]:
            # Done means nothing left. A tracker that claims done with open steps shows as active.
            pr["status"] = "active"
        # Done with only an open intake left: waiting on someone else's work ticket, shown apart so it is not clutter.
        ts = (t or {}).get("ticket_status") or {}
        pr["awaiting_ticket"] = bool(
            pr["status"] == "done"
            and ts
            and any(v["intake"] and not v["done"] for v in ts.values())
            and all(v["done"] for v in ts.values() if not v["intake"])
        )
        pr["updated"] = max(
            [d["updated"] for d in pr["docs"]] + ([t["updated"]] if t else []) or [""]
        )
        pr["id"] = f"{ARCHIVE + '/' if pr['archived'] else ''}projects/{pr['slug']}"
        pr["version"] = str(max(int(d["version"]) for d in pr["docs"] + ([t] if t else [])))
        plist.append(pr)
    plist.sort(key=lambda p: (p["status"] == "done", -int(p["updated"].replace("-", "") or 0)))
    library = [r for r in rows if r["section"] == "library"]
    order = {"in-progress": 0, "approved": 1, "proposed": 2, "parked": 3, "done": 4}
    library.sort(key=lambda r: (order.get(r["status"], 2), r["title"].lower()))
    live_projects = [p for p in plist if not p["archived"]]
    _freshness(live_projects)
    live_library = [r for r in library if not r["archived"]]
    return {
        "generated_utc": _iso(time.time()),
        "root": str(PLANS.resolve()),
        "projects": live_projects,
        "untracked": _untracked_work(usnap, ucand, refs),
        "library": live_library,
        "archived": {
            "projects": [p for p in plist if p["archived"]],
            "library": [r for r in library if r["archived"]],
        },
        "counts": {
            "projects": sum(1 for p in live_projects if p["status"] != "done"),
            "library": sum(1 for r in live_library if r["status"] != "done"),
            "archived": sum(1 for p in plist if p["archived"])
            + sum(1 for r in library if r["archived"]),
        },
        "jira": {
            "state": js["state"] if keys else "none",
            "checked_utc": _iso(js["at"]) if js["at"] else "",
            "errors": js.get("errors") or [],
        },
    }


# ---- reads and the two writes (archive, restore), all jailed to the plans folder ----


def _check_rel(rel):
    if not isinstance(rel, str) or not rel or len(rel) > 300 or "\x00" in rel or "\\" in rel:
        raise PermissionError("bad path")
    if rel.startswith("/") or any(
        part in ("", ".", "..") or part.startswith(".") for part in rel.split("/")
    ):
        raise PermissionError("path outside the plans folder")
    root = PLANS.resolve()
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as e:
        raise PermissionError("path outside the plans folder") from e
    return root, target


def _target(rel):
    """A client path to one plan file or one project folder. Returns (root, path, is_project)."""
    root, target = _check_rel(rel)
    parts = rel.split("/")
    core = parts[1:] if parts[0] == ARCHIVE else parts
    if len(core) == 2 and core[0] == "projects" and SLUG_RE.match(core[1]):
        if not target.is_dir():
            raise KeyError(rel)
        return root, target, True
    ok = (len(core) == 2 and core[0] == "library" and NAME_RE.match(core[1])) or (
        len(core) == 3
        and core[0] == "projects"
        and SLUG_RE.match(core[1])
        and NAME_RE.match(core[2])
    )
    if not ok:
        raise PermissionError("not a plan or project path")
    if not target.is_file():
        raise KeyError(rel)
    return root, target, False


def read(rel):
    _root, p, is_project = _target(rel)
    if is_project:
        raise PermissionError("open a file, not a folder")
    r = _item(p)
    if r["size"] > MAX_READ_BYTES:
        return {"item": r, "text": None}
    return {"item": r, "text": p.read_text(encoding="utf-8", errors="replace")}


def _version(target, is_project):
    if not is_project:
        return str(target.stat().st_mtime_ns)
    vs = [
        f.stat().st_mtime_ns
        for f in target.rglob("*.md")
        if f.is_file() and not f.name.startswith(".")
    ]
    return str(max(vs)) if vs else "0"


def _move(rel, version, what_if, to_archive):
    root, src, is_project = _target(rel)
    in_archive = rel.split("/", 1)[0] == ARCHIVE
    if to_archive and in_archive:
        return {"moved": False, "already": True, "from": rel, "to": rel}
    if not to_archive and not in_archive:
        return {"moved": False, "already": True, "from": rel, "to": rel}
    if version and _version(src, is_project) != str(version):
        raise Conflict("It changed since the page loaded it. Refresh first.")
    dest_rel = f"{ARCHIVE}/{rel}" if to_archive else rel.split("/", 1)[1]
    dest = root / dest_rel
    if dest.exists():
        raise Conflict(f"{dest_rel} already exists. Rename one of them first.")
    if what_if:
        return {"moved": False, "what_if": True, "from": rel, "to": dest_rel}
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    if not dest.exists() or src.exists():
        raise OSError("move did not land")
    # Leave no empty folder behind, except the live projects/ and library/ section folders.
    keep = {root / s for s in SECTIONS}
    parent = src.parent
    while parent != root and parent not in keep and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent
    return {"moved": True, "already": False, "from": rel, "to": dest_rel}


def archive(rel, version=None, what_if=False):
    """Move one plan file or a whole project folder under archive/, keeping its sub path."""
    return _move(rel, version, what_if, to_archive=True)


def restore(rel, version=None, what_if=False):
    """Move an archived plan file or project back to where it came from."""
    return _move(rel, version, what_if, to_archive=False)
