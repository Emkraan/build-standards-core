#!/usr/bin/env bash
# =====================================================================
# tfplan-fastpass.sh
# Purpose: Every-minute fast pass of the plan gate (run it from a service manager with a 60 second interval).
#          A scheduler tick can land late and a pass can end past the minute, so a "* * * * *" job may
#          still run only every 2 minutes. This pass approves ordinary plans, holds and queues the rest,
#          and cancels superseded runs exactly like the scheduled pass. TFGATE_PASS_ONLY=1 keeps it from
#          stamping assessment wakes or touching the health counters, so the scheduled pass still wakes
#          the agent for assessments and owns the alerts. A pass already running holds the gate lock and
#          this one skips.
# Log:     $TFGATE_FASTPASS_LOG (default ~/.opscenter/logs/tfplan-fastpass.log), failures only
# =====================================================================
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="${TFGATE_FASTPASS_LOG:-$HOME/.opscenter/logs/tfplan-fastpass.log}"
ERR="$(TFGATE_PASS_ONLY=1 "$(command -v python3)" "$HERE/tfplan_gate.py" 2>&1 >/dev/null)"
if [ -n "$ERR" ]
then
  mkdir -p "$(dirname "$LOG")"
  printf '== %s\n%s\n' "$(date -u +%FT%TZ)" "$ERR" >>"$LOG"
fi
exit 0
