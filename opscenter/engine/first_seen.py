"""
First-seen time per board item.

Why: item age only existed as model prose ("now into a second day" on an ask that arrived that same
morning). The bundler stamps every item with the time it first reached the board, computed from data
the model cannot rewrite, and the board shows it.

Store: state/dashboard/ac-first-seen.json {"first_seen": {fp: iso_utc}}. Single writer is the bundler
(every refresh), written atomically. An item's first seen is the earliest of its own fp and the fp it
aliases to (handled.py), so a re-keyed repeat keeps its age. `backfill` seeds the store from the git
history of the served board file, which carries every item's fp.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path


def _now_iso(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    m = d.get("first_seen") if isinstance(d, dict) else None
    if not isinstance(m, dict):
        raise ValueError(f"{path} has no first_seen map")
    return m


def save(path: Path, seen: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"first_seen": dict(sorted(seen.items()))}, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def stamp(items: list, seen: dict, now: dt.datetime | None = None) -> int:
    """Set item["first_seen"] on every item, recording new fps at now. Returns new count."""
    ts = _now_iso(now)
    added = 0
    for it in items:
        fps = [f for f in (it.get("fp"), it.get("fp_alias_of")) if f]
        if not fps:
            continue
        # Each fp keeps the time it was itself first seen (handled.py reads that to tell a
        # new repeat from an item that was already on the board). The shown age is the
        # earliest of the item's own fp and the fp it aliases to.
        for f in fps:
            if f not in seen:
                seen[f] = ts
                added += 1
        it["first_seen"] = min(seen[f] for f in fps)
    return added


def backfill(repo: Path, rel: str, seen: dict, since: str = "2026-08-01") -> int:
    """Seed first-seen times from the commit history of the served action-center.json.
    Only lowers or adds entries. Returns how many fps it added or moved earlier."""
    log = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "log",
            "--reverse",
            "--since=" + since,
            "--format=%H %cI",
            "--",
            rel,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout.split("\n")
    changed = 0
    for line in log:
        if not line.strip():
            continue
        sha, when = line.split(" ", 1)
        ts = (
            dt.datetime.fromisoformat(when)
            .astimezone(dt.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        p = subprocess.run(
            ["git", "-C", str(repo), "show", f"{sha}:{rel}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if p.returncode != 0:
            continue
        try:
            items = json.loads(p.stdout).get("items", [])
        except ValueError:
            continue
        for it in items:
            for f in (it.get("fp"), it.get("fp_alias_of")):
                if f and (f not in seen or seen[f] > ts):
                    seen[f] = ts
                    changed += 1
    return changed


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Backfill ac-first-seen.json from git history")
    ap.add_argument("--what-if", action="store_true", help="print the count, write nothing")
    a = ap.parse_args()
    root = Path(os.environ.get("OPSCENTER_ROOT") or Path.home() / ".opscenter")
    store = root / "state" / "dashboard" / "ac-first-seen.json"
    m = load(store)
    n = backfill(root, "state/ops-center-app/public/data/action-center.json", m)
    print(
        "backfill: %d fps added or moved earlier, %d total%s"  # noqa: UP031
        % (n, len(m), " (what-if, not written)" if a.what_if else "")
    )
    if not a.what_if:
        save(store, m)
