"""Small code host read helpers the server modules share: the gh binary, one JSON call, a job view, a UTC stamp and a safe wrapper.

GH_BIN names the gh binary (default gh on PATH). `_gh(args)` runs `gh <args>` and returns the parsed JSON ([] for empty output) or
raises RuntimeError with the first 300 characters of the error. `_safe(fn, *args)` returns (value, None) or (None, error text) for the
expected read failures, so one failed read never breaks a page.
"""

import datetime as dt
import json
import os
import shutil
import subprocess

GH = os.environ.get("GH_BIN") or shutil.which("gh") or "gh"


def _utc_now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gh(args, timeout=25):
    p = subprocess.run([GH, *args], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip()[:300])
    return json.loads(p.stdout or "[]")


def _job_view(j):
    steps = [
        {
            "n": st.get("number"),
            "name": st.get("name"),
            "status": st.get("status"),
            "conclusion": st.get("conclusion"),
            "started": st.get("started_at"),
            "completed": st.get("completed_at"),
        }
        for st in j.get("steps") or []
    ]
    return {
        "id": j["id"],
        "name": j.get("name"),
        "status": j.get("status"),
        "conclusion": j.get("conclusion"),
        "runner": j.get("runner_name"),
        "started": j.get("started_at"),
        "completed": j.get("completed_at"),
        "url": j.get("html_url"),
        "steps": steps,
    }


def _safe(fn, *args):
    try:
        return fn(*args), None
    except (RuntimeError, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        return None, str(exc)[:200]
