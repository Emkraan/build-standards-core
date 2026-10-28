#!/usr/bin/env python3
"""
autofix.py - the auto-fix session starter for the owner's own pull requests (opscenter/DESIGN.md section 12.3, items 3 to 5).

The own pull request lane (and the sync and core lanes) call consider() on every pass. The first pass that sees one of
the owner's pull requests held for a fixable problem starts ONE agent session right away to fix it on the branch (or
post the triage reply), and the lane merges once it clears. Other authors' pull requests never come here: consider()
refuses any author but the owner's.
  Fixable: red checks, untriaged high findings, blocking findings, a blocked review verdict, a merge conflict,
  unresolved review threads, and the extra reasons a target adds. Never fixable here: policy holds (the owner's
  sign-off), drafts, hold labels, a change freeze, checks still running, an unavailable review.
  A give-up whose cause is other open pull requests (a FIX WAITS ON line, or "open PRs #a and #b" in its text) waits for
  them; once every one merged the same head re-arms as problem rebase-on-main (one more session, daily cap applies). One
  closed unmerged is a plain give-up again.
  A lane hold "waits on #a, #b" (plan destroys only those open pull requests declare) is recorded like a give-up.
  A give-up may carry a structured FIX DECISION (question, options, recommendation) that the ops center shows as a
  decision card (decision_cards.py); the owner's choice of a "fix it this way" option (own-pr-directions.json, written
  only by the ops center) starts a directed-fix session for that head; CATALOG ADD lines in a result file are appended to
  the build skill's finding catalog (deduped) when a target has one, so the next build avoids the same finding.

Guards: one session per (PR, head, problem), never two at once for one PR, at most autofix.max_sessions_per_day sessions
per PR in 24 h, each capped by autofix.run_budget_s. When it gives up (cap hit, session gave up, or a session ended
without fixing the head it was given) it reports one line and the ops center counts the PR under Needs me.

Parts, all parameters or plug-ins (nothing here names a repository, a person or a tool):
  targets file   AUTOFIX_TARGETS (default <state>/autofix-targets.json):
                 {"targets": {"<name>": {"repo", "notes", "skill", "build": bool, "identity", "catalog", "extra_fixable"}},
                  "skills": ["common skill", ...]}
                 notes = extra brief lines for that repo, skill = the build skill the session loads, build = a repo with
                 a pre-push gate, identity = "Name <email>" the session commits as, catalog = finding catalog path
  pre-push gate  AUTOFIX_PREFLIGHT_CMD and AUTOFIX_REVIEW_CMD: command templates with {target} and {worktree}. Exit 0 pass,
                 1 findings (printed), 2 environment problem (treated as a failure). Unset means "run the repo's tests"
  runtime        set_runtime(obj) with busy_session(repo, number, branch, now) -> (id, title) | None,
                 launch(brief_path, name, skills, budget_s, log_path) -> pid, finished_sessions(now), archive(ids).
                 Default NullRuntime never reports busy and records the launch (pid -1). HermesRuntime is the reference
                 adapter for the Hermes agent runtime.
  held files     AUTOFIX_HELD_GATE: a module path whose path_reasons(files) names the files that cost an approval when
                 pushed (the plan gate, lanes/tfplan_gate.py); unset means every .github/ path
Test hooks: OWNPR_FIX_SPAWN=record (never spawns, records the argv in state).
System python3 is 3.9: no 3.10+ syntax.
"""

import contextlib
import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

BUSY_WINDOW_S = 600  # the session itself was active in the last 10 min
BUSY_MENTION_S = 1800  # and named the PR or its branch in the last 30 min
ARCHIVE_QUIET_S = 120  # an ended auto-fix session is archived once it has been quiet this long
# a push of files the plan gate holds costs an approval, so a fix that would land within this window of the last held
# push waits and joins the next round (one push per round).
HELD_PUSH_WINDOW_S = 1200
DECISION_RE = re.compile(r"^FIX DECISION:\s*(\{.*\})\s*$", re.M)
CATALOG_RE = re.compile(r"^CATALOG ADD:\s*\[([A-E])\]\s*(.{20,400})$", re.M)
LANE_WAITS_RE = re.compile(r"^waits on ((?:#\d+(?:, )?)+)")
OPTION_ACTIONS = ("override", "fix", "hold")
MIN_OPTIONS, MAX_OPTIONS = 2, 4
MAX_REASK = (
    2  # re-ask sessions per head after a rejected decision, then it shows as a plain give-up
)
FORBIDDEN = re.compile(
    r"ops ?center|hermes|\.hermes|\bbot\b|\bAI\b|assistant|claude|\u2014|\u2013|;", re.I
)
DEFAULTS = {"enabled": True, "max_sessions_per_day": 3, "run_budget_s": 5400}
# Lane reason prefix/substring -> problem key. Order matters: first match wins. A target adds its own through
# extra_fixable ([[needle, key], ...]); the keys it adds need a PLAIN line too (extra_plain).
FIXABLE = (
    ("checks red", "red-checks"),
    ("no triage reply", "untriaged-highs"),
    ("triage reply covers", "untriaged-highs"),  # a triage reply that names only some ids
    ("blocking finding", "blocking-findings"),
    ("PR review verdict blocked", "blocking-findings"),
    ("merge conflict", "merge-conflict"),
    ("unresolved review thread", "review-threads"),
)
PLAIN = {
    "red-checks": "checks are still red",
    "untriaged-highs": "high findings still have no fix or triage reply",
    "blocking-findings": "the review still has blocking findings",
    "merge-conflict": "it still conflicts with main",
    "review-threads": "review threads are still open",
    "rebase-on-main": "it is still held after the rebase on main",
    "directed-fix": "it is still held after the fix the owner chose",
}
RESULT_RE = re.compile(r"FIX RESULT:\s*(fixed|triaged|gave-up|nothing-to-do)\b\s*-?\s*(.*)", re.I)
# a give-up caused by other open PRs names them, so the lane re-arms once they merge.
# Explicit line from the session first, else the "open PR(s) #a and #b" phrase in its give-up text.
WAITS_LINE_RE = re.compile(r"^FIX WAITS ON:\s*(.+)$", re.I | re.M)
WAITS_TEXT_RE = re.compile(r"\bopen PRs?\s+(#\d+(?:\s*(?:,|and|, and)\s*#\d+)*)", re.I)
PR_STATE_CACHE = {}  # (repo, number) -> state, one lookup per PR per lane pass
ROUND_RULE = """ONE PUSH PER ROUND: every push of a file the plan job runs (anything the held-files gate names) costs the
   owner an approval. Before touching code, collect EVERY open finding for this head: the newest review comment (decode
   the data block, all H, B, M items), unresolved review threads, failing checks and the lane reason. Fix them all in ONE
   commit round, run the pre-push gate on the combined change, and push once. Never push one finding at a time. If held
   files were pushed in the last 20 minutes (git log, gh pr view), fold the rest of the round into that push window
   instead of adding another."""


