"""
dateranges.py
Purpose: Date handling for reports (reports module R4 and R7), pure functions with no import side effect.
           R4  A between filter takes whole days in a named time zone: the start day from its local midnight and the end day counted
               in full, across a clock change (a 23 or 25 hour day is still one day). The range is half open in UTC:
               [start of the start day, start of the day after the end day).
           R7  An event dated more than a day ahead (a device with a wrong clock) stays off time based panels in every range, and the
               panel says how many were left off so they can be looked at; they are never dropped silently.
Date:    2026-11-07

API:     parse_between("YYYY-MM-DD,YYYY-MM-DD") -> (start_day, end_day)
         whole_day_range(start_day, end_day, tz) -> (start_utc, end_utc_exclusive)  aware datetimes
         between(ts, start_day, end_day, tz) -> bool          ts is an aware datetime or an ISO 8601 string
         split_future(rows, now, key="at", horizon=timedelta(days=1)) -> (kept, future)
         future_note(count) -> str | None
`tz` is an IANA name or a tzinfo; an unknown zone raises ValueError, so a bad filter is refused instead of guessed.
"""

from __future__ import annotations

import datetime as dt

UTC = dt.timezone.utc
DAY = dt.timedelta(days=1)


def _zone(tz):
    if isinstance(tz, dt.tzinfo):
        return tz
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(str(tz))
    except Exception as exc:  # noqa: BLE001 - an unknown name or a missing tz database
        raise ValueError(f"unknown time zone: {tz!r}") from exc


def _day(value):
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"not a day (YYYY-MM-DD): {value!r}") from exc


def parse_between(text):
    """`start,end` as two whole days. A single day (`2026-03-09`) is that one day. An end before the start is refused."""
    parts = [p.strip() for p in str(text or "").split(",")]
    if len(parts) == 1 and parts[0]:
        parts = [parts[0], parts[0]]
    if len(parts) != 2 or not all(parts):
        raise ValueError("between takes 'start,end' as two days (YYYY-MM-DD)")
    start, end = _day(parts[0]), _day(parts[1])
    if end < start:
        raise ValueError("the end day is before the start day")
    return start, end


def _local_midnight_utc(day, zone):
    return dt.datetime.combine(day, dt.time(0, 0), tzinfo=zone).astimezone(UTC)


def whole_day_range(start_day, end_day, tz):
    """[start of the start day, start of the day after the end day) in UTC, for whole days in the zone. The end day is counted in
    full: a day that is 23 or 25 hours long across a clock change is still one day."""
    zone = _zone(tz)
    start, end = _day(start_day), _day(end_day)
    if end < start:
        raise ValueError("the end day is before the start day")
    return _local_midnight_utc(start, zone), _local_midnight_utc(end + DAY, zone)


def _aware(ts):
    if isinstance(ts, str):
        ts = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def between(ts, start_day, end_day, tz):
    """True when `ts` falls on one of the whole days, inclusive of the whole end day."""
    lo, hi = whole_day_range(start_day, end_day, tz)
    return lo <= _aware(ts).astimezone(UTC) < hi


def split_future(rows, now, key="at", horizon=DAY):
    """(kept, future): rows dated more than `horizon` after `now` are separated, never dropped. A row with no readable date stays in
    `kept` (it is not future dated, and hiding it would be a silent loss)."""
    now = _aware(now)
    kept, future = [], []
    for r in rows:
        try:
            when = _aware(r[key] if isinstance(r, dict) else getattr(r, key))
        except (KeyError, AttributeError, TypeError, ValueError):
            kept.append(r)
            continue
        (future if when - now > horizon else kept).append(r)
    return kept, future


def future_note(count):
    """The note a time panel shows, or None when nothing was left off."""
    if not count:
        return None
    noun = "event" if count == 1 else "events"
    return f"{count} {noun} dated more than a day ahead {'is' if count == 1 else 'are'} left off this chart (a device clock may be wrong)"
