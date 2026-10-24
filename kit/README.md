# Kit

`@build-standards/kit` is the shared React kit for apps on this standard. It turns the rules in
[web-ui.md](../standards/web-ui.md) into components, so an app gets the shell, the primitives, the
overlays and the required chrome of section 25 by importing them instead of rebuilding them.

The kit is plain TSX with no runtime dependencies besides `react` and `react-dom` (18 or 19). It
has no build step. Apps consume the source directly and compile it with their own bundler.

## How an app consumes it

The overlay sync (`templates/overlay/scripts/sync-core.py`) copies `kit/src/` into the app as
`kit-core/`, next to `tokens-core/`, `lint-core/` and `standards-core/`. Never edit `kit-core/` by
hand. Fix the kit here and sync again.

1. Make the kit importable. Pick one, and use it for every app in the repo.

   **A monorepo with a pnpm or npm workspace (preferred).** The sync also writes
   `kit-core/package.json`, so the synced folder is a workspace package named `kit-core`. Add the
   folder to the workspace (`pnpm-workspace.yaml`: `- "standards-overlay/kit-core"`, or the
   `workspaces` array) and depend on it from the package that imports it (`"kit-core": "workspace:*"`).
   Then `import { Button } from 'kit-core'` and `import 'kit-core/kit.css'` work with no alias. Its
   `node_modules` and any `.tsbuildinfo` are outside the content hash, so installing never shows as
   drift. Delete a stale `tsconfig.tsbuildinfo` after the first install, or tsc keeps old errors.

   **A single app, no workspace.** Add a Vite alias so imports read the same in every app:


   ```ts
   // vite.config.ts
   import { fileURLToPath } from 'node:url';

   export default defineConfig({
     resolve: { alias: { '@kit': fileURLToPath(new URL('./kit-core', import.meta.url)) } },
   });
   ```

   Add the same path to `tsconfig.json` (`"paths": { "@kit": ["./kit-core/index.ts"] }`).

2. Import the style sheets once, in this order:

   ```ts
   import './tokens-core/tokens.css';
   import './tokens-core/hub-layer.css';
   import './kit-core/styles/kit.css';
   ```

   The package that holds the kit must declare `"sideEffects": ["**/*.css"]` in its own
   package.json (the kit's package.json does). Without it a bundler may tree-shake the style
   sheet imports as unused and ship the app unstyled. A plain `"*.css"` pattern only matches
   sheets at the package root, not `styles/kit.css`.

   Both `hub-layer.css` and `kit.css` sit inside one cascade layer, `@layer core`. Inside it the
   usual specificity and source order apply, so the look is the same as unlayered. Any unlayered
   app CSS beats the whole layer by default: a legacy `.btn`, `.tab` or `.shell` in the app keeps
   its own styles, and an override of a kit part needs no extra specificity. To put the core
   somewhere specific in an app's own layer order, declare it first, for example
   `@layer reset, core, app;`. `tokens.css` stays unlayered (it only defines custom properties).
   An app's bare element rules (`a`, `table`, `th`, `td`, headings) belong in a layer below the core
   (`@layer base, core;` declared first), or they restyle kit parts. Recipe in web-ui.md section 7.

   **Fonts ship with the kit.** `kit.css` declares `@font-face` for Geist and Geist Mono (variable
   woff2, weights 100 to 900, `font-display: swap`), the faces the type tokens name first. The
   files sit in `kit/src/fonts/` and the urls are relative to the sheet, so the bundler emits them
   as hashed files and the sync copies them with the rest of `kit/src/`. The licence
   (`GEIST-LICENSE.txt`, SIL Open Font License 1.1) is in the same folder and travels with them.
   Do not add a Google Fonts link for them. A consumer that copies `kit/src/` keeps the whole
   `fonts/` folder next to `styles/kit.css` (the woff2 files and `GEIST-LICENSE.txt`), because the
   `@font-face` urls and the licence terms both depend on them. Copying the sheet alone leaves the
   faces unresolved and drops the licence.

3. Mount the providers and the shell at the root:

   ```tsx
   <ThemeProvider>
     <AccentProvider accent="teal">
       <ShortcutLayer>
         <Toaster>
           <AppShell rail={<Rail ... />} header={<Header ... />} strip={<FeedStrip ... />}>
             {routes}
           </AppShell>
           <CommandPalette items={paletteItems} />
           <TooltipLayer />
         </Toaster>
       </ShortcutLayer>
     </AccentProvider>
   </ThemeProvider>
   ```

4. Inject `themeInitScript()` into `index.html` so a stored light theme applies before first paint: add `kitThemeInit()` from `kit-core/theme-init` (`@build-standards/kit/theme-init`) to the Vite plugins, which puts the kit's script first in `<head>`. Do not paste it: a pasted copy drifts. A build that cannot take the plugin runs `hasCurrentThemeInit(html)` from the same entry in a test. An app that defaults to `dark` or `light` passes the same value to `ThemeProvider defaultChoice` and `themeInitScript(key, default)`: a System pick is stored as `system`, so it survives that default.

Routing stays in the app. Pass your router's link component to `AppShell linkComponent` (it
receives `href`) and the current path to `AppShell pathname` so the mobile drawer closes on
navigation.

