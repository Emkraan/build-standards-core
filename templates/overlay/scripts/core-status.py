#!/usr/bin/env python3
"""One status report for an overlay: where the pin stands, which rules pass, and what needs a person.

Usage:
  python3 scripts/core-status.py            human summary
  python3 scripts/core-status.py --json     machine-readable report for nightly tooling
  python3 scripts/core-status.py --latest   also compare against the newest core release (needs gh)
  python3 scripts/core-status.py --require-ui-adopted   exit 1 when a UI consumer is only partial
  python3 scripts/core-status.py --require-lint-config  exit 1 when a declared stack has no lint config,
                    or when parameters.md has no Stacks row
  python3 scripts/core-status.py --ci       read overlay-ci rule results from the latest default-branch
                    run of core-ci.yml, and of lint-sweep.yml when installed (needs gh); with no run
                    on the default branch, from the run on the head of the most recently merged pull
                    request whose tree equals the default branch's tree
  python3 scripts/core-status.py --ci-results FILE   read them from a JSON file instead
  python3 scripts/core-status.py --required-json FILE  read the merge gate's required checks from a
                    JSON file (the core-ci.py required-checks --api-json shape) instead of gh
  python3 scripts/core-status.py --vendored OWNER/REPO   a vendored repo carries no record of the core;
                    print the record the nightly keeps on this machine: the release the copy carries,
                    how it was found, and behind (exit 3) when the newest release is newer; with
                    --latest the newest release is read through gh instead of from the record

A UI consumer also gets a ui_adoption verdict (web-ui.md 0.11): adopted when the kit is imported from
kit-core, no local stylesheet redefines a token (UI007, UI008, UI010), the lint has zero findings and
ui-lint.json sets no baseline. Otherwise partial, or excepted while an active exception names web-ui.md 0.11. An overlay with no UI lint config and no kit-core is
not_applicable. --require-ui-adopted exits 1 on partial, for the drift workflow.

A stack declared in the Stacks row needs its lint config: web needs standards-local/ui-lint.json,
powershell, python and iac need standards-local/script-lint.json. A declared stack with no config is
a failure (reported under problems, and its lint rules are fail, not unverified): a lint that was
never set up proves nothing, and a silent skip let a consumer believe a rule held.
--require-lint-config exits 1 on it, for the drift workflow.

A local component that takes the name of a kit export in a file that never imports the kit is a
stand-in for a kit part (web-ui.md 0.11, "No local copy of a kit part"), so the UI stays partial
until it is replaced or turned into an adapter over the kit part. An adapter of the same name that
imports the kit is allowed: it is the baseline-first step.

Each registered rule gets a status:
  pass        no finding (lint rules), or proved in the core before release (core-ci rules)
  excepted    findings exist but sit inside a ratchet baseline or an active exception
  fail        findings above the baseline
  pass (repo-check)  a rule whose check is a scripts/repo_checks.py check (RC0nn) is run here against the repo's
              tracked files: no finding is pass, a finding is fail, an active exception makes it excepted
  proved      a test or review rule (or an overlay-ci rule with no result read) that a valid entry in
              standards-local/proofs.json proves; counted apart from pass
  not_applicable  a core-ci rule that needs the kit (check.requires ui-adoption) in an app whose UI is not adopted
  unverified  a test or review rule with no proof record, an overlay-ci rule whose workflow is installed
              but whose result was not read, or a script lint rule while the overlay has no
              standards-local/script-lint.json; prove it in the app

overlay-ci rules name a job of the template workflow (check.workflow, check.jobs). The rule fails when
that workflow or job is not installed in the repo's .github/workflows. With --ci the script reads the
latest default-branch run of the workflow through gh (a merge gate that merges with the workflow
token never starts a push run, so with none there the run on the head of the most recently merged
pull request whose tree equals the default branch's tree stands in); with --ci-results FILE it reads
{"core-ci.yml": {"<job>": "success|failure|skipped"}}. A successful job passes the rule, a failed one
fails it, a skipped one leaves it unverified.

Required checks: when core-ci.yml is installed, --ci (or --required-json FILE) also reads the merge
gate's required checks (branch protection, active rulesets, and a REQUIRED_CHECKS list in any
workflow) and lists every core-ci job nothing requires as a problem: a job that is not required does
not gate the merge, so its rule holds only by luck. `scripts/core-ci.py required-checks --fix` prints
the command that adds them.

standards-local/proofs.json (consumer-owned, optional) records how the app proves a rule the script
cannot see: {"<rule id>": {"kind": "ci|test|review", "ref": "...", "date": "YYYY-MM-DD",
"reviewed_by": "..."}}. ref is "<workflow file>#<job>" for ci, a test file path for test, and the
review record's path for review (relative to the repo root). A proof's kind must be the rule's check
kind or stronger (ci > test > review); a review needs a date within "$max_review_age_days" (default
180). A broken or stale entry is listed under problems and proves nothing.

A missing Stacks row in standards-local/parameters.md is a problem, and --require-lint-config fails on
it: without the row no stack is declared, so the lint config gate would check nothing.

Lint rules come from lint-core/ui_lint.py and lint-core/script_lint.py. A script lint check that
covers only part of a rule (for example the ASCII half of an overlay-ci rule) can fail that rule
with its findings, but never passes it: with no finding the rule stays unverified.

Scope: a rule applies to the stacks in its applies_to (web, wpf, local-ops, powershell, python, iac)
or to all. When standards-local/parameters.md declares the overlay's stacks (the "Stacks" row), rules
for other stacks are left out of the report and listed under out_of_scope. With no declaration every
rule is reported, as before.

With --latest the report adds the rules that are new, changed or removed in the newest release, so
tooling can raise them before the pin moves. The report never changes files. Exit 0 unless the
overlay itself is unreadable (2).
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import corehash as ch  # noqa: E402

try:
    import repo_checks  # noqa: E402
except ImportError:  # an overlay that predates repo_checks.py
    repo_checks = None

REGISTRY = ch.ROOT / "standards-core" / "rules.json"
LINT = ch.ROOT / "lint-core" / "ui_lint.py"
SCRIPT_LINT = ch.ROOT / "lint-core" / "script_lint.py"
EXCEPTIONS = ch.ROOT / "scripts" / "check-exceptions.py"
PARAMETERS = ch.ROOT / "standards-local" / "parameters.md"
SCOPES = ("web", "wpf", "local-ops", "powershell", "python", "iac")
EXPIRING_DAYS = 30
COMPARED = ("title", "statement", "level", "applies_to", "check", "acceptance")


STACK_CONFIG = {
    "web": "ui-lint.json",
    "powershell": "script-lint.json",
    "python": "script-lint.json",
    "iac": "script-lint.json",
}


def vendored_record(repo: str) -> dict | None:
    """The {release, source_hash} the nightly keeps on this machine for a vendored repo."""
    root = pathlib.Path(
        os.environ.get("CORE_VENDORED_DIR") or "~/.config/build-standards-core/vendored"
    ).expanduser()
    f = root / (repo.replace("/", "__") + ".json")
    try:
        rec = json.loads(f.read_text(encoding="utf8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) and rec.get("release") else None


def missing_lint_config(scopes) -> list[str]:
    """Declared stacks whose lint has no config file: (stack, file) as readable messages."""
    out = []
    for stack in sorted(scopes or ()):
        name = STACK_CONFIG.get(stack)
        if name and not (ch.ROOT / "standards-local" / name).is_file():
            out.append(
                f"stack {stack} is declared but standards-local/{name} is missing, so its lint never ran"
            )
    return out


def run_json(args) -> dict:
    r = subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=ch.ROOT)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": (r.stderr or r.stdout).strip()[-400:] or f"exit {r.returncode}"}


def registry_at(repo, tag) -> dict | None:
    r = subprocess.run(
        ["gh", "api", f"repos/{repo}/contents/standards/rules.json?ref={tag}", "--jq", ".content"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    try:
        return json.loads(base64.b64decode(r.stdout))
    except (ValueError, json.JSONDecodeError):
        return None


STACKS_MISSING = (
    "standards-local/parameters.md has no Stacks row, so no stack is declared and "
    "--require-lint-config checks nothing; add the row (empty reports every rule)"
)


def declared_scopes() -> tuple[set[str] | None, list[str]]:
    """The stacks named in the parameters sheet's Stacks row, or None when the row is absent or empty.
    A missing row (or a missing sheet) is a problem: it silently turns the lint config gate off."""
    if not PARAMETERS.is_file():
        return None, [STACKS_MISSING]
    for line in PARAMETERS.read_text(encoding="utf8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0].lower().startswith("stacks"):
            names = {
                n.strip().strip("`").lower()
                for n in cells[1].replace(";", ",").split(",")
                if n.strip()
            }
            if not names:
                return None, []
            unknown = sorted(names - set(SCOPES))
            problems = (
                [
                    f"parameters.md Stacks names unknown stack(s): {', '.join(unknown)} (known: {', '.join(SCOPES)})"
                ]
                if unknown
                else []
            )
            return names & set(SCOPES), problems
    return None, [STACKS_MISSING]


# ---------------------------------------------------------------- overlay-ci results


def repo_root() -> pathlib.Path:
    r = subprocess.run(
        ["git", "-C", str(ch.ROOT), "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    return pathlib.Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else ch.ROOT


# The named steps of core-checks in the core's core-ci workflow (the template and the reusable one run the
# same); a test keeps this list equal to both files.
CORE_CI_STEPS = (
    "core-setup",
    "core-secret-scan",
    "core-workflow-lint",
    "core-ascii",
    "core-pr-title",
    "core-commitlint",
    "core-attribution",
    "core-identity",
    "core-changelog",
    "core-python",
    "core-powershell",
    "core-node-pin",
    "core-kit-peers",
)


def workflow_jobs(name: str) -> set | None:
    """The check names a rule may bind to in .github/workflows/<name> at the repo root: its job ids and the
    names of its core- steps (core-ci.yml runs every check as a step of one job). None when not installed."""
    f = repo_root() / ".github" / "workflows" / name
    if not f.is_file():
        return None
    jobs, inside = set(), False
    # A core-ci.yml that calls the reusable workflow does not list the steps; they are the core's.
    if ch.REUSABLE_CALL.search(f.read_text(encoding="utf8")):
        jobs.update(CORE_CI_STEPS)
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


def ci_results(argv) -> tuple[dict | None, list[str]]:
    """{workflow: {job: conclusion}} from --ci-results FILE, or from the latest default-branch run with --ci."""
    if "--ci-results" in argv:
        i = argv.index("--ci-results")
        try:
            data = json.loads(pathlib.Path(argv[i + 1]).read_text(encoding="utf8"))
        except (IndexError, OSError, ValueError) as e:
            return None, [f"--ci-results: cannot read the results file: {e}"]
        return (
            {w: {j: str(c).lower() for j, c in (jobs or {}).items()} for w, jobs in data.items()}
            if isinstance(data, dict)
            else None
        ), []
    if "--ci" not in argv:
        return None, []
    # core-ci.yml always; the scheduled template lint-sweep.yml only when installed (ci-cd-release.md 2.1).
    names = ["core-ci.yml"] + [n for n in ("lint-sweep.yml",) if workflow_jobs(n) is not None]
    return read_ci_runs(names, default_branch(), gh_run)


def gh_run(args: list) -> tuple[int, str]:
    """One gh call from the repo root: (exit code, stdout). Tests replace it with a fixture."""
    r = subprocess.run(["gh", *args], capture_output=True, text=True, cwd=repo_root())
    return r.returncode, r.stdout.strip()


def merged_pr_head(branch: str, run) -> str:
    """The head sha of the most recently merged pull request into branch whose tree equals branch's
    tree, or "". A merge gate that merges with the workflow token never starts a push run on the
    default branch, so that head's pull request run is the CI result of what the branch holds."""
    rc, tree = run(
        ["api", f"repos/{{owner}}/{{repo}}/commits/{branch}", "--jq", ".commit.tree.sha"]
    )
    if rc != 0 or not tree:
        return ""
    rc, out = run(
        [
            "pr",
            "list",
            "--state",
            "merged",
            "--base",
            branch,
            "--limit",
            "10",
            "--json",
            "headRefOid,mergedAt",
        ]
    )
    try:
        prs = json.loads(out or "[]") if rc == 0 else []
    except ValueError:
        prs = []
    for pr in sorted(prs, key=lambda p: p.get("mergedAt") or "", reverse=True):
        head = pr.get("headRefOid") or ""
        if not head:
            continue
        rc, t = run(["api", f"repos/{{owner}}/{{repo}}/commits/{head}", "--jq", ".commit.tree.sha"])
        if rc == 0 and t == tree:
            return head
    return ""


