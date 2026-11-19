"""Knowledge curation for the Knowledge page: staged proposals, the applied log and the publish mode per class.

Reads what the nightly knowledge job and the guarded applier write, under <state>/dashboard:
  docs-proposals.json         {"proposals": [...]} staged proposals, one body file each in proposals/<fp>.body
  approve-applied.jsonl       one outcome per line {fp, result, page_id?, title?, when?, body_sha?, version_before?, version_after?}
  proposal-feedback.json      {"feedback": {fp: {reason, at, status, response?}}} notes sent back for a rewrite
  knowledge-curation-config.json   class_modes, owned by engine/publish_mode.py

Writes only the publish mode (engine/publish_mode.set_class_mode, under its own lock). Approve, reject and send back go through
server/stores.py (POST /api/approve), which the applier reads. A proposal the applier already recorded for the same content is
not shown again (engine/applied_log.is_finished), so a decision never reappears as pending.

Every read tolerates a missing or unreadable file and answers an empty board, never an error, because a consumer that has not
run the knowledge job yet has none of these files.
"""

import html
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# engine/ is on the path when routes.py loads this module, but not when a test loads it alone.
ENGINE = str(HERE.parent.parent / "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

import applied_log  # noqa: E402
import paths  # noqa: E402
import publish_mode  # noqa: E402

PREVIEW_MAX = 200_000


def _dash():
    return paths.dashboard_dir()


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _applied_rows():
    """Every outcome line, oldest first. Unreadable lines are skipped, as applied_log.load_index does."""
    rows = []
    try:
        with open(_dash() / "approve-applied.jsonl", encoding="utf-8") as fh:
            for ln in fh:
                try:
                    row = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("fp"):
                    rows.append(row)
    except OSError:
        pass
    return rows


def _feedback():
    fb = _load(_dash() / "proposal-feedback.json", {})
    out = fb.get("feedback") if isinstance(fb, dict) else None
    return out if isinstance(out, dict) else {}


def applied():
    """GET /api/applied: the outcome of every decision the applier has recorded."""
    return {"applied": _applied_rows()}


def curation():
    """GET /api/curation: staged proposals still waiting on a decision, each with its pending send-back note."""
    store = _load(_dash() / "docs-proposals.json", {})
    props = store.get("proposals") if isinstance(store, dict) else None
    props = props if isinstance(props, list) else []
    idx = applied_log.load_index(str(_dash() / "approve-applied.jsonl"))
    fb = _feedback()
    out = []
    for p in props:
        if not isinstance(p, dict) or not p.get("fp"):
            continue
        fp = p["fp"]
        if applied_log.is_finished(idx, fp, p.get("body_sha"), applied_log.staged_utc(p)):
            continue
        row = dict(p)
        note = fb.get(fp)
        if isinstance(note, dict):
            row["feedback"] = {
                "reason": str(note.get("reason") or ""),
                "at": str(note.get("at") or ""),
                "status": str(note.get("status") or "open"),
                "response": str(note.get("response") or ""),
                "pending": note.get("status") in (None, "open", "working"),
            }
        out.append(row)
    cfg = publish_mode.read_config()
    return {
        "mode": str(cfg.get("mode") or publish_mode.DEFAULT_MODE),
        "generated_utc": str(store.get("generated_utc") or "") if isinstance(store, dict) else "",
        "note": str(store.get("note") or "") if isinstance(store, dict) else "",
        "proposals": out,
    }


# A staged body is model written HTML. It opens in its own tab on the app's origin, so it carries a policy that runs no script,
# loads nothing and cannot be framed, and it is shown as a page the reader reviews, never as part of the app.
PREVIEW_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}


def preview(fp):
    """GET /api/curation/preview/<fp>: the staged body as an HTML page for a new tab. KeyError for an unknown fp."""
    fp = str(fp or "")
    if not fp or "/" in fp or "\\" in fp or fp.startswith("."):
        raise KeyError("no such proposal")
    try:
        body = (_dash() / "proposals" / (fp + ".body")).read_text(encoding="utf-8")[:PREVIEW_MAX]
    except OSError:
        raise KeyError("no such proposal") from None
    page = (
        '<!doctype html><meta charset="utf-8"><title>Proposal preview</title>'
        "<style>body{font:15px/1.5 system-ui,sans-serif;max-width:56rem;margin:2rem auto;padding:0 1rem}"
        "table{border-collapse:collapse}td,th{border:1px solid #8886;padding:.25rem .5rem}</style>"
        f"<p><small>Preview of {html.escape(fp)}. Nothing here runs.</small></p>" + body
    )
    return 200, page.encode("utf-8"), "text/html; charset=utf-8", PREVIEW_HEADERS


def publish_modes():
    """GET /api/knowledge/publish-modes: each class with its mode, and the digest of what auto published."""
    return publish_mode.state(applied_rows=_applied_rows())


def set_publish_mode(payload):
    """POST /api/knowledge/publish-mode {class, mode}. ValueError for a bad mode, KeyError for an unknown class."""
    payload = payload if isinstance(payload, dict) else {}
    try:
        publish_mode.set_class_mode(
            str(payload.get("class") or ""),
            str(payload.get("mode") or ""),
            who=os.environ.get("OPSCENTER_USER") or "ops-center",
        )
    except KeyError:
        raise KeyError("no such class") from None
    return publish_modes()