### Apps that share an origin

Local storage is per origin. When several apps are served from one origin (mounted under different
paths), give each one an id with `AppShell appId="<id>"`. The build card and the announcements then
use `shell.<id>.build.seen` and `shell.<id>.announce.dismissed`, so one app's seen version and
dismissed banners never leak into another. Theme (`shell.theme`) and rail pin
(`shell.sidebar.pinned`) stay one preference per browser. Without `appId` the keys are the shared
ones, as before. Kit parts mounted outside the shell (a banner on a page rendered elsewhere) read the
same scope from `<StorageScope appId="<id>">`, and `storageKeys(id)` returns the key names for
tooling. Pick a short id that never changes (a rename resets that state for users), for example
the route segment. An id is letters, digits, `-` or `_` (at most 64 characters, starting with a
letter or digit), and anything else (a dot, a space, a slash) throws, so two apps can never build
overlapping keys. An explicit `storageKey` prop still wins over the scope.

### Release notes for the build card

`scripts/gen-changelog.mjs` builds the What's new data from git history: `feat` becomes New, `perf`
Improved and `fix` Fixed, references are stripped, and a `Changelog:` line in the commit body
replaces the subject. Semver tags split releases. Run it in CI from a full-history checkout
(`fetch-depth: 0`) and import the file it writes:

```sh
node scripts/gen-changelog.mjs --out src/generated/changelog.json --version "$npm_package_version"
```

It fails when there is no history or no user-facing entry, so a deploy never ships a disabled
build card. When git is unavailable (a source upload) and the output file already has entries,
it keeps the file. `--path <dir>` (repeatable, relative to `--repo`) reads only the commits that
touch those folders, for an app inside a larger repository. `--allow-empty` (or
`CHANGELOG_ALLOW_EMPTY=1`) is for builds that only prove the app compiles, such as CI in a mirror
whose history has no conventional commits: it writes an empty What's new with a notice instead of
failing. Never set it for the build you ship. The overlay sync copies the script into the app's `scripts/` folder on every
sync, next to the other overlay scripts, so run it from there and never edit that copy.


### Build tooling for a multi-module shell

Three parts support a shell that mounts several modules (the web shell standard, sections 3 to 5).
The two scripts are copied into the app's `scripts/` folder on every sync, like
`gen-changelog.mjs`, so run them from there and never edit that copy.

- `scripts/scope-css.mjs`: `scopeModuleCss({ <sheet path>: <module id> })` is a PostCSS plugin that
  builds one module's stylesheet inside `:where([data-module="<id>"])`. Root tokens map onto the
  module element, keyframes and font faces stay global. Options: `root: 'document'` for a host that puts
  `data-module` on the document element (`:root` and `html` stay on it, `body` and `#root` stay
  descendants), and `keyframes: 'rename'` to prefix keyframes names and rewrite the `animation`
  references in the same sheet instead of warning.
- `scripts/build-registry.mjs`: generates the registry and its icon map from the module manifests,
  and `--check` fails when the committed file is stale. Run
  `node scripts/build-registry.mjs --manifests "modules/*/module.json" --out src/generated/registry.ts`.
  Opt in to host manifest keys with `--allow-keys a,b,x-*` (a name ending in `*` is a prefix), to host
  accent names with `--extra-accents brand`, and to host checks with `--validate-with check.mjs`.
  Without them an unknown key or accent is still an error and the output is unchanged.
- `ModuleManifest`, `RegistryEntry`, `GeneratedRegistry`, `ModuleDescriptor`, `ModuleRailEntry`,
  `ModuleFeedSource` and `ConfigureHost` (types, from the kit root): the manifest, the generated
  entry and the descriptor a module exports.
  `ModuleManifest`, `RegistryEntry`, `GeneratedRegistry` and `ModuleDescriptor` take optional type
  arguments for the host's own members and accent names, `ModuleDescriptor<TRoutes, TExtra, TAccent>`.

