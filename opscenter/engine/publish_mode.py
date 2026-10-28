"""
publish_mode.py
Purpose:
  Per-class publish mode for Knowledge proposals (opscenter/DESIGN.md section 12.3, item 21). One class exists
  today:

    changelog_append  An append to an existing changelog page (title matches the title pattern) inside an
                      allowed docs root. The page body may only gain lines, never lose or change one.

  Each class is "staged" (default, waits for a batch approval) or "auto" (the applier publishes it without one
  and logs the page version before and after, with a revert link). The owner flips a class in the Knowledge
  page; the ops center never does. Every other proposal stays staged, there is no class for it.

  Config lives in knowledge-curation-config.json under "class_modes". The top level "mode" key is not touched.
  All reads fail closed to "staged". The write takes an exclusive flock and replaces the file atomically.

  Shared by the applier and the server. Standard library only (3.9 floor).
Parameters (environment, or local/params.json `docs`):
  KC_DASH           the dashboard folder holding the config (default <state>/dashboard)
  DOCS_HOST         the docs home base URL, for version and history links [docs.host]
  PM_TITLE_PATTERN  regex a changelog page title must match, default (?i)\bchangelog$ [docs.changelog_title]
  DOCS_DIGEST_TZ    the zone the daily digest groups days in, default UTC [docs.digest_tz]
"""

from __future__ import annotations

import datetime as dt
import difflib
import fcntl
import html as _html
import json
import os
import re

DASH = os.environ.get("KC_DASH") or os.path.join(
    os.environ.get("OPSCENTER_STATE_DIR") or os.path.expanduser("~/.opscenter/state"), "dashboard"
)
CONFIG = os.path.join(DASH, "knowledge-curation-config.json")
CONFIG_LOCK = os.path.join(DASH, ".knowledge-curation-config.lock")
WIKI_HOST = os.environ.get("DOCS_HOST", "https://docs.example.invalid/wiki")
TITLE_PATTERN = re.compile(os.environ.get("PM_TITLE_PATTERN", r"(?i)\bchangelog$"))
DIGEST_TZ = os.environ.get("DOCS_DIGEST_TZ", "UTC")

MODES = ("staged", "auto")
DEFAULT_MODE = "staged"

CLASSES = {
    "changelog_append": {
        "label": "Changelog appends",
        "what_auto_does": (
            "In auto, an append to a changelog page inside an allowed docs root "
            "publishes without waiting for a batch approval. Each one is logged with the page version before "
            "and after, and listed in the daily digest below with a link to the prior version. "
            "Everything else stays staged."
        ),
    }
}


def _dash_paths(config_path=None, lock_path=None):
    return config_path or CONFIG, lock_path or CONFIG_LOCK


def read_config(config_path=None):
    """The config dict, or {} when missing or unreadable (callers then see staged)."""
    path, _ = _dash_paths(config_path)
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def class_modes(config_path=None):
    """Map class id -> mode for every known class. Unknown or invalid values read as staged."""
    raw = read_config(config_path).get("class_modes")
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for cls in CLASSES:
        val = raw.get(cls)
        out[cls] = val if val in MODES else DEFAULT_MODE
    return out


def class_mode(cls, config_path=None):
    return class_modes(config_path).get(cls, DEFAULT_MODE)


