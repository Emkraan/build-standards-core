"""The push channel's routes and its background loop: GET /api/live (the event stream), POST /api/live/presence (which tabs are visible
and which endpoints they show) and the tick that runs the data scan, the source watch and the warm loop.

Standard: Local Ops App section 20. The stream carries topic versions only, never data, so it makes no access decision: a tab reads
the endpoint, which is gated as before. Both routes pass the same Host and Origin gate as every other route.

Config (environment, all optional):
  OPSCENTER_LIVE_SOURCES   source files a bundler reads, separated by the OS path separator. With OPSCENTER_LIVE_BUNDLE set, a
                           change to one of them (once it holds still) runs the bundler.
  OPSCENTER_LIVE_BUNDLE    the bundler command as a JSON list of arguments, for example ["python3", "bundle.py"]. Run in the folder
                           above the served dist, under a timeout, never through a shell.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import live_bus
import live_watch


class Refused(Exception):
    """Raised for a stream that cannot open. status maps to the HTTP answer."""

    status = 503


class Stream:
    """What a stream route returns: the server calls serve(write) on the handler thread and close() when it ends."""

    def __init__(self, bus: live_bus.Bus, client: live_bus.Client):
        self.bus, self.client = bus, client

    def serve(self, write) -> None:
        live_bus.serve(self.bus, self.client, write, live_bus.HEARTBEAT_S)

    def close(self) -> None:
        self.bus.disconnect(self.client)


def install(registry, bus: live_bus.Bus | None = None) -> live_bus.Bus:
    """Register the two routes and the response hook that lets the bus watch declared endpoints."""
    bus = bus or live_bus.BUS

    def open_stream(_req):
        client = bus.connect()
        if client is None:
            raise Refused("too many live streams, this tab polls instead")
        return Stream(bus, client)

    def presence(req):
        p = req.payload()
        ok = bus.presence(p.get("id"), p.get("visible"), p.get("wants"))
        return (200 if ok else 404), {"ok": ok}

    registry.stream("/api/live", open_stream, "live")
    registry.post("/api/live/presence", presence, "live-presence")
    registry.on_response = bus.note_response
    return bus


def _sources() -> list:
    raw = os.environ.get("OPSCENTER_LIVE_SOURCES") or ""
    return [Path(p) for p in raw.split(os.pathsep) if p]


def make_loop(bus: live_bus.Bus, dist, port: int) -> live_watch.Loop:
    """The loop for this server. The data scan watches <dist>/data, the source watch exists only when a bundler is configured."""
    dist = Path(dist) if dist else Path(".")
    data = live_watch.DataWatch(bus, dist / "data")
    argv = None
    try:
        argv = json.loads(os.environ.get("OPSCENTER_LIVE_BUNDLE") or "null")
    except ValueError:
        print(
            "OPSCENTER_LIVE_BUNDLE is not a JSON list, no source watch", file=sys.stderr, flush=True
        )
    sources = _sources()

    def bundle():
        rc, tail = live_watch.run_cmd(argv, dist.resolve().parent, live_watch.BUNDLE_TIMEOUT_S)
        if rc != 0:
            raise RuntimeError(f"bundler exited {rc}: {tail.strip()[-160:]}")

    runnable = isinstance(argv, list) and bool(argv) and bool(sources)
    state = live_watch.StateWatch(lambda: sources, bundle if runnable else (lambda: None))
    if not runnable:
        state.tick = lambda now=None: False  # no bundler configured: nothing to run
    warm = live_watch.Warmer(bus, live_watch.http_fetch(port), pool=live_watch.make_pool())
    return live_watch.Loop(bus, data, state, warm)
