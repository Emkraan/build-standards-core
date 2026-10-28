"""
swr.py
Purpose: Stale-while-revalidate cache shared by every Ops Center backend module. A fresh entry is
         served as is. An expired entry is still served at once and ONE background refresh starts
         (single flight per key), so a page GET never waits on gh, Jira or Anthropic once the
         cache is warm. Only a cold key, an entry older than MAX_STALE_S, or fresh=True computes
         inline, and concurrent callers of the same key share that one computation.
         invalidate() after a write makes the next read compute inline (live-actions rule 4).
Date:    2026-10-13
"""

import threading
import time

MAX_STALE_S = 1800

_lock = threading.Lock()
_mem = {}  # key -> {"at": epoch, "val": value, "has": bool}
_flight = {}  # key -> threading.Event while a computation runs


def _compute(key, fn, since=None):
    """Run fn once per key at a time. Followers wait for the leader and read its result. A value
    computed after `since` (the caller's start) is reused instead of computing again."""
    since = time.time() if since is None else since
    with _lock:
        ent = _mem.get(key)
        if ent and ent["has"] and ent["at"] >= since:
            return ent["val"], ent["at"]
        ev = _flight.get(key)
        leader = ev is None
        if leader:
            ev = _flight[key] = threading.Event()
    if not leader:
        ev.wait(120)
        with _lock:
            ent = _mem.get(key)
        if ent and ent["has"]:
            return ent["val"], ent["at"]
        return _compute(key, fn, since)  # the leader failed, try ourselves
    try:
        val = fn()
        at = time.time()
        with _lock:
            _mem[key] = {"at": at, "val": val, "has": True}
        return val, at
    finally:
        with _lock:
            _flight.pop(key, None)
        ev.set()


def _background(key, fn):
    def run():
        try:
            _compute(key, fn)
        except Exception as exc:  # noqa: BLE001 - keep serving the last good value, log the failure
            print(f"swr refresh {key}: {exc}")

    threading.Thread(target=run, daemon=True, name=f"swr-{key}").start()


def cached_at(key, ttl, fn, fresh=False, max_stale=MAX_STALE_S):
    """(value, computed_at epoch). See the module docstring for the serving rules."""
    now = time.time()
    with _lock:
        ent = _mem.get(key)
        busy = key in _flight
    if ent and ent["has"] and not fresh:
        age = now - ent["at"]
        if age < ttl:
            return ent["val"], ent["at"]
        if age < max_stale:
            if not busy:
                _background(key, fn)
            return ent["val"], ent["at"]
    return _compute(key, fn, now)


def cached(key, ttl, fn, fresh=False, max_stale=MAX_STALE_S):
    return cached_at(key, ttl, fn, fresh=fresh, max_stale=max_stale)[0]


def invalidate(*keys):
    with _lock:
        for k in keys:
            _mem.pop(k, None)


def invalidate_prefix(prefix):
    with _lock:
        for k in [k for k in _mem if str(k).startswith(prefix)]:
            _mem.pop(k, None)


_kicks = set()


def kick(key, fn):
    """Run fn once in the background unless a run for key is already going (for modules that keep
    their own cache and only need the refresh moved off the request path)."""
    with _lock:
        if key in _kicks:
            return
        _kicks.add(key)

    def run():
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - the module keeps its last good value
            print(f"swr kick {key}: {exc}")
        finally:
            with _lock:
                _kicks.discard(key)

    threading.Thread(target=run, daemon=True, name=f"swr-kick-{key}").start()


def peek(key):
    """The cached value for key, or None. Never computes."""
    with _lock:
        ent = _mem.get(key)
    return ent["val"] if ent and ent["has"] else None
