#!/usr/bin/env python3
"""The ops center server: stdlib HTTP on the loopback, the route registry, the gate and the static single page app.

  GET /<anything under dist>   the built app, jailed to the dist folder (no traversal, no symlink escape), single page fallback
  /api/...                     the routes of the registry (routes.py builds it from the modules that are present)

Responses carry ETag with 304, gzip when the client takes it, the security headers and the cache class of gate.py. A write answers
before its body is read when the gate refuses it, so a refused POST never reuses its connection.

Config (environment): OPSCENTER_HOST (default 127.0.0.1), OPSCENTER_PORT (default 8766), OPSCENTER_DIST (the built app folder, default
<state>/../app/dist), and everything the modules read (OPSCENTER_STATE_DIR and so on).
"""

import gzip
import hashlib
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gate  # noqa: E402
import registry as reg  # noqa: E402

GZIP_TYPES = ("application/json", "text/", "application/javascript", "image/svg+xml")
GZIP_MIN = 1400
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".map": "application/json",
}


def make_handler(registry, dist, port):
    dist = Path(dist).resolve() if dist else None

    class Handler(BaseHTTPRequestHandler):
        server_version = "OpsCenter/1.0"
        protocol_version = "HTTP/1.1"  # every response carries Content-Length, so a connection serves many requests

        def log_message(self, fmt, *args):
            if os.environ.get("OPSCENTER_ACCESS_LOG"):
                super().log_message(fmt, *args)

        # ---- responses
        def _send(self, code, data, ctype="application/json; charset=utf-8", extra=None):
            if isinstance(data, (dict, list)) or data is None:
                data = json.dumps(data).encode("utf-8")
            elif isinstance(data, str):
                data = data.encode("utf-8")
            path = self.path.split("?", 1)[0]
            cache = gate.cache_control(self.command if self.command != "HEAD" else "GET", path)
            etag = None
            if code == 200 and cache != "no-store":
                etag = 'W/"' + hashlib.sha1(data).hexdigest()[:20] + '"'
                if etag in (self.headers.get("If-None-Match") or ""):
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.send_header("Cache-Control", cache)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            enc = None
            if (
                len(data) >= GZIP_MIN
                and "gzip" in (self.headers.get("Accept-Encoding") or "")
                and ctype.startswith(GZIP_TYPES)
            ):
                data, enc = gzip.compress(data, 5), "gzip"
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            if enc:
                self.send_header("Content-Encoding", enc)
                self.send_header("Vary", "Accept-Encoding")
            if etag:
                self.send_header("ETag", etag)
            self.send_header("Cache-Control", cache)
            for k, v in {**gate.SECURITY_HEADERS, **(extra or {})}.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _error(self, code, msg):
            self._send(code, {"error": str(msg)})

        # ---- static
        def _static(self, urlpath):
            if dist is None:
                return self._error(404, "no app is built")
            rel = urllib.parse.unquote(urlpath.split("?", 1)[0]).lstrip("/") or "index.html"
            target = (dist / rel).resolve()
            try:
                target.relative_to(dist)
            except ValueError:
                return self._error(403, "forbidden")
            if not target.is_file():
                if "." in Path(rel).name:
                    return self._error(404, "not found")
                target = dist / "index.html"  # single page fallback for a route of the app
                if not target.is_file():
                    return self._error(404, "no app is built")
            ctype = (
                CONTENT_TYPES.get(target.suffix.lower())
                or mimetypes.guess_type(str(target))[0]
                or "application/octet-stream"
            )
            self._send(200, target.read_bytes(), ctype)

        # ---- dispatch
        def _dispatch(self, method):
            path = self.path.split("?", 1)[0]
            if method == "POST":
                self.close_connection = True  # a refusal answers before the body is read
            refused = gate.check_request(method, path, self.headers, port)
            if refused:
                return self._error(*refused)
            route, groups = registry.match(method, path)
            if route is None:
                if path.startswith("/api/"):
                    return self._error(
                        405 if groups else 404, "method not allowed" if groups else "not found"
                    )
                if method in ("GET", "HEAD"):
                    return self._static(path)
                return self._error(404, "not found")
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            body = None
            if method == "POST":
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    return self._error(400, "bad Content-Length")
                if n > gate.MAX_BODY:
                    return self._error(413, "body too large")
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else {}
                except ValueError:
                    return self._error(400, "body is not JSON")
            req = reg.Request(method, path, query, body, dict(self.headers), groups)
            try:
                out = route.handler(req)
            except Exception as exc:  # noqa: BLE001 - mapped to a status, never a traceback to the client
                code = reg.error_status(exc)
                if (
                    code >= 500
                    and not getattr(exc, "status", None)
                    and not getattr(exc, "code", None)
                ):
                    print(
                        f"{method} {path}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True
                    )
                return self._error(
                    code,
                    exc
                    if code < 500 or hasattr(exc, "status") or hasattr(exc, "code")
                    else "read failed",
                )
            if isinstance(out, tuple) and len(out) == 4:
                return self._send(out[0], out[1], out[2], out[3])
            if isinstance(out, tuple) and len(out) == 2 and isinstance(out[0], int):
                return self._send(out[0], out[1])
            self._send(200, out)

        def do_GET(self):
            self._dispatch("GET")

        def do_HEAD(self):
            self._dispatch("HEAD")

        def do_POST(self):
            self._dispatch("POST")

        def do_OPTIONS(self):
            origin = gate.preflight_origin(self.headers)
            if not gate.host_ok(self.headers, port) or not origin:
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()

    return Handler


def make_server(registry, dist=None, host="127.0.0.1", port=0):
    """A ThreadingHTTPServer on host:port (port 0 picks a free one); the handler knows the final port for the Host check."""
    srv = ThreadingHTTPServer((host, port), BaseHTTPRequestHandler)
    srv.RequestHandlerClass = make_handler(registry, dist, srv.server_address[1])
    srv.daemon_threads = True
    return srv


def main():
    import routes

    host = os.environ.get("OPSCENTER_HOST") or "127.0.0.1"
    port = int(os.environ.get("OPSCENTER_PORT") or 8766)
    dist = os.environ.get("OPSCENTER_DIST")
    registry = routes.build()
    srv = make_server(registry, dist, host, port)
    print(
        f"ops center on http://{host}:{srv.server_address[1]}/ ({len(registry.routes)} routes)",
        flush=True,
    )
    for fn, every in registry.background:
        threading.Thread(target=_loop, args=(fn, every), daemon=True).start()
    srv.serve_forever()


def _loop(fn, every):
    while True:
        try:
            fn()
        except Exception as exc:  # a sampler must never end the thread
            print(f"background {getattr(fn, '__name__', 'job')}: {exc}", flush=True)
        time.sleep(every)


if __name__ == "__main__":
    main()
