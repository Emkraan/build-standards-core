"""
override_store.py
Purpose: The core helper behind a gate override (ops center layout standard, rules 10 and 11). An override lifts exactly one
         gate for the owner's own work, for a limited time, and it fails closed: the expiry is stored with the entry and
         compared on every read, so nothing has to run to turn an override off; every entry carries the scope (a freeze
         window, a release, a day) it was made for; a missing, unreadable, foreign-scope or expired store means no override.
         One module is the only writer (`OverrideStore.set` and `clear`, under one lock, atomic replace) and every change is
         appended to a log. The gate itself and who owns what are the consumer's: `qualify(key)` is the null-default slot that
         says whether a key may be overridden (an open pull request of the owner's own, for example). Nothing here names an
         estate, a host or a tool.
Date:    2026-11-01

Store file: {"all": {"scope", "until", "set_at"} | absent, "keys": {<key>: {"scope", "until", "set_at", ...extra}}}
            `until` is an ISO 8601 UTC time with a Z; `all` covers every key that qualifies, `keys` one key each.
Reads:      allowed(key, scope) is True only when an entry for the key (or `all`) has this scope and an expiry in the future.
            Anything else, including any error, is False. status(scope) lists what is on right now.
Rule 11:    pending_line(what, within_s) is the one line a card shows after an action until the next pass replaces it ("freeze
            bypassed, the lane re-checks within 3 minutes"), so a card never shows the reason the action just removed.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
from pathlib import Path


class OverrideRefused(Exception):
    """A write that is not allowed (status code in `code`: 400 bad input, 403 not the owner's, 409 nothing to override)."""

    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def _utc(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s):
    return dt.datetime.strptime(str(s), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def pending_line(what, within_s):
    """The line a card shows between an action and the next pass: what was done and when it is re-checked."""
    n = max(1, round(within_s / 60))
    return f"{what}, re-checked within {n} minute{'' if n == 1 else 's'}"


class OverrideStore:
    def __init__(self, path, log=None, clock=None, qualify=None):
        """path: the store file. log: the JSONL log (default beside the store). clock: now as an aware datetime (tests).
        qualify: `fn(key) -> None` that raises OverrideRefused when the key may not be overridden; None allows every key."""
        self.path = Path(path)
        self.log = Path(log) if log else self.path.with_suffix(".log.jsonl")
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self.qualify = qualify

    # ---- reads: fail closed -------------------------------------------------------------------------------------------

    def _read(self):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def _live(self, rec, scope):
        return (
            isinstance(rec, dict)
            and bool(scope)
            and rec.get("scope") == scope
            and _parse(rec["until"]) > self.clock()
        )

    def allowed(self, key, scope):
        """True only for an unexpired entry of this scope for the key or for `all`; any error, anything else is False."""
        try:
            data = self._read()
            return self._live(data.get("all"), scope) or self._live(
                (data.get("keys") or {}).get(key), scope
            )
        except Exception:  # noqa: BLE001 - an override that cannot be read is not an override
            return False

    def status(self, scope):
        """{all: bool, until: str|None, keys: [..]} that are on right now for this scope (empty on any error)."""
        try:
            data = self._read()
            every = data.get("all")
            on = self._live(every, scope)
            keys = sorted(k for k, v in (data.get("keys") or {}).items() if self._live(v, scope))
            return {"all": on, "until": every["until"] if on else None, "keys": keys}
        except Exception:  # noqa: BLE001
            return {"all": False, "until": None, "keys": []}

    # ---- the one writer -----------------------------------------------------------------------------------------------

    def _mutate(self, fn):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix(".lock"), "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                data = self._read()
            except Exception:  # noqa: BLE001 - an unreadable store is rebuilt empty by the next write
                data = {}
            data.setdefault("keys", {})
            fn(data)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)

    def _log(self, rec):
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict({"at": _utc(self.clock())}, **rec)) + "\n")

    def set(self, key, scope, until, who="", **extra):
        """Turn the override on for one key (or `*` for all) in this scope until `until` (an aware datetime)."""
        if not scope:
            raise OverrideRefused("there is nothing to override outside a scope", 409)
        if until <= self.clock():
            raise OverrideRefused("the expiry is already past")
        if key != "*" and self.qualify:
            self.qualify(key)
        rec = dict(extra, scope=scope, until=_utc(until), set_at=_utc(self.clock()))
        if key == "*":
            self._mutate(lambda d: d.update(all=rec))
        else:
            self._mutate(lambda d: d["keys"].__setitem__(key, rec))
        self._log({"action": "on", "key": key, "scope": scope, "until": rec["until"], "who": who})
        return rec

    def clear(self, key, who=""):
        """Take the override back for one key (or `*` for all). The only way to turn one off before its expiry."""
        if key == "*":
            self._mutate(lambda d: d.pop("all", None))
        else:
            self._mutate(lambda d: d["keys"].pop(key, None))
        self._log({"action": "off", "key": key, "who": who})
