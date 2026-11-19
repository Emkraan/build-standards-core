#!/usr/bin/env python3
"""Set up and check phone access to the agent over its API server (standards/hermes-api-access.md).

One command line for the whole procedure, stdlib only, Python 3.9. It holds no host, address or
account value: every machine-only value is a parameter.

  plugin           install the pinned push plugin (rule hermes-api-access.6). With --check it changes
                   nothing and exits 1 when the installed plugin differs from the pin
  key              stage the API server flag and a bearer key in the agent env file, only when missing
  tls              create the private certificate authority and the edge certificate, only when missing
  edge             run the reference TLS edge in front of the loopback API server
  pair             run the plugin's own pair command on this host (it shows the one-time link as a QR)
  gateway-check    prove the gateway log lists only the API server as connected (rule hermes-api-access.8)

The plugin source is data. The registry entry for the plugin in hermes/tools.json carries `pin`
(repository, path, commit, version). A consumer overrides any field with --pin-file (KEY=value lines,
keys repository, path, commit and version) or with --repository, --path, --commit and --version. The
order is parameter, then pin file, then registry. A consumer whose plugin source is private supplies
its own source this way and the core never names it.

Exit codes: 0 ok, 1 drift or a failed check, 2 a bad parameter or pin.
Nothing here prints the API key or a pairing link.
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import os
import re
import secrets
import select
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "hermes" / "tools.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PIN_KEYS = ("repository", "path", "commit", "version")
KEY_NAME = "API_SERVER_KEY"
FLAG_NAME = "API_SERVER_ENABLED"
KEY_MIN = 16
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


class UsageError(Exception):
    """A bad parameter or pin: the command exits 2."""


def agent_home(arg: str | None) -> Path:
    return Path(arg or os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()


# ---- plugin: the pinned source and its drift check ----------------------------------------------


def read_pin_file(path: Path) -> dict:
    out: dict = {}
    for line in path.read_text(encoding="utf8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in PIN_KEYS:
            out[key.strip()] = value.strip()
    return out


def resolve_pin(entry_id: str, overrides: dict, pin_file: str | None) -> tuple[dict, str]:
    """(pin, plugin name). Parameter over pin file over registry, and the commit must be a full sha."""
    tools = json.loads(REGISTRY.read_text(encoding="utf8"))["tools"]
    entry = next((t for t in tools if t.get("id") == entry_id), None)
    if not entry or "plugin" not in entry:
        raise UsageError(f"{entry_id}: no plugin entry in hermes/tools.json")
    pin = dict(entry.get("pin") or {})
    if pin_file:
        try:
            pin.update({k: v for k, v in read_pin_file(Path(pin_file).expanduser()).items() if v})
        except OSError as exc:
            raise UsageError(f"pin file {pin_file}: {exc.strerror}") from exc
    pin.update({k: v for k, v in overrides.items() if v})
    missing = [k for k in ("repository", "path", "commit") if not pin.get(k)]
    if missing:
        raise UsageError(
            f"{entry_id}: no {', '.join(missing)} in the registry, the pin file or the parameters"
        )
    if not SHA_RE.match(pin["commit"]):
        raise UsageError(
            f"{entry_id}: commit must be a full 40 character sha, never a branch or tag"
        )
    return pin, entry["plugin"]


def installed_commit(dest: Path) -> str:
    try:
        return (dest / ".pinned-sha").read_text(encoding="utf8").strip()
    except OSError:
        return ""


def fetch_plugin(pin: dict, work: Path) -> Path:
    """Fetch exactly the pinned commit and return the plugin directory. Raises RuntimeError on any mismatch."""

    def git(*args: str) -> str:
        r = subprocess.run(
            ["git", "-C", str(work), *args], capture_output=True, text=True, timeout=300
        )
        if r.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: {(r.stdout + r.stderr).strip()[-300:]}")
        return r.stdout.strip()

    git("init", "-q")
    git("fetch", "-q", "--depth", "1", pin["repository"], pin["commit"])
    if git("rev-parse", "FETCH_HEAD") != pin["commit"]:
        raise RuntimeError("the fetched commit does not match the pin")
    r = subprocess.run(
        ["git", "-C", str(work), "archive", "FETCH_HEAD", pin["path"]],
        capture_output=True,
        timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"path {pin['path']} is not in commit {pin['commit'][:12]}")
    subprocess.run(["tar", "-x", "-C", str(work)], input=r.stdout, check=True, timeout=300)
    src = work / pin["path"]
    if not (src / "plugin.yaml").is_file():
        raise RuntimeError(f"no plugin.yaml at {pin['path']} in {pin['commit'][:12]}")
    return src


def yaml_version(plugin_yaml: Path) -> str:
    m = re.search(r"^version:\s*\"?([^\s\"]+)", plugin_yaml.read_text(encoding="utf8"), re.M)
    return m.group(1) if m else ""


def cmd_plugin(args: argparse.Namespace) -> int:
    pin, plugin = resolve_pin(
        args.id,
        {k: getattr(args, k) for k in PIN_KEYS},
        args.pin_file,
    )
    dest = agent_home(args.home) / "plugins" / plugin
    have = installed_commit(dest)
    print(f"pinned:    {pin['commit']} {pin.get('version', '')}".rstrip())
    print(f"installed: {have or 'none'}")
    if args.check:
        if have == pin["commit"] and (dest / "plugin.yaml").is_file():
            print("ok")
            return 0
        print("drift")
        return 1
    if have == pin["commit"] and (dest / "plugin.yaml").is_file():
        print(f"{plugin} already at the pinned commit")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                src = fetch_plugin(pin, Path(tmp))
            except (RuntimeError, subprocess.SubprocessError) as exc:
                print(f"not installed: {exc}", file=sys.stderr)
                return 1
            got = yaml_version(src / "plugin.yaml")
            if pin.get("version") and got != pin["version"]:
                print(
                    f"not installed: plugin.yaml says {got or 'nothing'}, the pin says "
                    f"{pin['version']}. Review the commit and update the pin.",
                    file=sys.stderr,
                )
                return 1
            staged = dest.with_name(dest.name + ".new")
            shutil.rmtree(staged, ignore_errors=True)
            shutil.copytree(src, staged)
            (staged / ".pinned-sha").write_text(pin["commit"] + "\n", encoding="utf8")
            shutil.rmtree(dest, ignore_errors=True)
            os.replace(staged, dest)
        print(f"installed {plugin} {got} at {pin['commit'][:12]}")
        print("A new plugin version loads at the next gateway restart.")
    if args.no_enable:
        return 0
    r = subprocess.run(["hermes", "plugins", "enable", plugin], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"enable failed: {(r.stdout + r.stderr).strip()[-300:]}", file=sys.stderr)
        return 1
    return 0


# ---- key: stage the API server once --------------------------------------------------------------


def env_value(env: Path, name: str) -> str:
    try:
        for line in env.read_text(encoding="utf8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name:
                return value.strip().strip("\"'")
    except OSError:
        pass
    return ""


def cmd_key(args: argparse.Namespace) -> int:
    env = Path(args.env_file).expanduser() if args.env_file else agent_home(args.home) / ".env"
    add = []
    made = False
    if len(env_value(env, KEY_NAME)) < KEY_MIN:
        add.append(f"{KEY_NAME}={secrets.token_urlsafe(32)}")
        made = True
    if env_value(env, FLAG_NAME).lower() not in ("true", "1", "yes"):
        add.append(f"{FLAG_NAME}=true")
    if add:
        env.parent.mkdir(parents=True, exist_ok=True)
        existing = env.read_text(encoding="utf8") if env.exists() else ""
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf8") as fh:
            fh.write(prefix + "\n".join(add) + "\n")
    if env.exists():
        os.chmod(env, 0o600)
    length = len(env_value(env, KEY_NAME))
    # The name, the length and a boolean only, never the value (rule hermes-api-access.2).
    print(f"{KEY_NAME}: length {length}, ok {length >= KEY_MIN}, created now {made}")
    print("The API server starts at the next gateway restart.")
    return 0 if length >= KEY_MIN else 1


# ---- tls: a private authority and the edge certificate -------------------------------------------


def openssl(*args: str, cwd: Path | None = None) -> str:
    r = subprocess.run(["openssl", *args], capture_output=True, text=True, cwd=cwd, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"openssl {args[0]} failed: {(r.stdout + r.stderr).strip()[-300:]}")
    return r.stdout


def covers(meta: dict, hosts: list[str], ips: list[str]) -> bool:
    return sorted(meta.get("hosts", [])) == sorted(hosts) and sorted(meta.get("ips", [])) == sorted(
        ips
    )


def cmd_tls(args: argparse.Namespace) -> int:
    hosts, ips = args.host, args.ip
    if not hosts and not ips:
        raise UsageError("tls needs at least one --host or --ip: the names the edge is reached by")
    d = Path(args.dir).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    meta_file = d / "meta.json"
    try:
        meta = json.loads(meta_file.read_text(encoding="utf8"))
    except (OSError, ValueError):
        meta = {}
    leaf, leaf_key = d / "edge.crt", d / "edge.key"
    ca, ca_key = d / "ca.crt", d / "ca.key"
    if ca.is_file() and ca_key.is_file():
        print("authority present, kept")
    else:
        openssl("ecparam", "-genkey", "-name", "prime256v1", "-noout", "-out", str(ca_key))
        (d / "ca.cnf").write_text(
            "[req]\ndistinguished_name=dn\nx509_extensions=v3\nprompt=no\n[dn]\nCN=Private edge authority\n"
            "[v3]\nbasicConstraints=critical,CA:true\nkeyUsage=critical,keyCertSign,cRLSign\n"
            "subjectKeyIdentifier=hash\n",
            encoding="utf8",
        )
        openssl(
            "req", "-x509", "-new", "-key", str(ca_key), "-days", str(args.ca_days),
            "-config", str(d / "ca.cnf"), "-out", str(ca),
        )  # fmt: skip
        meta = {}
        print("authority created")
    fresh = (
        leaf.is_file()
        and leaf_key.is_file()
        and covers(meta, hosts, ips)
        and subprocess.run(
            ["openssl", "x509", "-checkend", str(30 * 86400), "-noout", "-in", str(leaf)],
            capture_output=True,
        ).returncode
        == 0
    )
    if fresh:
        print("edge certificate present, covers the names, not expiring within 30 days, kept")
    else:
        alt = [f"DNS.{i + 1}={h}" for i, h in enumerate(hosts)] + [
            f"IP.{i + 1}={ip}" for i, ip in enumerate(ips)
        ]
        (d / "leaf.cnf").write_text(
            "[req]\ndistinguished_name=dn\nprompt=no\n[dn]\nCN="
            + (hosts or ips)[0]
            + "\n[v3]\nbasicConstraints=CA:false\nkeyUsage=digitalSignature\n"
            "extendedKeyUsage=serverAuth\nsubjectAltName=@alt\n[alt]\n" + "\n".join(alt) + "\n",
            encoding="utf8",
        )
        openssl("ecparam", "-genkey", "-name", "prime256v1", "-noout", "-out", str(leaf_key))
        openssl(
            "req", "-new", "-key", str(leaf_key), "-config", str(d / "leaf.cnf"),
            "-out", str(d / "edge.csr"),
        )  # fmt: skip
        openssl(
            "x509", "-req", "-in", str(d / "edge.csr"), "-CA", str(ca), "-CAkey", str(ca_key),
            "-CAserial",
            str(d / "ca.srl"),
            "-CAcreateserial", "-days", str(args.days), "-extfile", str(d / "leaf.cnf"),
            "-extensions", "v3", "-out", str(leaf),
        )  # fmt: skip
        meta = {"hosts": hosts, "ips": ips}
        print("edge certificate issued")
    meta_file.write_text(json.dumps(meta), encoding="utf8")
    for f in (ca_key, leaf_key, meta_file):
        os.chmod(f, 0o600)
    fp = openssl("x509", "-in", str(ca), "-noout", "-fingerprint", "-sha256").strip()
    print(f"install this certificate on the phone and trust it: {ca}")
    print(fp)
    return 0


# ---- edge: the reference TLS front ---------------------------------------------------------------


def make_handler(upstream: str):
    parts = urlsplit(upstream)
    host, port = parts.hostname or "127.0.0.1", parts.port or 80

    class Edge(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "edge"

        def log_message(
            self, format, *args
        ):  # the request line can carry a path, never log headers or bodies
            sys.stderr.write(f"edge: {self.command} {self.path.split('?', 1)[0]}\n")

        def _tunnel(self):
            up = socket.create_connection((host, port), timeout=30)
            lines = [f"{self.command} {self.path} HTTP/1.1"]
            lines += [f"{k}: {v}" for k, v in self.headers.items() if k.lower() != "host"]
            lines.insert(1, f"Host: {host}:{port}")
            up.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
            up.settimeout(None)
            self.connection.settimeout(None)
            socks = [self.connection, up]
            self.close_connection = True
            while True:
                ready, _, _ = select.select(socks, [], [], 300)
                if not ready:
                    break
                for s in ready:
                    data = s.recv(65536)
                    if not data:
                        up.close()
                        return
                    (up if s is self.connection else self.connection).sendall(data)
            up.close()

        def _proxy(self):
            if "websocket" in self.headers.get("Upgrade", "").lower():
                return self._tunnel()
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            fwd = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP | {"host"}}
            conn = http.client.HTTPConnection(host, port, timeout=300)
            try:
                conn.request(self.command, self.path, body=body, headers=fwd)
                resp = conn.getresponse()
            except OSError:
                self.send_error(502, "upstream unreachable")
                return
            self.send_response(resp.status)
            known = resp.getheader("Content-Length") is not None
            for k, v in resp.getheaders():
                if k.lower() not in HOP_BY_HOP:
                    self.send_header(k, v)
            if not known:
                self.send_header("Connection", "close")  # a stream (events) ends when upstream ends
                self.close_connection = True
            self.end_headers()
            while True:
                chunk = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
            conn.close()

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _proxy

    return Edge


def serve_edge(bind: str, port: int, upstream: str, tls_dir: Path) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((bind, port), make_handler(upstream))
    server.daemon_threads = True
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(str(tls_dir / "edge.crt"), str(tls_dir / "edge.key"))
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    return server


def cmd_edge(args: argparse.Namespace) -> int:
    tls_dir = Path(args.dir).expanduser()
    if not (tls_dir / "edge.crt").is_file():
        raise UsageError(f"no edge certificate in {tls_dir}: run the tls command first")
    up = urlsplit(args.upstream)
    if up.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise UsageError("the upstream must be the loopback API server (rule hermes-api-access.1)")
    server = serve_edge(args.bind, args.port, args.upstream, tls_dir)
    print(f"edge listening on {args.bind}:{args.port} for {args.upstream}", flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


# ---- pair: the plugin's own command --------------------------------------------------------------


def cmd_pair(args: argparse.Namespace) -> int:
    _, plugin = resolve_pin(args.id, {}, args.pin_file)
    return subprocess.call(["hermes", plugin, "pair"])


# ---- gateway-check: the retired bot is gone (rule hermes-api-access.8) ---------------------------

CONNECTED = re.compile(r"[^\x00-\x7f] (\S+) connected\s*$")
RUNNING = re.compile(r"Gateway running with (\d+) platform")
STOPPED = re.compile(r"all adapters disconnected")


def connected_platforms(lines) -> tuple[set, int]:
    """The platforms the gateway reported connected in its latest start, and the count it announced."""
    now: set = set()
    last: tuple[set, int] = (set(), -1)
    for line in lines:
        if STOPPED.search(line):
            now = set()
            continue
        m = CONNECTED.search(line)
        if m:
            now.add(m.group(1))
        m = RUNNING.search(line)
        if m:
            last = (set(now), int(m.group(1)))
    return last


def cmd_gateway_check(args: argparse.Namespace) -> int:
    log = (
        Path(args.log).expanduser() if args.log else agent_home(args.home) / "logs" / "gateway.log"
    )
    try:
        with open(log, encoding="utf8", errors="replace") as fh:
            platforms, count = connected_platforms(fh)
    except OSError as exc:
        print(f"cannot read the gateway log {log}: {exc.strerror}", file=sys.stderr)
        return 2
    if count < 0:
        print(
            "no gateway start found in the log: restart the gateway and run this again",
            file=sys.stderr,
        )
        return 2
    print(f"connected: {', '.join(sorted(platforms)) or 'none'} (the gateway announced {count})")
    if platforms == {args.platform} and count == 1:
        print("ok")
        return 0
    print(f"fail: expected only {args.platform}")
    return 1


# ---- command line --------------------------------------------------------------------------------


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("--home", help="agent home (default HERMES_HOME or ~/.hermes)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def pin_args(s):
        s.add_argument("--id", default="phone-push", help="registry entry id")
        s.add_argument("--pin-file", help="KEY=value lines: repository, path, commit, version")

    s = sub.add_parser("plugin", help="install the pinned push plugin, or --check it")
    pin_args(s)
    for k in PIN_KEYS:
        s.add_argument(f"--{k}")
    s.add_argument("--check", action="store_true", help="change nothing, exit 1 on drift")
    s.add_argument("--no-enable", action="store_true", help="do not run hermes plugins enable")
    s.set_defaults(fn=cmd_plugin)

    s = sub.add_parser("key", help="stage the API server flag and key once")
    s.add_argument("--env-file")
    s.set_defaults(fn=cmd_key)

    s = sub.add_parser("tls", help="create the private authority and the edge certificate once")
    s.add_argument(
        "--dir", required=True, help="directory for the authority and certificate (mode 0700)"
    )
    s.add_argument("--host", action="append", default=[], help="a DNS name the edge is reached by")
    s.add_argument("--ip", action="append", default=[], help="an IP address the edge is reached by")
    s.add_argument("--days", type=int, default=397)
    s.add_argument("--ca-days", type=int, default=1825)
    s.set_defaults(fn=cmd_tls)

    s = sub.add_parser("edge", help="run the reference TLS edge")
    s.add_argument("--dir", required=True)
    s.add_argument("--port", type=int, default=9123)
    s.add_argument("--bind", default="0.0.0.0")
    s.add_argument("--upstream", default="http://127.0.0.1:8642")
    s.set_defaults(fn=cmd_edge)

    s = sub.add_parser("pair", help="run the plugin's own pair command")
    pin_args(s)
    s.set_defaults(fn=cmd_pair)

    s = sub.add_parser("gateway-check", help="the gateway log lists only the API server")
    s.add_argument("--log", help="gateway log (default <home>/logs/gateway.log)")
    s.add_argument("--platform", default="api_server")
    s.set_defaults(fn=cmd_gateway_check)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.fn(args)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
