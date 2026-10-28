#!/usr/bin/env bash
# =====================================================================
# tfplan-gate.sh
# Purpose: Wake gate for the plan gate job (opscenter/DESIGN.md section 12.3, item 9). Auto-approves ordinary
#          pull request infrastructure plan runs that wait on the plan environment, and HOLDS pull requests that
#          change how the pipeline works (workflows, the owners file, the exclusions list, or plan-time
#          code and network constructs) in <state>/tf-review/queue.json for the owner's review. Wakes the
#          agent only to write a private assessment for a held PR and sha that has none. The logic is in
#          tfplan_gate.py next to this script (policy lists at its top). Fails closed with a health
#          counter and backoff.
#
# Wake-gate contract:
#   - last stdout line {"wakeAgent": false}  -> agent is skipped
#   - anything else                          -> agent wakes, stdout injected
#   - this script ALWAYS exits 0.
#
# Config (env): TFGATE_REPO, TFGATE_ENV_NAME, TFGATE_SELF_LOGIN, TFGATE_STATE_DIR, TFGATE_CACHE_DIR,
#               TFGATE_GH_BIN, TFGATE_DRY_RUN=1 (never POST an approval)
# =====================================================================
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3)"

OUT="$("$PY" "$HERE/tfplan_gate.py" 2>&1)"
RC=$?
if [ $RC -ne 0 ] || [ -z "$OUT" ]; then
    # The Python side handles code host failures itself; reaching here means the interpreter itself
    # broke. Nothing was approved. Stay quiet; the job output log keeps the traceback.
    printf '%s\n' "$OUT" | tail -5 >&2
    echo '{"wakeAgent": false}'
    exit 0
fi
printf '%s\n' "$OUT"
exit 0
