"""
status_files.py
Purpose: The status files and freshness view (cutover comment capability 9): which state files the ops center reads, how big each is and how long ago it was last written,
         with the server deciding which are stale (ops-center-layout rule 4: the client holds no threshold). Names, sizes and times only, never contents.
Date:    2026-11-22
Source:  the `*.json` files directly inside <state>/dashboard (the dataset folder), skipping names that start with a dot and anything that is not a plain file.
Params:  OPSCENTER_STATUS_FRESH_MIN   minutes after which a file counts as stale (default 1440, one day; a bad value falls back to it)
Route:   GET /api/status-files    {generated_utc, stale_after_min, files: [{name, size, updated_utc, age_min, state fresh|stale}], counts: {fresh, stale}}
         Oldest first, at most 200 files. A folder that does not exist is an empty list, not an error.
"""

import datetime as dt
import os
import time

import stores

MAX = 200


def stale_after_min():
    try:
        return max(1, int(os.environ.get("OPSCENTER_STATUS_FRESH_MIN") or 1440))
    except ValueError:
        return 1440


def get(now=None):
    now = time.time() if now is None else now
    limit = stale_after_min()
    files = []
    try:
        entries = sorted(stores.dash().iterdir())
    except OSError:
        entries = []
    for p in entries:
        if p.name.startswith(".") or p.suffix != ".json" or not p.is_file() or p.is_symlink():
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        age = max(0, int((now - st.st_mtime) // 60))
        files.append(
            {
                "name": p.name,
                "size": st.st_size,
                "updated_utc": dt.datetime.fromtimestamp(st.st_mtime, dt.timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "age_min": age,
                "state": "stale" if age > limit else "fresh",
            }
        )
    files.sort(key=lambda f: -f["age_min"])
    files = files[:MAX]
    return {
        "generated_utc": dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "stale_after_min": limit,
        "files": files,
        "counts": {
            "fresh": sum(1 for f in files if f["state"] == "fresh"),
            "stale": sum(1 for f in files if f["state"] == "stale"),
        },
    }
