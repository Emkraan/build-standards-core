# Server modules

One stdlib Python module per page or lane backend (opscenter/DESIGN.md section 12.3). State lives under
`OPSCENTER_STATE_DIR` (default `~/.opscenter/state`); a module never writes outside it.

| Module | What it does | Tests |
|---|---|---|
| `dark_launches.py` | Dark launches: acting automation ships with its switch (a code host variable) off. Run a dry run, Enable (typed variable name, newest dry run green, read live), Disable (always allowed). Registry `dashboard/dark-launches.json`, append only log `dashboard/dark-launches-log.jsonl`. A failed read is `unknown`, never `off` | `dark_launches_test.py` |
| `own_lane.py` | Read only view of the own pull request lane per review lane: freshness, the lane's record for a head, held and covered rules, and what auto-fix is doing | `own_lane_test.py` |
| `decision_cards.py` | The one writer of the lane's direction and sign-off files: a click on a decision card option is a sign-off for that head only (fix, hold or override with the triage marker); head pinned, owner only, delete rules never signed off | `decision_cards_test.py` |
| `paths.py` | Where things live, from `OPSCENTER_ROOT`, `OPSCENTER_STATE_DIR`, `OPSCENTER_AGENT_HOME` and `OPSCENTER_REPOS` (never a literal home path), and `which` for binaries | `paths_test.py` |
| `swr.py` | Stale while revalidate cache: a fresh entry is served as is, an expired one is served at once with one background refresh (single flight per key), only a cold key or a too old entry computes inline, `invalidate` after a write | `swr_test.py` |
| `automation_actions.py` | The store behind automatic board items (one item per condition, keyed, closes itself when the condition clears), also a command line for jobs | covered by `alerts_test.py` |
| `alerts.py` | One board item per failing scheduled job, key `auto-alert-<job>-<streak start>`, closed by the next success; failures watched for every enabled job by default | `alerts_test.py` |
| `image_watch.py` | Optional. A failed desktop image build raises one board item with the failing job and step and the buttons Rerun failed jobs, Close the window and Open run; nothing acts by itself | `image_watch_test.py` |
| `browser_status.py` | Optional. Flags the shared automation browser when its window stays visible or the service stays down, and offers a one click hide | `browser_status_test.py` |
| `review_acted.py` | Tombstones for review actions the owner took, so a PR just merged or approved is not listed again before the code host catches up; a new push brings it back | `review_acted_test.py` |
| `cron_pulse.py` | Which scheduled job owns a card, when it runs next, and Run now (auto mapping from a job's script and prompt, override file `cron-card-map.json`); repos and the branch key are parameters (section 12.8) | `cron_pulse_test.py` |
| `link_health.py` | Weekly Links reachability check, Not reachable pill, Swap and Remove edit pull requests; the catalog is the consumer's data | `link_health_test.py` |
| `runbook_releases.py` | Optional. Release guarded deletes of a deploy root after the owner approves and merges the pull request, re-checking everything live | `runbook_releases_test.py` |
| `desktop_pool.py` | Optional. Host pool evidence (drain mode, sessions, a new host serving) for the Destroy approval card of a pool roll | `desktop_pool_test.py` |
| `ops_search.py` | Global search: board items, 1:1 topics, text files in configured folders and the agent runtime's sessions (read only), grouped, ranked, with a deep link per hit; builds the tracker query for the live scope. Folders and the runtime database are parameters | `ops_search_test.py` |
| `routing_api.py` | The Action Center routing API: read the rules with hit counts, the sources and the last collector report; preview a rule against the current candidates and items; add (idempotent), disable and delete click rules. A write re-bundles through `OPSCENTER_REFRESH_CMD` when set | `routing_api_test.py` |
| `builds.py` | The Builds page: the configured pipelines' runs with job and step progress, the failure reason (annotation, else the log), the environment a waiting run needs and whether the owner can approve it here, a rollout summary line, what landed (a consumer command per product), and for a deploy refused because the branch is behind main the live count and, on the owner's own branch, a guarded Update from main that merges through the merge API, re-runs, or lists the conflict. Pipelines, owner, branch pattern and landed commands are `BUILDS_CONFIG` (DESIGN.md 12.20) | `builds_test.py` (9, against a fake gh) |
| `model_accounts.py`, `model_fallback.py` | The Spend page (accounts, limits, spend history, token windows, routing and cooldown) and the fallback watch, over a `ModelAccountsProvider` that is null by default; a provider that declares a credential pool read is refused unless enabled (DESIGN.md 12.22) | `model_accounts_test.py` (28) |
| `eng_backlog.py` | The Debt and improvements page: TD and IMP entries parsed from two markdown files, decisions that rewrite one Status line in place, page-only snooze (DESIGN.md 12.25) | `eng_backlog_test.py` (10) |
| `doc_coverage.py` | The Knowledge page's documentation coverage: registry joined with the audit store, snooze and ignore, the badge count and the tackle item (DESIGN.md 12.26) | `doc_coverage_test.py` (9) |
| `core_consumption.py` | The core consumption panel: rows from the nightly consumption feed (no gh on read), and the approvals as single gh calls (DESIGN.md 12.24) | `core_consumption_test.py` (28) |
| `ghview.py` | The code host read helpers the modules share (gh binary from `GH_BIN`, one JSON call, a job view, a safe wrapper) | covered by `builds_test.py` |
| `pr_deps.py` | One dependency model for open pull requests (a line "Waits on #N", a stacked branch, a destroy attributed to a parent), so the board never asks for an approval that cannot pass yet; read failures never hide a card | `pr_deps_test.py` |
