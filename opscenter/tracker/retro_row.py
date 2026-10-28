#!/usr/bin/env python3
"""Draft and write the owner's row on each sprint's retro page.

Flow, one page per sprint:
  scan     Gate step (cron). Finds the newest retro page (title matching `retro.title_match`) under the retro parent.
           When the owner's row is blank it gathers the sprint facts (the owner's sprint tickets, merged pull requests,
           closures owed) to a facts file and prints a wake brief. Prints {"wakeAgent": false} when there is nothing to do.
  propose  The cron agent hands back the three cells. They are validated (ASCII, no semicolons, no em dashes), stored,
           and raised as one Action Center card with the draft and an Approve button. With auto_write on, the row is
           written at once and the card only reports it.
  write    Writes only the owner's row (ADF edit of that row's cells, version re-checked right before the update), reads
           the page back, records the outcome, closes the card.
  config   Shows or sets auto_write. Autonomy is the owner's call, never flipped by the job.

Parameters (tracker/params.py, the `retro` object): parent_page (the page the retro pages sit under), board_id, row_name,
  repos (code host repos whose merged pull requests count), gh_author, title_match, page_url (prefix of a page link),
  rules (the writing rules the agent gets verbatim; a neutral default applies), plus site_id and the driver.
Store: state/dashboard/retro-rows.json. Stdlib only (system python 3.9). This module has a test (retro_row_test.py).
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "server" / "modules"))
import params  # noqa: E402

ROOT = Path(os.environ.get("OPSCENTER_ROOT") or Path.home() / ".opscenter")
STATE = Path(os.environ.get("OPSCENTER_STATE_DIR") or ROOT / "state")
AGENT = Path(os.environ.get("OPSCENTER_AGENT_HOME") or ROOT / "agent")
STORE_PATH = STATE / "dashboard" / "retro-rows.json"
FACTS_DIR = AGENT / "cache" / "retro-row"
_R = params.get("retro", {}) if isinstance(params.get("retro", {}), dict) else {}
CLOUD = params.get("site_id", "")
RETRO_PARENT = str(_R.get("parent_page", ""))
BOARD_ID = _R.get("board_id")
ROW_NAME = str(_R.get("row_name") or params.get("owner_name", "the owner"))
GH_AUTHOR = str(_R.get("gh_author", ""))
REPOS = tuple(str(r) for r in _R.get("repos", []))
SITE = str(_R.get("page_url", ""))
TITLE_MATCH = str(_R.get("title_match") or "Retro")
PROJECT = str(
    params.get("project", "")
)  # the tracker project whose sprint tickets the retro row covers
SPRINT_FIELD = params.get("sprint_field", "customfield_10020")
POINTS_FIELD = params.get("points_field", "customfield_10016")
_PROJ = f"project={PROJECT} and " if PROJECT else ""
BANNED = re.compile(
    r"\b("
    + "|".join(["automation", *[re.escape(str(w)) for w in _R.get("banned_words", [])]])
    + r")\b",
    re.I,
)
REWAKE_HOURS = 6
MAX_WAKES = 3
CELLS = (
    ("well", "What went well?"),
    ("bad", "What didn't go well?"),
    ("change", "What needs to change?"),
)
MAX_CELL = 1500

# The writing rules the cron agent gets verbatim: the parameter `retro.rules`, else this neutral default.
RULES = list(_R.get("rules") or []) or [
    "Write in the owner's first person, plain direct sentences, ASCII only, no semicolons, no em dashes.",
    "Match the length of a teammate's cell: a short paragraph per cell, never bullet lists.",
    "What went well: the delivered outcomes of the sprint, grouped by theme, with ticket keys in parentheses.",
    "What didn't go well: real misses only (carried or unstarted tickets, closures owed on work that already merged, blockers). Ground every number in the facts file.",
    "What needs to change: only a genuine process change. Business as usual never goes there. Leave it empty when there is nothing real, empty is a fine answer.",
    "Never add an action item for business as usual.",
    "Say a ticket rolled over only when the facts list it in rolled_over_open (more than one sprint). Created long ago is not rolled over.",
    "Every number and ticket state comes from the facts file as gathered. Do not carry claims from earlier drafts or memory.",
    "Never mention automation or tooling as the author.",
]


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts):
    """Parse Atlassian timestamps (Z, +00:00 or -0400 offsets, optional millis) to aware UTC."""
    m = re.match(
        r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}:\d{2}))?(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?",
        (ts or "").strip(),
    )
    if not m:
        raise ValueError("bad timestamp %r" % ts)  # noqa: UP031
    t = dt.datetime.strptime("%s %s" % (m.group(1), m.group(2) or "00:00:00"), "%Y-%m-%d %H:%M:%S")  # noqa: UP031
    off = m.group(3) or "Z"
    if off != "Z":
        sign = -1 if off[0] == "-" else 1
        hh, mm = int(off[1:3]), int(off[-2:])
        t = t - sign * dt.timedelta(hours=hh, minutes=mm)
    return t.replace(tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------- store


def load_store():
    try:
        with open(STORE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("config", {})
            data.setdefault("pages", {})
            return data
    except FileNotFoundError:
        pass
    return {"config": {}, "pages": {}}


def save_store(data):
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(STORE_PATH.parent), prefix=".retro-rows.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
        f.write("\n")
    os.replace(tmp, STORE_PATH)


def config(data):
    c = {"auto_write": False, "auto_after_clean": 3}
    c.update(data.get("config") or {})
    return c


# ---------------------------------------------------------------- connectors


class ConnectorError(Exception):
    pass


def call(tool, args, retried=False):
    args = dict(args)
    args.setdefault("cloudId", CLOUD)
    try:
        proc = subprocess.run(
            [*params.driver_cmd(), tool, json.dumps(args)],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        raise ConnectorError("%s timed out" % tool)  # noqa: B904, UP031
    out = proc.stdout.strip()
    reauth = params.get("reauth_cmd", [])
    if "401" in out and "http_error" in out and not retried and reauth:
        # an optional command that refreshes the tracker sign-in, then the call is tried once more
        subprocess.run([str(a) for a in reauth], capture_output=True, text=True, timeout=180)
        return call(tool, args, retried=True)
    try:
        env, _ = json.JSONDecoder().raw_decode(out)
        res = env["result"]
        if res.get("isError"):
            msg = json.dumps(res)
            try:  # noqa: SIM105
                msg = json.loads(res["content"][0]["text"]).get("message") or msg
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                pass
            raise ConnectorError("%s: %s" % (tool, msg[:200]))  # noqa: UP031
        text = res["content"][0]["text"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise ConnectorError("%s failed: %s" % (tool, (out or proc.stderr)[:300]))  # noqa: B904, UP031
    try:
        return json.loads(text)
    except ValueError:
        return text


def jql_all(jql, fields):
    out, tok = [], None
    for _ in range(20):
        a = {"jql": jql, "fields": fields, "maxResults": 100}
        if tok:
            a["nextPageToken"] = tok
        r = call("searchJiraIssuesUsingJql", a)
        out += r.get("issues", [])
        tok = r.get("nextPageToken")
        if r.get("isLast", True) or not tok:
            break
    return out


def merged_prs(start, end):
    prs = []
    for repo in REPOS:
        q = "merged:%s..%s" % (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))  # noqa: UP031
        p = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "-R",
                repo,
                "--state",
                "merged",
                "--author",
                GH_AUTHOR,
                "--search",
                q,
                "--limit",
                "300",
                "--json",
                "number,title,mergedAt",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if p.returncode != 0:
            raise ConnectorError("gh pr list %s: %s" % (repo, p.stderr[:200]))  # noqa: UP031
        for x in json.loads(p.stdout or "[]"):
            prs.append(
                {
                    "repo": repo.split("/")[1],
                    "number": x["number"],
                    "title": x["title"],
                    "merged": x["mergedAt"][:10],
                }
            )
    return prs


# ---------------------------------------------------------------- page


def newest_retro_page():
    cql = (
        'type=page and parent=%s and title ~ "%s" and created >= now("-21d") order by created desc'  # noqa: UP031
        % (RETRO_PARENT, TITLE_MATCH)
    )
    r = call("searchConfluenceUsingCql", {"cql": cql, "limit": 3})
    for x in r.get("results", []):
        c = x.get("content") or x
        pid = str(c.get("id") or "")
        title = c.get("title") or x.get("title") or ""
        if pid and re.search(re.escape(TITLE_MATCH), title):
            return pid, title
    return None, None


def adf_text(n):
    if not isinstance(n, dict):
        return ""
    if n.get("type") == "text":
        return n.get("text", "")
    return "".join(adf_text(c) for c in n.get("content", []) or [])


def load_page(pid):
    pg = call("getConfluencePage", {"pageId": pid, "contentFormat": "adf"})
    body = pg.get("body")
    doc = json.loads(body) if isinstance(body, str) else body
    return pg, doc


def my_row(doc):
    rows = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "tableRow":
                rows.append(n)
            for c in n.get("content", []) or []:
                walk(c)

    walk(doc)
    mine = [r for r in rows if r.get("content") and adf_text(r["content"][0]).strip() == ROW_NAME]
    if len(mine) != 1:
        return None
    return mine[0]


def row_cells_text(row):
    return [adf_text(c).strip() for c in row["content"][1:]]


# ---------------------------------------------------------------- facts


def find_sprint(page_created):
    issues = jql_all(
        _PROJ + "assignee=currentUser() and updated >= -60d and sprint is not EMPTY", [SPRINT_FIELD]
    )
    sprints = {}
    for i in issues:
        for s in i["fields"].get(SPRINT_FIELD) or []:
            if s.get("boardId") == BOARD_ID and s.get("startDate"):
                sprints[s["id"]] = s
    best = None
    for s in sprints.values():
        start, end = _parse(s["startDate"]), _parse(s.get("endDate") or s["startDate"])
        if start <= page_created <= end + dt.timedelta(days=3) and (
            best is None or _parse(best["startDate"]) < start
        ):
            best = s
    if best is None:
        started = [s for s in sprints.values() if _parse(s["startDate"]) <= page_created]
        best = max(started, key=lambda s: s["startDate"]) if started else None
    return best


def gather(pid, title, page_created):
    sprint = find_sprint(page_created)
    if not sprint:
        raise ConnectorError("no board %s sprint found around %s" % (BOARD_ID, _iso(page_created)))  # noqa: UP031
    start = _parse(sprint["startDate"])
    fields = [
        "summary",
        "status",
        POINTS_FIELD,
        "created",
        "parent",
        SPRINT_FIELD,
        "resolutiondate",
        "issuetype",
        "issuelinks",
    ]
    rows = jql_all(
        _PROJ + "sprint=%s and assignee=currentUser() order by key" % sprint["id"],  # noqa: UP031
        fields,  # noqa: UP031
    )  # noqa: UP031
    prs = merged_prs(start, _now())
    tickets = []
    for i in rows:
        f = i["fields"]
        cat = f["status"]["statusCategory"]["name"]
        sprints = [s["name"] for s in (f.get(SPRINT_FIELD) or [])]
        linked = []
        for ln in f.get("issuelinks") or []:
            other = ln.get("outwardIssue") or ln.get("inwardIssue") or {}
            if other.get("key"):
                linked.append(other["key"])
        evidence = [p for p in prs if re.search(r"\b%s\b" % re.escape(i["key"]), p["title"])]  # noqa: UP031
        for k in linked:
            evidence += [p for p in prs if re.search(r"\b%s\b" % re.escape(k), p["title"])]  # noqa: UP031
        tickets.append(
            {
                "key": i["key"],
                "summary": f["summary"],
                "status": f["status"]["name"],
                "done": cat == "Done",
                "points": f.get(POINTS_FIELD),
                "epic": ((f.get("parent") or {}).get("fields") or {}).get("summary", ""),
                "created": f["created"][:10],
                "added_mid_sprint": _parse(f["created"]) > start + dt.timedelta(days=1),
                "sprints": sprints,
                "rolled_over": len(sprints) > 1 and cat != "Done",
                "linked": linked,
                "merged_pr_evidence": [
                    "%s #%s %s" % (p["repo"], p["number"], p["title"])  # noqa: UP031
                    for p in evidence  # noqa: UP031
                ][:6],  # noqa: UP031
            }
        )
    done = [t for t in tickets if t["done"]]
    open_ = [t for t in tickets if not t["done"]]
    pts = lambda ts: sum(t["points"] or 0 for t in ts)  # noqa: E731
    added = [t for t in tickets if t["added_mid_sprint"]]
    facts = {
        "page": {"id": pid, "title": title, "url": SITE + pid, "created": _iso(page_created)},
        "sprint": {
            "id": sprint["id"],
            "name": sprint["name"],
            "start": sprint["startDate"][:10],
            "end": (sprint.get("endDate") or "")[:10],
        },
        "totals": {
            "tickets": len(tickets),
            "done": len(done),
            "done_points": pts(done),
            "open": len(open_),
            "open_points": pts(open_),
            "added_mid_sprint": len(added),
            "added_points": pts(added),
            "merged_prs": {
                r.split("/")[1]: sum(1 for p in prs if p["repo"] == r.split("/")[1]) for r in REPOS
            },
        },
        "closures_owed": [t["key"] for t in open_ if t["merged_pr_evidence"]],
        "rolled_over_open": [t["key"] for t in open_ if t["rolled_over"]],
        "tickets": tickets,
        "merged_prs": prs,
        "rules": RULES,
        "examples": approved_examples(),
    }
    FACTS_DIR.mkdir(parents=True, exist_ok=True)
    path = FACTS_DIR / ("%s-facts.json" % pid)  # noqa: UP031
    with open(path, "w", encoding="utf-8") as f:
        json.dump(facts, f, indent=2)
    return facts, path


def approved_examples():
    out = []
    for _pid, p in sorted(
        load_store()["pages"].items(), key=lambda kv: kv[1].get("written_at") or "", reverse=True
    ):
        if p.get("state") == "written" and p.get("final"):
            out.append({"title": p.get("title"), "cells": p["final"]})
        if len(out) >= 2:
            break
    return out


# ---------------------------------------------------------------- commands


def cmd_scan(force=False):
    data = load_store()
    pid, title = newest_retro_page()
    if not pid:
        return {"wake": False, "why": "no retro page in the last 21 days"}
    rec = data["pages"].get(pid) or {}
    state = rec.get("state")
    if state in ("drafted", "written", "filled", "skipped") and not force:
        return {"wake": False, "why": "page %s already %s" % (pid, state)}  # noqa: UP031
    if state == "woken" and not force:
        last = _parse(rec.get("woken_at"))
        if rec.get("wakes", 0) >= MAX_WAKES:
            return {
                "wake": False,
                "why": "page %s woke %s times with no draft" % (pid, rec.get("wakes")),  # noqa: UP031
            }  # noqa: UP031
        if _now() - last < dt.timedelta(hours=REWAKE_HOURS):
            return {"wake": False, "why": "page %s waiting on the draft" % pid}  # noqa: UP031
    pg, doc = load_page(pid)
    row = my_row(doc)
    if row is None:
        data["pages"][pid] = {
            "state": "skipped",
            "title": title,
            "why": "no single %s row on the page" % ROW_NAME,  # noqa: UP031
            "at": _iso(_now()),
        }
        save_store(data)
        return {"wake": False, "why": "no %s row" % ROW_NAME}  # noqa: UP031
    cells = row_cells_text(row)
    if any(cells):
        data["pages"][pid] = {"state": "filled", "title": title, "cells": cells, "at": _iso(_now())}
        save_store(data)
        return {"wake": False, "why": "the owner's row already has content"}
    facts, path = gather(pid, title, _parse(pg.get("createdAt") or _iso(_now())))
    data = load_store()
    data["pages"][pid] = {
        "state": "woken",
        "title": title,
        "woken_at": _iso(_now()),
        "wakes": rec.get("wakes", 0) + 1,
        "sprint": facts["sprint"]["name"],
        "facts": str(path),
    }
    save_store(data)
    return {"wake": True, "pid": pid, "title": title, "facts": facts, "path": str(path)}


def validate_cells(cells):
    clean = {}
    for k, _label in CELLS:
        v = str(cells.get(k) or "").strip()
        if len(v) > MAX_CELL:
            raise ValueError("%s is longer than %d characters" % (k, MAX_CELL))  # noqa: UP031
        if ";" in v:
            raise ValueError("%s contains a semicolon" % k)  # noqa: UP031
        if "\u2014" in v or "\u2013" in v:
            raise ValueError("%s contains an em or en dash" % k)  # noqa: UP031
        if not v.isascii():
            raise ValueError("%s contains non-ASCII characters" % k)  # noqa: UP031
        if BANNED.search(v):
            raise ValueError("%s names internal tooling" % k)  # noqa: UP031
        clean[k] = v
    if not any(clean.values()):
        raise ValueError("all three cells are empty")
    return clean


def _raise_card(pid, rec, cells, written=False):
    import automation_actions  # noqa: E402

    t = rec.get("totals") or {}
    why = (
        "The %s retro page is up and the owner's row was blank. The draft comes from the owner's %s sprint tickets "  # noqa: UP031
        "(%s done, %s open) and %s merged PRs in the sprint window."
        % (
            rec.get("sprint") or "sprint",
            t.get("tickets", "?"),
            t.get("done", "?"),
            t.get("open", "?"),
            t.get("prs", "?"),
        )
    )
    draft = {
        "label": "Draft for the owner's row",
        "fields": [{"key": k, "label": lab, "text": cells.get(k, "")} for k, lab in CELLS],
    }
    if written:
        title = "Retro row written: %s" % rec.get("title")  # noqa: UP031
        action = "Written to the page automatically. Check it reads right, then Resolve."
        approve = None
    else:
        title = "Retro row ready to approve: %s" % rec.get("title")  # noqa: UP031
        action = "Approve writes only the owner's row. Edit changes the wording first (an empty cell stays empty). Ignore skips this sprint."
        approve = {"label": "Approve and write", "kind": "retro-row", "page": pid}
    return automation_actions.raise_item(
        "retro-%s" % pid,  # noqa: UP031
        title,
        why,
        action,
        priority="medium",
        refs=[],
        links=[{"label": "Retro page", "url": SITE + pid}],
        source="Retro row drafter",
        extra={"draft": draft, "approve": approve} if approve else {"draft": draft},
    )


def cmd_propose(pid, cells):
    cells = validate_cells(cells)
    data = load_store()
    rec = data["pages"].get(pid)
    if not rec:
        raise ValueError("page %s was never scanned" % pid)  # noqa: UP031
    if rec.get("state") in ("written", "filled"):
        raise ValueError("page %s is already %s" % (pid, rec["state"]))  # noqa: UP031
    try:
        with open(rec.get("facts") or "", encoding="utf-8") as f:
            facts = json.load(f)
        tot = facts["totals"]
        rec["totals"] = {
            "tickets": tot["tickets"],
            "done": tot["done"],
            "open": tot["open"],
            "prs": sum(tot["merged_prs"].values()),
        }
    except (OSError, ValueError, KeyError):
        rec.setdefault("totals", {})
    rec.update({"state": "drafted", "draft": cells, "drafted_at": _iso(_now())})
    data["pages"][pid] = rec
    save_store(data)
    if config(data)["auto_write"]:
        res = cmd_write(pid, None, edited=False, auto=True)
        _raise_card(pid, load_store()["pages"][pid], cells, written=True)
        return {"ok": True, "auto_written": True, "version": res.get("version")}
    _raise_card(pid, rec, cells)
    return {"ok": True, "card": "auto-retro-%s" % pid}  # noqa: UP031


def cited_keys(text):
    """Ticket keys of the project a cell cites, including shorthand lists like 'KEY-5547, 5548 and 5552'."""
    keys = []
    pre = re.escape(PROJECT) if PROJECT else r"[A-Z][A-Z0-9]{1,9}"
    for m in re.finditer(
        r"(%s)-(\d+)((?:\s*,\s*(?:and\s+)?\d{3,6}|\s+and\s+\d{3,6})*)" % pre,  # noqa: UP031
        text or "",  # noqa: UP031
    ):  # noqa: UP031
        keys.append("%s-%s" % (m.group(1), m.group(2)))  # noqa: UP031
        keys += ["%s-%s" % (m.group(1), n) for n in re.findall(r"\d{3,6}", m.group(3) or "")]  # noqa: UP031
    return sorted(set(keys))


def stale_claims(pid, final):
    """Tickets the draft cites whose done/open state changed since the facts were gathered."""
    rec = load_store()["pages"].get(pid) or {}
    try:
        with open(rec.get("facts") or "", encoding="utf-8") as f:
            then = {t["key"]: t["done"] for t in json.load(f)["tickets"]}
    except (OSError, ValueError, KeyError):
        return []
    keys = [k for k in cited_keys(" ".join(final.values())) if k in then]
    if not keys:
        return []
    now = jql_all("key in (%s)" % ",".join(keys), ["status"])  # noqa: UP031
    out = []
    for i in now:
        done = i["fields"]["status"]["statusCategory"]["name"] == "Done"
        if done != then[i["key"]]:
            out.append("%s is now %s" % (i["key"], i["fields"]["status"]["name"]))  # noqa: UP031
    return out


def _cell_content(text):
    if not text:
        return [{"type": "paragraph", "content": []}]
    return [
        {"type": "paragraph", "content": [{"type": "text", "text": p}]}
        for p in text.split("\n\n")
        if p.strip()
    ]


def cmd_write(pid, cells, edited=False, auto=False, force=False):
    data = load_store()
    rec = data["pages"].get(pid)
    if not rec or not rec.get("draft"):
        raise ValueError("no draft stored for page %s" % pid)  # noqa: UP031
    final = validate_cells(cells if cells is not None else rec["draft"])
    if cells is not None:
        edited = edited or any(final.get(k, "") != rec["draft"].get(k, "") for k, _ in CELLS)
    # An edit is the owner's own check of the wording, so the staleness guard only covers untouched drafts.
    force = force or edited
    if not force:
        changed = stale_claims(pid, final)
        if changed:
            raise ValueError(
                "the draft is out of date (%s). Edit it, then approve again." % ", ".join(changed)  # noqa: UP031
            )  # noqa: UP031
    pg, doc = load_page(pid)
    ver = pg["version"]["number"]
    FACTS_DIR.mkdir(parents=True, exist_ok=True)
    backup = FACTS_DIR / ("%s-v%s-backup.adf.json" % (pid, ver))  # noqa: UP031
    with open(backup, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    row = my_row(doc)
    if row is None:
        raise ValueError("the page no longer has a single %s row" % ROW_NAME)  # noqa: UP031
    if len(row["content"]) != 4:
        raise ValueError("the owner's row has %d cells, expected 4" % len(row["content"]))  # noqa: UP031
    if any(row_cells_text(row)):
        raise ValueError("the owner's row already has content on the page, nothing written")
    for (k, _), cell in zip(CELLS, row["content"][1:]):
        cell["content"] = _cell_content(final[k])
    live = call("getConfluencePage", {"pageId": pid, "contentFormat": "markdown"})
    if live["version"]["number"] != ver:
        raise ValueError(
            "the page changed while writing (v%s to v%s), try again"  # noqa: UP031
            % (ver, live["version"]["number"])
        )  # noqa: UP031
    call(
        "updateConfluencePage",
        {
            "pageId": pid,
            "title": pg["title"],
            "body": json.dumps(doc),
            "contentFormat": "adf",
            "versionMessage": "Added the owner's retro row",
        },
    )
    pg2, doc2 = load_page(pid)
    row2 = my_row(doc2)
    got = row_cells_text(row2) if row2 else []
    want = [final[k].replace("\n\n", "") for k, _ in CELLS]
    if [g.replace("\n", "") for g in got] != [w.replace("\n", "") for w in want]:
        raise ValueError(
            "read-back does not match the draft (page v%s), check the page"  # noqa: UP031
            % pg2["version"]["number"]
        )  # noqa: UP031
    data = load_store()
    rec = data["pages"][pid]
    rec.update(
        {
            "state": "written",
            "final": final,
            "edited": bool(edited),
            "auto": auto,
            "written_at": _iso(_now()),
            "version": pg2["version"]["number"],
            "backup": str(backup),
        }
    )
    save_store(data)
    if not auto:
        import automation_actions  # noqa: E402

        automation_actions.close_item(
            "retro-%s" % pid,  # noqa: UP031
            "written to the page, v%s" % pg2["version"]["number"],  # noqa: UP031
        )  # noqa: UP031
    _maybe_suggest_autonomy(load_store())
    return {"ok": True, "version": pg2["version"]["number"], "edited": bool(edited)}


def _maybe_suggest_autonomy(data):
    c = config(data)
    if c["auto_write"]:
        return
    written = sorted(
        (p for p in data["pages"].values() if p.get("state") == "written" and not p.get("auto")),
        key=lambda p: p.get("written_at") or "",
        reverse=True,
    )
    streak = 0
    for p in written:
        if p.get("edited"):
            break
        streak += 1
    if streak >= c["auto_after_clean"]:
        import automation_actions  # noqa: E402

        automation_actions.raise_item(
            "retro-autonomy",
            "Retro row drafter: %d sprints approved with no edits" % streak,  # noqa: UP031
            "The last %d retro rows went out exactly as drafted." % streak,  # noqa: UP031
            "Decide whether the drafter writes the owner's row on its own from now on: "
            "python3 ops-home/state/ops-center-app/retro_row.py config --auto-write on. "
            "It would still raise a card after each write.",
            priority="low",
            source="Retro row drafter",
        )


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Draft and write the owner's row on each sprint retro page (improvement-id)."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--force", action="store_true")
    p = sub.add_parser("propose")
    p.add_argument("--page", required=True)
    p.add_argument(
        "--cells-file", required=True, help='JSON {"well": "...", "bad": "...", "change": ""}'
    )
    w = sub.add_parser("write")
    w.add_argument("--page", required=True)
    w.add_argument("--cells-file", help="edited cells, JSON like propose")
    w.add_argument("--edited", action="store_true")
    c = sub.add_parser("config")
    c.add_argument("--auto-write", choices=("on", "off"))
    sub.add_parser("status")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "scan":
            res = cmd_scan(a.force)
            f = res.pop("facts", None)
            if f:
                res.update(
                    {
                        k: f[k]
                        for k in ("page", "sprint", "totals", "closures_owed", "rolled_over_open")
                    }
                )
            print(json.dumps(res, default=str))
        elif a.cmd == "propose":
            with open(a.cells_file, encoding="utf-8") as f:
                print(json.dumps(cmd_propose(a.page, json.load(f))))
        elif a.cmd == "write":
            cells = None
            if a.cells_file:
                with open(a.cells_file, encoding="utf-8") as f:
                    cells = json.load(f)
            print(json.dumps(cmd_write(a.page, cells, edited=a.edited)))
        elif a.cmd == "config":
            data = load_store()
            if a.auto_write:
                data["config"]["auto_write"] = a.auto_write == "on"
                save_store(data)
            print(json.dumps(config(data)))
        else:
            data = load_store()
            print(
                json.dumps(
                    {
                        "config": config(data),
                        "pages": {
                            k: {
                                kk: v.get(kk)
                                for kk in ("state", "title", "sprint", "edited", "version")
                            }
                            for k, v in data["pages"].items()
                        },
                    },
                    indent=2,
                )
            )
    except (ValueError, ConnectorError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
