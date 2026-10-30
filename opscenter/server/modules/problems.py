"""
problems.py
Purpose: The one server-side problem list. The rail badge, the section and item tab counts and the Overview cards all read this
         list, so they cannot disagree and the client applies no threshold of its own. Every item is one thing the owner runs
         (a pipeline, the scheduled jobs, CI and backup, spend, the core approvals) with a tone: `needs_me` (red: a failed main run,
         a failing job, a failed health check, approvals waiting), `worth_a_look` (amber: runners offline, a workflow red on main in
         another repo) or `healthy`. Work in progress (a run in flight) is a `running` flag the UI draws as a spinner, never red.
         Each source is a lifted module and is guarded on its own: a module that is not in the tree or cannot be read contributes
         no item, and a check that fails shows as one needs_me item, never as clear. Nothing here names an estate.
Date:    2026-10-30

Item: {id, hub, section, item, label, tone, headline, details (at most four lines), count, running, url}
List: {items, counts: {needs_me, worth_a_look, healthy, running, total, by_section: {section: n}, by_item: {"section/item": n}}}
      where the counts of a section or item are its needs_me plus worth_a_look items.

Where an item lives is configuration: OPSCENTER_PROBLEM_MAP (a JSON file, default <state>/problem-map.json) may set
{"hub": "<default hub>", "<source key>": {"hub", "section", "item", "label"}}. The source keys are builds:<product>, jobs, ci,
spend and core. The defaults are hub "operations" and the sections builds, automation and cost.
"""

import importlib
import json
import os
from pathlib import Path

import paths

HUB = "operations"
MAX_DETAILS = 4


def _mod(name):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _map():
    f = os.environ.get("OPSCENTER_PROBLEM_MAP") or str(paths.state_dir() / "problem-map.json")
    try:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _place(key, section, item, label):
    m = _map()
    hub = str(m.get("hub") or HUB)
    o = m.get(key) if isinstance(m.get(key), dict) else {}
    return {
        "hub": str(o.get("hub") or hub),
        "section": str(o.get("section") or section),
        "item": str(o.get("item") or item),
        "label": str(o.get("label") or label),
    }


def _item(key, section, item, label, tone, headline, details=(), running=False, url=None):
    d = [str(x) for x in details][:MAX_DETAILS]
    return dict(
        _place(key, section, item, label),
        id=key,
        tone=tone,
        headline=headline,
        details=d,
        count=0 if tone == "healthy" else 1,
        running=bool(running),
        url=url,
    )


def _plural(n, what):
    return f"{n} {what}" + ("" if n == 1 else "s")


def _builds():
    """One item per product (a product may have several pipelines: it needs me while any of them failed on main)."""
    b = _mod("builds")
    if b is None or not getattr(b, "PIPELINES", None):
        return []
    feed = b.swr.peek("builds:feed") or {}
    failed = {i["key"]: i for i in b.main_failure_items(feed)}
    by = {}
    for p in feed.get("pipelines") or []:
        e = by.setdefault(
            p["product"], {"label": p["label"], "failed": [], "running": False, "url": p.get("url")}
        )
        e["running"] = e["running"] or bool((p.get("state") or {}).get("current"))
        if p["key"] in failed:
            e["failed"].append(failed[p["key"]])
    out = []
    for product, e in sorted(by.items()):
        if e["failed"]:
            f = e["failed"][0]
            lines = [
                f"{x['label']}: last run on main {x['conclusion']} (run {x['run']})"
                for x in e["failed"]
            ]
            out.append(
                _item(
                    f"builds:{product}",
                    "builds",
                    product,
                    e["label"],
                    "needs_me",
                    lines[0],
                    lines[1:] + ["A later green run on main clears it"],
                    e["running"],
                    f.get("url"),
                )
            )
        else:
            out.append(
                _item(
                    f"builds:{product}",
                    "builds",
                    product,
                    e["label"],
                    "healthy",
                    "Running" if e["running"] else "Last run on main is fine",
                    [],
                    e["running"],
                    e["url"],
                )
            )
    return out


def _infra():
    m = _mod("infra")
    if m is None or not hasattr(m, "badge_problems"):
        return []
    try:
        bp = m.badge_problems()
    except Exception as e:  # noqa: BLE001 - unknown shows as one problem, never as clear
        return [
            _item(
                "ci",
                "automation",
                "ci",
                "CI and backup",
                "needs_me",
                "Infrastructure checks failed",
                [str(e)[:200]],
            )
        ]
    areas = bp.get("areas") or {}
    looks = bp.get("looks") or {}
    if (
        not (bp.get("count") or any(looks.values()))
        and hasattr(m, "configured")
        and not m.configured()
    ):
        return []  # nothing configured: no cards, not a wall of "healthy"
    out = []
    for key, section, label, noun in (
        ("jobs", "automation", "Scheduled jobs", "scheduled job problem"),
        ("ci", "automation", "CI and backup", "CI problem"),
        ("spend", "cost", "Spend", "spend problem"),
    ):
        lines, soft = list(areas.get(key) or []), list(looks.get(key) or [])
        if lines:
            out.append(
                _item(
                    key,
                    section,
                    key,
                    label,
                    "needs_me",
                    _plural(len(lines), noun) + " need me",
                    lines,
                )
            )
        elif soft:
            out.append(_item(key, section, key, label, "worth_a_look", "Worth a look", soft))
        else:
            out.append(_item(key, section, key, label, "healthy", "Healthy"))
    return out


def _core():
    c = _mod("core_consumption")
    if c is None or not hasattr(c, "badge"):
        return []
    n = c.badge()
    try:
        have = (c.get() or {}).get("state") == "ok" and bool((c.get() or {}).get("consumers"))
    except Exception:  # noqa: BLE001
        have = False
    if not n and not have:
        return []
    if n:
        return [
            _item(
                "core",
                "cost",
                "core",
                "Core",
                "needs_me",
                f"{_plural(n, 'approval')} waiting on me",
            )
        ]
    return [_item("core", "cost", "core", "Core", "healthy", "Nothing waiting")]


def collect():
    items = []
    for src in (_builds, _infra, _core):
        try:
            items += src()
        except Exception as e:  # noqa: BLE001 - one source never takes the list down
            items.append(
                _item(
                    src.__name__.strip("_"),
                    "other",
                    src.__name__.strip("_"),
                    src.__name__.strip("_"),
                    "needs_me",
                    "Could not read this source",
                    [str(e)[:200]],
                )
            )
    # needs_me first, then worth a look, then healthy; a running item stays among its tone
    order = {"needs_me": 0, "worth_a_look": 1, "healthy": 2}
    items.sort(key=lambda i: (order[i["tone"]], i["section"], i["item"]))
    counts = {
        "needs_me": 0,
        "worth_a_look": 0,
        "healthy": 0,
        "running": 0,
        "total": len(items),
        "by_section": {},
        "by_item": {},
    }
    for i in items:
        counts[i["tone"]] += 1
        counts["running"] += 1 if i["running"] else 0
        if i["count"]:
            counts["by_section"][i["section"]] = counts["by_section"].get(i["section"], 0) + 1
            k = f"{i['section']}/{i['item']}"
            counts["by_item"][k] = counts["by_item"].get(k, 0) + 1
    return {"items": items, "counts": counts}
