#!/usr/bin/env python3
"""
Purpose: Generate and validate CHANGELOG.md entries for a repository where every pull request carries one entry, so downstream
         consumers (agents that pull standards and designs from main) can stay in lockstep by reading the changelog instead of
         diffing the tree. The entry format is `## [#N] YYYY-MM-DD - Title`, a `Downstream:` line (none, review or adopt), an
         `Areas:` line and one `### <Area>` section per area; history is append only.
Usage:
  changelog.py check --pr N [--base SHA | --staged]
      Validate the whole changelog and the entry for PR N against the files the change touches.
  changelog.py new --pr N --title TITLE [--base SHA | --staged] [--summary TEXT]
      Insert a generated entry for PR N at the top of the changelog.
  changelog.py areas [--base SHA | --staged]
      Print the areas the change touches, one per line.
Exit codes: 0 ok, 1 validation failure, 2 usage or git error.
Config: CHANGELOG_TOOL_CONFIG, a JSON file, every key optional:
  areas            the allowed area names (default standards, skills, design, platform, security, config)
  area_rules       [[regex, area], ...] first match wins; a path no rule matches is "platform"
  consumer_areas   areas whose change is visible downstream: touching one forbids `Downstream: none` (default standards, skills, design)
  sync_overlay, sync_paths, sync_workflows   a change that only touches synced copies under sync_overlay (and the listed workflow
                   files) needs no entry (default none)
  skills_prefix    the folder whose children are skills, each with a SKILL.md (default skills/)
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

CHANGELOG = "CHANGELOG.md"
MARKER = "<!-- changelog:entries -->"
HEADING_RE = re.compile(r"^## \[(#\d+|baseline)\] (\d{4}-\d{2}-\d{2}) - (\S.*)$")
DOWNSTREAM = ("none", "review", "adopt")


def _config():
    f = os.environ.get("CHANGELOG_TOOL_CONFIG")
    d = {}
    if f:
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            d = {}
    return d if isinstance(d, dict) else {}


_C = _config()
AREAS = tuple(
    _C.get("areas") or ("standards", "skills", "design", "platform", "security", "config")
)
CONSUMER_AREAS = set(_C.get("consumer_areas") or ("standards", "skills", "design"))
# First match wins. Order matters (specific before general).
AREA_RULES = [
    (re.compile(p), a)
    for p, a in _C.get("area_rules", [])
    if isinstance(_C.get("area_rules"), list)
]
IGNORED = {CHANGELOG}
SYNC_OVERLAY = str(_C.get("sync_overlay") or "")
SYNC_PATHS = tuple(_C.get("sync_paths") or ())
SYNC_WORKFLOWS = tuple(_C.get("sync_workflows") or ())
SKILLS_PREFIX = str(_C.get("skills_prefix") or "skills/")


def is_overlay_sync(paths):
    """True when every changed path is a synced core copy: under the app folder, or a core template workflow.

    A change made only of template workflows is not a sync, so a hand edit to them still needs an entry."""
    paths = [p for p in paths if p]
    if not SYNC_OVERLAY:
        return False
    overlay = [
        p
        for p in paths
        if p.startswith(SYNC_OVERLAY) and p[len(SYNC_OVERLAY) :].startswith(SYNC_PATHS)
    ]
    return bool(overlay) and all(p in overlay or p in SYNC_WORKFLOWS for p in paths)


def git(*args):
    try:
        return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError as exc:
        sys.exit(f"git {' '.join(args)} failed: {exc.stderr.strip()}")


def area_of(path):
    for pattern, area in AREA_RULES:
        if pattern.search(path):
            return area
    return "platform"


def diff_args(opts):
    return ["--cached", "HEAD"] if opts.staged else [f"{opts.base}...HEAD"]


def changed_files(opts):
    """Return [(status, path)] for the change, excluding the changelog itself."""
    out = git("diff", "--name-status", "--no-renames", *diff_args(opts))
    rows = []
    for line in out.splitlines():
        status, _, path = line.partition("\t")
        if path and path not in IGNORED:
            rows.append((status[0], path))
    return rows


def old_text(opts, path):
    ref = "HEAD" if opts.staged else opts.base
    try:
        return subprocess.run(
            ["git", "show", f"{ref}:{path}"], check=True, capture_output=True, text=True
        ).stdout
    except subprocess.CalledProcessError:
        return None


def new_text(opts, path):
    if opts.staged:
        try:
            return subprocess.run(
                ["git", "show", f":{path}"], check=True, capture_output=True, text=True
            ).stdout
        except subprocess.CalledProcessError:
            return None
    p = Path(path)
    return p.read_text(encoding="utf-8") if p.exists() else None


# ---------- parsing ----------


def parse(text):
    """Split the changelog into (preamble, [entry dict]). Entry text keeps its own heading."""
    if MARKER not in text:
        return text, None
    preamble, _, body = text.partition(MARKER)
    entries, current = [], None
    for line in body.splitlines(keepends=True):
        m = HEADING_RE.match(line.rstrip("\n"))
        if line.startswith("## "):
            current = {"heading": line.rstrip("\n"), "match": m, "lines": [line]}
            entries.append(current)
        elif current is not None:
            current["lines"].append(line)
    for e in entries:
        e["text"] = "".join(e["lines"])
        e["fields"] = dict(re.findall(r"^(Downstream|Areas): *(.+?) *$", e["text"], re.M))
        e["sections"] = {s.strip().lower() for s in re.findall(r"^### (.+)$", e["text"], re.M)}
    return preamble, entries


def validate_entry(e):
    errs = []
    m = e["match"]
    if not m:
        return [f"bad heading (want '## [#N] YYYY-other-resource - Title'): {e['heading']}"]
    try:
        datetime.date.fromisoformat(m.group(2))
    except ValueError:
        errs.append(f"{e['heading']}: invalid date")
    ds = e["fields"].get("Downstream")
    if ds not in DOWNSTREAM:
        errs.append(f"{m.group(1)}: 'Downstream:' must be one of {', '.join(DOWNSTREAM)}")
    areas = [a.strip() for a in e["fields"].get("Areas", "").split(",") if a.strip()]
    if not areas:
        errs.append(f"{m.group(1)}: missing 'Areas:' line")
    for a in areas:
        if a not in AREAS:
            errs.append(f"{m.group(1)}: unknown area '{a}' (allowed: {', '.join(AREAS)})")
        elif a not in e["sections"]:
            errs.append(f"{m.group(1)}: area '{a}' declared but no '### {a.title()}' section")
    if ds in ("review", "adopt") and "downstream actions" not in e["sections"]:
        errs.append(
            f"{m.group(1)}: Downstream is '{ds}' but there is no '### Downstream actions' section"
        )
    if ds == "none" and CONSUMER_AREAS & set(areas):
        errs.append(
            f"{m.group(1)}: touches {sorted(CONSUMER_AREAS & set(areas))} so Downstream cannot be 'none'"
        )
    e["areas"] = set(areas)
    return errs


def cmd_check(opts):
    errs = []
    names = {p for _, p in changed_files(opts)}
    touched = git("diff", "--name-only", *diff_args(opts)).split()
    if CHANGELOG not in touched and is_overlay_sync(touched):
        print(f"ok: overlay-only core sync ({len(touched)} file(s)), no entry needed")
        return 0
    if CHANGELOG not in touched:
        print(
            f"FAIL: this change does not update {CHANGELOG}. Every PR needs an entry (see CONTRIBUTING.md)."
        )
        return 1
    text = new_text(opts, CHANGELOG) or ""
    _, entries = parse(text)
    if entries is None:
        print(f"FAIL: {CHANGELOG} is missing the '{MARKER}' marker line.")
        return 1
    # Order is merge order (newest merged first), not PR number order: a PR opened earlier can
    # merge later, so only uniqueness is enforced here.
    seen = set()
    for e in entries:
        errs += validate_entry(e)
        if not e["match"]:
            continue
        ident = e["match"].group(1)
        if ident in seen:
            errs.append(f"duplicate entry {ident}")
        seen.add(ident)
    if not entries or not entries[0]["match"] or entries[0]["match"].group(1) != f"#{opts.pr}":
        errs.append(f"the first entry under the marker must be '## [#{opts.pr}] ...' for this PR")
    else:
        top = entries[0]
        missing = {area_of(p) for p in names} - top["areas"]
        if missing:
            errs.append(
                f"#{opts.pr}: change touches areas not declared in 'Areas:': {', '.join(sorted(missing))}"
            )
    # History is append-only: every entry that exists on the base must be byte-identical now.
    base = old_text(opts, CHANGELOG)
    if base:
        _, base_entries = parse(base)
        now = {e["heading"]: e["text"].rstrip() for e in entries}
        for be in base_entries or []:
            if now.get(be["heading"]) != be["text"].rstrip():
                errs.append(
                    f"existing entry changed or removed: {be['heading']} (history is append-only)"
                )
    if errs:
        print("FAIL: changelog check")
        for err in errs:
            print(f"  - {err}")
        return 1
    print(f"OK: {CHANGELOG} entry #{opts.pr} valid; {len(entries)} entries checked")
    return 0


# ---------- generation ----------


def skill_root(path):
    """<skills prefix>/<...>/<skill>/... -> the directory holding SKILL.md (current or base tree)."""
    parts = path.split("/")
    for i in range(len(parts) - 1, SKILLS_PREFIX.count("/"), -1):
        cand = "/".join(parts[:i])
        if Path(cand, "SKILL.md").exists() or path == f"{cand}/SKILL.md":
            return cand
    return "/".join(parts[: SKILLS_PREFIX.count("/") + 1])


def frontmatter_description(text):
    m = re.search(r"^description:\s*(.*)$", text or "", re.M)
    if not m:
        return ""
    val = m.group(1).strip().strip("\"'")
    if val in ("|", ">", ">-", "|-", ""):
        after = text[m.end() :].splitlines()
        val = " ".join(line.strip() for line in after[:3] if line.startswith("  "))
    return val[:160]


def touched_sections(opts, path):
    """Markdown headings whose body changed, using the new-file line numbers of each hunk."""
    diff = git("diff", "-U0", *diff_args(opts), "--", path)
    text = new_text(opts, path) or ""
    lines = text.splitlines()
    heads, current = [], ""
    for line in lines:
        if re.match(r"^#{1,4} ", line):
            current = line.lstrip("#").strip()
        heads.append(current or "(top of file)")
    found = []
    for start, count in re.findall(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", diff, re.M):
        start, count = int(start), int(count or 1)
        for ln in range(max(start, 1), max(start, 1) + max(count, 1)):
            if ln <= len(heads) and heads[ln - 1] not in found:
                found.append(heads[ln - 1])
    return found[:8]


def token_changes(opts, path):
    diff = git("diff", "-U0", *diff_args(opts), "--", path)
    plus = set(re.findall(r"^\+\s*(--[a-z0-9-]+):", diff, re.M))
    minus = set(re.findall(r"^-\s*(--[a-z0-9-]+):", diff, re.M))
    return sorted(plus - minus), sorted(plus & minus), sorted(minus - plus)


def numstat(opts):
    out = git("diff", "--numstat", "--no-renames", *diff_args(opts))
    stats = {}
    for line in out.splitlines():
        a, d, p = line.split("\t")
        stats[p] = (a, d)
    return stats


def cmd_new(opts):
    rows = changed_files(opts)
    if not rows:
        print("no changes; nothing to record")
        return 0
    stats = numstat(opts)
    by_area = defaultdict(list)
    for status, path in rows:
        by_area[area_of(path)].append((status, path))
    verb = {"A": "added", "M": "changed", "D": "removed"}
    out = []

    if "standards" in by_area:
        sec = ["### Standards"]
        for status, path in by_area["standards"]:
            line = f"- `{path}` {verb.get(status, 'changed')}"
            if status == "M" and path.endswith(".md"):
                heads = touched_sections(opts, path)
                if heads:
                    line += "; sections touched: " + "; ".join(heads)
            sec.append(line)
        out.append(sec)

    if "skills" in by_area:
        skills = defaultdict(list)
        for status, path in by_area["skills"]:
            skills[skill_root(path)].append((status, path))
        sec = ["### Skills"]
        for root in sorted(skills):
            files = skills[root]
            name = root.removeprefix(SKILLS_PREFIX)
            md = f"{root}/SKILL.md"
            md_status = next((s for s, p in files if p == md), None)
            if md_status == "A":
                sec.append(f"- Added `{name}`: {frontmatter_description(new_text(opts, md))}")
            elif md_status == "D":
                sec.append(f"- Removed `{name}`")
            else:
                parts = []
                if md_status == "M":
                    heads = touched_sections(opts, md)
                    parts.append("SKILL.md sections: " + "; ".join(heads) if heads else "SKILL.md")
                others = []
                for s, p in files:
                    if p == md:
                        continue
                    label = p.removeprefix(root + "/")
                    heads = touched_sections(opts, p) if s == "M" and p.endswith(".md") else []
                    others.append(f"{label} (sections: {'; '.join(heads[:4])})" if heads else label)
                if others:
                    shown = ", ".join(others[:6]) + (
                        f" (+{len(others) - 6} more)" if len(others) > 6 else ""
                    )
                    parts.append(f"supporting files: {shown}")
                sec.append(f"- Changed `{name}`: " + "; ".join(parts))
        out.append(sec)

    if "design" in by_area:
        sec = ["### Design"]
        for status, path in by_area["design"]:
            a, d = stats.get(path, ("?", "?"))
            line = f"- `{path}` {verb.get(status, 'changed')} (+{a}/-{d})"
            if path.endswith(".css"):
                add, chg, rem = token_changes(opts, path)
                bits = [
                    f"{k}: {', '.join(v)}"
                    for k, v in (
                        ("new tokens", add),
                        ("changed tokens", chg),
                        ("removed tokens", rem),
                    )
                    if v
                ]
                if bits:
                    line += "; " + "; ".join(bits)
            sec.append(line)
        out.append(sec)

    for area in ("platform", "security"):
        if area in by_area:
            sec = [f"### {area.title()}"]
            for status, path in by_area[area]:
                a, d = stats.get(path, ("?", "?"))
                sec.append(f"- `{path}` {verb.get(status, 'changed')} (+{a}/-{d})")
            out.append(sec)

    if "config" in by_area:
        files = ", ".join(f"`{p}`" for _, p in by_area["config"])
        out.append(
            ["### Config", f"- Encrypted config re-encrypted: {files}. Not readable downstream."]
        )

    consumer = CONSUMER_AREAS & set(by_area)
    downstream = "review" if consumer else "none"
    if consumer:
        out.append(
            [
                "### Downstream actions",
                "- Re-read the files and sections listed under "
                + ", ".join(a.title() for a in AREAS if a in consumer)
                + " from main at this merge and reconcile any local copies.",
            ]
        )

    areas = [a for a in AREAS if a in by_area]
    head = [
        f"## [#{opts.pr}] {datetime.date.today().isoformat()} - {opts.title}",
        f"Downstream: {downstream}",
        f"Areas: {', '.join(areas)}",
        "",
    ]
    if opts.summary:
        head += [opts.summary, ""]
    entry = "\n".join(head + ["\n".join(sec) + "\n" for sec in out]).rstrip() + "\n\n"

    path = Path(CHANGELOG)
    text = path.read_text(encoding="utf-8")
    if MARKER not in text:
        sys.exit(f"{CHANGELOG} is missing the '{MARKER}' marker line")
    pre, _, post = text.partition(MARKER)
    path.write_text(f"{pre}{MARKER}\n\n{entry}{post.lstrip(chr(10))}", encoding="utf-8")
    sys.stdout.write(entry)
    return 0


def cmd_areas(opts):
    for area in sorted({area_of(p) for _, p in changed_files(opts)}):
        print(area)
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "new", "areas"):
        p = sub.add_parser(name)
        g = p.add_mutually_exclusive_group(required=True)
        g.add_argument("--base", help="base commit; the change is BASE...HEAD")
        g.add_argument("--staged", action="store_true", help="the change is the git index vs HEAD")
        if name != "areas":
            p.add_argument("--pr", type=int, required=True)
        if name == "new":
            p.add_argument("--title", required=True)
            p.add_argument("--summary", default="")
    opts = ap.parse_args()
    return {"check": cmd_check, "new": cmd_new, "areas": cmd_areas}[opts.cmd](opts)


if __name__ == "__main__":
    sys.exit(main())
