"""
doc_pipeline.py
Purpose: The document pipeline (cutover comment capability 3): a queue of documents that need writing, a draft of each, a preview, suggested changes in place, an
         approve or reject decision, a restore, and a guarded publish to a document library. The core owns the states, the transitions and the guard; the consumer
         owns the library and the drafting, as a provider slot. Nothing reaches the library except through publish, and publish refuses anything that changed
         after it was approved.
Date:    2026-11-21
States:  queued -> drafted -> approved | rejected -> published      suggested (a change was asked for on a drafted or approved document: the approval is dropped, the next draft clears it)
         restore moves a rejected or published document back to drafted. A new draft of an approved document drops the approval (the text changed).
Store:   <state>/dashboard/doc-pipeline.json  {"docs": {id: {state, version, approved_version?, suggestion?, history: [{at, what, version}]}}}  history keeps the last 20.
Provider (`OPSCENTER_DOCS_PIPELINE_PROVIDER=path/to/file.py:ClassName`, every method optional, a missing one is a 501):
         queue() -> [{id, title, source?}]          what needs a document: exports, merged pull requests, meetings, knowledge gaps (source is plain text)
         draft(id) -> {version, text}               write or rewrite the draft; version changes whenever the text does
         preview(id) -> {version, text}             the current draft as plain text
         suggest(id, text) -> {ok}                  forward a suggested change to the drafter (optional; the core records it either way)
         publish(id, version) -> {ok, detail?}      the guarded write into the library, called only for an approved, unchanged version
         authorize(headers, action, key) -> actor | falsy   actions docs.read and docs.write; the null default refuses everything
Routes:  GET  /api/doc-pipeline                      {fetched_utc, docs: [{id, title, source, state, version, suggestion?}], error?}
         GET  /api/doc-pipeline/preview?id=          {id, version, text}
         POST /api/doc-pipeline/draft                {id}                       -> state drafted
         POST /api/doc-pipeline/suggest              {id, text}                 -> state suggested
         POST /api/doc-pipeline/decide               {id, decision approve|reject, version, confirm: true}
         POST /api/doc-pipeline/restore              {id, confirm: true}
         POST /api/doc-pipeline/publish              {id, version, confirm: true}
"""

import datetime as dt
import fcntl
import re
from pathlib import Path

import optional_provider as op
import stores

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
MAX_QUEUE = 200
KEEP = 20


