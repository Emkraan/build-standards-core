#!/usr/bin/env python3
"""
action_center_gate.py

Purpose: Wake gate for the Action Center analysis cron.
         Builds the same analysis bundle the job reads, hashes it (minus the
         generated_utc stamp), and skips the agent when nothing in the bundle
         changed since the last successful analysis. Lets the job run on a
         15-minute cadence at roughly the cost of the old hourly one.

Wake rules:
  - material bundle hash differs from the last analyzed hash -> wake, at most
    once per 30 min
  - only ambient chatter changed (group chats, channels, FYI mail in
    candidates_context) -> wake once the last analysis is 2 h old
  - last wake did not produce a fresh action-center.json within 20 min -> wake
    again (the agent failed; do not let a failed run hide the change)
  - first tick of the day -> wake (forced daily audit)
  - the last analysis was rejected by the engine (contract.py, the item contract) -> the
    board kept its last good file, so retry after 20 min like a missing output, but after 3
    rejections in a row at most every 4 h (backoff), and say what was wrong in the wake text
  - bundle build fails -> fail open with backoff (wake on 3rd failure, then at most every 4h),
    since a silent gate would freeze the Action Center. The woken job rebuilds with the same
    builder the gate uses (analysis_bundle.py, one build path with two callers). On that same
    3rd failure (then every 4h) the gate also raises one Action Center item (automation_actions,
    auto-ac-gate-bundle), closed when a build succeeds again.

Read-only against the ops center state. Writes only its own health and state files under the gate state dir
(GATE_STATE_DIR), the bundle at <gate state dir>/analysis-bundle.json (the same path the job's first step
writes, so the agent may reuse it), the must-consider cids of the run it wakes (action-center-wake.json, which the
engine's contract check reads) and, on a build failure, the one Action Center report item.
Always exits 0; signals only through stdout.

Test hooks: GATE_BUNDLE_JSON (use this file instead of building the bundle),
GATE_AC_JSON (action-center.json path), GATE_STATE (state file path), GATE_PY (the python that runs the
builder and the report CLI, default this python), GATE_CONTRACT_STATE (the engine's ac-contract-state.json
path), GATE_WAKE_PATH (the wake snapshot path), GATE_MIN_GAP_S, GATE_CHATTER_MAX_AGE_S. Paths follow
OPSCENTER_ROOT and OPSCENTER_STATE_DIR (paths.py).
"""

import datetime
import fnmatch
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gatelib import (  # noqa: E402
    STATE_DIR,
    audit_due,
    clear_failures,
    failure_should_wake,
    gate_silent,
    mark_audit,
    run,
    wake,
)

NAME = "action-center"
ROOT = os.environ.get("OPSCENTER_ROOT") or os.path.expanduser("~/.opscenter")
OPS_STATE = os.environ.get("OPSCENTER_STATE_DIR") or os.path.join(ROOT, "state")
PY = os.environ.get("GATE_PY") or sys.executable
BUNDLER = os.path.join(os.path.dirname(HERE), "engine", "analysis_bundle.py")
BUNDLE_OUT = os.path.join(STATE_DIR, "analysis-bundle.json")
AC_JSON = os.environ.get("GATE_AC_JSON") or os.path.join(
    OPS_STATE, "dashboard", "action-center.json"
)
STATE = os.environ.get("GATE_STATE") or os.path.join(STATE_DIR, "action-center-state.json")
CONTRACT_STATE = os.environ.get("GATE_CONTRACT_STATE") or os.path.join(
    OPS_STATE, "dashboard", "ac-contract-state.json"
)
WAKE_PATH = os.environ.get("GATE_WAKE_PATH") or os.path.join(STATE_DIR, "action-center-wake.json")
REPORT_CLI = os.path.join(os.path.dirname(HERE), "server", "modules", "automation_actions.py")
REPORT_ID = "ac-gate-bundle"
REJECT_BACKOFF_AFTER = 3
REJECT_COOLDOWN_S = 4 * 3600
RETRY_AFTER_S = 20 * 60
# Cost cap: at most one analysis per 30 min even when the bundle keeps moving,
# so a busy afternoon cannot cost more than 2x the old hourly cadence.
MIN_GAP_S = int(os.environ.get("GATE_MIN_GAP_S", 30 * 60))
GAP_SLACK_S = 60
# Context sources that are ambient chatter, not routed to the analysis as must-act items (globs over the source id,
# so every chat feed prefix is covered).
CHATTER_SOURCES = ("mail.other", "*.group", "*.channel")
CHATTER_MAX_AGE_S = int(os.environ.get("GATE_CHATTER_MAX_AGE_S", 2 * 3600))
ENV = {"OPSCENTER_ROOT": ROOT, "OPSCENTER_STATE_DIR": OPS_STATE}


