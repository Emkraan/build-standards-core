"""Documentation coverage for the Knowledge page: the registry joined with the latest audit, plus the owner's Snooze and Ignore per thing.

doc-inventory.json (the registry) and doc-gaps.json (the audit's store, `engine/doc_audit.py`) are read only. Snooze and Ignore persist in
`<state>/dashboard/doc-handled.json`. Ignore holds for the current audit generation only: a new gap bumps the generation (a new key) and the
thing is open again. open_count feeds the Knowledge nav badge: high or medium things that are on the board, not snoozed and not ignored, plus one
per duplicate page set. Tackle goes through the runtime slot (server/runtime_slot.py); `tackle_item` builds its item from the registry and the audit.
"""

import datetime as dt
import json
import os
from pathlib import Path

import paths

SNOOZE_DAYS = 7
OPEN_PRIORITIES = ("high", "medium")
RANK = {"high": 0, "medium": 1, "low": 2}


def _dash():
    return paths.dashboard_dir()


def _handled_path():
    return Path(os.environ.get("DOC_COVERAGE_HANDLED") or _dash() / "doc-handled.json")


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_handled():
    d = _load(_handled_path(), {})
    h = d.get("handled") if isinstance(d, dict) else None
    return h if isinstance(h, dict) else {}


def handled_state(h, key):
    """The handled entry when it still applies to the thing's current gaps, else None."""
    if not h:
        return None
    if h.get("act") == "snoozed":
        try:
            until = dt.datetime.strptime(h.get("until", ""), "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=dt.timezone.utc
            )
        except ValueError:
            return None
        return h if until > _now() else None
    if h.get("act") == "ignored":
        return h if key and h.get("key") == key else None
    return None


def handle(thing_id, act):
    """Snooze (7 days), ignore (this generation) or restore."""
    if act not in ("snooze", "ignore", "restore"):
        raise ValueError("act must be snooze, ignore or restore")
    reg = _load(_dash() / "doc-inventory.json", {})
    if thing_id not in {t.get("id") for t in reg.get("things", [])}:
        raise KeyError(thing_id)
    key = ((_load(_dash() / "doc-gaps.json", {}).get("things") or {}).get(thing_id) or {}).get(
        "key"
    )
    handled = _load_handled()
    now = _now()
    if act == "restore":
        handled.pop(thing_id, None)
    elif act == "snooze":
        handled[thing_id] = {
            "act": "snoozed",
            "at": _iso(now),
            "until": _iso(now + dt.timedelta(days=SNOOZE_DAYS)),
            "key": key,
        }
    else:
        handled[thing_id] = {"act": "ignored", "at": _iso(now), "key": key}
    path = _handled_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"handled": handled}, indent=2), encoding="utf-8")
    tmp.replace(path)
    return {"id": thing_id, "handled": handled.get(thing_id)}


def get(tackles=None):
    """The page payload. `tackles` is the runtime slot's session map (key doc-<id>), shown per thing."""
    tackles = tackles or {}
    reg = _load(_dash() / "doc-inventory.json", {})
    store = _load(_dash() / "doc-gaps.json", {})
    store = store if isinstance(store, dict) else {}
    audited = store.get("things", {})
    surfaced = set(store.get("surface", []))
    doc_handled = _load_handled()
    rows = []
    for t in reg.get("things", []) if isinstance(reg, dict) else []:
        a = audited.get(t.get("id"), {})
        h = handled_state(doc_handled.get(t.get("id")), a.get("key"))
        on_board = t.get("action_center") is not False
        rows.append(
            {
                "id": t.get("id"),
                "name": t.get("name"),
                "kind": t.get("kind"),
                "tier": t.get("tier"),
                "status": t.get("status"),
                "raci_domain": t.get("raci_domain"),
                "owner_a": a.get("owner_a"),
                "owner_r": a.get("owner_r"),
                "repo": t.get("repo"),
                "path": t.get("path"),
                "confluence_home": t.get("confluence_home"),
                "home_title": a.get("home_title"),
                "release": t.get("release"),
                "changelog_file": t.get("changelog_file"),
                "on_board": on_board,
                "board_note": t.get("action_center_note"),
                "surfaced": t.get("id") in surfaced,
                "key": a.get("key"),
                "priority": a.get("priority", "none"),
                "gaps": a.get("gaps", []),
                "closed": a.get("closed", [])[-5:],
                "handled": h,
                "tackle": tackles.get(f"doc-{t.get('id')}"),
                "open": bool(on_board and a.get("priority") in OPEN_PRIORITIES and not h),
            }
        )
    internal = [
        {"id": k, "name": v.get("name"), "gaps": v.get("gaps", [])}
        for k, v in audited.items()
        if k.startswith("_") and k != "_duplicates"
    ]
    # Duplicate page sets are a real defect on the record: shown on their own and counted in the badge, one per set.
    duplicates = (audited.get("_duplicates") or {}).get("gaps", [])
    return {
        "audited_utc": store.get("generated_utc"),
        "last_error": store.get("last_error"),
        "counts": store.get("counts", {}),
        "open_count": sum(1 for r in rows if r["open"]) + len(duplicates),
        "things": rows,
        "internal": internal,
        "duplicates": duplicates,
    }


def badge():
    return get()["open_count"]


def tackle_item(thing_id, wiki_url=""):
    """The item the runtime slot starts a session for. Raises KeyError (unknown thing), PermissionError (kept off the board) or
    ValueError (no open gaps)."""
    t = next((x for x in get()["things"] if x["id"] == thing_id), None)
    if t is None:
        raise KeyError(thing_id)
    if not t["on_board"]:
        raise PermissionError(t.get("board_note") or f"{t['name']} is kept off the board")
    if not t["gaps"]:
        raise ValueError(f"{t['name']} has no open documentation gaps")
    gaps = sorted(t["gaps"], key=lambda g: RANK.get(g.get("severity"), 3))
    home = (
        f"{t.get('home_title') or ''} {wiki_url}{t['confluence_home']}".strip()
        if t.get("confluence_home")
        else "none yet"
    )
    lines = [
        f"Thing: {t['name']} (registry id {t['id']}, tier {t.get('tier') or '?'}, {t.get('status') or '?'})",
        f"Source: {t.get('repo') or '?'}/{t.get('path') or ''}",
        f"Owner (R / A): {t.get('owner_r') or '?'} / {t.get('owner_a') or '?'} (domain: {t.get('raci_domain') or '?'})",
        f"Docs home: {home}",
        f"Audit key: {t.get('key') or '(none)'} (priority {t['priority']})",
        "Open gaps, worst first:",
        *[f"- [{g.get('severity')}] {g.get('text')} ({g.get('rule')})" for g in gaps],
    ]
    return {
        "title": f"Document {t['name']}",
        "summary": "\n".join(lines),
        "priority": t["priority"] if t["priority"] in RANK else "low",
        "owner": t.get("owner_r") or "",
        "refs": [f"doc-{t['id']}"],
    }
