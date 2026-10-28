"""The request gate: Host and Origin guard, body cap, security headers and the cache class of a response.

The trust boundary is "can reach this loopback port". A request is served only when its Host header names the loopback address and the
port the server listens on (a DNS rebinding page cannot set Host to that), a write also needs a same origin Origin header when the
browser sends one, and a cross site fetch is refused. The core never answers `Access-Control-Allow-Origin: *`: a preflight is answered
only for the origins the consumer lists (OPSCENTER_PLUGIN_ORIGINS, a comma separated list, none by default).

Config (environment): OPSCENTER_ALLOWED_HOSTS (extra Host names, comma separated, for example a reverse proxy name), OPSCENTER_MAX_BODY
(bytes, default 1048576).
"""

import os

MAX_BODY = int(os.environ.get("OPSCENTER_MAX_BODY") or 1_048_576)
# Responses under these prefixes carry personal data and are never cached by the browser.
NO_STORE_PREFIXES = (
    "/api/one-on-ones",
    "/api/action-center/replied",
    "/api/yearly-reviews",
    "/api/team",
    "/api/member",
    "/api/plans",
)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def _csv(name):
    return [x.strip() for x in (os.environ.get(name) or "").split(",") if x.strip()]


def allowed_hosts(port):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    hosts.update(_csv("OPSCENTER_ALLOWED_HOSTS"))
    return hosts


def host_ok(headers, port):
    return (headers.get("Host") or "") in allowed_hosts(port)


def origin_ok(headers, port):
    """A write passes when it carries no Origin (a non browser client on the loopback) or an Origin whose host is an allowed Host.
    A browser also sends Sec-Fetch-Site: a cross site value is refused."""
    if (headers.get("Sec-Fetch-Site") or "same-origin") not in ("same-origin", "none", "same-site"):
        return False
    origin = headers.get("Origin")
    if not origin:
        return True
    host = origin.split("://", 1)[-1]
    return host in allowed_hosts(port)


def preflight_origin(headers):
    """The origin a preflight may be answered for, else None."""
    origin = headers.get("Origin") or ""
    return origin if origin and origin in _csv("OPSCENTER_PLUGIN_ORIGINS") else None


def cache_control(method, path):
    if method != "GET" or path.startswith(NO_STORE_PREFIXES):
        return "no-store"
    return "no-cache"


def check_request(method, path, headers, port):
    """None when the request may go ahead, else (status, message)."""
    if not host_ok(headers, port):
        return 403, "local only"
    if method in ("POST", "PUT", "PATCH", "DELETE") and not origin_ok(headers, port):
        return 403, "cross origin write refused"
    return None