## An app's own component library

An app library (for example `@acme/ui` in a monorepo) is kept, not deleted, and becomes a layer on
top of the kit:

- It re-exports the kit (`export * from 'kit-core'`), so existing imports keep working while each
  part moves over.
- It deletes its copy of any part the kit ships (web-ui.md 0.11). Where a prop differs, it keeps a
  thin adapter that maps the old props onto the kit part, with a test, until the call sites move.
- It keeps what is unique to the app: org branding (the logo mark), app-specific screens, analytics,
  and domain widgets. These use the app's own class names, built from core tokens, never a kit class
  name. Charts, the node graph and the API reference are kit parts on their own entries (below), so
  the app drops its copies of those too.
- [MIGRATION.md](MIGRATION.md) maps the common old part names (`KpiTile`, `PanelHead`, `Confirm`,
  `Tooltip`, `Tag`, `Meter` and more) onto the kit part that replaces each.
- A part that other apps would need is promoted to the kit by a pull request here, then deleted from
  the app on the next sync.

Delivery is by copy (the sync), so this works the same whether the overlay moves by a CI workflow,
a nightly cron job or a manual run: nothing in the app library is ever overwritten by a sync.
## Components

Theme and accent

- `ThemeProvider`, `useTheme`: light, dark or follow the OS, persisted per browser, set as `data-theme` on `<html>`.
- `ThemeToggle`: flips the theme with a circle reveal from the button (View Transitions API), instant under reduced motion.
- `AccentProvider`, `setAppAccent(name)`: sets `data-app-accent` once on the root. Cobalt is the default and sets nothing.

Shell

- `AppShell`: icon rail, header, feed strip and content, with the mobile drawer below 900px and `data-rail` on the shell. The open drawer is a modal layer (Tab stays inside, the page does not scroll, global shortcuts and the palette pause). `appId` scopes per-app storage (see Apps that share an origin).
- `Rail`: the 58px rail that opens on hover or focus, pins with `[` or the pin button, and glides one marker to the active link. `footer` holds the build card and `status` one short line under it (for example a data refresh time), hidden while collapsed. Without `status`, `environment` (an accent badge) and `statusText` (organisation or other app text) build the standard line with `v<version>` between them, and `showVersion={false}` drops the version when the footer already shows it. An app `status` is rendered as given, so the version never shows twice. `brandSlot` renders next to the brand in the rail's brand row, for example a tool switcher in a multi-module shell (`standards/web-shell.md` section 10). `keepBrandSlotCollapsed` keeps the slot visible in the collapsed rail (default false, hidden). Never insert into the rail by finding its markup by class name.
- `ButtonLink`: an anchor styled as a `Button` (same `variant` and `size`), for a link that reads as an action. Its `href` goes through `safeHref`, so never hand-build a `btn` anchor.
- `safeHref(url)`: every kit link (`NavItem`, `Header` home, `DefaultLink`, `ButtonLink`) passes its href through it. Relative paths, `#` fragments and http, https, mailto and tel URLs pass. Any other scheme (javascript, data, vbscript and the rest, after trimming, control character stripping and case folding) returns undefined, the link renders as a plain anchor without an href and never reaches the router adapter, and development builds warn once.
- `NavGroup`, `NavItem`: grouped links with a hued icon (`brand` follows the accent) and `aria-current="page"`. `badge` is the main count, `softBadge` a secondary count in a quiet outline after it, and `working` adds a spinner to the soft badge (with `workingLabel` for screen readers). The badges hide while the rail is collapsed, its resting state, so `iconBadge` (a count, or `'dot'`) shows on the icon itself while collapsed; it defaults to a numeric `badge`.
- `Header`: the tool title, an optional subtitle and the one way home.
- `PageHeader`: page title, purpose, eyebrow and status. It takes no actions. The tinted header is opt-in with `wash` (or `data-wash` on a hand-written `.page-header`).
- `Toolbar`: the actions row above the content, Refresh first, with a ticking freshness label.

Primitives

