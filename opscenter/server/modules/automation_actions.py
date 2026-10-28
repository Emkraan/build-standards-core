#!/usr/bin/env python3
"""Action Center items raised by the owner's automations (key prefix auto-).

.

A cron or session that finishes (or stops) unattended work and needs me to act raises one
item here instead of a chat message. bundle_data.load_action_center merges the
open items into the board on every refresh, so they survive the analysis job's re-synthesis.
Resolve or Ignore on the board hides an item by fingerprint like any other item. `close`
retires an item here once the automation knows it no longer applies.

Store: state/dashboard/automation-actions.json {"items": {"<id>": {...}}}. Stdlib only
(the gates and crons run on the system python 3.9).

CLI:
  automation_actions.py raise --id ID --title T --why W --action A [--priority high]
      [--owner NAME] [--ref <ticket-id>] [--link "Label=https://..."] [--source "Cron name"]
  automation_actions.py close --id ID --reason R
  automation_actions.py list
Raising an existing id updates it in place (and reopens it if it was closed).
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import paths

ROOT = Path(os.environ.get("OPSCENTER_ROOT", paths.root()))
STORE_PATH = ROOT / "state" / "dashboard" / "automation-actions.json"
PREFIX = "auto-"
PRIORITIES = ("critical", "high", "medium", "low")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,80}$")


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _ascii(s):
    s = str(s or "")
    for a, b in (
        ("\u2014", ", "),
        ("\u2013", "-"),
        ("\u2018", "'"),
        ("\u2019", "'"),
        ("\u201c", '"'),
        ("\u201d", '"'),
    ):
        s = s.replace(a, b)
    return s.encode("ascii", "replace").decode("ascii")


def _load():
    try:
        with open(STORE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("items"), dict):
            return data
    except FileNotFoundError:
        pass
    return {"items": {}}


def _save(data):
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(STORE_PATH.parent), prefix=".automation-actions.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
        f.write("\n")
    os.replace(tmp, STORE_PATH)


def raise_item(
    item_id,
    title,
    why,
    action,
    priority="high",
    owner="",
    refs=None,
    links=None,
    source="",
    extra=None,
):
    """extra: optional {"draft": {...}, "approve": {...}} rendered by the Action Center modal
    (draft fields to review and edit, plus an Approve button wired to a whitelisted handler).
    extra["actions"]: a list of {kind, label, ...} buttons, each a whitelisted kind run by server.py
    _automation_approve after a live re-read."""
    if not ID_RE.match(item_id):
        raise ValueError("id must be lowercase letters, digits and dashes (3 to 81 chars)")
    if priority not in PRIORITIES:
        raise ValueError("priority must be one of {}".format(", ".join(PRIORITIES)))
    for name, val in (("title", title), ("why", why), ("action", action)):
        if not str(val or "").strip():
            raise ValueError(f"{name} is required")
    data = _load()
    prev = data["items"].get(item_id, {})
    data["items"][item_id] = {
        "id": item_id,
        "priority": priority,
        "title": _ascii(title),
        "why": _ascii(why),
        "action": _ascii(action),
        "owner": _ascii(owner),
        "refs": [_ascii(r) for r in (refs or [])],
        "links": [{"label": _ascii(link["label"]), "url": link["url"]} for link in (links or [])],
        "source": _ascii(source),
        "raised_at": prev.get("raised_at") or _now(),
        "updated_at": _now(),
        "closed": None,
    }
    for k in ("draft", "approve", "actions"):
        if extra and extra.get(k):
            data["items"][item_id][k] = extra[k]
    _save(data)
    return data["items"][item_id]


def close_item(item_id, reason):
    data = _load()
    e = data["items"].get(item_id)
    if not e:
        return False
    e["closed"] = {"at": _now(), "reason": _ascii(reason)}
    _save(data)
    return True


def action_items():
    """Open items in Action Center shape (consumed by bundle_data.load_action_center)."""
    out = []
    for e in sorted(_load()["items"].values(), key=lambda x: x.get("raised_at") or ""):
        if e.get("closed"):
            continue
        out.append(
            {
                "key": PREFIX + e["id"],
                "priority": e.get("priority") or "high",
                "title": e.get("title", ""),
                "why": e.get("why", ""),
                "action": e.get("action", ""),
                "owner": e.get("owner", ""),
                "refs": e.get("refs") or [],
                "sources": ["Automation"] + ([e["source"]] if e.get("source") else []),
                "links": e.get("links") or [],
                **{k: e[k] for k in ("draft", "approve", "actions") if e.get(k)},
            }
        )
    return out


def _link(s):
    label, sep, url = s.partition("=")
    if not sep or not url.startswith("http"):
        raise argparse.ArgumentTypeError('link must be "Label=https://..."')
    return {"label": label.strip(), "url": url.strip()}


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Action Center items raised by the owner's automations (key prefix auto-)."
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("raise")
    r.add_argument("--id", required=True)
    r.add_argument("--title", required=True)
    r.add_argument("--why", required=True)
    r.add_argument("--action", required=True)
    r.add_argument("--priority", default="high", choices=PRIORITIES)
    r.add_argument("--owner", default="")
    r.add_argument("--ref", action="append", default=[])
    r.add_argument("--link", action="append", default=[], type=_link)
    r.add_argument("--source", default="")
    c = sub.add_parser("close")
    c.add_argument("--id", required=True)
    c.add_argument("--reason", required=True)
    sub.add_parser("list")
    a = p.parse_args(argv)
    try:
        if a.cmd == "raise":
            e = raise_item(
                a.id, a.title, a.why, a.action, a.priority, a.owner, a.ref, a.link, a.source
            )
            print("raised {}{}".format(PREFIX, e["id"]))
        elif a.cmd == "close":
            if not close_item(a.id, a.reason):
                print(f"no item {a.id}", file=sys.stderr)
                return 1
            print(f"closed {PREFIX}{a.id}")
        else:
            for e in _load()["items"].values():
                print(
                    "{}\t{}\t{}".format(
                        e["id"], "closed" if e.get("closed") else "open", e["title"]
                    )
                )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