def load_state():
    try:
        with open(STATE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(st, fh)
    os.replace(tmp, STATE)


def load_contract_state():
    try:
        with open(CONTRACT_STATE) as fh:
            st = json.load(fh)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def save_wake_snapshot(raw, woke_at):
    """The cids the job must consider this run, for the engine's coverage check. Written only
    when the job is woken, so a later tick that only rebuilds the bundle cannot move it."""
    try:
        data = json.loads(raw)
        cids = [
            str(c["cid"])
            for c in data.get("candidates_must") or []
            if isinstance(c, dict) and c.get("cid")
        ]
        os.makedirs(os.path.dirname(WAKE_PATH), exist_ok=True)
        tmp = WAKE_PATH + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"woke_at": woke_at, "must_cids": cids}, fh)
        os.replace(tmp, WAKE_PATH)
    except (OSError, ValueError, AttributeError):
        pass


def report_bundle_failure(err):
    """Raise (or update) the one Action Center item that says the bundle build is failing."""
    rc, out, e = run(
        [
            PY,
            REPORT_CLI,
            "raise",
            "--id",
            REPORT_ID,
            "--title",
            "The Action Center analysis is not running, its input bundle will not build",
            "--why",
            "The wake gate could not build the analysis bundle, so it skipped the job and the board is on its last good analysis. Error: %s"  # noqa: UP031
            % (err or "")[:300],
            "--action",
            "Run engine/analysis_bundle.py by hand to see the failure. This item closes itself when the gate builds a bundle again.",
            "--source",
            "Action Center gate",
        ],
        timeout=60,
        env=ENV,
    )
    return rc == 0


def close_bundle_report():
    run(
        [
            PY,
            REPORT_CLI,
            "close",
            "--id",
            REPORT_ID,
            "--reason",
            "The gate built the bundle again.",
        ],
        timeout=60,
        env=ENV,
    )


def build_bundle():
    override = os.environ.get("GATE_BUNDLE_JSON")
    if override:
        try:
            with open(override) as fh:
                return fh.read(), None
        except OSError as exc:
            return None, "override read: %s" % exc  # noqa: UP031
    rc, out, err = run([PY, BUNDLER], timeout=120, env=ENV)
    if rc != 0 or not out.strip():
        return None, "bundle rc=%s %s" % (rc, (err or out)[:200])  # noqa: UP031
    return out, None


def is_chatter(source):
    return any(fnmatch.fnmatch(str(source or ""), g) for g in CHATTER_SOURCES)


def split_chatter(data):
    """Move ambient chatter out of candidates_context. Group chats,
    channels and FYI mail changed the hash on every 30 min tick, so the analysis woke
    about 121 of 124 times. The analysis only folds that chatter into items, so it is
    hashed apart and only forces a refresh once the last analysis is CHATTER_MAX_AGE_S old.
    Returns the chatter list (sorted by cid, so arrival order is not signal)."""
    ctx = data.get("candidates_context")
    if not isinstance(ctx, list):
        return []
    keep, chatter = [], []
    for c in ctx:
        (chatter if isinstance(c, dict) and is_chatter(c.get("source")) else keep).append(c)
    data["candidates_context"] = keep
    return sorted(str(c.get("cid") or c.get("title")) for c in chatter)


