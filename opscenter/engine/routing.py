#!/usr/bin/env python3
"""
routing.py - routing engine for the Action Center collector.

Purpose: Decide where each candidate (an inbound ask, a ticket, an audit finding) or each
         synthesized item belongs, from DATA in ac-routing.json instead of prose rules in
         the analysis prompt or regexes in board_build.py. A click on the board ("Route
         elsewhere") appends a rule here, so a routing call never needs a code or prompt edit.
Date:    2026-10-14

Routes:
  action_center  must be considered: the analysis emits an item or records why it dropped it
  analysis       context only: the analysis may fold it into an item
  elsewhere      owned by another surface or person, never on the board ("where" says which)
  nowhere        dropped

Matching (all present fields must match, case-insensitive):
  source       fnmatch glob on the candidate source id (mail.direct, teams.1on1, doc.gap, ...)
  actor        exact person name                 actor_role  me|report|partner|leader|other|automation
  key          exact item key                    key_prefix  item key prefix (oo-, doc-, ...)
  ref_prefix   first-ref prefix (for example ABC-123)
  refs         any of these refs                 owner       exact owner name
  text         regex searched in the fields named by "fields" (default key, title, action)
  sources_any  any of these item source labels

Rule "scope" (optional): items (synthesized board items only), candidates (collected inputs
only) or all (default).

Rules are evaluated in order. Click rules are inserted at the top, so a newer call wins.
Disabled rules are skipped. The first match wins. No match falls to the defaults block.

Stdlib only, Python 3.9 floor (the gate and the refresh run on the system python).
"""

from __future__ import annotations

import datetime as dt
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("OPSCENTER_ROOT") or Path.home() / ".opscenter")
STATE = Path(os.environ.get("OPSCENTER_STATE_DIR") or ROOT / "state")
RULES_PATH = Path(os.environ.get("AC_ROUTING_PATH") or STATE / "dashboard" / "ac-routing.json")
LOCK_PATH = RULES_PATH.parent / ".ac-routing.lock"
ROUTES = ("action_center", "analysis", "elsewhere", "nowhere")
MATCH_KEYS = (
    "source",
    "actor",
    "actor_role",
    "key",
    "key_prefix",
    "ref_prefix",
    "refs",
    "owner",
    "text",
    "fields",
    "sources_any",
)
DEFAULT_FIELDS = ("key", "title", "action")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,80}$")
SCOPES = ("all", "items", "candidates")


class RoutingError(ValueError):
    pass


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path: Path | None = None) -> dict:
    """Read the routing file. Raises RoutingError when it is missing or malformed, so a
    caller can fail closed (keep the item visible) instead of routing on a partial file."""
    p = Path(path or RULES_PATH)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RoutingError("routing file missing: %s" % p)  # noqa: B904, UP031
    except ValueError as exc:
        raise RoutingError("routing file is not JSON: %s" % exc)  # noqa: B904, UP031
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise RoutingError("routing file has no rules list")
    for r in data["rules"]:
        validate_rule(r)
    return data


def validate_rule(r: dict) -> None:
    if not isinstance(r, dict):
        raise RoutingError("rule is not an object")
    if not ID_RE.match(str(r.get("id", ""))):
        raise RoutingError("rule id must be lowercase letters, digits and dashes: %r" % r.get("id"))  # noqa: UP031
    if r.get("route") not in ROUTES:
        raise RoutingError("rule %s: route must be one of %s" % (r.get("id"), ", ".join(ROUTES)))  # noqa: UP031
    m = r.get("match")
    if not isinstance(m, dict) or not m:
        raise RoutingError("rule %s: match must be a non-empty object" % r.get("id"))  # noqa: UP031
    unknown = set(m) - set(MATCH_KEYS)
    if unknown:
        raise RoutingError("rule %s: unknown match keys %s" % (r.get("id"), sorted(unknown)))  # noqa: UP031
    if set(m) <= {"fields"}:
        raise RoutingError("rule %s: match needs a condition besides fields" % r.get("id"))  # noqa: UP031
    if "text" in m:
        try:
            re.compile(m["text"])
        except re.error as exc:
            raise RoutingError("rule %s: bad text regex: %s" % (r.get("id"), exc))  # noqa: B904, UP031
    if r.get("scope", "all") not in SCOPES:
        raise RoutingError("rule %s: scope must be one of %s" % (r.get("id"), ", ".join(SCOPES)))  # noqa: UP031
    if r["route"] == "elsewhere" and not str(r.get("where", "")).strip():
        raise RoutingError("rule %s: route elsewhere needs a where" % r.get("id"))  # noqa: UP031


def _lc(v) -> str:
    return str(v or "").strip().lower()


