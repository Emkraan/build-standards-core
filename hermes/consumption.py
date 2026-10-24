#!/usr/bin/env python3
"""Write the machine's core consumption feed: ~/.config/build-standards-core/consumption.json.

Called by hermes/nightly.py once per run (step 6, apply.consumption). Any ops center on the machine
renders its "Core consumption panel" from this one file (standards/local-ops-app.md section 19), so
every ops center shows the same data. The file is local to the machine and is never posted: it may
carry repo names, which the report sections never do.

What it holds (format "build-standards-consumption/1", the schema is in standards/local-ops-app.md
section 19.2):
  - per registered consumer: its consumption class (apply-at-once for an ops center, approval-gated
    for every other app), the pinned release against the latest, how many releases behind, the open
    sync pull request with its CI state (workflow and vendored repos), the core-status counts and UI
    verdict, and adoption suggestions (local parts a kit part now covers, with the adoption-risk
    level when this account's consumer report gives one);
  - account: this account's consumer-report items waiting for an owner decision, and approved items
    this account owns with no core pull request open for them;
  - peers: every open consumer-report issue's items with their status, and approved D items from
    other accounts that shipped in the kit, as suggestions this machine's apps could adopt.

The rules, each with its reason:
- Read-only. Every gh call here is a read; nothing is written to any issue, pull request or repo,
  so the feed can never act for the owner. Approvals happen in the ops center, one action each,
  through the normal pull request path.
- Atomic. The file is written to a temporary file beside it and renamed over it, so a panel never
  reads half a file.
- Never guess. A value that could not be read is null, with the reason in not_collected.

Python 3.9, stdlib only. Network access only through the gh CLI, passed in as sh so tests run on
fixtures.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Callable

import report

Sh = Callable[..., "tuple[int, str]"]

FORMAT = "build-standards-consumption/1"
FILE = "consumption.json"
APPLY_AT_ONCE = "apply-at-once"
APPROVAL_GATED = "approval-gated"
ITEM_ID = r"[DPG]-\d{3}"
ITEM_HEAD = re.compile(r"\*\*(" + ITEM_ID + r")\s+([^*\n]+?)\*\*\s*(?:\(([^)\n]*)\))?")
RELEASE = re.compile(r"\bv\d+\.\d+\.\d+\b")
RELEASE_HEAD = re.compile(r"^## \d{4}-\d{2}-\d{2} \((v\d+\.\d+\.\d+)", re.M)
RISKS = ("none", "low", "medium", "high")
STATUSES = ("awaiting decision", "approved", "held", "rejected", "shipped")


def consumption_class(mode: str) -> str:
    """An ops center takes every release at once; every other app only through owner approval."""
    return APPLY_AT_ONCE if mode in ("ops-center", "local") else APPROVAL_GATED


# Pure functions (tests/test_consumption.py runs them on fixtures) ------------------------------


def behind_count(pinned: str, latest: str, tags: list[str]) -> int | None:
    """Releases between pinned and latest in tags (newest first). None when either is unknown."""
    if not pinned or not latest or pinned not in tags or latest not in tags:
        return None
    return max(0, tags.index(pinned) - tags.index(latest))


def ci_state(rollup: list[dict]) -> str:
    """pass, fail, pending or none, from a pull request's statusCheckRollup."""
    if not rollup:
        return "none"
    states = set()
    for c in rollup:
        v = (c.get("conclusion") or c.get("state") or c.get("status") or "").upper()
        if v in (
            "FAILURE",
            "ERROR",
            "CANCELLED",
            "TIMED_OUT",
            "ACTION_REQUIRED",
            "STARTUP_FAILURE",
        ):
            states.add("fail")
        elif v in ("SUCCESS", "NEUTRAL", "SKIPPED"):
            states.add("pass")
        else:
            states.add("pending")
    return "fail" if "fail" in states else "pending" if "pending" in states else "pass"


def risk_levels(body: str) -> dict[str, str]:
    """{part name: risk} from the adoption risk table rows of a consumer report: a table row that
    names a part in backticks and has a cell that is exactly one of none, low, medium, high."""
    out: dict = {}
    for line in body.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip().strip("*").lower() for c in line.strip().strip("|").split("|")]
        risk = next((c for c in cells if c in RISKS), "")
        names = re.findall(r"`([A-Z][A-Za-z0-9]+)`", line)
        if risk and names:
            out.setdefault(names[0], risk)
    return out


