"""hermes/phone_access.py: the pinned plugin install and drift check, the key, the TLS files, the edge and the gateway check."""

import io
import json
import socket
import ssl
import stat
import subprocess
import threading
import unittest
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from support import ROOT, Work, load

pa = load("phone_access", "hermes/phone_access.py")


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = pa.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def git(cwd, *args):
    r = subprocess.run(
        [
            "git",
            "-C",
            str(cwd),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@users.noreply.github.com",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return r.stdout.strip()


class Plugin(Work):
    def setUp(self):
        super().setUp()
        self.src = self.dir / "src"
        (self.src / "pkg" / "plug").mkdir(parents=True)
        (self.src / "pkg" / "plug" / "plugin.yaml").write_text("name: plug\nversion: 1.0.0\n")
        (self.src / "pkg" / "plug" / "__init__.py").write_text("X = 1\n")
        git(self.src, "init", "-q")
        git(self.src, "add", ".")
        git(self.src, "commit", "-q", "-m", "one")
        self.sha1 = git(self.src, "rev-parse", "HEAD")
        (self.src / "pkg" / "plug" / "plugin.yaml").write_text("name: plug\nversion: 1.1.0\n")
        git(self.src, "commit", "-q", "-am", "two")
        self.sha2 = git(self.src, "rev-parse", "HEAD")
        self.home = self.dir / "home"
        self.pin = self.dir / "plug.pin"
        self.reg = self.dir / "tools.json"
        self.reg.write_text(
            json.dumps(
                {
                    "tools": [
                        {
                            "id": "plug-id",
                            "plugin": "plug",
                            "pin": {
                                "repository": str(self.src),
                                "path": "pkg/plug",
                                "commit": self.sha1,
                                "version": "1.0.0",
                            },
                        }
                    ]
                }
            )
        )
        p = mock.patch.object(pa, "REGISTRY", self.reg)
        p.start()
        self.addCleanup(p.stop)

    def base(self, *more):
        return ["--home", str(self.home), "plugin", "--id", "plug-id", "--no-enable", *more]

    def test_check_before_install_is_drift_then_install_then_check_is_ok(self):
        self.assertEqual(run(*self.base("--check"))[0], 1)
        code, out, _ = run(*self.base())
        self.assertEqual(code, 0, out)
        self.assertTrue((self.home / "plugins" / "plug" / "plugin.yaml").is_file())
        self.assertEqual(
            (self.home / "plugins" / "plug" / ".pinned-sha").read_text().strip(), self.sha1
        )
        code, out, _ = run(*self.base("--check"))
        self.assertEqual((code, out.strip().splitlines()[-1]), (0, "ok"))

    def test_a_second_install_changes_nothing(self):
        run(*self.base())
        marker = self.home / "plugins" / "plug" / "marker"
        marker.write_text("keep")
        code, out, _ = run(*self.base())
        self.assertEqual(code, 0)
        self.assertIn("already at the pinned commit", out)
        self.assertTrue(marker.exists())

    def test_a_changed_installed_plugin_is_drift(self):
        run(*self.base())
        (self.home / "plugins" / "plug" / ".pinned-sha").write_text(self.sha2 + "\n")
        self.assertEqual(run(*self.base("--check"))[0], 1)

    def test_a_pin_file_and_a_parameter_override_the_registry_in_that_order(self):
        run(*self.base())
        self.pin.write_text(f"# comment\ncommit={self.sha2}\nversion=1.1.0\n")
        self.assertEqual(run(*self.base("--check", "--pin-file", str(self.pin)))[0], 1)
        code, _, _ = run(*self.base("--pin-file", str(self.pin)))
        self.assertEqual(code, 0)
        self.assertEqual(run(*self.base("--check", "--pin-file", str(self.pin)))[0], 0)
        self.assertEqual(
            run(*self.base("--check", "--pin-file", str(self.pin), "--commit", self.sha1))[0], 1
        )

    def test_a_branch_a_short_sha_and_a_missing_field_are_refused(self):
        for bad in ("main", self.sha1[:12]):
            code, _, err = run(*self.base("--check", "--commit", bad))
            self.assertEqual(code, 2, bad)
            self.assertIn("40 character", err)
        self.reg.write_text(json.dumps({"tools": [{"id": "plug-id", "plugin": "plug"}]}))
        code, _, err = run(*self.base("--check"))
        self.assertEqual(code, 2)
        self.assertIn("no repository, path, commit", err)

    def test_a_version_that_does_not_match_the_pin_is_not_installed(self):
        code, _, err = run(*self.base("--version", "9.9.9"))
        self.assertEqual(code, 1)
        self.assertIn("pin says 9.9.9", err)
        self.assertFalse((self.home / "plugins" / "plug").exists())

    def test_the_real_registry_pins_a_full_commit_with_every_field(self):
        shipped = json.loads((ROOT / "hermes" / "tools.json").read_text(encoding="utf8"))["tools"]
        pin = next(t for t in shipped if t["id"] == "phone-push")["pin"]
        self.assertEqual(set(pin), {"repository", "path", "commit", "version"})
        self.assertRegex(pin["commit"], r"^[0-9a-f]{40}$")


class Key(Work):
    def test_the_key_is_staged_once_with_mode_0600_and_never_printed(self):
        env = self.dir / ".env"
        env.write_text("OTHER=1")
        code, out, _ = run("key", "--env-file", str(env))
        self.assertEqual(code, 0)
        text = env.read_text()
        value = [x for x in text.splitlines() if x.startswith("API_SERVER_KEY=")][0].split("=", 1)[
            1
        ]
        self.assertNotIn(value, out)
        self.assertGreaterEqual(len(value), 16)
        self.assertIn("API_SERVER_ENABLED=true", text)
        self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o600)
        run("key", "--env-file", str(env))
        self.assertEqual(env.read_text(), text)


class Gateway(Work):
    LOG = (
        "x INFO gateway.run: \u2713 api_server connected\n"
        "x INFO gateway.run: Gateway running with 1 platform(s)\n"
    )

    def check(self, text):
        log = self.dir / "agent.log"
        log.write_text(text)
        return run("gateway-check", "--log", str(log))[0]

    def test_only_the_api_server_connected_passes(self):
        self.assertEqual(self.check(self.LOG), 0)

    def test_a_bot_connected_fails(self):
        bad = self.LOG.replace(
            "x INFO gateway.run: Gateway running",
            "x INFO gateway.run: \u2713 chatbot connected\nx INFO gateway.run: Gateway running",
        ).replace("1 platform", "2 platform")
        self.assertEqual(self.check(bad), 1)

    def test_only_the_latest_start_counts(self):
        old = "x \u2713 chatbot connected\nx Gateway running with 2 platform(s)\n"
        stop = "x Shutdown phase: all adapters disconnected at +1s\n"
        self.assertEqual(self.check(old + stop + self.LOG), 0)

    def test_a_log_with_no_start_or_missing_is_exit_2(self):
        self.assertEqual(self.check("nothing\n"), 2)
        self.assertEqual(run("gateway-check", "--log", str(self.dir / "none.log"))[0], 2)


class Edge(Work):
    def test_the_edge_serves_tls_forwards_headers_and_the_body_and_needs_a_certificate(self):
        class Up(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps(
                    {"auth": self.headers.get("Authorization", ""), "path": self.path}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        up = HTTPServer(("127.0.0.1", 0), Up)
        threading.Thread(target=up.serve_forever, daemon=True).start()
        self.addCleanup(up.server_close)
        self.addCleanup(up.shutdown)
        tls = self.dir / "tls"
        code, out, _ = run("tls", "--dir", str(tls), "--host", "localhost", "--ip", "127.0.0.1")
        self.assertEqual(code, 0, out)
        before = (tls / "edge.crt").read_bytes()
        code, out, _ = run("tls", "--dir", str(tls), "--host", "localhost", "--ip", "127.0.0.1")
        self.assertIn("kept", out)
        self.assertEqual((tls / "edge.crt").read_bytes(), before)
        self.assertEqual(stat.S_IMODE((tls / "edge.key").stat().st_mode), 0o600)
        run(
            "tls",
            "--dir",
            str(tls),
            "--host",
            "localhost",
            "--host",
            "other.example",
            "--ip",
            "127.0.0.1",
        )
        self.assertNotEqual((tls / "edge.crt").read_bytes(), before)
        edge = pa.serve_edge("127.0.0.1", 0, f"http://127.0.0.1:{up.server_port}", tls)
        threading.Thread(target=edge.serve_forever, daemon=True).start()
        self.addCleanup(edge.server_close)
        self.addCleanup(edge.shutdown)
        url = f"https://localhost:{edge.server_port}/v1/x?q=1"
        trusted = ssl.create_default_context(cafile=str(tls / "ca.crt"))
        req = urllib.request.Request(url, headers={"Authorization": "Bearer k"})
        with urllib.request.urlopen(req, context=trusted, timeout=10) as r:
            self.assertEqual(json.loads(r.read()), {"auth": "Bearer k", "path": "/v1/x?q=1"})
        with self.assertRaises(OSError):  # a client without the authority fails closed
            urllib.request.urlopen(url, context=ssl.create_default_context(), timeout=10)

    def test_an_upgrade_request_is_tunnelled_both_ways(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        self.addCleanup(listener.close)

        def echo():
            conn, _ = listener.accept()
            with conn:
                seen = b""
                while b"\r\n\r\n" not in seen:
                    seen += conn.recv(4096)
                conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\n")
                conn.sendall(b"hello " + conn.recv(16))

        threading.Thread(target=echo, daemon=True).start()
        tls = self.dir / "tls"
        run("tls", "--dir", str(tls), "--host", "localhost")
        edge = pa.serve_edge("127.0.0.1", 0, f"http://127.0.0.1:{listener.getsockname()[1]}", tls)
        threading.Thread(target=edge.serve_forever, daemon=True).start()
        self.addCleanup(edge.server_close)
        self.addCleanup(edge.shutdown)
        ctx = ssl.create_default_context(cafile=str(tls / "ca.crt"))
        conn = socket.create_connection(("127.0.0.1", edge.server_port), timeout=10)
        with ctx.wrap_socket(conn, server_hostname="localhost") as s:
            s.sendall(
                b"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n"
            )
            got = b""
            while b"hello" not in got:
                s.sendall(b"phone")
                got += s.recv(4096)
        self.assertIn(b"101 Switching Protocols", got)
        self.assertIn(b"hello phone", got)

    def test_the_edge_refuses_a_non_loopback_upstream(self):
        code, _, err = run("edge", "--dir", str(self.dir), "--upstream", "http://10.0.0.5:8642")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