- `Button`, `IconButton`: primary gradient with a spring press, secondary, ghost and danger, plus `success` and `warning` (solid deep fills) and `success-subtle`, `warning-subtle` and `danger-subtle` (status tint, hairline and ink). An icon-only button requires a label.
- `Card`, `CardHead`, `CardBody`: card with title left and controls right, optional tone or selection. `CardHead` takes `variant` (`card`, `panel` for a page region, `label` for a small group label), `count` and `level` (2, 3 or 4).
- `FormSection`: a fieldset with a legend and one muted description line, two columns of fields above the phone breakpoint.
- `ErrorState`, `errorDetail`: the load-failed block with the error's one line detail and a Retry button that spins while `retrying`.
- `SelectionBar`, `ListFooter`: the bulk action bar for selected rows, and the "Showing N of M" footer with a freshness label. `SelectionBar` also takes `run` (the `useBulkRun` state), `onCancel` and `itemNoun`, and then shows a named progress bar, Cancel while running, the per-item errors afterwards and a locked Clear while the run is active.
- `FilterPanel`: a form of typed filter cells (text, number and date ranges, select, multiselect, boolean and a lookup with an async loader) with Apply and Clear. It emits a neutral `{ key, op, value }` list (`FilterClause`) through `onApply`, seeds from `value`, and `buildFilters` and `draftFromFilters` are the pure halves. Cells are labelled, ranges and multiselects are fieldsets, and the lookup is a small local combobox (arrow keys, Enter, Escape, a status line, stale answers dropped). A lookup with `multiple: true` keeps several choices as removable chips (Backspace on an empty input removes the last) and emits one `in` clause of the chosen values, with the loader and keyboard behaviour unchanged. Without it the lookup is unchanged.
- `useBulkRun`: runs one task per item with a concurrency cap (default 4), progress, per-item errors and cancel (an `AbortSignal` for every task). `run(items)` resolves with the counts and `skipped`. Pair it with `SelectionBar`'s `run` prop.
- `Badge`, `Pill`: status and identity labels. Tones: neutral, accent, success, warning, urgent (the orange high-priority step), danger, info. `live` puts a spinner in the tone colour before the label for rows that are still working. `onRemove` makes a removable tag; `removing` turns its remove button into a spinner.
- `Spinner`: the working indicator, sizes xs, sm, md and lg, one turn per `--dur-spin`. Hidden from screen readers unless it gets a `label`, held still under reduced motion.
- `StatusDot`: a status mark, pulsing on success, with an optional text label. Takes the urgent tone too.
- `Tone`: wraps content in the `.tone` corner wash for a categorical hue.
- `HueTile`: an icon tile tinted by a categorical hue.
- `StatTile`: the only hero KPI primitive, with the deep fill, the glow recipe and a count-up that respects reduced motion.
- `FreshnessGrid`: one tile per source (label, state badge, age, stale threshold or last failure reason). The age ticks between polls (`tickMs`, default 15 s) and a fresh tile turns stale at its threshold on its own. `formatAge` and `liveFreshness` are the pure halves.
- `Stat`, `StatRow`: the light KPI card on the card surface (label, value with an optional status ink, hint, hue icon tile, optional click and selected ring) in a wrapping, labelled row.
- `FactRow`, `FactList`, `Disclosure`: label and value rows as a description list (mono, tone, hint, label width, a dash announced as None for an empty value, wraps on a narrow container, `tone` takes the neutral ranks and the status inks success, warning, urgent, danger, info, `style` passthrough over `--fact-gap` and `--fact-label-width`) and a button-controlled panel for secondary detail (uncontrolled or controlled, count, dense, `lazy` to mount the children only while open, `style` and `--disclosure-gap`).
- `Markdown`, `classifyLink`: a dependency-free, safe-by-default markdown reader (no raw HTML, no images, links only http, https, mailto and tel, relative document links through `onLink`).
- `Checkbox`, `Radio`, `RadioGroup`, `Switch`: native checkbox and radio inputs with a drawn box, a visible label, an optional description, `hideLabel`, `disabled` and `size` sm or md, a fieldset radio group with `options` or children, and a `role="switch"` button for settings that apply at once.
- `Tabs`, `TabPanel`: route-agnostic tabs with a pill variant, arrow keys, scroll into view and edge fades.
- `Segmented`: a small set of pressed buttons for ranges and views. An option may carry a `tone` (a dot and a tinted badge), a `badge` count and an `icon` (`iconOnly` keeps the label as the name and tooltip).
- `ChipGroup`: toggle chips where any number can be on (filters). `value` is the list that is on, `onChange` gets the new list in option order. Each chip is a button with `aria-pressed` in one named group, Tab reaches each chip, Space and Enter toggle, arrows move focus only. An option may carry a `tone` (a dot and a tinted pressed chip), a `badge` and `disabled`. Chips wrap on a narrow screen.
- `Field`, `Input`, `Select`, `Textarea`: a visible label, a hint, and an inline error wired to `aria-invalid` and `aria-describedby`. `Input size="sm"` matches the Segmented height for compact toolbars (a number is still the native width). `Select labelledBy` names a select by the id of visible text outside a Field.
- `Table`: sortable headers with `aria-sort`, filter then sort, sticky head, keyboard row focus and an empty state. `rowClassName(row)` and `rowProps(row)` tint or tag rows, and `sort` with `onSortChange` makes the sort controlled (uncontrolled stays the default). With `onRowActivate`, a click or Enter on a control inside a cell (button, link, field, label, a menuitem, checkbox or button role, contenteditable, or anything under `[data-no-row-activate]`) stays with that control and never activates the row, and neither does an event a handler already called `preventDefault` on. `selection` (from `useRowSelection(visibleIds)`) adds the select-all header and row checkboxes; pair it with `SelectionBar`. `density="compact"` tightens the row padding for long lists on a fine pointer; a touch screen keeps the comfortable rows.
- `ListTable`: the list shaped sibling of `Table` for a master pane. Each row is a list item with a `primary` line, an optional `secondary` line and `leading` and `trailing` slots. `groupBy` nests rows under named group headers. `selectedKey` marks the open row (`aria-current`) that a detail pane shows, `selection` (from `useRowSelection`) adds a checkbox per row and a select-all header that goes indeterminate over the rows on screen, and a checkbox never opens its row. Arrow keys, Home and End move between rows, Enter or a click opens one. Order is the caller's: sort and filter before passing rows.
- `Pagination` with an unknown total (a server paged list): leave `total` out or pass null and it reads "Page N, N on this page" from `itemCount`. Next follows `hasMore` when given, else it is on for a full page (`itemCount` equal to `pageSize`) and off for a short one. `onPage(page)` gets the target page for Previous and Next when `onPrev` or `onNext` is not given. A known total reads as before.
- `usePagination(total, size)` keeps page and size (pass null for an unknown total and the page is not clamped), slices the rows, keeps the first row on screen when the size changes and pulls the page back when the total shrinks.
- `SplitLayout`: a list pane and a detail pane with a resize handle (a focusable separator: arrows move it 16 pixels, Shift 64, Home and End go to the bounds, Enter or a double click resets, dragging works too). The detail pane keeps a minimum width. Under `stackBelow` pixels (720), measured on the layout itself, the panes stack, the handle goes away and the list is capped in height. `width` and `onWidthChange` make the width controlled.
- `EmptyState`, `StickFigure`: empty states with an icon tile or a mascot pose.
- `Skeleton`: loading placeholders for lines, cards, tables and lists (`variant="list"`).
- `TooltipLayer`: one layer for every `data-tip` on the page, placed by `data-tip-side` (top, bottom, right or left). A native `title` is adopted on first hover or focus: the text moves to `data-tip`, and a control with no other name keeps it as `aria-label`.
- `MonthGrid`: a generic month calendar: weekday headers, day cells, event chips with "+N more", a today marker and roving keyboard navigation (arrows, Home, End, PageUp, PageDown). Dates are ISO day strings. Events arrive as a list; `renderEvent`, `renderDay` and `dayHint` are the slots, and the rules about what an event means (coverage, shifts) stay in the app. Known limit: an event sits on its one `date`; multi-day events (a span across cells or weeks) are not supported, so an app splits one into an event per day.
- `ProgressBar`: a determinate bar or an indeterminate one, in five tones. `meter` makes it a meter for a measured value rather than task progress. `segments` draws a stacked bar (for example done and in progress); the spoken value lists each part.
- `TextDiff`: a read-only line diff of two texts with real `+` and `-` markers. `lineNumbers` adds an old and a new line number gutter (decoration only, hidden from assistive technology and not selected on copy, sized to the widest number). `diffLines` is the pure core and now returns `oldNumber` and `newNumber` per line.
- `useMediaQuery`, `useIsPhone`, `useColorScheme`: media query hooks on the kit breakpoints (`PHONE_QUERY`, `SHELL_QUERY`), and the resolved light or dark scheme.
- `Avatar`: initials on a stable hue derived from the name. A directory name written "Last, First" reads as "First Last" and a trailing note in parentheses is ignored.
- `usePolling`: load now and refresh on an interval; pauses while the tab is hidden and refreshes once on resume (`web-client-runtime.md` 3.8), never overlaps itself, keeps the last good data on a failed poll.
- `Avatar`: initials on a stable hue derived from the name.
- `IconCalendar`, `IconClock`, `IconEdit`, `IconEye`, `IconEyeOff`, `IconFolder`, `IconList`, `IconMail`, `IconTrash`: generic icons next to the chrome icons, 24 unit box, 2 unit stroke, `currentColor`, decorative by default, `size` prop.
- `Combobox`, `PersonOption`: one typeahead chooser over an async `search(query, signal)`, with a debounce, stale replies aborted and dropped, loading, empty and error (with retry) states, the ARIA combobox keyboard pattern and an Escape that closes only the list, so a dialog around it stays open. `renderOption` is the row slot: a person picker is `PersonOption` rows (an `Avatar`, name, detail, meta). `clearOnSelect` and `excludeKeys` serve a picker that builds a list. Arrow keys wrap and the input is as tall as the rows (44px) on a coarse pointer. When the lookup cannot work (`search` rejects with `UnavailableError`, or `onSearchError` returns `'unavailable'`) the input becomes a validated free entry field: a one line hint (`messages.unavailable`), `validate(text)` (a message string or false is invalid), and Enter adds `{ free: text }` through `onSelect` (type it `Combobox<Item, ComboboxFreeEntry>`). `defaultUnavailable` starts there.
- `ListControls`, `GroupHeader`: the filter, sort and group bar above a list, with `applySort`, `applyGrouping`, `paginate` and `usePagedState` for the data. `Pagination` takes `onPageSizeChange` for a rows-per-page select and `loading`.
- `Kbd`: a key cap.

