#!/usr/bin/env python3
"""
Bundle the ops center state into the app's data directory: the board composer.

Purpose: The app reads a set of small JSON files under data/ that this script assembles from the live state
         files. Run on every refresh tick (and before an app build) so the app reflects current state. The
         most important file is action-center.json: the analysis job's file after the item contract check
         (contract.py), the items the ops center adds itself, the routing filter (routing.py), the handled
         aliasing (handled.py), the first seen stamps (first_seen.py) and every item's stable fingerprint.
         Pure stdlib.

This is the single seam between the markdown and JSON state world and the app. The design's direction is live
reads with no bundle (DESIGN.md 2.4); this step is the migration path a consumer still on a bundle runs, and
it stays correct on its own.

Config:  OPSCENTER_ROOT, OPSCENTER_STATE_DIR (paths.py), OPSCENTER_AGENT_HOME
         OPSCENTER_BUNDLE_OUT       directories the data files are written to, separated by the path separator
                                    (default <state>/public-data)
         OPSCENTER_BUNDLE_DATASETS  JSON {file name: source JSON file}: further datasets copied through as they are
         OPSCENTER_MONITORS         JSON [{"name", "path"}]: monitor state files whose last run time the board shows
         OPSCENTER_TZ               the zone of the "refreshed" stamp (default UTC)
         OPSCENTER_PEOPLE           plug-in with agenda_action_items() and harvest(force): the 1:1 board
         OPSCENTER_BOARD_SOURCES    JSON list of plug-ins with action_items() (and harvest_feeds()): extra items
         OPSCENTER_REF_STATUS       plug-in with finished(items): closes an auto item whose references are all done
         OPSCENTER_TEAM_AWAY        plug-in with snapshot(): who is out today, shown above the list
"""

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collect  # noqa: E402

STATE = collect.STATE
OUT_DIRS = [
    Path(p)
    for p in (os.environ.get("OPSCENTER_BUNDLE_OUT") or str(STATE / "public-data")).split(
        os.pathsep
    )
    if p
]


def _tz():
    try:
        return ZoneInfo(os.environ.get("OPSCENTER_TZ") or "UTC")
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def read(p):
    try:
        return Path(p).read_text(encoding="utf-8")
    except OSError:
        return ""


def load_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default if default is not None else {}


def freeze_status(p):
    """Current and next change-freeze window from the freeze file ({"timezone", "windows": [{name, start, end,
    exception}], "synced"}). Window times are wall clock in the file's zone (default UTC)."""
    cf = load_json(p, {})
    try:
        zone = ZoneInfo(cf.get("timezone") or "UTC")
    except Exception:  # noqa: BLE001
        zone = ZoneInfo("UTC")
    now = dt.datetime.now(zone).replace(tzinfo=None)
    current, upcoming = None, None
    for w in sorted(cf.get("windows") or [], key=lambda w: w.get("start") or ""):
        try:
            start, end = dt.datetime.fromisoformat(w["start"]), dt.datetime.fromisoformat(w["end"])
        except (KeyError, TypeError, ValueError):
            continue
        rec = {
            "name": w.get("name"),
            "start": w["start"],
            "end": w["end"],
            "exception": w.get("exception"),
        }
        if start <= now <= end:
            current = rec
        elif start > now and upcoming is None:
            upcoming = {**rec, "days_out": (start.date() - now.date()).days}
    return {
        "in_freeze": current is not None,
        "current": current,
        "next": upcoming,
        "synced": cf.get("synced") or (cf.get("source_workbook") or {}).get("last_synced"),
    }


def monitor_health():
    """Last run time of each monitor named in OPSCENTER_MONITORS ([{"name", "path"}]). A monitor state writes its
    last run under "updated"; the legacy keys are read as a fallback."""
    try:
        listed = json.loads(os.environ.get("OPSCENTER_MONITORS") or "[]")
    except ValueError:
        listed = []
    out = []
    for m in listed if isinstance(listed, list) else []:
        if not isinstance(m, dict) or not m.get("path"):
            continue
        d = load_json(m["path"])
        updated = d.get("updated") or d.get("last_check_utc") or d.get("updated_utc")
        out.append({"name": m.get("name") or Path(m["path"]).stem, "updated": updated})
    return out


