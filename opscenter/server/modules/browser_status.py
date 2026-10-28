"""Flag for the shared automation browser (a browser run headless for sites with no API).

A launcher script (BROWSER_LAUNCHER) has `status` (key=value pairs: mode=headless|visible|down, pages=N,
agent_loaded=yes|no), `show` (opens a visible window for an SSO or MFA sign in) and `hide` (returns it to
headless). If a session never runs `hide`, the window stays on the owner's screen and the keep-alive agent
stays unloaded. get() reports that (visible longer than VISIBLE_ALERT_S, or down longer than DOWN_ALERT_S)
and hide() is the one click fix. The launcher is the single source of truth for mode; this module only
reads it and times it. Optional module (opscenter/DESIGN.md section 12.3, item 16).

Config: BROWSER_LAUNCHER (default <agent home>/scripts/browser-launcher), BROWSER_MAIN_PATTERN (a pgrep -f
pattern for the main browser process, used to time a visible window), BROWSER_VISIBLE_ALERT_S (900),
BROWSER_DOWN_ALERT_S (120).
"""

import datetime as dt
import os
import subprocess
import time

import paths
import swr

LAUNCHER = os.environ.get("BROWSER_LAUNCHER") or str(
    paths.agent_home() / "scripts" / "browser-launcher"
)
VISIBLE_ALERT_S = int(os.environ.get("BROWSER_VISIBLE_ALERT_S", "900"))
DOWN_ALERT_S = int(os.environ.get("BROWSER_DOWN_ALERT_S", "120"))
MAIN_PATTERN = os.environ.get("BROWSER_MAIN_PATTERN", "Browser --.*automation-profile")

_down_since = None  # first read that saw the browser down (server process memory)


def _iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _status():
    out = subprocess.run([LAUNCHER, "status"], capture_output=True, text=True, timeout=15).stdout
    return dict(kv.split("=", 1) for kv in out.split() if "=" in kv)


def _main_started():
    """Start time of the main Edge process on the automation profile, or None."""
    pid = subprocess.run(
        ["pgrep", "-f", MAIN_PATTERN], capture_output=True, text=True, timeout=5
    ).stdout.split()
    if not pid:
        return None
    lstart = subprocess.run(
        ["ps", "-o", "lstart=", "-p", pid[0]], capture_output=True, text=True, timeout=5
    ).stdout
    return dt.datetime.strptime(" ".join(lstart.split()), "%a %b %d %H:%M:%S %Y").timestamp()


def get():
    """Cached 10 s, refreshed in the background (three subprocesses per read, every page polls it)."""
    return swr.cached("browser_status", 10, _get)


def _get():
    global _down_since
    try:
        st = _status()
    except (OSError, subprocess.SubprocessError) as e:
        return {"mode": "unknown", "alert": None, "error": str(e)[:200]}
    mode = st.get("mode", "unknown")
    now = time.time()
    since = None
    if mode == "down":
        _down_since = _down_since or now
        since = _down_since
    else:
        _down_since = None
        try:
            since = _main_started()
        except (OSError, ValueError, subprocess.SubprocessError):
            since = None
    alert = None
    if mode == "visible" and since and now - since >= VISIBLE_ALERT_S:
        alert = "visible"
    elif mode == "down" and since and now - since >= DOWN_ALERT_S:
        alert = "down"
    return {
        "mode": mode,
        "since_utc": _iso(since) if since else None,
        "pages": int(st.get("pages", "0") or 0),
        "agent_loaded": st.get("agent_loaded") == "yes",
        "alert": alert,
    }


def hide():
    """Return the browser to headless under the keep-alive agent. Closes any visible window."""
    global _down_since
    r = subprocess.run([LAUNCHER, "hide"], capture_output=True, text=True, timeout=90)
    if r.returncode != 0:
        raise RuntimeError(
            (r.stderr or r.stdout or f"launcher hide exited {r.returncode}").strip()[:300]
        )
    _down_since = None
    swr.invalidate("browser_status")
    return get()
