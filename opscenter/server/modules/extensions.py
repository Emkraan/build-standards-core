"""
extensions.py
Purpose: The extension manifest (a provider slot, read only): pages a consumer adds to the rail without a change to the core. The consumer
         declares each page as data and the core draws it, so a consumer page is never code in the shell. A page is either a list of rows the
         consumer serves, or a link to a tool the consumer runs. The core owns the shape, the limits, the safe id rule and the two routes
         (issue 308, item 22).
Date:    2026-11-19
Notes:   Opt in: with no provider (`OPSCENTER_EXTENSIONS_PROVIDER` unset) there are no routes and the rail shows nothing extra. Never
         cached, because a page that was removed must leave the rail at once. A source that fails or is slow is reported as an error with no
         pages and never as an empty manifest. A page cannot take a path the core already serves, cannot name a rail group the core does not
         have, and carries no markup: text is plain text and a link is shown only when it is http or https.

Provider (`path/to/file.py:ClassName`):
         extensions(now) -> [<page>]                      the pages as the consumer declares them
         extension_rows(page_id, now) -> [<row>]          the rows of a `list` page, asked only for a page the manifest named
         authorize(headers, action, key) -> actor | falsy action extensions.read, the null default refuses everything
Page:    {id, title, group, kind, url?, lede?}
         id      lower case letters, digits and hyphens, 2 to 40 characters, and not a name the core already uses
         group   Operate | People | Knowledge | Platform, anything else becomes Platform
         kind    list | link. An unknown kind drops the page, because the core cannot draw it
         url     required for a link page, http or https only
Row:     {id, title, detail?, state?, url?, at?}          state is plain text drawn as a pill, url is http or https only
Routes:  GET /api/extensions                              {fetched_utc, pages (at most 12), truncated, error}
         GET /api/extensions/<id>                         {fetched_utc, page, rows (at most 200), truncated, error}, 404 for a page the
                                                          manifest does not name, 502 when the source failed
API:     summarize(pages, now=None)  read(provider, now=None)  read_rows(provider, page_id, now=None)  register(registry, provider)
"""

from __future__ import annotations

import datetime as dt
import re
import threading

import optional_provider as op

MAX_PAGES = 12
MAX_ROWS = 200
MAX_TEXT = 200
TIMEOUT_SECONDS = 8
GROUPS = ("Operate", "People", "Knowledge", "Platform")
KINDS = ("list", "link")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$")
# Every first path segment the core app already serves. A consumer page under one of these would shadow a core page, so it is refused.
RESERVED_IDS = frozenset(
    {
        # Every first path segment the app serves today. extensions_test.py reads App.tsx and fails if one is missing here.
        "action", "backlog", "builds", "core", "debt", "drafts", "history", "infra", "jira", "knowledge", "links", "operations",
        "people", "planning", "plans", "platform", "reviews", "search", "team", "work",
        # The page prefix of this feature, and the paths the server and the static files use.
        "extensions", "api", "assets", "static", "login", "infrastructure",
    }
)  # fmt: skip


def _clip(value, limit=MAX_TEXT):
    text = " ".join(str(value).split()) if value is not None else ""
    return text[:limit]


def _safe_url(value):
    text = _clip(value, 400)
    return text if text.startswith(("https://", "http://")) else None


def _now(now):
    return now if now is not None else dt.datetime.now(dt.timezone.utc).timestamp()


