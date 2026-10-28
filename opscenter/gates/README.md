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

The scanner, the catalog tool and the tracker driver are slot code the consumer supplies; the gates call them as
subprocesses and treat a failure as a failure, never as nothing to do. `gatehelp.py` is test support.
