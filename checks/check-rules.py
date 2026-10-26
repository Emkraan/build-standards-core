#!/usr/bin/env python3
"""Validate standards/rules.json, the registry of enforceable rules.

Checks: the format and fields of every rule, unique ids, id and ref agree, the doc exists and the
section exists in it (a "## N." heading, or numbered item K under "## N." for an "N.K" ref), every
lint rule names a real ui_lint or script_lint rule with the same ref, every ui_lint rule is
registered exactly once, and every script_lint rule is registered at most once and names a rule in
the registry (a script_lint rule that only covers part of a rule's acceptance supports that rule
without making it a lint rule). Prints the rule count per doc so docs with no registered rules stay
visible.

Every repo-check rule names a check in templates/overlay/scripts/repo_checks.py with the same ref, and every
repo check is registered exactly once.

Usage: python3 checks/check-rules.py        Exit codes: 0 valid, 1 problems.
"""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REG = ROOT / "standards" / "rules.json"
FORMAT = "build-standards-rules/1"
LEVELS = {"must", "should"}
KINDS = {"lint", "core-ci", "overlay-ci", "repo-check", "test", "review"}
# Scopes a rule applies to. A consumer declares the stacks it has (standards-local/parameters.md) and
# core-status reports only the rules whose scopes it has, plus every 'all' rule.
APPLIES = {"web", "wpf", "local-ops", "powershell", "python", "iac", "all"}
ID_RE = re.compile(r"^([a-z0-9-]+)\.(\d+(?:\.\d+)?)$")
REQUIRED = ("id", "ref", "title", "statement", "level", "applies_to", "check", "acceptance")

sys.path.insert(0, str(ROOT / "lint"))
import script_lint  # noqa: E402  # pyright: ignore[reportMissingImports]
import ui_lint  # noqa: E402  # pyright: ignore[reportMissingImports]

LINT_RULES = {**ui_lint.RULES, **script_lint.RULES}

sys.path.insert(0, str(ROOT / "templates" / "overlay" / "scripts"))
import repo_checks  # noqa: E402  # pyright: ignore[reportMissingImports]

TEMPLATES = ROOT / "templates" / "overlay" / ".github" / "workflows"


def template_jobs(name):
    """Check names a rule may bind to in a template workflow: job ids and core- step names. None when
    the file does not exist."""
    f = TEMPLATES / name
    if not f.is_file():
        return None
    jobs, inside = set(), False
    for line in f.read_text(encoding="utf8").splitlines():
        if re.match(r"^jobs:\s*$", line):
            inside = True
            continue
        if inside and re.match(r"^\S", line):
            inside = False
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line) if inside else None
        if m:
            jobs.add(m.group(1))
        m = re.match(r"^\s+-\s+name:\s*(core-[A-Za-z0-9_-]+)\s*$", line) if inside else None
        if m:
            jobs.add(m.group(1))
    return jobs


def job_name_problems(name="core-ci.yml"):
    """Every job of the core-ci template has an id starting core- and a name: equal to it, so its check
    name can never be the same as a job of a consumer's own workflows (a merge gate keyed on check names
    read two jobs called python as one)."""
    f = TEMPLATES / name
    if not f.is_file():
        return [f"{name}: the template workflow is missing"]
    bad, inside, job, named = [], False, None, {}
    for line in f.read_text(encoding="utf8").splitlines():
        if re.match(r"^jobs:\s*$", line):
            inside = True
            continue
        if inside and re.match(r"^\S", line):
            inside = False
        if not inside:
            continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            job = m.group(1)
            named[job] = None
            continue
        m = re.match(r"^    name:\s*(.+?)\s*$", line)
        if m and job:
            named[job] = m.group(1).strip("'\"")
    for job, display in named.items():
        if not job.startswith("core-"):
            bad.append(
                f"{name}: job {job} must start with core- so its check name cannot clash with a repo job"
            )
        if display != job:
            bad.append(
                f"{name}: job {job} needs name: {job} (the check name a merge gate requires)"
            )
    return bad


def core_ci_test_missing(command, root):
    """True when a core-ci command that runs one test file ("npm --prefix kit test -- tests/x.test.tsx")
    names a file that is not there: the proof would run nothing."""
    m = re.search(r"--prefix\s+(\S+)\s+test\s+--\s+(\S+)", command)
    return bool(m) and not (pathlib.Path(root) / m.group(1) / m.group(2)).is_file()


def section_exists(text, sec):
    major, _, minor = sec.partition(".")
    lines = text.splitlines()
    head = re.compile(rf"^##\s+{re.escape(major)}\.\s")
    starts = [i for i, ln in enumerate(lines) if head.match(ln)]
    if not starts:
        return False
    if not minor:
        return True
    body = []
    for ln in lines[starts[0] + 1 :]:
        if ln.startswith("## "):
            break
        body.append(ln)
    return any(re.match(rf"^(###\s+{re.escape(sec)}\b|{re.escape(minor)}\.\s)", ln) for ln in body)


