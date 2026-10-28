#!/usr/bin/env python3
"""
Assemble the analysis bundle for the Action Center LLM cron. Prints a single JSON blob to
stdout. Read-only against state, except the routing report and the unrouted-source ratchet
item the collector maintains.

The bundle comes from the collector (collect.py): every source
is normalized into one candidate shape and routed by DATA (ac-routing.json), so what reaches
the board no longer depends on prose rules in the analysis prompt.
  candidates_must     routed action_center: the analysis emits an item or records a drop reason
  candidates_context  routed analysis: context the analysis may fold into an item
  routed_away         routed elsewhere or nowhere by a rule: never an item
  on_board            items the ops center adds itself (1:1 agenda, files, automations)
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collect  # noqa: E402
import handled  # noqa: E402
import routing  # noqa: E402
import state_extract as B  # noqa: E402

STATE = collect.STATE
DASH = collect.DASH

CONTEXT_TEXT_CAP = 400
# Newest N per noisy context source, so the bundle stays readable. Must-consider candidates
# are never capped.
# keyed by fnmatch glob over the source id, so every chat feed prefix is covered
CONTEXT_CAPS = {"mail.other": 40, "*.group": 40, "*.channel_reply": 20, "*.channel": 20}
CAND_KEYS = (
    "cid",
    "source",
    "actor",
    "actor_role",
    "addressed",
    "received",
    "key",
    "title",
    "text",
    "refs",
    "owner",
    "link",
    "extra",
)
ON_BOARD_PREFIXES = ("oo-", "file-", "auto-")


def _zone():
    try:
        return ZoneInfo(os.environ.get("OPSCENTER_TZ") or "UTC")
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def head(md, n):
    return "\n".join(md.split("\n")[:n])


def main():
    rules = routing.load()  # a broken routing file fails the build, the gate fails open
    res = collect.collect(rules)
    cands = res["candidates"]

    must = [
        {k: c.get(k) for k in CAND_KEYS if c.get(k) not in (None, "", [], {})}
        for c in cands
        if c["route"] == "action_center"
    ]
    ctx_all = sorted(
        (c for c in cands if c["route"] == "analysis"),
        key=lambda c: c.get("received") or "",
        reverse=True,
    )
    seen, context = {}, []
    for c in ctx_all:
        n = seen.get(c["source"], 0)
        cap = next((n for g, n in CONTEXT_CAPS.items() if fnmatch.fnmatch(c["source"], g)), None)
        if cap is not None and n >= cap:
            continue
        seen[c["source"]] = n + 1
        row = {k: c.get(k) for k in CAND_KEYS if c.get(k) not in (None, "", [], {})}
        if row.get("text"):
            row["text"] = row["text"][:CONTEXT_TEXT_CAP]
        context.append(row)
    away = [
        {k: c.get(k) for k in ("cid", "source", "actor", "title", "rule", "where")}
        for c in cands
        if c["route"] in ("elsewhere", "nowhere")
    ]

    prev_raw = [
        {
            k: it.get(k)
            for k in ("key", "priority", "title", "why", "action", "owner", "refs", "sources")
        }
        for it in B._load_json(DASH / "action-center.json").get("items", [])
        if not str(it.get("key", "")).startswith(ON_BOARD_PREFIXES)
    ]
    # A previous item that a routing rule now sends elsewhere is not carried forward.
    prev, prev_away = routing.filter_items(prev_raw, rules)

    roles, _ = collect.people_roles(rules)
    current = B._read(collect.cfg()["state_files"]["current"])
    snap = B._load_json(collect.cfg()["tracker_snapshot"])
    by_status, by_priority, overdue, total = B.ticket_stats(snap)
    bundle = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "candidates_must": must,
        "candidates_context": context,
        "routed_away": away,
        "on_board": collect.on_board_items(),
        "people": {n: r for n, r in sorted(roles.items())},
        "collector_errors": res["errors"],
        "current_state_top": head(current, 90),
        "decisions_recent": [
            {"date": d, "title": t, "first": f}
            for d, t, f in B.newest_dated_entries(
                B._read(collect.cfg()["state_files"]["decisions"]), 8
            )
        ],
        "tickets": {
            "total": total,
            "by_status": by_status,
            "by_priority": by_priority,
            "overdue": overdue,
        },
        "freeze_window": snap.get("freeze_window"),
        "suppressions": B._load_json(DASH / "action-suppressions.json"),
        # Key, title and refs per decision so the analysis reuses the key of something the owner
        # ignored and recognises a reworded repeat (handled.py also aliases it on bundle).
        "handled": handled.compact_for_bundle(
            B._load_json(DASH / "action-handled.json").get("handled", {})
        ),
        "now_et": dt.datetime.now(_zone()).strftime("%a %Y-%m-%d %H:%M %Z"),
        # The owner's previous synthesis, for CARRY FORWARD. The wake gate drops this key from its hash.
        "previous_items": prev,
    }
    try:
        collect.report(res, items_away=prev_away)
        collect.ratchet(res["unregistered"])
    except Exception as exc:  # the report is visibility only, never blank the bundle
        bundle["collector_errors"].append("report: %s" % exc)  # noqa: UP031
    # Live status of every PR and ticket named in the bundle (the optional ref status plug-in).
    try:
        ref_status = collect.plugin("OPSCENTER_REF_STATUS")
        if ref_status is None:
            bundle["ref_status"] = {"finished": {}, "errors": []}
        else:
            rs = ref_status.resolve(
                json.dumps(
                    [
                        bundle[k]
                        for k in (
                            "candidates_must",
                            "candidates_context",
                            "current_state_top",
                            "previous_items",
                            "on_board",
                        )
                    ],
                    ensure_ascii=True,
                )
            )
            bundle["ref_status"] = {
                "finished": {k: rs["refs"][k] for k in rs["done"]},
                "errors": rs["errors"],
            }
    except Exception as exc:  # never let a lookup failure blank the bundle
        bundle["ref_status"] = {"finished": {}, "errors": [f"ref_status: {exc}"]}
    print(json.dumps(bundle, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
