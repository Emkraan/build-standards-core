#!/usr/bin/env python3
"""Item contract for the Action Center analysis and the engine step that enforces it.

Purpose: The analysis job reads one file (the bundle) and writes one file (action-center.json).
         Before anything else on the board runs (the routing filter, the handled aliasing), the
         engine checks that file against the contract in board.schema.json:
           - every required field is present and the right type
           - priority is one of critical, high, medium, low
           - keys are unique and never use a prefix the Ops Center owns (oo-, file-, auto-)
           - every candidates_must cid of the run that wrote the file is covered by an item
             (items[].cids) or listed under dropped with a reason
         A file that fails is rejected: the last good file is restored in its place, the bad file is
         kept as action-center.rejected.json, the streak is recorded (the wake gate retries and backs
         off on it) and the caller raises the board alert. Nothing here calls a model, a
         network or another system. Stdlib only, Python 3.9.

Usage:   settle(dash) is called by board_build.load_action_center on every refresh.
         python3 contract.py [file]   validate a file and print the verdict (exit 0 ok, 1 rejected)
Test hooks: AC_WAKE_PATH (the must-consider cids the wake gate saved for the run).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

PRIORITIES = ("critical", "high", "medium", "low")
REQUIRED_TOP = ("generated_utc", "headline", "items", "dropped")
REQUIRED_ITEM_STR = ("key", "priority", "title", "why", "action")
REQUIRED_ITEM_PRESENT_STR = ("owner",)  # present, may be empty (empty means it lands on me)
REQUIRED_ITEM_LIST = ("refs", "sources", "cids")
RESERVED_PREFIXES = ("oo-", "file-", "auto-")  # keys the Ops Center adds itself
QUIET_S = 10  # a file touched in the last seconds may still be mid-write, check it next refresh

GATE_STATE_DIR = Path(
    os.environ.get("AC_GATE_STATE_DIR")
    or os.environ.get("GATE_STATE_DIR")
    or Path.home() / ".opscenter" / "cache" / "cron-gates"
)
WAKE_PATH = Path(os.environ.get("AC_WAKE_PATH") or GATE_STATE_DIR / "action-center-wake.json")

FILE = "action-center.json"
LAST_GOOD = "action-center.last-good.json"
REJECTED = "action-center.rejected.json"
STATE_FILE = "ac-contract-state.json"


def _state_dir():
    return Path(os.environ.get("OPSCENTER_STATE_DIR") or Path.home() / ".opscenter" / "state")


def _is_text(v):
    return isinstance(v, str) and bool(v.strip())


def must_cids(bundle):
    """The candidates_must cids of a bundle (the ones that must end as an item or a drop reason)."""
    out = []
    for c in (bundle or {}).get("candidates_must") or []:
        if isinstance(c, dict) and c.get("cid"):
            out.append(str(c["cid"]))
    return out


def validate(data, must=None):
    """Return a list of error strings, empty when data meets the contract.

    must: the candidates_must cids the run had to consider, or None when they are not known
    (the structural checks still run, coverage does not)."""
    errs = []
    if not isinstance(data, dict):
        return ["the file is not a JSON object"]
    for k in REQUIRED_TOP:
        if k not in data:
            errs.append(f"missing top-level field {k}")
    if "generated_utc" in data and not _is_text(data["generated_utc"]):
        errs.append("generated_utc must be a non-empty string")
    if "headline" in data and not isinstance(data["headline"], str):
        errs.append("headline must be a string")
    items = data.get("items")
    dropped = data.get("dropped")
    if "items" in data and not isinstance(items, list):
        errs.append("items must be a list")
        items = None
    if "dropped" in data and not isinstance(dropped, list):
        errs.append("dropped must be a list")
        dropped = None
    covered = set()
    seen = set()
    for n, it in enumerate(items or []):
        tag = "items[%d]" % n  # noqa: UP031
        if not isinstance(it, dict):
            errs.append(f"{tag} is not an object")
            continue
        if _is_text(it.get("key")):
            tag = "item {}".format(it["key"])
        for k in REQUIRED_ITEM_STR:
            if not _is_text(it.get(k)):
                errs.append(f"{tag}: missing or empty {k}")
        for k in REQUIRED_ITEM_PRESENT_STR:
            if not isinstance(it.get(k), str):
                errs.append(f"{tag}: {k} must be present as a string (empty is allowed)")
        for k in REQUIRED_ITEM_LIST:
            v = it.get(k)
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                errs.append(f"{tag}: {k} must be a list of strings")
        if _is_text(it.get("priority")) and it["priority"] not in PRIORITIES:
            errs.append(
                "{}: priority {!r} is not one of {}".format(
                    tag, it["priority"], ", ".join(PRIORITIES)
                )
            )
        key = it.get("key")
        if isinstance(key, str) and key.strip():
            low = key.lower().strip()
            if low in seen:
                errs.append(f"{tag}: duplicate key")
            seen.add(low)
            if low.startswith(RESERVED_PREFIXES):
                errs.append(
                    "{}: key uses a prefix the Ops Center owns ({})".format(
                        tag, ", ".join(RESERVED_PREFIXES)
                    )
                )
        if isinstance(it.get("cids"), list):
            covered.update(str(c) for c in it["cids"])
    for n, d in enumerate(dropped or []):
        if not isinstance(d, dict):
            errs.append("dropped[%d] is not an object" % n)  # noqa: UP031
            continue
        if not _is_text(d.get("cid")):
            errs.append("dropped[%d]: missing cid" % n)  # noqa: UP031
        if not _is_text(d.get("reason")):
            errs.append("dropped[%d]: missing reason" % n)  # noqa: UP031
        if _is_text(d.get("cid")):
            covered.add(str(d["cid"]))
    if must is not None and items is not None and dropped is not None:
        missing = [c for c in must if c not in covered]
        for c in missing:
            errs.append(
                f"must-consider candidate {c} is neither covered by an item nor listed as dropped"
            )
    return errs


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
        f.write("\n")
    os.replace(tmp, path)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def wake_cids_for(file_mtime, wake_path=None):
    """The must-consider cids the wake gate saved, only when they belong to the run that wrote the
    file (the wake happened before the file was written). None when unknown, so the coverage check
    is skipped and the verdict says so, never guessed."""
    snap = _read_json(wake_path or WAKE_PATH, None)
    if not isinstance(snap, dict) or not isinstance(snap.get("must_cids"), list):
        return None
    try:
        if float(snap.get("woke_at", 0)) > file_mtime:
            return None
    except (TypeError, ValueError):
        return None
    return [str(c) for c in snap["must_cids"]]


def settle(dash, now=None, wake_path=None):
    """Validate the analysis file in the dashboard folder and keep the board on a good file.

    Returns {"status": one of missing, pending, unchanged, accepted, rejected, "errors": [...],
    "coverage_checked": bool, "streak": int}. Every call is cheap when the file did not change
    (one hash). On rejection the last good file is restored over action-center.json with its own
    modification time, so the wake gate sees a run that produced nothing and retries with backoff."""
    dash = Path(dash)
    now = time.time() if now is None else now
    f, good, bad, st_path = dash / FILE, dash / LAST_GOOD, dash / REJECTED, dash / STATE_FILE
    st = _read_json(st_path, {})
    if not isinstance(st, dict):
        st = {}
    if not f.is_file():
        return {
            "status": "missing",
            "errors": [],
            "coverage_checked": False,
            "streak": st.get("streak", 0),
        }
    mtime = f.stat().st_mtime
    if now - mtime < QUIET_S:
        return {
            "status": "pending",
            "errors": [],
            "coverage_checked": False,
            "streak": st.get("streak", 0),
        }
    sha = _sha(f)
    if sha == st.get("good_sha"):
        # Already judged: the file in place is the last good one (the job has not written since, or a
        # rejection restored it). Report the standing verdict, a rejection stays visible until a
        # later file passes. A rejected file never stays in place, it is swapped out at once.
        return {
            "status": "unchanged",
            "errors": st.get("errors", []) if st.get("status") == "rejected" else [],
            "coverage_checked": bool(st.get("coverage_checked")),
            "streak": st.get("streak", 0),
        }
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        parse_err = None
    except (OSError, ValueError) as e:
        data, parse_err = None, f"not valid JSON: {e}"
    must = wake_cids_for(mtime, wake_path)
    errs = [parse_err] if parse_err else validate(data, must)
    st.update({"checked_at": now, "coverage_checked": must is not None})
    if not errs:
        shutil.copy2(f, good)
        st.update(
            {"status": "accepted", "good_sha": sha, "streak": 0, "errors": [], "rejected_sha": ""}
        )
        _write_json(st_path, st)
        return {
            "status": "accepted",
            "errors": [],
            "coverage_checked": must is not None,
            "streak": 0,
        }
    shutil.copy2(f, bad)
    if good.is_file():
        restored = dash / (".restore." + FILE)
        shutil.copy2(good, restored)  # copy2 keeps the last good file's own modification time
        os.replace(restored, f)
    else:
        _write_json(f, {"generated_utc": "", "headline": "", "items": [], "dropped": []})
        os.utime(f, (0, 0))
    st.update(
        {
            "status": "rejected",
            "rejected_sha": sha,
            "rejected_at": now,
            "streak": int(st.get("streak", 0)) + 1,
            "errors": errs[:20],
        }
    )
    _write_json(st_path, st)
    return {
        "status": "rejected",
        "errors": errs,
        "coverage_checked": must is not None,
        "streak": st["streak"],
    }


def main(argv):
    path = Path(argv[1]) if len(argv) > 1 else _state_dir() / "dashboard" / FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"rejected: {e}")
        return 1
    must = wake_cids_for(path.stat().st_mtime)
    errs = validate(data, must)
    print(
        "ok (coverage %s)" % ("checked" if must is not None else "not checked")
        if not errs
        else "rejected:\n" + "\n".join(errs)
    )
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
