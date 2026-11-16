"""The loops behind the push channel (live_bus.py), run by one background tick in the server:

  DataWatch   stats the bundled datasets under the served data folder and publishes data:<file> when the content changes.
              Local files only, no upstream cost.
  StateWatch  stats the source files a bundler reads and, once they settle, runs the bundler (under the bundler's own lock, shared
              with any scheduled run) so a change reaches the screen in seconds instead of at the next scheduled bundle.
  Warmer      while at least one tab is visible, reads each endpoint a tab shows on that tab's cadence through the server's own
              caches, so a change upstream becomes a topic event. No tab connected, or all hidden: nothing runs and no upstream
              call is made.

Standard: Local Ops App section 20. Stdlib only. Every clock, fetch and spawn is injectable so the tests run without threads or
sockets.
"""

from __future__ import annotations

import concurrent.futures
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import live_bus

TICK_S = 1.0
STATE_QUIET_S = 1.5  # sources must hold still this long before the bundler runs
STATE_MIN_GAP_S = 20.0  # at most one bundler run per this many seconds
STATE_MAX_RUNS = (
    6  # and at most this many in STATE_RUN_WINDOW_S, a guard against a self-triggering loop
)
STATE_RUN_WINDOW_S = 600.0
BUNDLE_TIMEOUT_S = 120
WARM_MIN_GAP_S = 1.0  # after a write, a topic is read again at most once per second
WARM_TIMEOUT_S = 25
WARM_WORKERS = 4


def run_cmd(argv: list, cwd, timeout: float, env=None) -> tuple:
    """The one subprocess helper: an argument list, a timeout, and (rc, tail of output). A missing binary
    or a timeout is rc 127 or 124, never an exception."""
    try:
        r = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except OSError as exc:
        return 127, str(exc)
    return r.returncode, ((r.stdout or "") + (r.stderr or ""))[-400:]


class DataWatch:
    """data:<file> topics from the bundled datasets. Hashes a file only when its stat changed."""

    def __init__(self, bus: live_bus.Bus, folder: Path):
        self.bus = bus
        self.folder = Path(folder)
        self._sig: dict = {}

    def scan(self) -> int:
        changed = 0
        try:
            files = sorted(self.folder.glob("*.json"))
        except OSError:
            return 0
        for p in files:
            try:
                st = p.stat()
                sig = (st.st_mtime_ns, st.st_size)
                if self._sig.get(p.name) == sig:
                    continue
                body = p.read_bytes()
            except OSError:
                continue
            self._sig[p.name] = sig
            if (
                self.bus.observe(live_bus.data_topic(p.name), live_bus.body_version(body))
                == "changed"
            ):
                changed += 1
        return changed


class StateWatch:
    """Re-bundle when a source file moves. Debounced, rate limited, one run at a time."""

    def __init__(self, sources, run, outputs_marker=None, clock=time.time, threaded: bool = True):
        self._sources = sources  # callable returning the paths to watch
        self._run = run  # callable, True when the bundler ran
        self._marker = outputs_marker  # a path whose mtime says when the served bundle was written
        self._clock = clock
        self._threaded = threaded
        self.seen = None
        self.pending_since = None
        self.last_run = 0.0
        self.runs: list = []
        self.running = False
        self.skipped = 0

    def signature(self) -> tuple:
        out = []
        for p in self._sources():
            try:
                st = Path(p).stat()
                out.append((str(p), st.st_mtime_ns, st.st_size))
            except OSError:
                out.append((str(p), None, None))
        return tuple(out)

    def _behind(self, sig: tuple) -> bool:
        """True when a source is newer than the served bundle (it changed while nobody watched)."""
        if self._marker is None:
            return False
        try:
            built = Path(self._marker).stat().st_mtime_ns
        except OSError:
            return True
        return any(m is not None and m > built + 1_000_000_000 for _p, m, _s in sig)

    def tick(self, now: float | None = None) -> bool:
        """True when a bundler run started on this tick."""
        now = self._clock() if now is None else now
        sig = self.signature()
        if self.seen is None:
            self.seen = sig
            if self._behind(sig):
                self.pending_since = now - STATE_QUIET_S
        elif sig != self.seen:
            self.seen = sig
            self.pending_since = now
        if self.pending_since is None or self.running:
            return False
        if now - self.pending_since < STATE_QUIET_S or now - self.last_run < STATE_MIN_GAP_S:
            return False
        self.runs = [t for t in self.runs if now - t < STATE_RUN_WINDOW_S]
        if len(self.runs) >= STATE_MAX_RUNS:
            self.skipped += 1
            return False
        self.pending_since = None
        self.last_run = now
        self.runs.append(now)
        self.running = True
        if self._threaded:
            threading.Thread(target=self._go, daemon=True, name="live-bundle").start()
        else:
            self._go()
        return True

    def _go(self) -> None:
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001 - a failed run is retried by the next change or the cron
            print(f"live bundle: {exc}", flush=True)
        finally:
            self.running = False