def set_class_mode(cls, mode, config_path=None, lock_path=None, who="ops-center"):
    """Set one class mode. Raises KeyError for an unknown class and ValueError for a bad mode.
    Preserves every other key (including the top level mode). Returns the new class_modes map."""
    if cls not in CLASSES:
        raise KeyError(cls)
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    path, lock = _dash_paths(config_path, lock_path)
    with open(lock, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        cfg = read_config(path)
        # An unreadable existing file must never be replaced by a near-empty one.
        if not cfg and os.path.exists(path) and os.path.getsize(path) > 0:
            raise ValueError("config unreadable, refusing to overwrite")
        modes = cfg.get("class_modes") if isinstance(cfg.get("class_modes"), dict) else {}
        modes = dict(modes)
        modes[cls] = mode
        cfg["class_modes"] = modes
        cfg.setdefault("mode", "staged")
        cfg["class_modes_updated_utc"] = dt.datetime.now(dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        cfg["class_modes_updated_by"] = who
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    return class_modes(path)


def text_lines(h):
    """Block-level text lines of docs home HTML (same normalisation the doc builders diff with)."""
    h = re.sub(r"\s+", " ", h or "")
    h = re.sub(
        r"(?is)(<t[hd][^>]*>)(.*?)(</t[hd]>)",
        lambda m: m.group(1) + re.sub(r"(?i)</?p[^>]*>", " ", m.group(2)) + m.group(3),
        h,
    )
    h = re.sub(
        r"(?i)</(p|tr|li|h[1-6]|pre|th|td)>|<br\s*/?>",
        lambda m: "\n" if (m.group(1) or "").lower() not in ("th", "td") else " | ",
        h,
    )
    t = _html.unescape(re.sub(r"<[^>]+>", "", h))
    return [re.sub(r"\s+", " ", ln).strip() for ln in t.splitlines() if ln.strip()]


def is_append_only(live_html, new_body):
    """(ok, reason). True only when the new body adds lines to the live page and removes or
    rewrites none. Compared as block text, so the docs home's HTML reformatting does not matter."""
    old, new = text_lines(live_html), text_lines(new_body)
    if not old:
        return False, "live page has no text"
    added = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, old, new, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            added += j2 - j1
            continue
        return False, f"{tag} of {i2 - i1} existing line(s), not an append"
    if added == 0:
        return False, "no added lines"
    return True, f"{added} line(s) added"


def classify(prop):
    """The class id for a staged proposal, or None. Cheap checks on the staged record only.
    The applier re-checks against the live page before it publishes (is_append_only)."""
    if not isinstance(prop, dict):
        return None
    if prop.get("kind", "update") != "update" or not prop.get("target_id"):
        return None
    if prop.get("new_parent_id") or prop.get("approve_after"):
        return None  # a move, or a page that waits on something else
    if prop.get("scope_verdict") not in (None, "", "ALLOW"):
        return None
    title = str(prop.get("target_title") or "").strip()
    if not TITLE_PATTERN.search(title):
        return None
    return "changelog_append"


def version_number(page):
    """Page version number from a docs home page read result, or None."""
    v = page.get("version") if isinstance(page, dict) else None
    if isinstance(v, dict):
        v = v.get("number")
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def version_url(page_id, version):
    return f"{WIKI_HOST}/pages/viewpage.action?pageId={page_id}&pageVersion={version}"


def history_url(page_id):
    return f"{WIKI_HOST}/pages/viewpreviousversions.action?pageId={page_id}"


def digest(rows, tz_name=None, days=14):
    """Group auto-published rows (newest day first) for the Knowledge page digest."""
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name or DIGEST_TZ)
    except Exception:  # noqa: BLE001 - no tzdata, fall back to UTC days
        tz = dt.timezone.utc
    by_day = {}
    for r in rows:
        if not r.get("auto") or r.get("result") != "published":
            continue
        try:
            when = dt.datetime.strptime(r["when"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=dt.timezone.utc
            )
        except (KeyError, ValueError, TypeError):
            continue
        day = when.astimezone(tz).strftime("%Y-%m-%d")
        by_day.setdefault(day, []).append(
            {
                "fp": r.get("fp"),
                "title": r.get("title", ""),
                "page_id": r.get("page_id"),
                "when": r.get("when"),
                "class": r.get("class", ""),
                "version_before": r.get("version_before"),
                "version_after": r.get("version_after"),
                "revert_url": r.get("revert_url", ""),
                "history_url": r.get("history_url", ""),
            }
        )
    out = []
    for day in sorted(by_day, reverse=True)[:days]:
        out.append(
            {
                "date": day,
                "count": len(by_day[day]),
                "items": sorted(by_day[day], key=lambda x: x["when"]),
            }
        )
    return out


def state(config_path=None, applied_rows=None):
    """The payload the Knowledge page renders: classes with mode, and the digest."""
    modes = class_modes(config_path)
    return {
        "classes": [
            {
                "id": cid,
                "label": c["label"],
                "mode": modes[cid],
                "what_auto_does": c["what_auto_does"],
            }
            for cid, c in CLASSES.items()
        ],
        "digest": digest(applied_rows or []),
        "updated_utc": read_config(config_path).get("class_modes_updated_utc", ""),
    }
