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
Built-in kinds: `pr-merged: <number>` (that pull request is merged) and `run-success: <workflow> <branch>` (the newest completed
         run of the workflow on the branch succeeded). The consumer adds kinds: `OPSCENTER_GATE_KINDS` names a Python file with a
         dict `KINDS = {"kind": fn(arg, repo, run) -> (met: bool, detail: str)}`, or call `register(kind, fn)`.
API:     parse(body) -> gate | None;  evaluate(gate, repo, gh="gh", kinds=None, run=None) -> results;  summary(results) ->
         (met, total, first unmet or None). A result is {label, detail, met}. A check that raises is unmet with the error.
"""

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


register("pr-merged", _pr_merged)
register("run-success", _run_success)


def evaluate(gate, repo, gh="gh", kinds=None, run=None):
    """Check every line against live data. Nothing here writes."""
    run = run or (
        lambda args: subprocess.run(
            [gh or "gh", *args], capture_output=True, text=True, timeout=60, check=True
        )
    )
    table = dict(_KINDS)
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