def adoption(local: dict[str, str], kit: set[str], risks: dict[str, str]) -> list[dict]:
    """Local parts a kit part now covers, from report.relation over the kit's export list."""
    rows = []
    for name in sorted(local):
        rel = report.relation(name, kit)
        if not rel:
            continue
        rows.append(
            {
                "part": name,
                "file": local[name],
                "kit_part": name if rel == "duplicates" else rel.split(" ", 1)[1],
                "relation": "duplicates" if rel == "duplicates" else "extends",
                "risk": risks.get(name),
            }
        )
    return rows


def shipped_ids(changelog: str) -> dict[tuple, str]:
    """{(issue number, item id): release} from the core changelog: a parenthesised group that names
    an issue and item ids, such as (#115 G-001) or (#117 D-015, D-016), under a release heading."""
    out: dict = {}
    heads = list(RELEASE_HEAD.finditer(changelog))
    for i, h in enumerate(heads):
        text = changelog[h.end() : heads[i + 1].start() if i + 1 < len(heads) else len(changelog)]
        for group in re.findall(r"\(([^()]*#\d+[^()]*)\)", text):
            issues = re.findall(r"#(\d+)", group)
            for iid in re.findall(ITEM_ID, group):
                for n in issues:
                    out.setdefault((int(n), iid), h.group(1))  # newest release first in the file
    return out


def decisions(comments: list[dict], owner: str) -> dict[str, str]:
    """{item id: approved | rejected | held} from the owner's comments, the latest decision winning.
    Recognised forms: "approve D-003", "Approved: D-015, D-016 (...)", "reject P-002: reason",
    "hold G-004"."""
    out: dict = {}
    verbs = (
        ("approved", r"approve[ds]?"),
        ("rejected", r"reject(?:ed|s)?"),
        ("held", r"(?:hold|held|holds)"),
    )
    for c in comments:
        if owner and (c.get("author") or {}).get("login", "").lower() != owner.lower():
            continue
        for line in (c.get("body") or "").splitlines():
            for status, verb in verbs:
                for m in re.finditer(
                    r"\b"
                    + verb
                    + r"\b:?\s*((?:"
                    + ITEM_ID
                    + r"(?:\s*\([^)]*\))?[\s,]*(?:and\s+)?)+)",
                    line,
                    re.I,
                ):
                    for iid in re.findall(ITEM_ID, m.group(1)):
                        out[iid] = status
    return out


def item_status(note: str, decision: str, shipped: str) -> tuple[str, str | None]:
    """(status, shipped_in) for one item. Shipped in the changelog wins, then the owner's comment,
    then the state the report itself gives in its parentheses."""
    note = (note or "").lower()
    m = RELEASE.search(note)
    if shipped:
        return "shipped", shipped
    if ("closed by" in note or "shipped" in note) and m:
        return "shipped", m.group(0)
    if decision:
        return decision, None
    for word, status in (
        ("rejected", "rejected"),
        ("approved", "approved"),
        ("held", "held"),
        ("settling", "held"),
    ):
        if word in note:
            return status, None
    return "awaiting decision", None


def issue_items(issue: dict, owner: str, shipped: dict[tuple, str]) -> list[dict]:
    """Every item of one consumer-report issue, with its status."""
    dec = decisions(issue.get("comments") or [], owner)
    seen: dict = {}
    for m in ITEM_HEAD.finditer(issue.get("body") or ""):
        iid, title, note = m.group(1), m.group(2).strip(), m.group(3) or ""
        if iid in seen:
            continue
        status, release = item_status(
            note, dec.get(iid, ""), shipped.get((issue["number"], iid), "")
        )
        seen[iid] = {
            "id": iid,
            "title": title,
            "kind": iid[0],
            "status": status,
            "shipped_in": release,
        }
    return [seen[k] for k in sorted(seen)]