def matches(match: dict, obj: dict) -> bool:
    """obj is a candidate or an item. Both shapes share key, title, action, refs, sources,
    owner. Candidates add source, actor, actor_role, text."""
    if "source" in match and not fnmatch.fnmatch(_lc(obj.get("source")), _lc(match["source"])):
        return False
    if "actor" in match and _lc(obj.get("actor")) != _lc(match["actor"]):
        return False
    if "actor_role" in match and _lc(obj.get("actor_role")) != _lc(match["actor_role"]):
        return False
    if "owner" in match and _lc(obj.get("owner")) != _lc(match["owner"]):
        return False
    if "key" in match and _lc(obj.get("key")) != _lc(match["key"]):
        return False
    if "key_prefix" in match and not _lc(obj.get("key")).startswith(_lc(match["key_prefix"])):
        return False
    refs = [_lc(r) for r in (obj.get("refs") or []) if r]
    if "ref_prefix" in match and not (refs and refs[0].startswith(_lc(match["ref_prefix"]))):
        return False
    if "refs" in match and not ({_lc(r) for r in match["refs"]} & set(refs)):
        return False
    if "sources_any" in match:
        have = {_lc(s) for s in (obj.get("sources") or [])}
        if not ({_lc(s) for s in match["sources_any"]} & have):
            return False
    if "text" in match:
        fields = match.get("fields") or DEFAULT_FIELDS
        hay = " ".join(str(obj.get(f) or "") for f in fields)
        if not re.search(match["text"], hay, re.I):
            return False
    return True


def route(obj: dict, data: dict, kind: str = "candidate") -> dict:
    """Return {"route", "rule", "where", "reason"} for one candidate or item (kind)."""
    for r in data.get("rules", []):
        if r.get("disabled"):
            continue
        scope = r.get("scope", "all")
        if (scope == "items" and kind != "item") or (scope == "candidates" and kind != "candidate"):
            continue
        if matches(r["match"], obj):
            return {
                "route": r["route"],
                "rule": r["id"],
                "where": r.get("where", ""),
                "reason": r.get("reason", ""),
            }
    d = data.get("defaults") or {}
    role = _lc(obj.get("actor_role"))
    addressed = _lc(obj.get("addressed"))
    # Fail open: a person (not an automation, not me) who addressed me directly is always
    # considered, even when no rule names this kind of message yet.
    if addressed in ("direct", "mention", "team") and role not in ("me", "automation"):
        return {
            "route": d.get("person_addressed", "action_center"),
            "rule": "default:person",
            "where": "",
            "reason": "",
        }
    return {"route": d.get("other", "analysis"), "rule": "default:other", "where": "", "reason": ""}


def filter_items(items: list, data: dict) -> tuple:
    """Split synthesized items into (kept, routed_away). An item survives only when its route
    is action_center or analysis. routed_away rows carry the rule that moved them."""
    kept, away = [], []
    for it in items:
        r = route(it, data, kind="item")
        if r["route"] in ("action_center", "analysis"):
            kept.append(it)
        else:
            away.append({"key": it.get("key"), "title": it.get("title"), **r})
    return kept, away


def _save(data: dict) -> None:
    RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(RULES_PATH.parent), prefix=".ac-routing.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, RULES_PATH)


def rule_id_for(match: dict, route_name: str, scope: str = "all") -> str:
    basis = json.dumps({"m": match, "r": route_name, "s": scope}, sort_keys=True)
    return "click-" + hashlib.sha1(basis.encode()).hexdigest()[:10]


def add_rule(
    match: dict,
    route_name: str,
    where: str = "",
    reason: str = "",
    origin: str = "click",
    from_item: str = "",
    scope: str = "all",
) -> dict:
    """Insert a rule at the top (newest wins). Idempotent: the same match and route returns
    the existing rule with already=True and re-enables it."""
    rule = {
        "id": rule_id_for(match, route_name, scope),
        "match": match,
        "route": route_name,
        "where": where.strip(),
        "reason": reason.strip(),
        "origin": origin,
        "created": now_utc(),
    }
    if scope != "all":
        rule["scope"] = scope
    if from_item:
        rule["from_item"] = from_item
    validate_rule(rule)
    with open(LOCK_PATH, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        data = load()
        for r in data["rules"]:
            if r["id"] == rule["id"]:
                was = bool(r.get("disabled"))
                r.pop("disabled", None)
                _save(data)
                return dict(r, already=not was)
        data["rules"].insert(0, rule)
        _save(data)
    return dict(rule, already=False)


def set_disabled(rule_id: str, disabled: bool) -> dict:
    with open(LOCK_PATH, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        data = load()
        for r in data["rules"]:
            if r["id"] == rule_id:
                if disabled:
                    r["disabled"] = now_utc()
                else:
                    r.pop("disabled", None)
                _save(data)
                return r
    raise KeyError(rule_id)


def delete_rule(rule_id: str) -> bool:
    """Click rules can be deleted. Seed rules can only be disabled, so the migration record
    of each former prose rule stays readable."""
    with open(LOCK_PATH, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        data = load()
        for i, r in enumerate(data["rules"]):
            if r["id"] == rule_id:
                if r.get("origin") != "click":
                    raise RoutingError("seed rule %s can be disabled, not deleted" % rule_id)  # noqa: UP031
                del data["rules"][i]
                _save(data)
                return True
    return False


def preview(match: dict, route_name: str, candidates: list, items: list) -> dict:
    """What a proposed rule would catch among recent candidates and current items, and which
    of them currently route somewhere else (the rule would change their route)."""
    validate_rule({"id": "preview-rule", "match": match, "route": route_name, "where": "preview"})
    hit_c = [c for c in candidates if matches(match, c)]
    hit_i = [i for i in items if matches(match, i)]
    return {
        "candidates": [
            {
                "cid": c.get("cid"),
                "source": c.get("source"),
                "actor": c.get("actor"),
                "title": c.get("title"),
            }
            for c in hit_c[:50]
        ],
        "candidate_count": len(hit_c),
        "items": [{"key": i.get("key"), "title": i.get("title")} for i in hit_i[:50]],
        "item_count": len(hit_i),
    }
