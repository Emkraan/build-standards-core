#!/usr/bin/env python3
"""The nightly job every consumer runs: pull the core, then apply it to this machine and its UI repos.

    python3 hermes/nightly.py [--config FILE] [--check] [--retry-delay SECONDS]

Steps, in order, all from this clone so every consumer runs the identical code:
  1. Pull the core clone (fast-forward only, four tries with backoff, because the nightly tick often
     fires while the network is still waking). A clone with no merge base with origin/main (the core's
     history was rewritten) is reset to origin/main when it is clean, with one log line, or the run
     fails with the one-line recovery command. If the pull changed this script, hand over to the new
     copy so a release that changes the job takes effect the same night.
  2. Install the core- skills into the Hermes skills directory (hermes/sync_skills.py).
  3. Apply the Hermes setup from hermes/tools.json: binaries, plugins, third-party skills and
     settings (hermes/apply_setup.py).
  4. Bring every registered UI consumer repo to the newest core release by its mode:
       workflow    run the repo's own core-update workflow, which opens the sync pull request for the
                   owner's approval; report one whose checks fail
       ops-center  apply at once from a local clone behind a local gate (hermes/ops_center.py); a repo
                   with its own CI gate gets a pull request that merges once its checks pass
       vendored    the repo carries no record of the core; record on this machine the release the copy
                   carries (the vendoring tool's pin, or its source hash matched against each release)
       pin-file    the repo records the core as one KEY=<tag> line; open the bump pull request for the
                   repo's own merge path, and push optional pin metrics (hermes/pin_file.py)
       (the old mode name "local" is migrated to "ops-center")
  5. Keep the account's upward report on the core current (hermes/report.py), when apply.report is on:
     the candidates section and the changes-since-last-nightly section. A vendored repo is scanned at
     its root against the core's kit, read-only; a vendored repo registered report only still gets
     its machine record in step 4 (#117 G-031).
  6. Write the consumption feed ~/.config/build-standards-core/consumption.json (hermes/consumption.py),
     when apply.consumption is on: what every ops center's Core consumption panel shows. Read-only on
     every remote; written atomically.

While an ops center's sync pull request waits for the repo's own checks, a progress line (checks done,
pending, failed) is printed at most every 5 minutes, so a long wait shows in the nightly output.
Before and after the run, the core clone and every consumer clone are checked for core.bare = true on a
clone that has a work tree; the flag is set back to false and reported once per clone (cause and fix:
hermes/ops_center.py). Commands the nightly runs never inherit GIT_DIR, GIT_WORK_TREE and the other
variables that point git at one repository.

Consumption classes (README "Direction"): an ops center takes every release at once behind its gate;
every other app is approval-gated, so its release arrives as a pull request the owner approves.

Configuration is the consumer's own file, written by hermes/setup.py and kept outside every repo:
~/.config/build-standards-core/consumer.json (override with --config or CORE_CONSUMER_CONFIG).
Without a file the job still does steps 1 to 3 for ~/.hermes. A version 1 file is migrated in place to
version 2 (backup beside it as consumer.json.v1.bak) and one line says so. apply.claude and
apply.safe_restart default off; the claude step is skipped quietly when the claude CLI is absent.

Output: what changed goes to stdout, problems to stderr. Silent when nothing changed. Exit 0 when
everything is in line (changes included), 1 when something needs the operator, 2 bad arguments.
--check reports what would change and installs, dispatches and pushes nothing. Python 3.9, stdlib only.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Callable

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # the core clone must stay clean for the nightly fast-forward pull
sys.path.insert(0, str(HERE))

import apply_setup  # noqa: E402
import consumption  # noqa: E402
import ops_center  # noqa: E402
import pin_file  # noqa: E402
import report  # noqa: E402

DEFAULT_CONFIG = Path("~/.config/build-standards-core/consumer.json").expanduser()
STUCK_HOURS = 24
CONFIG_VERSION = 2
APPLY_DEFAULTS = {
    "hermes": True,
    "binaries": True,
    "ui": True,
    "claude": False,
    "safe_restart": False,
    "report": True,
    "consumption": True,
}
MODES = ("workflow", "ops-center", "vendored", "pin-file")
STATE_DIR = Path("~/.config/build-standards-core").expanduser()


# Variables that point git at one repository. Inherited by a command the nightly runs in another clone
# or worktree (the nightly started from a hook, or a wrapper that exported them), they make git read and
# write the wrong repository; a `git init` with a worktree's GIT_DIR sets core.bare = true in the clone.
GIT_REPO_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_PREFIX",
)


def child_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in GIT_REPO_ENV}


def sh(
    cmd: list[str],
    cwd: Path | None = None,
    timeout: int = 600,
    echo: Callable[[str], None] | None = None,
) -> tuple[int, str]:
    """Run a command, (exit code, stdout and stderr). With echo, every output line is also handed to
    echo as it arrives (a long wait-checks prints its progress lines this way)."""
    if echo is not None:
        return sh_stream(cmd, cwd, timeout, echo)
    try:
        r = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env=child_env(),
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)


def sh_stream(
    cmd: list[str], cwd: Path | None, timeout: int, echo: Callable[[str], None]
) -> tuple[int, str]:
    lines: list[str] = []
    try:
        p = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            stdin=subprocess.DEVNULL,
            env=child_env(),
        )
    except OSError as exc:
        return 127, str(exc)
    timer = threading.Timer(timeout, p.kill)
    timer.start()
    try:
        assert p.stdout is not None
        for line in p.stdout:
            lines.append(line.rstrip("\n"))
            echo(line.rstrip("\n"))
        rc = p.wait()
    finally:
        timer.cancel()
    return rc, "\n".join(lines).strip()


def migrate(cfg: dict) -> bool:
    """Bring a parsed config to version 2 in place. True when anything changed.

    v1 had no version key, mode "local" and an apply block whose missing keys meant on. A v1 file that
    listed claude as on stays on: only a missing key turns off, never an explicit choice."""
    changed = False
    if cfg.get("version", 1) < CONFIG_VERSION:
        cfg["version"] = CONFIG_VERSION
        changed = True
    for c in cfg.get("ui_consumers", []):
        if c.get("mode") == "local":
            c["mode"] = "ops-center"
            changed = True
    ap = cfg.setdefault("apply", {})
    for k, v in APPLY_DEFAULTS.items():
        if k not in ap:
            ap[k] = v
            changed = True
    return changed


def load_config(path: Path, notes: list[str] | None = None) -> dict:
    cfg = {}
    if path.is_file():
        cfg = json.loads(path.read_text(encoding="utf8"))
        v1 = cfg.get("version", 1) < CONFIG_VERSION
        if v1:
            backup = path.with_name(path.name + ".v1.bak")
            if not backup.exists():
                backup.write_text(path.read_text(encoding="utf8"), encoding="utf8")
            migrate(cfg)
            path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf8")
            if notes is not None:
                notes.append(
                    f"config: migrated {path.name} to version {CONFIG_VERSION} (backup {backup.name})"
                )
    cfg.setdefault("version", CONFIG_VERSION)
    cfg.setdefault("core", str(HERE.parent))
    cfg.setdefault("hermes_home", os.environ.get("HERMES_HOME") or "~/.hermes")
    cfg["apply"] = {**APPLY_DEFAULTS, **cfg.get("apply", {})}
    cfg.setdefault("ui_consumers", [])
    for c in cfg["ui_consumers"]:
        if c.get("mode") == "local":  # an in-memory alias when no file was read
            c["mode"] = "ops-center"
    return cfg


class Run:
    def __init__(self, cfg: dict, check: bool, retry_delay: int):
        self.cfg = cfg
        self.check = check
        self.retry_delay = retry_delay
        self.core = Path(cfg["core"]).expanduser()
        self.home = Path(cfg["hermes_home"]).expanduser()
        self.info: list[str] = []
        self.problems: list[str] = []
        self.bare: dict[str, list[str]] = {}  # clone -> when core.bare was found true and set back

    def bare_guard(self, when: str) -> None:
        """core.bare = true on a clone that has a work tree breaks git pull there. Check the core clone and
        every consumer clone, set the flag back to false, and note when (ops_center.py docstring)."""
        if self.check:
            return
        clones = [self.core] + [
            Path(c["path"]).expanduser() for c in self.cfg["ui_consumers"] if c.get("path")
        ]
        for clone in dict.fromkeys(clones):
            if ops_center.bare_flag_restore(clone, sh):
                self.bare.setdefault(str(clone), []).append(when)

    def bare_report(self) -> None:
        """One line per clone, however often the flag was found."""
        for clone, whens in self.bare.items():
            self.problems.append(
                f"git: core.bare was true on the non-bare clone {clone} ({', '.join(whens)}) and is "
                f"set back to false; a hook or tool that runs git with a worktree's GIT_DIR sets it"
            )

    # 1 ---------------------------------------------------------------------------------------
    def pull(self) -> bool:
        if not (self.core / ".git").exists():
            self.problems.append(f"core clone missing at {self.core}")
            return False
        _, before = sh(["git", "-C", str(self.core), "rev-parse", "HEAD"])
        err = ""
        for attempt in range(1, 5):
            rc, err = sh(
                ["git", "-C", str(self.core), "pull", "--ff-only", "--quiet", "origin", "main"]
            )
            if rc == 0:
                # --force: a tag the core moved (a rewritten history) must not fail the fetch.
                sh(["git", "-C", str(self.core), "fetch", "--quiet", "--tags", "--force", "origin"])
                break
            if self.recover_rewrite():
                break
            if any("history rewritten" in p for p in self.problems):
                return False
            if attempt < 4:
                time.sleep(self.retry_delay * attempt)
        else:
            self.problems.append(
                f"core pull failed after 4 tries (dirty clone, divergence or network): {err[-300:]}"
            )
            return False
        _, after = sh(["git", "-C", str(self.core), "rev-parse", "HEAD"])
        if before != after:
            self.info.append(f"core updated {before[:7]} -> {after[:7]} ({self.latest_tag()})")
        return True

    def recover_rewrite(self) -> bool:
        """Recover from a rewritten core history (CONSUMING.md section 6, "History rewritten").

        A rewrite leaves the clone with no merge base with origin/main, so a fast-forward can never
        succeed again. Nobody commits in this clone (section 1), so a clean clone is reset to
        origin/main, with the old tip kept as a local branch and one log line. A clone with local
        edits is not touched: the problem line gives the one-line recovery command. Returns True when
        the clone was reset."""
        c = str(self.core)
        rc, _ = sh(["git", "-C", c, "fetch", "--quiet", "--tags", "--force", "origin"])
        if rc != 0:
            return False  # network: the retry loop handles it
        if sh(["git", "-C", c, "rev-parse", "--verify", "--quiet", "origin/main"])[0] != 0:
            return False
        rc, _ = sh(["git", "-C", c, "merge-base", "HEAD", "origin/main"])
        if rc == 0:
            return False  # a shared history: divergence or a dirty clone, not a rewrite
        fix = f"git -C {c} fetch --tags --force origin && git -C {c} reset --hard origin/main"
        _, dirty = sh(["git", "-C", c, "status", "--porcelain", "--untracked-files=no"])
        if dirty:
            self.problems.append(
                f"core history rewritten (no merge base with origin/main) and the clone has local "
                f"edits, so it was not reset. Recover with: {fix}"
            )
            return False
        if self.check:
            self.info.append(
                f"core history rewritten: would reset the clone to origin/main ({fix})"
            )
            return True
        _, old = sh(["git", "-C", c, "rev-parse", "HEAD"])
        backup = f"core-before-rewrite-{old[:7]}"
        sh(["git", "-C", c, "branch", "--force", backup, old])
        rc, out = sh(["git", "-C", c, "reset", "--hard", "--quiet", "origin/main"])
        if rc != 0:
            self.problems.append(
                f"core history rewritten and the reset failed: {out[-200:]}. Recover with: {fix}"
            )
            return False
        self.info.append(
            f"core history rewritten: clone reset to origin/main, old tip kept as branch {backup}"
        )
        return True

    def latest_tag(self) -> str:
        """The newest published release, the same thing update-core.py moves a UI consumer to."""
        _, url = sh(["git", "-C", str(self.core), "remote", "get-url", "origin"])
        repo = url.strip().removesuffix(".git").split("github.com")[-1].lstrip(":/")
        rc, tag = sh(["gh", "release", "view", "-R", repo, "--json", "tagName", "--jq", ".tagName"])
        if rc == 0 and tag.strip():
            return tag.strip()
        _, tag = sh(["git", "-C", str(self.core), "describe", "--tags", "--abbrev=0", "HEAD"])
        return tag.strip()

    # 2 ---------------------------------------------------------------------------------------
    def skills(self) -> None:
        dest = Path(self.cfg.get("skills_dest") or self.home / "skills" / "core").expanduser()
        cmd = [sys.executable, str(self.core / "hermes" / "sync_skills.py"), "--dest", str(dest)]
        if self.check:
            cmd.append("--dry-run")
        rc, out = sh(cmd)
        if rc == 3:
            self.problems.append(f"core skills edited by hand, left as is: {out[-400:]}")
        elif rc != 0:
            self.problems.append(f"core skills sync failed (exit {rc}): {out[-400:]}")
        elif out and not out.startswith(
            ("updated 0 file(s), removed 0", "would update 0 file(s), removed 0")
        ):
            self.info.append(f"skills: {out.splitlines()[-1]}")

    # 3 ---------------------------------------------------------------------------------------
    def hermes(self) -> None:
        ap = self.cfg["apply"]
        if not ap.get("hermes", True):
            return
        s = apply_setup.Setup(
            self.home,
            apply=not self.check,
            binaries=ap.get("binaries", True),
            safe_restart=ap.get("safe_restart", False),
        ).run_all()
        for line in s.lines():
            (self.info if line.startswith(("CHANGED", "RESTART")) else self.problems).append(
                f"hermes: {line}"
            )

    def claude(self) -> None:
        if not self.cfg["apply"].get("claude", False) or shutil.which("claude") is None:
            return  # off by default; with no CLI there is nothing to configure, so stay quiet
        cmd = [sys.executable, str(self.core / "claude" / "apply_claude.py"), "--quiet"] + (
            ["--check"] if self.check else []
        )
        rc, out = sh(cmd)
        for line in out.splitlines():
            (self.info if line.startswith(("CHANGED", "RESTART")) else self.problems).append(
                f"claude: {line}"
            )
        if rc not in (0, 3) and not out:
            self.problems.append(f"claude: apply_claude.py failed (exit {rc})")

    # 4 ---------------------------------------------------------------------------------------
    def ui(self) -> None:
        if not self.cfg["apply"].get("ui", True):
            return
        latest = self.latest_tag()
        for c in self.cfg["ui_consumers"]:
            if c.get("apply") is False and c.get("mode") != "vendored":
                continue  # report only: a local job of the machine's own applies the core (CONSUMING.md section 5)
            # A vendored entry registered report only still gets its record (#117 G-031): the record
            # only reads the clone and the core clone and writes on this machine, never into the repo.
            try:
                mode = c.get("mode", "workflow")
                if mode == "local":
                    mode = "ops-center"
                if mode not in MODES:
                    raise RuntimeError(f"unknown mode {mode!r} (known: {', '.join(MODES)})")
                getattr(self, "ui_" + mode.replace("-", "_"))(c, latest)
            except Exception as exc:  # one broken consumer must not hide the others
                self.problems.append(f"ui {c.get('repo')}: {exc}")

    def upward(self) -> None:
        """Step 5: the upward report, for every consumer that has a local clone."""
        if not (self.cfg["apply"].get("report", True) and self.cfg["apply"].get("ui", True)):
            return
        core_repo = os.environ.get("CORE_REPO", "")
        target, why = report.report_target(
            self.cfg.get("report_repo") or os.environ.get("CORE_REPORT_REPO", ""), core_repo, sh
        )
        if not target:
            self.info.append(f"report: {why}")
            return
        clones = [
            self.report_entry(c)
            for c in self.cfg["ui_consumers"]
            if c.get("path") and c.get("mode") != "pin-file"
        ]  # a pin line has no kit to scan
        # one report issue per run: the section that creates it records the number here
        run: dict = {
            "configured": self.cfg.get("report_issue") or os.environ.get("CORE_REPORT_ISSUE", "")
        }
        try:
            i, p = report.update(self.core, target, clones, sh, STATE_DIR, self.check, run)
            self.info += i
            self.problems += p
        except Exception as exc:
            self.problems.append(f"report candidates: {exc}")
        try:
            i, p = report.update_changes(self.core, target, clones, sh, STATE_DIR, self.check, run)
            self.info += i
            self.problems += p
        except Exception as exc:
            self.problems.append(f"report changes: {exc}")

    def feed(self) -> None:
        """Step 6: the consumption feed every ops center's Core consumption panel renders
        (hermes/consumption.py, standards/local-ops-app.md section 19). Read-only on every remote."""
        if not self.cfg["apply"].get("consumption", True):
            return
        try:
            i, p = consumption.update(
                self.cfg,
                self.core,
                os.environ.get("CORE_REPO", ""),
                self.latest_tag(),
                sh,
                STATE_DIR,
                self.check,
                self.pinned_of,
                self.cfg.get("report_repo") or os.environ.get("CORE_REPORT_REPO", ""),
            )
            self.info += i
            self.problems += p
        except Exception as exc:
            self.problems.append(f"consumption feed: {exc}")

    def pinned_of(self, c: dict) -> str:
        """The release a consumer is pinned to, for the feed: the vendored record, else the default
        branch's standards.lock through gh. "" when it cannot be read."""
        try:
            if c.get("mode") == "vendored":
                return json.loads(record_path(c["repo"]).read_text(encoding="utf8")).get(
                    "release", ""
                )
            if c.get("mode") == "pin-file":
                rc, out = sh(
                    ["gh", "api", f"repos/{c['repo']}/contents/{c['file']}", "--jq", ".content"]
                )
                return (
                    pin_file.read_pin(base64.b64decode(out).decode(), c.get("key", "CORE_VERSION"))
                    if rc == 0
                    else ""
                )
            return self.pinned_ref(c["repo"], c.get("overlay", "standards-overlay"))
        except (OSError, ValueError, RuntimeError):
            return ""

    def report_entry(self, c: dict) -> dict:
        """The entry the report sections scan. A vendored repo has no overlay and no kit copy under
        its own name, so it is scanned at its root against the core clone's kit, and its release
        comes from the machine's vendored record (#117 G-031). Read-only either way."""
        if c.get("mode") != "vendored":
            return c
        e = {**c, "overlay": "", "kit_src": str(self.core / "kit" / "src")}
        try:
            e["release"] = json.loads(record_path(c["repo"]).read_text(encoding="utf8")).get(
                "release", ""
            )
        except (OSError, ValueError):
            e["release"] = ""
        return e

    def pinned_ref(self, repo: str, overlay: str) -> str:
        path = f"{overlay}/standards.lock" if overlay else "standards.lock"
        rc, out = sh(["gh", "api", f"repos/{repo}/contents/{path}", "--jq", ".content"])
        if rc != 0:
            raise RuntimeError(f"cannot read {path}: {out[-200:]}")
        for line in base64.b64decode(out).decode().splitlines():
            if line.startswith("ref="):
                return line[4:].strip()
        raise RuntimeError(f"{path} has no ref= line")

    def ui_workflow(self, c: dict, latest: str) -> None:
        repo, overlay = c["repo"], c.get("overlay", "standards-overlay")
        wf = c.get("workflow", "core-update.yml")
        ref = self.pinned_ref(repo, overlay)
        if ref == latest:
            return
        rc, out = sh(
            [
                "gh",
                "pr",
                "list",
                "-R",
                repo,
                "--head",
                f"chore/core-{latest}",
                "--state",
                "open",
                "--json",
                "number,url,createdAt,statusCheckRollup",
            ]
        )
        prs = json.loads(out) if rc == 0 and out else []
        if prs:
            # An approval-gated app: the open sync pull request waits for the owner, which is the
            # normal state (README "Direction"). Only a red CI on it needs the operator.
            pr = prs[0]
            age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(
                pr["createdAt"].replace("Z", "+00:00")
            )
            ci = consumption.ci_state(pr.get("statusCheckRollup") or [])
            if ci == "fail":
                self.problems.append(
                    f"ui {repo}: core {latest} pull request has failing checks, fix before the "
                    f"owner approves it: {pr['url']}"
                )
            elif age.total_seconds() > STUCK_HOURS * 3600:
                self.info.append(
                    f"ui {repo}: core {latest} pull request open {int(age.total_seconds() // 3600)}h, "
                    f"CI {ci}, awaiting owner approval: {pr['url']}"
                )
            else:
                self.info.append(
                    f"ui {repo}: {ref} -> {latest} pull request open (CI {ci}): {pr['url']}"
                )
            return
        rc, out = sh(
            [
                "gh",
                "run",
                "list",
                "-R",
                repo,
                "--workflow",
                wf,
                "-L",
                "1",
                "--json",
                "conclusion,status,url,createdAt",
            ]
        )
        last = (json.loads(out) or [{}])[0] if rc == 0 and out else {}
        if last.get("status") in ("queued", "in_progress"):
            self.info.append(f"ui {repo}: {ref} -> {latest} update running: {last.get('url')}")
            return
        if last.get("conclusion") == "failure":
            self.problems.append(
                f"ui {repo}: last {wf} run failed, pin still {ref} (core is {latest}): {last.get('url')}"
            )
        if self.check:
            self.info.append(f"ui {repo}: behind ({ref}, core is {latest}); would run {wf}")
            return
        rc, out = sh(["gh", "workflow", "run", wf, "-R", repo])
        if rc == 0:
            self.info.append(f"ui {repo}: behind ({ref}, core is {latest}); started {wf}")
        else:
            self.problems.append(
                f"ui {repo}: behind ({ref}, core is {latest}) and {wf} could not start: {out[-200:]}"
            )

    def ui_ops_center(self, c: dict, latest: str) -> None:
        r = ops_center.apply(c, latest, sh, STATE_DIR, self.check)
        if r.get("bare"):
            self.bare.setdefault(str(Path(c["path"]).expanduser()), []).append(
                "around the ops-center apply"
            )
        if r["status"] in ("applied", "would"):
            self.info.append(r["message"])
        elif r["status"] != "current" and r["report"]:
            self.problems.append(r["message"])
        elif r["status"] != "current":
            # Reported once per kind as a problem; a repeat still shows, so a run never looks silent.
            self.info.append(f"{r['message']} (still failing, reported before)")

    def ui_pin_file(self, c: dict, latest: str) -> None:
        """A repo that records the core as one pin line (hermes/pin_file.py): approval-gated, the bump
        arrives as a pull request the repo's own merge path takes."""
        i, p = pin_file.apply(c, latest, sh, self.check)
        self.info += i
        self.problems += p

    def ui_vendored(self, c: dict, latest: str) -> None:
        """The repo carries no record of the core, so the record lives on this machine.

        The record holds the release the copy actually carries, never simply the newest one: a
        vendored repo held back on purpose must read as behind. That release comes from the pin the
        vendoring tool writes on this machine ("pin" in the consumer entry), else from matching the
        recorded source hash against each release of the core clone."""
        repo = c["repo"]
        if not c.get("path"):
            raise RuntimeError('mode "vendored" needs "path", the local clone')
        rec = record_path(repo)
        old: dict = {}
        with contextlib.suppress(OSError, ValueError):
            old = json.loads(rec.read_text(encoding="utf8"))
        carried, how = carried_release(self.core, c, old)
        if not carried:
            self.problems.append(
                f"ui {repo}: vendored, but which release the copy carries is unknown: have the vendoring tool "
                f'write the release it copied to a pin file and name it as "pin" in consumer.json, or record '
                f"{{release, source_hash}} in {rec} when it copies"
            )
            return
        digest = source_hash_at(self.core, carried) or old.get("source_hash", "")
        new = {
            "release": carried,
            "source_hash": digest,
            "found_by": how,
            "latest": latest,
            "behind": carried != latest,
        }
        if old == new:
            return
        if self.check:
            self.info.append(
                f"ui {repo}: vendored record would change ({old.get('release', 'none')} -> {carried})"
            )
            return
        rec.parent.mkdir(parents=True, exist_ok=True)
        rec.write_text(json.dumps(new, indent=2) + "\n", encoding="utf8")
        state = f"behind ({carried}, core is {latest})" if carried != latest else "current"
        self.info.append(f"ui {repo}: vendored copy carries {carried} by {how}, {state}")


