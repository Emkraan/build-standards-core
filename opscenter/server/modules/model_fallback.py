"""Fallback watch: flags calls billed to a usage-billed account while a seat plan account still had headroom.

It is a watch, not a fallback order editor. The usage-billed account is meant to be a failover only, so a call it served while the
first seat plan account was under its limits is a leak. A scheduled run (`python3 model_fallback.py`, every ten minutes) prints the
message of a newly opened incident and nothing otherwise; the page reads the same state through `GET /api/llm-fallback`.

State `<state>/dashboard/llm-fallback.json`: checkpoint_ts (last ledger timestamp judged), team (seat plan usage at the last check),
active (the open incident or null; it closes after QUIET_S with no leak calls), history (the last 10 closed incidents).

Parameters (environment):
  OPSCENTER_FALLBACK_HEADROOM_PCT  a seat plan limit at or above this means fallback is legitimate (default 90)
  OPSCENTER_MODEL_RATES            JSON file {"default": [in, out, cache_read, cache_write], "match": {"<substring of model>": [..]}}
                                   per million tokens, for the estimate in an incident; with no file the estimate is 0
Test hooks: LLMFB_STATE (state path), LLMFB_LEDGER (ledger path), LLMFB_TEAM_JSON (fixed seat plan usage), LLMFB_NOW (epoch).
"""

import json
import os
import time
from pathlib import Path

import model_accounts as ma
import paths

QUIET_S = 3600
MAX_LOOKBACK_S = 2 * 3600
LEDGER_TAIL_BYTES = 8 * 1024 * 1024


def headroom_pct():
    try:
        return float(os.environ.get("OPSCENTER_FALLBACK_HEADROOM_PCT") or 90)
    except ValueError:
        return 90.0


def _state_path():
    return Path(os.environ.get("LLMFB_STATE") or paths.dashboard_dir() / "llm-fallback.json")


def _ledger_path():
    return Path(os.environ["LLMFB_LEDGER"]) if os.environ.get("LLMFB_LEDGER") else ma.ledger_path()


def _now():
    return float(os.environ.get("LLMFB_NOW") or time.time())


def _clock(ts):
    return time.strftime("%H:%M", time.gmtime(ts + ma.display_tz().utcoffset(None).total_seconds()))


def _rates():
    try:
        return json.loads(Path(os.environ["OPSCENTER_MODEL_RATES"]).read_text())
    except (KeyError, OSError, ValueError):
        return {}


def _price(row):
    """List price estimate of one ledger row from the rates file; 0 when none is configured."""
    cfg = _rates()
    model = (row.get("model") or "").lower()
    rate = next(
        (v for k, v in (cfg.get("match") or {}).items() if k.lower() in model), cfg.get("default")
    )
    if not rate:
        return 0.0
    toks = (
        row.get("input_tokens"),
        row.get("output_tokens"),
        row.get("cache_read_tokens"),
        row.get("cache_write_tokens"),
    )
    return sum((t or 0) * p for t, p in zip(toks, rate)) / 1e6


def load_state():
    try:
        return json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {"checkpoint_ts": None, "team": None, "active": None, "history": []}


def save_state(state):
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(path)


def team_usage():
    """{session_pct, weekly_pct, headroom, error} for the highest priority account that is not usage-billed."""
    fixed = os.environ.get("LLMFB_TEAM_JSON")
    if fixed:
        return json.loads(fixed)
    none = {"session_pct": None, "weekly_pct": None, "headroom": None}
    try:
        accts = ma.list_accounts()["accounts"]
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        return {**none, "error": str(exc)[:200]}
    team = next(
        (
            a
            for a in sorted(accts, key=lambda a: a.get("priority", 0))
            if a.get("billing_model") != ma.USAGE
        ),
        None,
    )
    if team is None:
        return {**none, "error": "no seat plan account"}
    limits = team.get("limits") or []
    if team.get("error") or not limits:
        return {**none, "error": team.get("error") or "no limits returned"}
    sess = max((lim["percent"] for lim in limits if lim["kind"] == "session"), default=0)
    week = max((lim["percent"] for lim in limits if lim["kind"] == "weekly_all"), default=0)
    tight = any(
        lim["percent"] >= headroom_pct() or lim.get("severity", "normal") != "normal"
        for lim in limits
    )
    return {"session_pct": sess, "weekly_pct": week, "headroom": not tight, "error": None}


