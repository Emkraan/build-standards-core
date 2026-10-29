"""The route registry: one table of (method, path, handler, kind) so a route is declared once and the gate, the cache class and the error
mapping apply to all of them.

A handler is called with a Request (method, path, query, body, headers, groups) and returns a JSON value (status 200), a (status, value)
pair, or a (status, bytes, content type, headers) tuple for a file. An exception is mapped to a status: an int `status` or `code`
attribute (the modules' own error classes), 400 for ValueError, 404 for KeyError, 502 for anything else the module raised as a read
failure. `kind` is "read" or "write"; a write is POST only and goes through the Origin check.
"""

import re
from dataclasses import dataclass, field


@dataclass
class Request:
    method: str
    path: str
    query: dict = field(default_factory=dict)
    body: object = None
    headers: dict = field(default_factory=dict)
    groups: tuple = ()

    def arg(self, name, default=""):
        v = self.query.get(name)
        return v[0] if v else default

    def payload(self):
        return self.body if isinstance(self.body, dict) else {}


class Route:
    def __init__(self, method, pattern, handler, kind, name):
        self.method, self.handler, self.kind, self.name = method, handler, kind, name
        self.path = pattern.pattern if hasattr(pattern, "fullmatch") else pattern
        self.pattern = pattern if hasattr(pattern, "fullmatch") else re.compile(re.escape(pattern))


class Registry:
    def __init__(self):
        self.routes = []
        self.background = []  # (function, interval seconds) run by the server on daemon threads

    def add(self, method, path, handler, kind=None, name=""):
        kind = kind or ("write" if method == "POST" else "read")
        if (method == "POST") != (kind == "write"):
            raise ValueError("a write is a POST and a POST is a write")
        self.routes.append(
            Route(method, path, handler, kind, name or getattr(handler, "__name__", ""))
        )

    def get(self, path, handler, name=""):
        self.add("GET", path, handler, "read", name)

    def post(self, path, handler, name=""):
        self.add("POST", path, handler, "write", name)

    def match(self, method, path):
        """(route, groups) for the first route that fits, else (None, path_known) where path_known tells 404 from 405."""
        known = False
        for r in self.routes:
            m = r.pattern.fullmatch(path)
            if not m:
                continue
            known = True
            if r.method == method or (method == "HEAD" and r.method == "GET"):
                return r, m.groups()
        return None, known

    def paths(self):
        return sorted({(r.method, r.path) for r in self.routes})


def error_status(exc):
    """The HTTP status a handler exception maps to."""
    for attr in ("status", "code"):
        v = getattr(exc, attr, None)
        if isinstance(v, int) and not isinstance(v, bool) and 400 <= v <= 599:
            return v
    if isinstance(exc, PermissionError):
        return 403
    if isinstance(exc, ValueError):
        return 400
    if isinstance(exc, KeyError):
        return 404
    return 502