Overlays

- `Modal`, `ModalSection`: portal, focus moved in and trapped, focus restored, Escape on the top dialog, scroll lock, sheet variant. `onClose(reason)` receives `'escape'`, `'backdrop'` or `'close'` (the close button and Cancel), so a nested step can back out on Escape only. When the focused node inside unmounts, focus returns to the panel. Sizes sm, md, lg, xl, `wide` and `full`. `hideHead` drops the head row and keeps the name (a string title becomes `aria-label`, any other title a hidden heading). `data-*` and other attributes pass through to the panel. `meta` puts badges beside the title, outside the dialog's accessible name; `primaryAction.icon` adds an icon to the button.
- `RecordPreviewProvider`, `RecordChip`, `useRecordPreview`, `createRecordRegistry`: a labelled record preview dialog. The host registers a loader and a body per record type, chips and the hook open it, with a skeleton (or an optional per type `seed` painted at once and merged with the live load), an error with Retry and a body boundary. A body gets `reload` and an optional open `context`.
- `useConfirm`: a promise-based confirm with a question title, a consequence body and a verb button. `confirm({ action })` runs the action inside the dialog (busy confirm button, Cancel and Escape held while it runs, a rejection shown inline with the dialog kept open for a retry, true only after success); `validate` returns an error string to keep the dialog open.
- `usePrompt`: a promise-based prompt that resolves the trimmed value or null.
- `Toaster`, `useToast`: the toast stack, with one action per toast for Undo. Toasts dedupe by `id` only: a toast with the id of one on screen replaces it in place with a fresh timer, and calls without an id always stack, whatever the text.
- `Popover`, `Menu`: an anchored panel and an action menu with arrow keys. Opening the menu (click, Enter, Space or ArrowDown on the trigger) focuses the first enabled item, ArrowUp the last. Panels portal into one body-level layer root (`layerRoot()`, a labelled region hidden while empty), never into `<main>`, so a transform an app animates on `<main>` cannot move a fixed panel off its trigger. Pass `container` to place one elsewhere.

