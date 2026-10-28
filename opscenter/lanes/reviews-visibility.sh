#!/bin/bash
# =====================================================================
# reviews-visibility.sh
# Purpose: Scheduler entry for the reviews visibility check (opscenter/DESIGN.md section 12.3, item 24). The scheduler decides the
#          cadence (the running one fires every 30 minutes in working hours and once at night). Findings go to the board, so the job
#          is silent on a steady pass and always exits 0. reviews_visibility.py exits 2 when it cannot read the ops center, which is
#          logged here and raised as a board item after three failures in a row.
# Config:  RV_LANES, RV_BASE, RV_SELF_LOGIN, RV_OWN_CHECK and the rest in reviews_visibility.py; RV_LOG (default
#          ~/.opscenter/logs/reviews-visibility.log)
# =====================================================================
LOG="${RV_LOG:-$HOME/.opscenter/logs/reviews-visibility.log}"
mkdir -p "$(dirname "$LOG")"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out=$("$(command -v python3)" "$HERE/reviews_visibility.py" 2>&1)
rc=$?
if [ -n "$out" ]
then
  printf '== %s rc=%s\n%s\n' "$(date -u +%FT%TZ)" "$rc" "$out" >>"$LOG"
fi
exit 0
