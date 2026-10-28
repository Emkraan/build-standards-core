import contextlib
import datetime as dt
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sitrep  # noqa: E402
import sitrep_prerun  # noqa: E402

NOW = dt.datetime.now(dt.timezone.utc)
FUTURE = (NOW + dt.timedelta(hours=5)).isoformat()
PAST = (NOW - dt.timedelta(hours=5)).isoformat()


def serve(routes):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = routes.get(self.path.split("?")[0])
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


BOARD = {
    "items": [
        {
            "fp": "a",
            "title": "Rotate the key",
            "priority": "high",
            "owner": "me",
            "action": "do it",
            "refs": ["PR #1"],
        },
        {"fp": "b", "title": "Done already", "priority": "critical"},
        {"fp": "c", "title": "Snoozed", "priority": "high"},
        {"fp": "d", "title": "Snooze over", "priority": "low"},
    ]
}
HANDLED = {
    "handled": {
        "b": {
            "act": "resolved",
            "at": (NOW - dt.timedelta(hours=2)).isoformat()[:19],
            "item": {"title": "Done already"},
        },
        "c": {"act": "snoozed", "until": FUTURE},
        "d": {"act": "snoozed", "until": PAST},
    }
}
ROUTES = {
    "/data/action-center.json": BOARD,
    "/api/action-handled": HANDLED,
    "/api/badges": {
        "builds": {"waiting": 2},
        "knowledge_pending": ["x"],
        "knowledge_docs": 3,
        "debt": 4,
        "infra": {"count": 1, "items": ["disk full"]},
    },
    "/api/alerts": {
        "counts": {"unacked": 2},
        "alerts": [{"name": "nightly", "open": True}, {"name": "ok", "open": False}],
    },
    "/api/platform-reviews": {"counts": {"needs_me": 3}},
    "/api/team_prefix-reviews": {"counts": {"needs_me": 0}},
    "/api/repo-reviews": {"counts": {"needs_me": 1}},
}


class Base(unittest.TestCase):
    def setUp(self):
        self.srv = serve(dict(ROUTES))
        self._url = sitrep.URL
        sitrep.URL = f"http://127.0.0.1:{self.srv.server_port}"

    def tearDown(self):
        sitrep.URL = self._url
        self.srv.shutdown()
        self.srv.server_close()
        os.environ.pop("SITREP_REVIEWS", None)


class Sitrep(Base):
    def test_lists_what_waits_on_the_owner(self):
        out = sitrep.build()
        self.assertIn("Action Center (2)", out)
        self.assertIn("[high] Rotate the key", out)
        self.assertIn("Snooze over", out)
        self.assertNotIn("Done already", out)
        self.assertNotIn("Snoozed\n", out)
        self.assertIn("**Reviews (4):** Primary 3, other repos 1", out)
        self.assertIn("Builds waiting on your approval:** 2", out)
        self.assertIn("1 proposal, 3 doc gaps", out)
        self.assertIn("Debt decisions open:** 4", out)
        self.assertIn("Infrastructure (1):** disk full", out)
        self.assertIn("2 new alerts, failing now: nightly", out)
        self.assertIn("13 items waiting on you.", out)  # debt is listed, never counted
        self.assertTrue(out.rstrip().endswith(sitrep.URL + "/"))

    def test_an_unreadable_review_source_is_named_not_counted(self):
        os.environ["SITREP_REVIEWS"] = json.dumps(
            [
                {"label": "Primary", "path": "/api/platform-reviews"},
                {"label": "Gone", "path": "/api/nope"},
            ]
        )
        out = sitrep.build()
        self.assertIn("**Reviews (3):** Primary 3", out)
        self.assertIn("Could not read reviews for Gone", out)

    def test_nothing_waiting(self):
        self.srv.shutdown()
        self.srv.server_close()
        quiet = dict(ROUTES)
        quiet.update(
            {
                "/data/action-center.json": {"items": []},
                "/api/badges": {},
                "/api/alerts": {"counts": {}, "alerts": []},
                "/api/platform-reviews": {"counts": {}},
                "/api/team_prefix-reviews": {"counts": {}},
                "/api/repo-reviews": {"counts": {}},
            }
        )
        self.srv = serve(quiet)
        sitrep.URL = f"http://127.0.0.1:{self.srv.server_port}"
        out = sitrep.build()
        self.assertIn("Nothing waiting on you.", out)

    def test_many_items_are_capped(self):
        self.srv.shutdown()
        self.srv.server_close()
        r = dict(ROUTES)
        r["/data/action-center.json"] = {
            "items": [{"fp": str(i), "title": f"t{i}", "priority": "low"} for i in range(14)]
        }
        r["/api/action-handled"] = {"handled": {}}
        self.srv = serve(r)
        sitrep.URL = f"http://127.0.0.1:{self.srv.server_port}"
        out = sitrep.build()
        self.assertIn("- and 4 more", out)

    def test_a_dead_ops_center_exits_one_and_says_so(self):
        self.srv.shutdown()
        self.srv.server_close()
        sitrep.URL = "http://127.0.0.1:9"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = sitrep.main()
        self.assertEqual(rc, 1)
        self.assertIn("could not be read", buf.getvalue())


