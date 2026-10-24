#!/usr/bin/env python3
"""One-time setup of a consumer: register the nightly job that applies the core to this machine.

    python3 hermes/setup.py [--ui OWNER/REPO[=MODE[:PATH]]] ... [--at "15 3 * * *"]
                            [--claude | --no-claude] [--safe-restart | --no-safe-restart] [--no-run] [--check]

What it does, all idempotent (run it again to change anything):
  1. Writes the consumer file ~/.config/build-standards-core/consumer.json: where the core clone is,
     the Hermes home, and the UI consumer repos to keep on the newest core release. Existing UI
     entries are kept; --ui adds or updates one. Mode "workflow" (default) runs the repo's own
     core-update workflow; "ops-center:PATH" applies at once from a local clone behind a local gate;
     "vendored:PATH" records the release on this machine only; "pin-file:PATH" keeps a one-line pin
     current by pull request (set "file" and the other hermes/pin_file.py keys in the entry) ("local:PATH" is the old name of
     ops-center and is migrated). The file is version 2; an older file is migrated with a backup.
     apply.claude and apply.safe_restart are off unless the file or --claude / --safe-restart turns
     them on; --no-claude and --no-safe-restart turn them off again.
  2. Writes the cron wrapper <hermes home>/scripts/core-nightly.sh, which runs hermes/nightly.py from
     the core clone, so the job's logic always comes from the core and never from a local copy.
  3. Creates (or updates) the Hermes cron job "core-nightly": no-agent, daily, stdout delivered to the
     origin chat (--deliver changes it), failures notified. Removes the job "core-skills-sync" it
     supersedes, and the old wrapper scripts of retired core jobs that the core wrote. The job is found again by its wrapper script, not its name, so a consumer may rename it
     to its own naming rule (configurations.md section 2) and a rerun keeps the name and the delivery
     target unless --name or --deliver is given.
  4. Runs the nightly job once now and prints the result, unless --no-run.
A "workflow" repo given with --ui must have a merge gate that requires status checks on its default
branch, read through gh: branch protection, an active ruleset, or a REQUIRED_CHECKS list in one of its
workflows (the merge gate workflow of a plan without branch protection). A repo with none has nothing
that stops a red sync pull request from merging, so setup refuses it and says how to fix it.
--allow-no-required-checks registers it anyway (core-update.yml still waits for every check before it
merges) and prints a warning.
An "ops-center" repo given with --ui is checked for a guard on its default branch that refuses the
nightly's direct push: a pre-push hook in the local clone, branch protection or an active ruleset (read
through gh). Setup registers it and prints which mode fits (an overlay-only allowance in the hook, or
mode workflow), because otherwise every apply rolls back on the push.
--report-only registers the --ui repos for the report sections only, for a repo a local job of this
machine already applies the core to (CONSUMING.md section 5); the nightly skips their apply.
Each --ui repo gets one line naming its consumption class: an ops-center repo applies at once, every
other mode is approval-gated (README "Direction", "Two consumption classes").
--check prints what it would do and changes nothing. Python 3.9, stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import nightly  # noqa: E402
import ops_center  # noqa: E402

CORE = HERE.parent
CONFIG = Path(
    os.environ.get("CORE_CONSUMER_CONFIG") or "~/.config/build-standards-core/consumer.json"
).expanduser()
TEMP_MARKERS = ("/tmp/", "/private/tmp/", "/var/folders/", "/.hermes/cache/scratch/")
JOB = "core-nightly"
LEGACY = {"core-skills-sync"}
# Wrapper scripts of retired core jobs. Removed only when the file names the core, so a consumer's own
# script of the same name is never touched.
LEGACY_SCRIPTS = ("core-skills-sync.sh", "core-lockstep.sh")
WRAPPER = """#!/bin/bash
# Written by build-standards-core hermes/setup.py. Do not edit; rerun setup.py instead.
# Cron runs with a thin PATH, so add the usual package-manager locations for brew, cargo and npx.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
exec python3 "{core}/hermes/nightly.py" --config "{config}"
"""


def hermes(home: Path, *args: str) -> tuple[int, str]:
    keep = ("HOME", "PATH", "LANG", "USER", "TMPDIR")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["HERMES_HOME"] = str(home)
    env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
    r = subprocess.run(
        ["hermes", *args],
        capture_output=True,
        text=True,
        env=env,
        stdin=subprocess.DEVNULL,
        timeout=300,
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def jobs(home: Path) -> list[dict]:
    path = home / "cron" / "jobs.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf8"))
    return data["jobs"] if isinstance(data, dict) else data


def find_job(all_jobs: list[dict], wrapper_name: str) -> list[dict]:
    """The job this setup owns: by its wrapper script first, so a renamed job is still found, then by
    the default name for a job written before the script was recorded."""
    mine = [j for j in all_jobs if j.get("script") == wrapper_name]
    return mine or [j for j in all_jobs if j.get("name") == JOB]


def parse_ui(spec: str) -> dict:
    repo, _, mode = spec.partition("=")
    entry = {"repo": repo.strip(), "mode": "workflow", "overlay": "standards-overlay"}
    name, _, path = mode.partition(":")
    if name == "local":
        name = "ops-center"
    if name in ("ops-center", "vendored", "pin-file") and path:
        entry.update(mode=name, path=path)
    elif mode and name != "workflow":
        raise SystemExit(
            f"--ui {spec}: mode must be empty, workflow, ops-center:PATH, vendored:PATH or pin-file:PATH"
        )
    return entry


def class_note(e: dict) -> str:
    """One line on the consumption class a registered repo falls in (README "Direction")."""
    mode = e.get("mode", "workflow")
    if mode in ("ops-center", "local"):
        return (
            f"{e['repo']} ({mode}): apply-at-once, every core release is applied at once by the nightly "
            "behind the local gate, with rollback"
        )
    return (
        f"{e['repo']} ({mode}): approval-gated, never changes without the owner's approval: each "
        "release arrives as a pull request the owner approves, and nothing is applied to it directly"
    )


def load_core_ci():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "core_ci", CORE / "templates" / "overlay" / "scripts" / "core-ci.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def required_checks(repo: str) -> tuple[set, list]:
    """(required check names, notes) on the repo's default branch, through gh."""
    mod = load_core_ci()
    repo, branch = mod.repo_and_branch(repo)
    contexts, _, notes = mod.required_contexts(repo, branch)
    for names in mod.remote_gate_lists(repo).values():
        contexts |= set(names)
    return contexts, notes