def _targets():
    """The targets file, or {} when absent or unreadable (a bad file never breaks a pass)."""
    path = os.environ.get("AUTOFIX_TARGETS") or os.path.join(
        os.environ.get("OPSCENTER_STATE_DIR") or os.path.expanduser("~/.opscenter/state"),
        "autofix-targets.json",
    )
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def target_cfg(name):
    t = (_targets().get("targets") or {}).get(name)
    return t if isinstance(t, dict) else {}


def is_build_target(name):
    """A repo with a pre-push gate and a build skill: its fixes batch into one push per round."""
    return bool(target_cfg(name).get("build"))


def common_skills():
    s = _targets().get("skills")
    return [x for x in s if isinstance(x, str)] if isinstance(s, list) else []


def build_skill(name):
    return str(target_cfg(name).get("skill") or "")


def target_notes(ctx):
    return str(target_cfg(notes_key(ctx)).get("notes") or "")


def commit_identity(repo, target=""):
    """The name <email> a fix session commits as in this repo (a noreply address where the repo rejects real ones)."""
    return str(target_cfg(target).get("identity") or "the owner's configured git identity")


def catalog_path(target):
    p = target_cfg(target).get("catalog")
    return Path(p) if p else None


REARM_NEVER = ("draft", "label", "freeze")  # deliberate holds a rebase must never override


def waits_on(text, own=None, path=None):
    """Sorted PR numbers a give-up waits on (never the PR itself), or []."""
    src = ""
    if path:
        try:
            m = list(WAITS_LINE_RE.finditer(Path(path).read_text(errors="replace")))
            src = m[-1].group(1) if m else ""
        except OSError:
            src = ""
    if not src:
        m = WAITS_TEXT_RE.search(text or "")
        src = m.group(1) if m else ""
    nums = {int(x) for x in re.findall(r"#?(\d+)", src)}
    nums.discard(int(own) if own is not None else -1)
    return sorted(nums)


