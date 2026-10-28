# Wake gates

Scheduled gate scripts (opscenter/DESIGN.md sections 2.6 and 12.3, items 21, 22 and 24). Each runs on the
scheduler, does its read with no model call, and wakes the agent only when there is something to do; an idle
tick costs nothing. Stdlib Python 3.9. Paths and tools are environment variables or arguments, never literals.

Wake gate contract: the last stdout line `{"wakeAgent": false}` skips the agent; anything else wakes it with
stdout as context. The scheduler honours a gate only when it exits 0, so a gate always exits 0. A gate that
guards a mutating job fails open (it wakes the agent with the error); a connector failure backs off through the
health file instead (wake on the Nth consecutive failure, then once per cooldown).

| Module | What it does | Config | Tests |
|---|---|---|---|
| `gatelib.py` | The contract in one place: `gate_silent`, `wake`, failure backoff with a health file, daily audit marker, the accumulate and drain model for inbound monitors (wake now only for an urgent item, otherwise drain at set hours), a subprocess helper that never raises, an env file reader, and the inbound files store hook | `GATE_STATE_DIR`, `GATE_DRAIN_HOURS`, `GATE_ENV_FILE` | `gatelib_test.py` |
| `cron_catalog_gate.py` | Wakes the model only when an enabled scheduled job has a name outside `<Area> - <what it does>` or no catalog description | `CRON_CATALOG_TOOL` | `cron_catalog_gate_test.py` |
| `proposal_rewrite_gate.py` | Claims each docs proposal the owner sent back and wakes the rewrite agent; a claim older than 20 minutes is re-offered | `OPSCENTER_STATE_DIR` | `proposal_rewrite_gate_test.py` |
| `sprint_close_gate.py` | Runs the sprint evidence scanner and wakes only on new evidence for an open ticket or an unapplied Needs me answer | `SPRINT_CLOSE_SCANNER`, `OPSCENTER_STATE_DIR` | `sprint_close_gate_test.py` |
| `plans_reconcile_gate.py` | Wakes for a plan tracker that is a skeleton or Behind (once per fingerprint, then one retry), adopts the work ticket linked to an intake, archives finished trackers | `OPSCENTER_PORT`, `OPSCENTER_STATE_DIR`, `PLANS_TRACKER_DRIVER`, `TRACKER_SITE`, `PLANS_INTAKE_TYPE` | `plans_reconcile_gate_test.py` |
| `sitrep.py` | The one daily message for the owner, no agent and no model call: what waits on the owner, read from the endpoints the sidebar badges use (Action Center items not handled or snoozed, review counts, builds waiting, knowledge, infrastructure problems, unacknowledged alerts and failing jobs). Exit 1 when the ops center cannot be read, so a dead ops center is never silent | `OPSCENTER_URL` or `OPSCENTER_PORT`, `SITREP_REVIEWS` | `sitrep_test.py` |
| `sitrep_prerun.py` | The pre-run block for an agent written morning brief: the consumer's health command first, then open Action Center items, what was resolved or ignored in the last 72 hours, and an optional live check of the references the state files and items name | `SITREP_HEALTH_CMD`, `SITREP_STATE_FILES`, `SITREP_REF_STATUS` | `sitrep_test.py` |
| `retro_row_gate.py` | Wake gate for the retro row drafter: runs `tracker/retro_row.py scan` and wakes the agent only when the owner's row on the newest retro page is blank and no draft exists; a failing scan backs off (an alert on the third failure, then daily) | the tracker parameters | `retro_row_gate_test.py` (2) |

The scanner, the catalog tool and the tracker driver are slot code the consumer supplies; the gates call them as
subprocesses and treat a failure as a failure, never as nothing to do. `gatehelp.py` is test support.