def read_ci_runs(names: list, branch: str, run) -> tuple[dict, list[str]]:
    """{workflow: {job: conclusion}} from the latest run of each workflow on branch. With no run on the
    branch, the last run on the head of the most recently merged pull request whose tree equals the
    branch's tree (merged_pr_head) stands in."""
    out, problems = {}, []
    head = None
    for name in names:
        rc, rid = run(
            [
                "run",
                "list",
                "--workflow",
                name,
                "--limit",
                "1",
                "--json",
                "databaseId",
                "--jq",
                ".[0].databaseId",
                "--branch",
                branch,
            ]
        )
        if rc != 0 or not rid:
            if head is None:
                head = merged_pr_head(branch, run)
            rc, rid = (
                run(
                    [
                        "run",
                        "list",
                        "--workflow",
                        name,
                        "--limit",
                        "1",
                        "--json",
                        "databaseId",
                        "--jq",
                        ".[0].databaseId",
                        "--commit",
                        head,
                    ]
                )
                if head
                else (1, "")
            )
            if rc != 0 or not rid:
                problems.append(
                    f"--ci: no run of {name} found on the default branch"
                    + (" or on the head of the last merged pull request" if head else "")
                )
                continue
        got = run_results(rid, run)
        if got is None:
            problems.append(f"--ci: cannot read run {rid} of {name}")
            continue
        # A push run of core-ci.yml runs only the secret scan, so its other steps read skipped. Their
        # result is the run on the head of the last merged pull request with the same tree.
        if any(c == "skipped" for k, c in got.items() if k.startswith("core-")):
            if head is None:
                head = merged_pr_head(branch, run)
            rc, prid = (
                run(
                    [
                        "run",
                        "list",
                        "--workflow",
                        name,
                        "--limit",
                        "1",
                        "--json",
                        "databaseId",
                        "--jq",
                        ".[0].databaseId",
                        "--commit",
                        head,
                    ]
                )
                if head
                else (1, "")
            )
            pr = run_results(prid, run) if rc == 0 and prid and prid != rid else None
            for k, c in (pr or {}).items():
                if got.get(k) in ("skipped", None):
                    got[k] = c
        out[name] = got
    return out, problems


