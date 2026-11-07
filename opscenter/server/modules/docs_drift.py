"""
docs_drift.py
Purpose: The documentation drift feed (a provider slot, report only): pages that are behind the code they document, and each app's README and
         changelog facts. The consumer owns where the report comes from (a workflow artifact, a service, a file); the core owns the summary
         shape, the status vocabulary, the cache, the refresh thread and the routes. Nothing here writes to the docs home or the code host.
Date:    2026-11-07
Notes:   Opt in: with no provider (`OPSCENTER_DOCS_DRIFT_PROVIDER` unset) no route exists and the tab is hidden. A GET never waits on the source:
         it returns the cache at once and starts one background refresh when the cache is stale.

Provider (`path/to/file.py:ClassName`, every method optional except the first):
         docs_drift_source(now) -> {"run": {id, created, head, url}, "drift": <drift report>, "facts": [<facts item>], "preview": <write preview> | None}
                                   | None (no successful run yet) | {"error": "<text>"} (a fetch failed: the last good data is kept)
         docs_drift_latest_run() -> {"id", ...} | None      cheap: when the id equals the cached run's, the source is not called again
         docs_drift_dispatch() -> {"started": bool, "reason"?, "url"?}      absent: Run now is refused (501)
         authorize(headers, action, key) -> actor | falsy   actions docs-drift.read and docs-drift.run; null default refuses everything
Drift report: {head, things: [{thing, name, home, watch, pages: [{thing, page, title, link, status, basis, since, commits, files, files_total,
         edited, footer, detail, versions}]}], errors: [{thing, page, error}]}
         status: behind | current | current-unverified | sha-missing | no-footer     basis: footer-commit | footer-date | edit-date | none
         Closed sets: an unknown value is kept and a client draws it neutral. `files` is at most 15 per row, `files_total` the full count.
Facts item: {facts: {thing, name, version, latest_release, home, ...}, readme: {status, lines, detail}, changelog: {status, missing, page}}
         readme.status: missing | stale-version | no-confluence-link | current      changelog.status: changelog-page-unreadable |
         no-changelog-page | no-changelog-file | gaps | complete
Summary: {fetched_utc, run, counts, bases, total, behind (at most 40, most commits first), behind_total, no_verdict (no-footer and sha-missing, at
         most 40), facts, preview, pending_run, errors, error, refreshing}
Cache:   `<state>/dashboard/docs-drift.json` (`OPSCENTER_DOCS_DRIFT_CACHE`), 900 s; a run that Run now started is polled for 600 s.
Routes:  GET /api/docs-drift   POST /api/docs-drift/refresh   POST /api/docs-drift/run
API:     summarize(drift, facts, run, preview=None, now=None)  refresh(provider, cache_path, force=False)  run_now(provider, cache_path)
         read_state(provider, cache_path)  register(registry, provider)
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
from pathlib import Path

import optional_provider as op
import paths

CACHE_SECONDS = 900
PENDING_SECONDS = 600
MAX_BEHIND = 40
MAX_DIFF_LINES = 80
EMPTY = {
    "fetched_utc": None,
    "run": None,
    "counts": {},
    "bases": {},
    "total": 0,
    "behind": [],
    "behind_total": 0,
    "no_verdict": [],
    "preview": None,
    "pending_run": None,
    "facts": [],
    "errors": 0,
    "error": None,
    "refreshing": False,
}
ROW_KEYS = (
    "thing",
    "page",
    "title",
    "link",
    "basis",
    "since",
    "commits",
    "files",
    "files_total",
    "edited",
    "status",
    "detail",
)
PREVIEW_KEEP = (
    "page",
    "thing",
    "kind",
    "title",
    "link",
    "status",
    "reasons",
    "added",
    "removed",
    "older_gaps",
    "footer",
    "tokens",
)

_lock = threading.Lock()
_running = False


def cache_path():
    return Path(
        os.environ.get("OPSCENTER_DOCS_DRIFT_CACHE") or paths.dashboard_dir() / "docs-drift.json"
    )


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _stamp(t):
    return t.isoformat(timespec="seconds")


def _read(path):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _preview(doc):
    """The write preview of the run (what a write job would change), or None for a run that had none. Keys are filtered and the diff is cut."""
    if not isinstance(doc, dict) or not isinstance(doc.get("pages"), list):
        return None
    pages = []
    for page in doc["pages"]:
        if isinstance(page, dict):
            row = {k: page.get(k) for k in PREVIEW_KEEP}
            row["diff"] = [str(x)[:400] for x in (page.get("diff") or [])[:MAX_DIFF_LINES]]
            pages.append(row)
    return {"model": doc.get("model"), "head": doc.get("head"), "pages": pages}


def summarize(drift, facts, run, preview=None, now=None):
    """Pure: the page payload from the drift report, the facts list, the run and the optional write preview. Never raises on empty input."""
    drift = drift if isinstance(drift, dict) else {}
    rows = [
        r
        for t in (drift.get("things") or [])
        if isinstance(t, dict)
        for r in (t.get("pages") or [])
        if isinstance(r, dict)
    ]
    counts, bases = {}, {}
    for row in rows:
        s = row.get("status", "")
        counts[s] = counts.get(s, 0) + 1
        if row.get("basis"):
            bases[row["basis"]] = bases.get(row["basis"], 0) + 1
    behind = sorted(
        (r for r in rows if r.get("status") == "behind"), key=lambda r: -int(r.get("commits") or 0)
    )
    other = [r for r in rows if r.get("status") in ("no-footer", "sha-missing")]
    facts_rows = []
    for item in facts if isinstance(facts, list) else []:
        if not isinstance(item, dict):
            continue
        f = item.get("facts") or {}
        facts_rows.append(
            {
                "thing": f.get("thing"),
                "name": f.get("name"),
                "version": f.get("version"),
                "latest_release": f.get("latest_release"),
                "home": f.get("home"),
                "readme": item.get("readme") or {},
                "changelog": item.get("changelog") or {},
            }
        )
    return {
        "fetched_utc": _stamp(now or _now()),
        "run": run,
        "counts": counts,
        "bases": bases,
        "total": len(rows),
        "behind": [{k: r.get(k) for k in ROW_KEYS} for r in behind[:MAX_BEHIND]],
        "behind_total": len(behind),
        "no_verdict": [{k: r.get(k) for k in ROW_KEYS} for r in other[:MAX_BEHIND]],
        "facts": facts_rows,
        "preview": _preview(preview),
        "pending_run": None,
        "errors": len(drift.get("errors") or []),
        "error": None,
        "refreshing": False,
    }


def _fail(cache, text):
    out = dict(EMPTY, **cache)
    out["error"] = str(text)[:300]
    out["refreshing"] = False
    return out


def refresh(provider, path, force=False, now=None):
    """Fetch the source if it has a newer run than the cache (or the cache is forced). Never raises: a failure is kept as `error` beside the
    last good data."""
    now = now or _now()
    cache = _read(path)
    try:
        source = op.method(provider, "docs_drift_source")
        if source is None:
            raise RuntimeError("no docs drift source is configured")
        latest = op.method(provider, "docs_drift_latest_run")
        if latest and not force:
            run = latest()
            if run and (cache.get("run") or {}).get("id") == run.get("id"):
                cache["fetched_utc"] = _stamp(now)
                cache["error"] = None
                cache["refreshing"] = False
                _write(path, cache)
                return cache
        got = source(now)
        if got is None:
            raise RuntimeError("no successful docs drift run yet")
        if not isinstance(got, dict):
            raise RuntimeError(
                "the docs drift source answered with something that is not an object"
            )
        if got.get("error"):
            raise RuntimeError(got["error"])
        summary = summarize(
            got.get("drift"), got.get("facts"), got.get("run"), got.get("preview"), now
        )
        pending = cache.get("pending_run")
        if pending and (summary.get("run") or {}).get("id") == (cache.get("run") or {}).get("id"):
            summary["pending_run"] = pending  # the run it started has not finished yet
    except Exception as err:  # noqa: BLE001 - a failed fetch keeps the last good data
        summary = _fail(cache, err)
    _write(path, summary)
    return summary


def run_now(provider, path, now=None):
    """Ask the consumer to start a run. One at a time is the consumer's rule (it answers started false with a reason). Never raises."""
    dispatch = op.method(provider, "docs_drift_dispatch")
    if dispatch is None:
        return {"started": False, "reason": "no way to start a run is configured"}
    try:
        out = dispatch()
    except Exception as err:  # noqa: BLE001
        return {"started": False, "reason": str(err)[:300]}
    if not isinstance(out, dict) or not out.get("started"):
        return {"started": False, **(out if isinstance(out, dict) else {})}
    cache = _read(path)
    cache["pending_run"] = {
        "since": _stamp(now or _now()),
        "after_run": (cache.get("run") or {}).get("id"),
    }
    _write(path, cache)
    return {"started": True}


