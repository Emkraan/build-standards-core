import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "upgrade.py"


def make_source(root, marker="v1"):
    (root / "app" / "dist").mkdir(parents=True)
    (root / "app" / "dist" / "index.html").write_text(marker)
    (root / "app" / "src").mkdir()
    (root / "app" / "src" / "App.tsx").write_text("source")
    (root / "app" / "node_modules").mkdir()
    (root / "server").mkdir()
    (root / "server" / "app.py").write_text(marker)
    (root / "server" / "app_test.py").write_text("test")
    (root / "kit").mkdir()
    (root / "kit" / "k.ts").write_text("kit")
    (root / "DESIGN.md").write_text("doc")


class Health(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, *a):
        pass


PAGE = b'<html><head><script src="/assets/app.js"></script></head><body><div id="root"></div></body></html>'


def site(over=None):
    """A handler for a fake ops center. `over` maps a path to the (status, content type, body) that replaces its answer."""
    answers = {
        "/api/health": (200, "application/json", b'{"ok": true}'),
        "/api/routes": (200, "application/json", b'{"count": 120}'),
        "/": (200, "text/html", PAGE),
        "/assets/app.js": (200, "text/javascript", b"x"),
    }
    answers.update(over or {})

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            a = answers.get(self.path)
            status, kind, body = a if a else (404, "text/plain", b"no")
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    return H