def main():
    bad = []
    try:
        reg = json.loads(REG.read_text(encoding="utf8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"::error::check-rules: cannot read {REG}: {e}")
        return 1
    if reg.get("format") != FORMAT:
        bad.append(f"format is {reg.get('format')!r}, expected {FORMAT!r}")
    seen, per_doc, lint_ids, repo_ids = set(), {}, {}, {}
    docs = {}
    for i, r in enumerate(reg.get("rules", [])):
        where = f"rule {i} ({r.get('id', '?')})"
        missing = [k for k in REQUIRED if not r.get(k)]
        if missing:
            bad.append(f"{where}: missing {', '.join(missing)}")
            continue
        m = ID_RE.match(r["id"])
        if not m:
            bad.append(f'{where}: id is not "<doc>.<section>[.<rule>]"')
            continue
        doc, sec = m.groups()
        if r["id"] in seen:
            bad.append(f"{where}: duplicate id")
        seen.add(r["id"])
        if r["ref"] != f"{doc}.md {sec}":
            bad.append(
                f'{where}: ref {r["ref"]!r} does not match the id (expected "{doc}.md {sec}")'
            )
        path = ROOT / "standards" / f"{doc}.md"
        if not path.is_file():
            bad.append(f"{where}: standards/{doc}.md does not exist")
        else:
            docs.setdefault(doc, path.read_text(encoding="utf8"))
            if not section_exists(docs[doc], sec):
                bad.append(f"{where}: section {sec} is not in standards/{doc}.md")
        per_doc[doc] = per_doc.get(doc, 0) + 1
        if r["level"] not in LEVELS:
            bad.append(f"{where}: level must be one of {sorted(LEVELS)}")
        if not isinstance(r["applies_to"], list) or not set(r["applies_to"]) <= APPLIES:
            bad.append(f"{where}: applies_to must be a list within {sorted(APPLIES)}")
        elif "all" in r["applies_to"] and len(r["applies_to"]) > 1:
            bad.append(f'{where}: applies_to "all" stands alone')
        kind = r["check"].get("kind")
        if kind not in KINDS:
            bad.append(f"{where}: check.kind must be one of {sorted(KINDS)}")
        if kind == "lint":
            lid = r["check"].get("id")
            if lid not in LINT_RULES:
                bad.append(f"{where}: check.id {lid!r} is not a ui_lint or script_lint rule")
            else:
                if LINT_RULES[lid][1] != r["ref"]:
                    bad.append(
                        f"{where}: lint {lid} points at {LINT_RULES[lid][1]!r}, the registry says {r['ref']!r}"
                    )
                lint_ids[lid] = lint_ids.get(lid, 0) + 1
        if kind == "overlay-ci":
            wf, jobs = r["check"].get("workflow"), r["check"].get("jobs")
            have = template_jobs(wf) if wf else None
            if have is None:
                bad.append(
                    f"{where}: an overlay-ci check needs workflow, a file in {TEMPLATES.relative_to(ROOT)}"
                )
            elif not isinstance(jobs, list) or not jobs or any(j not in have for j in jobs):
                bad.append(
                    f"{where}: check.jobs must list jobs or core- steps of {wf} (it has {', '.join(sorted(have))})"
                )
            elif wf not in r["acceptance"] or not all(j in r["acceptance"] for j in jobs):
                bad.append(f"{where}: the acceptance line must name {wf} and each job")
        if kind == "core-ci" and not r["check"].get("command"):
            bad.append(f"{where}: a core-ci check needs the command core CI runs")
        if kind == "core-ci" and core_ci_test_missing(r["check"].get("command", ""), ROOT):
            bad.append(f"{where}: the test file the command runs does not exist")
        if kind == "repo-check":
            cid = r["check"].get("id")
            if cid not in repo_checks.CHECKS:
                bad.append(f"{where}: check.id {cid!r} is not a repo_checks check")
            else:
                if repo_checks.CHECKS[cid][1] != r["ref"]:
                    bad.append(
                        f"{where}: repo check {cid} points at {repo_checks.CHECKS[cid][1]!r}, the registry says {r['ref']!r}"
                    )
                repo_ids[cid] = repo_ids.get(cid, 0) + 1
                if cid not in r["acceptance"]:
                    bad.append(f"{where}: the acceptance line must name {cid}")
        for k in ("title", "statement", "acceptance"):
            if not r[k].isascii():
                bad.append(f"{where}: {k} is not ASCII")
        if len(r["statement"]) > 400:
            bad.append(f"{where}: statement over 400 characters; link the doc instead")
    for lid in ui_lint.RULES:
        if lint_ids.get(lid, 0) != 1:
            bad.append(f"ui_lint {lid} is registered {lint_ids.get(lid, 0)} times, expected once")
    for cid in repo_checks.CHECKS:
        if repo_ids.get(cid, 0) != 1:
            bad.append(
                f"repo check {cid} is registered {repo_ids.get(cid, 0)} times, expected once"
            )
    refs = {r.get("ref") for r in reg.get("rules", [])}
    for lid, (_, ref, _) in script_lint.RULES.items():
        if lint_ids.get(lid, 0) > 1:
            bad.append(
                f"script_lint {lid} is registered {lint_ids[lid]} times, expected at most once"
            )
        if ref not in refs:
            bad.append(f"script_lint {lid} names {ref!r}, which is not a registered rule")
    bad += job_name_problems()
    for b in bad:
        print(f"::error::check-rules: {b}")
    all_docs = sorted(p.stem for p in (ROOT / "standards").glob("*.md"))
    cover = ", ".join(f"{d} {per_doc.get(d, 0)}" for d in all_docs)
    print(f"check-rules: {len(seen)} rule(s), {len(bad)} problem(s). Per doc: {cover}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
