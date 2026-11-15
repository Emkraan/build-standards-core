"""
directory.py
Purpose: Account names to directory people, resolved while data is ingested so reports can show real names (reports module R6). Devices send an
         account name (DOMAIN\\sam, sam, or a UPN). Each distinct name is looked up once through the lookup slot and the answer is cached: a
         person for 30 days, a miss for a day, a failure retried after an hour. A computer account, a service account and the posting device are
         stored as "not a person". A name that matches two people is stored as not found, never guessed. Lookups never run in the request path; a
         directory that is not reachable pauses lookups for ten minutes and never fails ingest.
Date:    2026-11-07
Notes:   Ported from the reference implementation. Its directory query is the lookup slot here: `lookup(kind, value) -> [person]` is called with
         `("account", <bare name>)` first, then `("principal", <upn or "<bare>@">)`; a person is {displayName, userPrincipalName, mail, department,
         jobTitle, accountEnabled}. Raise `DirectoryUnavailable` for an outage (no permission, no network). The reference's email field is a
         directory field here too (the reference planned it and had not built it).

API:     account_key(raw), bare_account(raw), is_not_person(raw, device=None), resolve_account(raw, lookup), stale_accounts(values),
         enrich_accounts(values, device, lookup, now=None), directory_stats(), expire_directory(), get_entry(account), reset_pause()
"""

from __future__ import annotations

import datetime as dt

from . import lookup_db

FOUND_TTL = dt.timedelta(days=30)
MISS_TTL = dt.timedelta(days=1)
ERROR_TTL = dt.timedelta(hours=1)
PAUSE = dt.timedelta(minutes=10)
MAX_PER_RUN = 200
NOT_USERS = {"", "unknown", "system", "local service", "network service", "administrator"}

_blocked_until = None
_in_flight = set()


class DirectoryUnavailable(Exception):
    """The directory cannot be reached (an outage or a missing right): lookups pause, nothing is cached as a miss."""


def reset_pause():
    global _blocked_until
    _blocked_until = None


def account_key(raw):
    """The key reports join on: the raw name as sent, trimmed and lowercased."""
    return raw.strip().lower() if isinstance(raw, str) else ""


def bare_account(raw):
    """The bare account name inside DOMAIN\\sam or a UPN."""
    v = raw.strip().lower()
    v = v[v.rfind("\\") + 1 :] if "\\" in v else v
    at = v.find("@")
    return v[:at] if at > 0 else v


def is_not_person(raw, device=None):
    """True for names that are not people: computer accounts (a trailing $), service accounts and the posting device."""
    bare = bare_account(raw)
    if bare in NOT_USERS or bare.endswith("$"):
        return True
    return bool(device) and bare == bare_account(device)


def _empty(status):
    return {
        "status": status,
        "displayName": None,
        "userPrincipalName": None,
        "email": None,
        "department": None,
        "jobTitle": None,
        "enabled": None,
    }


def resolve_account(raw, lookup):
    """Look one account up: the exact account name first, then the principal name. Only a single match counts; several people for one name is
    ambiguous and is not found, never a guess."""
    bare = bare_account(raw)
    attempts = [("account", bare), ("principal", raw.strip().lower() if "@" in raw else f"{bare}@")]
    for kind, value in attempts:
        users = lookup(kind, value)
        if len(users) == 1:
            u = users[0]
            return {
                "status": "found",
                "displayName": u.get("displayName"),
                "userPrincipalName": u.get("userPrincipalName"),
                "email": u.get("mail"),
                "department": u.get("department"),
                "jobTitle": u.get("jobTitle"),
                "enabled": u.get("accountEnabled"),
            }
        if len(users) > 1:
            break
    return _empty("not_found")


def _now(now):
    return now or dt.datetime.now(dt.timezone.utc)


def _stamp(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _save(con, account, e, now):
    con.execute(
        "INSERT INTO log_directory (account, status, display_name, upn, email, department, job_title, enabled, resolved_at) VALUES (?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(account) DO UPDATE SET status=excluded.status, display_name=excluded.display_name, upn=excluded.upn, email=excluded.email, "
        "department=excluded.department, job_title=excluded.job_title, enabled=excluded.enabled, resolved_at=excluded.resolved_at",
        (
            account,
            e["status"],
            e["displayName"],
            e["userPrincipalName"],
            e["email"],
            e["department"],
            e["jobTitle"],
            None if e["enabled"] is None else int(bool(e["enabled"])),
            _stamp(now),
        ),
    )


def stale_accounts(values, now=None):
    """Accounts among `values` that have no fresh answer yet (unseen, or older than their time to live)."""
    keys = {k for k in (account_key(v) for v in values) if k}
    if not keys:
        return []
    now = _now(now)
    con = lookup_db.connect()
    try:
        out = []
        for k in sorted(keys):
            row = con.execute(
                "SELECT status, resolved_at FROM log_directory WHERE account = ?", (k,)
            ).fetchone()
            if not row:
                out.append(k)
                continue
            ttl = (
                ERROR_TTL
                if row["status"] == "error"
                else FOUND_TTL
                if row["status"] == "found"
                else MISS_TTL
            )
            if row["resolved_at"] <= _stamp(now - ttl):
                out.append(k)
        return out
    finally:
        con.close()


def enrich_accounts(values, device, lookup, now=None):
    """Resolve the accounts in freshly ingested rows. Never raises: an outage pauses lookups for ten minutes, any other failure is stored as an
    error (retried after an hour). Returns how many accounts were resolved."""
    global _blocked_until
    now = _now(now)
    if _blocked_until and now < _blocked_until:
        return 0
    todo = [k for k in stale_accounts(values, now) if k not in _in_flight][:MAX_PER_RUN]
    done = 0
    con = lookup_db.connect()
    try:
        for k in todo:
            _in_flight.add(k)
            try:
                if is_not_person(k, device):
                    _save(con, k, _empty("not_user"), now)
                else:
                    _save(con, k, resolve_account(k, lookup), now)
                con.commit()
                done += 1
            except DirectoryUnavailable:
                _blocked_until = now + PAUSE
                break
            except Exception:  # noqa: BLE001 - stored as an error, retried after an hour
                _save(con, k, _empty("error"), now)
                con.commit()
            finally:
                _in_flight.discard(k)
        return done
    finally:
        con.close()


def get_entry(account):
    con = lookup_db.connect()
    try:
        r = con.execute(
            "SELECT * FROM log_directory WHERE account = ?", (account_key(account),)
        ).fetchone()
        if not r:
            return None
        return {
            "account": r["account"],
            "status": r["status"],
            "displayName": r["display_name"],
            "userPrincipalName": r["upn"],
            "email": r["email"],
            "department": r["department"],
            "jobTitle": r["job_title"],
            "enabled": None if r["enabled"] is None else bool(r["enabled"]),
            "resolvedAt": r["resolved_at"],
        }
    finally:
        con.close()


def directory_stats():
    con = lookup_db.connect()
    try:
        by = {
            r["status"]: r["n"]
            for r in con.execute("SELECT status, COUNT(*) AS n FROM log_directory GROUP BY status")
        }
        return {
            "found": by.get("found", 0),
            "notFound": by.get("not_found", 0),
            "notUser": by.get("not_user", 0),
            "error": by.get("error", 0),
        }
    finally:
        con.close()


def expire_directory():
    """Re-resolve everything after a directory change: entries are marked stale and the next ingest refreshes them."""
    con = lookup_db.connect()
    try:
        n = con.execute("UPDATE log_directory SET resolved_at = '1970-01-01 00:00:00'").rowcount
        con.commit()
        return n
    finally:
        con.close()
