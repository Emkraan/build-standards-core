# Ops center app

React, TypeScript and Vite on the shared kit (`@kit` resolves to `opscenter/kit/src`), lifted from the shell consumer's running
ops center (opscenter/DESIGN.md section 4 and 12). Every page and component of the running app is here:

| Rail group | Pages |
|---|---|
| Operate | Action Center (board, completed, routing, alerts), work tracker (sprint with its trend card, needs me, backlog, closed sprints), Reviews (primary repo lane, secondary lane, other repos, member views), Debt |
| People | 1:1 board, team performance, member reviews, yearly review, team history |
| Knowledge | Knowledge (proposals, coverage, docs drift, history), Plans, Links |
| Platform | Builds, Core consumption, Infrastructure (spend, jobs, live, CI, code host), Search |

The rail, home route and which pages show are decided by the parameters in `opscenter/DESIGN.md` sections 4 and 6; a page
whose backend slot is null hides (section 1.3). The optional tabs follow it: Docs drift, the sprint trend card, Closed sprints and
Live automation each hide when their provider is not configured.

## Parameters (build time)

| Variable | Default | Meaning |
|---|---|---|
| `VITE_PRIMARY_REPO` | `owner/primary` | `owner/name` of the repo behind the primary Reviews lane (pull request links) |
| `VITE_APP_SUBTITLE` | empty | the sidebar build card subtitle |

## Commands

```bash
npm ci && npm run typecheck && npm test && npm run build   # then: npm run test:browser
```

CI runs typecheck, the unit tests and the build in `.github/workflows/opscenter-app.yml`. The accessibility and live
action tests drive Chrome and run with `npm run test:browser` after a build (set `CHROME_BIN`; they skip on a machine
with no browser and never skip when `CI` is set); a consumer runs them in its own CI.

## Notes

- `src/lib/live.ts` is the client of the push channel (Local Ops App section 20). `createLiveStore` takes `{ topics }` or `{ path }`: it reloads once when the server says that topic moved, stretches its own timer to a five minute safety net while the channel is live, and goes back to its own interval the moment the channel drops. A dataset store (`useData`) listens on `data:<file>`. `setAliases` carries the short topic names the server's `live_bus.ALIASES` defines.
- `src/lib/time.ts` is the one time formatter (Ops Center Layout rule 21). `setTimeZone('<IANA zone>')` once at start-up picks the zone every clock time is written in (default: the viewer's own).

- Names that were estate specific are neutral: the two review lanes are `platform` (primary) and `team` (secondary), and
  the endpoint paths follow them. A consumer maps its own repositories through the server's `cron_pulse.repos` parameter
  (section 12.8); the app does not carry repository names.
- `src/pages/links/catalog.json` is an example catalog; the real one is the consumer's data.
