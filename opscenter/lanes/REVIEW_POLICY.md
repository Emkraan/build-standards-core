# Review policy schema

The review engine (`pr_review.py`) and the own pull request lane (`own_pr_merge.py`) read one JSON policy file per
target, on every call, so an edit takes effect on the next run. `fixtures/review-policy.json` is a complete example for
the primary target and `fixtures/own-pr-policy.json` for a secondary target; the tests read them. A key that starts
with an underscore is a note and is ignored. A rule hit means: do not approve, escalate to the owner's Needs me list.
Regexes are Python `re`, case-insensitive.

Files: the primary policy is `<state dir>/review/policy.json` (`OPRG_POLICY` overrides); a secondary target's is
`<state dir>/secondary-review/own-pr-policy.json`. State dir is `OPSCENTER_STATE_DIR` (default `~/.opscenter/state`).

| Key | Meaning |
|---|---|
| `version` | schema version, 1 |
| `repo` | `owner/name` of the repository the target reviews |
| `self_login` | the owner's login: its own pull requests never reach the engineer lane, its triage comments count in the own lane |
| `approve_as` | the identity an approval is posted as |
| `skip_authors_regex`, `skip_drafts` | authors (bots) and drafts the engine never reviews |
| `merge` | `method` (`rebase`), `use_merge_queue`, `admin` (never true for an engineer pull request) |
| `own_pr_merge` | the own lane: `enabled`, `hold_labels`, `max_high` (high findings allowed to merge), `respect_freeze`, `notify_on_merge`, `autofix` (the auto-fix starter's switches, DESIGN.md 12.9), `residual_risk_rule` (the one rule that accepts a named short race as logged debt: `id`, `enabled`, `title`, `text`) |
| `reuse_tfplan_gate_matcher` | true when the plan gate's matcher (hold paths, denied lines, new lockfile entries) also applies; false for a target with no plan workflow |
| `inherit_line_rules_from` | a secondary policy only: a path (absolute, or relative to the state dir) of the primary policy whose `line_rules` and `role_assignment_scope` it prepends |
| `ignore_checks_regex` | check names that never count as red (preview deploy checks, for example) |
| `scan_suffixes` | file suffixes the line rules scan |
| `path_rules[]` | `{id, pattern, reason}`: a changed path that matches escalates |
| `line_rules[]` | `{id, pattern, reason, file_types, path_exceptions[]}`: an added line that matches escalates; `path_exceptions` waive a shape for one kind of path |
| `role_assignment_scope` | `{id, allowed_scope_regex, reason, path_exceptions[]}`: a role assignment must match an allowed scope and role pair |
| `plan_rules` | `destroy`, `replace`, `plan_error`: `{id, reason, escalate}` for the plan workflow's summary |
| `judgement_rules[]` | text the review reads as guidance: when to escalate with no deterministic rule |
| `standards[]` | files the reviewer reads before judging (paths under the consumer's own clone) |
| `review` | `marker` (the hidden marker that names this engine's review comment), `max_rounds_before_escalation`, `stale_escalation_hours` |
| `trust_rules` | `new_app_roots[]` (a new folder under one of them escalates the first pull request), `new_file_roots[]` and `new_file_extensions[]` (a new file there escalates), `first_prs_to_review` (an author's first N merged pull requests escalate), `approval_paths[]` (paths that always go to the owner), `dev_tier_only` (`enabled`, `prod_tier`, `kinds[]`: a pull request that provably cannot reach production is waived from the trust rules) |
| `maintenance_window` | the downtime windows (README.md, "Policy data") |
| `ai_review` | `escalate_blocking`: whether a confirmed blocking finding of the independent review goes to the owner (false: back to the author) |

Environment: `OPRG_STATE_DIR` (queue and decisions), `OPRG_CACHE_DIR` (fingerprint, health, lock), `OPRG_POLICY`,
`OPRG_GH_BIN`, `OPRG_DRY_RUN=1`, `OPRG_NO_AUDIT=1`, `OPRG_NOW`, `OPSCENTER_LANE_LABEL` (the label in gate lines and
card tags, default `primary`), `OPSCENTER_BRANCH_PREFIX` (the engineer branch prefix the drift rule reads, default
`ticket-`), `OPSCENTER_FORBIDDEN_WORDS` (extra words a posted comment may never contain, a regex alternation, added to
the built in list). The own lane adds `OWNPR_FREEZE_FILE`, `OPSCENTER_DRAFT_GATE` (a draft gate plug-in, below).
