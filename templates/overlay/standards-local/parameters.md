# Local parameters

Fill in per business. Keep secrets, hostnames and tenant ids out of any repo that is shared.

| Parameter | Value | Used by |
|---|---|---|
| App accent (a named accent set with `data-app-accent` on the root, or a block printed by `tokens-core/build.py --accent`) | | web-ui.md sections 12 and 16 |
| Identity provider | | identity-and-people-data.md, rbac.md |
| Hosting platform | | web-build.md, data-safety-sqlite.md |
| Runner topology | | ci-cd-release.md |
| Notification channel | | notifications.md |
| Python interpreter floor (default 3.9 where the OS python is the runtime) | | scripting-python.md 1.1 |
| Secret store (where workloads read secrets with their own identity) | | secrets-and-credentials.md 1.6 |
| Docs home (wiki space, docs site or the repo) | | docs-and-changelog.md |
| Tombstone TTL for live actions (default 10 minutes) | | live-actions.md 1.2 |
| Change freeze calendar (where applies read it live) | | iac-governance.md 1.9 |
| IaC back-port window for break-glass changes (default one business day) | | iac-governance.md 1.1 |
| Stacks this overlay has, comma-separated from web, wpf, local-ops, powershell, python, iac (empty reports every rule) | | scripts/core-status.py, rules.json applies_to |
| Python test command run on the floor by core-ci.yml (default `python -m unittest discover`) | | scripting-python.md 1.1 |
| Commit emails the identity check allows besides GitHub noreply, comma-separated globs (for example `*@example.com`) | | pr-review-and-merge.md 1.4 |
| Changelog file (default `CHANGELOG.md`) | | docs-and-changelog.md 1.3 |
| Version files the changelog check reads, comma-separated (default `package.json, pyproject.toml, VERSION`) | | docs-and-changelog.md 1.3 |
| Changelog entries (`per-pr`: one new entry per pull request, fixed heading, newest first, append-only, checked by core-ci.yml; empty: off) | | docs-and-changelog.md 1.9 |
| Lint sweep command (the repo's own full-tree lint that lint-sweep.yml runs weekly; empty: only the overlay lints) | | ci-cd-release.md 2.1 |
| App directory (the folder with the web app's lockfile that lint-sweep.yml installs and lints in; empty: the root, else the first folder one level down that holds a lockfile) | | ci-cd-release.md 2.1 |
| Trust hold: merged pull requests before an author is no longer new (default 3) | | pr-review-and-merge.md section 4 |
| Trust hold: device-shipped paths, comma-separated globs (content shipped to managed devices or end-user machines) | | pr-review-and-merge.md section 4 |
| ASCII check patterns, comma-separated globs that narrow the ASCII check (empty: every tracked text file, the default and the rule; for existing non-ASCII files record a time-boxed exception instead of narrowing) | | pr-review-and-merge.md 1.19, scripting-powershell.md 1.7, wpf-design-system.md 6.1 |
| Node major version (web; empty takes the first pin found) | | ci-cd-release.md 1 |