def record_path(repo: str) -> Path:
    """Where the vendored record lives: the operator machine, never the repo."""
    root = Path(os.environ.get("CORE_VENDORED_DIR") or STATE_DIR / "vendored").expanduser()
    return root / (repo.replace("/", "__") + ".json")


RELEASE_RE = re.compile(r"\bv\d+\.\d+\.\d+\b")
SOURCE_DIRS = ("standards", "tokens", "lint", "kit/src")
SKIP_PARTS = {"node_modules", "dist", "__pycache__"}


def carried_release(core: Path, c: dict, old: dict) -> tuple[str, str]:
    """(release the vendored copy carries, how it was found) or ("", "")."""
    pin = c.get("pin")
    if pin:
        try:
            m = RELEASE_RE.search(Path(pin).expanduser().read_text(encoding="utf8"))
        except OSError:
            m = None
        if m:
            return m.group(0), "pin"
    digest = old.get("source_hash")
    if digest:
        tags = [old["release"]] if old.get("release") else []
        _, out = sh(["git", "-C", str(core), "tag", "--list", "v*", "--sort=-v:refname"])
        tags += [t for t in out.split() if t not in tags]
        for tag in tags:
            if source_hash_at(core, tag) == digest:
                return tag, "content hash"
    return "", ""


def _hash(entries) -> str:
    """sha256 over (src, relative path, bytes) entries, CRLF normalised, in source then path order."""
    import hashlib

    h = hashlib.sha256()
    for src, rel, data in entries:
        h.update(f"{src}/{rel}\n".encode())
        h.update(data.replace(b"\r\n", b"\n"))
        h.update(b"\0")
    return h.hexdigest()