def ac_fingerprint(item):
    """Stable id for an action item so Resolve/Ignore survives rebuilds even
    when the LLM rewords the title or regroups the related tickets. Basis, in
    priority order:
      1. explicit item["key"] (a stable slug the cron sets per underlying issue)
      2. the PRIMARY ref (first ref as emitted, uppercased) - anchoring on the
         one ticket the item is really about survives the cron adding or
         dropping *related* refs run to run (e.g. [CHN-4139] one run,
         [CHN-4139,CHN-4037,CHN-4071] the next both anchor on CHN-4139)
      3. the title with volatile counter tokens removed (bare digits and
         "day N" / "occurrence N" style counters) so "day 14+ unshipped" and
         "day 15+ unshipped" collapse to one id
    MUST stay byte-identical to the fingerprint spec in the Action Center
    analysis cron prompt and documented in action-suppressions.json.
    """
    import hashlib

    key = str(item.get("key", "")).strip().lower()
    if key:
        basis = "key:" + key
    else:
        refs = [str(r).upper().strip() for r in item.get("refs", []) if r]
        if refs:
            basis = "ref:" + refs[0]
        else:
            title = (item.get("title", "")).lower()
            # drop counter tokens ("day 14", "occurrence 15", "occ 3", "#7")
            title = re.sub(
                r"\b(day|occurrence|occ|attempt|round|iteration|week|hour|hr|instance|count|no|number|#)\s*#?\d+\b",
                "",
                title,
            )
            title = re.sub(r"[^a-z ]", "", title)  # strips remaining digits + punct
            title = re.sub(r"\s+", " ", title).strip()
            basis = "title:" + title
    return "ac_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def routing_summary():
    """Counts the Action Center shows next to its list: rules in force, candidates the
    collector considered, routed away, and the analysis's own drop reasons."""
    rules = load_json(STATE / "dashboard" / "ac-routing.json", {}).get("rules", [])
    rep = load_json(STATE / "dashboard" / "ac-routing-report.json", {})
    return {
        "rules": sum(1 for r in rules if not r.get("disabled")),
        "considered": rep.get("considered", 0),
        "routed_away": len(rep.get("routed_away", [])),
        "report_utc": rep.get("generated_utc"),
        "collector_errors": rep.get("errors", []),
        "unregistered": rep.get("unregistered", []),
    }


def close_finished_auto_items(items):
    """Drop (and retire in the automation store) auto- items whose linked PRs are all merged and linked tickets
    all done. The ref check (the OPSCENTER_REF_STATUS plug-in) never closes an item with no resolvable ref or on a
    failed read, and any error here keeps the board whole (unknown never hides). With no plug-in nothing closes."""
    try:
        ref_status = collect.plugin("OPSCENTER_REF_STATUS")
        if ref_status is None:
            return items
        automation_actions = collect.automation()
        verdict = ref_status.finished(items)
        if not verdict:
            return items
        kept = []
        for it in items:
            why = verdict.get(it.get("key"))
            if why is None:
                kept.append(it)
                continue
            key = str(it["key"])
            automation_actions.close_item(
                key[len(automation_actions.PREFIX) :], "closed by the live ref check: " + why
            )
            print(f"auto card closed: {key} ({why})")
        return kept
    except Exception as e:  # noqa: BLE001 - any failure keeps the board whole
        print(f"auto card close skipped: {e}")
        return items


ANALYSIS_ALERT_ID = "ac-analysis-rejected"  # shown on the board as auto-ac-analysis-rejected


