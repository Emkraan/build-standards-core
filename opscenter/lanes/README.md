# Lane modules

Stdlib Python 3.9 modules the review and merge lanes share (opscenter/DESIGN.md section 12.3, items 1, 2, 6
and 24). They are lifted from the shell consumer's running ops center with every estate name removed; the
window table, the restricted systems and the zone are policy data, never code.

| Module | What it does | Tests |
|---|---|---|
| `maintenance_window.py` | Classifies a pull request as downtime (a deployable app that restarts on deploy, a plan that replaces or deletes a serving or data resource, or an unreadable plan, which fails closed), picks the change class (`standard`, `restricted` or `both`), and does the window math in UTC with DST handled per calendar date | `maintenance_window_test.py` |
| `merge_queue.py` | Puts a pull request into the main branch's merge queue and proves it got there (cancels a stale auto merge request, enqueues, re-reads, raises when it did not enter) | `merge_queue_test.py` |
| `gh_run_jobs.py` | Reads every job of a workflow run in pages of 50 with one retry on a 5xx, so every lane reads run jobs one way | `gh_run_jobs_test.py` |
| `tfplan_gate.py` (+ `tfplan-gate.sh`, `tfplan-fastpass.sh`) | The infrastructure plan gate (gated deploys lane): approves ordinary pull request plans waiting on the plan environment, holds pull requests that change how the pipeline works (workflow code, the owners file, the exclusions list, plan-time code or network constructs, provider and backend changes) in a queue for the owner, cancels superseded runs, carries an approval to a later head whose held content is identical, backs off after failures, and wakes the agent only to write a private assessment. Fails closed on any code host error. Repo, environment, owner login, state and cache paths are `TFGATE_*` environment variables | `tfplan_gate_checks.py` (298 checks, run by `tfplan_gate_test.py`) |
| `signoff_store.py` | Reference sign-off store for the plan gate: one owner sign-off per pull request and lane (own: carries to later heads; engineer: exact head only), with the fingerprints of the held hits it covers. Replaceable with `tfplan_gate.set_signoff_store` | `signoff_store_test.py` |
| `autofix.py` (+ `autofix_checks.py`) | The auto-fix starter for the owner's own pull requests: the fixable problem table, one session per (PR, head, problem), daily cap, give-up and report, waits-on re-arm, FIX DECISION cards, directed fixes, one push per round, finding catalog. Targets, pre-push gate, runtime and held-files gate are parameters or plug-ins (DESIGN.md 12.9) | `autofix_checks.py` (115 checks, run by `autofix_test.py`) |
| `docs_write_guard.py` | The `docs_home` `api` variant's scope proof (DESIGN.md 5.2): a docs write is allowed only when the page's ancestor chain reaches an allowed root and never an excluded root (folders are proven downward), only create and update are allowed, a forbidden pattern in a body refuses, every decision is logged, and anything unproven is refused. Roots, tenant, endpoint and patterns are parameters; the token comes from the sign-in slot | `docs_write_guard_test.py` |
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

## Not lifted

The review lane engine and the own pull request lane scripts: the handoff snapshot does not include the review
engine, the auto-fix session starter or the privileged plan lane they import (`tfplan_gate.set_privileged_gate`
is the seam for the last). The tests that need them (hold in approve, enqueue inside the window, plan summary,
the plan card's decide and Approve and merge helper) come with them. The reference sign-off store was written for
the standard because the running one was not in the snapshot.
