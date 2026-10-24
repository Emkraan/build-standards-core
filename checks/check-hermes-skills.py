#!/usr/bin/env python3
"""Check the shared Hermes skills: every folder under hermes/skills is named core-<name>, has a
SKILL.md whose front matter name equals the folder and whose description starts "Use when", no
hand-written skill carries a date or a ticket id (configurations.md section 6, "Lessons, not logs"),
and the generated core-practices skill is current."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "hermes" / "skills"
GENERATED = {"core-practices"}
# A dated entry or a ticket reference turns a lesson into a log. Version numbers (v1.2.3) are fine.
LOG_MARK = re.compile(
    r"\b20\d\d-[01]\d-[0-3]\d\b|(?<![\w&/])#\d{2,}\b|\b[A-Z][A-Z0-9]{1,9}-\d{1,6}\b"
)


NOT_TICKETS = {"UTF", "SHA", "ISO", "RFC", "AES", "TLS", "HTTP", "UI"}


def log_marks(text: str) -> list:
    return [m for m in LOG_MARK.findall(text) if m.split("-")[0] not in NOT_TICKETS]


def main() -> int:
    errs = []
    for d in sorted(SKILLS.iterdir()) if SKILLS.exists() else []:
        if not d.is_dir():
            continue
        if not d.name.startswith("core-"):
            errs.append(f"{d.relative_to(ROOT)}: shared skills must be named core-<name>")
            continue
        md = d / "SKILL.md"
        if not md.exists():
            errs.append(f"{d.relative_to(ROOT)}: missing SKILL.md")
            continue
        head = md.read_text().split("---")
        front = head[1] if len(head) > 2 else ""
        name = re.search(r"^name:\s*(\S+)\s*$", front, re.M)
        desc = re.search(r"^description:\s*\"?(.*?)\"?\s*$", front, re.M)
        if not name or name.group(1) != d.name:
            errs.append(f"{md.relative_to(ROOT)}: front matter name must be {d.name}")
        if not desc or not desc.group(1).startswith("Use when"):
            errs.append(f"{md.relative_to(ROOT)}: description must start with 'Use when'")
        if d.name not in GENERATED:
            marks = log_marks(md.read_text())
            if marks:
                errs.append(
                    f"{md.relative_to(ROOT)}: {len(marks)} date or ticket id(s), lessons not logs: {', '.join(marks[:5])}"
                )
    gen = subprocess.run(
        [sys.executable, str(ROOT / "hermes" / "build_skills.py"), "--check"],
        capture_output=True,
        text=True,
    )
    if gen.returncode:
        errs.append(gen.stdout.strip())
    for e in errs:
        print(e)
    if not errs:
        print("hermes skills ok")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
