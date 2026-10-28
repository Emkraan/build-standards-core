#!/usr/bin/env python3
"""
inbound_score.py

Purpose: Deterministic triage for the inbound monitors. Decides whether a batch of new mail or chat messages contains anything a
         model needs to look at, so the monitor jobs stop paying full agent cost to conclude "routine noise".

DESIGN RULE: this is a NOISE FILTER, not a decision maker. It only ever drops traffic that is provably mechanical (a known
automated sender emitting a known routine subject shape). Anything from a human, anything unrecognized, and anything carrying
urgency language is KEPT and handed to the agent. When in doubt it keeps. A false keep costs one agent run; a false drop loses a
signal, so the asymmetry is deliberate. With no configuration the scorer therefore drops only the owner's own messages and bot
senders the config names: everything else is kept.

Configuration: one JSON file, INBOUND_SCORE_CONFIG, every key optional (an unreadable file means the defaults):
  mechanical_senders   addresses whose ROUTINE output is mechanical. Being listed is not enough to drop a message: its subject must
                       also match a pattern in routine_subjects
  routine_subjects     regexes for routine subject shapes, matched only for mechanical senders
  urgent_patterns      extra regexes that ALWAYS keep a message, on top of the built in urgency words
  ticket_regex         a ticket or incident reference that counts as urgent (default none)
  downgrades           [{"sender": addr, "subject": regex, "reason": text}, ...]: an urgent hit from that sender with that subject
                       becomes a non urgent keep with the reason (timing only: still kept, folded on the next drain)
  hard_fail            regex of subjects a downgrade never applies to (default run, build, deploy or pipeline failed)
  self_names           display names of the owner: their own chat messages carry no inbound signal
  bot_senders          chat sender names that are bots
  noise_channels       chat channels that carry monitoring alerts (routed through the alert triage)
  recorder_regex       chat senders that are meeting recorders (default notetaker, recorder, otter, fireflies, read.ai)
"""

import json
import os
import re


def _config():
    path = os.environ.get("INBOUND_SCORE_CONFIG")
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def _rx(items, flags=re.I):
    out = []
    for p in items or []:
        try:
            out.append(re.compile(str(p), flags))
        except re.error:
            continue
    return out


CFG = _config()
MECHANICAL_SENDERS = {str(s).lower() for s in CFG.get("mechanical_senders") or []}
ROUTINE_SUBJECTS = _rx(CFG.get("routine_subjects"))
DOWNGRADES = [d for d in CFG.get("downgrades") or [] if isinstance(d, dict)]
HARD_FAIL = re.compile(
    str(
        CFG.get("hard_fail")
        or r"\b(run failed|build failed|deploy(ment)? failed|pipeline failed)\b"
    ),
    re.I,
)
SELF_NAMES = {str(n).lower().strip() for n in CFG.get("self_names") or []}
BOT_SENDERS = {str(n).lower().strip() for n in CFG.get("bot_senders") or []}
NOISE_CHANNELS = {str(n).lower().strip() for n in CFG.get("noise_channels") or []}
RECORDER = re.compile(
    str(CFG.get("recorder_regex") or r"notetaker|recorder|read\.ai|otter\.ai|fireflies"), re.I
)

# Anything matching these ALWAYS goes to the agent, overriding every drop rule.
URGENT = [
    re.compile(
        r"\b(P1|P2|priority[- ]?1|sev[- ]?[12]|urgent|outage|incident|major incident|escalat|breach|compromis|degraded|down)\b",
        re.I,
    ),
    re.compile(r"\b(freeze|change freeze|emergency change)\b", re.I),
    re.compile(r"\b(run failed|build failed|deploy(ment)? failed|pipeline failed)\b", re.I),
    re.compile(r"\b(access denied|cannot access|can.t access|no access|locked out)\b", re.I),
]
URGENT += _rx(CFG.get("urgent_patterns"))
if CFG.get("ticket_regex"):
    URGENT += _rx([CFG["ticket_regex"]], 0)

# A monitoring alert line looks like "<name> | Status: Firing Resource: ..." (the shape is the alert source's, kept as data).
ALERT_RE = re.compile(
    str(
        CFG.get("alert_regex")
        or r"^\W*(?P<name>[^|]+?)\s*\|\s*Status:\s*(?P<status>Firing|Resolved)"
    ),
    re.I,
)
# A count inside the alert body, e.g. "71 error(s) detected" / "1 error(s)".
ALERT_COUNT_RE = re.compile(r"(\d+)\s+(?:error|violation|failure)s?\b", re.I)


def parse_alert(text):
    """Return (name, status, count) for a monitoring alert, else (None, None, None)."""
    if not text:
        return None, None, None
    m = ALERT_RE.match(text.strip())
    if not m:
        return None, None, None
    cm = ALERT_COUNT_RE.search(text)
    count = int(cm.group(1)) if cm else None
    return m.group("name").strip(), m.group("status").lower(), count


