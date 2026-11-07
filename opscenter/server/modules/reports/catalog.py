"""
catalog.py
Purpose: A catalog of entries (for example browser extensions) resolved once at ingest through a lookup slot and cached (reports module R6): a hit for
         30 days, a miss for 7 days, an outage is never cached as a miss and pauses lookups for an hour. A publisher a person typed in is kept as
         is: a lookup never overwrites it and it never expires, and removing it sends the entry back to the lookup. Ids that do not match the
         configured pattern are junk and are ignored.
Date:    2026-11-07
Notes:   Ported from the reference implementation. Its store endpoint is the lookup slot here: `fetch(entry_id) -> {status: found|not_found, store,
         name, publisher, installs}`, raising `CatalogUnavailable` for a transient failure (network, 5xx, rate limit). The id pattern is
         configuration (`id_re`; the reference's is 32 letters a to p).
API:     Catalog(id_re=r"^[A-Za-z0-9._-]{1,64}$"): .stale(values) .enrich(values, fetch, now=None) .stats() .expire() .get(id)
         .save_known_publisher(id, publisher, name=None) .remove_known_publisher(id) .list_known_publishers() .reset_pause()
"""

from __future__ import annotations

import datetime as dt
import re

from . import lookup_db

FOUND_TTL = dt.timedelta(days=30)
MISS_TTL = dt.timedelta(days=7)
PAUSE = dt.timedelta(hours=1)
MAX_PER_RUN = 100


class CatalogUnavailable(Exception):
    """A transient failure of the lookup: retried later, never cached as a miss."""


def _stamp(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Catalog:
    def __init__(self, id_re=r"^[A-Za-z0-9._-]{1,64}$"):
        self.id_re = re.compile(id_re)
        self._blocked_until = None
        self._in_flight = set()

    def reset_pause(self):
        self._blocked_until = None

    def _ids(self, values):
        return {
            k
            for k in (v.strip().lower() if isinstance(v, str) else "" for v in values)
            if self.id_re.match(k)
        }

    def stale(self, values, now=None):
        """Ids among `values` that need a lookup: unseen, or past their time to live. A person's entry never needs one."""
        ids = self._ids(values)
        if not ids:
            return []
        now = now or dt.datetime.now(dt.timezone.utc)
        con = lookup_db.connect()
        try:
            out = []
            for i in sorted(ids):
                row = con.execute(
                    "SELECT status, resolved_at, manual FROM log_catalog WHERE entry_id = ?", (i,)
                ).fetchone()
                if not row:
                    out.append(i)
                elif row["manual"]:
                    continue
                elif row["resolved_at"] <= _stamp(
                    now - (FOUND_TTL if row["status"] == "found" else MISS_TTL)
                ):
                    out.append(i)
            return out
        finally:
            con.close()

    def enrich(self, values, fetch, now=None):
        """Look up the stale ids. An outage pauses lookups for an hour and caches nothing; a manual entry is never overwritten. Returns how many
        were resolved."""
        now = now or dt.datetime.now(dt.timezone.utc)
        if self._blocked_until and now < self._blocked_until:
            return 0
        todo = [i for i in self.stale(values, now) if i not in self._in_flight][:MAX_PER_RUN]
        done = 0
        con = lookup_db.connect()
        try:
            for i in todo:
                self._in_flight.add(i)
                try:
                    listing = fetch(i)
                    con.execute(
                        "INSERT INTO log_catalog (entry_id, status, store, name, publisher, installs, resolved_at) VALUES (?,?,?,?,?,?,?) "
                        "ON CONFLICT(entry_id) DO UPDATE SET status=excluded.status, store=excluded.store, name=excluded.name, publisher=excluded.publisher, "
                        "installs=excluded.installs, resolved_at=excluded.resolved_at WHERE log_catalog.manual = 0",
                        (
                            i,
                            listing["status"],
                            listing.get("store"),
                            listing.get("name"),
                            listing.get("publisher"),
                            listing.get("installs"),
                            _stamp(now),
                        ),
                    )
                    con.commit()
                    done += 1
                except Exception:  # noqa: BLE001 - an outage (or any failure) pauses lookups and caches nothing
                    self._blocked_until = now + PAUSE
                    break
                finally:
                    self._in_flight.discard(i)
            return done
        finally:
            con.close()

    def get(self, entry_id):
        con = lookup_db.connect()
        try:
            r = con.execute(
                "SELECT * FROM log_catalog WHERE entry_id = ?", (str(entry_id).strip().lower(),)
            ).fetchone()
            return (
                None
                if not r
                else {
                    "id": r["entry_id"],
                    "status": r["status"],
                    "store": r["store"],
                    "name": r["name"],
                    "publisher": r["publisher"],
                    "installs": r["installs"],
                    "manual": bool(r["manual"]),
                }
            )
        finally:
            con.close()

    def stats(self):
        con = lookup_db.connect()
        try:
            by = {
                r["status"]: r["n"]
                for r in con.execute(
                    "SELECT status, COUNT(*) AS n FROM log_catalog GROUP BY status"
                )
            }
            return {"found": by.get("found", 0), "notFound": by.get("not_found", 0)}
        finally:
            con.close()

    def expire(self):
        """Mark every looked-up entry stale (a person's entry is left alone)."""
        con = lookup_db.connect()
        try:
            n = con.execute(
                "UPDATE log_catalog SET resolved_at = '1970-01-01 00:00:00' WHERE manual = 0"
            ).rowcount
            con.commit()
            return n
        finally:
            con.close()

    def save_known_publisher(self, entry_id, publisher, name=None):
        """A publisher a person entered, for entries no lookup covers. Kept as is; a later lookup never overwrites it."""
        i, pub = str(entry_id).strip().lower(), str(publisher or "").strip()[:200]
        if not self.id_re.match(i):
            raise ValueError(f'"{str(entry_id)[:40]}" is not a valid id')
        if not pub:
            raise ValueError("Publisher is required")
        nm = (str(name).strip()[:200] or None) if name else None
        con = lookup_db.connect()
        try:
            con.execute(
                "INSERT INTO log_catalog (entry_id, status, store, name, publisher, installs, resolved_at, manual) VALUES (?, 'found', 'Known publisher', ?, ?, NULL, ?, 1) "
                "ON CONFLICT(entry_id) DO UPDATE SET status='found', store='Known publisher', name=COALESCE(excluded.name, name), publisher=excluded.publisher, "
                "resolved_at=excluded.resolved_at, manual=1",
                (i, nm, pub, _stamp(dt.datetime.now(dt.timezone.utc))),
            )
            con.commit()
        finally:
            con.close()

    def remove_known_publisher(self, entry_id):
        """Remove a person's entry; the id goes back to the lookup on its next pass. True when one was removed."""
        con = lookup_db.connect()
        try:
            n = con.execute(
                "DELETE FROM log_catalog WHERE entry_id = ? AND manual = 1",
                (str(entry_id).strip().lower(),),
            ).rowcount
            con.commit()
            return n > 0
        finally:
            con.close()

    def list_known_publishers(self):
        con = lookup_db.connect()
        try:
            return [
                {
                    "id": r["entry_id"],
                    "publisher": r["publisher"],
                    "name": r["name"],
                    "updatedAt": r["resolved_at"],
                }
                for r in con.execute(
                    "SELECT * FROM log_catalog WHERE manual = 1 ORDER BY lower(publisher), entry_id"
                )
            ]
        finally:
            con.close()
