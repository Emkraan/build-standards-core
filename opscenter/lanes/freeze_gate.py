#!/usr/bin/env python3
"""
freeze_gate.py

Purpose: Decide whether a pull request may be auto-merged right now, given the active change-freeze
         windows. A merge to main can trigger a push-to-main deploy, so an unattended auto-merge is a
         production change and must respect the freeze the same way a human change does. The windows
         come from the `freeze_source` slot (opscenter/DESIGN.md section 5.3) as a freeze file that a
         sync job writes; this module only reads it and classifies.

Read-only: touches no repo, no code host state, no deploy surface.

Usage:
  freeze_gate.py --config freeze.json --repo owner/name --pr 146
  freeze_gate.py --config freeze.json --paths app/server/index.js README.md
  cat changed-paths.txt | freeze_gate.py --config freeze.json --stdin
  freeze_gate.py --config freeze.json --status          # freeze posture only, no PR

Freeze file (JSON):
  timezone        zone the window stamps are written in (default UTC)
  windows[]       {id, name, start, end, exception}; stamps are YYYY-MM-DDTHH:MM:SS; end null means
                  open ended
  deploy_impact   {deploy_paths[], client_globs[], non_deploying_prefixes[], non_deploying_suffixes[],
                  quiet_heads[]}: which changed paths cause a deploy on push to main

Output: one JSON object on stdout.
  verdict            MERGE_OK | HOLD
  in_freeze          true, false or null (unknown)
  window             the matching window id, or null
  deploy_impacting   true, false or null (unknown)
  matched_paths      the changed paths that cause a production deploy
  reason             one plain sentence, safe to paste into a pull request comment
Exit codes: 0 = MERGE_OK, 10 = HOLD, 2 = usage or configuration error.

Fail closed by design. If the freeze file is missing or unreadable, if a window is open ended, if the
changed paths cannot be listed, or if path classification is ambiguous, the answer is HOLD.
"""

import argparse
import fnmatch
import json
import subprocess
import sys
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - 3.9+ always has it
    ZoneInfo = None

EXIT_OK = 0
EXIT_HOLD = 10
EXIT_ERROR = 2

DEFAULT_QUIET_HEADS = ("docs", "scripts", ".github")


def hold(reason, in_freeze=None, window=None):
    """The fail closed answer: a HOLD with a reason and every other field unknown."""
    return (
        {
            "verdict": "HOLD",
            "in_freeze": in_freeze,
            "window": window,
            "deploy_impacting": None,
            "matched_paths": [],
            "reason": reason,
        },
        EXIT_HOLD,
    )


def load_config(path):
    """Return (config, None) or (None, hold answer)."""
    try:
        with open(path, encoding="ascii", errors="replace") as handle:
            return json.load(handle), None
    except FileNotFoundError:
        return None, hold(
            f"Freeze config {path} is missing, so freeze posture is unknown. Failing closed: no auto-merge."
        )
    except (ValueError, OSError) as err:
        return None, hold(
            f"Freeze config {path} is unreadable ({err}). Failing closed: no auto-merge."
        )


def now_local(tz_name, now=None):
    """The wall time in the freeze zone, naive. `now` (an aware datetime) is for tests."""
    if ZoneInfo is not None:
        try:
            return (
                (now or datetime.now(ZoneInfo(tz_name)))
                .astimezone(ZoneInfo(tz_name))
                .replace(tzinfo=None)
            )
        except Exception:  # noqa: BLE001 - an unknown zone falls back to the host clock
            pass
    return datetime.now()


