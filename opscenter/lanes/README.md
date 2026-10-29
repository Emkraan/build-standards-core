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
| `pr_landing.py` | The structured ask for PR cards: what lands at the merge per root, why it needs the owner, risks, the typed-name rule, and a check that prose never claims an unapplied root (DESIGN.md 12.42) | `pr_landing_test.py` (16) |
| `signoff_store.py` | Reference sign-off store for the plan gate: one owner sign-off per pull request and lane (own: carries to later heads; engineer: exact head only), with the fingerprints of the held hits it covers. Replaceable with `tfplan_gate.set_signoff_store` | `signoff_store_test.py` |
| `review_threads.py` | Open review conversations on a PR: read, tag each author once with a marker comment, resolve one on request; fails closed with `ThreadError` (DESIGN.md 12.27) | `review_threads_test.py` (7) |
| `autofix.py` (+ `autofix_checks.py`) | The auto-fix starter for the owner's own pull requests: the fixable problem table, one session per (PR, head, problem), daily cap, give-up and report, waits-on re-arm, FIX DECISION cards, directed fixes, one push per round, finding catalog. Targets, pre-push gate, runtime and held-files gate are parameters or plug-ins (DESIGN.md 12.9) | `autofix_checks.py` (115 checks, run by `autofix_test.py`) |
| `docs_write_guard.py` | The `docs_home` `api` variant's scope proof (DESIGN.md 5.2): a docs write is allowed only when the page's ancestor chain reaches an allowed root and never an excluded root (folders are proven downward), only create and update are allowed, a forbidden pattern in a body refuses, every decision is logged, and anything unproven is refused. Roots, tenant, endpoint and patterns are parameters; the token comes from the sign-in slot | `docs_write_guard_test.py` |
| `reviews_visibility.py` (+ `reviews-visibility.sh`) | Proves every open item behind the Reviews pages sits in a tab with an action and that each card agrees with its lane: raises `contradiction`, `invisible` and `stuck` board items, closes them when the condition clears. Lanes, owner login, live check and refresh command are parameters (DESIGN.md 12.10) | `reviews_visibility_checks.py` (48 checks, run by `reviews_visibility_test.py`) |
| `preflight.py` | The reference pre-push gate (DESIGN.md 12.11): `run`, `review`, `review-template` and `design-template` on a worktree diff against origin/main: repo gates, hygiene (ASCII and dashes, secrets, branch rule, version bump, conflict, attribution), the lane dry run as expected sign-offs, overlap with other open pull requests, the catalog's scriptable rules, the self-review gate, the local independent review (reviewers through the agent CLI, the codex CLI or an API with a key command) and the design check for acting automation. Exit 0 pass, 1 failures, 2 environment problem | `preflight_test.py` (57 tests on scratch git repos) |
| `pr_review.py` | The review engine for engineer pull requests: `gate` (the wake gate), `check`, `record`, `approve` (the only approve path: re-runs the check and refuses on any escalation, red or pending checks, open threads or a moved head), `status`, `window`. Deterministic policy rules, trust rules, the dev tier waiver, branch drift, main baseline and main pending, the maintenance window hold. The policy is data (`REVIEW_POLICY.md`) | `pr_review_*_checks.py` (7 files, 132 tests, run by `review_lanes_test.py`) |
| `own_pr_merge.py` | The own pull request lane: merges the owner's green pull request (policy rules, triage markers that name finding ids, sign-off carry, freeze, plan guard) with the head pinned, and starts the auto-fix starter on a held one. Targets `primary` and `secondary` | `tests/own_pr_merge_checks.py` (171 checks, run by `review_lanes_test.py`) |
| `destroy_followup.py` | Follows a dispatched destroy: matches its run, reruns a main apply that failed only on the destroy guard, reports once, expires after 48 hours | `destroy_followup_checks.py` (37 checks) |
| `model_bump.py` | Opens and merges the review model bump pull request for a target (discovery hourly, shape check, rebase merge when every check is green); targets come from `OPSCENTER_REVIEW_TARGETS` | `model_bump_test.py` |
| `core_pr_lane.py` | The merge lane for the owner's green pull requests on the core repository: every check green, merge state clean, a quiet period on an unchanged head, the repo's local checks in a temporary worktree, one new CHANGELOG version above the newest tag. Merges at most one per pass (squash, pinned to the head), releases the tag with the entry's notes and runs an optional sync command. Owner mode keeps every gate but never merges. Hands holds a session can fix to `autofix.py` | `tests/core_pr_lane_checks.py` (107 checks, run by `review_lanes_test.py`) |
| `own_sync_lane.py` | The auto-fix lane for the owner's nightly sync pull requests on a repository: it never merges, labels or comments; it hands red checks and conflicts to `autofix.py` under the same caps and reports a give-up or a stuck CI run once | `tests/own_sync_lane_checks.py` (49 checks) |
| `queued_approvals.py` | The queued docs approvals applier: drains the approval inbox through the docs write guard, verifies each write by reading the page back, never creates a title twice (looked up under the guard's roots, a failed lookup fails closed), records each outcome the moment it publishes, supports the changelog append auto mode, and optionally refreshes a documentation audit. The docs home adapter is `DOCS_HOME_CMD`, none by default (then nothing is applied) | `queued_approvals_checks.py` (run by `review_lanes_test.py`), `queued_approvals_concurrency_test.py` (3), `queued_approvals_null_test.py` (2) |
| `paths.py` | The same helper as `../server/modules/paths.py` (state, agent home and repos from environment variables), copied so a lane runs on its own | none |
| `../testing/policy_env.py` | A scratch state tree holding the two policy fixtures, for the review lane checks | used by them |
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

Item 17 (model accounts) by decision, the queued approvals applier (needs the docs home adapter wiring), and the
sitrep and analyzer scripts, which have their own pieces. The reference sign-off store gained `review`, `plan_facts`,
`path_of` and `latest_epoch` for the own lane's carry rule, written for the standard because the running store was not
in the snapshot.