class Prerun(Base):
    def run_prerun(self, **env):
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        h = sitrep_prerun.HEALTH
        sitrep_prerun.HEALTH = env.get("SITREP_HEALTH_CMD", "")
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = sitrep_prerun.main()
        finally:
            sitrep_prerun.HEALTH = h
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return rc, buf.getvalue()

    def test_open_and_recently_handled_blocks(self):
        rc, out = self.run_prerun()
        self.assertEqual(rc, 0)
        self.assertIn("OPEN ACTION CENTER ITEMS (2", out)
        self.assertIn("- [high] Rotate the key | owner me | next: do it", out)
        self.assertIn("IN THE LAST 72H (1)", out)
        self.assertIn("resolved: Done already", out)
        self.assertNotIn("LIVE REF STATUS", out)

    def test_health_block_prints_first_and_a_failure_stops(self):
        with tempfile.TemporaryDirectory() as d:
            ok = Path(d) / "ok.py"
            ok.write_text("print('HEALTH OK')\n")
            rc, out = self.run_prerun(SITREP_HEALTH_CMD=str(ok))
            self.assertEqual(rc, 0)
            self.assertTrue(out.startswith("HEALTH OK"))
            bad = Path(d) / "bad.py"
            bad.write_text("import sys\nsys.stderr.write('boom')\nsys.exit(3)\n")
            rc, out = self.run_prerun(SITREP_HEALTH_CMD=str(bad))
            self.assertEqual(rc, 3)
            self.assertIn("boom", out)

    def test_ref_status_plugin_reads_the_state_files_and_the_open_items(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "state.md"
            state.write_text("line one PR #7\nline two\n")
            plug = Path(d) / "refs.py"
            plug.write_text(
                "def resolve(text):\n"
                "    refs = [w for w in text.split() if w.startswith('#')]\n"
                "    return {'refs': refs, 'done': refs[:1], 'errors': ['one failed']}\n"
                "def done_lines(rs):\n"
                "    return ['- done ' + r for r in rs['done']]\n"
            )
            rc, out = self.run_prerun(
                SITREP_REF_STATUS=str(plug), SITREP_STATE_FILES=json.dumps([[str(state), 1]])
            )
            self.assertEqual(rc, 0)
            self.assertIn(
                "LIVE REF STATUS (2 refs checked, 1 finished)", out
            )  # #7 and the open item's #1
            self.assertIn("- done #7", out)
            self.assertIn("- check error: one failed", out)

    def test_an_unreadable_board_never_blocks_the_brief(self):
        self.srv.shutdown()
        self.srv.server_close()
        sitrep.URL = "http://127.0.0.1:9"
        rc, out = self.run_prerun()
        self.assertEqual(rc, 0)
        self.assertIn("OPEN ACTION CENTER ITEMS: unavailable", out)


if __name__ == "__main__":
    unittest.main()