def run_results(rid: str, run) -> dict | None:
    """{job or step name: conclusion} of one run: every job and every step of it, or None if unreadable."""
    rc, text = run(
        [
            "run",
            "view",
            rid,
            "--json",
            "jobs",
            "--jq",
            ".jobs[] | ([.name, .conclusion] | @tsv), (.steps[]? | [.name, .conclusion] | @tsv)",
        ]
    )
    if rc != 0:
        return None
    out = dict(ln.split("\t", 1) for ln in text.splitlines() if "\t" in ln)
    # A job that calls the reusable workflow reads "<caller job> / core-checks": keep the bare name too.
    for k in [k for k in out if k.endswith(" / core-checks")]:
        out.setdefault("core-checks", out[k])
    return out


def required_problems(argv) -> list[str]:
    """Problems for the core-ci.yml jobs the merge gate does not require, read through core-ci.py."""
    api = None
    if "--required-json" in argv:
        i = argv.index("--required-json")
        try:
            api = json.loads(pathlib.Path(argv[i + 1]).read_text(encoding="utf8"))
        except (IndexError, OSError, ValueError) as e:
            return [f"--required-json: cannot read the file: {e}"]
    elif "--ci" not in argv:
        return []
    import importlib.util

    spec = importlib.util.spec_from_file_location("core_ci", ch.ROOT / "scripts" / "core-ci.py")
    if spec is None or spec.loader is None:
        return ["required checks: scripts/core-ci.py is missing, run sync-core.py"]
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    root = repo_root()
    try:
        if api is None:
            r = subprocess.run(
                ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
                capture_output=True,
                text=True,
                cwd=root,
            )
            rep = mod.required_report(root, r.stdout.strip(), default_branch())
        else:
            rep = mod.required_report(root, api=api)
    except (RuntimeError, OSError, ValueError) as e:
        return [f"required checks: cannot read the merge gate: {e}"]
    if rep is None or not rep["missing"]:
        return []
    return [
        f"core-ci.yml jobs the merge gate does not require: {', '.join(rep['missing'])} "
        f"(scripts/core-ci.py required-checks --fix prints the command)"
    ]


