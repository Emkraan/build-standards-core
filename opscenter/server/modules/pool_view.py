"""
pool_view.py
Purpose: Optional, read-only host pool evidence for the Destroy approval card of a host pool roll. The roll's delete step
         removes the retired session hosts. Before the owner approves, the card shows what the pool looks like right now:
         every retiring host in drain mode with 0 sessions, and at least one new host Available and accepting sessions. The
         read is one command call per pool, cached for a minute, bounded by a timeout, and a failed read says so and leaves
         the card as it was (it never turns into a pass).
Date:    2026-10-26

Off by default. Nothing here knows a cloud: the read is the consumer's command (POOL_VIEW_CMD), so no cloud session or
credential is touched by core. The command is called as `<cmd> hosts <pool resource name>` and prints
{"hosts": [{"name", "status", "allow_new_session", "sessions"}]} (every page already merged); a non-zero exit is a failed read.
The values below reach the command as environment variables POOL_VIEW_SUBSCRIPTION, POOL_VIEW_RESOURCE_GROUP and
POOL_VIEW_API_VERSION.

Configuration: the JSON file POOL_VIEW_CONFIG, each key overridable by POOL_VIEW_<KEY in capitals> (null default: disabled):
  roll_workflow   the workflow path whose run is a pool roll (none: no card is a pool roll)
  pool_prefix     the resource name prefix of a pool; the pool is the prefix plus the name found in the plan
  host_regex      how a retiring host's VM name is read from the plan, with a named group `pool` and `num`
                  (default ^host-(?P<pool>[a-z0-9]+(?:-[a-z0-9]+)*)-(?P<num>\\d{2,3})$)
  subscription, resource_group, api_version   passed through to the command
  cmd             the command (a shell-split string), the same as POOL_VIEW_CMD
"""

import datetime as dt
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

import paths
import swr

TTL_S = 60  # a read newer than this is served as is
MAX_STALE_S = 300  # an older read is never served, the card shows checking until a fresh one lands
CMD_TIMEOUT_S = 25
_DEFAULT_HOST = r"^host-(?P<pool>[a-z0-9]+(?:-[a-z0-9]+)*)-(?P<num>\d{2,3})$"
_VM_TYPES = ("virtual_machine",)


def _cfg(key):
    """Environment POOL_VIEW_<KEY>, else the JSON file's key, else ''."""
    v = os.environ.get("POOL_VIEW_" + key.upper())
    if v:
        return v.strip()
    f = os.environ.get("POOL_VIEW_CONFIG") or str(paths.state_dir() / "pool-view.json")
    try:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    v = d.get(key) if isinstance(d, dict) else None
    return str(v).strip() if isinstance(v, str) else ""


def _prefix():
    return _cfg("pool_prefix")


def _host_re():
    try:
        return re.compile(_cfg("host_regex") or _DEFAULT_HOST)
    except re.error:
        return re.compile(_DEFAULT_HOST)


class PoolReadError(Exception):
    pass


def enabled():
    return bool(_cfg("roll_workflow"))


def is_roll(workflow):
    wf = _cfg("roll_workflow")
    return bool(wf) and (workflow or "") == wf


def _run(argv, timeout=CMD_TIMEOUT_S):
    """One command call with a timeout. Returns stdout or raises PoolReadError (tests patch this)."""
    env = dict(os.environ)
    for k in ("subscription", "resource_group", "api_version"):
        env["POOL_VIEW_" + k.upper()] = _cfg(k)
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        raise PoolReadError(f"the pool read timed out after {timeout}s") from e
    except OSError as e:
        raise PoolReadError(f"the pool read could not start: {e}") from e
    if r.returncode != 0:
        tail = " ".join((r.stderr or r.stdout or "").strip().splitlines()[-2:])[:200]
        raise PoolReadError(f"the pool read exit {r.returncode}: {tail}")
    return r.stdout


def fetch_hosts(pool):
    """[{name, status, allow_new_session, sessions}] for one pool (read only). Raises PoolReadError."""
    cmd = _cfg("cmd")
    if not cmd:
        raise PoolReadError("no pool read command is configured (POOL_VIEW_CMD)")
    try:
        d = json.loads(_run([*shlex.split(cmd), "hosts", f"{_prefix()}{pool}"]) or "{}")
    except ValueError as e:
        raise PoolReadError(f"unreadable answer: {e}") from e
    hosts = []
    for h in (d.get("hosts") if isinstance(d, dict) else None) or []:
        hosts.append(
            {
                "name": str(h.get("name") or "").split("/")[-1].split(".")[0].lower(),
                "status": h.get("status"),
                "allow_new_session": h.get("allow_new_session"),
                "sessions": h.get("sessions"),
            }
        )
    return hosts


def _read(pool):
    """The cached-value shape: never raises, so a failed read is cached for the TTL and not retried per GET."""
    try:
        return {"ok": True, "hosts": fetch_hosts(pool), "at": _now()}
    except PoolReadError as e:
        return {"ok": False, "error": str(e)[:200], "at": _now()}


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_pool(pool, blocking=False):
    """{ok, hosts|error, at} for a pool, or None when no read is cached yet. Not blocking, a cold key
    starts one background read and returns None, so a page GET never waits on the command."""
    key = f"pool-view:{pool}"
    if blocking:
        return swr.cached(key, TTL_S, lambda: _read(pool), max_stale=MAX_STALE_S)
    val = swr.peek(key)
    age = _age_s(val.get("at")) if val else 1e9
    if val is None or age > MAX_STALE_S:
        swr.kick(key, lambda: swr.cached(key, TTL_S, lambda: _read(pool), fresh=True))
        return None
    if age >= TTL_S:
        swr.kick(key, lambda: swr.cached(key, TTL_S, lambda: _read(pool), fresh=True))
    return val


