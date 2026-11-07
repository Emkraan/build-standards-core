"""
sources.py
Purpose: The data source slot (reports module R3). A panel names a stream and a measure, never a store: a source turns that into columns and rows,
         so the dashboard code never sees where the data lives. The local snapshot source (the log intake tables) is the one provided here;
         any other source (a query service, a warehouse) is another object with the same two methods, and a dashboard cannot tell them apart.
Date:    2026-11-07

Contract: source.get_stream(key) -> stream dict | None       (what query.check_spec expects: key, mode, fields)
          source.run(stream, spec) -> {columns: [{name, type}], rows: [[..]], truncated: bool}
          source.options(stream, field, limit) -> [str]       optional; defaults to the distinct non-empty values by row count
A source raises ValueError for a spec it refuses and any other exception for a failure; the dashboard reports either per panel.
API:      LocalSource(get_stream=None, connect=None)    the stream lookup and connection factory default to log intake and query.connect
"""

from __future__ import annotations

from . import query


class LocalSource:
    def __init__(self, get_stream=None, connect=None):
        self._get_stream = get_stream
        self._connect = connect or query.connect

    def get_stream(self, key):
        if self._get_stream:
            return self._get_stream(key)
        from log_intake import stream_store

        return stream_store.get_stream(key)

    def run(self, stream, spec):
        con = self._connect()
        try:
            return query.run_local(stream, spec, con)
        finally:
            con.close()


def options(source, stream, field, limit=200):
    """Distinct values a dropdown can offer, most rows first then sorted by name, from the source's own rows."""
    if hasattr(source, "options"):
        return source.options(stream, field, limit)
    spec = {
        "filters": [{"field": field, "op": "notEmpty"}],
        "groupBy": [field],
        "metrics": ["rows"],
        "columns": [],
        "sort": {"by": "Rows", "dir": "desc"},
        "limit": limit,
    }
    rows = source.run(stream, spec)["rows"]
    return sorted((str(r[0]) for r in rows), key=lambda s: (s.casefold(), s))