def peers_block(issues: list[dict], me: str, owner: str, changelog: str, previous: dict) -> dict:
    """The peers block: every open report's items, and other accounts' shipped D items as
    suggestions (new marks the ones shipped since the last run)."""
    shipped = shipped_ids(changelog)
    before = {(s["issue"], s["id"]) for s in (previous.get("peers") or {}).get("suggestions", [])}
    first_run = not previous
    out_issues, suggestions = [], []
    for iss in sorted(issues, key=lambda i: i["number"]):
        author = (iss.get("author") or {}).get("login", "")
        items = issue_items(iss, owner, shipped)
        mine = bool(me) and author.lower() == me.lower()
        out_issues.append(
            {
                "number": iss["number"],
                "url": iss.get("url", ""),
                "author": author,
                "mine": mine,
                "items": items,
            }
        )
        if mine:
            continue
        for it in items:
            if it["kind"] == "D" and it["status"] == "shipped":
                key = (iss["number"], it["id"])
                suggestions.append(
                    {
                        "issue": iss["number"],
                        "id": it["id"],
                        "title": it["title"],
                        "author": author,
                        "shipped_in": it["shipped_in"],
                        "new": not first_run and key not in before,
                    }
                )
    return {"issues": out_issues, "suggestions": suggestions}


def own_items(own: list[dict] | None, owner: str, changelog: str) -> list[dict] | None:
    """This account's report issues, open or closed, most recent first, each with its items."""
    if own is None:
        return None
    shipped = shipped_ids(changelog)
    return [
        {"number": i["number"], "url": i.get("url", ""), "items": issue_items(i, owner, shipped)}
        for i in sorted(own, key=lambda i: i["number"], reverse=True)
    ]


def account_block(peers: dict, open_prs: list[dict], own: list[dict] | None = None) -> dict:
    """This account's items waiting for the owner (open reports), and approved items with no core PR
    open, read from own (every report of the account, open or closed, most recent first) when given.
    An id is the account's for good, so the most recent issue with a decision on it decides; an item
    approved on a closed issue still counts (#117 G-037)."""
    mine = [i for i in peers["issues"] if i["mine"]]
    awaiting, unopened = [], []
    for iss in mine:
        for it in iss["items"]:
            if it["status"] == "awaiting decision":
                awaiting.append({"issue": iss["number"], "id": it["id"], "title": it["title"]})
    decided: dict = {}  # id -> (issue number, item): the most recent issue with a decision on it
    for iss in own if own is not None else mine:
        for it in iss["items"]:
            if it["id"] not in decided and it["status"] != "awaiting decision":
                decided[it["id"]] = (iss["number"], it)
    for iid in sorted(decided):
        number, it = decided[iid]
        if it["status"] != "approved":
            continue
        linked = [
            p
            for p in open_prs
            if iid in f"{p.get('title', '')}\n{p.get('body', '')}"
            and f"#{number}" in f"{p.get('title', '')}\n{p.get('body', '')}"
        ]
        if not linked:
            unopened.append({"issue": number, "id": iid, "title": it["title"]})
    report_issue = mine[0]["url"] if mine else (own[0]["url"] if own else None)
    return {
        "report_issue": report_issue,
        "awaiting_decision": awaiting,
        "approved_unopened": unopened,
    }


CI_UNREAD = re.compile(r"^--ci: (?:no run of (\S+)|cannot read run \S+ of (\S+))")


def ci_counts(rules: list[dict], problems: list[str], ci_read: bool) -> tuple[dict, list[str]]:
    """Status counts with the repo's CI results (#117 G-036). An overlay-ci rule whose workflow's
    result was not read is unverified, never fail; each unread workflow is one not_collected line."""
    unread = set()
    for p in problems:
        m = CI_UNREAD.match(p)
        if m:
            unread.add(m.group(1) or m.group(2))
    counts = {k: 0 for k in report.STATUS_KEYS}
    moved = 0
    for r in rules:
        status = r.get("status")
        if r.get("kind") == "overlay-ci" and status == "fail":
            note = str(r.get("note") or "")
            if not ci_read or any(w in note for w in unread):
                status, moved = "unverified", moved + 1
        if status in counts:
            counts[status] += 1
    reasons = []
    if not ci_read:
        reasons.append("status: CI results not collected (core-status --ci gave no report)")
    reasons += [
        f"status: CI results of {w} not collected (no readable run)" for w in sorted(unread)
    ]
    if moved:
        reasons.append(
            f"status: {moved} CI rule(s) reported unverified, not fail, while their CI result is unread"
        )
    return counts, reasons


