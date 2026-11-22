"""
drafts.py
Purpose: Drafts the owner keeps beside the Action Center (cutover comment capability 5): list them, archive one, and write a reply draft that sits threaded in the mailbox.
         Automation never sends: there is no send route and no delete route, a draft can be archived and restored and nothing more. A provider slot, because the
         mailbox is the consumer's.
Date:    2026-11-21
Provider (`OPSCENTER_DRAFTS_PROVIDER=path/to/file.py:ClassName`, every method optional, a missing one is a 501):
         drafts() -> [{id, title, kind?, thread?, updated?, archived?}]   kind is reply or doc; thread is the conversation a reply belongs to
         archive(id) -> {ok}            move a draft out of the way; it is kept, never deleted
         restore(id) -> {ok}            bring an archived draft back
         reply(thread, text) -> {id}    create a reply draft threaded under `thread`; it is a draft in the mailbox and is never sent from here
         authorize(headers, action, key) -> actor | falsy    actions drafts.read and drafts.write; the null default refuses everything
Routes:  GET  /api/drafts                    {fetched_utc, drafts: [{id, title, kind, thread, updated, archived}], error?}
         POST /api/drafts/archive            {id, confirm: true}
         POST /api/drafts/restore            {id, confirm: true}
         POST /api/drafts/reply              {thread, text, confirm: true} -> {id}
         There is deliberately no send route and no delete route (drafts_test.py asserts the route table).
"""

import datetime as dt
import re

import optional_provider as op

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:=@+-]{0,199}$")
MAX = 200


class Refused(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(v, n):
    return " ".join(str(v if v is not None else "").split())[:n]


def _row(d):
    if not isinstance(d, dict) or not ID.match(str(d.get("id", ""))):
        return None
    kind = _text(d.get("kind"), 10).lower()
    return {
        "id": str(d["id"]),
        "title": _text(d.get("title"), 200) or "(no subject)",
        "kind": kind if kind in ("reply", "doc") else "doc",
        "thread": _text(d.get("thread"), 200) or None,
        "updated": _text(d.get("updated"), 40) or None,
        "archived": d.get("archived") is True,
    }


def read(provider):
    out = {"fetched_utc": _now(), "drafts": [], "error": None}
    fn = op.method(provider, "drafts")
    if fn is None:
        out["error"] = "the provider has no drafts method"
        return out
    try:
        got = fn()
        if not isinstance(got, list):
            raise TypeError("the source did not return a list")
        out["drafts"] = [r for r in (_row(x) for x in got) if r][:MAX]
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"the drafts could not be read ({type(exc).__name__})"
    return out


def _confirmed(payload):
    if payload.get("confirm") is not True:
        raise ValueError("confirm must be true")


def _id(payload):
    ident = str(payload.get("id") or "")
    if not ID.match(ident):
        raise ValueError("id must be a draft id")
    return ident


def _need(provider, name):
    fn = op.method(provider, name)
    if fn is None:
        raise Refused(f"the provider has no {name} method", 501)
    return fn


def _ok(got):
    return bool(got.get("ok")) if isinstance(got, dict) else bool(got)


def archive(provider, payload, restore=False):
    ident = _id(payload)
    _confirmed(payload)
    return {
        "id": ident,
        "ok": _ok(_need(provider, "restore" if restore else "archive")(ident)),
        "archived": not restore,
    }


def reply(provider, payload):
    _confirmed(payload)
    thread, text = str(payload.get("thread") or ""), str(payload.get("text") or "").strip()
    if not ID.match(thread):
        raise ValueError("thread must be a conversation id")
    if not text:
        raise ValueError("text is required")
    got = _need(provider, "reply")(thread, text[:20000])
    ident = str(got.get("id") or "") if isinstance(got, dict) else ""
    if not ID.match(ident):
        raise Refused("the provider returned no draft id", 502)
    return {"id": ident, "thread": thread, "sent": False}


def register(r, provider):
    def guard(action, fn):
        def run(q):
            op.actor_of(q.headers, provider, action)
            return fn(q)

        return run

    r.add("GET", "/api/drafts", guard("drafts.read", lambda q: read(provider)), name="drafts.get")
    r.add(
        "POST",
        "/api/drafts/archive",
        guard("drafts.write", lambda q: archive(provider, q.payload())),
        name="drafts.archive",
    )
    r.add(
        "POST",
        "/api/drafts/restore",
        guard("drafts.write", lambda q: archive(provider, q.payload(), True)),
        name="drafts.restore",
    )
    r.add(
        "POST",
        "/api/drafts/reply",
        guard("drafts.write", lambda q: reply(provider, q.payload())),
        name="drafts.reply",
    )
