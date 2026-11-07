#!/usr/bin/env python3
"""
pr_gate.py

Purpose: The draft gate block grammar and its checker, the plug-in own_pr_merge.py loads from OPSCENTER_DRAFT_GATE. A staged
         pull request stays a draft until a condition holds (an earlier pull request merged, the logs show nothing would break).
         The condition is a fenced block in the PR description; each line is checked against live data, and the own-PR lane marks
         the draft ready once every line is met. The grammar and the loop are generic; the line kinds are the consumer's.
Date:    2026-11-06

Block:   a fence opened by three backticks and the word gate, closed by three backticks:

             ```gate
             # a comment
             pr-merged: 513
             run-success: terraform-ci main
             logs-quiet: the plan shows no deletes
               and the last run is under an hour old
             ```

         One line is `kind: argument`. A line that starts with white space continues the line above. Blank lines and lines
         starting with # are ignored. A line with no kind, or a kind nobody registered, is an error and is never met.
Built-in kinds: `pr-merged: <number>` (that pull request is merged), `run-success: <workflow> <branch>` (the newest completed
         run of the workflow on the branch succeeded, however old it is) and `applied: <number>` (that pull request is merged
         AND a run of the apply workflow on the apply branch that started at or after the merge succeeded; a run after the
         merge that did not succeed is named in the reason). The apply workflow and branch come from evaluate's `config`
         ({"apply_workflow", "apply_branch"}, the own-PR lane passes its policy `gate_apply_workflow` and
         `gate_apply_branch`) or from OPSCENTER_GATE_APPLY_WORKFLOW and OPSCENTER_GATE_APPLY_BRANCH. Both default to
         nothing, and `applied` is then never met and says it is not configured. The consumer adds kinds: `OPSCENTER_GATE_KINDS` names a Python file with a
         dict `KINDS = {"kind": fn(arg, repo, run) -> (met: bool, detail: str)}`, or call `register(kind, fn)`.
API:     parse(body) -> gate | None;  evaluate(gate, repo, gh="gh", kinds=None, run=None, config=None) -> results;  summary(results) ->
         (met, total, first unmet or None). A result is {label, detail, met}. A check that raises is unmet with the error.
"""

import datetime as dt
import importlib.util
import json
import os
import re
import subprocess

FENCE_OPEN = re.compile(r"^\s*```gate\s*$")
FENCE_CLOSE = re.compile(r"^\s*```\s*$")
LINE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\s*:\s*(.*)$")
_KINDS = {}


def parse(body):
    """The gate declared in a PR description, or None when there is no block. {"lines": [{kind, arg, raw, error}]}."""
    lines, inside, found = [], False, False
    for raw in (body or "").replace("\r\n", "\n").split("\n"):
        if not inside:
            if FENCE_OPEN.match(raw):
                inside = found = True
            continue
        if FENCE_CLOSE.match(raw):
            break
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[0] in " \t" and lines:
            lines[-1]["arg"] = (lines[-1]["arg"] + " " + raw.strip()).strip()
            lines[-1]["raw"] += "\n" + raw
            continue
        m = LINE.match(raw.strip())
        lines.append(
            {
                "kind": m.group(1).lower() if m else "",
                "arg": m.group(2).strip() if m else "",
                "raw": raw,
                "error": None if m else "not `kind: argument`",
            }
        )
    if not found:
        return None
    return {"lines": lines}


def register(kind, fn):
    _KINDS[kind.lower()] = fn


