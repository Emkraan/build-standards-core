"""
phone_pairing.py
Purpose: Pairing and alerts for the phone app, on Platform, Host and access (standards/hermes-api-access.md sections 5 and 6): pair a device,
         list the paired devices, send a test notification, remove one, and show whether the API path is healthy. A provider slot: the
         consumer supplies the push plugin's commands, the core owns the routes, the limits and the rules for the one time link.
Date:    2026-11-21
Notes:   Opt in: with no provider (`OPSCENTER_PHONE_PROVIDER` unset) there are no routes and the page shows the setup steps. The pairing link
         is the one secret here. It is issued only on a request that reaches the server on the loopback with no proxy header (a client that came
         through a forwarding proxy, which is what a LAN client looks like, gets 403), by POST, answered with `Cache-Control: no-store`, and it
         is never logged, cached, stored or put in a URL: the handler returns it once in the body and keeps nothing. The page draws it as a QR
         for 60 seconds and never as text. Test and Remove need `confirm: true` in the body, so a stray request changes nothing.

Provider (`path/to/file.py:ClassName`), every method optional, a missing one is the null default:
         status() -> {api_reachable, edge_covers_host, plugin_pinned, plugin_matches_pin, only_api_connected}   each true, false or null (not known)
         devices() -> [{id, name, paired_at?, last_seen?}]
         pair() -> {link}                                   one time link, a string
         test(device_id) -> {ok, detail?}
         remove(device_id) -> {ok}
         authorize(headers, action, key) -> actor | falsy   actions phone.read, phone.pair, phone.test, phone.remove; the null default refuses all
Routes:  GET  /api/phone-access           {fetched_utc, status, devices, truncated, error}
         POST /api/phone-access/pair      {link, expires_in: 60}                      loopback only, 403 otherwise
         POST /api/phone-access/test      {id, confirm: true} -> {ok, detail}
         POST /api/phone-access/remove    {id, confirm: true} -> {ok}
API:     read(provider)  register(registry, provider)
"""

from __future__ import annotations

import datetime as dt
import json
import re

import optional_provider as op

MAX_DEVICES = 50
MAX_TEXT = 120
PAIR_SECONDS = 60
ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
STATUS_KEYS = (
    "api_reachable",
    "edge_covers_host",
    "plugin_pinned",
    "plugin_matches_pin",
    "only_api_connected",
)
PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded", "via")


class Refused(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(v):
    return " ".join(str(v if v is not None else "").split())[:MAX_TEXT]


def _tri(v):
    return v if isinstance(v, bool) else None


def _device(d):
    if not isinstance(d, dict) or not ID_PATTERN.match(str(d.get("id", ""))):
        return None
    return {k: (_text(d.get(k)) or None) for k in ("name", "paired_at", "last_seen")} | {
        "id": str(d["id"])
    }


def read(provider):
    """The page's data. A source that fails is an error and never an empty list, because nothing paired and unable to tell differ."""
    out = {
        "fetched_utc": _now(),
        "status": {k: None for k in STATUS_KEYS},
        "devices": [],
        "truncated": 0,
        "error": None,
    }
    st, dev = op.method(provider, "status"), op.method(provider, "devices")
    try:
        if st:
            got = st()
            if isinstance(got, dict):
                out["status"] = {k: _tri(got.get(k)) for k in STATUS_KEYS}
        if dev:
            rows = dev()
            if not isinstance(rows, list):
                raise TypeError("the devices source did not return a list")
            clean = [d for d in (_device(x) for x in rows) if d]
            out["devices"], out["truncated"] = clean[:MAX_DEVICES], max(0, len(clean) - MAX_DEVICES)
    except Exception as exc:  # noqa: BLE001
        out["error"] = _text(f"the phone access source failed ({type(exc).__name__})")
    return out


def loopback_only(headers):
    """The pairing link goes only to a client on the loopback itself. A forwarding header means a proxy relayed the request, so refuse it."""
    low = {str(k).lower() for k in (headers or {})}
    if low & set(PROXY_HEADERS):
        raise Refused("the pairing link is issued on the host itself only", 403)


def _id_of(body):
    ident = str((body or {}).get("id", ""))
    if not ID_PATTERN.match(ident):
        raise ValueError("id must be a device id")
    if (body or {}).get("confirm") is not True:
        raise ValueError("confirm must be true")
    return ident


def register(r, provider):
    def get(q):
        op.actor_of(q.headers, provider, "phone.read")
        return read(provider)

    def pair(q):
        loopback_only(q.headers)
        op.actor_of(q.headers, provider, "phone.pair")
        fn = op.method(provider, "pair")
        if not fn:
            raise Refused("the provider has no pair method", 501)
        got = fn()
        link = got.get("link") if isinstance(got, dict) else None
        if not isinstance(link, str) or not link:
            raise Refused("the provider returned no link", 502)
        body = json.dumps({"link": link, "expires_in": PAIR_SECONDS}).encode()
        # Raw answer so the response carries no-store; nothing here keeps, logs or caches the link.
        return 200, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"}

    def act(name, method):
        def run(q):
            op.actor_of(q.headers, provider, f"phone.{name}")
            ident = _id_of(q.payload())
            fn = op.method(provider, method)
            if not fn:
                raise Refused(f"the provider has no {method} method", 501)
            got = fn(ident)
            ok = bool(got.get("ok")) if isinstance(got, dict) else bool(got)
            out = {"ok": ok}
            if isinstance(got, dict) and got.get("detail"):
                out["detail"] = _text(got["detail"])
            return out

        return run

    r.add("GET", "/api/phone-access", get, name="phone_pairing.get")
    r.add("POST", "/api/phone-access/pair", pair, name="phone_pairing.pair")
    r.add("POST", "/api/phone-access/test", act("test", "test"), name="phone_pairing.test")
    r.add("POST", "/api/phone-access/remove", act("remove", "remove"), name="phone_pairing.remove")
