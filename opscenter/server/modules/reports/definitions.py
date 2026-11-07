"""
definitions.py
Purpose: Dashboard and report definitions are data, not code (reports module R2). A definition is a JSON object kept in a store
         (one file per kind, one record per key). A consumer ships default definitions with a `version`; `seed` rolls them out:
           - a key the store does not have is added;
           - an unedited copy is replaced when the shipped version is higher (raise the version to roll a change out);
           - an edited copy is NEVER overwritten, whatever the version;
           - an edit can be reset to the shipped copy.
         Definitions are edited in the UI, imported and exported as JSON by key, and every import is validated: a bad definition is
         refused whole, never half stored.
Date:    2026-11-07

Definition: {"key": "slug", "title": "text", "panels": [{"title": "text", "stream": "name", "measure": "name" | "spec": {...}}, ...]}
            a panel names a stream and a measure (or the full report spec, see query.py), never a store (R3). Extra fields are kept.
Store file: {"definitions": {key: {"def": {...}, "shipped_version": int | null, "edited": bool, "at": iso}}}
API:        Store(path).seed(defaults, version) -> {"added": [...], "updated": [...], "kept": [...]}
            .get(key) .list() .save(definition) (an edit) .reset(key, defaults) .delete(key)
            .export(key) -> JSON text   .import_(text) -> key (validated)   validate(definition) -> list of problems
One writer under a lock with an atomic replace. Pure Python, no import side effect.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import re
from pathlib import Path

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_PANELS = 50
PANEL_TYPES = ("stat", "line", "area", "bar", "hbar", "donut", "table")


def validate(definition):
    """The problems with a definition, [] when it is fine."""
    out = []
    if not isinstance(definition, dict):
        return ["a definition must be a JSON object"]
    key = definition.get("key")
    if not isinstance(key, str) or not KEY_RE.match(key):
        out.append("key must be a lowercase slug (letters, digits, dash, underscore)")
    if not isinstance(definition.get("title"), str) or not definition["title"].strip():
        out.append("title must be a non-empty string")
    panels = definition.get("panels")
    if not isinstance(panels, list):
        out.append("panels must be a list")
        return out
    if len(panels) > MAX_PANELS:
        out.append(f"at most {MAX_PANELS} panels")
    for i, p in enumerate(panels):
        if not isinstance(p, dict):
            out.append(f"panel {i + 1} must be an object")
            continue
        for f in ("title", "stream"):
            if not isinstance(p.get(f), str) or not p[f].strip():
                out.append(f"panel {i + 1}: {f} must be a non-empty string")
        if p.get("type") is not None and p["type"] not in PANEL_TYPES:
            out.append(f"panel {i + 1}: type must be one of {', '.join(PANEL_TYPES)}")
        has_measure = isinstance(p.get("measure"), str) and p["measure"].strip()
        if not has_measure and not isinstance(p.get("spec"), dict):
            out.append(
                f"panel {i + 1}: a measure (a name) or a spec (the report query) is required"
            )
    return out


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, path):
        self.path = Path(path)

    def _read(self):
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"definitions": {}}
        return (
            d
            if isinstance(d, dict) and isinstance(d.get("definitions"), dict)
            else {"definitions": {}}
        )

    def _mutate(self, fn):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix(".lock"), "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            data = self._read()
            result = fn(data["definitions"])
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
            return result

    # ---- reads
    def get(self, key):
        rec = self._read()["definitions"].get(key)
        return json.loads(json.dumps(rec["def"])) if rec else None

    def list(self):
        return [
            {
                "key": k,
                "title": r["def"].get("title"),
                "edited": bool(r.get("edited")),
                "shipped_version": r.get("shipped_version"),
            }
            for k, r in sorted(self._read()["definitions"].items())
        ]

    def records(self):
        """Every record as {key: {def, edited, shipped_version, at}} (copies)."""
        return json.loads(json.dumps(self._read()["definitions"]))

    def export(self, key):
        d = self.get(key)
        if d is None:
            raise KeyError(key)
        return json.dumps(d, indent=2, sort_keys=True)

    # ---- the shipped defaults
    def seed(self, defaults, version):
        """Roll the shipped defaults out at `version`. Returns which keys were added, updated (an unedited copy at a lower version)
        and kept (an edited copy, or one already at this version or newer)."""
        for d in defaults:
            problems = validate(d)
            if problems:
                raise ValueError(
                    f"shipped definition {d.get('key') if isinstance(d, dict) else d!r}: {'; '.join(problems)}"
                )

        def go(defs):
            added, updated, kept = [], [], []
            for d in defaults:
                cur = defs.get(d["key"])
                if cur is None:
                    defs[d["key"]] = {
                        "def": d,
                        "shipped_version": version,
                        "edited": False,
                        "at": _now(),
                    }
                    added.append(d["key"])
                elif cur.get("edited") or (cur.get("shipped_version") or 0) >= version:
                    kept.append(d["key"])
                else:
                    defs[d["key"]] = {
                        "def": d,
                        "shipped_version": version,
                        "edited": False,
                        "at": _now(),
                    }
                    updated.append(d["key"])
            return {"added": added, "updated": updated, "kept": kept}

        return self._mutate(go)

    def reset(self, key, defaults):
        """Put an edited copy back to the shipped one. KeyError when there is no shipped definition with that key."""
        shipped = next((d for d in defaults if isinstance(d, dict) and d.get("key") == key), None)
        if shipped is None:
            raise KeyError(f"no shipped definition {key!r}")

        def go(defs):
            cur = defs.get(key) or {}
            defs[key] = {
                "def": shipped,
                "shipped_version": cur.get("shipped_version"),
                "edited": False,
                "at": _now(),
            }

        self._mutate(go)

    # ---- edits
    def save(self, definition):
        """Store an edit (a new definition or a changed shipped one). The record is marked edited, so a later seed never overwrites it."""
        problems = validate(definition)
        if problems:
            raise ValueError("; ".join(problems))
        key = definition["key"]

        def go(defs):
            cur = defs.get(key) or {}
            defs[key] = {
                "def": definition,
                "shipped_version": cur.get("shipped_version"),
                "edited": True,
                "at": _now(),
            }

        self._mutate(go)
        return key

    def delete(self, key):
        def go(defs):
            if key not in defs:
                raise KeyError(key)
            del defs[key]

        self._mutate(go)

    def import_(self, text):
        """Import one definition from JSON text. Validated whole: a bad one changes nothing."""
        try:
            d = json.loads(text)
        except (TypeError, ValueError) as e:
            raise ValueError(f"not JSON: {e}") from e
        return self.save(d)