Required chrome

- `ErrorBoundary`, `PageErrorBoundary`: the crash screen. `ErrorBoundary` is the app level screen (Reload, Reset session). `PageErrorBoundary` keeps a crash inside the page and clears when its required `resetKey` changes, so a host keys it by the route. Both take `fallback` and `onError`.
- `CommandPalette`, `SearchTrigger`, `openCommandPalette()`: Cmd or Ctrl and K, a bare `/` outside text fields (`slashOpens`, `isSlashOpen`) or the open event (all ignored while another dialog is open), substring filter with the match highlighted, Escape from anywhere. `onQueryChange(query)` feeds async results. `SearchTrigger compact` is icon-only (`"auto"` below 640px), with the shortcut kept in its accessible name.
- `CommandPalette` grouping and ranking: `PaletteItem.group` renders headers (groups in first-appearance order), `filters` adds tabs cycled with Tab and Shift+Tab (`allLabel` names the first), and `shortcut` shows keys on the row and registers them in `ShortcutLayer` so the help sheet lists them. Matches rank exact label, prefix, word start, substring, keyword, kind (`scorePaletteItem`, `groupPaletteItems`). A custom `rank` and `limit` work inside the active tab; with a `toolbar`, Tab moves into the toolbar and the filter tabs sit in the tab order instead.
- `CommandPalette` options: `preview(item)` renders a read-only pane beside the list for the active row (`previewLabel` names it, hidden at 640px and below). `scope` makes a palette answer Cmd or Ctrl and K (and `/`) only inside a region spread with `paletteScope(name)`, and the global palette then ignores the shortcut there. `openScopedPalette(name)` opens it from outside. `paletteOwnsKey(scope, target)` is the rule itself.
- `CommandPalette` ranking and rows: `rank(query, items)` replaces the substring filter (it gets the raw query, an empty one included, and returns the order to show, so the host owns the empty-query order). `limit` caps the rows (default 50, `Infinity` shows all, and it applies to a custom `rank` too). `toolbar` is a slot under the search field for filter chips, in a group named by `toolbarLabel` (default Filters), and keys pressed inside it never move or open a result. `PaletteItem` takes an optional `description` (a second, one line row) and `badge` (a status mark at the right end, text rather than colour alone). With none of these set the palette is unchanged.
- `useTileReorder`, `TileReorderStatus`, `TileOrderStore`: drag reorder for dashboard tiles with Alt and arrow key moves, a live region announcement and a saved order kept per person. The host implements `TileOrderStore` (`read` and `write`, either may be async or fail) and spreads `tileProps(id)` on each tile wrapper. `reconcileOrder(saved, catalog)` drops removed ids and appends new ones, `moveInOrder` and `placeInOrder` are the pure moves, `createMemoryTileOrderStore` is the reference store. Hidden tiles (`hidden`) keep their place and are skipped. `endZoneProps` goes on an element after the last tile (it spans the grid row, `aria-hidden`, with `data-drop-target` while a tile is over it): a drop there moves the tile last. `edge` (`true` or `'x'` horizontal, `'y'` vertical) reads the cursor against the tile midpoint so a drop lands before or after it, and `data-drop-edge` (`before` or `after`, only on the tile under the cursor) drives the indicator (the tile keeps its outline and the half the drop lands in is tinted). In a right to left list the horizontal sides flip. Off by default, so a drop on a tile still takes its place.
- `ToolSwitchButton`, `ToolLauncher`, `useToolLauncher`: the tool switcher. The button goes in the Rail `brandSlot` (a `prominent` variant is for a screen with no rail, `variant="mark"` is the mark with a corner chip, and `collapsible` turns the rail form into that mark while the rail is collapsed, paired with `Rail` `keepBrandSlotCollapsed`) and opens a full window `Modal` carousel of plain `LauncherTool` data (id, name, tagline, description, hue, mark, `external`). Arrow keys, Home, End, buttons, dots, swipe and the `t` shortcut move and open it, it advances slowly on its own and holds on hover, focus and interaction, and under reduced motion nothing moves by itself. `slideOffset` and `openToYouLabel` are the pure helpers.
- `AccountMenu`: the signed-in account for the Rail footer. Plain `AccountIdentity`, `AccountFact` rows and `AccountLink` data, the Light, Dark and System choice, safe new tab links and Sign out (`onSignOut`, an inline alert when it rejects). Needs `ThemeProvider` unless `showTheme={false}`.
- `BuildCard`, `ReleaseNotesDialog`: live dot, rolling version, New pill and the What's new dialog.
- `FeedStrip`: the presenter with the mascot, dots, pause and search, and a health line that is always shown.
- `AnnouncementBanner`, `AnnouncementStack`: dismissible tone banners, persisted per id. Every banner on the page shares one dismissed list (a dismiss re-reads storage and merges, other tabs sync through the storage event). The stack hides dismissed banners before it orders and caps the list to five, so a dismissal lets the next one in. `action` adds one link (class `announce-link`) or small button, and `dismissible: false` hides dismiss for alerts that clear themselves.
- `ShortcutLayer`, `useShortcut`: the shortcut registry and the help dialog on `?`.
- `HubHome`: the hub home layout, three zones (strip, main pair, side) for keyed blocks, ordered and filtered by a `tiles` list, with no gap for a hidden or empty block. Zones default to `waiting` and `actions`, `live` and `fleet`, then `pinned` (`DEFAULT_HUB_ZONES`). It answers to the width of the page area (container queries), not the window.
- `FeedBlock`, `ActionsBlock`, `PinnedBlock`: the hub home blocks. They take plain data: `HomeTool` (id, name, mount path, hue), `HomeFeedSource` (a tool, a `loading`, `error` or `ready` status and `HomeItem` rows with label, detail, time, value, tone and route) and `HomeAction`. A skeleton shows while a source is loading, one quiet line per source that could not be read, an empty state when nothing is left. `PinnedBlock` takes a `PinsStore`, the `recents` and an optional `reachable` set of module ids. Rows are `HubLink` anchors that call `go(href)` on a plain click, with `homeHref(tool, route)` building the address. `ToolChip` and `HomeItemRow` are the shared pieces.
- `PinButton`, `PinsStore`: the header control that pins the current page to the hub. The host implements `PinsStore` (`snapshot`, `subscribe`, `pin` and `unpin` resolving to null or one sentence, optional `load`) and the control renders nothing until the store is `ready`, and nothing when it is `denied`. At `max` pins it is disabled with the reason. `pageAt(pages, pathname)` finds the declared page a path is on, `createMemoryPinsStore` is the reference store, and `usePins(store)` reads one. `addRecent` and `sanitizeRecents` are the pure helpers for the recents list a host keeps.

