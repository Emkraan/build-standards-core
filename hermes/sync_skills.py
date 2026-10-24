#!/usr/bin/env python3
"""Install the core- skills from this checkout into a consumer's Hermes skills directory.

    python3 hermes/sync_skills.py --dest ~/.hermes/skills/core [--dry-run]

Copies every hermes/skills/core-* folder, adds the standards docs of this checkout as the skill's
references/, removes core-* skills that left the core, and records sha256 hashes in
<dest>/.core-skills.json. A file changed by hand since the last sync is reported and left as is
(exit 3). Only folders whose name starts with core- are ever touched.

Exit codes: 0 synced (or nothing to do), 2 bad arguments, 3 local edits found (others still synced).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "hermes" / "skills"
DOCS = ROOT / "standards"
MANIFEST = ".core-skills.json"
PREFIX = "core-"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _ref() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _wanted() -> dict[str, dict[str, bytes]]:
    """{skill: {relative path: bytes}} for every core- skill, docs added under references/."""
    out: dict[str, dict[str, bytes]] = {}
    for d in sorted(SRC.iterdir()) if SRC.exists() else []:
        if not (d.is_dir() and d.name.startswith(PREFIX)):
            continue
        files = {str(f.relative_to(d)): f.read_bytes() for f in sorted(d.rglob("*")) if f.is_file()}
        if d.name == "core-practices":
            for doc in sorted(DOCS.glob("*.md")):
                files[f"references/{doc.name}"] = doc.read_bytes()
        out[d.name] = files
    return out


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def sync(dest: Path, dry_run: bool = False) -> int:
    dest = dest.expanduser()
    man_path = dest / MANIFEST
    try:
        old = json.loads(man_path.read_text())
    except (OSError, ValueError):
        old = {"files": {}}
    old_files: dict[str, str] = old.get("files", {})
    wanted = _wanted()
    new_files: dict[str, str] = {}
    edited, changed = [], []
    for skill, files in wanted.items():
        for rel, data in files.items():
            key = f"{skill}/{rel}"
            target = dest / skill / rel
            digest = hashlib.sha256(data).hexdigest()
            if target.exists():
                cur = _sha(target)
                if key in old_files and cur != old_files[key] and cur != digest:
                    edited.append(key)  # changed by hand since the last sync: keep it, report it
                    new_files[key] = old_files[key]
                    continue
                if cur == digest:
                    new_files[key] = digest
                    continue
            changed.append(key)
            new_files[key] = digest
            if not dry_run:
                _write(target, data)
    # Files and skills that left the core (only ones this sync installed).
    removed = [k for k in old_files if k not in new_files and k.split("/", 1)[0].startswith(PREFIX)]
    for key in removed:
        target = dest / key
        if target.exists() and _sha(target) != old_files[key]:
            edited.append(key)
            new_files[key] = old_files[key]
            continue
        if not dry_run and target.exists():
            target.unlink()
    if not dry_run:
        for d in dest.iterdir() if dest.exists() else []:
            if (
                d.is_dir()
                and d.name.startswith(PREFIX)
                and d.name not in wanted
                and not any(d.rglob("*.*"))
            ):
                shutil.rmtree(d, ignore_errors=True)
        _write(
            man_path, (json.dumps({"ref": _ref(), "files": new_files}, indent=1) + "\n").encode()
        )
    verb = "would update" if dry_run else "updated"
    print(
        f"{verb} {len(changed)} file(s), removed {len([k for k in removed if k not in new_files])}, ref {_ref()}"
    )
    for k in edited:
        print(f"LOCAL EDIT kept, change it in the core instead: {k}")
    return 3 if edited else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Install the core- skills into a Hermes skills directory."
    )
    ap.add_argument("--dest", required=True, help="the consumer's skills folder for core skills")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    return sync(Path(a.dest), a.dry_run)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
