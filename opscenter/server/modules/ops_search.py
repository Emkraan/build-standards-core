"""
ops_search.py - global search of the ops center (opscenter/DESIGN.md section 12.3, item 23, and Table A row 9).

One query fans out across every local source the ops center knows about and returns grouped, ranked hits with a
deep link per hit: board items (open and completed), 1:1 topics (people slot), text files in configured folders,
and the agent runtime's chat sessions (titles and message full text, read only). The work tracker is searched
live by the server in a separate scope (tracker_query builds its query). Pure stdlib; read only everywhere.

Parameters (environment, or local/params.json `search`):
  SEARCH_DIRS        JSON list of {"path", "label", "recursive"}: the folders whose text files are searched,
                     default the state folder and its plans folder
  SEARCH_RUNTIME_DB  the runtime's session database, default <agent home>/state.db (tables sessions, messages,
                     messages_fts and optionally messages_fts_trigram); absent means no session group
  OPSCENTER_STATE_DIR  the state tree (default ~/.opscenter/state)
"""

import json
import os
import re
import sqlite3
from pathlib import Path

import paths

DASH = paths.dashboard_dir()
DATA = paths.state_dir() / "app" / "dist" / "data"
RUNTIME_DB = Path(os.environ.get("SEARCH_RUNTIME_DB") or paths.agent_home() / "state.db")


def _dirs():
    raw = os.environ.get("SEARCH_DIRS")
    if raw:
        return [
            (Path(d["path"]), d.get("label", ""), bool(d.get("recursive"))) for d in json.loads(raw)
        ]
    return [(paths.state_dir(), "State", False), (paths.state_dir() / "plans", "Plans", True)]


TEXT_EXT = {".md", ".txt", ".json", ".ps1", ".sh", ".yaml", ".yml"}
MAX_FILE_BYTES = 1_500_000
PER_GROUP = 25


def _terms(q):
    return [t for t in re.findall(r'"([^"]+)"|(\S+)', q) for t in t if t]


def _lower_terms(q):
    return [t.lower() for t in _terms(q)]


def _match(text, terms):
    low = (text or "").lower()
    return all(t in low for t in terms)


def _score(title, body, terms):
    tl = (title or "").lower()
    bl = (body or "").lower()
    s = 0
    for t in terms:
        if t in tl:
            s += 10
        s += min(bl.count(t), 10)
    return s