Charts

- `chartTheme()`, `useChartTheme()`: axis, grid, tooltip and series colours read from the live CSS variables.
- `categoricalPalette()`, `categoricalHueNames()`: the six categorical hues minus the hue named by `--accent-withheld-hue` (`none` withholds nothing).
- `CATEGORICAL_HUES`, `EXTRA_HUES`, `isCategoricalHue`, `isMarkHue`: the six series hues (`CategoricalHue`) and the two extra hues (yellow and ink, the solid neutral) that data takes by name only. Every `hue` prop takes a `MarkHue` (both sets), the rotation, the avatar hash and the withholding use only the six.

Optional entries

Each lives behind its own entry, on an optional peer dependency, so an app that never draws one
never installs or bundles it. The kit root keeps zero runtime dependencies.

- `kit-core/charts` (recharts): `LineChart`, `AreaChart`, `BarChart`, `Sparkline`, `DonutChart` and `ChartTooltip`, coloured by `useChartTheme` and the categorical hues, never by a prop. The same entry holds `ChartLegend`, a standalone named-list legend for a chart you compose yourself (items `{ label, color?, line? }`, a missing colour takes the next categorical hue), and `Gauge` (half ring) and `RingProgress` (full ring with a label and sub label): single-value meters (`role="meter"`, named by `label`, value text in `aria-valuetext`) that clamp `value` to 0 through `max`, take their tone from `thresholds` (warning and danger values in the units of `value` and `max`, higher worse unless `higherIsBetter` flips it) or a fixed `tone` (`accent`, `info` for a colour that is not a status, `success`, `warning`, `danger`), colour from the status tokens, and travel on `--dur-travel`, with no animation under reduced motion.
- `kit-core/graph` (`@xyflow/react`): `Graph`, `GraphNodeCard`, `graphEdge` and `graphNodeTypes`. Import `kit-core/graph.css` once after `kit.css`.
- `kit-core/api-reference` (`@scalar/api-reference-react`): `ApiReference` renders an OpenAPI document from `url`, `content` or `fetchSpec`, themed by the kit tokens and following the kit theme. It sets no fonts, sends no telemetry, shifts the document's headings under `headingLevel` and turns Scalar's own main landmark into a named region inside the page main. Import `kit-core/api-reference.css` once after `kit.css`.

