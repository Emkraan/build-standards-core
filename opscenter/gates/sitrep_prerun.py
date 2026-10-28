#!/usr/bin/env python3
"""
sitrep_prerun.py

Purpose: Pre-run script for a morning brief written by an agent. Prints the overnight health block first (the
         consumer's health command, when one is configured), then what the brief needs to avoid re-surfacing
         finished work:
           1. OPEN ACTION CENTER ITEMS: the served board minus everything the owner resolved, ignored or
              snoozed. This is the curated must-do source.
           2. RESOLVED OR IGNORED IN THE LAST 72H: titles, so a state file item that matches one is skipped.
           3. LIVE REF STATUS (optional plug-in): pull requests and tickets named in the state files and the
              open items, checked live, finished ones only.
Usage:   sitrep_prerun.py
Exit:    0 always when the blocks printed (the scheduler treats non-zero as a script error), 2 when the
         health command itself broke.
Config:  OPSCENTER_URL or OPSCENTER_PORT (as sitrep.py);
         SITREP_HEALTH_CMD     a command (path to a python script) whose output is printed first; unset prints none
         SITREP_STATE_FILES    JSON list of [path, line count]: the state files the ref check reads the head of
         SITREP_REF_STATUS     a python file with resolve(text) and done_lines(result); unset skips block 3
System python3 is 3.9: no 3.10+ syntax.
"""

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sitrep  # noqa: E402

HEALTH = os.environ.get("SITREP_HEALTH_CMD") or ""


def head(path, n):
    try:
        with open(path, errors="ignore") as fh:
            return "".join(fh.readline() for _ in range(n))
    except OSError:
        return ""


def state_files():
    try:
        v = json.loads(os.environ.get("SITREP_STATE_FILES") or "[]")
    except ValueError:
        return []
    if not isinstance(v, list):
        return []
    return [(str(p), int(n)) for p, n in v]


def load_ref_status():
    p = os.environ.get("SITREP_REF_STATUS")
    if not p:
        return None
    spec = importlib.util.spec_from_file_location("sitrep_ref_status", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    if HEALTH:
        p = subprocess.run([sys.executable, HEALTH], capture_output=True, text=True, timeout=120)
        sys.stdout.write(p.stdout)
        if p.returncode != 0:
            sys.stdout.write(p.stderr[-400:])
            return p.returncode or 2

    open_text = ""
    try:
        open_items = sitrep.open_action_items()
        handled = sitrep.get_json("/api/action-handled")
        handled = handled.get("handled", handled)
        print(
            f"\nOPEN ACTION CENTER ITEMS ({len(open_items)}, served board minus handled, highest first):"
        )
        for it in open_items[:15]:
            line = "- [{}] {} | owner {} | next: {}".format(
                it.get("priority"),
                it.get("title"),
                it.get("owner") or "-",
                (it.get("action") or "")[:220],
            )
            print(line)
            open_text += line + " " + " ".join(it.get("refs") or []) + "\n"
        cut = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=72)).isoformat()
        recent = [
            h
            for h in handled.values()
            if h.get("act") in ("resolved", "ignored", "ignored_forever")
            and (h.get("at") or "") >= cut[:19]
        ]
        recent.sort(key=lambda h: h.get("at") or "", reverse=True)
        print(f"\nRESOLVED OR IGNORED ON THE ACTION CENTER IN THE LAST 72H ({len(recent)}):")
        for h in recent[:25]:
            title = ((h.get("item") or {}).get("title")) or h.get("summary") or "(no title)"
            print(
                "- {} {}: {}".format(
                    (h.get("at") or "")[:16].replace("T", " "), h.get("act"), title[:160]
                )
            )
    except Exception as exc:  # noqa: BLE001 - board unreachable: say so, never block the brief
        print(
            f"\nOPEN ACTION CENTER ITEMS: unavailable ({str(exc)[:120]}). Fall back to the state files."
        )

    ref = None
    try:
        ref = load_ref_status()
    except Exception as exc:  # noqa: BLE001
        print(f"\nLIVE REF STATUS: unavailable ({str(exc)[:120]}).")
    if ref is not None:
        try:
            text = "".join(head(p, n) for p, n in state_files()) + open_text
            rs = ref.resolve(text)
            print(
                f"\nLIVE REF STATUS ({len(rs['refs'])} refs checked, {len(rs['done'])} finished):"
            )
            for line in ref.done_lines(rs):
                print(line)
            for e in rs["errors"]:
                print(f"- check error: {e}")
        except Exception as exc:  # noqa: BLE001
            print(f"\nLIVE REF STATUS: unavailable ({str(exc)[:120]}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