def _snippet(text, terms, width=180):
    if not text:
        return ""
    flat = re.sub(r"\s+", " ", text)
    low = flat.lower()
    pos = min((low.find(t) for t in terms if low.find(t) >= 0), default=0)
    start = max(0, pos - width // 3)
    out = flat[start : start + width]
    return ("..." if start else "") + out + ("..." if start + width < len(flat) else "")


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _hit(kind, title, snippet, score, **extra):
    h = {"kind": kind, "title": title, "snippet": snippet, "score": score}
    h.update({k: v for k, v in extra.items() if v not in (None, "")})
    return h


def _action_items(terms):
    items = _load(DATA / "action-center.json", {}).get("items") or []
    handled = _load(DASH / "action-handled.json", {}).get("handled") or {}
    tackle = _load(DASH / "action-tackle.json", {}).get("sessions") or {}
    seen = set()
    out = []
    for it in items:
        fp = it.get("fp")
        seen.add(fp)
        h = handled.get(fp) or {}
        body = " ".join(str(it.get(k) or "") for k in ("why", "action", "owner", "priority"))
        body += " " + " ".join(it.get("refs") or []) + " " + (h.get("summary") or "")
        if _match(it.get("title", "") + " " + body, terms):
            done = h.get("act") == "resolved"
            out.append(
                _hit(
                    "action",
                    it.get("title", ""),
                    _snippet(body, terms),
                    _score(it.get("title"), body, terms),
                    route="/action/completed" if done else f"/action?item={fp}",
                    fp=fp,
                    status=h.get("act") or "open",
                    session_id=(tackle.get(fp) or {}).get("session_id"),
                )
            )
    # Completed items that have rotated out of the current synthesis keep a snapshot.
    for fp, h in handled.items():
        snap = h.get("item") if isinstance(h, dict) else None
        if fp in seen or not isinstance(snap, dict):
            continue
        body = (
            " ".join(str(snap.get(k) or "") for k in ("why", "action", "owner"))
            + " "
            + (h.get("summary") or "")
        )
        if _match(snap.get("title", "") + " " + body, terms):
            out.append(
                _hit(
                    "action",
                    snap.get("title", ""),
                    _snippet(body, terms),
                    _score(snap.get("title"), body, terms),
                    route="/action/completed",
                    fp=fp,
                    status=h.get("act"),
                    session_id=h.get("session_id"),
                )
            )
    return out


def _one_on_ones(terms):
    out = []
    topics = _load(DASH / "one-on-one-topics.json", {}).get("topics") or {}
    for t in topics.values():
        msgs = " ".join(
            str(m.get("text") or m.get("body") or "") for m in (t.get("messages") or [])
        )
        body = f"{t.get('person', '')} {t.get('kind', '')} {msgs}"
        if _match(t.get("title", "") + " " + body, terms):
            out.append(
                _hit(
                    "one-on-one",
                    t.get("title", ""),
                    _snippet(msgs or body, terms),
                    _score(t.get("title"), body, terms),
                    route="/people?p=" + (t.get("person") or ""),
                    person=t.get("person"),
                    at=t.get("last_at"),
                )
            )
    return out


def _files(terms):
    out = []
    seen = set()
    for base, label, recurse in _dirs():
        if not base.exists():
            continue
        files = base.rglob("*") if recurse else base.glob("*")
        for f in files:
            if not f.is_file() or f.suffix.lower() not in TEXT_EXT or f in seen:
                continue
            seen.add(f)
            try:
                if f.stat().st_size > MAX_FILE_BYTES:
                    continue
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not _match(f.name + " " + text, terms):
                continue
            lines = [ln for ln in text.splitlines() if any(t in ln.lower() for t in terms)]
            out.append(
                _hit(
                    "file",
                    f.name,
                    _snippet(" | ".join(lines[:4]) or text, terms, 240),
                    _score(f.name, text, terms),
                    path=str(f),
                    group=label,
                    lines=len(lines),
                )
            )
    return out


def _fts_query(terms):
    return " AND ".join('"' + t.replace('"', '""') + '"' for t in terms)


def _runtime_sessions(terms):
    out = []
    if not RUNTIME_DB.exists():
        return out
    try:
        con = sqlite3.connect(f"file:{RUNTIME_DB}?mode=ro", uri=True, timeout=3)
    except sqlite3.Error:
        return out
    try:
        con.row_factory = sqlite3.Row
        best = {}
        like = [f"%{t}%" for t in terms]
        where = " AND ".join("lower(coalesce(title,'')) LIKE ?" for _ in terms)
        for r in con.execute(
            f"SELECT id, title, archived, started_at, last_activity_at, source FROM sessions "
            f"WHERE {where} ORDER BY started_at DESC LIMIT 40",
            like,
        ):
            best[r["id"]] = _hit(
                "session",
                r["title"] or r["id"],
                "Title match",
                30 + _score(r["title"], "", terms),
                session_id=r["id"],
                archived=bool(r["archived"]),
                at=r["last_activity_at"] or r["started_at"],
                source=r["source"],
            )
        # Word FTS first (precise: "EWS" will not match "reviews"); trigram
        # only as a fallback for odd substrings the word tokenizer splits.
        rows = []
        for table in ("messages_fts", "messages_fts_trigram"):
            if table.endswith("trigram") and not all(len(t) >= 3 for t in terms):
                continue
            sql = (
                f"SELECT m.session_id AS sid, s.title AS title, s.archived AS archived, s.started_at AS started, "
                f"s.last_activity_at AS last, s.source AS source, substr(m.content, 1, 20000) AS body "
                f"FROM {table} f JOIN messages m ON m.id = f.rowid JOIN sessions s ON s.id = m.session_id "
                f"WHERE {table} MATCH ? AND m.role IN ('user','assistant') ORDER BY f.rowid DESC LIMIT 600"
            )
            try:
                rows = con.execute(sql, (_fts_query(terms),)).fetchall()
            except sqlite3.Error:
                rows = []
            if rows:
                break
        counts = {}
        first = {}
        for r in rows:  # newest first, so the first row per session is its latest mention
            counts[r["sid"]] = counts.get(r["sid"], 0) + 1
            first.setdefault(r["sid"], r)
        for sid, r in first.items():
            prev = best.get(sid)
            n = counts[sid]
            best[sid] = _hit(
                "session",
                r["title"] or sid,
                _snippet(r["body"] or "", terms),
                (prev["score"] if prev else 0) + min(n, 20),
                session_id=sid,
                archived=bool(r["archived"]),
                at=r["last"] or r["started"],
                source=r["source"],
                matches=n,
            )
        out = list(best.values())
    finally:
        con.close()
    return out


SOURCES = {
    "action": _action_items,
    "one-on-one": _one_on_ones,
    "file": _files,
    "session": _runtime_sessions,
}


def search(q, limit=PER_GROUP):
    terms = _lower_terms(q or "")
    if not terms or max(len(t) for t in terms) < 2:
        return {"q": q, "terms": terms, "groups": {}, "total": 0}
    groups = {}
    errors = {}
    for name, fn in SOURCES.items():
        try:
            hits = fn(terms)
        except Exception as e:  # one broken source must not sink the whole search
            errors[name] = f"{type(e).__name__}: {e}"
            continue
        for h in hits:
            groups.setdefault(h["kind"], []).append(h)
    total = 0
    for k in groups:
        groups[k].sort(key=lambda h: (h["score"], str(h.get("at") or "")), reverse=True)
        total += len(groups[k])
        groups[k] = groups[k][:limit]
    return {"q": q, "terms": terms, "groups": groups, "total": total, "errors": errors}


def tracker_query(q):
    terms = _terms(q or "")
    keys = [t.upper() for t in terms if re.fullmatch(r"[A-Za-z][A-Za-z0-9]+-\d+", t)]
    text = " ".join(t for t in terms if t.upper() not in keys).replace('"', "")
    parts = []
    if keys:
        parts.append("key in (" + ",".join(keys) + ")")
    if text:
        parts.append(f'text ~ "{text}"')
    if not parts:
        return None
    return "(" + " OR ".join(parts) + ") ORDER BY updated DESC"


if __name__ == "__main__":
    import sys

    print(json.dumps(search(" ".join(sys.argv[1:])), indent=1)[:4000])
