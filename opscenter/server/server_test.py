"""The server: the gate (Host, Origin, preflight, body cap), the registry and error mapping, static serving (jail, fallback, ETag,
gzip) and the route table against the real modules on a scratch state tree."""

import gzip
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import app  # noqa: E402
import gate  # noqa: E402
import registry as reg  # noqa: E402


class Boom(Exception):
    status = 418


class Served(unittest.TestCase):
    registry_factory = None

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="server-test-"))
        self.dist = self.d / "dist"
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_text("<html>app</html>")
        (self.dist / "assets" / "a.js").write_text("x" * 3000)
        (self.d / "secret.txt").write_text("secret")
        self._env = dict(os.environ)
        self.registry = self.make_registry()
        self.srv = app.make_server(self.registry, self.dist)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.d, ignore_errors=True)

    def make_registry(self):
        r = reg.Registry()
        r.get("/api/ok", lambda q: {"ok": True})
        r.get("/api/echo", lambda q: {"q": q.arg("q"), "n": q.query.get("n")})
        r.get("/api/boom", lambda q: (_ for _ in ()).throw(Boom("teapot")))
        r.get("/api/value", lambda q: (_ for _ in ()).throw(ValueError("bad value")))
        r.get("/api/key", lambda q: (_ for _ in ()).throw(KeyError("nope")))
        r.get("/api/crash", lambda q: (_ for _ in ()).throw(RuntimeError("secret detail")))
        r.get("/api/big", lambda q: {"rows": ["x" * 50] * 100})
        r.get("/api/one-on-ones", lambda q: {"private": True})
        r.get("/api/file", lambda q: (200, b"raw", "application/octet-stream", {"X-Extra": "1"}))
        r.post("/api/write", lambda q: {"got": q.body})
        r.post("/api/status", lambda q: (201, {"made": True}))
        return r

    def call(self, method, path, body=None, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        out = (r.status, dict(r.getheaders()), raw)
        c.close()
        return out

    def js(self, *a, **kw):
        s, h, raw = self.call(*a, **kw)
        if h.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return s, h, json.loads(raw or b"null")


class Gate(Served):
    def test_a_foreign_host_is_refused_and_a_loopback_one_served(self):
        self.assertEqual(self.js("GET", "/api/ok", host="evil.example:80")[0], 403)
        self.assertEqual(self.js("GET", "/api/ok", host=f"localhost:{self.port}")[0], 200)
        os.environ["OPSCENTER_ALLOWED_HOSTS"] = "ops.example.com"
        self.assertEqual(self.js("GET", "/api/ok", host="ops.example.com")[0], 200)

    def test_a_cross_origin_write_is_refused_and_a_same_origin_or_originless_one_passes(self):
        self.assertEqual(
            self.js("POST", "/api/write", {"a": 1}, {"Origin": "https://evil.example"})[0], 403
        )
        self.assertEqual(
            self.js("POST", "/api/write", {"a": 1}, {"Sec-Fetch-Site": "cross-site"})[0], 403
        )
        self.assertEqual(
            self.js("POST", "/api/write", {"a": 1}, {"Origin": f"http://127.0.0.1:{self.port}"})[2],
            {"got": {"a": 1}},
        )
        self.assertEqual(self.js("POST", "/api/write", {"a": 2})[2], {"got": {"a": 2}})

    def test_a_preflight_is_answered_only_for_a_listed_origin_and_never_with_a_wildcard(self):
        s, h, _ = self.call("OPTIONS", "/api/write", headers={"Origin": "https://plugin.example"})
        self.assertEqual(s, 403)
        os.environ["OPSCENTER_PLUGIN_ORIGINS"] = "https://plugin.example"
        s, h, _ = self.call("OPTIONS", "/api/write", headers={"Origin": "https://plugin.example"})
        self.assertEqual((s, h.get("Access-Control-Allow-Origin")), (204, "https://plugin.example"))
        s, h, _ = self.call("GET", "/api/ok")
        self.assertNotIn("Access-Control-Allow-Origin", h)

    def test_the_body_cap_and_a_bad_body(self):
        os.environ["OPSCENTER_MAX_BODY"] = "10"
        gate.MAX_BODY = 10
        try:
            self.assertEqual(self.js("POST", "/api/write", {"a": "x" * 50})[0], 413)
        finally:
            gate.MAX_BODY = 1_048_576
        self.assertEqual(self.js("POST", "/api/write", b"not json")[0], 400)

    def test_security_headers_and_cache_classes(self):
        s, h, _ = self.js("GET", "/api/ok")
        self.assertEqual(
            (h["X-Content-Type-Options"], h["X-Frame-Options"], h["Cache-Control"]),
            ("nosniff", "DENY", "no-cache"),
        )
        self.assertEqual(self.js("GET", "/api/one-on-ones")[1]["Cache-Control"], "no-store")
        self.assertEqual(self.js("POST", "/api/write", {})[1]["Cache-Control"], "no-store")


class Dispatch(Served):
    def test_unknown_and_wrong_method_paths(self):
        self.assertEqual(self.js("GET", "/api/missing")[0], 404)
        self.assertEqual(self.js("GET", "/api/write")[0], 405)
        self.assertEqual(self.js("POST", "/api/ok", {})[0], 405)

    def test_query_arguments_and_the_statuses_handlers_map_to(self):
        self.assertEqual(self.js("GET", "/api/echo?q=hi&n=1&n=2")[2], {"q": "hi", "n": ["1", "2"]})
        self.assertEqual(
            self.js("GET", "/api/boom")[0:1] + (self.js("GET", "/api/boom")[2],),
            (418, {"error": "teapot"}),
        )
        self.assertEqual(self.js("GET", "/api/value")[0], 400)
        self.assertEqual(self.js("GET", "/api/key")[0], 404)
        s, _, body = self.js("GET", "/api/crash")
        self.assertEqual(
            (s, body), (502, {"error": "read failed"})
        )  # no internal detail reaches the client

    def test_a_handler_may_answer_a_status_or_a_file(self):
        self.assertEqual(self.js("POST", "/api/status", {})[0:1], (201,))
        s, h, raw = self.call("GET", "/api/file")
        self.assertEqual((s, raw, h["X-Extra"]), (200, b"raw", "1"))

    def test_etag_304_and_gzip(self):
        s, h, raw = self.call("GET", "/api/big", headers={"Accept-Encoding": "gzip"})
        self.assertEqual((s, h.get("Content-Encoding")), (200, "gzip"))
        self.assertEqual(len(json.loads(gzip.decompress(raw))["rows"]), 100)
        s2, _, _ = self.call("GET", "/api/big", headers={"If-None-Match": h["ETag"]})
        self.assertEqual(s2, 304)

    def test_head_answers_like_get_without_a_body(self):
        s, h, raw = self.call("HEAD", "/api/ok")
        self.assertEqual((s, raw), (200, b""))

    def test_registry_refuses_a_write_declared_as_a_read(self):
        with self.assertRaises(ValueError):
            reg.Registry().add("POST", "/x", lambda q: 1, "read")
        with self.assertRaises(ValueError):
            reg.Registry().add("GET", "/x", lambda q: 1, "write")


class Static(Served):
    def test_the_app_assets_and_the_single_page_fallback(self):
        s, h, raw = self.call("GET", "/")
        self.assertEqual(
            (s, raw, h["Content-Type"]), (200, b"<html>app</html>", "text/html; charset=utf-8")
        )
        self.assertEqual(self.call("GET", "/reviews/42")[2], b"<html>app</html>")
        s, h, raw = self.call("GET", "/assets/a.js", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(
            (h["Content-Type"], h.get("Content-Encoding")),
            ("text/javascript; charset=utf-8", "gzip"),
        )
        self.assertEqual(self.call("GET", "/assets/missing.js")[0], 404)

    def test_traversal_and_symlink_escapes_are_refused(self):
        for p in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
            s, _, raw = self.call("GET", p)
            self.assertNotEqual(raw, b"secret", p)
        (self.dist / "link.txt").symlink_to(self.d / "secret.txt")
        s, _, raw = self.call("GET", "/link.txt")
        self.assertNotEqual(raw, b"secret")


class Routes(unittest.TestCase):
    """The route table against the real modules on a scratch state tree."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="routes-test-"))
        self._env = dict(os.environ)
        os.environ.update(
            OPSCENTER_ROOT=str(self.d),
            OPSCENTER_STATE_DIR=str(self.d / "state"),
            OPSCENTER_AGENT_HOME=str(self.d / "agent"),
        )
        for k in (
            "OPSCENTER_PEOPLE_PARAMS",
            "BUILDS_CONFIG",
            "OPSCENTER_REWRITE_CMD",
            "OPSCENTER_SERVED_BOARD",
        ):
            os.environ.pop(k, None)
        for m in ("stores", "routes"):
            sys.modules.pop(m, None)
        import routes

        self.routes = routes
        self.registry = routes.build()
        self.srv = app.make_server(self.registry, None)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.d, ignore_errors=True)

    def js(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        c.request(
            method,
            path,
            body=json.dumps(body).encode() if body is not None else None,
            headers={"Host": f"127.0.0.1:{self.port}"},
        )
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, json.loads(raw or b"null")

    def test_every_registered_route_names_a_function_that_exists(self):
        names = {r.name for r in self.registry.routes}
        self.assertIn("builds.get", names)
        self.assertIn("one_on_ones.board", names)
        for r in self.registry.routes:
            if "." in r.name:
                mod, fn = r.name.split(".", 1)
                self.assertTrue(hasattr(sys.modules[mod], fn), r.name)
        # reads are GET only, writes are POST only
        self.assertTrue(
            all((r.method == "POST") == (r.kind == "write") for r in self.registry.routes)
        )

    def test_health_and_the_handled_store_round_trip_with_restore(self):
        self.assertEqual(self.js("GET", "/api/health"), (200, {"ok": True}))
        s, body = self.js(
            "POST", "/api/action-handled", {"fp": "ac_1", "act": "resolved", "summary": "done"}
        )
        self.assertEqual(body["handled"]["ac_1"]["act"], "resolved")
        self.assertEqual(body["handled"]["ac_1"]["via"], "ops-center")
        self.assertIn("ac_1", self.js("GET", "/api/action-handled")[1]["handled"])
        self.js(
            "POST",
            "/api/action-handled",
            {"fp": "ac_2", "act": "snoozed", "until": "2099-01-01T00:00:00Z"},
        )
        self.js("POST", "/api/action-handled", {"fp": "ac_1", "act": "restore"})
        self.assertEqual(sorted(self.js("GET", "/api/action-handled")[1]["handled"]), ["ac_2"])

    def test_the_item_is_snapshotted_from_the_served_board(self):
        board = self.d / "board.json"
        board.write_text(
            json.dumps(
                {"items": [{"fp": "ac_9", "key": "k", "title": "A title", "priority": "high"}]}
            )
        )
        os.environ["OPSCENTER_SERVED_BOARD"] = str(board)
        self.js("POST", "/api/action-handled", {"fp": "ac_9", "act": "ignored"})
        self.assertEqual(
            self.js("GET", "/api/action-handled")[1]["handled"]["ac_9"]["item"]["title"], "A title"
        )

    def test_approve_queues_approved_and_rejected_and_sends_changes_to_the_feedback_file(self):
        s, body = self.js(
            "POST",
            "/api/approve",
            {
                "decisions": [
                    {"fp": "a", "act": "approved", "body_sha": "s1", "title": "T"},
                    {"fp": "b", "act": "rejected", "reason": "no"},
                    {"fp": "c", "act": "changes", "reason": "reword", "title": "C"},
                    {"fp": "d", "act": "weird"},
                    {"act": "approved"},
                ]
            },
        )
        self.assertEqual(body, {"queued": 3})
        dash = self.d / "state" / "dashboard"
        rows = [json.loads(x) for x in (dash / "approve-inbox.jsonl").read_text().splitlines()]
        self.assertEqual(
            [(r["fp"], r["act"]) for r in rows], [("a", "approved"), ("b", "rejected")]
        )
        self.assertEqual(rows[1]["reason"], "no")
        self.assertEqual(
            json.loads((dash / "proposal-feedback.json").read_text())["feedback"]["c"]["status"],
            "open",
        )
        self.assertEqual(self.js("POST", "/api/approve", {"decisions": "x"})[0], 400)

    def test_modules_that_are_present_answer_with_an_empty_state(self):
        s, body = self.js("GET", "/api/builds")
        self.assertEqual(s, 200)
        self.assertIsInstance(body["pipelines"], list)
        s, body = self.js("GET", "/api/one-on-ones")
        self.assertEqual((s, body["people"]), (200, []))
        s, body = self.js("GET", "/api/ac-routing")
        self.assertEqual(s, 200)
        self.assertIn("rules", body)

    def test_model_accounts_with_no_provider_answer_empty_and_a_fallback_order_write_is_unsupported(
        self,
    ):
        for k in ("OPSCENTER_MODEL_ACCOUNTS_PROVIDER", "OPSCENTER_MODEL_ACCOUNTS_ALLOW_POOL_READ"):
            os.environ.pop(k, None)
        s, body = self.js("GET", "/api/infra/accounts")
        self.assertEqual((s, body["accounts"], body["ledger"]), (200, [], None))
        s, body = self.js("GET", "/api/llm-fallback")
        self.assertEqual((s, body["active"]), (200, None))
        self.assertEqual(
            self.js("GET", "/api/infra/fallback-order")[1], {"order": [], "writable": False}
        )
        self.assertEqual(self.js("POST", "/api/infra/fallback-order", {"ids": ["a"]})[0], 501)

    def test_the_restart_card_is_empty_with_no_script_and_a_write_is_501(self):
        os.environ.pop("OPSCENTER_RUNTIME_RESTART_SCRIPT", None)
        s, body = self.js("GET", "/api/hermes-restart")
        self.assertEqual((s, body["configured"], body["alert"]), (200, False, None))
        self.assertEqual(self.js("POST", "/api/hermes-restart", {"action": "now"})[0], 501)
        self.assertEqual(self.js("POST", "/api/hermes-restart", {"action": "x"})[0], 400)

    def test_privileged_reviews_with_no_review_config_answer_empty_and_a_decision_is_501(self):
        os.environ["OPSCENTER_REVIEWS_CONFIG"] = os.path.join(
            os.environ["OPSCENTER_STATE_DIR"], "none.json"
        )
        try:
            s, body = self.js("GET", "/api/privileged-reviews")
            self.assertEqual((s, body["pending"]), (200, []))
            body = {"key": "destroy:1", "head_sha": "a" * 40}
            self.assertEqual(
                self.js("POST", "/api/platform-reviews/deployment/approve", body)[0], 501
            )
        finally:
            os.environ.pop("OPSCENTER_REVIEWS_CONFIG", None)

    def test_the_brief_route_with_nothing_configured_is_a_400(self):
        os.environ["OPSCENTER_REVIEWS_CONFIG"] = os.path.join(
            os.environ["OPSCENTER_STATE_DIR"], "none.json"
        )
        os.environ.pop("APPROVAL_BRIEF_MODEL_CMD", None)
        try:
            self.assertEqual(
                self.js("POST", "/api/reviews/brief", {"repo": "plan", "pr": 1})[0], 400
            )
        finally:
            os.environ.pop("OPSCENTER_REVIEWS_CONFIG", None)

    def test_the_runtime_routes_answer_with_no_runtime_configured_by_default(self):
        os.environ.pop("OPSCENTER_RUNTIME_CMD", None)
        s, body = self.js("GET", "/api/tackle")
        self.assertEqual((s, body["runtime"]["configured"]), (200, False))
        for path, payload in (
            ("/api/tackle", {"fp": "x"}),
            ("/api/jira/tackle", {"key": "A-1"}),
            ("/api/pr/discuss", {"repo": "o/r", "pr": 1}),
            ("/api/eng-backlog/tackle", {"uid": "x"}),
            ("/api/doc-coverage/tackle", {"id": "x"}),
        ):
            s, body = self.js("POST", path, payload)
            self.assertEqual((s, body["error"]), (501, "no runtime configured"), path)

    def test_the_documentation_coverage_page_answers_empty_without_files(self):
        s, body = self.js("GET", "/api/doc-coverage")
        self.assertEqual((s, body["things"], body["open_count"]), (200, [], 0))
        self.assertEqual(
            self.js("POST", "/api/doc-coverage/handle", {"id": "x", "act": "snooze"})[0], 404
        )

    def test_a_refused_provider_answers_403_with_the_reason(self):
        os.environ["OPSCENTER_MODEL_ACCOUNTS_PROVIDER"] = "nocolon"
        s, body = self.js("GET", "/api/infra/accounts")
        self.assertEqual(s, 403)
        self.assertIn("provider must be", body["error"])

    def test_a_module_error_keeps_its_own_status(self):
        s, body = self.js(
            "POST", "/api/jira/needs-me/decide", {"key": "not a key", "decision": "close"}
        )
        self.assertEqual(s, 400)
        s, body = self.js("POST", "/api/one-on-ones/topic", {"person": "nobody", "title": "x"})
        self.assertEqual(s, 400)


if __name__ == "__main__":
    unittest.main()