def pr_state(repo, number):
    """OPEN / MERGED / CLOSED for another PR, or None when gh fails (treated as still open)."""
    key = (repo, int(number))
    if key in PR_STATE_CACHE:
        return PR_STATE_CACHE[key]
    gh = os.environ.get("OPRG_GH_BIN") or shutil.which("gh") or "gh"
    try:
        r = subprocess.run(
            [gh, "pr", "view", str(int(number)), "-R", repo, "--json", "state", "--jq", ".state"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        state = r.stdout.strip().upper() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        state = None
    PR_STATE_CACHE[key] = state or None
    return PR_STATE_CACHE[key]


def push_files(repo, old, new):
    """File names changed between two heads of a PR branch, or None when gh cannot say."""
    gh = os.environ.get("OPRG_GH_BIN") or shutil.which("gh") or "gh"
    try:
        r = subprocess.run(
            [
                gh,
                "api",
                "--paginate",
                f"repos/{repo}/compare/{old}...{new}",
                "--jq",
                ".files[].filename",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def held_files(files):
    """The files the plan gate would hold, by its own path matcher (path_reasons). Any
    trouble loading the gate falls back to every .github/ path. None (unknown files) counts as held,
    so a failed read can only delay a fix by the window, never cost an extra approval."""
    if files is None:
        return [".github/ (changed files unknown)"]
    if not os.environ.get("AUTOFIX_HELD_GATE"):
        return [f for f in files if f.startswith(".github/")]
    try:
        spec = importlib.util.spec_from_file_location(
            "autofix_held_gate", os.environ["AUTOFIX_HELD_GATE"]
        )
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        reasons = gate.path_reasons(list(files))
        return [r.split(": ", 1)[-1] for r in reasons]
    except Exception:  # noqa: BLE001 - the gate is a separate script, fall back to the strict path rule
        return [f for f in files if f.startswith(".github/")]


def track_push(frec, target, repo, head, now_iso):
    """Notice a push (the head moved since the last pass) and remember when it touched held files."""
    prev = frec.get("seen_head")
    frec["seen_head"] = head
    if not prev or prev == head or not is_build_target(target):
        return
    paths = held_files(push_files(repo, prev, head))
    if paths:
        frec["held_push"] = {"head": head, "at": now_iso, "paths": paths[:5]}


def batch_wait_s(frec, now, others):
    """Seconds a pending fix should still wait so it joins the next round, or 0 to go now.
    others = the other open holds of the PR when the caller knows them: an empty list means this
    fix is the only blocker, so waiting gains nothing. None (unknown) batches."""
    hp = frec.get("held_push")
    if not hp or others == []:
        return 0
    left = HELD_PUSH_WINDOW_S - (now.timestamp() - _ts(hp.get("at")))
    return int(left) if left > 0 else 0


def problem_of(status, reason, target=""):
    """Problem key when the lane holds the PR for something a session can fix, else None. A target adds its own
    needles through extra_fixable ([[needle, key], ...] in the targets file), tried after the built in ones."""
    if status != "held" or not reason or reason.startswith(("needs me", "draft")):
        return None  # a draft is parked on purpose, never a fix
    extra = [
        tuple(x)
        for x in (target_cfg(target).get("extra_fixable") or [])
        if isinstance(x, (list, tuple)) and len(x) == 2
    ]
    for needle, key in (*FIXABLE, *extra):
        if needle.lower() in reason.lower():
            return key
    return None


def _alive(pid, marker=None):
    """True when pid runs. With a marker (the session's brief path, which is on its command
    line) it must also be that session, so a recycled pid is never mistaken for it."""
    try:
        if int(pid) <= 0:
            return False  # 0 and -1 mean "process group" and "every process" to kill()
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    if not marker:
        return True
    try:
        cmd = subprocess.run(
            ["/bin/ps", "-p", str(int(pid)), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return True  # cannot tell, keep treating it as running (never double-launch)
    return marker in cmd


def run_alive(run):
    return bool(run) and _alive(run.get("pid"), run.get("brief"))


def _ts(s):
    try:
        return (
            dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
            .replace(tzinfo=dt.timezone.utc)
            .timestamp()
        )
    except (TypeError, ValueError):
        return 0.0


def read_result(path):
    """(outcome, text) from the session's result file, or (None, '') when it wrote none."""
    try:
        txt = Path(path).read_text(errors="replace")
    except OSError:
        return None, ""
    matches = list(RESULT_RE.finditer(txt))
    m = matches[-1] if matches else None
    if not m:
        return None, ""
    return m.group(1).lower(), m.group(2).strip()[:800]


def check_decision(path):
    """(decision, error) for the FIX DECISION line of a result file. (None, None) when the file
    carries no decision line. (None, "<why>") when it carries one that fails the schema, so the
    fixer can be told exactly what to correct and re-ask (pr-review-and-merge.1.17: a fifth
    option is refused, never silently cut, because the cut could drop the recommended option).
    Shape of a good one: {"question": str, "options": [{"id", "label", "action": override|fix|hold,
    "effect", "reply" (override only: the owner's triage reply without the marker)}], "recommend": id},
    two to four options."""
    try:
        txt = Path(path).read_text(errors="replace")
    except OSError:
        return None, None
    m = list(DECISION_RE.finditer(txt))
    if not m:
        return None, None
    try:
        d = json.loads(m[-1].group(1))
    except ValueError:
        return None, "the FIX DECISION line is not valid JSON on a single line"
    if (
        not isinstance(d, dict)
        or not isinstance(d.get("question"), str)
        or not isinstance(d.get("options"), list)
    ):
        return None, 'the FIX DECISION needs a "question" string and an "options" list'
    n = len(d["options"])
    if n < MIN_OPTIONS or n > MAX_OPTIONS:
        return (
            None,
            f"the FIX DECISION has {n} options, it must have {MIN_OPTIONS} to {MAX_OPTIONS}",
        )
    opts = []
    for o in d["options"]:
        if not isinstance(o, dict) or o.get("action") not in OPTION_ACTIONS:
            return None, "every option needs an action of " + ", ".join(OPTION_ACTIONS)
        oid, label = str(o.get("id") or "").strip()[:8], str(o.get("label") or "").strip()[:120]
        if not oid or not label:
            return None, "every option needs an id and a label"
        clean = {
            "id": oid,
            "label": label,
            "action": o["action"],
            "effect": str(o.get("effect") or "")[:400],
        }
        if o["action"] == "override":
            reply = str(o.get("reply") or "").strip()
            if not reply or FORBIDDEN.search(reply) or not reply.isascii() or "triage:" in reply:
                # the card posts this on the code host as the owner, so it must already be clean
                return (
                    None,
                    "an override option needs a clean ASCII reply with no marker, semicolon or tool names",
                )
            clean["reply"] = reply[:3000]
        opts.append(clean)
    ids = [o["id"] for o in opts]
    if len(set(ids)) != len(ids):
        return None, "the option ids must be unique"
    rec = d.get("recommend") if d.get("recommend") in ids else ids[0]
    return {"question": d["question"].strip()[:400], "options": opts, "recommend": rec}, None


def read_decision(path):
    """The validated FIX DECISION dict from a result file, else None (see check_decision)."""
    return check_decision(path)[0]


def add_to_catalog(path, now_iso, target=""):
    """Append CATALOG ADD lines from a result file to the finding catalog, deduped by text.
    Returns the number added. A missing catalog is never created here."""
    cat_file = catalog_path(target)
    if cat_file is None:
        return 0
    try:
        txt = Path(path).read_text(errors="replace")
        cat = cat_file.read_text()
    except OSError:
        return 0
    # Lines this function appended end in "(added <date>)", so drop that before comparing, or the
    # same finding would be appended again on every later pass.
    have = {
        re.sub(r"\W+", " ", re.sub(r" \(added \d{4}-\d{2}-\d{2}\)$", "", ln).lower()).strip()
        for ln in cat.splitlines()
    }
    new = []
    for m in CATALOG_RE.finditer(txt):
        line = f"- [{m.group(1)}] {m.group(2).strip()}"
        if not line.isascii() or FORBIDDEN.search(m.group(2)):
            continue
        key = re.sub(r"\W+", " ", line.lower()).strip()
        if key not in have:
            have.add(key)
            new.append(line + f" (added {now_iso[:10]})")
    if new:
        with cat_file.open("a") as fh:
            fh.write("\n".join(new) + "\n")
    return len(new)


def directions_file(workdir):
    return Path(workdir).parent / "own-pr-directions.json"


def read_direction(workdir, number, head):
    """The owner's choice from the Ops Center decision card for this PR head, else None."""
    try:
        d = json.loads(directions_file(workdir).read_text())
    except (OSError, ValueError):
        return None
    rec = (d.get("prs") or {}).get(str(number)) or {}
    return rec if rec.get("head") == head and rec.get("at") else None


def notes_key(ctx):
    """The targets file key whose notes a brief carries: the target, or `<target>-feature` for a branch outside the target's
    `sync_branch_prefix` when the target sets one (a repo with nightly sync pull requests and feature pull requests)."""
    target = ctx.get("target") or ""
    prefix = target_cfg(target).get("sync_branch_prefix")
    if prefix and not str(ctx.get("branch") or "").startswith(prefix):
        return target + "-feature"
    return target


def residual_rule_text(cfg):
    """part 3: the brief block for the standing residual-risk rule (policy own_pr_merge.residual_risk_rule).
    Empty when the rule is absent, disabled or malformed, so a bad policy edit never breaks a brief."""
    rule = (cfg or {}).get("residual_risk_rule")
    if (
        not isinstance(rule, dict)
        or not rule.get("enabled")
        or not rule.get("id")
        or not rule.get("text")
    ):
        return ""
    rid = str(rule["id"])
    td_file = str(rule.get("td_file") or "technical-debt.md")
    text = f"""   Standing residual-risk rule {rid} (the owner approved it, policy own_pr_merge.residual_risk_rule):
   "{rule["text"]}"
   A fix session may triage a high as ACCEPTED under {rid} only when it cites, in the triage reply, all of:
   the rule id ({rid}), the race window in seconds, and the named recovery, each with file:line evidence
   (the line where the race window opens and closes, the line or command of the recovery). If either
   condition is not proven from the code in this head, or the window is more than about a second, or the
   recovery is a plan to build one later, it does NOT qualify: fix it or send it to the owner (FIX DECISION).
   A medium or blocking finding never qualifies, only a high.
   For every high accepted this way, before you post the reply append one debt entry to {td_file}:
   run grep -o "DEBT-[0-9]*" {td_file} | sort -u | tail -3 first and use the next id (two sessions may
   race, re-grep right before the append), heading "### DEBT-<n>: <title>", then lines Context (PR, finding id),
   Risk, Recovery (named, with file:line), Decision ("accepted under {rid}, no escalation"), and a
   "- **Status**: accepted" line (every TD entry needs a Status line). Commit that file by name
   (git add -- <file>, git commit -m ... -- <file>), never git add -A. Cite the debt id in the reply.
   The triage marker still names only the ids you answered, the lane clears only those ids.
"""
    return text


def brief_text(ctx):
    """The first message of the fix session. ASCII only."""
    waits = ctx.get("waits_on") or []
    rebase = ""
    if waits:
        rebase = f"""
Rebase on main: an earlier session gave up on this head because the open PRs {_nums(waits)} had to merge
first. They have now merged. Rebase this branch on origin/main (resolve conflicts, keep main's side for
anything this PR does not own), run the tests, push with --force-with-lease, then follow step 5. The new
head gets a new review. A high that a triage reply on the previous head refuted with evidence may be
refuted again on the new head only after you re-check that evidence still holds (code unchanged apart
from the rebase, live state re-read where the refutation relied on it).
"""
    direction = ""
    reask = ""
    if ctx.get("direction"):
        dd = ctx["direction"]
        direction = f"""
The owner's direction (chosen in the decision card for this head): {dd.get("label")}.
{dd.get("effect") or ""}
Do exactly that. It is the owner's decision, so do not re-open the question. If it cannot be done safely,
give up with the reason.
"""
    if ctx.get("reask"):
        reask = f"""
Your last FIX DECISION was rejected: {ctx["reask"].get("error")}.
Re-ask. Re-read the live PR, do not repeat work already pushed, and write the FIX DECISION again with
{MIN_OPTIONS} to {MAX_OPTIONS} options (merge or drop options so the recommended one and the one the owner would
most likely pick both stay), then the FIX RESULT line with gave-up. This is re-ask {ctx["reask"].get("n")} of {MAX_REASK}.
"""
    skill = build_skill(ctx.get("target") or "")
    skill_line = f"\nand skill {skill} for how to change the code" if skill else ""
    if ctx.get("catalog"):
        learn = f"""Learning loop: for every REAL finding you fixed that the build skill's finding catalog would not
   have caught, write a line CATALOG ADD: [<A-E>] <rule>. Why: #{ctx["pr"]} <finding id> <one line>
   (A infrastructure, B identity, C runtime, D CI, E docs). Never a rule that weakens a check."""
    else:
        learn = """Learning loop: when the fix taught a rule the build skill does not hold yet, say so in the
   FIX RESULT sentence. Write no CATALOG ADD lines for this repo."""
    return f"""Auto-fix (launched by the own-PR auto-merge lane). Follow skill own-pr-autofix exactly{skill_line}.

PR: {ctx["repo"]} #{ctx["pr"]} - {ctx["title"]}
URL: {ctx["url"]}
Branch: {ctx["branch"]}
Head: {ctx["head"]}
Author: the owner (this is one of the owner's own PRs)
Problem: {ctx["problem"]}
Lane reason: {ctx["reason"]}
Attempt: {ctx["attempt"]} of {ctx["max"]} in 24 h
{rebase}{direction}{reask}{target_notes(ctx)}
What to do:
1. Re-read the live PR first (gh pr view, gh pr checks, the newest PR review comment). If the head moved
   or the problem is gone, write the result "nothing-to-do" and stop.
2. Fix the problem on this branch only, from a fresh worktree of the PR head. Red checks: read the failing
   logs (gh run view --log-failed) and fix the cause. Merge conflict: rebase on origin/main, resolve, re-run
   the tests, push with --force-with-lease. Untriaged high findings: fix every real one and push. When every
   remaining high is refuted or accepted, post ONE triage reply in the owner's first-person voice that ends with
   <!-- triage:<current head sha> <ids answered> --> naming only the review table ids that reply refutes
   or accepts (for example <!-- triage:abc1234 H1 H3 -->). The lane clears only the ids named, and a bare
   marker clears nothing. Never put the marker on a reply that promises a fix.
{ctx.get("residual") or ""}   Blocking findings and review threads: fix them, and resolve threads whose code is fixed.
3. {ctx["gates"]} Fix every real finding of the round in ONE push, then triage the rest in ONE
   reply. Commit as {commit_identity(ctx["repo"], ctx.get("target") or "")}, no tool attribution.
   {ctx["round"]}
4. Never merge, never approve, never add or remove labels, never mark the PR draft, never weaken a test,
   a check, a workflow or a policy to get green, never touch any other PR. The lane merges once it clears.
5. After a push, wait for the new head's checks and review. If a new fixable problem appears, fix it in this
   same session. Stop after 3 pushes.
6. If it needs a decision, an outside dependency, or a change you cannot make safely, stop. Post nothing on
   the code host and give up with the reason. When the cause is other open PRs that must merge first, write the
   line FIX WAITS ON: #<n>, #<m> to the result file before the FIX RESULT line. The lane then rebases
   this PR on its own once all of them merge.
   When it needs the owner's DECISION (risk acceptance, design choice, intended delete, broad grant), also
   write ONE line before the FIX RESULT line, valid JSON on a single line:
   FIX DECISION: {{"question": "...", "recommend": "A", "options": [
     {{"id": "A", "label": "short verb phrase", "action": "fix", "effect": "exactly what the fix session will change"}},
     {{"id": "B", "label": "Accept the risk", "action": "override", "effect": "what merging as is means",
      "reply": "the triage reply to post, first person, ASCII, no semicolons, no em dashes, no marker"}},
     {{"id": "C", "label": "Hold it", "action": "hold", "effect": "adds do-not-merge"}}]}}
   2 to 4 options. action is fix (a session does it), override (applies the override label and posts the
   reply, only for review findings) or hold. Recommend the option that serves secure by default.
   When the Lane reason above lists several rules ('needs me: a, b, c'), an override option signs off only the
   rules the card names. Name every rule id of the lane reason verbatim in the question or in that option's
   effect and say what merging as is grants. A rule the card does not name stays on the owner's Needs me list
   after the click.
7. {learn}
8. Last step, always: write exactly one line to {ctx["result_path"]}
   FIX RESULT: <fixed|triaged|gave-up|nothing-to-do> - <one plain sentence>
"""


# ---------------------------------------------------------------------------- runtime adapters


class NullRuntime:
    """No agent runtime: nobody is ever busy and a launch is only recorded (pid -1), so the lane state shows what would
    have started. The default until a consumer plugs a runtime in."""

    def busy_session(self, repo, number, branch, now):
        return None

    def launch(self, brief_path, name, skills, budget_s, log_path):
        return -1

    def finished_sessions(self, now):
        return []

    def archive(self, ids):
        return []


class HermesRuntime:
    """Reference adapter for the Hermes agent runtime: a session is `hermes chat --continue <name> --query-file <brief>`
    started detached; a busy session and the finished ones are read from the runtime's session database (read only);
    archiving goes through the runtime's own session store. Parameters (environment): HERMES_BIN, HERMES_AGENT_DIR,
    OWNPR_STATE_DB (default <agent home>/state.db), OPSCENTER_AGENT_HOME, AUTOFIX_WORKDIR (cwd of a session)."""

    def __init__(self):
        home = Path(os.environ.get("OPSCENTER_AGENT_HOME") or Path.home() / ".opscenter" / "agent")
        self.hermes = os.environ.get("HERMES_BIN") or shutil.which("hermes") or "hermes"
        self.state_db = Path(os.environ.get("OWNPR_STATE_DB") or home / "state.db")
        self.agent_dir = Path(os.environ.get("HERMES_AGENT_DIR") or home / "hermes-agent")
        self.py = str(self.agent_dir / "venv" / "bin" / "python")
        self.cwd = os.environ.get("AUTOFIX_WORKDIR") or str(home)

    def busy_session(self, repo, number, branch, now):
        """(id, title) of a live interactive session already working this PR, else None. Live = not ended and active in the
        last BUSY_WINDOW_S. Working it = a message or tool call in the last BUSY_MENTION_S names the PR URL path or its
        branch. Cron runs and the fixer's own sessions do not count. A database read error counts as nobody."""
        needles = [f"%{repo.split('/')[-1]}/pull/{number}%"]
        if branch and len(branch) >= 8:
            needles.append(f"%{branch}%")
        since = now.timestamp() - BUSY_WINDOW_S
        try:
            con = sqlite3.connect(f"file:{self.state_db}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error:
            return None
        try:
            rows = con.execute(
                "SELECT s.id, COALESCE(s.title, '') FROM sessions s WHERE s.ended_at IS NULL "
                "AND (COALESCE(s.last_activity_at, s.started_at) > ? "
                "OR EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id AND m.timestamp > ?)) "
                "AND s.source != 'cron' AND s.id NOT LIKE 'cron_%' AND COALESCE(s.title, '') NOT LIKE 'Auto-fix %' "
                "ORDER BY COALESCE(s.last_activity_at, s.started_at) DESC",
                (since, since),
            ).fetchall()
            for sid, title in rows:
                # A session about ANOTHER PR of this repo often names this one (a dependency, a shared failure).
                m = re.search(r"\bPR #(\d+)\b", title)
                if (
                    m
                    and int(m.group(1)) != int(number)
                    and repo.split("/")[-1].lower() in title.lower()
                ):
                    continue
                for nd in needles:
                    hit = con.execute(
                        "SELECT 1 FROM messages WHERE session_id = ? AND timestamp > ? "
                        "AND (content LIKE ? OR tool_calls LIKE ?) LIMIT 1",
                        (sid, now.timestamp() - BUSY_MENTION_S, nd, nd),
                    ).fetchone()
                    if hit:
                        return sid, title
        except sqlite3.Error:
            return None
        finally:
            con.close()
        return None

    def launch(self, brief_path, name, skills, budget_s, log_path):
        """Start the session fully detached so the gate script never waits on it (double fork through /bin/sh)."""
        argv = [
            self.hermes,
            "chat",
            "--continue",
            name,
            "--create-if-missing",
            "--in",
            self.cwd,
            "--query-file",
            str(brief_path),
            "--oneshot",
            "-Q",
            "-s",
            ",".join(skills),
            "--pass-session-id",
            "--run-budget",
            str(int(budget_s)),
        ]
        env = dict(os.environ)
        for k in list(env):
            if k.startswith(
                (
                    "OPRG_",
                    "OWNPR_",
                    "HERMES_CRON",
                    "_HERMES_CRON",
                    "HERMES_SESSION",
                    "HERMES_UI_SESSION",
                )
            ):
                env.pop(
                    k
                )  # the session must see the real lanes and run as its own session, not the cron's
        sh = subprocess.run(
            ["/bin/sh", "-c", 'nohup "$@" >>"$LOGF" 2>&1 </dev/null & echo $!', "sh"] + argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=20,
            start_new_session=True,
            close_fds=True,
            env=dict(env, LOGF=str(log_path)),
            cwd=self.cwd,
        )
        try:
            return int(sh.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise RuntimeError(
                f"fix session did not start: rc={sh.returncode} {sh.stderr.strip()[:200]}"
            ) from None

    def finished_sessions(self, now):
        """Ids of auto-fix sessions that are done and still in the session list (ended, no live turn lease, quiet for
        ARCHIVE_QUIET_S). A database read error returns nothing."""
        try:
            con = sqlite3.connect(f"file:{self.state_db}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error:
            return []
        try:
            rows = con.execute(
                "SELECT s.id FROM sessions s WHERE s.title LIKE 'Auto-fix %' AND s.ended_at IS NOT NULL "
                "AND COALESCE(s.archived, 0) = 0 AND COALESCE(s.last_activity_at, s.ended_at) < ? "
                "AND NOT EXISTS (SELECT 1 FROM session_turn_leases l WHERE l.conversation_id = s.id AND l.expires_at > ?) "
                "ORDER BY s.ended_at",
                (now.timestamp() - ARCHIVE_QUIET_S, now.timestamp()),
            ).fetchall()
        except sqlite3.Error:
            return []
        finally:
            con.close()
        return [r[0] for r in rows]

    def archive(self, ids):
        code = (
            "import sys\nfrom pathlib import Path\nfrom hermes_state import SessionDB\n"
            "db = SessionDB(db_path=Path(sys.argv[1]))\nfor sid in sys.argv[2:]:\n"
            "    print(sid, db.set_session_archived(sid, True))\n"
        )
        try:
            res = subprocess.run(
                [self.py, "-c", code, str(self.state_db)] + list(ids),
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.agent_dir),
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if res.returncode != 0:
            return []
        return [ln.split()[0] for ln in res.stdout.splitlines() if ln.endswith(" True")]


RUNTIME = NullRuntime()


def set_runtime(rt):
    """Plug in the agent runtime (see the header)."""
    global RUNTIME
    RUNTIME = rt


def busy_session(repo, number, branch, now):
    return RUNTIME.busy_session(repo, number, branch, now)


def _gate_text(target):
    """The pre-push gate step of a brief: the consumer's gate commands for a build target, else the repo's own tests."""
    if not is_build_target(target):
        return "Run the repo's tests and linters locally for what you touched before every push."
    pre = os.environ.get("AUTOFIX_PREFLIGHT_CMD", "")
    rev = os.environ.get("AUTOFIX_REVIEW_CMD", "")
    if not pre:
        return "Run the repo's tests and linters locally for what you touched before every push."
    text = (
        "Before every push run the pre-push gate and fix what it reports (exit 0 pass, 1 findings printed above,\n"
        "   2 an environment problem, which counts as a failure):\n"
        f"   {pre.format(target=target, worktree='<your worktree>')}\n"
    )
    if rev:
        text += (
            "   Before the push also run the independent local review on the combined change (max 3 rounds):\n"
            f"   {rev.format(target=target, worktree='<your worktree>')}\n"
            "   Fix every real high, refute a wrong one with a REFUTED line. Run it BEFORE the push, never after."
        )
    return text


def consider(
    target, tag, repo, self_login, pr, status, reason, frec, cfg, workdir, now, others=None
):
    """Decide for one of the owner's PRs on this lane pass. Mutates frec (persists across heads).
    Returns a line to print (only when the auto-fix gives up) or None."""
    acfg = dict(DEFAULTS)
    acfg.update(cfg.get("autofix") or {})
    head = pr["headRefOid"]
    author = ((pr.get("author") or {}).get("login")) or self_login
    if not acfg["enabled"] or author != self_login:
        return None
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    track_push(frec, target, repo, head, now_iso)
    run = frec.get("running")
    if (
        run
        and run_alive(run)
        and now.timestamp() - _ts(run.get("started")) > int(acfg["run_budget_s"]) + 900
    ):
        try:
            os.killpg(
                os.getpgid(int(run["pid"])), 15
            )  # past its budget: stop it, then treat it as ended below
        except (OSError, ValueError):
            with contextlib.suppress(OSError, ValueError):
                os.kill(int(run["pid"]), 15)
        run["killed"] = True
    if run and (run.get("killed") or not run_alive(run)):
        outcome, text = read_result(run.get("result_path", ""))
        if not outcome and run.get("killed"):
            outcome, text = "gave-up", "the session ran past its time budget and was stopped"
        run.update({"ended": now_iso, "outcome": outcome or "no-result", "text": text})
        if outcome == "gave-up":
            w = waits_on(text, pr.get("number"), run.get("result_path"))
            if w:
                run["waits_on"] = w
            dec, dec_err = check_decision(run.get("result_path", ""))
            if dec and not w:
                run["decision"] = dec
            elif dec_err and not w:
                run["decision_error"] = dec_err
        added = add_to_catalog(run.get("result_path", ""), now_iso, target)
        if added:
            run["catalog_added"] = added
        frec.setdefault("history", []).append(run)
        frec["history"] = frec["history"][-10:]
        frec.pop("running", None)
        if (
            outcome == "gave-up"
            and run.get("decision_error")
            and int(run.get("reask") or 0) < MAX_REASK
        ):
            # Return the fixer the error and have it re-ask (1.17). Not a give-up yet.
            frec["reask"] = {
                "head": head,
                "error": run["decision_error"],
                "n": int(run.get("reask") or 0) + 1,
                "at": now_iso,
            }
        elif outcome == "gave-up":
            frec["gave_up"] = {
                "head": run["head"],
                "why": text or "the session could not fix it",
                "at": now_iso,
            }
            if run.get("waits_on"):
                frec["gave_up"]["waits_on"] = run["waits_on"]
            if run.get("decision"):
                frec["gave_up"]["decision"] = run["decision"]
                # The session reads the live PR and may have pushed before it stopped, so its
                # decision is about the head the PR has now, not the head it was started on.
                frec["gave_up"]["head"] = head
    # Pipeline v2: the lane found that the plan destroys only objects other open PRs of mine
    # declare. Same machinery as an give-up, so it re-arms once they all merge.
    lw = LANE_WAITS_RE.match(reason or "") if status == "held" else None
    if lw and not frec.get("running"):
        nums = sorted({int(x) for x in re.findall(r"#(\d+)", lw.group(1))} - {int(pr["number"])})
        g = frec.get("gave_up") or {}
        if nums and (g.get("head") != head or g.get("waits_on") != nums):
            frec["gave_up"] = {
                "head": head,
                "why": reason,
                "waits_on": nums,
                "at": now_iso,
                "source": "lane",
            }
            frec.pop("reported", None)
    problem = problem_of(status, reason, target)
    # Pipeline v2: the owner's choice in the decision card for this head starts a directed fix at once.
    direction = None
    if status == "held" and not frec.get("running"):
        dr = read_direction(workdir, pr["number"], head)
        if dr and dr.get("action") == "fix" and frec.get("direction_used") != dr.get("at"):
            direction = dr
            frec.pop("gave_up", None)
            frec.pop("reported", None)
            problem = "directed-fix"
    ask = frec.get("reask")
    if ask and ask.get("head") != head:
        frec.pop("reask", None)  # the PR moved on, the question was about an older head
        ask = None
    reask = ask if (ask and status == "held" and problem and not frec.get("running")) else None
    if frec.get("running"):
        return None
    rearm = frec.get("rearm")
    if rearm and rearm.get("head") != head:
        frec.pop("rearm", None)
        rearm = None
    gave = frec.get("gave_up")
    if gave and gave.get("head") == head and "waits_on" not in gave:
        gave["waits_on"] = waits_on(gave.get("why"), pr.get("number"))  # give-ups recorded before
    # a give-up that named other open PRs as the cause waits for them, whatever the lane
    # shows meanwhile (red checks, or the destroy guard read as a plan-destroy sign-off). Once every
    # one merged, the same head re-arms with a rebase on main. One closed unmerged turns it back into
    # a plain give-up. Deliberate holds (draft, label, freeze) and running checks never re-arm.
    rearmable = status == "held" and not any(x in (reason or "").lower() for x in REARM_NEVER)
    if gave and gave.get("head") == head and gave.get("waits_on") and rearmable:
        states = {n: pr_state(repo, n) for n in gave["waits_on"]}
        closed = [n for n, s in states.items() if s == "CLOSED"]
        if closed:
            gave["waits_on"] = []
            gave["why"] = (
                f"it waited on {_nums(sorted(states))}, but {_nums(closed)} closed without merging"
            )
        elif all(s == "MERGED" for s in states.values()):
            frec.pop("gave_up", None)
            frec.pop("reported", None)
            rearm = {"head": head, "waits_on": sorted(states), "at": now_iso}
            frec["rearm"] = rearm
            gave = None
        elif problem:
            return _report_once(frec, tag, pr, f"auto-fix gave up: {gave['why']}")
        else:
            return None
    if rearm and rearmable and not direction:
        problem = "rebase-on-main"
    if not problem:
        frec.pop("deferred", None)
        frec.pop("batched", None)
        # Cleared or not fixable here. A give-up on an older head no longer applies.
        if frec.get("gave_up", {}).get("head") not in (None, head):
            frec.pop("gave_up", None)
        return None
    if gave and gave.get("head") == head and not direction:
        return _report_once(frec, tag, pr, f"auto-fix gave up: {gave['why']}")
    if gave and gave.get("head") != head:
        frec.pop("gave_up", None)
    hist = frec.get("history") or []
    done_here = [h for h in hist if h.get("head") == head and h.get("problem") == problem]
    if rearm:
        done_here = [h for h in done_here if _ts(h.get("started")) >= _ts(rearm.get("at"))]
    if direction or reask:
        done_here = []  # the owner's click, or the fixer's rejected decision, authorizes one more session on this head
    if done_here:
        last = done_here[-1]
        if (
            last.get("outcome") in ("fixed", "triaged", "nothing-to-do")
            and now.timestamp() - _ts(last.get("ended")) < 600
        ):
            return None  # give the lane a few minutes to see the push or the triage reply
        crashed = all(h.get("outcome") == "no-result" for h in done_here)
        if not (crashed and len(done_here) < 2):  # one retry when a session died without a result
            still = PLAIN.get(problem, problem)
            if last.get("outcome") == "gave-up":
                why = last.get("text") or f"the session could not fix it and {still}"
            elif crashed:
                why = f"two fix sessions ended without a result and {still}"
            else:
                said = f" (the session said: {last['text']})" if last.get("text") else ""
                why = f"{still} after a fix session{said}"
            frec["gave_up"] = {"head": head, "why": why, "at": now_iso}
            return _report_once(frec, tag, pr, f"auto-fix gave up: {why}")
    recent = [h for h in hist if now.timestamp() - _ts(h.get("started")) < 86400]
    if len(recent) >= int(acfg["max_sessions_per_day"]) and not (direction or reask):
        why = f"{len(recent)} auto-fix sessions in 24 h and it is still held ({reason})"
        frec["gave_up"] = {"head": head, "why": why, "at": now_iso}
        return _report_once(frec, tag, pr, f"auto-fix gave up: {why}")
    # held files were pushed a few minutes ago. Another push now would cost a second plan
    # approval, so wait for the rest of the round's findings (the next session fixes them all at once).
    # The owner's own directed-fix click never waits, and neither does a fix that is the only thing blocking.
    wait = (
        batch_wait_s(frec, now, others)
        if (is_build_target(target) and not (direction or reask))
        else 0
    )
    if wait:
        frec["batched"] = {
            "head": head,
            "problem": problem,
            "since": (frec.get("batched") or {}).get("since") or now_iso,
            "wait_s": wait,
        }
        return None
    frec.pop("batched", None)
    busy = busy_session(repo, pr["number"], pr.get("headRefName"), now)
    if busy:
        # Someone is already on it (usually the session that opened the PR). Re-checked every
        # pass, so the fix starts the first pass after that session goes quiet.
        frec["deferred"] = {
            "head": head,
            "problem": problem,
            "session": busy[1] or busy[0],
            "since": frec.get("deferred", {}).get("since") or now_iso,
        }
        return None
    frec.pop("deferred", None)
    workdir.mkdir(parents=True, exist_ok=True)
    stem = f"{pr['number']}-{head[:8]}-{problem}"
    result_path = workdir / f"{stem}.result"
    brief_path = workdir / f"{stem}.brief.txt"
    log_path = workdir / f"{stem}.log"
    ctx = {
        "target": target,
        "repo": repo,
        "pr": pr["number"],
        "title": pr.get("title") or "",
        "url": pr.get("url") or "",
        "branch": pr.get("headRefName") or "",
        "head": head,
        "problem": problem,
        "reason": reason,
        "attempt": len(recent) + 1,
        "max": acfg["max_sessions_per_day"],
        "result_path": str(result_path),
        "waits_on": (rearm or {}).get("waits_on") or [],
        "direction": direction,
        "reask": reask,
        "residual": residual_rule_text(cfg),
        "round": ROUND_RULE if is_build_target(target) else "",
        "gates": _gate_text(target),
        "catalog": catalog_path(target) is not None,
    }
    brief_path.write_text(brief_text(ctx))
    with contextlib.suppress(OSError):
        result_path.unlink()
    name = f"Auto-fix {repo.split('/')[-1]} PR #{pr['number']} {head[:8]}"
    skills = common_skills() + ([build_skill(target)] if build_skill(target) else [])
    if os.environ.get("OWNPR_FIX_SPAWN") == "record":
        pid = -1
    else:
        pid = RUNTIME.launch(brief_path, name, skills, int(acfg["run_budget_s"]), log_path)
    argv = ["launch", name, str(brief_path), ",".join(skills)]
    if reask:
        frec.pop("reask", None)
    if direction:
        frec["direction_used"] = direction.get("at")
    frec["running"] = {
        "pid": pid,
        "head": head,
        "problem": problem,
        "started": now_iso,
        "name": name,
        "brief": str(brief_path),
        "result_path": str(result_path),
        "log": str(log_path),
        "argv": argv,
    }
    if reask:
        frec["running"]["reask"] = reask["n"]
    return None


def finished_sessions(now):
    return RUNTIME.finished_sessions(now)


def archive_finished(now):
    """Archive every finished auto-fix session so they never pile up in the session list. Runs once per lane pass.
    Returns the archived ids. Never raises."""
    try:
        ids = RUNTIME.finished_sessions(now)
        if not ids or os.environ.get("OWNPR_ARCHIVE") == "record":
            return ids
        return RUNTIME.archive(ids)
    except Exception:  # noqa: BLE001 - housekeeping never breaks a lane pass
        return []


def _nums(nums):
    """#1, #2 and #3"""
    tags = [f"#{n}" for n in nums]
    return tags[0] if len(tags) == 1 else ", ".join(tags[:-1]) + " and " + tags[-1]


def _report_once(frec, tag, pr, text):
    key = f"{pr['headRefOid']}:{text[:60]}"
    if frec.get("reported") == key:
        return None
    frec["reported"] = key
    return f"{tag} PR #{pr['number']} {pr.get('title')}: {text} - {pr.get('url')}"
