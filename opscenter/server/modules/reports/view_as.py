"""
view_as.py
Purpose: Role preview ("view as") is read only (reports module P3). While a preview is on, every request is refused with
         "Preview is read-only." except reads (GET, HEAD, OPTIONS) and a PINNED allowlist of read-only query POSTs: queries that need a
         POST for a body and write nothing. The allowlist is fixed when the checker is built and cannot be added to afterwards; add a
         route to it only if it writes nothing. A path may use `*` for one segment (`/api/reports/*/run`).
Date:    2026-11-07
API:     ViewAs(allowed_posts=[("POST", "/api/reports/query")]) -> .check(method, path) -> (ok, message)
Pure Python, no import side effect.
"""

from __future__ import annotations

import re

READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
MESSAGE = "Preview is read-only."


def _pattern(path):
    return re.compile(
        "^" + "/".join("[^/]+" if seg == "*" else re.escape(seg) for seg in path.split("/")) + "$"
    )


class ViewAs:
    def __init__(self, allowed_posts=()):
        pairs = []
        for method, path in allowed_posts:
            if str(method).upper() != "POST":
                raise ValueError("the allowlist holds POST routes only; reads are always allowed")
            pairs.append(_pattern(str(path).rstrip("/") or "/"))
        self._allowed = tuple(pairs)  # a tuple: pinned

    def check(self, method, path):
        """(True, "") when the request may run in a preview, else (False, "Preview is read-only.")."""
        m = str(method).upper()
        if m in READ_ONLY_METHODS:
            return True, ""
        p = str(path).split("?", 1)[0].rstrip("/") or "/"
        if m == "POST" and any(rx.match(p) for rx in self._allowed):
            return True, ""
        return False, MESSAGE