def _pending(cache, now=None):
    p = cache.get("pending_run")
    if not isinstance(p, dict):
        return None
    try:
        age = ((now or _now()) - dt.datetime.fromisoformat(p["since"])).total_seconds()
    except (KeyError, ValueError):
        return None
    return p if age < PENDING_SECONDS else None


def _stale(cache, now=None):
    if _pending(cache, now):
        return True  # polling for the new run: the same run id means no download
    fetched = cache.get("fetched_utc")
    if not fetched:
        return True
    try:
        age = ((now or _now()) - dt.datetime.fromisoformat(fetched)).total_seconds()
    except ValueError:
        return True
    return age > CACHE_SECONDS


def _background(provider, path):
    global _running
    try:
        refresh(provider, path)
    finally:
        with _lock:
            _running = False


def read_state(provider, path, now=None):
    """The cached summary at once. Starts one background refresh when it is stale, so a GET never waits on the source."""
    global _running
    cache = dict(EMPTY, **_read(path))
    cache["pending_run"] = _pending(cache, now)
    if _stale(cache, now):
        with _lock:
            if not _running:
                _running = True
                threading.Thread(target=_background, args=(provider, path), daemon=True).start()
            cache["refreshing"] = True
    return cache


def register(r, provider):
    def who(q, action):
        return op.actor_of(q.headers, provider, action)

    def get(q):
        who(q, "docs-drift.read")
        return read_state(provider, cache_path())

    def refresh_(q):
        who(q, "docs-drift.read")
        return refresh(provider, cache_path(), force=True)

    def run_(q):
        who(q, "docs-drift.run")
        out = run_now(provider, cache_path())
        return (
            out
            if out.get("started")
            else (501 if "configured" in out.get("reason", "") else 409, out)
        )

    r.add("GET", "/api/docs-drift", get, name="docs_drift.get")
    r.add("POST", "/api/docs-drift/refresh", refresh_, name="docs_drift.refresh")
    r.add("POST", "/api/docs-drift/run", run_, name="docs_drift.run")
