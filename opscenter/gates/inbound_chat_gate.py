#!/usr/bin/env python3
"""
inbound_chat_gate.py

Purpose: Wake gate for the inbound chat monitor. Pulls every configured chat source (a chat platform can have several surfaces,
         for example direct chats and channels, and a second platform can ride the same gate), then decides with static rules
         whether the batch needs a model.

Same two gates and the same checkpoint handoff contract as the mail gate: the puller advances its own checkpoint, so the gate pulls
once, spools the batch, and the agent reads the spool rather than re-pulling.

Monitoring channel traffic goes through the alert triage rather than a blanket channel drop, because such a channel carries real
signal. A persisted count baseline means a spike like "71 violations against an all time max of 2" survives the filter.

Config (environment):
  GATE_CHAT_SOURCES   JSON list of sources, none means the gate stays silent:
                      [{"name": "chat", "cmds": [["pull", "--fetch"], ["pull", "--channels"]], "kind": "chat",
                        "sentinels": ["[CHAT-REAUTH-NEEDED]"], "fix": "text shown when a sentinel appears", "optional": false}]
                      Each command prints {"messages": [...]}; exit code 3 means another pull holds the lock (an empty batch).
                      An optional source failing never blocks the others; it alerts with backoff like any connector error.
  GATE_CHAT_SPOOL, GATE_CHAT_BASELINE   the spool and the alert baseline (defaults under the gate state dir)
  GATE_STATE_DIR, GATE_DRAIN_HOURS (gatelib.py), INBOUND_SCORE_CONFIG (inbound_score.py)
"""

import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gatelib import (  # noqa: E402
    STATE_DIR,
    accumulate,
    clear_failures,
    failure_should_wake,
    gate_silent,
    harvest_inbound_files,
    is_urgent_why,
    load_accumulated,
    load_json_file,
    run,
    should_drain,
    wake,
)
from inbound_score import triage  # noqa: E402


def _sources():
    try:
        v = json.loads(os.environ.get("GATE_CHAT_SOURCES") or "null")
    except ValueError:
        v = None
    out = []
    for s in v if isinstance(v, list) else []:
        if isinstance(s, dict) and s.get("name") and isinstance(s.get("cmds"), list):
            out.append(s)
    return out


NAME = "inbound-chat"
SPOOL = os.environ.get("GATE_CHAT_SPOOL") or os.path.join(STATE_DIR, "chat-spool.json")
BASELINE = os.environ.get("GATE_CHAT_BASELINE") or os.path.join(
    STATE_DIR, "chat-alert-baseline.json"
)


def pull(cmd, sentinels):
    """(data, error, raw): the parsed batch, or None and what went wrong. A sentinel first line is returned as the error."""
    rc, out, err = run([str(a) for a in cmd], timeout=300, env={"PYTHONPATH": ""})
    first = (out or "").strip().split("\n", 1)[0]
    for marker in sentinels:
        if first.startswith(marker):
            return None, marker, out
    if rc == 3:
        return {"messages": []}, None, out  # another pull holds the lock
    if rc != 0:
        return None, f"rc={rc} {(err or out)[:200]}", out
    try:
        return json.loads(out), None, out
    except Exception as exc:  # noqa: BLE001
        return None, f"unparseable: {exc} :: {(out or '')[:200]}", out


def pull_source(src):
    """(messages, errors, sentinel_hit, raw) for one source: every command is run, a source fails only when all of them do."""
    sentinels = [str(s) for s in src.get("sentinels") or []]
    msgs, errors, raws, ok = [], [], [], 0
    for cmd in src["cmds"]:
        data, err, raw = pull(cmd, sentinels)
        raws.append(raw)
        if err in sentinels:
            return [], [err], err, raw
        if data is None:
            errors.append(err)
            continue
        ok += 1
        msgs.extend(data.get("messages") or [])
    for m in msgs:
        m.setdefault("_kind", src.get("kind") or src["name"])
    return (msgs if ok else None), errors, None, "".join(raws)