def unguarded(entries: list[dict], lookup=required_checks) -> list[str]:
    """One message per workflow-mode repo whose default branch requires no status checks (or cannot be
    read): its sync pull request would have no gate."""
    out = []
    for e in entries:
        if e.get("mode", "workflow") != "workflow":
            continue
        try:
            contexts, notes = lookup(e["repo"])
        except Exception as exc:  # gh missing, no access: unproven is not guarded
            contexts, notes = set(), [str(exc)]
        if not contexts:
            out.append(
                f"{e['repo']}: the default branch requires no status checks"
                + (f" ({'; '.join(notes)})" if notes else "")
            )
    return out


def push_guards(entries: list[dict], sh=nightly.sh) -> list[str]:
    """One line per ops-center repo whose default branch refuses a direct push, saying which mode fits."""
    out = []
    for e in entries:
        if e.get("mode") != "ops-center" or not e.get("path"):
            continue
        clone = Path(e["path"]).expanduser()
        if not (clone / ".git").exists():
            continue
        branch = ops_center.default_branch(clone, sh)
        advice = ops_center.guard_advice(
            e["repo"],
            branch,
            ops_center.local_push_guard(clone, sh),
            ops_center.remote_push_guard(e["repo"], branch, sh),
        )
        if advice:
            out.append(advice)
    return out