def default_branch() -> str:
    r = subprocess.run(
        ["gh", "repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"],
        capture_output=True,
        text=True,
        cwd=repo_root(),
    )
    return r.stdout.strip() or "main"


def overlay_ci_status(rule, results) -> tuple[str, str]:
    """pass or fail from the workflow's job conclusions; fail when the workflow or a job is not installed;
    unverified when installed but no result was read, or a job was skipped."""
    wf, jobs = rule["check"].get("workflow"), rule["check"].get("jobs") or []
    if not wf or not jobs:
        return "unverified", "the rule names no workflow job"
    have = workflow_jobs(wf)
    if have is None:
        return "fail", f".github/workflows/{wf} is not installed"
    missing = [j for j in jobs if j not in have]
    if missing:
        return "fail", f"{wf} has no job {', '.join(missing)}"
    if results is None:
        return "unverified", f"{wf} is installed; pass --ci or --ci-results to read its result"
    got = [(results.get(wf) or {}).get(j) for j in jobs]
    if any(c in ("failure", "cancelled", "timed_out", "action_required") for c in got):
        return "fail", f"{wf} job failed: " + ", ".join(
            j for j, c in zip(jobs, got) if c not in ("success", None, "skipped")
        )
    if all(c == "success" for c in got):
        return "pass", f"{wf} {', '.join(jobs)} succeeded"
    return "unverified", f"{wf} {', '.join(jobs)}: no successful result (skipped or not run)"


