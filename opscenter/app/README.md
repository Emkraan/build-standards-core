# Ops center app

React, TypeScript and Vite on the shared kit (`@kit` resolves to `kit/src`), lifted from the shell consumer's running
ops center (opscenter/DESIGN.md section 4 and 12). Every page and component of the running app is here:

| Rail group | Pages |
|---|---|
| Operate | Action Center (board, completed, routing, alerts), work tracker (sprint, needs me, backlog), Reviews (primary repo lane, secondary lane, other repos, member views), Debt |
| People | 1:1 board, team performance, member reviews, yearly review, team history |
| Knowledge | Knowledge (proposals, coverage, history), Plans, Links |
| Platform | Builds, Core consumption, Infrastructure (spend, jobs, live, CI, code host), Search |

The rail, home route and which pages show are decided by the parameters in `opscenter/DESIGN.md` sections 4 and 6; a page
whose backend slot is null hides (section 1.3).

## Parameters (build time)

| Variable | Default | Meaning |
|---|---|---|
| `VITE_PRIMARY_REPO` | `owner/primary` | `owner/name` of the repo behind the primary Reviews lane (pull request links) |
| `VITE_APP_SUBTITLE` | empty | the sidebar build card subtitle |

## Commands

```bash
npm ci && npm run typecheck && npm test && npm run build
```

CI runs the same three in `.github/workflows/opscenter-app.yml`. Four browser tests (accessibility and live actions) skip
without a browser and run in a consumer's own CI.

## Notes

- Names that were estate specific are neutral: the two review lanes are `platform` (primary) and `team` (secondary), and
  the endpoint paths follow them. A consumer maps its own repositories through the server's `cron_pulse.repos` parameter
  (section 12.8); the app does not carry repository names.
- `src/pages/links/catalog.json` is an example catalog; the real one is the consumer's data.
