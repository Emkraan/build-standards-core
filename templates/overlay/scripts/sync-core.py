#!/usr/bin/env python3
"""Copy the core folders (standards, tokens, lint, kit source) from the pinned ref into the overlay.

Usage: python3 scripts/sync-core.py [ref|latest]
Works from any directory (paths resolve from this script's location). Needs the gh CLI signed in
as an account with read access to the core. Rewrites standards.lock with the commit and a content
hash that the offline drift check uses. `latest` resolves to the newest core release. If targets.map
exists, each listed copy is also written to its destination (for example a UI package).

The overlay scripts are refreshed from the core first. When that changes the sync tooling itself
(this script or corehash.py), the sync hands over to the new copy once, so a tooling change takes
effect in the same run instead of the next one.

Parameters rows the core's template sheet has and standards-local/parameters.md lacks are appended to
the sheet with the template's value cell and a marker comment, and named on one line; an existing row
is never changed, so an upgraded overlay never silently misses a parameter.

The template workflows the repo already has (.github/workflows/core-ci.yml, core-drift.yml,
core-update.yml, lint-sweep.yml at the root of the git work tree) are refreshed from the release, keeping
the repo's own settings: the OVERLAY env value, the overlay path prefix of core-drift.yml's relative
paths, and every value the template marks `# core-sync: keep`. No other workflow is touched, and a
template workflow the repo does not have is not added. When core-ci.yml's job names change, the old ->
new required-check names are printed (and appended to the file CORE_SYNC_NOTES names, when set, for a
pull request body): the merge gate must require the new names. A REQUIRED_CHECKS list in a gate workflow
is rewritten in the same sync (core-ci.py required-checks --lists-only --fix); one it cannot edit safely
is named with its file, line and replacement.
"""

import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

import corehash as ch

HANDOVER = "CORE_SYNC_HANDOVER"
SELF = pathlib.Path(__file__).resolve()
TOOLING = (SELF, SELF.parent / "corehash.py")
IGNORE = shutil.ignore_patterns("node_modules", "dist", "__pycache__", "*.test.*", "fixtures")


def fingerprint(paths):
    return [hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None for p in paths]


cfg = ch.read_lock()
REPO = ch.core_repo()
ref = sys.argv[1] if len(sys.argv) > 1 else cfg.get("ref", "main")
if ref == "latest":
    ref = ch.latest_tag(REPO)
tmp = pathlib.Path(tempfile.mkdtemp())
try:
    ch.clone(REPO, tmp / "core", ref)
    sha = subprocess.run(
        ["git", "-C", str(tmp / "core"), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    before = fingerprint(TOOLING)
    tpl = tmp / "core" / "templates" / "overlay" / "scripts"
    for name in ch.OVERLAY_SCRIPTS:
        if (tpl / name).is_file():
            shutil.copyfile(tpl / name, ch.ROOT / "scripts" / name)
    if fingerprint(TOOLING) != before and not os.environ.get(HANDOVER):
        # execve never returns, so the finally block below would not clean up.
        shutil.rmtree(tmp, ignore_errors=True)
        print("sync tooling changed, continuing with the new copy")
        sys.stdout.flush()
        os.execve(sys.executable, [sys.executable, str(SELF), ref], {**os.environ, HANDOVER: "1"})

    for src, dst in ch.SYNC_MAP:
        out = ch.ROOT / dst
        shutil.rmtree(out, ignore_errors=True)
        if (tmp / "core" / src).is_dir():
            shutil.copytree(tmp / "core" / src, out, ignore=IGNORE)
    for src, dst in ch.SYNC_FILES:
        if (tmp / "core" / src).is_file():
            (ch.ROOT / dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tmp / "core" / src, ch.ROOT / dst)
    for src, dst in ch.read_targets():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    added = ch.sync_parameters(tmp / "core", ref)
    if added:
        print(
            f"parameters: added {len(added)} template row(s) to {ch.PARAMETERS_LOCAL} with the template value, "
            f"set them: " + "; ".join(a.split(" (", 1)[0] for a in added)
        )
    refreshed, notes = ch.sync_workflows(tmp / "core")
    if refreshed:
        print("workflows: refreshed " + ", ".join(refreshed) + " (per-repo settings kept)")
    if any(n.startswith("required checks:") for n in notes):
        notes.append(
            "order: a newly required job must already exist on the default branch before the gate lists "
            "it; merge the pull request that adds the job first, then the gate change (or let the gate "
            "read core-ci.yml: templates/overlay/.github/workflows/automerge.yml)"
        )
    cc = ch.ROOT / "scripts" / "core-ci.py"
    if cc.is_file():
        # A merge gate kept as a REQUIRED_CHECKS list in a workflow (a plan with no rulesets) is
        # rewritten in this same sync, so the pull request carries the matching gate; a list the
        # script cannot edit safely is printed with its file, line and replacement.
        r = subprocess.run(
            [sys.executable, str(cc), "required-checks", "--lists-only", "--fix"],
            cwd=str(ch.ROOT),
            capture_output=True,
            text=True,
        )
        fixed = [
            ln
            for ln in (r.stdout + r.stderr).splitlines()
            if ln.startswith(("required-checks: rewrote", "required-checks: cannot"))
        ]
        notes += fixed
    for line in notes:
        print(line)
    if notes and os.environ.get("CORE_SYNC_NOTES"):
        with open(os.environ["CORE_SYNC_NOTES"], "a", encoding="utf8") as f:
            f.write("\n".join(notes) + "\n")
    digest = ch.content_hash()
    ch.write_lock(ref, sha, digest)
    print(f"synced core@{sha[:8]} (content {digest[:12]})")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
