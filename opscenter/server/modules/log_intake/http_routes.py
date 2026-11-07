"""
http_routes.py
Purpose: The log intake HTTP routes, registered only when a consumer turns the module on (`OPSCENTER_LOG_INTAKE`). Importing this file registers
         nothing and touches nothing; `register(registry, provider)` adds the routes, the sink and the two background tasks.
Date:    2026-11-07
Notes:   Writes are POST (the registry has no PUT or DELETE). The device route authenticates with `X-Api-Key` through the provider's `verify_key`
         (null default refuses every key); every admin route needs the provider's `authorize` (null default refuses everything). The body cap is
         the server's `OPSCENTER_MAX_BODY` (default 1 MiB), which applies before a stream's own post size.

Provider (all optional, `OPSCENTER_LOG_INTAKE_PROVIDER=path/to/file.py:ClassName`):
         verify_key(api_key, integration_key) -> {name} | falsy      authorize(headers, action, key) -> actor | falsy
         on_rows(stream, source, rows)        enrichment, never delays a device      audit(status, details)  a device post's audit line
         audit_event(actor, action, details)  admin audit lines      sink() -> the sink object (name, send(table, rows), has_table, ...)
         extra_reserved() -> [field names a stream may not declare]

Routes:  POST /api/log-streams/<key>/ingest                       device post (X-Api-Key)
         GET  /api/log-streams                                    action log-streams.read         list
         GET  /api/log-streams/<key>                              log-streams.read                one stream with its fields
         POST /api/log-streams                                    log-streams.write               create  {key, name, tableName, fields, ...}
         POST /api/log-streams/<key>/update                       log-streams.write               settings patch
         POST /api/log-streams/<key>/schema                       log-streams.write               {fields, confirm?, dryRun?}
         POST /api/log-streams/<key>/delete                       log-streams.write               {confirmTable}
         GET  /api/log-sink/checks                                log-streams.read                the sink's own checks, normalised
         POST /api/log-streams/<key>/test-row                     log-streams.write               one marked row through the real sink path
         POST /api/log-streams/<key>/test-row/verify              log-streams.read                {marker} whether it reached the sink
Answers:  {success: true, data} or the registry's error mapping (ValueError 400, KeyError 404, PermissionError 403)
"""

from __future__ import annotations

import json

import optional_provider as op

from . import buffer, current_store, forwarder, ingest, sink_check, stream_store

KEY = r"([a-z0-9][a-z0-9-]{1,40})"
JSON_TYPE = "application/json; charset=utf-8"


def _ok(data=None):
    return {"success": True, "data": data}


def register(r, provider):
    import re

    meth = lambda name: op.method(provider, name)  # noqa: E731
    reserved = (meth("extra_reserved") or (lambda: ()))()
    if meth("audit_event"):
        stream_store.set_audit(meth("audit_event"))
    if meth("sink"):
        forwarder.set_sink(meth("sink")())

    def who(q, action, key=None):
        return op.actor_of(q.headers, provider, action, key)

    def route(method, tail, handler, name):
        r.add(method, re.compile("/api/log-streams" + tail), handler, name=f"log_intake.{name}")

    def do_ingest(q):
        try:
            length = int(op.header(q.headers, "Content-Length") or 0)
        except ValueError:
            length = 0
        status, body, headers = ingest.handle(
            q.groups[0],
            op.header(q.headers, "X-Api-Key"),
            length,
            q.body if isinstance(q.body, dict) else None,
            verify_key=meth("verify_key"),
            on_rows=meth("on_rows"),
            audit=meth("audit"),
            extra_reserved=reserved,
        )
        return status, json.dumps(body).encode("utf-8"), JSON_TYPE, headers

    route("POST", rf"/{KEY}/ingest", do_ingest, "ingest")

    def list_(q):
        who(q, "log-streams.read")
        return _ok(stream_store.list_streams())

    def get_(q):
        who(q, "log-streams.read", q.groups[0])
        s = stream_store.get_stream(q.groups[0])
        if not s:
            raise KeyError("Stream not found")
        return _ok(s)

    def create(q):
        actor = who(q, "log-streams.write")
        return _ok(stream_store.create_stream(q.payload(), actor, reserved))

    def update(q):
        actor = who(q, "log-streams.write", q.groups[0])
        return _ok(stream_store.update_stream(q.groups[0], q.payload(), actor))

    def schema(q):
        actor = who(q, "log-streams.write", q.groups[0])
        p = q.payload()
        return _ok(
            stream_store.apply_schema(
                q.groups[0],
                p.get("fields") or [],
                actor,
                confirm=bool(p.get("confirm")),
                dry_run=bool(p.get("dryRun")),
                extra_reserved=reserved,
            )
        )

    def delete(q):
        actor = who(q, "log-streams.write", q.groups[0])
        return _ok(stream_store.delete_stream(q.groups[0], q.payload().get("confirmTable"), actor))

    def checks(q):
        who(q, "log-streams.read")
        return _ok(sink_check.diagnose(forwarder.get_sink()))

    def test_row(q):
        actor = who(q, "log-streams.write", q.groups[0])
        return _ok(sink_check.send_test_row(q.groups[0], actor, forwarder.get_sink()))

    def verify(q):
        who(q, "log-streams.read", q.groups[0])
        return _ok(
            sink_check.verify_test_row(q.groups[0], q.payload().get("marker"), forwarder.get_sink())
        )

    r.add("GET", "/api/log-streams", list_, name="log_intake.list")
    r.add("POST", "/api/log-streams", create, name="log_intake.create")
    r.add("GET", "/api/log-sink/checks", checks, name="log_intake.checks")
    route("GET", rf"/{KEY}", get_, "get")
    route("POST", rf"/{KEY}/update", update, "update")
    route("POST", rf"/{KEY}/schema", schema, "schema")
    route("POST", rf"/{KEY}/delete", delete, "delete")
    route("POST", rf"/{KEY}/test-row", test_row, "test-row")
    route("POST", rf"/{KEY}/test-row/verify", verify, "test-row-verify")
    # Only a registered sink drains the buffer; retention runs always.
    r.background.append((lambda: forwarder.flush_all() if forwarder.get_sink() else None, 60))
    r.background.append((lambda: (buffer.purge_old(), current_store.purge_events()), 3600))
