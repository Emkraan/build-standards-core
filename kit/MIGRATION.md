# Adopting the UI whole

Syncing the overlay does not adopt the UI. An app has adopted it when `python3 scripts/core-status.py`
reports `ui: adopted` (web-ui.md 0.11). Work in this order, one pull request per step, and run
`python3 lint-core/ui_lint.py` after each.

0. **Baseline first.** A repo that predates the core adopts the baseline before it swaps anything,
   so the app stays whole at every step. Sync the overlay (`CONSUMING.md`) and get its checks
   passing against the app as it is. Then, for each hand-rolled part that a kit part covers, add
   a thin adapter that re-exports the kit part under the name your pages already import: call
   sites never move, and old behaviour the kit part lacks is composed onto the kit part in the
   adapter, not forked beside it. A shared UI package in a monorepo becomes the baseline plus
   additions: it re-exports the kit and the core tokens and grows repo-specific parts beside
   them. Adapters are consumer-owned app code; the core never ships one. If the app's TypeScript
   config includes the synced `kit-core` folder, list the optional entries whose peers it does not
   install (`charts`, `graph`, `api-reference`) under `exclude`: nothing the kit root reaches imports their
   peers, so an optional peer stays optional at typecheck too. `python3 scripts/core-ci.py kit-peers` proves it:
   it fails a tsconfig that includes the whole copy without excluding an entry whose peer the app's
   `package.json` does not declare, and where the repo has `tsc` it typechecks the copy with the
   entries excluded and the peers blocked (the core runs the same proof on every kit change). With
   the app green on adapters, retire the hand-rolled parts in the order below.

   **An app the core was taken from** (its design system is the core's ancestor and has since drifted
   the other way) follows the same steps; it is not exempt and does not get an exception row for the
   drift. Before step 1, compare its parts with the kit: what the app has that the kit lacks goes up
   as report items (CONTRIBUTING.md "Reporting from a consumer"), what the kit has moved on goes in a
   dated move plan in the app's own docs (which part, which step, by when). The plan replaces an
   open-ended exception: an exception row is only for a rule the app cannot meet by the plan's date.
1. **Tokens.** Import `tokens-core/tokens.css` once and delete the app's own copy of any core token.
   Rename app references to the core names (`--text-on-accent`, `--surface-1`, `--radius-md`).
   Lint rule UI010 lists every redefinition.
2. **Shell.** Replace the hand-rolled layout with the kit `AppShell` and the icon rail. The sidebar is the
   rail, not a custom list. Delete the app's sidebar, header and layout CSS.
3. **Parts.** Swap each local button, input, select, table, dialog, toast, tab and card for the kit
   part. Compact toolbar controls use `size="sm"`, a clickable card is `<Card interactive onClick>`,
   an inline message is `<Alert tone>`.
   An app library becomes a layer on the kit rather than being deleted: README "An app's own
   component library". Kit class names (`.btn`, `.modal`, `.table`, `.toast`) collide with a local
   library's classes, so swap the colliding parts together in one pull request.
4. **Leftovers.** What the kit lacks stays an app component with its own classes, built from tokens. If
   others would need it, add it to the account's `consumer-report` issue (CONTRIBUTING.md
   "Reporting from a consumer"); the owner approves, then the owning account opens the core pull
   request.
5. **Close the baseline.** Delete `baseline` from `standards-local/ui-lint.json`. Anything still failing
   is fixed or recorded as a named exception.
6. **Prove it.** `core-status.py --require-ui-adopted` exits 0 and the core-drift workflow is green.

## Old names to kit parts

An app library that grew its own version of a kit part maps onto the kit part below. Swap the call
site, then delete the local part. The kit never carries a second part under the old name.