class Warmer:
    """Reads each declared endpoint on its cadence while a visible tab is connected."""

    def __init__(self, bus: live_bus.Bus, fetch, clock=time.time, pool=None):
        self.bus = bus
        self._fetch = fetch  # path -> body bytes, or None when the read failed
        self._clock = clock
        self._pool = pool
        self.last: dict = {}
        self.inflight: set = set()
        self._nudged = 0.0
        self._lock = threading.Lock()
        self.calls = 0

    def nudge(self, now: float | None = None) -> None:
        """A write succeeded somewhere: read every wanted endpoint again soon (once per second at most)."""
        self._nudged = self._clock() if now is None else now

    def due(self, now: float) -> list:
        wants = self.bus.visible_wants()
        with self._lock:
            for topic in [t for t in self.last if t not in wants]:
                del self.last[topic]
            out = []
            for topic, (path, ms) in wants.items():
                if not path or topic in self.inflight:
                    continue
                last = self.last.setdefault(topic, now)  # first sight waits a full interval
                nudge_due = self._nudged > last and now - last >= WARM_MIN_GAP_S
                if now - last >= ms / 1000.0 or nudge_due:
                    out.append((topic, path))
            return out

    def tick(self, now: float | None = None) -> int:
        now = self._clock() if now is None else now
        todo = self.due(now)
        for topic, path in todo:
            with self._lock:
                self.last[topic] = now
                self.inflight.add(topic)
            if self._pool is None:
                self._run(topic, path)
            else:
                self._pool.submit(self._run, topic, path)
        return len(todo)

    def _run(self, topic: str, path: str) -> None:
        try:
            self.calls += 1
            body = self._fetch(path)
            if body is not None:
                self.bus.note_response(path, "", body)
        except Exception as exc:  # noqa: BLE001 - the next interval tries again
            print(f"live warm {path}: {exc}", flush=True)
        finally:
            with self._lock:
                self.inflight.discard(topic)


def http_fetch(port: int):
    """Read a path from this same server on loopback, so its own caches and tombstones answer."""

    def fetch(path: str):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            headers={"Accept-Encoding": "identity", "X-Live-Warm": "1"},
        )
        try:
            with urllib.request.urlopen(req, timeout=WARM_TIMEOUT_S) as r:  # noqa: S310 - fixed loopback host
                return r.read() if r.status == 200 else None
        except (urllib.error.URLError, OSError, ValueError):
            return None

    return fetch


class Loop:
    """One thread: data scan, state watch and warm, once per tick, only while a tab is connected."""

    def __init__(self, bus, data: DataWatch, state: StateWatch, warm: Warmer, clock=time.time):
        self.bus, self.data, self.state, self.warm, self._clock = bus, data, state, warm, clock
        self._stop = threading.Event()

    def tick(self, now: float | None = None) -> None:
        now = self._clock() if now is None else now
        counts = self.bus.counts()
        if counts["clients"] == 0:
            self.state.seen = None  # the next tab starts with a catch-up check
            return
        self.data.scan()
        if counts["visible"] > 0:
            self.state.tick(now)
            self.warm.tick(now)
        else:
            self.state.seen = None

    def run(self) -> None:
        while not self._stop.wait(TICK_S):
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - a bad pass must never stop the loop
                print(f"live loop: {exc}", flush=True)

    def stop(self) -> None:
        self._stop.set()


def make_pool() -> concurrent.futures.ThreadPoolExecutor:
    return concurrent.futures.ThreadPoolExecutor(
        max_workers=WARM_WORKERS, thread_name_prefix="live-warm"
    )
