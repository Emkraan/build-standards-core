---
title: Hermes Standard
last_updated: 2026-10-12
category: standards
related:
  - docs/standards/web-ui.md
  - docs/standards/web-build.md
---
# Hermes Standard: Skills and Plugins Sharing

## Version
1.0 | Last reviewed: 2026-10-12 | Status: current

## Scope
This standard defines what content related to the Hermes agent platform is shared in source-controlled overlays, and what must remain local. It covers skills, plugins, and associated configuration, for first-party and derived fleet Hermes deployments.

## What is sharable
- **Skills** whose filenames begin with `core-` _only_:
    - Example: `core-token-parity.md`, `core-onboarding.md`
    - No identifying, instance-specific, or organization content
    - Documented and acceptance-criteria-driven
    - Published upstream for rapid fleet parity
- **Plugins**: Source, documentation, and non-secret configuration
- **Plugin examples**: Demo code and wiring patterns without any secret, token, or API key values

## What is never sharable (MUST remain local)
- MCP configuration, gateway tokens, kanban config or boards
- All entries from `~/.hermes/config.yaml`, profiles, or vault directory
- Any secret, key, token, or authentication material
- Any skill which mentions, references, or encodes an instance's real world configuration, URLs, hostnames, project identifiers, or user details

## Plugin rules
- The plugin's source code _without_ configuration or secrets may be furnished in the template
- Instructions must explicitly tell operators where and how to provide their own tokens or sensitive conf
- No example configuration file checked in may work out of the box or leak to a peer instance
- Plugins must not reference local kanban boards, MCP, or vault secrets

## Skills directory
- All skills ready to sync to overlays must start with `core-`, and be ASCII-only, business-agnostic, and versioned
- The upstream repo provides best-practice reference skills for test, onboarding, and token parity
- All other skills, local operator skills, and environment-specific content must stay out of source

## How to contribute
1. Author skill or plugin as `core-`. Submit PR to core.
2. Review for leaking configuration or secret context-request changes if violation found
3. On acceptance, merge and publish in next release
4. Consumer overlays use `sync-core.py latest` for update

## Compliance
| Area   | Checked | Failure Action |
|--------|---------|----------------|
| Skills have `core-` prefix only | yes | Block merge / reject sync |
| No secrets, keys, or instance detail | yes | Block merge / reject sync |
| Plugins source, no secrets | yes | Block merge / reject sync |
| Overlay contains no MCP, kanban, config, or vault | yes | Block merge / reject sync |

## Failure modes and remediations
- **Leaked config/secret/board:** PR auto-reject or immediate revert; operator rotate/clear sensitive content
- **Skill missing prefix:** Blocked from publish, operator must rename and resubmit