# ---------------------------------------------------------------- proof records

PROOFS = ch.ROOT / "standards-local" / "proofs.json"
PROOF_KINDS = ("ci", "test", "review")
# A proof may be the rule's own kind or stronger: ci beats test beats review.
STRENGTH = {
    "review": 0,
    "test": 1,
    "ci": 2,
    "overlay-ci": 2,
    "core-ci": 2,
    "lint": 2,
    "repo-check": 2,
}
REVIEW_MAX_DAYS = 180


def load_proofs(registry, today=None) -> tuple[dict, list[str]]:
    """Valid proof records by rule id, and a problem line for every broken or stale one."""
    import datetime

    if not PROOFS.is_file():
        return {}, []
    try:
        data = json.loads(PROOFS.read_text(encoding="utf8"))
    except (OSError, ValueError) as e:
        return {}, [f"proofs.json: cannot read: {e}"]
    if not isinstance(data, dict):
        return {}, ["proofs.json: the top level must be an object of rule id -> proof"]
    max_days = data.pop("$max_review_age_days", REVIEW_MAX_DAYS)
    data.pop("$description", None)
    rules = {r["id"]: r for r in registry.get("rules", [])}
    today = today or datetime.date.today()
    root = repo_root()
    good, problems = {}, []
    for rid, p in data.items():
        where = f"proofs.json {rid}"
        if rid not in rules:
            problems.append(f"{where}: no such rule in the registry")
            continue
        if (
            not isinstance(p, dict)
            or p.get("kind") not in PROOF_KINDS
            or not isinstance(p.get("ref"), str)
            or not p["ref"]
        ):
            problems.append(f"{where}: needs kind (ci, test or review) and ref")
            continue
        kind, ref = p["kind"], p["ref"]
        if STRENGTH[kind] < STRENGTH.get(rules[rid]["check"]["kind"], 0):
            problems.append(
                f"{where}: a {kind} proof is weaker than the rule's {rules[rid]['check']['kind']} check"
            )
            continue
        if kind == "ci":
            wf, _, job = ref.partition("#")
            jobs = workflow_jobs(wf) if wf and job else None
            if jobs is None or job not in jobs:
                problems.append(
                    f"{where}: ref must be <workflow file>#<job> of an installed workflow; {ref} not found"
                )
                continue
        elif kind == "test":
            if not (root / ref).is_file():
                problems.append(f"{where}: test file {ref} does not exist")
                continue
        else:
            doc = root / ref
            if not doc.is_file():
                problems.append(f"{where}: review record {ref} does not exist")
                continue
            try:
                when = datetime.date.fromisoformat(str(p.get("date", "")))
            except ValueError:
                problems.append(f"{where}: a review proof needs date YYYY-MM-DD")
                continue
            age = (today - when).days
            if age > max_days:
                problems.append(
                    f"{where}: review of {when} is {age} days old, over the {max_days}-day limit"
                )
                continue
        good[rid] = p
    return good, problems


def repo_check_status(rule, by_ref) -> tuple[str, int, str]:
    """(status, finding count, note) of a repo-check rule: pass on no finding, fail on a finding, excepted
    while an active exception names the rule, unverified when the check cannot run."""
    cid = rule["check"].get("id")
    if repo_checks is None or cid not in repo_checks.CHECKS:
        return "unverified", 0, f"repo check {cid} is not in this overlay's scripts/repo_checks.py"
    try:
        found = repo_checks.run(cid, repo_root())
    except Exception as e:  # a crashed check proves nothing
        return "unverified", 0, f"repo check {cid} could not run: {e}"
    if not found:
        return "pass", 0, ""
    first = f"{found[0][0]}:{found[0][1]}: {found[0][2]}"
    return ("excepted" if by_ref.get(rule["ref"]) else "fail"), len(found), first


def in_scope(rule, scopes) -> bool:
    applies = rule.get("applies_to") or ["all"]
    return scopes is None or "all" in applies or bool(scopes & set(applies))


UI_THEME_RULES = ("UI007", "UI008", "UI010")
# The synced folder, the package name, or the usual '@kit' alias for kit-core in the build config.
KIT_IMPORT = ("kit-core", "@build-standards/kit", "'@kit'", '"@kit"', "'@kit/", '"@kit/')


DEFINES = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:function|const|class)\s+([A-Z][A-Za-z0-9]*)", re.M
)
KIT_EXPORTS = re.compile(r"export\s*\{([^}]*)\}\s*from", re.S)