def source_hash(core: Path) -> str:
    """Hash of the core folders a release ships, read from the core clone's working tree. A vendored
    copy has its names scrubbed, so it cannot be hashed back to the source; the source hash is what
    tells a later run which core content the copy was made from."""

    def entries():
        for src in SOURCE_DIRS:
            d = core / src
            if d.is_dir():
                files = [p for p in d.rglob("*") if p.is_file() and not SKIP_PARTS & set(p.parts)]
                for f in sorted(files, key=lambda p: PurePosixPath(p.relative_to(d).as_posix())):
                    yield src, f.relative_to(d).as_posix(), f.read_bytes()

    return _hash(entries())


def source_hash_at(core: Path, rev: str) -> str:
    """source_hash of the release rev, read from git objects (no checkout). "" when rev is unknown."""
    r = subprocess.run(
        ["git", "-C", str(core), "ls-tree", "-r", "-z", rev, "--", *SOURCE_DIRS],
        capture_output=True,
    )
    if r.returncode != 0:
        return ""
    blobs = []
    for item in r.stdout.split(b"\0"):
        if not item:
            continue
        meta, path = item.decode().split("\t", 1)
        if meta.split()[1] != "blob":
            continue
        src = next(s for s in SOURCE_DIRS if path.startswith(s + "/"))
        rel = path[len(src) + 1 :]
        if not SKIP_PARTS & set(rel.split("/")):
            blobs.append((SOURCE_DIRS.index(src), PurePosixPath(rel), src, rel, meta.split()[2]))
    blobs.sort(key=lambda b: (b[0], b[1]))
    if not blobs:
        return _hash([])
    batch = subprocess.run(
        ["git", "-C", str(core), "cat-file", "--batch"],
        input=b"".join(b[4].encode() + b"\n" for b in blobs),
        capture_output=True,
    )
    out, pos, entries = batch.stdout, 0, []
    for _, _, src, rel, _ in blobs:
        nl = out.index(b"\n", pos)
        size = int(out[pos:nl].split()[2])
        entries.append((src, rel, out[nl + 1 : nl + 1 + size]))
        pos = nl + 1 + size + 1
    return _hash(entries)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--config", default=os.environ.get("CORE_CONSUMER_CONFIG") or str(DEFAULT_CONFIG)
    )
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--retry-delay", type=int, default=60)
    ap.add_argument("--core", help="override the core clone (older wrappers pass it)")
    ap.add_argument("--skills-dest", help="override the core skills directory")
    a = ap.parse_args()
    notes: list[str] = []
    cfg = load_config(Path(a.config).expanduser(), notes)
    os.environ["CORE_CONSUMER_CONFIG"] = str(
        Path(a.config).expanduser()
    )  # overlay scripts read core_repo from it
    if a.core:
        cfg["core"] = a.core
    if not os.environ.get("CORE_REPO"):
        # The overlays do not store the source; hand them the one this clone came from.
        _, url = sh(
            ["git", "-C", str(Path(cfg["core"]).expanduser()), "remote", "get-url", "origin"]
        )
        slug = url.strip().removesuffix(".git").split("github.com")[-1].lstrip(":/")
        if slug.count("/") == 1:
            os.environ["CORE_REPO"] = slug
    if a.skills_dest:
        cfg["skills_dest"] = a.skills_dest
    run = Run(cfg, a.check, a.retry_delay)
    run.info += notes

    if run.pull() and os.environ.get("CORE_NIGHTLY_HANDOVER") != "1":
        fresh = run.core / "hermes" / "nightly.py"
        if fresh.resolve() != Path(__file__).resolve() or fresh.stat().st_mtime > START:
            os.environ["CORE_NIGHTLY_HANDOVER"] = "1"
            for line in run.info:
                print(line)
            os.execv(sys.executable, [sys.executable, str(fresh), *sys.argv[1:]])
    run.bare_guard("before the run")
    if not run.problems:
        run.skills()
        run.hermes()
        run.claude()
        run.ui()
        run.upward()
        run.feed()
    run.bare_guard("after the run")
    run.bare_report()
    for line in run.info:
        print(line)
    for line in run.problems:
        print(line, file=sys.stderr)
    return 1 if run.problems else 0


START = time.time()

if __name__ == "__main__":
    sys.exit(main())