def _consumer_kinds():
    path = os.environ.get("OPSCENTER_GATE_KINDS", "").strip()
    if not path or not os.path.isfile(path):
        return {}
    spec = importlib.util.spec_from_file_location("gate_kinds_plugin", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {k.lower(): v for k, v in (getattr(mod, "KINDS", {}) or {}).items()}


def _gh_json(run, args):
    r = run(args)
    return json.loads(r.stdout or "null")


def _pr_merged(arg, repo, run):
    m = re.fullmatch(r"#?(\d+)", arg.strip())
    if not m:
        return False, f"{arg!r} is not a pull request number"
    d = _gh_json(run, ["pr", "view", m.group(1), "-R", repo, "--json", "state,mergedAt"]) or {}
    ok = str(d.get("state")).upper() == "MERGED" or bool(d.get("mergedAt"))
    return ok, f"#{m.group(1)} is {str(d.get('state') or 'unknown').lower()}"


def _run_success(arg, repo, run):
    parts = arg.split()
    if len(parts) != 2:
        return False, "expected `<workflow> <branch>`"
    runs = (
        _gh_json(
            run,
            [
                "run",
                "list",
                "-R",
                repo,
                "--workflow",
                parts[0],
                "--branch",
                parts[1],
                "--limit",
                "20",
                "--json",
                "conclusion,status",
            ],
        )
        or []
    )
    done = [x for x in runs if x.get("status") == "completed"]
    if not done:
        return False, f"no completed run of {parts[0]} on {parts[1]}"
    return done[0].get(
        "conclusion"
    ) == "success", f"newest run of {parts[0]} on {parts[1]}: {done[0].get('conclusion')}"


def _when(s):
    """A code host timestamp (2026-01-02T03:04:05Z) as an aware datetime, or None when it cannot be read."""
    try:
        t = dt.datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def apply_settings(config=None):
    """(workflow, branch) for the `applied` kind: `config` first, then the environment, else None."""
    config = config or {}
    wf = config.get("apply_workflow") or os.environ.get("OPSCENTER_GATE_APPLY_WORKFLOW", "").strip()
    br = config.get("apply_branch") or os.environ.get("OPSCENTER_GATE_APPLY_BRANCH", "").strip()
    return (str(wf) if wf else None), (str(br) if br else None)


def _applied(arg, repo, run, config=None):
    m = re.fullmatch(r"#?(\d+)", arg.strip())
    if not m:
        return False, f"{arg!r} is not a pull request number"
    workflow, branch = apply_settings(config)
    if not workflow or not branch:
        return False, (
            "no apply workflow and branch are configured (gate_apply_workflow and gate_apply_branch, or "
            "OPSCENTER_GATE_APPLY_WORKFLOW and OPSCENTER_GATE_APPLY_BRANCH)"
        )
    n = m.group(1)
    d = _gh_json(run, ["pr", "view", n, "-R", repo, "--json", "state,mergedAt"]) or {}
    if str(d.get("state")).upper() != "MERGED":
        return False, f"#{n} is {str(d.get('state') or 'unknown').lower()}, not merged"
    merged = _when(d.get("mergedAt"))
    if merged is None:
        return False, f"#{n} is merged but its merge time could not be read"
    runs = (
        _gh_json(
            run,
            [
                "run",
                "list",
                "-R",
                repo,
                "--workflow",
                workflow,
                "--branch",
                branch,
                "--limit",
                "50",
                "--json",
                "databaseId,conclusion,status,startedAt,createdAt,headBranch",
            ],
        )
        or []
    )
    after = []
    for r in runs:
        if r.get("headBranch") not in (None, branch):
            continue
        started = _when(r.get("startedAt") or r.get("createdAt"))
        if started is not None and started >= merged:  # a run with no readable start never counts
            after.append((started, r))
    after.sort(key=lambda x: x[0])
    ok = [
        r for _, r in after if r.get("status") == "completed" and r.get("conclusion") == "success"
    ]
    if ok:
        return (
            True,
            f"#{n} merged, and {workflow} run {ok[0].get('databaseId')} on {branch} succeeded after the merge",
        )
    bad = [
        r
        for _, r in after
        if r.get("status") == "completed" and r.get("conclusion") not in ("success", None, "")
    ]
    if bad:
        r = bad[-1]
        return False, (
            f"#{n} merged, but {workflow} run {r.get('databaseId')} on {branch} after the merge ended "
            f"{r.get('conclusion')}"
        )
    return False, f"#{n} merged, but {workflow} has not succeeded on {branch} since the merge"


register("pr-merged", _pr_merged)
register("run-success", _run_success)
register("applied", _applied)


def evaluate(gate, repo, gh="gh", kinds=None, run=None, config=None):
    """Check every line against live data. Nothing here writes. `config` carries the `applied` kind's settings."""
    run = run or (
        lambda args: subprocess.run(
            [gh or "gh", *args], capture_output=True, text=True, timeout=60, check=True
        )
    )
    table = dict(_KINDS)
    table["applied"] = lambda arg, repo, run: _applied(arg, repo, run, config)
    table.update(_consumer_kinds())
    table.update({k.lower(): v for k, v in (kinds or {}).items()})
    out = []
    for ln in gate["lines"]:
        label = f"{ln['kind']}: {ln['arg']}" if ln["kind"] else ln["raw"].strip()
        if ln["error"]:
            out.append({"label": label, "detail": f"error: {ln['error']}", "met": False})
            continue
        fn = table.get(ln["kind"])
        if fn is None:
            out.append(
                {"label": label, "detail": f"error: unknown kind {ln['kind']!r}", "met": False}
            )
            continue
        try:
            met, detail = fn(ln["arg"], repo, run)
        except Exception as e:  # noqa: BLE001 - a check that cannot run is not met, never a pass
            met, detail = False, f"could not check: {str(e)[:160]}"
        out.append({"label": label, "detail": str(detail), "met": bool(met)})
    return out


def summary(results):
    """(met, total, first unmet result or None). An empty block is never met."""
    total = len(results)
    met = sum(1 for r in results if r["met"])
    first = next((r for r in results if not r["met"]), None)
    if total == 0:
        return 0, 0, {"label": "gate block", "detail": "the block has no lines"}
    return met, total, first