def legacy_scripts(home: Path) -> list[Path]:
    """Retired core wrapper scripts still on disk that the core wrote (they name the core)."""
    out = []
    for name in LEGACY_SCRIPTS:
        p = home / "scripts" / name
        try:
            if p.is_file() and "build-standards-core" in p.read_text(
                encoding="utf8", errors="replace"
            ):
                out.append(p)
        except OSError:
            pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--ui",
        action="append",
        default=[],
        help="OWNER/REPO or OWNER/REPO=ops-center:PATH or =vendored:PATH",
    )
    ap.add_argument("--overlay", default="standards-overlay", help="overlay folder in the UI repos")
    ap.add_argument("--at", default="15 3 * * *", help="cron schedule, default 03:15 daily")
    ap.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME") or "~/.hermes")
    ap.add_argument(
        "--no-binaries", action="store_true", help="never let the job run a package manager"
    )
    for step in ("claude", "safe-restart"):
        g = ap.add_mutually_exclusive_group()
        g.add_argument(
            f"--{step}",
            dest=step.replace("-", "_"),
            action="store_const",
            const=True,
            help=f"turn the {step} step on (apply.{step.replace('-', '_')})",
        )
        g.add_argument(
            f"--no-{step}",
            dest=step.replace("-", "_"),
            action="store_const",
            const=False,
            help=f"turn the {step} step off",
        )
    ap.add_argument("--name", help=f"job name on create (default {JOB}), on update only when given")
    ap.add_argument(
        "--deliver", help="delivery target on create (default origin), on update only when given"
    )
    ap.add_argument(
        "--allow-no-required-checks",
        action="store_true",
        help="register a workflow repo whose default branch requires no status checks",
    )
    ap.add_argument(
        "--report-only",
        action="store_true",
        help="the --ui repos given are applied by a local job of this machine: register them for the "
        'report sections only ("apply": false on the entry)',
    )
    ap.add_argument(
        "--report-repo",
        help="OWNER/REPO of the PRIVATE intake that receives this account's consumer report "
        "(report_repo); never the core",
    )
    ap.add_argument("--no-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    home = Path(a.hermes_home).expanduser()
    if any(m in f"{CORE}/" for m in TEMP_MARKERS):
        print(
            f"this clone is at a temporary path ({CORE}); macOS clears it and the nightly job would break.\n"
            "Clone to a permanent path, for example ~/GitHub/build-standards-core, and run setup.py from there.",
            file=sys.stderr,
        )
        return 2

    cfg = json.loads(CONFIG.read_text(encoding="utf8")) if CONFIG.is_file() else {}
    cfg.update(core=str(CORE), hermes_home=str(home))
    # Where the core lives, recorded on this machine only so overlays never have to name it.
    r = subprocess.run(
        ["git", "-C", str(CORE), "remote", "get-url", "origin"], capture_output=True, text=True
    )
    slug = (
        r.stdout.strip().removesuffix(".git").split("github.com")[-1].lstrip(":/")
        if r.returncode == 0
        else ""
    )
    if slug.count("/") == 1:
        cfg["core_repo"] = slug
    if a.report_repo:
        cfg["report_repo"] = a.report_repo
    nightly.migrate(cfg)
    if a.no_binaries:
        cfg["apply"]["binaries"] = False
    for key in ("claude", "safe_restart"):
        if getattr(a, key) is not None:
            cfg["apply"][key] = getattr(a, key)
    ui = {u["repo"]: u for u in cfg.get("ui_consumers", [])}
    added = []
    for spec in a.ui:
        e = parse_ui(spec)
        e["overlay"] = a.overlay
        if a.report_only:
            e["apply"] = False
        ui[e["repo"]] = e
        added.append(e)
    gaps = unguarded([e for e in added if e.get("apply") is not False])
    if gaps and not a.allow_no_required_checks:
        print(
            "refusing to register a workflow repo with no merge gate:\n  "
            + "\n  ".join(gaps)
            + "\n"
            "Its core sync pull request must merge only after the repo's own CI passes. Require the "
            "core-ci.yml jobs on the default branch (in a clone: python3 scripts/core-ci.py required-checks "
            "--fix prints the command) or list them in the REQUIRED_CHECKS of its merge gate workflow, or "
            "register it as ops-center:PATH. To register it anyway, rerun with --allow-no-required-checks.",
            file=sys.stderr,
        )
        return 2
    for g in gaps:
        print(
            f"WARNING {g}; registered because of --allow-no-required-checks. core-update.yml waits for "
            "every check before it merges, but nothing on GitHub stops another merge.",
            file=sys.stderr,
        )
    for g in push_guards(added):
        print(f"NOTE {g}", file=sys.stderr)
    cfg["ui_consumers"] = list(ui.values())
    for e in added:
        print(class_note(e))

    wrapper = home / "scripts" / "core-nightly.sh"
    existing = find_job(jobs(home), wrapper.name)
    legacy = [j for j in jobs(home) if j.get("name") in LEGACY]
    plan = [
        f"consumer file {CONFIG}: {len(cfg['ui_consumers'])} UI consumer(s) "
        f"({', '.join(ui) or 'none'})",
        f"cron wrapper {wrapper}",
        f"cron job {a.name or (existing[0].get('name') if existing else JOB)} at '{a.at}': "
        + ("update " + existing[0]["id"] if existing else "create"),
    ]
    plan += [f"remove superseded cron job {j['name']} ({j['id']})" for j in legacy]
    old_scripts = legacy_scripts(home)
    plan += [f"remove retired wrapper script {p}" for p in old_scripts]
    plan.append(
        "apply steps: " + ", ".join(f"{k}={'on' if v else 'off'}" for k, v in cfg["apply"].items())
    )
    if a.check:
        print("\n".join("would " + p for p in plan))
        return 0

    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if (
        CONFIG.is_file()
        and json.loads(CONFIG.read_text(encoding="utf8")).get("version", 1) < nightly.CONFIG_VERSION
    ):
        CONFIG.with_name(CONFIG.name + ".v1.bak").write_text(
            CONFIG.read_text(encoding="utf8"), encoding="utf8"
        )
    CONFIG.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf8")
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(WRAPPER.format(core=CORE, config=CONFIG), encoding="utf8")
    wrapper.chmod(0o755)

    prompt = (
        "Nightly apply of the core standards: Hermes skills, plugins and settings, and UI consumer "
        "repos (silent unless something changed or needs the operator)."
    )
    if existing:
        extra = (["--deliver", a.deliver] if a.deliver else []) + (
            ["--name", a.name] if a.name else []
        )
        rc, out = hermes(
            home,
            "cron",
            "edit",
            existing[0]["id"],
            "--schedule",
            a.at,
            "--script",
            wrapper.name,
            "--no-agent",
            "--prompt",
            prompt,
            *extra,
        )
    else:
        rc, out = hermes(
            home,
            "cron",
            "create",
            a.at,
            prompt,
            "--name",
            a.name or JOB,
            "--script",
            wrapper.name,
            "--no-agent",
            "--deliver",
            a.deliver or "origin",
        )
    if rc != 0:
        print(f"cron job {JOB} could not be written: {out[-400:]}", file=sys.stderr)
        return 1
    for j in legacy:
        hermes(home, "cron", "remove", j["id"])
    for p in old_scripts:
        p.unlink()
    job = next(iter(find_job(jobs(home), wrapper.name)), None)
    if not job or not job.get("no_agent") or job.get("script") != wrapper.name:
        print(f"cron job {JOB} not found as expected after writing it", file=sys.stderr)
        return 1
    print("\n".join(plan))
    print(
        f"cron job {JOB} {job['id']}: {job.get('schedule_display')}, next run {job.get('next_run_at')}"
    )

    if a.no_run:
        return 0
    print("first run:")
    r = subprocess.run([str(wrapper)], text=True, capture_output=True)
    print((r.stdout + r.stderr).strip() or "nothing to change")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
