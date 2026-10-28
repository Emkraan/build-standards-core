"""
desktop_pool.py
Purpose: Host pool evidence for the Destroy approval card of a pool roll (opscenter/DESIGN.md section 12.3, item 14).
         The roll's delete step removes the retired session hosts. Before the owner approves it the card shows what
         the pool looks like right now: every retiring host in drain mode with 0 sessions, and at least one new host
         Available and accepting sessions. The read is one read only cloud GET per pool through az, cached for a
         minute, bounded by a timeout, and a failed read says so and leaves the card as it was (it never turns into
         a pass). Optional module: a consumer without a desktop pool leaves it off.
Parameters (environment, or local/params.json `pool`):
  POOL_SUBSCRIPTION   the cloud subscription id [subscription], required
  POOL_RG             the resource group holding the host pools [resource_group], required
  POOL_PREFIX         the host pool name prefix, the pool name is prefix + pool [prefix], default hostpool-
  POOL_HOST_PREFIX    the session host VM name prefix, hosts are <host_prefix>-<pool>-NN [host_prefix], default host
  POOL_ROLL_WORKFLOW  the roll workflow file that marks a card as a pool roll [roll_workflow]
  POOL_AZ_BIN         the az binary, default the one on PATH
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess

import paths
import swr

AZ = os.environ.get("POOL_AZ_BIN", paths.which("az"))
SUBSCRIPTION = os.environ.get("POOL_SUBSCRIPTION", "")
RESOURCE_GROUP = os.environ.get("POOL_RG", "")
API_VERSION = "2024-04-03"
POOL_PREFIX = os.environ.get("POOL_PREFIX", "hostpool-")
HOST_PREFIX = os.environ.get("POOL_HOST_PREFIX", "host")
ROLL_WORKFLOW = os.environ.get("POOL_ROLL_WORKFLOW", ".github/workflows/pool-roll.yml")
TTL_S = 60  # a read newer than this is served as is
MAX_STALE_S = 300  # an older read is never served, the card shows checking until a fresh one lands
AZ_TIMEOUT_S = 25
MAX_PAGES = 5

_HOST = re.compile(
    r"^" + re.escape(HOST_PREFIX) + r"-(?P<pool>[a-z0-9]+(?:-[a-z0-9]+)*)-(?P<num>\d{2,3})$"
)
_VM_TYPES = ("virtual_machine",)


class PoolReadError(Exception):
    pass


def is_roll(workflow):
    return (workflow or "") == ROLL_WORKFLOW


def _run(argv, timeout=AZ_TIMEOUT_S):
    """One az call with a timeout. Returns stdout or raises PoolReadError (tests patch this)."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise PoolReadError(f"az timed out after {timeout}s") from None
    except OSError as e:
        raise PoolReadError(f"az could not start: {e}") from e
    if r.returncode != 0:
        tail = " ".join((r.stderr or r.stdout or "").strip().splitlines()[-2:])[:200]
        raise PoolReadError(f"az exit {r.returncode}: {tail}")
    return r.stdout


def pool_url(pool):
    return (
        f"https://management.azure.com/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}"
        f"/providers/Microsoft.DesktopVirtualization/hostPools/{POOL_PREFIX}{pool}/sessionHosts"
        f"?api-version={API_VERSION}"
    )


def fetch_hosts(pool):
    """[{name, status, allow_new_session, sessions}] for one pool (read only). Raises PoolReadError."""
    url = pool_url(pool)
    hosts = []
    for _ in range(MAX_PAGES):
        try:
            d = json.loads(
                _run([AZ, "rest", "--method", "get", "--url", url, "--only-show-errors"]) or "{}"
            )
        except ValueError as e:
            raise PoolReadError(f"unreadable answer: {e}") from e
        for h in d.get("value") or []:
            p = h.get("properties") or {}
            vm = str(h.get("name") or "").split("/")[-1].split(".")[0].lower()
            hosts.append(
                {
                    "name": vm,
                    "status": p.get("status"),
                    "allow_new_session": p.get("allowNewSession"),
                    "sessions": p.get("sessions"),
                }
            )
        url = d.get("nextLink")
        if not url:
            return hosts
    raise PoolReadError(f"more than {MAX_PAGES} pages of session hosts")


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
    starts one background read and returns None, so a page GET never waits on Azure."""
    key = f"pool:{pool}"
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
    """The session host VM name a deleted VM resource carries (<host_prefix>-<pool>-NN), else ''."""
    cands = [(r.get("attrs") or {}).get("name"), r.get("key"), r.get("address")]
    for c in cands:
        for tok in re.findall(re.escape(HOST_PREFIX) + r"-[a-z0-9-]+", str(c or "").lower()):
            if _HOST.match(tok):
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
        m = _HOST.match(name) if name else None
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
        "pool_name": f"{POOL_PREFIX}{pool}",
        "retiring": rows,
        "not_registered": gone,
        "new": fresh,
        "new_ready": len(ready),
        "ok": not problems,
        "problems": problems,
    }


def evidence(resources, roll=None, blocking=False):
    """The pool block of a pool roll card, or None when this run retires no pool host and names no pool.
    status: ok (safe to approve), attention (something is missing), checking (first read in flight),
    unknown (the read failed or the hosts could not be read from the plan)."""
    ret = retiring(resources)
    pools = sorted(set(ret) | set((roll or {}).get("pools") or []))
    if not pools:
        return {
            "kind": "pool-roll",
            "status": "unknown",
            "pools": [],
            "text": "Could not tell which host pool this roll works on, so there is no host evidence. Check the pool "
            "in the portal before approving.",
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
            failed.append(f"{POOL_PREFIX}{p}: {rd.get('error')}")
            continue
        at.append(rd.get("at") or "")
        if not names:
            failed.append(f"{POOL_PREFIX}{p}: the plan names no host to retire")
            continue
        j = _judge_pool(p, rd["hosts"], set(names))
        bad = bad or not j["ok"]
        out.append(j)
    ev = {"kind": "pool-roll", "pools": out, "checked_at": min(at) if at else None}
    if failed:
        ev.update(
            status="unknown",
            text="Could not read the host pool ("
            + "; ".join(failed)[:300].replace(";", ",")
            + "). Check the pool "
            "in the portal before approving.",
        )
    elif checking:
        ev.update(
            status="checking",
            text="Reading the host pool now. The evidence appears here in a moment.",
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
        return f"{body}. Every retiring host is drained and a new host is serving, so approving is recommended."
    miss = [x for j in pools for x in j["problems"]]
    shown = ", ".join(miss[:4]).replace(";", ",") + (
        f", and {len(miss) - 4} more" if len(miss) > 4 else ""
    )
    return f"{body}. Approving is not recommended yet: {shown}."
