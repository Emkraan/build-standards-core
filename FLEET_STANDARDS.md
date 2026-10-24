# Emkraan Fleet Standards

<!-- GENERATED FILE. Do not edit in this repo. Source: Emkraan/apollo scripts/generate-fleet-standards.py. -->

This file is generated in Emkraan/apollo from the Apollo standards and synced into every
private Emkraan repo by Fleet Compliance. Local edits are overwritten and fail the
`C-fleet-standards` compliance check; change the source standard in Apollo instead.
Apollo is the source of truth and wins on any detail: each line links the full standard.

## Standards obedience

- Consult the relevant Apollo standard before code or infra work and follow it exactly; if it is impossible or wrong, stop and get operator sign-off. Never silently deviate or baseline a violation. [Standard](https://github.com/Emkraan/apollo/blob/main/OPERATING_CONTRACT.md)

## Operator-pending work

- Work waiting on the operator (a decision, approval, review or operator-only action) gets a blocked card on the `operator-actions` kanban board with the exact decision, a link and a recommended default; a question asked only in chat is not tracked. [Standard](https://github.com/Emkraan/apollo/blob/main/OPERATING_CONTRACT.md)

## Issue routing

- Label every GitHub issue you file with its routing label at filing time: `kratos` (Kratos builds it), `eir` (Eir picks it up), or neither for tracking; never close an issue with unfinished scope. [Standard](https://github.com/Emkraan/apollo/blob/main/OPERATING_CONTRACT.md)

## Orchestration

- Recurring or triggered work on homelab or fleet state is an Eir job; no Kratos cron, launchd agent, host timer or private-repo GitHub schedule outside the named exceptions registry, every exception reports a heartbeat, and no scheduled job uses a personal credential. [Standard](https://github.com/Emkraan/apollo/blob/main/OPERATING_CONTRACT.md)

## CI and deploys

- Deploy only what a push ships: deploy triggers skip docs, licences and tests, list only the packages the app builds from, and treat a version bump as a deploy only when the artifact reads VERSION at runtime. [Standard](https://github.com/Emkraan/apollo/blob/main/docs/standards/github-actions-monorepo-standard.md)

## Git and pull requests

- Conventional Commits for every commit and PR title (commitlint-enforced). [Standard](https://github.com/Emkraan/apollo/blob/main/OPERATING_CONTRACT.md)
- No AI attribution: never mention Claude, AI or Anthropic in commits, PR bodies or code comments, and never add a Co-Authored-By trailer. [Standard](https://github.com/Emkraan/apollo/blob/main/OPERATING_CONTRACT.md)
- No em or en dashes in any `.md` file; use hyphens, commas or colons. [Standard](https://github.com/Emkraan/apollo/blob/main/docs/standards/github-repo-standard.md)
- Main is protected: no direct push, no force-push; every change lands via a PR that auto-merges on green CI. [Standard](https://github.com/Emkraan/apollo/blob/main/docs/standards/github-repo-standard.md)
- Do all branch, commit and push work in your own per-session git worktree, never in a shared checkout. [Standard](https://github.com/Emkraan/apollo/blob/main/docs/standards/github-repo-standard.md)

## Homelab operations

- Claudius first: every homelab read and mutation goes through the Claudius MCP tools; no improvised ssh, curl or API path. Read before write, verify after. [Standard](https://github.com/Emkraan/apollo/blob/main/docs/standards/claudius-operations.md)
- Containers are Portainer-managed and every stack is git-backed: no bare `docker run`, no standalone stacks, no `.env` files in Portainer compose dirs. [Standard](https://github.com/Emkraan/apollo/blob/main/docs/standards/portainer-stacks-standard.md)

## Code and platform

- LLM calls route through the homelab LiteLLM gateway; never send `max_tokens`, `max_completion_tokens` or `reasoning_effort`, the gateway owns them. [Standard](https://github.com/Emkraan/apollo/blob/main/docs/homelab/automation/litellm.md)
- Grafana dashboards live only in `Emkraan/emkraan-grafana`, and a new operator-visible metric ships with its panel in the same change set. [Standard](https://github.com/Emkraan/apollo/blob/main/docs/standards/grafana-dashboard-standard.md)
- Python uses Ruff (lint and format, pinned version, `[tool.ruff]` in `pyproject.toml`) as the CI gate. [Standard](https://github.com/Emkraan/apollo/blob/main/docs/standards/python-tooling-standard.md)
- Every alert carries an https `annotations.runbook_url` pointing at a real runbook section. [Standard](https://github.com/Emkraan/apollo/blob/main/docs/standards/notification-standard.md)
- Secrets live only in Azure Key Vault: never committed to git or baked into an image; repos ship empty `.env.example` placeholders. [Standard](https://github.com/Emkraan/apollo/blob/main/docs/standards/azure-access-and-key-vault.md)
- Web tools authenticate with Entra ID as the IdP, brokered through Authentik (`auth.emkraan.com`); never wire an app directly to Entra. [Standard](https://github.com/Emkraan/apollo/blob/main/docs/standards/authentik-broker-standard.md)