def kit_exports(kit_dir) -> set:
    """Component names the kit exports from its index (types are skipped)."""
    names = set()
    index = kit_dir / "index.ts"
    try:
        text = index.read_text(encoding="utf8")
    except OSError:
        return names
    for m in KIT_EXPORTS.finditer(text):
        for part in m.group(1).split(","):
            name = part.strip().split(" as ")[-1].strip()
            if name[:1].isupper():
                names.add(name)
    return names


def stand_ins(files, kit_names) -> list:
    """Local components named like a kit export, in files that never import the kit."""
    out = []
    for f in files:
        if (
            f.suffix not in (".tsx", ".jsx", ".ts")
            or "kit-core" in f.parts
            or "node_modules" in f.parts
        ):
            continue
        try:
            text = f.read_text(encoding="utf8", errors="replace")
        except OSError:
            continue
        if any(k in text for k in KIT_IMPORT):
            continue
        for name in DEFINES.findall(text):
            if name in kit_names:
                out.append(f"{name} ({f.name})")
    return sorted(set(out))


def ui_adoption(lint, scopes) -> dict:
    """Verdict on web-ui.md 0.11 from the lint report and a scan for the kit import."""
    cfg_file = ch.ROOT / "standards-local" / "ui-lint.json"
    kit_dir = ch.ROOT / "kit-core"
    if (scopes is not None and "web" not in scopes) or not (cfg_file.is_file() or kit_dir.is_dir()):
        return {"status": "not_applicable", "reasons": []}
    try:
        cfg = json.loads(cfg_file.read_text(encoding="utf8")) if cfg_file.is_file() else {}
    except (OSError, json.JSONDecodeError):
        cfg = {}
    base = (ch.ROOT / cfg.get("root", ".")).resolve()
    imported = False
    scanned = []
    for p in cfg.get("paths", ["src"]):
        target = base / p
        files = (
            [target] if target.is_file() else sorted(target.rglob("*")) if target.is_dir() else []
        )
        scanned += files
        for f in files:
            if imported:
                break
            if (
                f.suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".css")
                and "node_modules" not in f.parts
            ):
                try:
                    if any(k in f.read_text(encoding="utf8", errors="replace") for k in KIT_IMPORT):
                        imported = True
                except OSError:
                    pass
    copies = stand_ins(scanned, kit_exports(kit_dir))
    theme = sum(1 for f in lint.get("findings", []) if f["rule"] in UI_THEME_RULES)
    reasons = []
    if not imported:
        reasons.append("the kit is not imported from kit-core")
    if theme:
        reasons.append(f"{theme} local theme or token finding(s) (UI007, UI008, UI010)")
    if lint.get("findings"):
        reasons.append(f"{len(lint['findings'])} lint finding(s), the target is zero")
    if lint.get("baseline_set") or cfg.get("baseline"):
        reasons.append("ui-lint.json sets a baseline, which a UI consumer may not keep")
    if "error" in lint:
        reasons.append("the UI lint could not run")
    if copies:
        reasons.append(f"{len(copies)} local stand-in(s) for kit parts: " + ", ".join(copies[:8]))
    return {"status": "adopted" if not reasons else "partial", "reasons": reasons}


def ui_with_exceptions(ui, by_ref):
    """A partial adoption covered by an active exception on web-ui.md 0.11 is excepted, not partial."""
    ids = by_ref.get("web-ui.md 0.11")
    if ui["status"] == "partial" and ids:
        return dict(ui, status="excepted", exceptions=ids)
    return ui


def diff_rules(old, new):
    o = {r["id"]: r for r in (old or {}).get("rules", [])}
    n = {r["id"]: r for r in (new or {}).get("rules", [])}
    added = [n[k] for k in n if k not in o]
    changed = [
        {
            "id": k,
            "title": n[k]["title"],
            "fields": [f for f in COMPARED if o[k].get(f) != n[k].get(f)],
        }
        for k in n
        if k in o and any(o[k].get(f) != n[k].get(f) for f in COMPARED)
    ]
    removed = [{"id": k, "title": o[k]["title"]} for k in o if k not in n]
    return added, changed, removed