def serving(handler):
    srv = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class Upgrade(unittest.TestCase):
    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, str(TOOL), *args], capture_output=True, text=True, timeout=60
        )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.src = self.d / "src"
        make_source(self.src)
        self.target = self.d / "svc"

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_copies_the_built_app_and_the_server_and_leaves_sources_tests_and_modules_out(self):
        p = self.run_tool("--source", str(self.src), "--target", str(self.target))
        self.assertEqual(p.returncode, 0, p.stderr)
        live = self.target / "opscenter"
        self.assertEqual((live / "app" / "dist" / "index.html").read_text(), "v1")
        self.assertTrue((live / "server" / "app.py").is_file())
        for gone in ("app/src", "app/node_modules", "kit", "server/app_test.py"):
            self.assertFalse((live / gone).exists(), gone)
        self.assertFalse((self.target / "opscenter.new").exists())

    def test_an_upgrade_keeps_the_replaced_copy_as_prev(self):
        self.run_tool("--source", str(self.src), "--target", str(self.target))
        (self.src / "app" / "dist" / "index.html").write_text("v2")
        self.assertEqual(
            self.run_tool("--source", str(self.src), "--target", str(self.target)).returncode, 0
        )
        self.assertEqual(
            (self.target / "opscenter" / "app" / "dist" / "index.html").read_text(), "v2"
        )
        self.assertEqual(
            (self.target / "opscenter.prev" / "app" / "dist" / "index.html").read_text(), "v1"
        )

    def test_no_built_app_is_exit_2_and_changes_nothing(self):
        (self.src / "app" / "dist" / "index.html").unlink()
        p = self.run_tool("--source", str(self.src), "--target", str(self.target))
        self.assertEqual(p.returncode, 2)
        self.assertFalse((self.target / "opscenter").exists())

    def test_a_dry_run_copies_nothing(self):
        p = self.run_tool("--source", str(self.src), "--target", str(self.target), "--dry-run")
        self.assertEqual(p.returncode, 0)
        self.assertIn("would be copied", p.stdout)
        self.assertFalse((self.target / "opscenter").exists())
        self.assertFalse((self.target / "opscenter.new").exists())

    def test_a_failed_restart_puts_the_previous_copy_back_and_restarts_again(self):
        self.run_tool("--source", str(self.src), "--target", str(self.target))
        (self.src / "app" / "dist" / "index.html").write_text("v2")
        log = self.d / "restarts.log"
        cmd = f"echo r >> {log}; exit 1"
        p = self.run_tool(
            "--source", str(self.src), "--target", str(self.target), "--restart-cmd", cmd
        )
        self.assertEqual(p.returncode, 1)
        self.assertEqual(
            (self.target / "opscenter" / "app" / "dist" / "index.html").read_text(), "v1"
        )
        self.assertEqual(len(log.read_text().split()), 2)

    def test_the_smoke_check_waits_for_a_healthy_answer_and_a_dead_url_rolls_back(self):
        srv = HTTPServer(("127.0.0.1", 0), Health)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{srv.server_address[1]}/api/health"
            self.assertEqual(
                self.run_tool(
                    "--source",
                    str(self.src),
                    "--target",
                    str(self.target),
                    "--smoke-url",
                    url,
                    "--timeout",
                    "10",
                ).returncode,
                0,
            )
        finally:
            srv.shutdown()
            srv.server_close()
        (self.src / "app" / "dist" / "index.html").write_text("v2")
        p = self.run_tool(
            "--source",
            str(self.src),
            "--target",
            str(self.target),
            "--smoke-url",
            "http://127.0.0.1:9/none",
            "--timeout",
            "2",
        )
        self.assertEqual(p.returncode, 1)
        self.assertEqual(
            (self.target / "opscenter" / "app" / "dist" / "index.html").read_text(), "v1"
        )

    def upgrade_against(self, handler, *extra):
        (self.src / "app" / "dist" / "index.html").write_text("v2")
        srv, base = serving(handler)
        try:
            return self.run_tool(
                "--source", str(self.src), "--target", str(self.target),
                "--base-url", base, "--timeout", "2", *extra,
            )  # fmt: skip
        finally:
            srv.shutdown()
            srv.server_close()

    def live_index(self):
        return (self.target / "opscenter" / "app" / "dist" / "index.html").read_text()

    def test_the_full_smoke_check_passes_on_a_healthy_server(self):
        self.run_tool("--source", str(self.src), "--target", str(self.target))
        p = self.upgrade_against(site(), "--min-routes", "100")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.live_index(), "v2")

    def test_a_server_with_too_few_routes_rolls_back_and_says_why(self):
        self.run_tool("--source", str(self.src), "--target", str(self.target))
        p = self.upgrade_against(site(), "--min-routes", "500")
        self.assertEqual(p.returncode, 1)
        self.assertIn("reports 120 routes, expected at least 500", p.stderr)
        self.assertEqual(self.live_index(), "v1")

    def test_a_server_with_no_routes_endpoint_rolls_back(self):
        self.run_tool("--source", str(self.src), "--target", str(self.target))
        p = self.upgrade_against(site({"/api/routes": (404, "text/plain", b"no")}))
        self.assertEqual(p.returncode, 1)
        self.assertIn("/api/routes did not report a route count", p.stderr)
        self.assertEqual(self.live_index(), "v1")

    def test_a_page_that_does_not_render_rolls_back(self):
        self.run_tool("--source", str(self.src), "--target", str(self.target))
        for page in (
            (200, "text/plain", b"hello"),
            (200, "text/html", b"<html>no root</html>"),
            (500, "text/html", b""),
        ):
            p = self.upgrade_against(site({"/": page}))
            self.assertEqual(p.returncode, 1, page)
            self.assertEqual(self.live_index(), "v1")

    def test_a_missing_asset_rolls_back(self):
        self.run_tool("--source", str(self.src), "--target", str(self.target))
        p = self.upgrade_against(site({"/assets/app.js": (404, "text/plain", b"")}))
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.live_index(), "v1")

    def test_a_protected_folder_is_refused_on_macos_and_changes_nothing(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("upgrade_mod", TOOL)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        home = self.d / "home"
        for name in ("Documents", "Desktop", "Downloads"):
            inside = home / name / "svc"
            self.assertEqual(mod.protected_folder(inside, home, "darwin"), name)
        self.assertEqual(mod.protected_folder(home / "Documents", home, "darwin"), "Documents")
        self.assertIsNone(mod.protected_folder(home / "Library" / "svc", home, "darwin"))
        self.assertIsNone(mod.protected_folder(home / "DocumentsOld", home, "darwin"))
        # a synced Documents folder: ~/Documents is a link, and a target given through either path is refused
        real = self.d / "cloud" / "Documents"
        real.mkdir(parents=True)
        home.mkdir(exist_ok=True)
        (home / "Documents").symlink_to(real)
        self.assertEqual(
            mod.protected_folder(home / "Documents" / "svc", home, "darwin"), "Documents"
        )
        self.assertEqual(mod.protected_folder(real / "svc", home, "darwin"), "Documents")
        self.assertIsNone(mod.protected_folder(home / "Documents" / "svc", home, "linux"))
        mod.PLATFORM = "darwin"
        os.environ["HOME"] = str(home)
        try:
            argv = ["--source", str(self.src), "--target", str(home / "Documents" / "svc")]
            self.assertEqual(mod.main(argv), 2)
            self.assertFalse((home / "Documents" / "svc" / "opscenter").exists())
            self.assertEqual(mod.main([*argv, "--allow-protected"]), 0)
        finally:
            del os.environ["HOME"]

    def test_the_routes_endpoint_the_smoke_check_reads_exists_in_the_server(self):
        routes = (Path(__file__).resolve().parent.parent / "server" / "routes.py").read_text()
        self.assertIn('r.get("/api/routes"', routes)


if __name__ == "__main__":
    unittest.main()