| Old part | Kit part | Prop mapping |
| --- | --- | --- |
| `KpiTile` | `StatTile` | `label`, `value`, `hint`, `icon`, `onClick` and `className` keep their names. `tone` maps to `tone` (`accent` is the default in both). The count-up is built in. |
| `PanelHead` | `CardHead variant="panel"` | `title` and `subtitle` keep their names. `actions` becomes `controls`. `children` after the title goes in `controls`. |
| `CardTitle` | `CardHead` (`variant="card"`, the default) | The children become `title`. Pass `level` when the card is not a level 2 section. |
| `SectionLabel` | `CardHead variant="label"` | The children become `title`. `icon` and `count` keep their names. |
| `Confirm` | `useConfirm` | Render `dialog` once and `await confirm({ ... })` instead of mounting `Confirm` with `onConfirm` and `onClose`. `message` becomes `body`. `tone="danger"` becomes `danger`. `confirmLabel`, `cancelLabel`, `requireText` and `requireTextLabel` keep their names. `busy` and `error` go: run the action after the promise resolves `true` and report a failure with a toast. |
| `Tooltip` (wrapper) | `TooltipLayer` plus `data-tip` | Mount `TooltipLayer` once, or pass `tooltipLayer` to `AppShell` and let it mount the layer (an app that mounts its own keeps working, because only the first layer draws). Put `data-tip="label"` on the child instead of wrapping it, and `side` becomes `data-tip-side` (`top`, `bottom`, `right` or `left`). |
| `Tag` | `Badge` with `onRemove` | `tone`, `dot`, `onRemove` and `removing` keep their names. `label` becomes `removeLabel` (the remove button reads "Remove <removeLabel>"). |
| `Meter` | `ProgressBar meter` | `ratio` becomes `value` with `max={1}`. `tone` keeps its name. Give it a `label`. `height` goes: the bar height is a token. |
| `SkeletonList` | `Skeleton variant="list"` | `rows` becomes `count`. `label` keeps its name. `height`, `gap` and `radius` go: the shapes come from tokens. |
| `ErrorState` | `ErrorState` | Same name and props, plus `retryLabel`. `errorDetail(error)` gives the same one line text. |
| `useRowSelection`, `ThSelect`, `TdSelect` | `useRowSelection` plus the `selection` prop on `Table` | `const sel = useRowSelection(visibleIds)`, then `<Table selection={sel} rowKey={...} />`. The table draws the select-all header and the row checkboxes itself, so `ThSelect` and `TdSelect` go. |
| `SelectionBar`, `ListFooter` | `SelectionBar`, `ListFooter` | Same names. |
| `FormSection` | `FormSection` | Same name. `columns` is `1` or `2` (default 2). |
| `useMediaQuery`, `useIsPhone` | `useMediaQuery`, `useIsPhone` | Same names. `PHONE_QUERY` and `SHELL_QUERY` are the kit breakpoints. |
| `ToastProvider`, `useToast` | `Toaster`, `useToast` | Mount `Toaster` once. `toast(variant, message, opts)` takes the variant first (`success`, `error`, `warning` or `info`) and returns a string id. There are no `success()`, `error()` or `info()` shorthands. `opts` carries `description`, `action`, `persistent`, `duration` and `id`. |
| `Modal`, `Drawer` | `Modal` | `open` and `onClose(reason)` are required, the reason being `escape`, `backdrop` or `close`. `size` adds `xl`, `wide` and `full`. A drawer is `variant="sheet"`, and its `label` becomes `title`. |
| `Tabs`, `TabPanel` | `Tabs`, `TabPanel` | `tabs` becomes `items`, `owner` becomes `idBase`, `underline` becomes `default`, and every tab `label` is a string. `TabPanel` takes `idBase` and `tabId`. |
| `Badge` with `mono`, `Pill` | `Badge`, `Pill`, `Mono` | Tones add `neutral` and `urgent`, `hue` takes a categorical hue and `onRemove` adds a remove button. `mono` becomes a `Mono` child. `Pill` is its own part, not an alias. |
| `StatusDot` | `StatusDot` | `title` becomes `label`, `live` becomes `pulse` (on by default), `size` is gone, and there is no `accent` tone. A `title` that explained the state becomes `tip`. |
| `Table`, `THead`, `TBody`, `Th`, `Tr`, `Td` | `Table` | Data driven: `columns` (`key`, `header`, `value`, `render`, `sortable`, `numeric`, `width`), `rows`, `rowKey` and a required `caption`. Sorting is `useTableSort`, selection is `useRowSelection`. |
| Disabled button with a `title` that says why | `Button disabledReason` | Replace `disabled` and the `title` with `disabledReason="..."`. The button renders `aria-disabled`, stays focusable and shows the reason as its tip. `Modal` `primaryAction` takes the same prop. Lint rule UI011 flags a kit `Button` with `disabled` and no reason. |
| Hand-made glossary hint, info icon or help tooltip | `GlossaryProvider`, `Term`, `InfoTip` | Register `{ id: { term, short, long?, href? } }` once (`AppShell glossary`). `<Term id>` replaces an underlined word with a `title`, and `<InfoTip id>` replaces an info icon with its own popover. |
| Local "x ago" label with the date in a `title` | `When` | `value` (a date, an ISO string or milliseconds) and `timeZone`. The absolute date, time and zone are the tip, and every instance shares one clock. |
| Local help page, help modal or onboarding panel | `usePageHelp`, `HelpDrawer` | A page calls `usePageHelp({ title, summary, steps, terms, links })`. The `Header` shows the Help button once `AppShell helpDrawer` mounts the drawer. |
| Local step list or progress steps | `Stepper` | `steps` of `{ id, title, state, detail, meta, actions, waitingOn }` with a `state` of `done`, `current`, `upcoming`, `failed` or `waiting`. |
| Local activity list or history feed | `Timeline` | `entries` of `{ id, time, actor, actorTip, text, source, href }`, with `timeZone` for the page. |
| `Banner` | `Alert` | `tone` is `info`, `success`, `warning` or `danger`. The role follows the tone (`alert` for warning and danger, `status` otherwise), so drop `role`. `icon` and `onClose` have no kit prop: a dismiss `IconButton` goes in `action`. |
| `Menu` | `Menu` | `trigger` is a required element, not a render function, and `label` is required. Items are `MenuItemDef` with a required `id`. `align` becomes `placement` (`bottom-start`, `bottom-end`, `top-start` or `top-end`). |
| `Avatar` | `Avatar` | `name` is required. `id` and `kind` are gone: the hue comes from `name` unless `hue` is set, and a group passes `icon`. `size` is `sm`, `md` or `lg`. |
| `HubFeed`, `NewsItem` | `FeedStrip`, `FeedItem` | `FeedStrip` renders and the app fetches: pass `health` (`status` and `label`) and `items`. A `FeedItem` is `id`, `title`, `tone`, with optional `body` and `onOpen`. Tones are `info`, `success`, `warning` and `critical`. Mount it in the `AppShell` `strip` slot. |
| `AnnouncementBanners` | `AnnouncementStack`, `AnnouncementBanner` | Pass `announcements` (`id`, `tone`, `title`, with optional `body`, `meta`, `action` and `dismissible`) and a `storageKey` so dismissals are remembered. |
| `renderNavLink`, `NavLinkRenderProps` | `linkComponent`, `KitLinkProps` | Pass the router link once as the `AppShell` `linkComponent`. It receives `KitLinkProps` (`href` plus anchor attributes). `NavItem` `active` sets `aria-current`. |
| Local `T` token object | `tokens-core/tokens.ts` | The generated `tokens` object, with `accents` and `categoricalHues`, replaces the local copy. CSS reads the custom properties; only code outside the DOM (tests, canvas) reads `tokens`. |
| `IconX`, and app icons the kit lacks | `IconClose`, app icons | `IconX` becomes `IconClose`. An icon outside the kit chrome set stays an app icon, typed `IconComponent` (24 unit viewBox, `currentColor` stroke) so it sits beside the kit icons. |
| Local chart wrappers | `kit-core/charts` | `LineChart`, `AreaChart`, `BarChart`, `Sparkline` and `DonutChart` on recharts, an optional peer. Colours come from `useChartTheme`, never a prop. |
| Local API reference mount | `kit-core/api-reference` | `ApiReference` with `url` (or `content`). Import `api-reference.css` once after `kit.css`. Scalar is an optional peer. |
| Local node graph | `kit-core/graph` | `Graph`, `GraphNodeCard` and `graphEdge` on `@xyflow/react`, an optional peer. Import `graph.css` once after `kit.css`. |