def main():
    sources = _sources()
    if not sources:
        gate_silent()

    messages, any_ok, failed = [], False, []
    for src in sources:
        name = "inbound-" + src["name"]
        msgs, errors, sentinel, raw = pull_source(src)
        if sentinel:
            wake(
                f"[CHAT GATE] Puller for {src['name']} returned {sentinel}",
                str(
                    src.get("fix")
                    or "Fix the puller's sign in, then the next tick folds the backlog."
                ),
                (raw or "").strip()[:400],
            )
        if msgs is None:
            detail = f"{src['name']}: " + " | ".join(errors)
            should = failure_should_wake(name, detail)
            if src.get("optional"):
                if should:
                    wake(
                        f"[CHAT GATE ALERT] The optional source {src['name']} is failing.",
                        f"Detail: {detail}",
                        "The other sources are unaffected.",
                    )
            else:
                failed.append((detail, should))
            continue
        clear_failures(name)
        any_ok = True
        if src.get("harvest_files", True):
            harvest_inbound_files(msgs, src.get("kind") or src["name"])
        messages.extend(msgs)

    if not any_ok:
        alerts = [d for d, should in failed if should]
        if alerts:
            wake("[CHAT GATE ALERT] Every chat source is failing.", *alerts)
        gate_silent()

    pulled_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # GATE 1: nothing new this tick. A non empty accumulation may still be due for a scheduled drain, so fall through.
    keep, drop = [], []
    baseline = load_json_file(BASELINE, {})
    if messages:
        keep, drop, new_baseline = triage(messages, "chat", baseline)
        os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
        with open(BASELINE, "w") as fh:
            json.dump(new_baseline, fh, indent=2)

        os.makedirs(os.path.dirname(SPOOL), exist_ok=True)
        with open(SPOOL, "w") as fh:
            json.dump(
                {
                    "pulled_at": pulled_at,
                    "total": len(messages),
                    "kept": [m for m, _ in keep],
                    "filtered": [
                        {
                            "from": m.get("from_name"),
                            "channel": m.get("channel"),
                            "text": (m.get("text") or "")[:120],
                            "reason": r,
                        }
                        for m, r in drop
                    ],
                },
                fh,
                indent=2,
            )
        os.chmod(SPOOL, 0o600)

    # Accumulate kept items so a wake folds the FULL backlog.
    entries, urgent = [], []
    for m, why in keep:
        e = dict(m)
        e["_why"] = why
        e["_kind"] = m.get("_kind") or "chat"
        e["_pulled_at"] = pulled_at
        entries.append(e)
        if is_urgent_why(why):
            urgent.append(e)
    total_accum = accumulate(NAME, entries)

    # WAKE DECISION: urgent now, else scheduled routine drain, else silent.
    drain = should_drain() and total_accum > 0
    if not urgent and not drain:
        gate_silent()

    items, since = load_accumulated(NAME)
    reason = "URGENT item(s) in this batch" if urgent else "scheduled routine drain"
    lines = [
        f"[CHAT GATE] {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - waking to FOLD the {NAME} accumulation ({reason}).",
        "",
        f"{len(items)} item(s) accumulated since {since or '?'} across one or more pulls are awaiting a state fold. The puller "
        "checkpoints are already advanced; do NOT re-run the pullers this tick. Items carry _kind (the source).",
        "",
        "FOLD CONTRACT: classify and fold the accumulated items into the state files per the monitor's instructions, then CLEAR "
        f"the accumulation (delete {os.path.join(STATE_DIR, NAME + '-accumulated.json')}) so the next batch starts clean. The full "
        "item list (with _why triage tags) is in that file.",
    ]
    if urgent:
        lines.append("")
        lines.append("URGENT items driving this wake (fold these first):")
        for e in urgent[:15]:
            where = f"{e.get('_kind')} " + (e.get("channel") or "chat")
            lines.append(
                f"- {e.get('created')} | {e.get('from_name')} in {where} | {(e.get('text') or e.get('subject') or '')[:80]}  [{e.get('_why')}]"
            )
    wake(*lines)


if __name__ == "__main__":
    main()
