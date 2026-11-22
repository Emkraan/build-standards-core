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


if __name__ == "__main__":
    unittest.main()