def _age_s(iso):
    try:
        t = dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        return (dt.datetime.now(dt.timezone.utc) - t).total_seconds()
    except (TypeError, ValueError):
        return 1e9


# ---- what the plan retires ----


def _host_name(r):
    """The session host VM name a deleted VM resource carries (matching host_regex), else ''."""
    cands = [(r.get("attrs") or {}).get("name"), r.get("key"), r.get("address")]
    for c in cands:
        for tok in re.findall(r"[a-z0-9][a-z0-9-]*", str(c or "").lower()):
            if _host_re().match(tok):
                return tok
    return ""


def retiring(resources):
    """{pool: sorted host names} for every VM the plan deletes or replaces."""
    out = {}
    for r in resources or []:
        if r.get("action") not in ("destroy", "delete", "replace"):
            continue
        if not any(str(r.get("type") or "").endswith(t) for t in _VM_TYPES):
            continue
        name = _host_name(r)
        m = _host_re().match(name) if name else None
        if m:
            out.setdefault(m.group("pool"), set()).add(name)
    return {p: sorted(h) for p, h in out.items()}


# ---- the verdict ----


def _judge_pool(pool, hosts, retiring_names):
    by = {h["name"]: h for h in hosts}
    gone, rows, problems = [], [], []
    for n in sorted(retiring_names):
        h = by.get(n)
        if not h:
            gone.append(n)
            continue
        drained = h.get("allow_new_session") is False
        idle = h.get("sessions") == 0
        row = dict(h, drained=drained, idle=idle)
        if not drained:
            problems.append(f"{n} is still accepting new sessions (drain mode is off)")
        if h.get("sessions") is None:
            problems.append(f"{n} did not report its session count")
        elif not idle:
            problems.append(
                f"{n} still has {h['sessions']} session{'' if h['sessions'] == 1 else 's'}"
            )
        rows.append(row)
    fresh = [h for h in hosts if h["name"] not in retiring_names]
    ready = [
        h for h in fresh if h.get("status") == "Available" and h.get("allow_new_session") is True
    ]
    if not ready:
        if not fresh:
            problems.append("the pool has no new host")
        else:
            problems.append(
                "no new host is Available and accepting sessions ("
                + ", ".join(f"{h['name']} is {h.get('status') or 'unknown'}" for h in fresh)
                + ")"
            )
    return {
        "pool": pool,
        "pool_name": f"{_prefix()}{pool}",
        "retiring": rows,
        "not_registered": gone,
        "new": fresh,
        "new_ready": len(ready),
        "ok": not problems,
        "problems": problems,
    }


def evidence(resources, roll=None, blocking=False):
    """The pool block of an AVD pool roll card, or None when this run retires no pool host and names no pool.
    status: ok (safe to approve), attention (something is missing), checking (first read in flight),
    unknown (the read failed or the hosts could not be read from the plan)."""
    ret = retiring(resources)
    pools = sorted(set(ret) | set((roll or {}).get("pools") or []))
    if not pools:
        return {
            "kind": "avd-pool-roll",
            "status": "unknown",
            "pools": [],
            "text": "I could not tell which host pool this roll works on, so I have no host evidence. Check the pool "
            "in the cloud console before approving.",
        }
    out, checking, failed, bad = [], False, [], False
    at = []
    for p in pools:
        names = ret.get(p) or []
        rd = read_pool(p, blocking=blocking)
        if rd is None:
            checking = True
            continue
        if not rd.get("ok"):
            failed.append(f"{_prefix()}{p}: {rd.get('error')}")
            continue
        at.append(rd.get("at") or "")
        if not names:
            failed.append(f"{_prefix()}{p}: the plan names no host to retire")
            continue
        j = _judge_pool(p, rd["hosts"], set(names))
        bad = bad or not j["ok"]
        out.append(j)
    ev = {"kind": "avd-pool-roll", "pools": out, "checked_at": min(at) if at else None}
    if failed:
        ev.update(
            status="unknown",
            text="I could not read the host pool ("
            + "; ".join(failed)[:300].replace(";", ",")
            + "). Check the pool "
            "in the cloud console before approving.",
        )
    elif checking:
        ev.update(
            status="checking",
            text="I am reading the host pool now. The evidence appears here in a moment.",
        )
    elif bad:
        ev.update(status="attention", text=_text(out, False))
    else:
        ev.update(status="ok", text=_text(out, True))
    return ev


def _text(pools, ok):
    parts = []
    for j in pools:
        n = len(j["retiring"]) + len(j["not_registered"])
        drained = sum(1 for h in j["retiring"] if h["drained"] and h["idle"])
        bit = (
            f"{j['pool_name']}: {drained} of {n} retiring hosts are in drain mode with 0 sessions"
            + (
                f" ({len(j['not_registered'])} already left the pool)"
                if j["not_registered"]
                else ""
            )
            + f", {j['new_ready']} of {len(j['new'])} new hosts are Available and accepting sessions"
        )
        parts.append(bit)
    body = ". ".join(parts)
    if ok:
        return f"{body}. Every retiring host is drained and a new host is serving, so I recommend approving."
    miss = [x for j in pools for x in j["problems"]]
    shown = ", ".join(miss[:4]).replace(";", ",") + (
        f", and {len(miss) - 4} more" if len(miss) > 4 else ""
    )
    return f"{body}. I do not recommend approving yet: {shown}."
