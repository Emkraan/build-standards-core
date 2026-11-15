"""
status_source.py
Purpose: Two rules for any card that depends on a collector's status file.
           1. Unknown is never in sync. A status file that is missing, older than its limit, unreadable or not the expected shape
              reads as `unknown`, never as good. `read()` answers `ok` only for a fresh, well formed reading.
           2. A lapsed sign-in is never silent. A collector that needs a signed-in tool keeps serving its last reading, marked
              stale, when the sign-in lapses, and exits non-zero once the lapse has lasted `lapse_s` (default 240 minutes) so the
              Alerts tab raises it. `collect()` is that loop for one collector: it writes the file, tracks the lapse and returns
              the exit code and one line for the log.
         Nothing here names a tool or an estate; the fetch and the sign-in test are the consumer's.
Date:    2026-11-06

File:    {"at": <epoch seconds>, "data": <anything>, "stale": bool, "lapsed_since": <epoch seconds> | null, "error": str | null}
API:     read(path, max_age_s=None, now=None, check=None) -> {state: ok|unknown, reason, data, age_s, stale}
         collect(fetch, path, lapse_s=14400, now=None, is_auth_error=None) -> (exit code, line)
         `fetch()` returns the reading or raises; `is_auth_error(exc)` says the failure is the sign-in (default: AuthLapse).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

LAPSE_S = 240 * 60


class AuthLapse(Exception):
    """The collector's sign-in is no longer valid."""


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read(path, max_age_s=None, now=None, check=None):
    """The reading in `path`, or unknown with the reason. `check(data)` may return a reason string to reject the shape."""
    now = time.time() if now is None else now
    try:
        d = _load(path)
    except FileNotFoundError:
        return {
            "state": "unknown",
            "reason": "no status file yet",
            "data": None,
            "age_s": None,
            "stale": False,
        }
    except (OSError, ValueError):
        return {
            "state": "unknown",
            "reason": "the status file cannot be read",
            "data": None,
            "age_s": None,
            "stale": False,
        }
    if not isinstance(d, dict) or not isinstance(d.get("at"), (int, float)) or "data" not in d:
        return {
            "state": "unknown",
            "reason": "the status file is not the expected shape",
            "data": None,
            "age_s": None,
            "stale": False,
        }
    age = max(0.0, now - float(d["at"]))
    why = check(d["data"]) if check else None
    if why:
        return {
            "state": "unknown",
            "reason": str(why),
            "data": None,
            "age_s": age,
            "stale": bool(d.get("stale")),
        }
    if d.get("stale"):
        return {
            "state": "unknown",
            "reason": "the collector's sign-in lapsed, this is its last reading",
            "data": d["data"],
            "age_s": age,
            "stale": True,
        }
    if max_age_s is not None and age > max_age_s:
        return {
            "state": "unknown",
            "reason": f"the reading is {int(age // 60)} minutes old",
            "data": d["data"],
            "age_s": age,
            "stale": True,
        }
    return {"state": "ok", "reason": "", "data": d["data"], "age_s": age, "stale": False}


def _write(path, rec):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec), encoding="utf-8")
    os.replace(tmp, p)


def collect(fetch, path, lapse_s=LAPSE_S, now=None, is_auth_error=None):
    """One collector run. Returns (exit code, log line). 0 is a fresh reading, or a lapse shorter than `lapse_s` (the last reading is
    kept and marked stale); 1 is a lapse that has lasted `lapse_s` or a failure that is not the sign-in. The last reading is never
    thrown away on a failure, and a failure never writes a reading that looks fresh."""
    now = time.time() if now is None else now
    is_auth_error = is_auth_error or (lambda e: isinstance(e, AuthLapse))
    try:
        prev = _load(path)
        prev = prev if isinstance(prev, dict) else {}
    except (OSError, ValueError):
        prev = {}
    try:
        data = fetch()
    except Exception as e:  # noqa: BLE001 - classified below, never swallowed
        if not is_auth_error(e):
            _write(
                path,
                dict(
                    prev,
                    stale=True,
                    error=str(e)[:200],
                    at=prev.get("at", 0),
                    data=prev.get("data"),
                ),
            )
            return 1, f"collector failed: {str(e)[:160]}"
        since = prev.get("lapsed_since") or now
        _write(
            path,
            {
                "at": prev.get("at", 0),
                "data": prev.get("data"),
                "stale": True,
                "lapsed_since": since,
                "error": "sign-in lapsed",
            },
        )
        minutes = int((now - since) // 60)
        if now - since >= lapse_s:
            return (
                1,
                f"sign-in lapsed for {minutes} minutes, renew it (the last reading is kept, marked stale)",
            )
        return 0, f"sign-in lapsed {minutes} minutes ago, serving the last reading as stale"
    _write(path, {"at": now, "data": data, "stale": False, "lapsed_since": None, "error": None})
    return 0, "ok"
