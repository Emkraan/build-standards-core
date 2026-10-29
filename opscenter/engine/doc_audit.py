#!/usr/bin/env python3
"""
doc_audit.py - documentation coverage auditor.

Checks every thing in the documentation registry (`doc-inventory.json`) against the documentation rules and writes the durable gap store
(`doc-gaps.json`) the Knowledge page and the board analysis read. Deterministic, no model call. The docs home is read only, through the
consumer's driver (`DOCS_HOME_CMD`, a JSON list; the contract is `<cmd> <tool> '<json args>'` printing a JSON-RPC result, the same one
`lanes/queued_approvals.py` uses; the default is none, and without it the audit fails closed and keeps the previous store). Git reads use
origin/main of the local clones after a fetch.

Configuration: `DOC_AUDIT_CONFIG` (default `<state>/dashboard/doc-audit-config.json`), a JSON object, every key optional:
  repos            {name: clone path}                    the clones the rules read
  raci_page_id     docs home page holding the ownership table (a "Domain / Responsibility" table, columns per person, A and R cells)
  wiki_url         prefix that turns a page id into a link
  cloud_id         passed to the driver as cloudId
  dup_roots        {page id: label}                      page trees checked for duplicate titles (rule R11)
  closeout_state   JSON of the sprint close-out (rule R12)
  cron_jobs, cron_catalog   the agent's job list and the catalog that must describe each job (rule R10)
  owner_exclude    names skipped when picking the responsible person
  discovery        {"dirs": [{"repo", "parent", "label"}], "file_trees": [{"repo", "dir", "ext", "label", "gap_id", "legacy_match"}]}
                   what rule R9 looks for that no registry entry covers; registry key `discovery_ignore` lists "<repo>:<dir>" to skip

Usage:   doc_audit.py            run the audit, write doc-gaps.json, print only on failure
         doc_audit.py --report   also print a per-thing summary
         doc_audit.py --dry-run  run and print, do not write the store
         doc_audit.py --wait-lock  wait for a running audit instead of skipping

One run at a time (an exclusive flock on .doc-audit.lock). Without --wait-lock a second run prints one skip line on stderr and exits 0.
Exit codes: 0 audit completed (store written), 2 audit failed (store kept, an alert line is printed so a cron delivers it).
"""

import argparse
import datetime as dt
import fcntl
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server" / "modules"))
import paths  # noqa: E402

DASH = paths.dashboard_dir()
REGISTRY = DASH / "doc-inventory.json"
STORE = DASH / "doc-gaps.json"
RUN_LOCK = DASH / ".doc-audit.lock"

SEV_RANK = {"high": 3, "medium": 2, "low": 1}
SURFACE_LIMIT = 5

# Page types by title keyword. The home page itself is always the overview.
PAGE_TYPES = {
    "design": r"design document|architecture",
    "runbook": r"runbook|operations",
    "quickcard": r"quick card|service desk",
    "troubleshooting": r"troubleshooting",
    "release": r"release process",
    "changelog": r"changelog|release notes",
}
TYPE_LABEL = {
    "design": "Design Document",
    "runbook": "Operations Runbook",
    "quickcard": "Service Desk Quick Card",
    "troubleshooting": "Troubleshooting Guide",
    "release": "Release Process",
    "changelog": "Changelog",
}


