#!/usr/bin/env python3
"""
driver.py

Purpose: The reference driver of the work tracker adapter (tracker/params.py `driver_cmd`): a minimal JSON-RPC
         StreamableHTTP client for a tracker MCP connector. It reuses an OAuth bearer token that another tool cached
         in a file, performs the MCP handshake (initialize and notifications/initialized), then issues one tools/call
         and prints the parsed result as JSON. Honors CURL_CA_BUNDLE or REQUESTS_CA_BUNDLE when set.

Usage:
  python3 driver.py <tool_name> '<json_args>'

Environment:
  TRACKER_ENDPOINT    the connector URL (default the Atlassian MCP endpoint)
  TRACKER_TOKEN_FILE  JSON file holding {"access_token": "..."} (required; no default, so nothing reads a token by guess)

Example:
  python3 driver.py getJiraIssue '{"cloudId":"...","issueIdOrKey":"ABC-123"}'

A consumer with another tracker or another auth writes its own driver with the same command line and output and names it
in `driver_cmd`; the contract is DESIGN.md 12.15.
"""

import json
import os
import ssl
import sys
import urllib.request

ENDPOINT = os.environ.get("TRACKER_ENDPOINT") or "https://mcp.atlassian.com/v1/mcp"
TOKEN_PATH = os.path.expanduser(os.environ.get("TRACKER_TOKEN_FILE") or "")


def load_token():
    if not TOKEN_PATH:
        print(json.dumps({"error": "TRACKER_TOKEN_FILE is not set"}), file=sys.stderr)
        sys.exit(1)
    with open(TOKEN_PATH) as f:
        data = json.load(f)
    return data["access_token"]


def make_ssl_context():
    ca = os.environ.get("CURL_CA_BUNDLE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if ca and os.path.exists(ca):
        return ssl.create_default_context(cafile=ca)
    return ssl.create_default_context()


def parse_sse_or_json(raw):
    """The MCP StreamableHTTP endpoint returns either application/json or an
    SSE stream (event: message\\ndata: {...}). Extract the JSON-RPC object."""
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith("{"):
        return json.loads(raw)
    # SSE: find the last data: line carrying JSON
    result = None
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:") :].strip()
            if payload and payload != "[DONE]":
                try:  # noqa: SIM105
                    result = json.loads(payload)
                except json.JSONDecodeError:
                    pass
    return result


def rpc(token, ctx, payload, session_id=None, notify=False):
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "node",
        "MCP-Protocol-Version": "2024-11-05",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    req = urllib.request.Request(ENDPOINT, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            sid = resp.headers.get("Mcp-Session-Id", session_id)
            raw = resp.read().decode("utf-8")
            if notify:
                return sid, None
            return sid, parse_sse_or_json(raw)
    except urllib.error.HTTPError as e:
        errbody = e.read().decode("utf-8", "replace")
        print(
            json.dumps({"http_error": e.code, "headers": dict(e.headers), "body": errbody[:1000]}),
            file=sys.stderr,
        )
        raise


def main():
    if len(sys.argv) < 3:
        print("usage: driver.py <tool_name> '<json_args>'", file=sys.stderr)
        sys.exit(2)
    tool = sys.argv[1]
    args = json.loads(sys.argv[2])

    token = load_token()
    ctx = make_ssl_context()

    # 1. initialize
    sid, init = rpc(
        token,
        ctx,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "team-prefix-ops-center", "version": "1.0"},
            },
        },
    )
    if not init or "result" not in init:
        print(json.dumps({"error": "initialize failed", "raw": init}), file=sys.stderr)
        sys.exit(1)

    # 2. notifications/initialized
    rpc(
        token,
        ctx,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        session_id=sid,
        notify=True,
    )

    # 3. tools/call
    _, out = rpc(
        token,
        ctx,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        },
        session_id=sid,
    )

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