def settle_analysis(dash):
    """Enforce the item contract on the analysis job's file before anything else reads it.

    The job writes one file (action-center.json). contract.settle validates it (required
    fields, priority values, every must-consider candidate covered or dropped). A file that fails
    is swapped for the last good one, so the board keeps its last good items, and one Action
    Center item (automation_actions, the same alert path the failing crons use) names the errors.
    The item closes itself when a later file passes. Returns the verdict for the board summary.
    Any failure of the check itself is reported on the board data and never hides the board."""
    try:
        import contract

        verdict = contract.settle(dash)
    except Exception as e:  # noqa: BLE001 - the board stays whole, the summary says the check did not run
        print(f"analysis contract check did not run: {e}")
        return {"status": "error", "errors": [str(e)], "coverage_checked": False, "streak": 0}
    try:
        automation_actions = collect.automation()
        if verdict["status"] in ("rejected", "unchanged") and verdict["errors"]:
            shown = "; ".join(verdict["errors"][:5]) + (
                " and %d more" % (len(verdict["errors"]) - 5) if len(verdict["errors"]) > 5 else ""  # noqa: UP031
            )
            automation_actions.raise_item(
                ANALYSIS_ALERT_ID,
                title="The Action Center analysis was rejected",
                why="The last analysis file failed the item contract (%d rejections in a row), so the board is still on the last good analysis. Errors: %s"  # noqa: UP031
                % (verdict["streak"], shown),
                action="The next run retries on its own (20 minutes, then at most every 4 hours after 3 in a row). The rejected file is kept as action-center.rejected.json in the dashboard folder.",
                priority="high",
                owner=collect.cfg()["owner_name"],
                source="Action Center analysis",
            )
            print(f"analysis rejected: {shown}")
        elif verdict["status"] == "accepted":
            automation_actions.close_item(
                ANALYSIS_ALERT_ID, "A later analysis passed the item contract."
            )
    except Exception as e:  # noqa: BLE001 - the alert is best effort, the rejection already held the board
        print(f"analysis rejection alert not raised: {e}")
    return verdict


