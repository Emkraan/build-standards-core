#!/usr/bin/env python3
"""
collect.py - source adapters for the Action Center collector.

Purpose: Turn every source the Action Center reads into ONE candidate shape, route each
         candidate through routing (rules are data in ac-routing.json), and hand the
         analysis only what belongs on the board. No source needs a prompt rule to be seen:
         a person who addresses me directly is considered by default (fail open), and every
         candidate routed away is counted in ac-routing-report.json.
Date:    2026-10-14

Candidate shape:
  cid         stable id (<source>:<native id>)
  source      source id, registered in ac-routing.json "sources"
  actor       person or system that produced it        actor_role  me|report|partner|leader|other|automation
  addressed   direct|mention|team|cc|none               received    ISO time
  key         stable slug when the source has one       title       one line
  text        body (capped)                             refs        ticket, CR or PR ids found in it
  owner       who it lands on when known                link        URL
  extra       source-specific facts (replied_after_last, status, ...)

Stdlib only, Python 3.9 floor. Every path and name is a parameter (config()), every source optional.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("OPSCENTER_ROOT") or Path.home() / ".opscenter")
STATE = Path(os.environ.get("OPSCENTER_STATE_DIR") or ROOT / "state")
DASH = STATE / "dashboard"
AGENT_HOME = Path(os.environ.get("OPSCENTER_AGENT_HOME") or ROOT / "agent")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import routing  # noqa: E402
import state_extract as B  # noqa: E402

TEXT_CAP = 1500
LINE_CAP = 600
REPORT_PATH = DASH / "ac-routing-report.json"
UNROUTED_AUTO_ID = "ac-unrouted-sources"
DEFAULT_REF_REGEX = r"\b[A-Z][A-Z0-9]{1,9}-\d{2,6}\b|#\d{2,5}\b"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def config():
    """The collector's parameters: OPSCENTER_COLLECT_CONFIG (a JSON file, default <state>/dashboard/collector.json),
    every key optional, no default names an estate.
      owner_name          the owner's display name: their own messages are not asks, their tickets land on them
      ref_regex           what counts as a ticket or change reference in a text (default KEY-123 style, bare #123 ignored)
      ask_days            how far back mail and chat count (default 3)
      mail_feed           path of the mail feed file ({"items": [...]}, default <agent home>/feeds/mail.json)
      chat_feeds          [{"prefix", "label", "path", "team_posts"}]: one entry per chat platform; prefix names the
                          source ids (`<prefix>.1on1`, `<prefix>.mention`, ...), team_posts true makes a top level
                          channel post from a report, partner or leader read as addressed to the owner
      tracker_snapshot    path of the tracker snapshot ({"tickets": {KEY: {status, priority, duedate}}, "last_check_utc"})
      tracker_base_url    browse URL prefix for a ticket link (default none)
      state_files         {"current", "risk", "unplanned", "decisions"}: the markdown state files (default <state>/*.md names)
      doc_gaps_file       the documentation audit's store (default <dashboard>/doc-gaps.json)
    """
    p = os.environ.get("OPSCENTER_COLLECT_CONFIG") or str(DASH / "collector.json")
    try:
        cfg = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    feeds = AGENT_HOME / "feeds"
    sf = cfg.get("state_files") or {}
    return {
        "owner_name": str(
            cfg.get("owner_name") or os.environ.get("OPSCENTER_OWNER_NAME") or "the owner"
        ),
        "ref_re": re.compile(str(cfg.get("ref_regex") or DEFAULT_REF_REGEX)),
        "ask_days": int(cfg.get("ask_days") or 3),
        "mail_feed": Path(cfg.get("mail_feed") or feeds / "mail.json"),
        "chat_feeds": [
            {
                "prefix": str(f["prefix"]),
                "label": str(f.get("label") or f["prefix"]),
                "path": Path(f["path"]),
                "team_posts": bool(f.get("team_posts")),
            }
            for f in (cfg.get("chat_feeds") if isinstance(cfg.get("chat_feeds"), list) else [])
            if isinstance(f, dict) and f.get("prefix") and f.get("path")
        ],
        "tracker_snapshot": Path(cfg.get("tracker_snapshot") or STATE / "tracker-snapshot.json"),
        "tracker_base_url": str(cfg.get("tracker_base_url") or ""),
        "state_files": {
            "current": Path(sf.get("current") or STATE / "current-state.md"),
            "risk": Path(sf.get("risk") or STATE / "risk-radar.md"),
            "unplanned": Path(sf.get("unplanned") or STATE / "unplanned-work-ledger.md"),
            "decisions": Path(sf.get("decisions") or STATE / "decisions-log.md"),
        },
        "doc_gaps_file": Path(cfg.get("doc_gaps_file") or DASH / "doc-gaps.json"),
    }


_CFG = None


def cfg():
    """The parameters, read once per process; reload_config() re-reads them (tests, a long running server)."""
    global _CFG
    if _CFG is None:
        _CFG = config()
    return _CFG


def reload_config():
    global _CFG
    _CFG = None
    return cfg()


def plugin(env_name):
    """A plug-in module named by an environment variable holding a file path, or None."""
    p = os.environ.get(env_name)
    return _load_module("plugin_" + env_name.lower(), p) if p else None


def board_sources():
    """The modules that add items to the board by themselves, each with action_items(): the automation store, then
    every file named in OPSCENTER_BOARD_SOURCES (a JSON list of paths). A source that fails to load is skipped."""
    mods = []
    try:
        mods.append(automation())
    except Exception as exc:  # noqa: BLE001
        print(f"collect: automation items unavailable ({exc})", file=sys.stderr)
    try:
        listed = json.loads(os.environ.get("OPSCENTER_BOARD_SOURCES") or "[]")
    except ValueError:
        listed = []
    for i, p in enumerate(listed if isinstance(listed, list) else []):
        try:
            mods.append(_load_module(f"board_source_{i}", p))
        except Exception as exc:  # noqa: BLE001
            print(f"collect: board source {p} unavailable ({exc})", file=sys.stderr)
    return mods


def automation():
    """The core automation store (server/modules/automation_actions.py)."""
    modules = HERE.parent / "server" / "modules"
    if str(modules) not in sys.path:
        sys.path.insert(0, str(modules))
    return _load_module("automation_actions", modules / "automation_actions.py")


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _refs(*texts, ref_re=None):
    seen = []
    ref_re = ref_re or cfg()["ref_re"]
    for t in texts:
        for m in ref_re.findall(str(t or "")):
            if m.startswith("#"):
                continue  # bare PR numbers are ambiguous across repos, keep them in the text only
            if m not in seen:
                seen.append(m)
    return seen[:8]


def _line(m):
    when = (m.get("created") or "")[5:16].replace("T", " ")
    return "[%s UTC] %s: %s" % (when, m.get("from_name") or "?", (m.get("text") or "")[:LINE_CAP])  # noqa: UP031


def people_roles(routing_cfg):
    """name.lower() -> role, from the people plug-in's roster (reports and partners, OPSCENTER_PEOPLE, a file with
    roster() returning [{name, group}]) plus the routing file's people block (leaders and anyone else the owner
    classifies)."""
    roles = {cfg()["owner_name"].lower(): "me"}
    errors = []
    try:
        people = plugin("OPSCENTER_PEOPLE")
        for p in people.roster() if people else []:
            roles[p["name"].lower()] = p.get("group", "report")
    except Exception as exc:  # roster is best-effort, never blank the collection
        errors.append("roster unavailable: %s" % exc)  # noqa: UP031
    for role, names in (routing_cfg.get("people") or {}).items():
        for n in names or []:
            roles[str(n).lower()] = role
    return roles, errors


def role_of(name, roles, automated=False):
    if automated:
        return "automation"
    return roles.get(str(name or "").strip().lower(), "other")


# ------------------------------------------------------------------ adapters


def from_mail(roles, cut):
    feed = B._load_json(cfg()["mail_feed"]).get("items", [])
    out = []
    for m in feed:
        if (m.get("received") or "") < cut and not m.get("direct_ask"):
            continue
        direct = bool(m.get("direct_ask"))
        automated = (
            not direct
            and not m.get("direct_to_me")
            and "noreply" in str(m.get("from_addr", "")).lower()
        )
        body = m.get("body_text") or m.get("preview") or ""
        out.append(
            {
                "cid": "mail:%s" % m.get("id"),  # noqa: UP031
                "source": "mail.direct" if direct else "mail.other",
                "actor": m.get("from_name") or m.get("from_addr") or "",
                "actor_role": role_of(m.get("from_name"), roles, automated),
                "addressed": "direct"
                if direct
                else ("cc" if m.get("direct_to_me") is False else "none"),
                "received": m.get("received"),
                "title": m.get("subject") or "(no subject)",
                "text": body[:TEXT_CAP],
                "refs": _refs(m.get("subject"), body),
                "link": m.get("web_link"),
                "extra": {"to": m.get("to"), "cc": m.get("cc"), "importance": m.get("importance")},
            }
        )
    return out


def from_chats(roles, cut):
    out = []
    for f in cfg()["chat_feeds"]:
        out += from_chat(roles, cut, f["path"], f["prefix"], f["label"], f["team_posts"])
    return out


def from_chat(roles, cut, feed_path, prefix, label, team_posts=False):
    """Chat platforms share one adapter: 1:1 chats, mentions, channel posts, replies, group chats."""
    feed = B._load_json(feed_path).get("items", [])
    recent = sorted(
        (m for m in feed if (m.get("created") or "") >= cut), key=lambda m: m.get("created") or ""
    )
    out = []
    # 1:1 chats: one candidate per chat holding the conversation, the owner's replies included, so the
    # analysis can tell an open ask from one the owner already closed.
    chats = {}
    for m in recent:
        if m.get("surface") == "chat" and m.get("chat_type") == "oneOnOne":
            chats.setdefault(m.get("chat_id"), []).append(m)
    for chat_id, msgs in chats.items():
        theirs = [m for m in msgs if m.get("from_name") != cfg()["owner_name"]]
        if not theirs:
            continue
        last = theirs[-1]
        body = "\n".join(_line(m) for m in msgs[-40:])
        out.append(
            {
                "cid": "%s.1on1:%s" % (prefix, chat_id),  # noqa: UP031
                "source": "%s.1on1" % prefix,  # noqa: UP031
                "actor": last.get("from_name"),
                "actor_role": role_of(last.get("from_name"), roles),
                "addressed": "direct",
                "received": last.get("created"),
                "title": "%s 1:1 with %s" % (label, last.get("from_name")),  # noqa: UP031
                "text": body[-6000:],
                "refs": _refs(body),
                "link": last.get("web_url"),
                "extra": {
                    "replied_after_last": any(
                        m.get("from_name") == cfg()["owner_name"]
                        and (m.get("created") or "") > (last.get("created") or "")
                        for m in msgs
                    ),
                    "files": sum(len(m.get("files") or []) for m in theirs),
                },
            }
        )

    def thread_of(m):
        if m.get("surface") == "chat":
            return ("chat", m.get("chat_id"))
        return ("channel", m.get("reply_to") or m.get("id"))

    for m in recent:
        if m.get("from_name") == cfg()["owner_name"]:
            continue
        if m.get("surface") == "chat" and m.get("chat_type") == "oneOnOne":
            continue
        where = (
            label + " group chat '%s'" % (m.get("chat_topic") or "untitled")
            if m.get("surface") == "chat"
            else "%s / %s" % (m.get("team"), m.get("channel"))  # noqa: UP031
        )
        if m.get("mentions_me"):
            same = [x for x in recent if thread_of(x) == thread_of(m)]
            idx = same.index(m)
            body = "\n".join(_line(x) for x in same[max(0, idx - 3) : idx + 1])
            source, addressed = "%s.mention" % prefix, "mention"  # noqa: UP031
            extra = {
                "replied_after": any(
                    x.get("from_name") == cfg()["owner_name"] for x in same[idx + 1 :]
                ),
                "where": where,
            }
        elif m.get("surface") == "channel" and m.get("reply_to") is None:
            body = m.get("text") or ""
            source = "%s.channel" % prefix  # noqa: UP031
            # A top-level post from the owner's team to a team channel is addressed to me as a team member.
            # Slack channels are running conversations (vendor and shared channels included), so a
            # post there is context unless it tags me. DMs and tags are the direct path.
            addressed = (
                "team"
                if team_posts
                and role_of(m.get("from_name"), roles) in ("report", "partner", "leader")
                else "none"
            )
            extra = {"where": where}
        else:
            body = m.get("text") or ""
            source = (
                "%s.group" % prefix if m.get("surface") == "chat" else "%s.channel_reply" % prefix  # noqa: UP031
            )
            addressed = "none"
            extra = {"where": where}
        out.append(
            {
                "cid": m.get("id")
                if str(m.get("id") or "").startswith(prefix + ":")
                else "%s:%s" % (prefix, m.get("id")),  # noqa: UP031
                "source": source,
                "actor": m.get("from_name"),
                "actor_role": role_of(m.get("from_name"), roles),
                "addressed": addressed,
                "received": m.get("created"),
                "title": "%s in %s" % (m.get("from_name"), where),  # noqa: UP031
                "text": body[:TEXT_CAP],
                "refs": _refs(body),
                "link": m.get("web_url"),
                "extra": extra,
            }
        )
    return out


def from_tracker():
    snap = B._load_json(cfg()["tracker_snapshot"])
    out = []
    for key, t in (snap.get("tickets") or {}).items():
        out.append(
            {
                "cid": "tracker:%s" % key,  # noqa: UP031
                "source": "tracker.assigned",
                "actor": "",
                "actor_role": "automation",
                "addressed": "none",
                "received": snap.get("last_check_utc"),
                "title": "%s %s (%s)" % (key, t.get("status"), t.get("priority")),  # noqa: UP031
                "text": "",
                "refs": [key],
                "owner": cfg()["owner_name"],
                "link": (cfg()["tracker_base_url"] + key) if cfg()["tracker_base_url"] else "",
                "extra": {
                    "status": t.get("status"),
                    "priority": t.get("priority"),
                    "duedate": t.get("duedate"),
                },
            }
        )
    return out


def from_state():
    current = B._read(cfg()["state_files"]["current"])
    out = []
    for i, e in enumerate(B.extract_escalations(current)):
        text = json.dumps(e, ensure_ascii=True) if not isinstance(e, str) else e
        out.append(_state_cand("state.escalation", i, text))
    for i, e in enumerate(B.extract_stale_tickets(current)):
        text = json.dumps(e, ensure_ascii=True) if not isinstance(e, str) else e
        out.append(_state_cand("state.stale", i, text))
    for i, e in enumerate(B.extract_open_items(current, limit=25)):
        out.append(_state_cand("state.open_item", i, e))
    for src, path in (
        ("risk.recent", cfg()["state_files"]["risk"]),
        ("unplanned.recent", cfg()["state_files"]["unplanned"]),
    ):
        for d, t, f in B.newest_dated_entries(B._read(path), 8):
            out.append(
                {
                    "cid": "%s:%s:%s" % (src, d, re.sub(r"[^a-z0-9]+", "-", t.lower())[:60]),  # noqa: UP031
                    "source": src,
                    "actor": "",
                    "actor_role": "automation",
                    "addressed": "none",
                    "received": d,
                    "title": t,
                    "text": f[:TEXT_CAP],
                    "refs": _refs(t, f),
                    "link": "",
                    "extra": {},
                }
            )
    return out


def _state_cand(source, i, text):
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower())[:60]
    return {
        "cid": "%s:%s" % (source, slug or i),  # noqa: UP031
        "source": source,
        "actor": "",
        "actor_role": "automation",
        "addressed": "none",
        "received": "",
        "title": str(text)[:160],
        "text": str(text)[:TEXT_CAP],
        "refs": _refs(text),
        "link": "",
        "extra": {},
    }


def from_doc_gaps():
    store = B._load_json(cfg()["doc_gaps_file"])
    out = []
    for tid, t in (store.get("things") or {}).items():
        for g in t.get("gaps", []):
            if g.get("severity") not in ("high", "medium"):
                continue
            out.append(
                {
                    "cid": "doc:%s:%s" % (tid, g.get("id")),  # noqa: UP031
                    "source": "doc.gap",
                    "actor": "Documentation audit",
                    "actor_role": "automation",
                    "addressed": "none",
                    "received": store.get("generated_utc"),
                    "key": "doc-%s" % tid,  # noqa: UP031
                    "title": "%s: %s" % (t.get("name"), g.get("text")),  # noqa: UP031
                    "text": g.get("text", ""),
                    "refs": [],
                    "owner": t.get("owner_r") or "",
                    "link": "",
                    "extra": {"severity": g.get("severity"), "rule": g.get("rule")},
                }
            )
    return out


def on_board_items():
    """Items the ops center adds by itself (1:1 agenda oo-, files file-, automations auto-).
    The analysis must not duplicate them, so they travel as a list, not as candidates. Sources are the automation
    store and the modules named in OPSCENTER_BOARD_SOURCES; one that fails is reported and skipped."""
    out = []
    for mod in board_sources():
        try:
            out += mod.action_items()
        except Exception as exc:  # best effort, never blank the bundle
            print(
                "collect: items from %s unavailable (%s)" % (getattr(mod, "__name__", "?"), exc),  # noqa: UP031
                file=sys.stderr,
            )
    return [{k: i.get(k) for k in ("key", "title", "refs")} for i in out]


ADAPTERS = (
    ("mail", lambda roles, cut: from_mail(roles, cut)),
    ("chat", lambda roles, cut: from_chats(roles, cut)),
    ("tracker", lambda roles, cut: from_tracker()),
    ("state", lambda roles, cut: from_state()),
    ("doc", lambda roles, cut: from_doc_gaps()),
)


def collect(rules=None, now=None):
    """Run every adapter and route every candidate. Returns a dict with the routed
    candidates, the routed-away list, unregistered sources and per-adapter errors.
    An adapter that fails is reported, never silently skipped."""
    rules = rules or routing.load()
    now = now or _now()
    cut = _iso(now - dt.timedelta(days=cfg()["ask_days"]))
    roles, errors = people_roles(rules)
    cands = []
    for name, fn in ADAPTERS:
        try:
            cands += fn(roles, cut)
        except Exception as exc:  # one broken source must not hide the others
            errors.append("%s adapter failed: %s" % (name, exc))  # noqa: UP031
    registered = set((rules.get("sources") or {}).keys())
    unregistered = sorted({c["source"] for c in cands} - registered)
    routed = []
    for c in cands:
        r = routing.route(c, rules)
        routed.append(dict(c, route=r["route"], rule=r["rule"], where=r.get("where", "")))
    return {
        "candidates": routed,
        "unregistered": unregistered,
        "errors": errors,
        "generated": _iso(now),
    }


def report(result, items_away=None):
    """Write ac-routing-report.json (counts per route and source, what went where and why)."""
    counts = {}
    for c in result["candidates"]:
        counts.setdefault(c["route"], {}).setdefault(c["source"], 0)
        counts[c["route"]][c["source"]] += 1
    away = [
        {
            k: c.get(k)
            for k in (
                "cid",
                "source",
                "actor",
                "title",
                "route",
                "rule",
                "where",
                "received",
                "link",
            )
        }
        for c in result["candidates"]
        if c["route"] in ("elsewhere", "nowhere")
    ]
    rep = {
        "_comment": "Written by state/dashboard/collect.py on every Action Center bundle build. Do not hand-edit.",
        "generated_utc": result["generated"],
        "counts": counts,
        "considered": sum(1 for c in result["candidates"] if c["route"] == "action_center"),
        "considered_list": [
            {k: c.get(k) for k in ("cid", "source", "actor", "title", "received", "link", "rule")}
            for c in result["candidates"]
            if c["route"] == "action_center"
        ],
        "context": sum(1 for c in result["candidates"] if c["route"] == "analysis"),
        "routed_away": away[-200:],
        "items_routed_away": items_away or [],
        "unregistered": result["unregistered"],
        "errors": result["errors"],
    }
    tmp = REPORT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rep, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(REPORT_PATH))
    return rep


def ratchet(unregistered):
    """One low board item while any candidate source is not registered in ac-routing.json, closed as soon as the
    set is empty. Same idea as the doc registry."""
    try:
        automation_actions = automation()
    except Exception as exc:  # noqa: BLE001
        print("collect: ratchet skipped (%s)" % exc, file=sys.stderr)  # noqa: UP031
        return
    have = automation_actions._load()["items"].get(UNROUTED_AUTO_ID)
    title = "New Action Center source not registered: %s" % ", ".join(unregistered)  # noqa: UP031
    if unregistered and have and not have.get("closed") and have.get("title") == title:
        return  # same set, already open, nothing to rewrite
    if unregistered:
        automation_actions.raise_item(
            UNROUTED_AUTO_ID,
            title,
            "The collector saw candidates from a source ac-routing.json does not list. They still route by the "
            "defaults (anything a person addressed to the owner shows here), but the source needs a description "
            "and, if it should never reach the board, a routing rule.",
            "Add the source to the sources block of the routing file, or route it from an item with Route elsewhere.",
            priority="low",
            source="Action Center collector",
        )
    elif have and not have.get("closed"):
        automation_actions.close_item(UNROUTED_AUTO_ID, "every candidate source is registered")


if __name__ == "__main__":
    res = collect()
    rep = report(res)
    print(
        json.dumps(
            {k: rep[k] for k in ("counts", "considered", "context", "unregistered", "errors")},
            indent=2,
        )
    )