def content_hash(raw):
    """Returns (material hash, chatter hash)."""
    data = json.loads(raw)
    chatter = split_chatter(data)
    data.pop("generated_utc", None)
    data.pop("now_et", None)  # clock stamp for the analysis, not signal
    # The owner's own previous synthesis (carried forward for the analysis) changes every time the
    # job writes; hashing it would make each run wake the next one.
    data.pop("previous_items", None)
    # Live ref lookups can fail transiently. Only the finished set is signal.
    if isinstance(data.get("ref_status"), dict):
        data["ref_status"].pop("errors", None)
    # Collector adapter errors are transient, like ref lookups.
    data.pop("collector_errors", None)
    material = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]
    return material, hashlib.sha256(json.dumps(chatter).encode()).hexdigest()[:16]


def main():
    today = datetime.date.today().isoformat()
    raw, err = build_bundle()
    if raw is None:
        if failure_should_wake(NAME, err):
            report_bundle_failure(err)
            wake(
                "ACTION-CENTER GATE: bundle build failing (%s). Run the bundle step yourself and report the error if it persists."  # noqa: UP031
                % err
            )
        gate_silent()
    try:
        h, chatter_h = content_hash(raw)
    except ValueError as exc:
        if failure_should_wake(NAME, "bundle not JSON: %s" % exc):  # noqa: UP031
            report_bundle_failure("bundle output was not valid JSON (%s)" % exc)  # noqa: UP031
            wake(
                "ACTION-CENTER GATE: bundle output was not valid JSON (%s). Run the bundle step yourself."  # noqa: UP031
                % exc
            )
        gate_silent()
    if clear_failures(NAME):
        close_bundle_report()
    if not os.environ.get("GATE_BUNDLE_JSON"):
        try:
            with open(BUNDLE_OUT, "w") as fh:
                fh.write(raw)
        except OSError:
            # As before: a failed write never skips a run. The job's bundle step rebuilds a missing or
            # invalid bundle with the same builder.
            pass

    st = load_state()
    now = time.time()
    try:
        ac_mtime = os.path.getmtime(AC_JSON)
    except OSError:
        ac_mtime = 0

    contract = load_contract_state()
    streak = int(contract.get("streak") or 0) if contract.get("status") == "rejected" else 0
    # A rejected file is swapped for the last good one (same modification time), so it reads here
    # as a run that wrote nothing. After 3 in a row the retry backs off to once per 4 h.
    retry_after = RETRY_AFTER_S if streak < REJECT_BACKOFF_AFTER else REJECT_COOLDOWN_S
    reason = None
    if (
        st.get("woke_hash")
        and st.get("woke_at", 0) > ac_mtime
        and now - st["woke_at"] >= retry_after
    ):
        reason = "previous analysis at %s did not write action-center.json; retrying" % (  # noqa: UP031
            time.strftime("%H:%M", time.localtime(st["woke_at"]))
        )
        if streak:
            reason = (
                "previous analysis at %s was rejected by the engine (%d in a row: %s); retrying"  # noqa: UP031
                % (
                    time.strftime("%H:%M", time.localtime(st["woke_at"])),
                    streak,
                    "; ".join(str(e) for e in (contract.get("errors") or [])[:3]),
                )
            )
    # woke_at lands a few seconds after the tick starts, so a strict 30 min gap
    # always missed the tick 30 min later and silently made it 45 (10/12).
    elif h != st.get("woke_hash") and now - st.get("woke_at", 0) >= MIN_GAP_S - GAP_SLACK_S:
        reason = "bundle changed since last analysis"
    elif (
        chatter_h != st.get("woke_chatter")
        and now - st.get("woke_at", 0) >= CHATTER_MAX_AGE_S - GAP_SLACK_S
    ):
        reason = "only background chatter changed, last analysis is over %d h old" % (  # noqa: UP031
            CHATTER_MAX_AGE_S // 3600
        )
    elif audit_due(NAME, today):
        reason = "daily audit run"

    if not reason:
        gate_silent()

    if audit_due(NAME, today):
        mark_audit(NAME, today)
    st.update({"woke_hash": h, "woke_chatter": chatter_h, "woke_at": now, "reason": reason})
    save_state(st)
    save_wake_snapshot(raw, now)
    wake(
        "ACTION-CENTER GATE: waking because %s (bundle %s). "  # noqa: UP031
        "The fresh bundle is ALREADY at %s; you may skip rebuilding it in the bundle step."
        % (reason, h, BUNDLE_OUT)
    )


if __name__ == "__main__":
    main()