def parse_stamp(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")


def active_window(config, now=None):
    """Return (window, open_ended) for the freeze covering right now, else (None, False)."""
    current = now_local(config.get("timezone", "UTC"), now)
    for window in config.get("windows", []):
        start = parse_stamp(window.get("start"))
        end = parse_stamp(window.get("end"))
        if start is None or current < start:
            continue
        if end is None:
            return window, True  # open ended: fail closed
        if current <= end:
            return window, False
    return None, False


def changed_paths_for_pr(repo, number, run=subprocess.run):
    """Return (paths, None) or (None, hold answer). `run` is replaceable in tests."""
    cmd = ["gh", "api", f"repos/{repo}/pulls/{number}/files", "--paginate", "--jq", ".[].filename"]
    try:
        out = run(cmd, capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as err:
        return None, hold(
            f"Could not list files for PR #{number} ({err}). Failing closed: no auto-merge."
        )
    if out.returncode != 0:
        detail = (out.stderr or "").strip()[:200]
        return None, hold(
            f"The code host could not list files for PR #{number}: {detail}. Failing closed: no auto-merge."
        )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()], None


def classify(paths, impact):
    """Return the subset of paths that cause a production deploy on push to main."""
    deploy_paths = impact.get("deploy_paths", [])
    client_globs = impact.get("client_globs", [])
    quiet_prefixes = tuple(impact.get("non_deploying_prefixes", []))
    quiet_suffixes = tuple(impact.get("non_deploying_suffixes", []))
    quiet_heads = tuple(impact.get("quiet_heads", DEFAULT_QUIET_HEADS))
    matched = []
    for path in paths:
        # Explicitly quiet surfaces first: docs, standards, ad-hoc scripts, infrastructure code that
        # has no apply workflow on push.
        if path.startswith(quiet_prefixes) or path.endswith(quiet_suffixes):
            continue
        hit = any(path == p or path.startswith(p) for p in deploy_paths)
        if not hit:
            hit = any(fnmatch.fnmatch(path, pattern.rstrip("/") + "/*") for pattern in client_globs)
        if not hit and "/" in path and path.split("/")[0] not in quiet_heads:
            # Unrecognised path inside an app folder: fail closed, treat it as deploy impacting.
            hit = True
        if hit:
            matched.append(path)
    return matched


def decide(config, paths, now=None):
    """The whole decision for a list of changed paths. Returns (payload, exit code)."""
    window, open_ended = active_window(config, now)
    in_freeze = window is not None
    if not paths:
        return hold(
            "No changed paths could be determined, so deploy impact is unknown. Failing closed: no auto-merge.",
            in_freeze,
            (window or {}).get("id"),
        )
    matched = classify(paths, config.get("deploy_impact", {}))
    deploy_impacting = bool(matched)
    base = {
        "in_freeze": in_freeze,
        "deploy_impacting": deploy_impacting,
        "changed_path_count": len(paths),
    }
    if not in_freeze:
        return (
            {
                **base,
                "verdict": "MERGE_OK",
                "window": None,
                "open_ended": False,
                "matched_paths": matched,
                "reason": "No freeze window active. Merge may proceed.",
            },
            EXIT_OK,
        )
    name = window.get("name")
    if not deploy_impacting:
        return (
            {
                **base,
                "verdict": "MERGE_OK",
                "window": window.get("id"),
                "window_name": name,
                "open_ended": open_ended,
                "matched_paths": [],
                "reason": f"In freeze ({name}), but none of the {len(paths)} changed paths trigger a "
                "push-to-main deploy. Merge may proceed.",
            },
            EXIT_OK,
        )
    tail = (
        " The end date for this window has not been published, so it holds until one is supplied."
        if open_ended
        else ""
    )
    return (
        {
            **base,
            "verdict": "HOLD",
            "window": window.get("id"),
            "window_name": name,
            "open_ended": open_ended,
            "window_end": window.get("end"),
            "exception": window.get("exception"),
            "matched_paths": matched,
            "reason": f"HOLD: inside {name} and this PR changes {len(matched)} path(s) that deploy to production on "
            f"push to main ({', '.join(matched[:5])}).{tail} Merging would ship an unapproved production change "
            "during the freeze.",
        },
        EXIT_HOLD,
    )


def status(config, now=None):
    window, open_ended = active_window(config, now)
    in_freeze = window is not None
    if in_freeze:
        said = f"IN FREEZE: {window.get('name')}{', end date not published' if open_ended else ''}."
    else:
        said = "No freeze window active."
    return (
        {
            "verdict": "HOLD" if in_freeze else "MERGE_OK",
            "in_freeze": in_freeze,
            "window": (window or {}).get("id"),
            "window_name": (window or {}).get("name"),
            "open_ended": open_ended,
            "deploy_impacting": None,
            "matched_paths": [],
            "reason": f"Freeze posture only. {said}",
        },
        EXIT_HOLD if in_freeze else EXIT_OK,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Change-freeze merge gate for pull requests.")
    parser.add_argument("--config", required=True, help="path to the freeze file")
    parser.add_argument("--repo", help="owner/name, needed with --pr")
    parser.add_argument("--pr", help="PR number; changed paths are read from the code host")
    parser.add_argument("--paths", nargs="*", default=None, help="explicit changed paths")
    parser.add_argument(
        "--stdin", action="store_true", help="read changed paths from stdin, one per line"
    )
    parser.add_argument("--status", action="store_true", help="report freeze posture only")
    args = parser.parse_args(argv)

    config, failed = load_config(args.config)
    if failed:
        payload, code = failed
    elif args.status:
        payload, code = status(config)
    else:
        paths = None
        if args.pr:
            if not args.repo:
                parser.error("--pr needs --repo")
            paths, failed = changed_paths_for_pr(args.repo, args.pr)
        elif args.stdin:
            paths = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
        elif args.paths:
            paths = args.paths
        else:
            parser.error("one of --pr, --paths, --stdin or --status is required")
        payload, code = failed if failed else decide(config, paths)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