def _stamp(now):
    return dt.datetime.fromtimestamp(_now(now), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _page(raw):
    """One declared page as the client draws it, or None when the core cannot draw it safely."""
    if not isinstance(raw, dict):
        return None
    page_id = _clip(raw.get("id"), 60).lower()
    if not ID_PATTERN.match(page_id) or page_id in RESERVED_IDS:
        return None
    kind = _clip(raw.get("kind"), 20).lower()
    if kind not in KINDS:
        return None
    url = _safe_url(raw.get("url"))
    if kind == "link" and url is None:
        return None
    group = _clip(raw.get("group"), 20)
    group = next((g for g in GROUPS if g.lower() == group.lower()), "Platform")
    return {
        "id": page_id,
        "title": _clip(raw.get("title"), 60) or page_id,
        "group": group,
        "kind": kind,
        "url": url if kind == "link" else None,
        "lede": _clip(raw.get("lede")) or None,
    }


def _row(raw):
    if not isinstance(raw, dict) or raw.get("id") in (None, ""):
        return None
    return {
        "id": _clip(raw.get("id"), 80),
        "title": _clip(raw.get("title")) or "Untitled",
        "detail": _clip(raw.get("detail"), 400) or None,
        "state": _clip(raw.get("state"), 30) or None,
        "url": _safe_url(raw.get("url")),
        "at": _clip(raw.get("at"), 40) or None,
    }


def summarize(pages, now=None):
    """The manifest a client draws: pages that cannot be drawn dropped, a repeated id kept once, capped, with how many were cut."""
    seen, rows = set(), []
    for raw in pages if isinstance(pages, list) else []:
        page = _page(raw)
        if page and page["id"] not in seen:
            seen.add(page["id"])
            rows.append(page)
    return {
        "fetched_utc": _stamp(now),
        "pages": rows[:MAX_PAGES],
        "truncated": max(0, len(rows) - MAX_PAGES),
        "error": None,
    }


def _ask(fn, *args):
    """Run provider code under a limit. Returns (value, error) and never raises, a provider is consumer code."""
    box = {}

    def run():
        try:
            box["value"] = fn(*args)
        except Exception as exc:  # noqa: BLE001 whatever a provider raises is a failed read and not a crash
            box["error"] = type(exc).__name__

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(TIMEOUT_SECONDS)
    if worker.is_alive():
        return None, f"the source did not answer within {TIMEOUT_SECONDS} s"
    if "error" in box:
        return None, f"the source failed ({box['error']})"
    return box.get("value"), None


def _failed(reason, now=None):
    out = summarize([], now)
    out["error"] = reason
    return out


def read(provider, now=None):
    """Ask the provider now. A missing method, an exception or a slow source is an error with no pages."""
    fn = op.method(provider, "extensions")
    if fn is None:
        return _failed("the provider has no extensions method", now)
    value, error = _ask(fn, _now(now))
    if error:
        return _failed(error, now)
    if not isinstance(value, list):
        return _failed("the source did not return a list", now)
    return summarize(value, now)


def read_rows(provider, page_id, now=None):
    """The rows of one `list` page. The page must be one the manifest names, so an id typed into the address bar asks the provider nothing."""
    manifest = read(provider, now)
    out = {
        "fetched_utc": manifest["fetched_utc"],
        "page": None,
        "rows": [],
        "truncated": 0,
        "error": manifest["error"],
    }
    if manifest["error"]:
        return out, 502
    page = next((p for p in manifest["pages"] if p["id"] == page_id), None)
    if page is None:
        out["error"] = "no such page"
        return out, 404
    out["page"] = page
    if page["kind"] != "list":
        return out, 200
    fn = op.method(provider, "extension_rows")
    if fn is None:
        out["error"] = "the provider has no extension_rows method"
        return out, 502
    value, error = _ask(fn, page_id, _now(now))
    if error:
        out["error"] = error
        return out, 502
    if not isinstance(value, list):
        out["error"] = "the source did not return a list"
        return out, 502
    rows = [r for r in (_row(x) for x in value) if r]
    out["rows"] = rows[:MAX_ROWS]
    out["truncated"] = max(0, len(rows) - MAX_ROWS)
    return out, 200


def register(r, provider):
    def manifest(q):
        op.actor_of(q.headers, provider, "extensions.read")
        return read(provider)

    def page(q):
        op.actor_of(q.headers, provider, "extensions.read")
        body, status = read_rows(provider, q.groups[0])
        return body if status == 200 else (status, body)

    r.add("GET", "/api/extensions", manifest, name="extensions.get")
    # The id pattern is in the route, so an address that is not a safe id never reaches the handler or the provider.
    r.add(
        "GET",
        re.compile(r"/api/extensions/([a-z0-9][a-z0-9-]{0,38}[a-z0-9])"),
        page,
        name="extensions.page",
    )
