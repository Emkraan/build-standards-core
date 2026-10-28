#!/usr/bin/env python3
"""
inbound_mail_gate.py

Purpose: Wake gate for the inbound mail monitor, the most expensive monitor job when it runs a model every tick. Pulls new mail,
         then decides with static rules whether anything in the batch needs a model.

TWO GATES:
  1. count == 0                       -> silent
  2. every new message is mechanical  -> silent

CRITICAL ORDERING NOTE: the puller ADVANCES ITS CHECKPOINT when it runs. If the gate pulls and then the agent pulls again, the agent
sees an empty mailbox and the batch is lost. So the gate pulls ONCE, writes the batch to a spool file, and the agent reads the spool
instead of re-running the puller. The spool is the handoff contract.

The scorer is a NOISE FILTER, never a decision maker: it keeps anything from a human, anything unrecognized, and anything with
urgency language (inbound_score.py).

Config (environment):
  GATE_MAIL_PULLER     JSON list: the command that pulls once and prints {"messages": [...], "checkpoint", "new_checkpoint"} (required;
                       without it the gate stays silent and says nothing)
  GATE_MAIL_SPOOL      the spool file (default <gate state dir>/mail-spool.json)
  GATE_MAIL_SENTINELS  JSON list of first line markers that mean the puller needs attention (default [MAIL-REAUTH-NEEDED], [MAIL-ERROR])
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
    run,
    should_drain,
    wake,
)
from inbound_score import triage  # noqa: E402


def _list(name, default):
    try:
        v = json.loads(os.environ.get(name) or "null")
    except ValueError:
        v = None
    return [str(x) for x in v] if isinstance(v, list) else default


NAME = "inbound-mail"
PULLER = _list("GATE_MAIL_PULLER", [])
SPOOL = os.environ.get("GATE_MAIL_SPOOL") or os.path.join(STATE_DIR, "mail-spool.json")
SENTINELS = tuple(_list("GATE_MAIL_SENTINELS", ["[MAIL-REAUTH-NEEDED]", "[MAIL-ERROR]"]))


def main():
    if not PULLER:
        gate_silent()
    # Clear PYTHONPATH: an inherited one from another runtime can poison the puller's own interpreter.
    rc, out, err = run(PULLER, timeout=300, env={"PYTHONPATH": ""})
    first = (out or "").strip().split("\n", 1)[0]

    # Sentinel lines are load bearing: the job must surface them, so wake.
    for marker in SENTINELS:
        if first.startswith(marker):
            wake(f"[MAIL GATE] Puller returned {marker}", out.strip()[:600])

    if rc != 0:
        detail = f"puller rc={rc} {(err or out)[:200]}"
        if failure_should_wake(NAME, detail):
            wake(
                "[MAIL GATE ALERT] The mail puller is failing.",
                f"Detail: {detail}",
                "Inbound mail is not being folded into state while this persists.",
            )
        gate_silent()

    try:
        data = json.loads(out)
    except Exception as exc:  # noqa: BLE001
        detail = f"unparseable puller output: {exc} :: {(out or '')[:200]}"
        if failure_should_wake(NAME, detail):
            wake("[MAIL GATE ALERT] Puller output is not JSON.", detail)
        gate_silent()

    clear_failures(NAME)
    messages = data.get("messages") or []
    harvest_inbound_files(messages, "mail")

    pulled_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # GATE 1: nothing new this tick. Even so, a non empty accumulation may be due for a scheduled drain, so fall through to the
    # drain check rather than returning immediately.
    keep, drop = [], []
    if messages:
        keep, drop, _ = triage(messages, "mail")

    # The batch is consumed either way; spool THIS tick so nothing is ever lost and a later run can see what was filtered.
    if messages:
        os.makedirs(os.path.dirname(SPOOL), exist_ok=True)
        payload = {
            "pulled_at": pulled_at,
            "checkpoint": data.get("checkpoint"),
            "new_checkpoint": data.get("new_checkpoint"),
            "total": len(messages),
            "kept": [m for m, _ in keep],
            "filtered": [
                {"subject": m.get("subject"), "from": m.get("from_addr"), "reason": r}
                for m, r in drop
            ],
        }
        with open(SPOOL, "w") as fh:
            json.dump(payload, fh, indent=2)
        os.chmod(SPOOL, 0o600)

    # Accumulate kept items (routine and urgent alike) so a wake folds the FULL backlog.
    entries, urgent = [], []
    for m, why in keep:
        e = dict(m)
        e["_why"] = why
        e["_kind"] = "mail"
        e["_pulled_at"] = pulled_at
        entries.append(e)
        if is_urgent_why(why):
            urgent.append(e)
    total_accum = accumulate(NAME, entries)

    # WAKE DECISION: an urgent item this tick wakes now; a scheduled drain hour with a backlog wakes to fold the routine batch;
    # otherwise silent and routine items wait in the accumulation.
    drain = should_drain() and total_accum > 0
    if not urgent and not drain:
        gate_silent()

    items, since = load_accumulated(NAME)
    reason = "URGENT item(s) in this batch" if urgent else "scheduled routine drain"
    lines = [
        f"[MAIL GATE] {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - waking to FOLD the {NAME} accumulation ({reason}).",
        "",
        f"{len(items)} item(s) accumulated since {since or '?'} across one or more pulls are awaiting a state fold. The puller "
        "checkpoint is already advanced; do NOT re-run the puller this tick.",
        "",
        "FOLD CONTRACT: classify and fold the accumulated items into the state files per the monitor's instructions, then CLEAR "
        f"the accumulation (delete {os.path.join(STATE_DIR, NAME + '-accumulated.json')}) so the next batch starts clean. The full "
        "item list (with _why triage tags) is in that file.",
    ]
    if urgent:
        lines.append("")
        lines.append("URGENT items driving this wake (fold these first):")
        for e in urgent[:15]:
            lines.append(
                f"- {e.get('received')} | {e.get('from_name') or e.get('from_addr')} | {(e.get('subject') or '')[:80]}  [{e.get('_why')}]"
            )
    wake(*lines)


if __name__ == "__main__":
    main()
