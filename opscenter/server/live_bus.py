"""The push channel: one topic registry with a version per topic, a server-sent-events stream (GET /api/live) that tells every open tab
which topic moved, and the presence record that says which tabs are visible and which endpoints they show.

The bus never calls an upstream system and never carries payloads: a topic event only says "this changed", and the tab then reads the
endpoint it already knows, which is gated as before. Standard: Local Ops App section 20. Stdlib only.

Frames (text/event-stream):
  retry: 3000                    reconnect delay for the browser
  event: hello                   on connect: {id, now, topics: {topic: {v, at}}} so a reconnect catches up
  event: topic                   {t, v, at} when a topic's version changes
  : hb                           comment every HEARTBEAT_S seconds, so a dead peer fails its next write

Topic names:
  data:<file>.json               a bundled dataset under the served data folder (live_watch.DataWatch)
  api:<path>                     the response body of a GET endpoint changed (note_response, the warm loop)
  <alias>                        a short name a consumer gives an endpoint every page reads (ALIASES)

A topic seen for the first time is recorded quietly (no event): a page that just loaded already holds that content, so announcing it
would double the first load.
"""

from __future__ import annotations

import hashlib
import json
import queue
import secrets
import threading
import time

MAX_CLIENTS = 24
HEARTBEAT_S = 20
RETRY_MS = 3000
QUEUE_MAX = 512
MAX_WANTS = 80
MIN_WARM_MS = 2000
MAX_WARM_MS = 3_600_000
FLAP_MAX = (
    6  # more publishes than this inside FLAP_WINDOW_S and the topic is held quiet (a loop guard)
)
FLAP_WINDOW_S = 60

# path -> short topic name. A consumer fills it before the server starts (for example ALIASES["/api/badges"] = "badges").
ALIASES: dict = {}


def api_topic(path: str) -> str:
    return ALIASES.get(path) or "api:" + path


def data_topic(name: str) -> str:
    return "data:" + name


# Keys that change on every read without the content changing. They never count toward a version, or an
# endpoint that stamps its answer (a generated_at stamp) would publish on every read and loop the tabs.
VOLATILE_KEYS = frozenset(
    {
        "generated_utc",
        "generated_at",
        "generated",
        "fetched_at",
        "fetched_utc",
        "checked_at",
        "now",
        "server_time",
    }
)