def load_action_center(p):
    """Load action-center.json and stamp each item with its stable fingerprint
    so the app can persist Resolve/Snooze/Ignore decisions client-side. Also
    merges the owner's open 1:1 agenda actions (key oo-<id>) so anything that needs the owner
    is on the Action Center, linked back to the person's 1:1."""
    contract = settle_analysis(Path(p).parent)
    ac = load_json(p, {})
    ac["contract"] = {k: contract[k] for k in ("status", "errors", "coverage_checked", "streak")}
    items = ac.setdefault("items", []) or []
    # Items the ops center raises by itself (1:1 agenda oo-, files file-, automations auto-), deterministic, merged
    # once each by key. A source that fails is reported and skipped.
    people = collect.plugin("OPSCENTER_PEOPLE") if os.environ.get("OPSCENTER_PEOPLE") else None
    sources = (
        [people] if people and hasattr(people, "agenda_action_items") else []
    ) + collect.board_sources()
    for mod in sources:
        try:
            if hasattr(mod, "harvest_feeds"):
                mod.harvest_feeds()
            fn = getattr(mod, "action_items", None) or mod.agenda_action_items
            have = {str(i.get("key", "")).lower() for i in items}
            for extra in fn():
                if extra["key"].lower() not in have:
                    items.append(extra)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            print(f"items from {getattr(mod, '__name__', '?')} merge skipped: {e}")
    # An auto- card closes itself once every PR and ticket it names is finished.
    items[:] = close_finished_auto_items(items)
    # Routing is data: the same ac-routing.json rules the collector applies to
    # candidates decide which items stay. This replaced hardcoded filters.
    # A missing or broken routing file keeps every item visible (unknown never hides).
    ac["routing"] = routing_summary()
    try:
        import routing

        items[:], away = routing.filter_items(items, routing.load())
        ac["routing"]["items_routed_away"] = away
        ac["routing"]["routed_away"] += len(away)
    except Exception as e:  # noqa: BLE001 - any failure keeps the board whole
        ac["routing"]["error"] = "routing not applied: %s" % e  # noqa: UP031
        print(f"routing filter skipped: {e}")
    ac["items"] = items
    for it in items:
        it["fp"] = ac_fingerprint(it)
    # A re-keyed or reworded repeat of something the owner resolved, ignored or snoozed takes that decision's
    # fp, so the owner's Ignore holds when the analysis drifts the key (handled.py). A broken
    # handled store keeps every item visible (unknown never hides).
    try:
        import handled as handled_mod

        decisions = load_json(STATE / "dashboard" / "action-handled.json", {}).get("handled", {})
        # Source evidence (newest message per cid) decides whether a repeat is a real
        # recurrence, and first-seen keeps a second ask already on the board from aliasing.
        evidence = handled_mod.evidence_from_report(
            load_json(STATE / "dashboard" / "ac-routing-report.json", None)
        )
        first_seen = load_json(STATE / "dashboard" / "ac-first-seen.json", {}).get("first_seen", {})
        ac["aliased"] = [
            {"fp": old, "to": new, "reason": why}
            for old, new, why in handled_mod.alias_items(
                items, decisions, evidence=evidence, first_seen=first_seen
            )
        ]
    except Exception as e:  # noqa: BLE001 - any failure keeps the board whole
        print(f"handled alias skipped: {e}")
    # When each item first reached the board, so age is data, not model prose.
    try:
        import fcntl

        import first_seen

        store = STATE / "dashboard" / "ac-first-seen.json"
        lock = collect.AGENT_HOME / "cache" / "ac-first-seen.lock"  # outside the repo
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            seen = first_seen.load(store)
            if first_seen.stamp(items, seen):
                first_seen.save(store, seen)
    except Exception as e:  # noqa: BLE001 - a broken store leaves the column blank
        print(f"first-seen stamp skipped: {e}")
    # Who on the owner's team is out today and soon, shown above the list (plug-in, optional).
    try:
        away = collect.plugin("OPSCENTER_TEAM_AWAY")
        ac["team_away"] = away.snapshot() if away else {"people": []}
    except Exception as e:  # noqa: BLE001 - the strip says unknown, the board stays whole
        ac["team_away"] = {"error": "team availability not loaded: %s" % e, "people": []}  # noqa: UP031
    return ac


def main():
    for d in OUT_DIRS:
        d.mkdir(parents=True, exist_ok=True)
    # Keep the 1:1 topic ledger current even when no browser is open (people plug-in, pure parsing).
    try:
        people = collect.plugin("OPSCENTER_PEOPLE")
        if people is not None and hasattr(people, "harvest"):
            people.harvest(force=True)
    except Exception as e:  # noqa: BLE001
        print(f"people harvest skipped: {e}")

    now = dt.datetime.now(dt.timezone.utc)
    local = now.astimezone(_tz())
    manifest = {
        "generated_utc": now.isoformat(),
        "generated_et": local.strftime("%a %Y-%m-%d %I:%M %p ") + (local.tzname() or "UTC"),
    }
    datasets = {
        "manifest.json": manifest,
        "action-center.json": load_action_center(STATE / "dashboard" / "action-center.json"),
        "freeze.json": freeze_status(STATE / "change-freeze.json"),
        "monitors.json": {"monitors": monitor_health()},
    }
    try:
        extra = json.loads(os.environ.get("OPSCENTER_BUNDLE_DATASETS") or "{}")
    except ValueError:
        extra = {}
    for fname, src in (extra if isinstance(extra, dict) else {}).items():
        datasets[str(fname)] = load_json(src)
    written = 0
    for out in OUT_DIRS:
        for fname, data in datasets.items():
            (out / fname).write_text(json.dumps(data, indent=2), encoding="utf-8")
            written += 1
    print(f"bundled {len(datasets)} datasets x {len(OUT_DIRS)} targets ({written} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