## Rules the kit enforces by shape

- No edge bars. Tone is `.tone` with a `.hue-*` class, and selection is `.is-selected`.
- No native dialogs. `useConfirm`, `usePrompt` and `useToast` replace them.
- Every colour, radius, shadow, duration, easing and z-index is a token. `kit.css` adds base looks
  only, on top of the `hub-layer.css` recipes.
- The accent is written in one place (`setAppAccent`), on the root.
- Nothing branches on theme. A theme is a token swap.
- `PageHeader` takes no actions, `Header` holds the one way home, and `IconButton` requires a label.
- `StatTile` is the only hero KPI, and its count-up always lands on the real value.

## Checks

From `kit/`:

```sh
npm ci
npm run typecheck      # the kit, the tests and the gallery under strict TypeScript
npm test               # unit tests, axe in both themes, and a static scan of src/
npm run gallery:build  # generates release notes from git history and builds the gallery
npm run check          # all three
```

From the repo root, the core checks cover the kit too:

```sh
python3 lint/ui_lint.py kit/src
python3 checks/check-css-vars.py tokens kit/src
```

The axe test disables only the color-contrast rule, because jsdom cannot compute rendered colours.
Contrast is certified on the tokens by `tokens/build.py --check`.

## Gallery

`npm run gallery:dev` serves every component on one page with a theme switch and an accent
switcher across the named accents. Each specimen section has a stable id (`specimen-*`) for
screenshot comparison.