def write_atomic(path: Path, data: dict) -> None:
    """Write JSON to a temporary file beside path, then rename it over path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# I/O around them -----------------------------------------------------------------------------


def _json(sh: Sh, cmd: list[str], default):
    rc, out = sh(cmd)
    if rc != 0:
        raise RuntimeError(out[-200:] or f"exit {rc}")
    try:
        return json.loads(out or "null") if out else default
    except ValueError as exc:
        raise RuntimeError(f"unreadable gh output: {exc}") from exc


def local_pin(c: dict) -> str:
    """The release in the local clone's standards.lock, "" when there is none."""
    if not c.get("path"):
        return ""
    overlay = c.get("overlay", "standards-overlay")
    base = Path(c["path"]).expanduser()
    lock = (base / overlay if overlay else base) / "standards.lock"
    try:
        for line in lock.read_text(encoding="utf8").splitlines():
            if line.startswith("ref="):
                return line[4:].strip()
    except OSError:
        pass
    return ""


def sync_pr(c: dict, sh: Sh) -> dict | None:
    """The open sync pull request of a workflow or vendored repo: head branch starting with the
    entry's sync_head (default chore/core-, the core-update.yml branch; a vendoring tool names its own)."""
    head = c.get("sync_head", "chore/core-")
    prs = _json(
        sh,
        [
            "gh",
            "pr",
            "list",
            "-R",
            c["repo"],
            "--state",
            "open",
            "--json",
            "number,url,headRefName,createdAt,statusCheckRollup",
            "-L",
            "50",
        ],
        [],
    )
    prs = [p for p in prs or [] if str(p.get("headRefName", "")).startswith(head)]
    if not prs:
        return None
    p = sorted(prs, key=lambda x: x.get("createdAt", ""))[-1]
    return {
        "number": p["number"],
        "url": p.get("url", ""),
        "head": p.get("headRefName", ""),
        "created_at": p.get("createdAt", ""),
        "ci": ci_state(p.get("statusCheckRollup") or []),
    }


def consumer_row(
    c: dict,
    latest: str,
    tags: list[str],
    core: Path,
    sh: Sh,
    risks: dict,
    pinned_remote: Callable[[dict], str],
) -> dict:
    mode = c.get("mode", "workflow")
    if mode == "local":
        mode = "ops-center"
    row = {
        "repo": c["repo"],
        "label": report.repo_label(c["repo"]),
        "mode": mode,
        "class": consumption_class(mode),
        "report_only": c.get("apply") is False,
        "pinned": None,
        "latest": latest or None,
        "behind": None,
        "sync_pr": None,
        "status": None,
        "ui_verdict": None,
        "adoption": [],
        "not_collected": [],
    }
    try:
        # A vendored repo's release comes from the machine's vendored record (#117 G-031), which
        # pinned_remote reads; any other repo's from its local clone first, then its default branch.
        row["pinned"] = (local_pin(c) if mode != "vendored" else "") or pinned_remote(c) or None
    except Exception as exc:
        row["not_collected"].append(f"pinned: {exc}")
    row["behind"] = behind_count(row["pinned"] or "", latest, tags)
    if mode != "ops-center":
        try:
            row["sync_pr"] = sync_pr(c, sh)
        except Exception as exc:
            row["not_collected"].append(f"sync_pr: {exc}")
    if c.get("path"):
        clone = Path(c["path"]).expanduser()
        overlay = "" if mode == "vendored" else c.get("overlay", "standards-overlay")
        snap = report.snapshot(clone, overlay, sh, ci=mode != "vendored")
        if snap["status"]:
            row["status"], row["ui_verdict"] = snap["status"], snap["ui"] or None
            if snap.get("rules"):
                row["status"], reasons = ci_counts(
                    snap["rules"], snap.get("problems", []), snap.get("ci_read", False)
                )
                row["not_collected"] += reasons
        else:
            row["not_collected"].append(
                "status: no core-status.py in the clone"
                if mode != "vendored"
                else "status: a vendored repo carries no core-status.py by design"
            )
        kit = report.kit_parts(clone, overlay, str(core / "kit" / "src"))
        row["adoption"] = adoption(report.local_parts(clone, overlay), kit, risks)
    else:
        row["not_collected"].append("status and adoption: no local clone (path) registered")
    return row