class AuditError(Exception):
    """Raised when a source the audit depends on is unreachable."""


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except ValueError:
        try:
            return dt.datetime.strptime(str(s)[:10], "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            return None


def days_since(d):
    return (now_utc() - d).days if d else None


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def config():
    path = Path(os.environ.get("DOC_AUDIT_CONFIG") or DASH / "doc-audit-config.json")
    cfg = load_json(path, {})
    return cfg if isinstance(cfg, dict) else {}


def repos():
    return {name: Path(p) for name, p in (config().get("repos") or {}).items()}


def wiki_url():
    return config().get("wiki_url") or ""


# ---------------------------------------------------------------- git helpers


def git(repo, *args):
    if repo not in repos():
        return None
    p = subprocess.run(
        ["git", "-C", str(repos()[repo]), *args], capture_output=True, text=True, timeout=120
    )
    if p.returncode != 0:
        return None
    return p.stdout


def fetch_repos():
    for name, path in repos().items():
        if not path.exists():
            raise AuditError(f"repo {name} missing at {path}")
        p = subprocess.run(
            ["git", "-C", str(path), "fetch", "-q", "origin"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if p.returncode != 0:
            raise AuditError(f"git fetch failed for {name}: {p.stderr.strip()[:200]}")


def last_commit_date(repo, path):
    out = (
        git(repo, "log", "-1", "--format=%cI", "origin/main", "--", path)
        if path
        else git(repo, "log", "-1", "--format=%cI", "origin/main")
    )
    return parse_date(out.strip()) if out and out.strip() else None


def file_at_main(repo, path):
    return git(repo, "show", f"origin/main:{path}")


def latest_release(repo, spec):
    """Return (version, date, marker_ok). marker_ok False means no machine-readable release marker."""
    if not spec or spec == "none":
        return None, None, False
    kind, _, arg = spec.partition(":")
    if kind == "tag":
        out = git(
            repo,
            "for-each-ref",
            "--sort=-creatordate",
            "--format=%(refname:short) %(creatordate:iso-strict)",
            f"refs/tags/{arg}",
        )
        lines = [ln for ln in (out or "").splitlines() if ln.strip()]
        if not lines:
            return None, None, False
        tag, when = lines[0].split(" ", 1)
        ver = re.sub(r"^.*?-v", "", tag)
        return ver, parse_date(when), True
    if kind == "pkg":
        raw = file_at_main(repo, arg)
        if not raw:
            return None, None, False
        try:
            ver = json.loads(raw).get("version")
        except ValueError:
            return None, None, False
        when = git(repo, "log", "-1", "--format=%cI", "-G", '"version"', "origin/main", "--", arg)
        return ver, parse_date(when.strip()) if when else None, bool(ver)
    return None, None, False


# ------------------------------------------------------------- RACI resolution


def load_raci(conf):
    """Map RACI domain name -> {'A': [names], 'R': [names]} from the docs home RACI page.

    Fails closed (AuditError) when the page or its Domain / Responsibility table cannot be
    read, so a docs home hiccup keeps the previous store instead of dropping every owner.
    """
    page_id = config().get("raci_page_id")
    if not page_id:
        return {}
    text = conf.page(page_id)["body"]
    rows = [ln for ln in text.splitlines() if ln.startswith("|")]
    start = next((i for i, ln in enumerate(rows) if "Domain / Responsibility" in ln), None)
    if start is None:
        raise AuditError(f"RACI page {page_id} has no 'Domain / Responsibility' table")
    rows = rows[start:]
    header = [c.strip() for c in rows[0].strip("|").split("|")]
    people = header[1:]
    out = {}
    for ln in rows[2:]:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 2:
            continue
        domain = cells[0].replace("*", "").strip()
        roles = {"A": [], "R": []}
        for person, cell in zip(people, cells[1:]):
            tokens = [t.strip() for t in re.split(r"[,(]", cell)]
            if "A" in tokens:
                roles["A"].append(person)
            if "R" in tokens:
                roles["R"].append(person)
        out[domain] = roles
    return out


# ------------------------------------------------------------- the docs home (read only, through the consumer's driver)


class DocsHome:
    def __init__(self):
        try:
            cmd = json.loads(os.environ.get("DOCS_HOME_CMD") or "[]")
        except ValueError:
            cmd = []
        self.cmd = [str(a) for a in cmd] if isinstance(cmd, list) else []
        if not self.cmd:
            raise AuditError("no docs home adapter is configured (DOCS_HOME_CMD)")
        self.cloud = config().get("cloud_id") or ""
        self.cache = {}

    def _call(self, tool, args):
        args = dict(args, cloudId=self.cloud)
        try:
            p = subprocess.run(
                [*self.cmd, tool, json.dumps(args)], capture_output=True, text=True, timeout=120
            )
            res = json.loads(p.stdout)["result"]
            text = res["content"][0]["text"]
        except (
            OSError,
            subprocess.SubprocessError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
        ) as e:
            raise AuditError(f"{tool}: the docs home driver failed ({type(e).__name__})") from e
        if res.get("isError"):
            raise AuditError(f"{tool}: {text[:200]}")
        try:
            return json.loads(text)
        except ValueError:
            raise AuditError(f"{tool}: non-JSON result {text[:200]}") from None

    def page(self, page_id):
        key = ("page", page_id)
        if key not in self.cache:
            p = self._call(
                "getConfluencePage", {"pageId": str(page_id), "contentFormat": "markdown"}
            )
            self.cache[key] = {
                "id": str(page_id),
                "title": p.get("title") or "",
                "parent": str(p.get("parentId") or ""),
                "modified": parse_date((p.get("version") or {}).get("createdAt")),
                "body": p.get("body") or "",
            }
        return self.cache[key]

    def descendants(self, page_id):
        key = ("desc", page_id)
        if key not in self.cache:
            d = self._call(
                "searchConfluenceUsingCql",
                {"cql": f"ancestor = {page_id} AND type = page", "limit": 100},
            )
            self.cache[key] = [
                {
                    "id": r["content"]["id"],
                    "title": r["content"].get("title") or "",
                    "modified": parse_date(r.get("lastModified")),
                }
                for r in d.get("results", [])
            ]
        return self.cache[key]


# ------------------------------------------------------------- rules


def gap(gid, rule, sev, text):
    return {"id": gid, "rule": rule, "severity": sev, "text": text}


def audit_thing(t, conf, raci):
    gaps = []
    repo = t.get("repo")
    live = t.get("status") == "live"
    tier = t.get("tier")
    home_id = t.get("confluence_home")
    links = []
    pages = []
    home = None

    # R1 home
    if not home_id:
        sev = ("high" if tier == "A" else "medium") if live else "low"
        gaps.append(gap("R1:home", "R1", sev, f"No docs home page for {t['name']}."))
    else:
        home = conf.page(home_id)
        pages = conf.descendants(home_id)
        links.append({"label": f"Docs home: {home['title']}", "url": wiki_url() + home_id})

    if t.get("status") == "wip":
        return gaps, links, home

    all_pages = ([home] if home else []) + pages
    newest_page = max((p["modified"] for p in all_pages if p.get("modified")), default=None)

    def has_type(tp):
        rx = re.compile(PAGE_TYPES[tp], re.I)
        return any(rx.search(p["title"]) for p in all_pages)

    def body_has(rx):
        return bool(home and re.search(rx, home["body"], re.I | re.M))

    # R2 required pages
    if home:
        if tier == "A":
            required = ["design", "runbook", "troubleshooting", "release", "changelog"]
            if t.get("service_desk"):
                required.insert(2, "quickcard")
            for tp in required:
                if not has_type(tp):
                    gaps.append(
                        gap(
                            f"R2:{tp}",
                            "R2",
                            "medium",
                            f"No {TYPE_LABEL[tp]} page under the {t['name']} home.",
                        )
                    )
        elif tier == "B":
            if not (
                has_type("runbook")
                or body_has(r"^#+ .*(runbook|operations|schedule|failure handling)")
            ):
                gaps.append(
                    gap(
                        "R2:runbook",
                        "R2",
                        "medium",
                        f"{t['name']} has no runbook (schedule, auth, inputs, outputs, failure handling).",
                    )
                )
            if not (
                has_type("changelog")
                or t.get("changelog_page")
                or body_has(r"^#+ .*(changelog|change log|revision history)")
            ):
                gaps.append(
                    gap(
                        "R2:changelog",
                        "R2",
                        "low",
                        f"{t['name']} has no changelog table on its page.",
                    )
                )

    # R3 changelog per release, R8 release markers
    if tier == "A" and live:
        ver, rel_date, marker_ok = latest_release(repo, t.get("release"))
        if not marker_ok:
            gaps.append(
                gap(
                    "R8:marker",
                    "R8",
                    "medium",
                    f"{t['name']} releases carry no machine-readable marker ({t.get('release') or 'none'}), so a missing changelog entry cannot be detected per release.",
                )
            )
        cl_file = t.get("changelog_file")
        cl_text = file_at_main(repo, cl_file) if cl_file else None
        if t.get("changelog") == "confluence":
            # Docs home only documentation: the changelog of record is the Changelog page under the
            # home, which the R3:conf check below holds to each release.
            if not any(re.search(PAGE_TYPES["changelog"], p["title"], re.I) for p in all_pages):
                recent = days_since(last_commit_date(repo, t.get("path")))
                sev = "high" if recent is not None and recent <= 90 else "medium"
                gaps.append(
                    gap(
                        "R3:conf-changelog",
                        "R3",
                        sev,
                        f"No changelog for {t['name']} (no Changelog page under its docs home).",
                    )
                )
        elif not cl_text:
            recent = days_since(last_commit_date(repo, t.get("path")))
            sev = "high" if recent is not None and recent <= 90 else "medium"
            where = f"{cl_file} is not on main" if cl_file else "no changelog file in the repo"
            gaps.append(
                gap("R3:repo-changelog", "R3", sev, f"No changelog for {t['name']} ({where}).")
            )
        elif ver and ver not in cl_text:
            age = days_since(rel_date) or 0
            if age >= 7:
                gaps.append(
                    gap(
                        f"R3:repo:{ver}",
                        "R3",
                        "high" if age >= 14 else "medium",
                        f"Release {ver} ({age} days ago) has no entry in {cl_file}.",
                    )
                )
        if ver and home:
            cl_pages = [
                p for p in all_pages if re.search(PAGE_TYPES["changelog"], p["title"], re.I)
            ]
            if cl_pages:
                body = conf.page(cl_pages[0]["id"])["body"]
                age = days_since(rel_date) or 0
                if ver not in body and age >= 7:
                    gaps.append(
                        gap(
                            f"R3:conf:{ver}",
                            "R3",
                            "medium",
                            f"The docs home changelog does not list release {ver} ({age} days ago).",
                        )
                    )

    # R4 render drift
    if home and t.get("repo_docs"):
        doc_dates = [d for d in (last_commit_date(repo, p) for p in t["repo_docs"]) if d]
        if doc_dates and newest_page:
            lag = (max(doc_dates) - newest_page).days
            if lag > 14:
                gaps.append(
                    gap(
                        "R4:drift",
                        "R4",
                        "medium" if lag > 45 else "low",
                        f"Repo docs changed {lag} days after the newest docs home page (last repo doc change {iso(max(doc_dates))[:10]}, pages {iso(newest_page)[:10]}).",
                    )
                )

    # R5 review age
    if home and newest_page and (days_since(newest_page) or 0) > 180:
        changed = last_commit_date(repo, t.get("path")) if repo else None
        if changed and changed > newest_page:
            gaps.append(
                gap(
                    "R5:age",
                    "R5",
                    "low",
                    f"No docs home page touched in {days_since(newest_page)} days while the code kept changing.",
                )
            )

    # R6 metadata
    if home and tier in ("A", "B"):
        missing = [
            f
            for f, rx in (("Owner", r"\bowner\b"), ("Current version", r"version"))
            if not re.search(rx, home["body"], re.I)
        ]
        if tier == "B" and "Current version" in missing:
            missing.remove("Current version")
        if missing:
            gaps.append(
                gap(
                    "R6:metadata",
                    "R6",
                    "low",
                    f"Home page is missing metadata: {', '.join(missing)}.",
                )
            )

    # R7 placement
    if home and t.get("expected_parent") and home["parent"] != str(t["expected_parent"]):
        gaps.append(
            gap(
                "R7:placement",
                "R7",
                "low",
                f"Home page sits under {home['parent']}, expected {t['expected_parent']}.",
            )
        )

    return gaps, links, home


def _split(v):
    return [p.strip() for p in (v or "").split(",") if p.strip()]


def discover(registry):
    """R9: things in the repos that no registry entry covers. Returns (found directories, [(gap id, label, loose file names)])."""
    disc = config().get("discovery") or {}
    covered = {(t["repo"], t.get("path") or "") for t in registry["things"]}
    ignore = set(registry.get("discovery_ignore", []))
    found = []
    for spec in disc.get("dirs") or []:
        repo, parent = spec["repo"], spec.get("parent") or ""
        out = (
            git(repo, "ls-tree", "-d", "--name-only", "origin/main", *([parent] if parent else []))
            or ""
        )
        for d in out.split():
            name = d[len(parent) :] if parent and d.startswith(parent) else d
            if name.startswith(".") or f"{repo}:{name}" in ignore:
                continue
            rel = parent + name
            if not any(
                r == repo
                and (p in (name, rel) or p.startswith(rel + "/") or p.startswith(name + "/"))
                for r, p in covered
            ):
                found.append(f"{spec.get('label') or repo}/{name}")
    loose = []
    for spec in disc.get("file_trees") or []:
        repo, tree, ext = spec["repo"], spec["dir"], spec.get("ext") or ""
        files = [
            Path(f).name
            for f in (git(repo, "ls-tree", "--name-only", f"origin/main:{tree}") or "").split()
            if not ext or f.endswith(ext)
        ]
        pats = [
            p
            for t in registry["things"]
            if t.get("repo") == repo and t.get("path") == tree
            for p in _split(t.get("match"))
        ]
        if spec.get("legacy_match"):
            pats += [p for t in registry["things"] for p in _split(t.get("legacy_match"))]
        names = sorted(f for f in files if not any(fnmatch.fnmatch(f, p) for p in pats))
        if names:
            loose.append((spec.get("gap_id") or f"{repo}:{tree}", spec.get("label") or tree, names))
    return found, loose


def tree_pages(conf, root_id, lo="2000-01-01", hi="2100-01-01", depth=0):
    """Every current page under root_id, split by created date until no CQL page is truncated.
    Fails closed (AuditError) instead of returning a partial list."""
    cql = f'ancestor = {root_id} AND type = page AND created >= "{lo}" AND created < "{hi}"'
    d = conf._call("searchConfluenceUsingCql", {"cql": cql, "limit": 250})
    res = d.get("results")
    if res is None:
        raise AuditError(f"R11 page listing returned no results field for {root_id}")
    if d.get("totalSize", len(res)) <= len(res):
        return [
            {
                "id": str(r["content"]["id"]),
                "title": r["content"].get("title") or "",
                "created": ((r["content"].get("history") or {}).get("createdDate") or "")[:10],
            }
            for r in res
        ]
    a, b = dt.date.fromisoformat(lo), dt.date.fromisoformat(hi)
    if depth > 20 or (b - a).days < 2:
        raise AuditError(f"R11 page listing under {root_id} still truncated for {lo}..{hi}")
    mid = (a + (b - a) / 2).isoformat()
    return tree_pages(conf, root_id, lo, mid, depth + 1) + tree_pages(
        conf, root_id, mid, hi, depth + 1
    )


def duplicate_gaps(conf):
    """R11: two or more pages in our trees with the same title once a docs home " (N)" suffix is
    stripped. Each set is one gap with an id from its sorted page ids, so it stays stable."""
    seen = {}
    for rid, rname in (config().get("dup_roots") or {}).items():
        for p in tree_pages(conf, rid):
            seen[p["id"]] = dict(p, tree=rname)
    groups = {}
    for p in seen.values():
        groups.setdefault(re.sub(r"\s*\(\d+\)\s*$", "", p["title"].strip()).lower(), []).append(p)
    gaps = []
    for ps in groups.values():
        if len(ps) < 2:
            continue
        ps.sort(key=lambda p: (p["created"], p["id"]))
        ids = sorted(p["id"] for p in ps)
        listing = ", ".join(f"'{p['title']}' {p['id']} (created {p['created']})" for p in ps)
        gaps.append(
            gap(
                f"R11:{'-'.join(ids)}",
                "R11",
                "medium",
                f"Duplicate pages in {ps[0]['tree']}: {listing}. Keep the first, compare the bodies, "
                "and delete the copies.",
            )
        )
    return gaps, len(seen)


def closeout_gaps(conf, thing_ids):
    """R12: changes the sprint close-out shipped whose docs home page does not
    describe them as shipped (doc_check stale or missing). The close-out judges the content,
    this only carries the result. A stale gap clears once its page is edited after the check,
    a missing one once the close-out records covered or resolved. Returns {thing_id: [gaps]}."""
    path = config().get("closeout_state")
    tickets = load_json(path, {}).get("tickets", {}) if path else {}
    out = {}
    for key, rec in sorted(tickets.items()):
        dc = rec.get("doc_check") if isinstance(rec, dict) else None
        if (
            not isinstance(dc, dict)
            or dc.get("resolved")
            or dc.get("result") not in ("stale", "missing")
        ):
            continue
        checked = parse_date(dc.get("at"))
        if checked and len(str(dc.get("at"))) == 10:
            checked += dt.timedelta(days=1)  # date-only check time: only a later-day edit clears it
        page_id = dc.get("page")
        if dc["result"] == "stale" and page_id and checked:
            modified = conf.page(page_id).get("modified")
            if modified and modified > checked:
                continue
        note = (dc.get("note") or "").strip().rstrip(".")
        if dc["result"] == "stale":
            title = dc.get("page_title") or "its page"
            text = f"{key} shipped, but {title} ({wiki_url()}{page_id}) {note or 'does not describe it as shipped'}."
        else:
            text = f"{key} shipped with no docs home page that covers it." + (
                f" {note}." if note else ""
            )
        tid = dc.get("thing") if dc.get("thing") in thing_ids else "_registry"
        sev = "medium" if tid != "_registry" else "low"
        if tid == "_registry":
            text += " No registry thing owns this change."
        out.setdefault(tid, []).append(gap(f"R12:{key}", "R12", sev, text))
    return out


def internal_gaps():
    """R10: agent jobs with no catalog description (the ops center only, never the docs home)."""
    cfg = config()
    jobs = load_json(cfg.get("cron_jobs") or paths.agent_home() / "cron" / "jobs.json", {})
    jobs = jobs.get("jobs", jobs) if isinstance(jobs, dict) else jobs
    cat = load_json(cfg.get("cron_catalog") or DASH / "cron-catalog.json", {}).get("jobs", {})
    return [
        f"{j['id']} {j.get('name', '')}".strip()
        for j in jobs
        if isinstance(j, dict) and j.get("id") not in cat
    ]


# ------------------------------------------------------------- store


def merge_store(prev, results, generated):
    """Carry first_seen, bump the generation when a new gap opens, record closures."""
    things = {}
    for tid, r in results.items():
        old = prev.get("things", {}).get(tid, {})
        old_open = {g["id"]: g for g in old.get("gaps", [])}
        gen = old.get("generation", 0)
        new_ids = [g["id"] for g in r["gaps"] if g["id"] not in old_open]
        if r["gaps"] and (gen == 0 or new_ids):
            gen += 1
        for g in r["gaps"]:
            g["first_seen"] = old_open.get(g["id"], {}).get("first_seen", generated)
        open_ids = {g["id"] for g in r["gaps"]}
        closed = list(old.get("closed", []))
        closed += [
            {"id": gid, "text": g["text"], "closed_utc": generated}
            for gid, g in old_open.items()
            if gid not in open_ids
        ]
        sev = max((SEV_RANK[g["severity"]] for g in r["gaps"]), default=0)
        priority = {3: "high", 2: "medium", 1: "low", 0: "none"}[sev]
        things[tid] = dict(
            r["meta"],
            generation=gen,
            key=f"doc-{tid}-g{gen}" if gen else f"doc-{tid}",
            priority=priority,
            gaps=sorted(r["gaps"], key=lambda g: (-SEV_RANK[g["severity"]], g["id"])),
            new_since_last=new_ids if old else [],
            links=r["links"],
            closed=closed[-20:],
        )
    return things


def surface(things, hidden=()):
    """The slice the Action Center sees: things with high or medium gaps, highest first, capped.
    Things whose registry entry sets action_center false stay in the
    store but never take a slot."""
    cand = [
        t for t in things.values() if t["priority"] in ("high", "medium") and t["id"] not in hidden
    ]
    cand.sort(
        key=lambda t: (
            -SEV_RANK[t["priority"]],
            -sum(SEV_RANK[g["severity"]] for g in t["gaps"]),
            t["id"],
        )
    )
    return [t["id"] for t in cand[:SURFACE_LIMIT]]


def run(args):
    generated = iso(now_utc())
    registry = load_json(REGISTRY, None)
    if not registry or not registry.get("things"):
        raise AuditError(f"registry missing or empty: {REGISTRY.name}")
    prev = load_json(STORE, {})
    fetch_repos()
    conf = DocsHome()
    raci = load_raci(conf)
    exclude = set(config().get("owner_exclude") or [])

    results = {}
    for t in registry["things"]:
        if t.get("audit") is False:
            continue
        gaps, links, home = audit_thing(t, conf, raci)
        roles = raci.get(t.get("raci_domain", ""), {})
        owner_r = (
            next((p for p in roles.get("R", []) if p not in exclude), None)
            or (roles.get("R") or [None])[0]
        )
        results[t["id"]] = {
            "gaps": gaps,
            "links": links,
            "meta": {
                "id": t["id"],
                "name": t["name"],
                "tier": t.get("tier"),
                "status": t.get("status"),
                "raci_domain": t.get("raci_domain"),
                "owner_a": (roles.get("A") or [None])[0],
                "owner_r": owner_r,
                "confluence_home": t.get("confluence_home"),
                "home_title": home["title"] if home else None,
            },
        }

    found, loose = discover(registry)
    reg_gaps = [
        gap(f"R9:{f}", "R9", "low", f"{f} is not in the documentation registry.") for f in found
    ]
    for gap_id, label, names in loose:
        reg_gaps.append(
            gap(
                f"R9:{gap_id}",
                "R9",
                "low",
                f"{len(names)} {label} belong to no registered family: {', '.join(names)}.",
            )
        )
    results["_registry"] = {
        "gaps": reg_gaps,
        "links": [],
        "meta": {
            "id": "_registry",
            "name": "Documentation registry",
            "tier": "internal",
            "status": "live",
        },
    }
    results["_crons"] = {
        "gaps": [
            gap(f"R10:{m.split()[0]}", "R10", "low", f"Job {m} has no cron-catalog.json entry.")
            for m in internal_gaps()
        ],
        "links": [],
        "meta": {"id": "_crons", "name": "Ops center jobs", "tier": "internal", "status": "live"},
    }
    dup_gaps, _ = duplicate_gaps(conf)
    results["_duplicates"] = {
        "gaps": dup_gaps,
        "links": [],
        "meta": {
            "id": "_duplicates",
            "name": "Duplicate docs home pages",
            "tier": "internal",
            "status": "live",
        },
    }

    for tid, extra in closeout_gaps(conf, set(results)).items():
        results[tid]["gaps"].extend(extra)

    things = merge_store(prev, results, generated)
    return {
        "_comment": "Written by the documentation audit (doc_audit.py). Do not hand-edit. Registry: doc-inventory.json.",
        "generated_utc": generated,
        "last_attempt_utc": generated,
        "last_error": None,
        "surface": surface(
            things, {t["id"] for t in registry["things"] if t.get("action_center") is False}
        ),
        "counts": {
            s: sum(1 for t in things.values() for g in t["gaps"] if g["severity"] == s)
            for s in ("high", "medium", "low")
        },
        "things": things,
    }


def report(store):
    print(
        f"doc audit {store['generated_utc']}  gaps high={store['counts']['high']} medium={store['counts']['medium']} low={store['counts']['low']}  surfaced={store['surface']}"
    )
    for t in store["things"].values():
        print(f"- {t['key']:<34} {t['priority']:<6} gaps={len(t['gaps'])} R={t.get('owner_r')}")
        for g in t["gaps"]:
            print(f"    [{g['severity']}] {g['id']}: {g['text']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--wait-lock", action="store_true")
    args = ap.parse_args()
    # The run lock is held for the whole run (read prev store, merge, write) and released on exit.
    with open(RUN_LOCK, "w") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX if args.wait_lock else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("doc_audit: another run holds the lock, skipping", file=sys.stderr)
            return 0
        return _main_locked(args)


def _main_locked(args):
    try:
        store = run(args)
    except (AuditError, subprocess.TimeoutExpired, OSError) as e:
        prev = load_json(STORE, {})
        if prev and not args.dry_run:
            prev["last_attempt_utc"] = iso(now_utc())
            prev["last_error"] = str(e)[:300]
            STORE.write_text(json.dumps(prev, indent=2, ensure_ascii=True) + "\n")
        print(f"Documentation audit FAILED, previous gap store kept: {e}")
        return 2
    if not args.dry_run:
        tmp = STORE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(store, indent=2, ensure_ascii=True) + "\n")
        tmp.replace(STORE)
    if args.report or args.dry_run:
        report(store)
    return 0


if __name__ == "__main__":
    sys.exit(main())