class Refused(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def _path():
    return stores.dash() / "doc-pipeline.json"


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(v, n):
    return " ".join(str(v if v is not None else "").split())[:n]


def _load():
    d = stores._load_json(_path(), {})
    d = d if isinstance(d, dict) else {}
    d.setdefault("docs", {})
    return d


def _locked(fn):
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with Path(str(p) + ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        d = _load()
        out = fn(d)
        stores._write_json(p, d)
        return out


def _note(rec, what, version=None):
    rec["history"] = (
        [{"at": _now(), "what": what, "version": version}] + list(rec.get("history") or [])
    )[:KEEP]


def _doc_id(payload):
    ident = str(payload.get("id") or "")
    if not ID.match(ident):
        raise ValueError("id must be a document id")
    return ident


def _confirmed(payload):
    if payload.get("confirm") is not True:
        raise ValueError("confirm must be true")


def _need(provider, name):
    fn = op.method(provider, name)
    if fn is None:
        raise Refused(f"the provider has no {name} method", 501)
    return fn


def read(provider):
    out = {"fetched_utc": _now(), "docs": [], "error": None}
    fn = op.method(provider, "queue")
    try:
        queued = fn() if fn else []
        if not isinstance(queued, list):
            raise TypeError("the queue source did not return a list")
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"the document queue could not be read ({type(exc).__name__})"
        return out
    store = _load()["docs"]
    seen = set()
    for q in queued[:MAX_QUEUE]:
        if not isinstance(q, dict) or not ID.match(str(q.get("id", ""))):
            continue
        ident = str(q["id"])
        seen.add(ident)
        rec = store.get(ident) or {}
        out["docs"].append(
            {
                "id": ident,
                "title": _text(q.get("title"), 160) or ident,
                "source": _text(q.get("source"), 40) or None,
                "state": rec.get("state", "queued"),
                "version": rec.get("version"),
                "suggestion": rec.get("suggestion"),
            }
        )
    # A document already moving through the pipeline stays listed even when the source stopped queueing it (a published one is the proof).
    for ident, rec in store.items():
        if ident not in seen and rec.get("state") in ("published", "approved", "rejected"):
            out["docs"].append(
                {
                    "id": ident,
                    "title": rec.get("title") or ident,
                    "source": None,
                    "state": rec["state"],
                    "version": rec.get("version"),
                    "suggestion": None,
                }
            )
    return out


def preview(provider, ident):
    got = _need(provider, "preview")(ident)
    if not isinstance(got, dict) or "text" not in got:
        raise Refused("the provider returned no preview", 502)
    return {
        "id": ident,
        "version": _text(got.get("version"), 80),
        "text": str(got["text"])[:200000],
    }


def draft(provider, payload):
    ident = _doc_id(payload)
    got = _need(provider, "draft")(ident)
    if not isinstance(got, dict) or not got.get("version"):
        raise Refused("the provider returned no draft version", 502)
    version = _text(got["version"], 80)

    def go(d):
        rec = d["docs"].setdefault(ident, {})
        # New text drops an earlier approval: what was approved is no longer what is drafted.
        if rec.get("approved_version") and rec["approved_version"] != version:
            rec.pop("approved_version", None)
        rec.update(
            state="drafted",
            version=version,
            title=_text(payload.get("title"), 160) or rec.get("title") or ident,
        )
        rec.pop("suggestion", None)
        _note(rec, "drafted", version)
        return {"id": ident, "state": "drafted", "version": version}

    return _locked(go)


def suggest(provider, payload):
    ident, text = _doc_id(payload), _text(payload.get("text"), 4000)
    if not text:
        raise ValueError("text is required")
    # Check the state before anything is forwarded: a refused suggestion reaches nobody.
    rec = _load()["docs"].get(ident)
    if not rec or rec.get("state") not in ("drafted", "suggested", "approved"):
        raise Refused("only a drafted or approved document can take a suggestion", 409)
    fn = op.method(provider, "suggest")
    if fn:
        fn(ident, text)

    def go(d):
        rec = d["docs"].get(ident)
        if not rec or rec.get("state") not in ("drafted", "suggested", "approved"):
            raise Refused("only a drafted or approved document can take a suggestion", 409)
        rec.update(state="suggested", suggestion=text)
        rec.pop("approved_version", None)
        _note(rec, "suggested", rec.get("version"))
        return {"id": ident, "state": "suggested"}

    return _locked(go)


def decide(payload):
    ident = _doc_id(payload)
    _confirmed(payload)
    decision, version = str(payload.get("decision") or ""), str(payload.get("version") or "")
    if decision not in ("approve", "reject"):
        raise ValueError("decision must be approve or reject")

    def go(d):
        rec = d["docs"].get(ident)
        if not rec or rec.get("state") != "drafted":
            raise Refused("only a drafted document can be decided", 409)
        if not version or version != rec.get("version"):
            raise Refused("the draft changed since you read it", 409)
        if decision == "approve":
            rec.update(state="approved", approved_version=version)
        else:
            rec.update(state="rejected")
            rec.pop("approved_version", None)
        _note(rec, decision, version)
        return {"id": ident, "state": rec["state"], "version": version}

    return _locked(go)


def restore(payload):
    ident = _doc_id(payload)
    _confirmed(payload)

    def go(d):
        rec = d["docs"].get(ident)
        if not rec or rec.get("state") not in ("rejected", "published"):
            raise Refused("only a rejected or published document can be restored", 409)
        rec.update(state="drafted")
        rec.pop("approved_version", None)
        _note(rec, "restored", rec.get("version"))
        return {"id": ident, "state": "drafted", "version": rec.get("version")}

    return _locked(go)


def publish(provider, payload):
    ident = _doc_id(payload)
    _confirmed(payload)
    version = str(payload.get("version") or "")
    fn = _need(provider, "publish")
    rec = _load()["docs"].get(ident)
    if (
        not rec
        or rec.get("state") != "approved"
        or not version
        or rec.get("approved_version") != version
    ):
        raise Refused("only an approved, unchanged version can be published", 409)
    # The guard re-reads the draft: if it moved on after the approval, nothing is written.
    current = preview(provider, ident)["version"]
    if current != version:
        raise Refused("the draft changed after it was approved; read it and decide again", 409)
    got = fn(ident, version)
    ok = bool(got.get("ok")) if isinstance(got, dict) else bool(got)

    def go(d):
        r = d["docs"][ident]
        if ok:
            r.update(state="published")
        _note(r, "published" if ok else "publish failed", version)
        return {
            "id": ident,
            "ok": ok,
            "detail": _text(got.get("detail"), 200) if isinstance(got, dict) else "",
        }

    return _locked(go)


def register(r, provider):
    def guard(action):
        def wrap(fn):
            def run(q):
                op.actor_of(q.headers, provider, action)
                return fn(q)

            return run

        return wrap

    read_ = guard("docs.read")
    write = guard("docs.write")
    r.add("GET", "/api/doc-pipeline", read_(lambda q: read(provider)), name="doc_pipeline.get")
    r.add(
        "GET",
        "/api/doc-pipeline/preview",
        read_(lambda q: preview(provider, _doc_id({"id": q.arg("id")}))),
        name="doc_pipeline.preview",
    )
    r.add(
        "POST",
        "/api/doc-pipeline/draft",
        write(lambda q: draft(provider, q.payload())),
        name="doc_pipeline.draft",
    )
    r.add(
        "POST",
        "/api/doc-pipeline/suggest",
        write(lambda q: suggest(provider, q.payload())),
        name="doc_pipeline.suggest",
    )
    r.add(
        "POST",
        "/api/doc-pipeline/decide",
        write(lambda q: decide(q.payload())),
        name="doc_pipeline.decide",
    )
    r.add(
        "POST",
        "/api/doc-pipeline/restore",
        write(lambda q: restore(q.payload())),
        name="doc_pipeline.restore",
    )
    r.add(
        "POST",
        "/api/doc-pipeline/publish",
        write(lambda q: publish(provider, q.payload())),
        name="doc_pipeline.publish",
    )