def usage_ids():
    return {cid for cid, model in ma.account_kinds().items() if model == ma.USAGE}


def ledger_rows(since):
    """Ledger rows with ts > since. Reads the tail only (the file is append-only)."""
    rows = []
    path = _ledger_path()
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - LEDGER_TAIL_BYTES))
            if fh.tell():
                fh.readline()  # drop the partial first line
            for line in fh:
                try:
                    r = json.loads(line)
                    if float(r.get("ts") or 0) > since:
                        rows.append(r)
                except ValueError:
                    continue
    except OSError:
        return []
    return rows


def run():
    now = _now()
    state = load_state()
    cp = state.get("checkpoint_ts")
    if cp is None:
        cp = now  # first run: start from now
    since = max(float(cp), now - MAX_LOOKBACK_S)
    rows = ledger_rows(since)
    ids = usage_ids()
    billed = [r for r in rows if r.get("cred_id") in ids]
    team = team_usage()
    team["checked_utc"] = ma._iso(now)
    state["team"] = team
    state["checked_utc"] = ma._iso(now)
    message = ""

    if billed and team.get("headroom") is None:
        # Cannot judge without seat plan usage: hold the checkpoint so these calls are judged on the next run.
        save_state(state)
        return ""

    newest = max((float(r["ts"]) for r in rows), default=since)
    state["checkpoint_ts"] = max(float(cp), newest)

    leak = billed if team.get("headroom") else []
    if leak:
        act = state.get("active")
        opened = act is None
        if opened:
            act = {
                "id": f"fb_{int(float(leak[0]['ts']))}",
                "opened_utc": ma._iso(float(leak[0]["ts"])),
                "calls": 0,
                "est_usd": 0.0,
                "sessions": {},
            }
        for r in leak:
            sid = r.get("session_id") or "?"
            s = act["sessions"].setdefault(
                sid, {"platform": r.get("platform"), "calls": 0, "est_usd": 0.0}
            )
            s["calls"] += 1
            s["est_usd"] = round(s["est_usd"] + _price(r), 4)
            act["calls"] += 1
            act["est_usd"] = round(act["est_usd"] + _price(r), 4)
        last = max(float(r["ts"]) for r in leak)
        act["last_call_utc"] = ma._iso(last)
        act["last_call_ts"] = last
        act["team_session_pct"] = team["session_pct"]
        act["team_weekly_pct"] = team["weekly_pct"]
        state["active"] = act
        if opened:
            top = sorted(act["sessions"].items(), key=lambda kv: -kv[1]["calls"])[:3]
            who = ", ".join(f"{v['platform']} {k} ({v['calls']})" for k, v in top)
            message = (
                "A usage-billed account is serving calls while the seat plan has headroom.\n"
                f"{act['calls']} call(s) since {_clock(float(leak[0]['ts']))}, about ${act['est_usd']:.2f} at list. "
                f"The seat plan is at {team['session_pct']}% session and {team['weekly_pct']}% weekly.\n"
                f"Sessions: {who}."
            )

    act = state.get("active")
    if act and now - float(act.get("last_call_ts") or 0) > QUIET_S:
        act["closed_utc"] = ma._iso(now)
        state["history"] = ([act] + (state.get("history") or []))[:10]
        state["active"] = None

    save_state(state)
    return message


def stale_host():
    fn = getattr(ma.provider(), "stale_host", None)
    try:
        return fn() if callable(fn) else None
    except Exception:
        return None


def get():
    """Server read: the state file plus a ready to render active flag."""
    st = load_state()
    return {
        "checked_utc": st.get("checked_utc"),
        "team": st.get("team"),
        "active": st.get("active"),
        "history": (st.get("history") or [])[:5],
        "stale_host": stale_host(),
    }


if __name__ == "__main__":
    out = run()
    if out:
        print(out)
