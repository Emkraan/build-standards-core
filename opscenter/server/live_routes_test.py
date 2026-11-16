"""The push channel over a real server on a scratch port: the stream opens with retry and hello, the presence route validates, a watched
endpoint publishes through the response hook, the stream cap answers 503 and the gate still guards both routes. Hermetic: a scratch
dist, a private bus, no upstream call."""

import http.client
import json
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import live_bus  # noqa: E402
import live_routes  # noqa: E402
import registry as reg  # noqa: E402
import server_test  # noqa: E402


class LiveServed(server_test.Served):
    def make_registry(self):
        live_bus.HEARTBEAT_S, self._hb = (
            0.2,
            live_bus.HEARTBEAT_S,
        )  # a closed peer is seen at the next heartbeat write
        self.addCleanup(setattr, live_bus, "HEARTBEAT_S", self._hb)
        r = reg.Registry()
        self.n = 1
        r.get("/api/data", lambda q: {"n": self.n, "generated_at": time.time()})
        self.bus = live_bus.Bus(max_clients=2)
        live_routes.install(r, self.bus)
        return r

    def open_stream(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/api/live", headers={"Host": f"127.0.0.1:{self.port}"})
        return c, c.getresponse()

    def read_frame(self, resp):
        lines = []
        while True:
            line = resp.fp.readline().decode()
            if line in ("\n", ""):
                if lines:
                    return "".join(lines)
                continue
            lines.append(line)

    def hello(self, resp):
        self.assertEqual(self.read_frame(resp), "retry: 3000\n")
        frame = self.read_frame(resp)
        self.assertTrue(frame.startswith("event: hello"))
        return json.loads(frame.split("data: ", 1)[1])

    def test_the_stream_opens_with_retry_then_hello_and_the_right_headers(self):
        c, resp = self.open_stream()
        self.assertEqual(resp.status, 200)
        self.assertTrue(resp.getheader("Content-Type").startswith("text/event-stream"))
        self.assertEqual(resp.getheader("Cache-Control"), "no-store")
        self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff")
        self.assertIn("id", self.hello(resp))
        c.close()

    def test_a_watched_endpoint_publishes_once_through_the_response_hook_and_a_stamp_never_does(
        self,
    ):
        c, resp = self.open_stream()
        cid = self.hello(resp)["id"]
        s, _, body = self.js(
            "POST",
            "/api/live/presence",
            {
                "id": cid,
                "visible": True,
                "wants": [{"topic": "x", "path": "/api/data", "ms": 5000}],
            },
        )
        self.assertEqual((s, body), (200, {"ok": True}))
        self.js("GET", "/api/data")  # first sight, recorded quietly
        self.js("GET", "/api/data")  # only the stamp differs, no publish
        self.n = 2
        self.js("GET", "/api/data")
        frame = self.read_frame(resp)
        self.assertTrue(frame.startswith("event: topic"), frame)
        self.assertEqual(json.loads(frame.split("data: ", 1)[1])["t"], "api:/api/data")
        c.close()

    def test_presence_refuses_a_gone_stream_and_a_bad_body_and_drops_a_query_path(self):
        self.assertEqual(
            self.js("POST", "/api/live/presence", {"id": "nope", "visible": True, "wants": []})[0],
            404,
        )
        c, resp = self.open_stream()
        cid = self.hello(resp)["id"]
        self.assertEqual(
            self.js("POST", "/api/live/presence", {"id": cid, "visible": "yes", "wants": []})[0],
            404,
        )
        bad = {
            "id": cid,
            "visible": True,
            "wants": [{"topic": "x", "path": "/api/data?q=1", "ms": 5000}],
        }
        self.assertEqual(self.js("POST", "/api/live/presence", bad)[0], 200)
        self.assertEqual(
            self.bus.clients[cid].wants, {}
        )  # the want is dropped, the body is not refused
        c.close()

    def test_the_third_stream_is_refused_with_503_and_a_closed_one_frees_a_slot(self):
        a, ra = self.open_stream()
        b, rb = self.open_stream()
        self.hello(ra)
        self.hello(rb)
        c, rc = self.open_stream()
        self.assertEqual(rc.status, 503)
        c.close()
        ra.close()
        a.close()
        for _ in range(60):
            if self.bus.counts()["clients"] <= 1:
                break
            time.sleep(0.1)
        d, rd = self.open_stream()
        self.assertEqual(rd.status, 200)
        d.close()
        b.close()

    def test_the_gate_guards_the_stream_and_the_presence_route(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/api/live", headers={"Host": "evil.example:80"})
        self.assertEqual(c.getresponse().status, 403)
        self.assertEqual(
            self.js("POST", "/api/live/presence", {"id": "x"}, {"Origin": "https://evil.example"})[
                0
            ],
            403,
        )


if __name__ == "__main__":
    unittest.main()
