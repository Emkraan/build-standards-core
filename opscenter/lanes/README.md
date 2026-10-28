# Lane modules

Stdlib Python 3.9 modules the review and merge lanes share (opscenter/DESIGN.md section 12.3, items 1, 2, 6
and 24). They are lifted from the shell consumer's running ops center with every estate name removed; the
window table, the restricted systems and the zone are policy data, never code.

| Module | What it does | Tests |
|---|---|---|
| `maintenance_window.py` | Classifies a pull request as downtime (a deployable app that restarts on deploy, a plan that replaces or deletes a serving or data resource, or an unreadable plan, which fails closed), picks the change class (`standard`, `restricted` or `both`), and does the window math in UTC with DST handled per calendar date | `maintenance_window_test.py` |
| `merge_queue.py` | Puts a pull request into the main branch's merge queue and proves it got there (cancels a stale auto merge request, enqueues, re-reads, raises when it did not enter) | `merge_queue_test.py` |
| `gh_run_jobs.py` | Reads every job of a workflow run in pages of 50 with one retry on a 5xx, so every lane reads run jobs one way | `gh_run_jobs_test.py` |
| `freeze_gate.py` | Change freeze merge gate: reads the freeze windows, classifies the changed paths as deploying or quiet, answers MERGE_OK or HOLD (exit 0 or 10), fails closed | `freeze_gate_test.py` |
| `../testing/hermetic_home.py` | A throwaway HOME so a test never touches the real agent home or state tree | `hermetic_home_test.py` |

## Policy data (`maintenance_window` in the lane policy file)

| Key | Meaning |
|---|---|
| `timezone` (default `UTC`), `timezone_label` (default the zone name) | the zone the windows are written in and the word used in comments |
| `classes.<standard or restricted>.windows[]` | `{start_day, start, end}`; an `end` at or before `start` runs into the next day |
| `restricted_systems[]` | systems whose changes need the restricted window; a change with an unknown system waits for a window open to both |
| `restart_kinds`, `serving_types`, `restart_attrs`, `postgres_static_parameters`, `patch_types`, `extra_deploys[]`, `tier`, `stale_grace_minutes` | what counts as downtime; defaults are in the module |

`fixtures/maintenance-policy.json` is a complete example the tests read.

## Not lifted in this piece

The review lane engine, the own pull request lane and the plan gate call these modules and come in later
pieces; their tests that need the engine (hold in approve, enqueue inside the window, plan summary) come
with them.