def build(
    cfg: dict,
    core: Path,
    core_repo: str,
    latest: str,
    sh: Sh,
    previous: dict,
    pinned_remote: Callable[[dict], str],
) -> dict:
    """The whole feed. Every read failure lands in not_collected; nothing here writes remotely."""
    data = {
        "format": FORMAT,
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "core_repo": core_repo or None,
        "latest": latest or None,
        "consumers": [],
        "account": {"report_issue": None, "awaiting_decision": [], "approved_unopened": []},
        "peers": {"issues": [], "suggestions": []},
        "not_collected": [],
    }
    _, out = sh(["git", "-C", str(core), "tag", "--list", "v*", "--sort=-v:refname"])
    tags = out.split()
    issues: list = []
    own: list | None = None
    me, open_prs, changelog = "", [], ""
    if core_repo:
        try:
            issues = _json(
                sh,
                [
                    "gh",
                    "issue",
                    "list",
                    "-R",
                    core_repo,
                    "--label",
                    report.LABEL,
                    "--state",
                    "open",
                    "--json",
                    "number,url,author,body,comments",
                    "-L",
                    "50",
                ],
                [],
            )
        except Exception as exc:
            data["not_collected"].append(f"peers: {exc}")
        try:
            me = str(
                _json(sh, ["gh", "api", "user", "--jq", "{login: .login}"], {}).get("login", "")
            )
        except Exception as exc:
            data["not_collected"].append(f"account login: {exc}")
        try:
            # Approved items stay owed after their issue closes, so the account's own reports are read
            # open or closed, most recent first (#117 G-037).
            own = _json(
                sh,
                [
                    "gh",
                    "issue",
                    "list",
                    "-R",
                    core_repo,
                    "--label",
                    report.LABEL,
                    "--author",
                    "@me",
                    "--state",
                    "all",
                    "--json",
                    "number,url,author,body,comments,state",
                    "-L",
                    "20",
                ],
                [],
            )
        except Exception as exc:
            data["not_collected"].append(f"account report issues: {exc}")
        try:
            open_prs = _json(
                sh,
                [
                    "gh",
                    "pr",
                    "list",
                    "-R",
                    core_repo,
                    "--state",
                    "open",
                    "--json",
                    "number,title,body,url",
                    "-L",
                    "100",
                ],
                [],
            )
        except Exception as exc:
            data["not_collected"].append(f"core pull requests: {exc}")
    else:
        data["not_collected"].append("peers and account: core repo unknown (CORE_REPO)")
    try:
        changelog = (core / "CHANGELOG.md").read_text(encoding="utf8")
    except OSError:
        data["not_collected"].append("shipped items: no CHANGELOG.md in the core clone")
    owner = core_repo.split("/", 1)[0] if core_repo else ""
    mine = next(
        (
            i
            for i in issues
            if me and (i.get("author") or {}).get("login", "").lower() == me.lower()
        ),
        None,
    )
    risks = risk_levels(mine.get("body", "")) if mine else {}
    for c in cfg.get("ui_consumers", []):
        try:
            data["consumers"].append(consumer_row(c, latest, tags, core, sh, risks, pinned_remote))
        except Exception as exc:  # one broken consumer must not hide the others
            data["not_collected"].append(f"consumer {report.repo_label(c.get('repo', '?'))}: {exc}")
    data["peers"] = peers_block(issues, me, owner, changelog, previous)
    data["account"] = account_block(data["peers"], open_prs, own_items(own, owner, changelog))
    return data


def update(
    cfg: dict,
    core: Path,
    core_repo: str,
    latest: str,
    sh: Sh,
    state_dir: Path,
    check: bool,
    pinned_remote: Callable[[dict], str],
) -> tuple[list[str], list[str]]:
    """Build the feed and write it atomically. Returns (info lines, problem lines)."""
    path = state_dir / FILE
    try:
        previous = json.loads(path.read_text(encoding="utf8"))
    except (OSError, ValueError):
        previous = {}
    data = build(cfg, core, core_repo, latest, sh, previous, pinned_remote)
    if check:
        return [f"consumption: would write {path}"], []
    write_atomic(path, data)
    info = []
    new = [s for s in data["peers"]["suggestions"] if s["new"]]
    if new:
        info.append(
            f"consumption: {len(new)} new kit suggestion(s) from other accounts: "
            + ", ".join(f"#{s['issue']} {s['id']}" for s in new)
        )
    return info, []


if __name__ == "__main__":
    raise SystemExit("hermes/consumption.py is called by hermes/nightly.py")