def main(argv):
    if "--vendored" in argv:
        i = argv.index("--vendored")
        repo = argv[i + 1] if i + 1 < len(argv) else ""
        rec = vendored_record(repo)
        if rec is None:
            print(
                f"core-status: no vendored record for {repo or '(no repo given)'} on this machine"
            )
            return 2
        latest = rec.get("latest")
        if "--latest" in argv:
            latest = ch.latest_tag(ch.core_repo())
        behind = bool(latest) and latest != rec["release"]
        if "--json" in argv:
            print(
                json.dumps(
                    {"vendored": True, "repo": repo, **rec, "latest": latest, "behind": behind},
                    indent=2,
                )
            )
        else:
            state = (
                f"behind (core is {latest})"
                if behind
                else ("current" if latest else "latest unknown")
            )
            print(
                f"core-status: {repo} vendored copy carries core {rec['release']}, {state} "
                f"(found by {rec.get('found_by', 'record')}, source {str(rec.get('source_hash', ''))[:12]})"
            )
        return 3 if behind else 0
    try:
        lock = ch.read_lock()
    except (OSError, KeyError, ValueError) as e:
        print(f"core-status: cannot read standards.lock: {e}")
        return 2
    registry = (
        json.loads(REGISTRY.read_text(encoding="utf8")) if REGISTRY.is_file() else {"rules": []}
    )
    pinned_hash = lock.get("content_sha256")
    drift = bool(pinned_hash) and ch.content_hash() != pinned_hash
    lint = (
        run_json([str(LINT), "--json"])
        if LINT.is_file()
        else {"error": "lint-core/ui_lint.py missing, run sync-core.py"}
    )
    exc = (
        run_json([str(EXCEPTIONS), "--json"])
        if EXCEPTIONS.is_file()
        else {"error": "check-exceptions.py missing"}
    )
    exceptions = exc.get("exceptions", [])
    by_ref = {}
    for e in exceptions:
        by_ref.setdefault(e["rule"], []).append(e["id"])

    slint = (
        run_json([str(SCRIPT_LINT), "--json"])
        if SCRIPT_LINT.is_file()
        else {"configured": False, "findings": [], "over_baseline": {}, "refs": {}}
    )
    script_refs = slint.get("refs", {})
    script_on = bool(slint.get("configured")) and "error" not in slint

    def tally(source, ids):
        n = sum(1 for f in source.get("findings", []) if f["rule"] in ids)
        n_over = sum(
            v for k, v in source.get("over_baseline", {}).items() if k.rsplit("::", 1)[-1] in ids
        )
        return n, n_over

    scopes, scope_problems = declared_scopes()
    stacks_missing = STACKS_MISSING in scope_problems
    results, ci_problems = ci_results(argv)
    ci_problems = ci_problems + required_problems(argv)
    proofs, proof_problems = load_proofs(registry)
    gaps = missing_lint_config(scopes)
    scope_problems = scope_problems + gaps
    gap_stacks = {g.split()[1] for g in gaps}
    ui_gap = "web" in gap_stacks
    script_gap = bool(gap_stacks & {"powershell", "python", "iac"})
    rules, out_of_scope = [], []
    ui = ui_with_exceptions(ui_adoption(lint, scopes), by_ref)
    for r in registry.get("rules", []):
        if not in_scope(r, scopes):
            out_of_scope.append(r["id"])
            continue
        kind = r["check"]["kind"]
        note = ""
        lid = r["check"].get("id")
        n = n_over = 0
        if kind == "lint" and lid in script_refs:
            n, n_over = tally(slint, {lid})
            status = (
                "error"
                if "error" in slint
                else "fail"
                if script_gap and not script_on
                else "unverified"
                if not script_on
                else "pass"
                if n == 0
                else "fail"
                if n_over
                else "excepted"
            )
        elif (
            kind == "lint"
            and ui_gap
            and (r.get("applies_to") or ["all"]) != ["all"]
            and "web" in r["applies_to"]
        ):
            status = "fail"
        elif kind == "lint" and lid not in lint.get("refs", {lid: None}):
            status = "unverified"
        elif kind == "lint":
            n, n_over = tally(lint, {lid})
            status = (
                "error"
                if "error" in lint
                else "pass"
                if n == 0
                else "fail"
                if n_over
                else "excepted"
            )
        elif kind == "core-ci":
            # A proof the core runs on the kit holds for an app only when the app uses the kit whole.
            status = (
                "pass"
                if r["check"].get("requires") != "ui-adoption" or ui["status"] == "adopted"
                else "not_applicable"
            )
        elif kind == "repo-check":
            status, n, note = repo_check_status(r, by_ref)
            n_over = n if status == "fail" else 0
        elif kind == "overlay-ci":
            status, note = overlay_ci_status(r, results)
            if status == "unverified" and by_ref.get(r["ref"]):
                status = "excepted"
        else:
            status = "excepted" if by_ref.get(r["ref"]) else "unverified"
            support = (
                {k for k, ref in script_refs.items() if ref == r["ref"]} if script_on else set()
            )
            if support:
                n, n_over = tally(slint, support)
                if n:
                    status = "fail" if n_over else "excepted"
        proof = proofs.get(r["id"])
        if proof and status == "unverified":
            status, note = "proved", f"{proof['kind']}: {proof['ref']}"
        rules.append(
            {
                "id": r["id"],
                "ref": r["ref"],
                "title": r["title"],
                "level": r["level"],
                "kind": kind,
                "status": status,
                "note": note,
                "findings": n,
                "over_baseline": n_over,
                "exceptions": by_ref.get(r["ref"], []),
            }
        )

    report = {
        "core": {
            "pinned_ref": lock.get("ref"),
            "pinned_commit": lock.get("commit"),
            "drift": drift,
            "latest": None,
            "behind": None,
        },
        "scopes": sorted(scopes) if scopes is not None else None,
        "out_of_scope": out_of_scope,
        "ui_adoption": ui,
        "summary": {
            s: sum(1 for x in rules if x["status"] == s)
            for s in ("pass", "proved", "excepted", "fail", "unverified", "not_applicable", "error")
        },
        "rules": rules,
        "exceptions": [
            dict(e, expiring=e.get("days_left") is not None and e["days_left"] <= EXPIRING_DAYS)
            for e in exceptions
        ],
        "problems": (
            exc.get("problems", [])
            + ([lint["error"]] if "error" in lint else [])
            + ([slint["error"]] if "error" in slint else [])
            + ([exc["error"]] if "error" in exc else [])
            + scope_problems
            + ci_problems
            + proof_problems
        ),
        "fixed_since_baseline": lint.get("fixed_since_baseline", 0)
        + slint.get("fixed_since_baseline", 0),
        "script_lint": {
            "configured": bool(slint.get("configured")),
            "files": slint.get("files", 0),
        },
        "new_rules": [],
        "changed_rules": [],
        "removed_rules": [],
    }
    if "--latest" in argv:
        latest = ch.latest_tag(ch.core_repo())
        report["core"]["latest"] = latest
        report["core"]["behind"] = latest != lock.get("ref")
        if report["core"]["behind"]:
            newer = registry_at(ch.core_repo(), latest)
            if newer is None:
                report["problems"].append(f"could not read standards/rules.json at {latest}")
            else:
                a, c, rm = diff_rules(registry, newer)
                a = [r for r in a if in_scope(r, scopes)]
                newer_by_id = {r["id"]: r for r in newer.get("rules", [])}
                c = [r for r in c if in_scope(newer_by_id.get(r["id"], {}), scopes)]
                report["new_rules"], report["changed_rules"], report["removed_rules"] = a, c, rm

    require_ui = "--require-ui-adopted" in argv
    ui_bad = report["ui_adoption"]["status"] == "partial"
    lint_bad = "--require-lint-config" in argv and (bool(gaps) or stacks_missing)
    if "--json" in argv:
        print(json.dumps(report, indent=2))
        return 1 if (require_ui and ui_bad) or lint_bad else 0
    c, s = report["core"], report["summary"]
    print(
        f"core-status: core pinned at {c['pinned_ref']}"
        + (f", latest {c['latest']}" if c["latest"] else "")
        + (" (drift: synced copies were edited)" if drift else "")
    )
    print(
        f"  rules: {s['pass']} pass, {s['proved']} proved, {s['excepted']} excepted, {s['fail']} fail, "
        f"{s['unverified']} unverified, {s['not_applicable']} not applicable"
    )
    if report["scopes"] is not None:
        print(
            f"  stacks: {', '.join(report['scopes']) or 'none'} ({len(out_of_scope)} rule(s) for other stacks not reported)"
        )
    ui = report["ui_adoption"]
    if ui["status"] != "not_applicable":
        print(f"  ui: {ui['status']}" + (f" ({'; '.join(ui['reasons'])})" if ui["reasons"] else ""))
    for x in rules:
        if x["status"] in ("fail", "error"):
            print(
                f"  FAIL {x['id']} {x['title']}: "
                + (x["note"] or f"{x['over_baseline'] or x['findings']} finding(s)")
            )
    for e in report["exceptions"]:
        if e["expiring"]:
            print(f"  EXPIRING {e['id']} ({e['rule']}) in {e['days_left']} day(s)")
    for p in report["problems"]:
        print(f"  PROBLEM {p}")
    for r in report["new_rules"]:
        print(f"  NEW in {c['latest']}: {r['id']} {r['title']}")
    for r in report["changed_rules"]:
        print(f"  CHANGED in {c['latest']}: {r['id']} {r['title']} ({', '.join(r['fields'])})")
    if lint_bad:
        print("::error::" + "; ".join(gaps + ([STACKS_MISSING] if stacks_missing else [])))
    if require_ui and ui_bad:
        print(
            "::error::the UI is only partly adopted (web-ui.md 0.11): " + "; ".join(ui["reasons"])
        )
        return 1
    return 1 if lint_bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
