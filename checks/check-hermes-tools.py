#!/usr/bin/env python3
"""Check the Hermes tool decision registry (hermes/tools.json).

Every entry has an id, a kind (plugin or skill), a decision (adopt, adapt or reject), a reason and
an install hint; plugins name `plugin`, skills name `skill`. Every required tool is named in
hermes/configurations.md, so the registry and the prose cannot drift apart, and every adapted or
adopted required tool has a configurations.md section number in its reason.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REG = ROOT / "hermes" / "tools.json"
DOC = ROOT / "hermes" / "configurations.md"
DECISIONS = {"adopt", "adapt", "reject"}


def main() -> int:
    errs = []
    tools = json.loads(REG.read_text(encoding="utf8"))["tools"]
    doc = DOC.read_text(encoding="utf8")
    seen = set()
    for t in tools:
        tid = t.get("id", "?")
        if tid in seen:
            errs.append(f"{tid}: duplicate id")
        seen.add(tid)
        if t.get("kind") not in ("plugin", "skill"):
            errs.append(f"{tid}: kind must be plugin or skill")
        elif t["kind"] not in t:
            errs.append(f"{tid}: a {t['kind']} entry needs a '{t['kind']}' field")
        if t.get("decision") not in DECISIONS:
            errs.append(f"{tid}: decision must be one of {sorted(DECISIONS)}")
        for f in ("reason", "install_hint"):
            if not t.get(f):
                errs.append(f"{tid}: missing {f}")
        if t.get("required") and tid not in doc:
            errs.append(f"{tid}: required tool is not named in hermes/configurations.md")
        if t.get("required") and t.get("decision") == "reject":
            errs.append(f"{tid}: a rejected tool cannot be required")
        if t.get("required") and not t.get("install"):
            errs.append(f"{tid}: a required tool needs an install command, the nightly job runs it")
    for s in json.loads(REG.read_text(encoding="utf8")).get("settings", []):
        if not (s.get("key") and "value" in s and s.get("reason")):
            errs.append(f"setting {s.get('key', '?')}: needs key, value and reason")
    for e in errs:
        print(e)
    if not errs:
        print(f"hermes tools ok ({len(tools)} decisions)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