def triage_alerts(messages, baseline=None, spike_factor=5, spike_floor=10):
    """Classify a batch of monitoring channel alerts.

    Drops only self healing flap: a Firing that has a matching Resolved in the same batch, whose count is within normal range for
    that alert name.

    Keeps:
      - an alert name never seen before (novel failure mode)
      - a Firing with no Resolved in the batch (still broken)
      - any count that spikes past spike_factor x the recorded max for that alert, or past spike_floor when there is no history

    baseline is a dict {alert_name: max_count_seen}, persisted by the caller, so "71 when the all time max was 2" is caught.
    """
    baseline = baseline or {}
    resolved_names = set()
    parsed = []
    for m in messages:
        name, status, count = parse_alert(m.get("text") or m.get("subject") or "")
        parsed.append((m, name, status, count))
        if name and status == "resolved":
            resolved_names.add(name)

    keep, drop, new_baseline = [], [], dict(baseline)
    for m, name, status, count in parsed:
        if not name:
            keep.append((m, "unparseable-alert"))
            continue
        prev_max = baseline.get(name)
        if count is not None:
            new_baseline[name] = max(count, prev_max or 0)

        if prev_max is None:
            keep.append((m, f"novel-alert:{name[:40]}"))
            continue
        if count is not None:
            threshold = max(prev_max * spike_factor, spike_floor)
            if count > threshold:
                keep.append((m, f"count-spike:{name[:30]} {count}>{threshold}"))
                continue
        if status == "firing" and name not in resolved_names:
            keep.append((m, f"firing-unresolved:{name[:40]}"))
            continue
        drop.append((m, "self-healing-flap"))
    return keep, drop, new_baseline


def _downgrade_mail(sender, subject):
    """A non urgent keep reason when an urgent hit is a known echo the config names, else None. Never for a hard failure."""
    if HARD_FAIL.search(subject):
        return None
    for d in DOWNGRADES:
        if str(d.get("sender", "")).lower() != sender:
            continue
        try:
            if re.search(str(d.get("subject") or ""), subject, re.I):
                return str(d.get("reason") or "echo-batched")
        except re.error:
            continue
    return None


def _text(msg, *fields):
    return " ".join(str(msg.get(f) or "") for f in fields)


def score_mail(msg):
    """Return (keep: bool, reason: str) for one mail item."""
    sender = (msg.get("from_addr") or "").lower().strip()
    subject = msg.get("subject") or ""
    body = _text(msg, "subject", "preview")

    for pat in URGENT:
        if pat.search(body):
            why = f"urgent-signal:{pat.pattern[:34]}"
            return True, _downgrade_mail(sender, subject) or why

    if str(msg.get("importance", "")).lower() == "high":
        return True, "flagged-high-importance"

    if sender in MECHANICAL_SENDERS:
        for pat in ROUTINE_SUBJECTS:
            if pat.search(subject):
                return False, "mechanical-routine"
        return True, "known-sender-but-unrecognized-subject"

    # A human, a vendor, or any sender without a rule: always keep.
    return True, "human-or-unknown-sender"


def score_chat(msg):
    """Return (keep: bool, reason: str) for one chat item."""
    frm = (msg.get("from_name") or "").lower().strip()
    channel = (msg.get("channel") or "").lower().strip()
    body = _text(msg, "subject", "text")

    # The owner's own messages carry no inbound signal, even when they mention a ticket or a freeze.
    if frm in SELF_NAMES:
        return False, "self-authored"
    # Meeting recorder bots announce themselves in meeting chats; not a human.
    if RECORDER.search(frm):
        return False, "bot-sender"

    for pat in URGENT:
        if pat.search(body):
            return True, "urgent-signal"

    if channel in NOISE_CHANNELS:
        return False, "monitoring-channel"
    if frm in BOT_SENDERS:
        return False, "bot-sender"
    return True, "human-message"


score_teams = score_chat  # the old name, kept for a consumer's own scripts


def triage(messages, kind="mail", alert_baseline=None):
    """Split a batch. Returns (keep, drop, new_baseline).

    Monitoring channel traffic is routed through triage_alerts so a novel or spiking alert survives, while self healing flap is
    dropped. kind is "mail" or "chat" ("teams" is accepted for the old name).
    """
    if kind == "mail":
        keep, drop = [], []
        for m in messages:
            ok, why = score_mail(m)
            (keep if ok else drop).append((m, why))
        return keep, drop, dict(alert_baseline or {})

    alerts = [m for m in messages if (m.get("channel") or "").lower() in NOISE_CHANNELS]
    rest = [m for m in messages if (m.get("channel") or "").lower() not in NOISE_CHANNELS]

    keep, drop = [], []
    for m in rest:
        ok, why = score_chat(m)
        (keep if ok else drop).append((m, why))

    akeep, adrop, new_baseline = triage_alerts(alerts, alert_baseline)
    keep.extend(akeep)
    drop.extend(adrop)
    return keep, drop, new_baseline
