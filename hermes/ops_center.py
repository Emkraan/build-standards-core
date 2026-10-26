#!/usr/bin/env python3
"""Apply a core release to a local ops center at once, behind a local gate.

An ops center is an app only its operator uses. It has no pull request gate worth waiting on, so the
nightly is the gate (README, "Local alternative"). This module is that gate, called by
hermes/nightly.py for every consumer in mode "direct":

  1. Read the pin from the committed default branch. Equal to the release: nothing to do.
  2. Make an isolated git worktree of the committed default branch. The working tree is never read,
     so uncommitted work cannot decide the verdict and is never touched.
  3. Run the gate on the CURRENT pin. A failure here is the consumer's: the update is held and the
     failure reported as the consumer's, never blamed on the release.
  4. Sync the release in the worktree and run the gate again.
  5. Only when both runs pass: commit the pin, the copies and the overlay scripts by name, push if a
     remote exists, then move the local default branch to the new commit. Where the remote refuses a
     direct push (a protected branch), push a branch, open a pull request and merge it at once.
     A push the repo's own pre-push hook refuses is not retried another way: the failure line names
     the hook and the two fixes (an overlay-only allowance in the hook, or mode workflow).
  6. Any failure discards the worktree. The default branch and the pin stay as they were.

An ops center whose source is a repo with its own CI gate (a remote that requires status checks, or
a repo with its own pre-push guard) stays in the apply-at-once class, but the release lands as a pull
request through that gate instead of a write to the deploy checkout. The entry selects it with
"apply_via": "pr" ("direct" forces the old path; with neither key the guard is detected). Then step 2
works from the remote's default branch, and step 5 becomes: push a branch, open the pull request,
wait for the repo's own checks on that head with the worktree's scripts/core-ci.py wait-checks, and
merge it at once with scripts/merge-pr.py --match-head-commit. The owner is never waited for, and
the deploy checkout is never written: the repo's own deploy job takes the merge. A failure or a
timeout closes the pull request, deletes the branch and leaves the pin unchanged, reported once per
kind like every other failure ("pr_timeout_min" bounds the wait, default 60).

The gate is the overlay's own checks (core sync, exceptions, UI lint, script lint), then the commands
the consumer names in standards-local/parameters.md: "Gate typecheck", "Gate build" and "Gate verify"
(its own verify command). A step with no command is skipped. Commands are split like a shell would
and run without one, from the repo root of the worktree. The clone's node_modules is linked into the
worktree when it exists, and so is the overlay folder's own node_modules when the overlay is a
subfolder that has one, so a typecheck or build does not need a fresh install.

Every push runs from the clone, never from the gate worktree: git hands a hook GIT_DIR, and inside a
worktree that is <clone>/.git/worktrees/<name>. A pre-push hook (or the tests it runs) that calls
`git init` or `git config` with that GIT_DIR in its environment writes core.bare = true into the
clone's shared config, which then breaks `git pull` in the clone. Pushed from the clone, the hook runs as
it would for a push by hand there (in the clone's work tree, with no worktree GIT_DIR), so it can no
longer flip the flag; the gate has already run on the worktree's tree before the push. Commands the nightly runs get no GIT_DIR, GIT_WORK_TREE,
GIT_INDEX_FILE or GIT_COMMON_DIR from its own environment (nightly.sh). In any case a guard reads
core.bare before and after each apply: true on a clone that has a work tree is set back to false and
reported once in that run.

While the pull request path waits for the repo's own checks, wait-checks prints a progress line at
most every 5 minutes (done, pending, failed); this module streams those lines to the nightly's output
as they come, so a long wait is visible.

Failures are reported once per kind: the kind is kept in a state file and the nightly prints a
problem only when it differs from the last one, until a clean run clears it. Python 3.9, stdlib only.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path
from typing import Callable

Sh = Callable[..., "tuple[int, str]"]

GATE_PARAMS = (("typecheck", "Gate typecheck"), ("build", "Gate build"), ("verify", "Gate verify"))
OVERLAY_CHECKS = (
    ("core sync", "scripts/check-core-sync.py", []),
    ("exceptions", "scripts/check-exceptions.py", []),
    ("UI lint", "lint-core/ui_lint.py", []),
    ("script lint", "lint-core/script_lint.py", []),
)
# What a sync writes. Committed by name so nothing else in the worktree can ride along.
COMMIT_PATHS = (
    "standards-core",
    "tokens-core",
    "lint-core",
    "kit-core",
    "scripts",
    "standards.lock",
    "standards-local/parameters.md",
)
# The template workflows a sync refreshes (corehash.WORKFLOWS), at the root of the repo, not the overlay.
# Committed by name too, so the sync never carries any other workflow.
WORKFLOW_PATHS = tuple(
    f".github/workflows/{n}"
    for n in ("core-ci.yml", "core-drift.yml", "core-update.yml", "lint-sweep.yml")
)
VIAS = ("pr", "direct")


def sync_notes(out: str) -> str:
    """The lines of a sync's output a person must act on or see: refreshed workflows and the old -> new
    required-check names."""
    keep, inside = [], False
    for line in out.splitlines():
        if line.startswith("workflows: refreshed") or line.startswith("required checks:"):
            keep.append(line)
            inside = line.startswith("required checks:")
        elif inside and line.startswith("  ") and " -> " in line:
            keep.append(line)
        else:
            inside = False
    return "\n".join(keep)


def gate_params(base: Path) -> dict:
    """The consumer's own gate commands from standards-local/parameters.md (empty cell: no step)."""
    out: dict = {}
    sheet = base / "standards-local" / "parameters.md"
    if not sheet.is_file():
        return out
    for line in sheet.read_text(encoding="utf8").splitlines():
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not cells[1]:
            continue
        for key, label in GATE_PARAMS:
            if cells[0].lower().startswith(label.lower()):
                out[key] = cells[1]
    return out


