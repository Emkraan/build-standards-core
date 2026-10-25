#!/usr/bin/env python3
"""Validate standards-local/exceptions.md and the core-exception markers in the overlay's repo.

Fails (exit 1) when a row is malformed, names a core doc that is not synced, has no review date,
has a review date more than 180 days after approval, is past its review date, or when a
`core-exception: EXC-NNN` marker in a tracked file names an ID that is not in the table. Markers
inside the synced core copies (the lint fixtures in lint-core/) belong to the core and are skipped.

A baseline file (a tracked *baseline*.json, or the file a lint config names under "baseline") that
names an EXC-NNN id missing from the table is a problem too: a ratchet that cites an exception which
is gone proves nothing, and the orphan file hides that.

--json prints the parsed exceptions (id, rule, scope, review_by, days_left) for tooling such as a
nightly ingest, and still exits 1 on any problem.
"""

import datetime
import json
import os
import pathlib
import re
import subprocess
import sys

# CORE_CI_OVERLAY points the checker at the caller's overlay when the reusable workflow runs this pinned copy.
ROOT = (
    pathlib.Path(os.environ["CORE_CI_OVERLAY"]).resolve()
    if os.environ.get("CORE_CI_OVERLAY")
    else pathlib.Path(__file__).resolve().parent.parent
)
TABLE = ROOT / "standards-local" / "exceptions.md"
CORE = ROOT / "standards-core"
HEADER = ["ID", "Rule", "Scope", "Deviation", "Reason", "Owner", "Approved", "Review by"]
MAX_DAYS = 180
ID_RE = re.compile(r"^EXC-\d{3}$")
RULE_RE = re.compile(r"^([a-z0-9-]+\.md) (\d+(?:\.\d+)?)$")
MARK_RE = re.compile(r"core-exception:\s*(EXC-\d{3})")
COPIES = ("standards-core", "tokens-core", "lint-core", "kit-core")


def parse_date(text):
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def rows():
    if not TABLE.is_file():
        return []
    out = []
    header_seen = False
    for n, line in enumerate(TABLE.read_text(encoding="utf8").splitlines(), 1):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells == HEADER:
            header_seen = True
            continue
        if not header_seen or set("".join(cells)) <= set("-: "):
            continue
        out.append((n, cells))
    return out


def tracked_files():
    r = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True
    )
    if r.returncode != 0:
        return [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [ROOT / f for f in r.stdout.splitlines() if f]


def registry_refs():
    """Rule refs in the synced registry, or None when the core predates it."""
    reg = CORE / "rules.json"
    if not reg.is_file():
        return None
    try:
        return {r["ref"] for r in json.loads(reg.read_text(encoding="utf8")).get("rules", [])}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def baseline_files():
    """Tracked baseline files: *baseline*.json anywhere outside the core copies, plus any file a lint
    config in standards-local/ names under "baseline"."""
    out = {
        f
        for f in tracked_files()
        if f.is_file()
        and "baseline" in f.name.lower()
        and f.suffix == ".json"
        and f.relative_to(ROOT).parts[0] not in COPIES
    }
    for cfg in (ROOT / "standards-local").glob("*-lint.json"):
        try:
            name = json.loads(cfg.read_text(encoding="utf8")).get("baseline")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(name, str) and (ROOT / name).is_file():
            out.add(ROOT / name)
    return sorted(out)


def baseline_problems(found):
    bad = []
    for f in baseline_files():
        try:
            text = f.read_text(encoding="utf8")
        except (UnicodeDecodeError, OSError):
            continue
        ids = sorted(set(re.findall(r"EXC-\d{3}", text)))
        missing = [i for i in ids if i not in found]
        if missing:
            bad.append(
                f"{f.relative_to(ROOT)}: baseline names {', '.join(missing)}, not in exceptions.md; "
                "delete the file or restore the exceptions"
            )
    return bad


def main():
    today = datetime.date.today()
    bad, warn = [], []
    found = {}
    refs = registry_refs()
    for n, cells in rows():
        where = f"exceptions.md line {n}"
        if len(cells) != len(HEADER):
            bad.append(f"{where}: expected {len(HEADER)} columns, found {len(cells)}")
            continue
        rec = dict(zip(HEADER, cells))
        eid = rec["ID"]
        if not ID_RE.match(eid):
            bad.append(f'{where}: ID "{eid}" is not EXC-NNN')
            continue
        if eid in found:
            bad.append(f"{where}: {eid} is listed twice")
        m = RULE_RE.match(rec["Rule"])
        if not m:
            bad.append(f'{where}: {eid} rule "{rec["Rule"]}" is not "<doc>.md <section>[.<rule>]"')
        elif CORE.is_dir() and not (CORE / m.group(1)).is_file():
            bad.append(f"{where}: {eid} names {m.group(1)}, which is not in standards-core/")
        elif refs is not None and rec["Rule"] not in refs:
            warn.append(
                f"{where}: {eid} names {rec['Rule']}, which is not a registered rule in standards-core/rules.json"
            )
        if not rec["Scope"] or rec["Scope"].lower() in ("all", "*", "everything"):
            bad.append(
                f"{where}: {eid} needs a specific scope; an exception for everything is a core change"
            )
        for field in ("Deviation", "Reason", "Owner"):
            if not rec[field]:
                bad.append(f"{where}: {eid} has no {field.lower()}")
        approved = parse_date(rec["Approved"])
        review = parse_date(rec["Review by"])
        if not approved or not review:
            bad.append(f"{where}: {eid} needs Approved and Review by as YYYY-MM-DD")
        else:
            if (review - approved).days > MAX_DAYS:
                bad.append(
                    f"{where}: {eid} review date is more than {MAX_DAYS} days after approval"
                )
            if review < today:
                bad.append(
                    f"{where}: {eid} passed its review date {review}; renew it or fix the app and remove the row"
                )
        found[eid] = {
            "id": eid,
            "rule": rec["Rule"],
            "scope": rec["Scope"],
            "owner": rec["Owner"],
            "review_by": rec["Review by"],
            "days_left": (review - today).days if review else None,
        }

    for f in tracked_files():
        if f == TABLE or not f.is_file():
            continue
        if f.relative_to(ROOT).parts[:1] and f.relative_to(ROOT).parts[0] in COPIES:
            continue
        try:
            text = f.read_text(encoding="utf8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for eid in MARK_RE.findall(line):
                if eid not in found:
                    bad.append(
                        f"{f.relative_to(ROOT)} line {n}: marker names {eid}, which is not in exceptions.md"
                    )

    bad += baseline_problems(found)

    if "--json" in sys.argv:
        print(
            json.dumps(
                {"exceptions": list(found.values()), "problems": bad, "warnings": warn}, indent=2
            )
        )
    else:
        for w in warn:
            print(f"::warning::{w}")
        for b in bad:
            print(f"::error::{b}")
        print(f"check-exceptions: {len(found)} exception(s), {len(bad)} problem(s)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