def _strip(value: object) -> object:
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def body_version(body: bytes) -> str:
    """A short hash of the content. A JSON body is hashed without its volatile stamp keys, anything else raw."""
    try:
        canon = json.dumps(_strip(json.loads(body)), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    except (ValueError, UnicodeDecodeError, RecursionError):
        canon = body
    return hashlib.sha1(canon).hexdigest()[:12]


def frame(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


def _valid_path(path: object) -> bool:
    """A path the warm loop may read: under /api/, no query, no fragment, plain characters."""
    if not isinstance(path, str) or not path.startswith("/api/") or len(path) > 200:
        return False
    if path.startswith("/api/live"):
        return False
    return all(c.isalnum() or c in "/-_.%" for c in path) and ".." not in path


class Client:
    """One open stream. The handler thread drains q. A full queue closes the client (it reconnects and
    the hello brings it up to date)."""

    def __init__(self, cid: str):
        self.id = cid
        self.q: queue.Queue = queue.Queue(QUEUE_MAX)
        self.visible = False
        self.wants: dict = {}  # topic -> (path, ms)
        self.closed = False

    def push(self, data: bytes) -> bool:
        try:
            self.q.put_nowait(data)
            return True
        except queue.Full:
            self.closed = True
            return False


class Bus:
    def __init__(self, clock=time.time, max_clients: int = MAX_CLIENTS):
        self._clock = clock
        self._max = max_clients
        self._lock = threading.RLock()
        self.topics: dict = {}  # topic -> {"v": version, "at": epoch ms}
        self.clients: dict = {}  # id -> Client
        self.paths: set = set()  # endpoints a tab has declared, the only ones note_response watches
        self.publishes = 0
        self.suppressed = 0
        self._recent: dict = {}  # topic -> publish times, for the flap guard

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    def snapshot(self) -> dict:
        with self._lock:
            return {t: dict(v) for t, v in self.topics.items()}

    def observe(self, topic: str, version: str) -> str:
        """Record a topic's version. "new" (first sight, quiet), "same" or "changed" (event sent)."""
        with self._lock:
            cur = self.topics.get(topic)
            if cur is None:
                self.topics[topic] = {"v": version, "at": self._now_ms()}
                return "new"
            if cur["v"] == version:
                return "same"
            self.topics[topic] = {"v": version, "at": self._now_ms()}
            now = self._clock()
            recent = [t for t in self._recent.get(topic, []) if now - t < FLAP_WINDOW_S]
            if len(recent) >= FLAP_MAX:
                # A topic that keeps changing is not news. Keep the version, tell nobody, the tabs'
                # five minute safety net still reads it. Cleared once it holds still for the window.
                self._recent[topic] = recent
                self.suppressed += 1
                return "same"
            recent.append(now)
            self._recent[topic] = recent
            self.publishes += 1
            out = frame("topic", {"t": topic, "v": version, "at": self.topics[topic]["at"]})
            for c in list(self.clients.values()):
                c.push(out)
            return "changed"

    def connect(self) -> Client | None:
        """Register a stream, or None when MAX_CLIENTS streams are open."""
        with self._lock:
            if len(self.clients) >= self._max:
                return None
            c = Client(secrets.token_hex(8))
            self.clients[c.id] = c
            c.push(frame("hello", {"id": c.id, "now": self._now_ms(), "topics": self.snapshot()}))
            return c

    def disconnect(self, client: Client) -> None:
        with self._lock:
            client.closed = True
            self.clients.pop(client.id, None)

    def presence(self, cid: object, visible: object, wants: object) -> bool:
        """Replace one stream's presence. False when the stream is gone or the body is not usable."""
        if not isinstance(wants, list) or not isinstance(visible, bool):
            return False
        clean: dict = {}
        for w in wants[:MAX_WANTS]:
            if (
                not isinstance(w, dict)
                or not isinstance(w.get("topic"), str)
                or len(w["topic"]) > 200
            ):
                continue
            path = w.get("path")
            if path is not None and not _valid_path(path):
                continue
            try:
                ms = min(max(int(w.get("ms") or 0), MIN_WARM_MS), MAX_WARM_MS)
            except (TypeError, ValueError):
                continue
            clean[w["topic"]] = (path, ms)
        with self._lock:
            c = self.clients.get(cid) if isinstance(cid, str) else None
            if c is None:
                return False
            c.visible = visible
            c.wants = clean
            for path, _ms in clean.values():
                if path:
                    self.paths.add(path)
            return True

    def counts(self) -> dict:
        with self._lock:
            cs = list(self.clients.values())
        return {"clients": len(cs), "visible": sum(1 for c in cs if c.visible)}

    def any_visible(self) -> bool:
        return self.counts()["visible"] > 0

    def visible_wants(self) -> dict:
        """topic -> (path, ms) for the visible streams. The smallest interval wins."""
        out: dict = {}
        with self._lock:
            for c in self.clients.values():
                if not c.visible:
                    continue
                for topic, (path, ms) in c.wants.items():
                    if topic not in out or ms < out[topic][1]:
                        out[topic] = (path, ms)
        return out

    def note_response(self, path: str, query: str, body: bytes) -> str | None:
        """Called with every 200 GET answer. Only a declared endpoint without parameters (a refresh
        flag is not one) counts, so a query variant never makes a topic flap."""
        if query not in ("", "fresh=1"):
            return None
        with self._lock:
            if path not in self.paths:
                return None
        return self.observe(api_topic(path), body_version(body))


def serve(bus: Bus, client: Client, write, heartbeat_s: float = HEARTBEAT_S) -> None:
    """The stream loop, run on the handler's own thread. write(bytes) raises OSError once the peer is
    gone, which ends the loop. The caller disconnects the client."""
    write(f"retry: {RETRY_MS}\n\n".encode("ascii"))
    while not client.closed:
        try:
            out = client.q.get(timeout=heartbeat_s)
        except queue.Empty:
            out = b": hb\n\n"
        write(out)


BUS = Bus()