def gate_steps(root: Path, overlay: str) -> list:
    """Every gate step as (label, argv, cwd), in order, for the tree at root."""
    base = root / overlay if overlay else root
    steps = []
    for label, rel, extra in OVERLAY_CHECKS:
        if (base / rel).is_file():
            steps.append((label, [sys.executable, rel, *extra], base))
    for key, label in GATE_PARAMS:
        cmd = gate_params(base).get(key)
        if cmd:
            steps.append((label.split(" ", 1)[1], shlex.split(cmd), root))
    return steps


def run_gate(root: Path, overlay: str, sh: Sh) -> tuple[bool, str]:
    for label, argv, cwd in gate_steps(root, overlay):
        rc, out = sh(argv, cwd=cwd, timeout=1800)
        if rc != 0:
            tail = " | ".join(out.splitlines()[-3:])[-300:]
            return False, f"{label} failed (exit {rc}): {tail}"
    return True, ""


def target_paths(root: Path, overlay: str) -> list:
    """The destinations in the overlay's targets.map, relative to the repo root: the copies a sync writes
    outside the overlay (for example a UI package's token stylesheet), committed with the sync. A
    destination outside the repo is skipped."""
    base = (root / overlay) if overlay else root
    f = base / "targets.map"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text(encoding="utf8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            dst = (base / line.split("=", 1)[1].strip()).resolve()
            try:
                out.append(str(dst.relative_to(root.resolve())))
            except ValueError:
                continue
    return out


TRANSIENT = (
    "unexpected disconnect",
    "remote end hung up",
    "rpc failed",
    "timed out",
    "early eof",
    "connection reset",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
    "could not resolve host",
)


def push(sh: Sh, clone: Path, *args: str, attempts: int = 3, pause: float = 10) -> tuple[int, str]:
    """git push from the clone with a large HTTP buffer, retried on a transient network failure. A
    rejection (a hook, a failed lease, a protected branch) is never retried."""
    rc, out = 1, ""
    for i in range(attempts):
        rc, out = sh(["git", "-C", str(clone), "-c", "http.postBuffer=524288000", "push", *args])
        if rc == 0 or not any(t in out.lower() for t in TRANSIENT) or i == attempts - 1:
            return rc, out
        time.sleep(pause)
    return rc, out


def default_branch(clone: Path, sh: Sh) -> str:
    rc, out = sh(["git", "-C", str(clone), "symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
    if rc == 0 and out.startswith("origin/"):
        return out[len("origin/") :]
    for name in ("main", "master"):
        if (
            sh(["git", "-C", str(clone), "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"])[
                0
            ]
            == 0
        ):
            return name
    rc, out = sh(["git", "-C", str(clone), "symbolic-ref", "--short", "HEAD"])
    return out if rc == 0 and out else "main"


def pin_at(clone: Path, branch: str, overlay: str, sh: Sh) -> str:
    path = f"{overlay}/standards.lock" if overlay else "standards.lock"
    rc, out = sh(["git", "-C", str(clone), "show", f"{branch}:{path}"])
    if rc != 0:
        raise RuntimeError(f"cannot read {path} on {branch}: {out[-200:]}")
    for line in out.splitlines():
        if line.startswith("ref="):
            return line[4:].strip()
    raise RuntimeError(f"{path} has no ref= line")


class State:
    """The last failure kind per consumer, so a failure is reported once until a clean run."""

    def __init__(self, directory: Path, repo: str):
        self.file = directory / ("direct__" + re.sub(r"[^A-Za-z0-9_.-]", "__", repo) + ".json")

    def last(self) -> str:
        try:
            return json.loads(self.file.read_text(encoding="utf8")).get("kind", "")
        except (OSError, ValueError):
            return ""

    def set(self, kind: str) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps({"kind": kind}) + "\n", encoding="utf8")

    def clear(self) -> None:
        with contextlib.suppress(OSError):
            self.file.unlink()


def bare_flag_restore(clone: Path, sh: Sh) -> bool:
    """True when the clone has a work tree (a .git directory) but its config says core.bare = true; the
    flag is then set back to false. Read and written with --file, so no GIT_DIR and no worktree can point
    the command at another repository."""
    cfg = clone / ".git" / "config"
    if not cfg.is_file():
        return False
    rc, out = sh(["git", "config", "--file", str(cfg), "--get", "core.bare"])
    if rc != 0 or out.strip().lower() != "true":
        return False
    sh(["git", "config", "--file", str(cfg), "core.bare", "false"])
    return True


def apply(c: dict, latest: str, sh: Sh, state_dir: Path, check: bool = False) -> dict:
    """Apply release `latest` to the ops center described by consumer entry c.

    Returns {"status", "kind", "message", "report", "bare"}. status is current, applied, would, held or
    failed. report says whether the nightly should print the message as a problem (a new kind). bare is
    "" or the one line saying core.bare was found true on the clone and set back to false."""
    if not c.get("path"):
        raise RuntimeError('mode "direct" needs "path", the local clone')
    clone = Path(c["path"]).expanduser()
    when = []
    if not check and bare_flag_restore(clone, sh):
        when.append("before")
    try:
        r = _apply(c, clone, latest, sh, state_dir, check)
    finally:
        if not check and bare_flag_restore(clone, sh):
            when.append("after")
    r["bare"] = (
        f"ui {c['repo']}: core.bare was true on the clone {clone} ({' and '.join(when)} the apply) and is "
        f"set back to false; a hook or tool that runs git with a worktree's GIT_DIR sets it"
        if when
        else ""
    )
    return r


def _apply(c: dict, clone: Path, latest: str, sh: Sh, state_dir: Path, check: bool) -> dict:
    repo, overlay = c["repo"], c.get("overlay", "standards-overlay")
    state = State(state_dir, repo)

    def fail(status: str, kind: str, msg: str) -> dict:
        new = state.last() != kind
        if not check:
            state.set(kind)
        return {"status": status, "kind": kind, "message": msg, "report": new}

    branch = default_branch(clone, sh)
    via = apply_via(c, clone, branch, sh)
    remotes = sh(["git", "-C", str(clone), "remote"])[1].split()
    base_ref = branch
    if via == "pr":
        if not remotes:
            return fail(
                "failed",
                "pr-remote",
                f'ui {repo}: "apply_via": "pr" needs a remote, the clone has none',
            )
        sh(["git", "-C", str(clone), "fetch", "--quiet", remotes[0], branch])
        base_ref = f"{remotes[0]}/{branch}"
    pinned = pin_at(clone, base_ref, overlay, sh)
    if pinned == latest:
        return {"status": "current", "kind": "", "message": "", "report": False}
    if check:
        how = "by a pull request through the repo's own checks" if via == "pr" else "at once"
        return {
            "status": "would",
            "kind": "",
            "report": False,
            "message": f"ui {repo}: ops center behind ({pinned}, core is {latest}); would gate and apply {how}",
        }

    sh(["git", "-C", str(clone), "worktree", "prune"])
    wt = clone.parent / f"{clone.name}.core-gate"
    sh(["git", "-C", str(clone), "worktree", "remove", "--force", str(wt)])
    rc, out = sh(
        ["git", "-C", str(clone), "worktree", "add", "--quiet", "--detach", str(wt), base_ref]
    )
    if rc != 0:
        return fail("failed", "worktree", f"ui {repo}: worktree failed: {out[-200:]}")
    try:
        link_node_modules(clone, wt, overlay)
        ok, why = run_gate(wt, overlay, sh)
        if not ok:
            return fail(
                "held",
                "gate-current-pin",
                f"ui {repo}: the gate fails on the current pin {pinned}, so the update to {latest} is held "
                f"(the consumer's own failure, not the release's): {why}",
            )
        base = wt / overlay if overlay else wt
        rc, out = sh([sys.executable, "scripts/sync-core.py", latest], cwd=base)
        if rc != 0:
            return fail(
                "failed", "sync", f"ui {repo}: sync to {latest} failed, rolled back: {out[-300:]}"
            )
        ok, why = run_gate(wt, overlay, sh)
        if not ok:
            return fail(
                "failed",
                "gate-after-sync",
                f"ui {repo}: the gate fails after the sync to {latest}, rolled back, pin still {pinned}: {why}",
            )
        msg = f"chore(standards): sync core {latest}"
        notes = sync_notes(out)
        names = (
            [(f"{overlay}/{p}" if overlay else p) for p in COMMIT_PATHS]
            + list(WORKFLOW_PATHS)
            + target_paths(wt, overlay)
        )
        for rel in names:
            if (wt / rel).exists() or sh(["git", "-C", str(wt), "ls-files", "--", rel])[1]:
                sh(["git", "-C", str(wt), "add", "-A", "--", rel])
        extra = (
            [os.environ.get("CORE_COMMIT_ARGS", "")] if os.environ.get("CORE_COMMIT_ARGS") else []
        )
        rc, out = sh(["git", "-C", str(wt), *extra, "commit", "--quiet", "-m", msg])
        if rc != 0:
            return fail("failed", "commit", f"ui {repo}: commit failed, rolled back: {out[-200:]}")
        new = sh(["git", "-C", str(wt), "rev-parse", "HEAD"])[1]
        if via == "pr":
            kind, why = land_pr(c, clone, wt, base, branch, new, latest, remotes[0], sh, notes)
            if kind:
                return fail(
                    "failed",
                    kind,
                    f"ui {repo}: {why}, pull request closed and branch deleted, pin still {pinned}",
                )
            sh(["git", "-C", str(clone), "fetch", "--quiet", remotes[0], branch])
            state.clear()
            return {
                "status": "applied",
                "kind": "",
                "report": bool(why),
                "message": f"ui {repo}: ops center {pinned} -> {latest} by pull request, gate passed before and "
                f"after, the repo's own checks passed"
                + (f"; {why}" if why else "")
                + (f"\n{notes}" if notes else ""),
            }
        landed = land(clone, wt, branch, new, latest, repo, sh)
        if landed:
            return fail("failed", "push", f"ui {repo}: {landed}, rolled back, pin still {pinned}")
        state.clear()
        return {
            "status": "applied",
            "kind": "",
            "report": False,
            "message": f"ui {repo}: ops center {pinned} -> {latest}, gate passed before and after"
            + (f"\n{notes}" if notes else ""),
        }
    finally:
        sh(["git", "-C", str(clone), "worktree", "remove", "--force", str(wt)])


def link_node_modules(clone: Path, wt: Path, overlay: str) -> None:
    """Link the clone's node_modules into the worktree, at the root and, when the overlay is a subfolder
    with its own node_modules, at that subfolder too."""
    for rel in ("", overlay) if overlay else ("",):
        src, dst = clone / rel / "node_modules", wt / rel / "node_modules"
        if src.is_dir() and dst.parent.is_dir() and not dst.exists() and not dst.is_symlink():
            os.symlink(src, dst)


def apply_via(c: dict, clone: Path, branch: str, sh: Sh) -> str:
    """pr or direct. The entry's "apply_via" wins; without it, a repo with its own CI gate (a remote whose
    default branch requires status checks, or the repo's own pre-push guard) applies by pull request."""
    via = c.get("apply_via")
    if via:
        if via not in VIAS:
            raise RuntimeError(f"unknown apply_via {via!r} (known: {', '.join(VIAS)})")
        return via
    if not sh(["git", "-C", str(clone), "remote"])[1].split():
        return "direct"
    if local_push_guard(clone, sh) or "required_status_checks" in remote_push_guard(
        c["repo"], branch, sh
    ):
        return "pr"
    return "direct"


def land_pr(
    c: dict,
    clone: Path,
    wt: Path,
    base: Path,
    branch: str,
    new: str,
    latest: str,
    remote: str,
    sh: Sh,
    notes: str = "",
) -> tuple[str, str]:
    """Land the commit as a pull request through the repo's own checks and merge it at once.
    Returns ("", note) when merged (note is a merge-pr warning or ""), or (kind, reason) after the pull
    request was closed and its branch deleted. Pushes run from the clone (module docstring: core.bare)."""
    repo = c["repo"]
    pr_branch = f"chore/core-{latest}"
    timeout = int(c.get("pr_timeout_min", 60))
    number = ""

    def rollback(kind: str, why: str) -> tuple[str, str]:
        if number:
            sh(["gh", "pr", "close", number, "-R", repo, "--delete-branch"], cwd=wt)
        sh(["git", "-C", str(clone), "push", "--quiet", remote, "--delete", pr_branch])
        return kind, why

    rc, out = push(sh, clone, "--quiet", "-f", remote, f"{new}:refs/heads/{pr_branch}")
    if rc != 0:
        return rollback("pr-push", f"push of {pr_branch} failed: {out[-200:]}")
    rc, out = sh(
        [
            "gh",
            "pr",
            "create",
            "-R",
            repo,
            "--head",
            pr_branch,
            "--base",
            branch,
            "--title",
            f"chore(standards): sync core {latest}",
            "--body",
            f"Automated sync to core release {latest}. The local gate passed before and after the sync; "
            f"this pull request merges as soon as the repo's own checks pass."
            + (f"\n\n```\n{notes}\n```" if notes else ""),
        ],
        cwd=wt,
    )
    if rc != 0 and "already exists" not in out:
        return rollback("pr-open", f"pull request failed: {out[-200:]}")
    rc, out = sh(
        [
            "gh",
            "pr",
            "view",
            pr_branch,
            "-R",
            repo,
            "--json",
            "number,headRefOid",
            "--jq",
            "[.number, .headRefOid] | @tsv",
        ],
        cwd=wt,
    )
    number, head = (out.split("\t") + [""])[:2] if rc == 0 and "\t" in out else ("", "")
    if not number or head != new:
        return rollback(
            "pr-open",
            f"pull request for {pr_branch} not readable or not on {new[:12]}: {out[-150:]}",
        )
    ci = base / "scripts" / "core-ci.py"
    merge = base / "scripts" / "merge-pr.py"
    if not ci.is_file() or not merge.is_file():
        return rollback(
            "pr-checks", "scripts/core-ci.py or scripts/merge-pr.py missing after the sync"
        )
    rc, out = sh(
        [sys.executable, str(ci), "wait-checks", new, "--repo", repo, "--timeout", str(timeout)],
        cwd=wt,
        timeout=timeout * 60 + 300,
        echo=progress_printer(repo, number),
    )
    if rc != 0:
        tail = " | ".join(out.splitlines()[-2:])[-200:]
        return rollback("pr-checks", f"the repo's own checks on #{number} did not pass ({tail})")
    rc, out = sh(
        [sys.executable, str(merge), number, "-R", repo, "--match-head-commit", new], cwd=wt
    )
    if rc == 2:
        return rollback("pr-merge", f"merge of #{number} refused: {out[-200:]}")
    return "", (f"merge-pr: {out.splitlines()[-1][-200:]}" if rc != 0 and out else "")


def progress_printer(repo: str, number: str, out=None) -> Callable[[str], None]:
    """The line handler for a streamed wait-checks: its progress lines go to the nightly's output at once."""

    def echo(line: str) -> None:
        if "wait-checks: progress" in line:
            print(f"ui {repo}: #{number} {line.strip()}", file=out or sys.stdout, flush=True)

    return echo


def local_push_guard(clone: Path, sh: Sh) -> str:
    """The repo's own pre-push hook (core.hooksPath or .git/hooks), or "" when there is none.

    A hook that refuses a push to the default branch fails the apply every night, and the failure text
    is the hook's own, so the nightly and setup.py name it instead."""
    rc, hooks = sh(["git", "-C", str(clone), "rev-parse", "--git-path", "hooks"])
    rc2, custom = sh(["git", "-C", str(clone), "config", "--get", "core.hooksPath"])
    base = (
        Path(custom)
        if rc2 == 0 and custom
        else Path(hooks)
        if rc == 0 and hooks
        else clone / ".git" / "hooks"
    )
    if not base.is_absolute():
        base = clone / base
    hook = base / "pre-push"
    if hook.is_file() and os.access(hook, os.X_OK):
        try:
            return str(hook.relative_to(clone))
        except ValueError:
            return str(hook)
    return ""


def remote_push_guard(repo: str, branch: str, sh: Sh) -> str:
    """Branch protection or an active ruleset on the default branch that refuses a direct push, read
    through gh. "" when none was found or gh cannot tell (a failed read is reported, never guessed)."""
    rc, out = sh(["gh", "api", f"repos/{repo}/rules/branches/{branch}"])
    if rc == 0:
        try:
            kinds = {r.get("type") for r in json.loads(out or "[]")}
        except ValueError:
            kinds = set()
        hit = sorted(
            kinds & {"pull_request", "required_status_checks", "update", "required_linear_history"}
        )
        if hit:
            return f"an active ruleset on {branch} ({', '.join(hit)})"
    rc, out = sh(["gh", "api", f"repos/{repo}/branches/{branch}/protection"])
    if rc == 0 and out.strip().startswith("{"):
        try:
            prot = json.loads(out)
        except ValueError:
            prot = {}
        parts = [
            k for k in ("required_pull_request_reviews", "required_status_checks") if prot.get(k)
        ]
        return f"branch protection on {branch}" + (f" ({', '.join(parts)})" if parts else "")
    return ""


def guard_advice(repo: str, branch: str, hook: str, remote: str) -> str:
    """Which mode fits a repo whose default branch refuses the apply-at-once push."""
    if hook:
        return (
            f"{repo}: the pre-push hook {hook} may refuse the nightly's push to {branch}. Fits: allow a push to "
            f"{branch} whose diff touches only the overlay folder in the hook (with a hook test), or set "
            f'"apply_via": "pr" (the default for a repo with its own guard) so each release lands as a pull '
            f"request through the repo's own checks and merges at once, or register the repo as workflow."
        )
    if remote:
        return (
            f"{repo}: {remote} refuses a direct push. direct then lands each release as a pull request; with "
            f'required checks it waits for them on that head and merges at once ("apply_via": "pr"). A '
            f"branch that also requires a review refuses that merge, so register such a repo as workflow."
        )
    return ""


def land(clone: Path, wt: Path, branch: str, new: str, latest: str, repo: str, sh: Sh) -> str:
    """Publish the new commit and move the local default branch. Returns "" or the reason it failed."""
    old = sh(["git", "-C", str(clone), "rev-parse", branch])[1]
    remote = sh(["git", "-C", str(clone), "remote"])[1].split()
    if remote:
        rc, out = push(sh, clone, "--quiet", remote[0], f"{new}:refs/heads/{branch}")
        if rc != 0:
            if not re.search(r"protected|GH006|GH013|pull request|rule", out, re.I):
                hook = local_push_guard(clone, sh)
                if hook:
                    return (
                        f"push to {branch} refused by the repo's pre-push hook {hook} (allow an overlay-only push "
                        f'to {branch} in it, set "apply_via": "pr", or register the repo as workflow): {out[-150:]}'
                    )
                return f"push failed: {out[-200:]}"
            pr_branch = f"chore/core-{latest}"
            rc, out = push(sh, clone, "--quiet", "-f", remote[0], f"{new}:refs/heads/{pr_branch}")
            if rc != 0:
                return f"push of {pr_branch} failed: {out[-200:]}"
            rc, out = sh(
                [
                    "gh",
                    "pr",
                    "create",
                    "-R",
                    repo,
                    "--head",
                    pr_branch,
                    "--base",
                    branch,
                    "--title",
                    f"chore(standards): sync core {latest}",
                    "--body",
                    f"Automated sync to core release {latest}. The local gate passed before and after the sync.",
                ],
                cwd=wt,
            )
            if rc != 0 and "already exists" not in out:
                return f"pull request failed: {out[-200:]}"
            rc, out = sh(
                ["gh", "pr", "merge", pr_branch, "-R", repo, "--squash", "--delete-branch"], cwd=wt
            )
            if rc != 0:
                return f"pull request merge failed: {out[-200:]}"
            sh(["git", "-C", str(clone), "fetch", "--quiet", remote[0], branch])
            new = sh(["git", "-C", str(clone), "rev-parse", f"{remote[0]}/{branch}"])[1] or new
    head = sh(["git", "-C", str(clone), "symbolic-ref", "--short", "HEAD"])[1]
    if head == branch:
        rc, out = sh(["git", "-C", str(clone), "merge", "--ff-only", "--quiet", new])
    else:
        rc, out = sh(["git", "-C", str(clone), "update-ref", f"refs/heads/{branch}", new, old])
    if rc != 0:
        return f"could not move local {branch} to the new commit (uncommitted work in the way?): {out[-200:]}"
    return ""


if __name__ == "__main__":
    sys.exit("hermes/ops_center.py is called by hermes/nightly.py")
