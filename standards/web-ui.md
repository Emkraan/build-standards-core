# Web UI Design System

Version: 4.0 | Last reviewed: 2026-10-13 | Status: current | Scope: web (first-party)

**Canonical source:** this repo. This doc is the source of truth. Where a reference implementation differs, the implementation
is fixed, or the consumer records an explicit exception (README, "Source of truth and explicit
exceptions").
**Applies to:** all first-party web apps and internal tools. Desktop (PowerShell/WPF)
tools use the [Design System - WPF / PowerShell Edition](wpf-design-system.md), which
translates the same DNA (see [section 10](#10-wpf--powershell-translation-desktop-tools)).
**Companions:** [First-Party Build Standard](web-build.md) (architecture,
API, auth, RBAC, verification gate).

**Implementation.** Values live in `tokens/tokens.json` (generated into `tokens/tokens.css`), the
behavioural recipes in `tokens/hub-layer.css`, and the React components in the kit (`kit/src/`,
synced into apps as `kit-core/`, see `kit/README.md`). Every custom property this doc names exists
in one of those three places, and `checks/check-token-names.py` fails the core build when one does not.

**One statement per rule.** Each rule is stated once, in the section listed below, and every other
section links to it instead of repeating it. Section numbers are stable because rule ids and
exceptions name them.

| Group | Sections |
|---|---|
| Rules | [0](#0-the-rules-non-negotiable) |
| Foundations | [1 DNA](#1-design-dna), [2 colour](#2-color-tokens), [3 Tailwind](#3-tailwind-class-map), [4 type](#4-typography), [5 geometry](#5-geometry--elevation), [14 motion](#14-motion), [16 accent tokens](#16-one-accent-token-per-app), [17 hues, tone, selection](#17-categorical-hues-tone-and-selection) |
| Components | [7 primitives](#7-shared-primitives), [8 charts](#8-charts), [18 stat tile](#18-stat-tile-glow-and-count-up), [27 help layer](#27-the-help-layer) |
| Shell and patterns | [6 shell](#6-shell-layout), [11 mobile](#11-mobile--responsive-shell), [13 search palette](#13-global-search-palette), [19 rail](#19-the-desktop-icon-rail), [20 announcements and feed](#20-announcements-the-pulse-feed-and-the-presenter), [22 build card](#22-build-card-and-release-notes), [23 undo and confirm](#23-reversible-actions-undo-irreversible-ones-confirm), [24 chrome accessibility](#24-shell-chrome-added-by-the-behavioural-layer), [25 required chrome](#25-required-chrome-what-every-app-with-a-sidebar-must-mount) |
| App types | [10 WPF](#10-wpf--powershell-translation-desktop-tools), [12 accent and plain-CSS port](#12-per-app-accent-and-plain-css-port), [21 system health](#21-system-health-request-analytics) |
| Engineering | [9 verification gate](#9-verification-gate-before-done) |

---

## 0. THE RULES (non-negotiable)

1. **No edge-bar accents, on any side.** Never draw a coloured bar, stripe, tab or thick single-side
   border on any edge of an element (left, right, top or bottom) to carry colour, status or
   selection. It reads as a generic template signature and overrides any reference or mockup that
   shows an edge indicator. The UI lint enforces it (UI001). Use instead:
   - **Tone** for identity, status and severity ([section 17](#17-categorical-hues-tone-and-selection)).
   - **Selection** for the active nav item, tab, row, result or chip
     ([section 17](#17-categorical-hues-tone-and-selection)).
   - **Small items** (calendar chips, table rows, badges): a tinted fill, a full tinted outline, or
     a status dot. Round category dots are fine anywhere.
   - **Data marks are not accents:** a chart "today" line, a timeline connector or a milestone
     pole is data. Put `edge-ok` in a comment on that line (or the line above).
2. **Accent discipline.** The app accent ([section 16](#16-one-accent-token-per-app)) is reserved
   for **brand, primary CTA and active state** only. It is never a generic categorical or
   data-series colour. When an app's accent sits within 30 degrees of hue of a categorical hue,
   that hue is withheld from data in that app (`--accent-withheld-hue`, applied by the kit's
   palette helper), so brand and data never share a colour. Exception: the **status** ramp maps
   in-progress to the accent (a semantic "active" status, used consistently in Gantt, Kanban and
   nav). Things that are NOT accent-coloured: role badges (violet), avatars (`hueFor`), decorative
   icons, informational pills, and hover on plain links (links brighten to `--text-primary`, only
   primary buttons and active markers take the accent).
3. **One glow recipe.** Glow is a single theme-gated recipe, a `box-shadow` driven by the
   element's `--hue` and the theme-gated `--glow-a` alpha
   ([section 18](#18-stat-tile-glow-and-count-up) holds the recipe). It is applied ONLY to these
   named uses: hero KPI tiles, the active nav marker, selected cards, chart bars, the search field
   focus ring glow (beside the focus ring, never replacing it), the progress bar fill glow, and the
   brand mark glow (the art mark glow layer, `.art-mark .am-glow`). The rule is closed to any other
   glow (meter fills, flow graph nodes and status dots carry none). Never per row or on ordinary
   cards, whose hover uses lift and a neutral shadow.
4. **One stat system.** Hero KPIs use the kit's `StatTile` only
   ([section 18](#18-stat-tile-glow-and-count-up)). No second parallel stat-card implementation may
   co-exist on any surface.
5. **Contrast is a release gate.** Text clears WCAG AA (4.5:1 small, 3:1 large) in BOTH themes on
   every surface it can sit on, including tiles at their gloss peak. Bright hues used as small
   text on light surfaces take the darkened light-theme token values. Custom accents are generated
   and certified, never hand-picked ([section 2](#2-color-tokens) says how).
6. **Actions live with the content they act on.** The page header (title and subtitle) carries no
   buttons. Add, Import, Export, Sync and Refresh go in a toolbar row directly above the table,
   card grid or list they affect (right-aligned, usually sharing the search and filter row), or in
   that card's `card-head`. Do not hide create actions behind a "Manage" mode toggle: the primary
   create action is always visible to anyone permitted, as a primary button with a verb label
   ("Add Vendor"). Row edit and delete icons show whenever the user has permission. A mode toggle
   is only acceptable where always-on edit chrome would clutter a dense grid, and then it is
   labeled with what it does ("Edit links" / "Done editing"), never "Manage". Refresh is an
   icon-only secondary button with `aria-label` "Refresh", placed first in the toolbar. Status
   badges (for example "Webhook configured") may stay in the header.
7. **The app owns every dialog.** No browser-native `confirm`, `prompt` or `alert`: use the kit's
   `useConfirm`, `usePrompt` and `useToast` ([section 7](#7-shared-primitives)). The UI lint fails
   on native dialogs (UI002). The one exception is the `beforeunload` guard for unsaved work when
   a tab closes: browsers do not allow styling it.
8. **Undo over "are you sure".** A small, reversible change (remove an assignment, deactivate a
   party) applies immediately and the toast offers Undo. A destructive or irreversible change
   (delete a schedule, revoke a key) asks first with a danger confirm: the title is a question,
   the body states the consequence in plain words, the button is the verb ("Delete"). The
   acceptance test is in [section 23](#23-reversible-actions-undo-irreversible-ones-confirm).
9. **One way home.** Only the header home button navigates to the app home. Logos,
   breadcrumbs and grid icons are not links. For a single app, home is its landing page. For a
   shell that mounts several tools, home is the hub (the shell's landing page), and each mounted
   tool has no home button of its own. The header mounts the button (the kit's `Header` `home`
   prop); without it the kit renders none and nothing else fails, so it is a row in
   [section 25](#25-required-chrome-what-every-app-with-a-sidebar-must-mount).
10. **Content stays inside its box.** Text never escapes, or is cut off by, the control, chip or
    card that holds it, at any width the app supports. Three habits keep it that way:
    - Controls size with `min-height`, never a fixed `height`, so an extra line grows the box
      instead of spilling out of it. The kit's `.btn`, `.hub-btn`, `.badge` and `.tab` do this.
    - A single-line control holds a single line. A label that can outgrow it truncates with an
      ellipsis and carries the full text in a tooltip. A choice with a title and a description
      is a card-style option (an app class, or a radio group with descriptions), never a button.
    - An element never borrows a kit control class (`btn`, `hub-btn`, `badge`, `tab`, `seg-btn`,
      `input`, `select`, `kbd`) as a hook and then restyles its box inline. The kit recipe
      (minimum height, `nowrap`, `line-height: 1`, centring) still applies wherever the inline
      style is silent, which is how a two-line option ends up centred with its description
      hanging out of the bottom. Use the kit component as it is, or a class of the app's own.
      The UI lint flags the borrowed class (UI009).
    The rendered check is `kit/scripts/overflow-probe.mjs` (section 9).
11. **A UI consumer adopts the UI whole, or it is not consuming it.** Syncing the overlay is not
    adoption. An app that uses the core UI uses the shell, the tokens and the kit as shipped:
    - **No parallel theme.** No local stylesheet redefines a core token (UI010), switches on the
      theme (UI008) or sets an accent token (UI007). The accent is chosen once with `data-app-accent`.
    - **No local copy of a kit part.** A button, table, dialog, toast, palette, shell or rail that the
      kit provides is the kit's, not a hand-rolled one.
    - **Adoption is counted through the kit.** A thin adapter that keeps the app's import names while
      a kit part renders underneath counts as adoption (`kit/MIGRATION.md`, step 0): it forwards to
      the kit and no call site moves. A local part that duplicates a role the kit provides, such as
      a hand-rolled spinner, banner, badge, palette or rail, does not count however good it is: it
      is a stand-in to retire. There is no adoption percentage and no baseline to park a UI consumer
      on: `core-status.py` reports `adopted` or `partial`, and the lint runs at zero findings.
    - **Extend downstream, never by forking.** An app may compose kit parts, add pages and add
      app-specific components with their own classes, built from the tokens. An addition never
      restyles a kit part or borrows its class (0.10). When the kit lacks something an app needs, the
      app opens a pull request on the core and builds with the core's answer, not around it.
    - **No lint baseline.** The UI lint runs at zero findings. The only suppression is a named
      exception in `standards-local/exceptions.md` with an owner, a reason and a review date, marked
      on the line with `core-exception`.
    A consumer that carries no record of the core and takes the UI as a vendored package (scrubbed
    names) has no `kit-core`. It proves adoption with the release and the content hash of the
    unscrubbed source, recorded by the vendoring tool on the operator machine and read by
    `core-status.py`; the hash, not the scrubbed copy, is the measure of how far behind it is.
    `core-status.py` reports a UI consumer `adopted` only when the kit is imported from `kit-core`,
    no local stylesheet redefines a token, and the lint has zero findings and no baseline.
    Otherwise it reports `partial`, and the drift check fails. The migration order is in
    `kit/MIGRATION.md`.

12. **Boards and wide tables keep their own scrollbars.** On a short window a board or a wide table
    stays scrollable on screen instead of being squeezed or clipped:
    - The page body is one vertical scroll container (the kit's `page-scroll` class: full height,
      `overflow-y: auto`), so content taller than the window scrolls the page.
    - A board is sized to the window with a floor (`LaneBoard` `fit`: the window height less 6rem, never
      under 360px). It scrolls sideways on its own edge and each lane scrolls vertically on its own.
    - A wide or long table gets a capped scroll area with a floor (`Table` `capped`: at most the window
      height less 15rem, no floor, so a short table stays short). The area is a named, focusable region so the keyboard can
      scroll it.
    - Never cap a page header with a viewport fraction (`max-height` in `vh`): on a short window the
      content below it is squeezed to nothing. The header keeps its natural height and the page scrolls.
    - Never put `overflow: hidden` on a flex parent to make a board fit: it removes the very scrollbars
      the board needs. Use `min-height: 0` on the flex child and let the child scroll.
    The proof: load every route that has a board or a wide table at a window about 700px tall (and at
    the narrowest supported width) and confirm the page scrolls, the board shows its sideways scrollbar
    and each lane scrolls, and the table shows its own scrollbars with the header still in view. A
    route with no board or wide table has nothing to prove.

---

## 1. Design DNA

Deep near-black canvas where cards genuinely float (clear luminosity separation and a soft shadow),
a disciplined multi-hue categorical palette under the app accent, hero gradient stat tiles,
theme-aware gradient charts, a bento of titled cards (title left, controls right), an icon rail
with one gliding active marker, status pills, and segmented toggles.
Light AND dark are first-class. Everything themes through CSS-variable tokens, and a theme is a
token swap with no component branching (UI008).

---

## 2. Color Tokens

**Source of truth:** `tokens/tokens.json`. `tokens/build.py` generates `tokens/tokens.css` (the CSS
custom properties every app imports), `tokens/tokens.ts` (resolved values for code outside the
DOM), `tokens/tailwind.preset.cjs` (the same tokens for a Tailwind build), the WPF dictionaries in
`tokens/wpf/`, and `tokens/CONTRAST.md` (every certified ratio). This doc quotes token names, not
values. Where a value is quoted, `tokens.json` wins. Never write a colour literal in an app (UI003).

| Group | What it holds | Key tokens |
|---|---|---|
| Surfaces | A luminance ladder. Dark steps up in lightness as elevation rises. Light puts white cards (`--surface-1`) on a light grey canvas, and the steps above surface-1 descend from white for states on a card | `--bg-canvas`, `--surface-1` to `--surface-5`, `--surface-inset` |
| Elevation | Six steps: hairline ring, same-angle key shadows, 1px top highlight, plus named shadows and the accent washes for recipes (`--card-sheen`, `--header-wash`, `--canvas-wash`) | `--elev-0` to `--elev-5`, `--shadow-glow`, `--shadow-xs`, `--shadow-key`, `--shadow-lift`, `--shadow-pop`, `--shadow-inset-top`, `--card-sheen`, `--header-wash`, `--canvas-wash`, `--backdrop`, `--scrim` |
| Borders | Hairlines plus the certified form-control boundary | `--border-subtle`, `--border-default`, `--border-strong`, `--border-field` |
| Text | Four inks certified on every surface | `--text-primary`, `--text-secondary`, `--text-tertiary`, `--text-quaternary` (lowest emphasis, AA on the page, card and raised panel), `--text-inverse` |
| Accent | A nine-step ramp plus role tokens, one per app ([section 16](#16-one-accent-token-per-app)) | `--accent`, `--accent-hover`, `--accent-bright`, `--accent-dim`, `--focus-ring` |
| Status | Ink, tint and border per status, deuteranopia-separated | `--success`, `--warning`, `--danger`, `--info` with `-dim`, `-border` |
| Categorical | Six data hues in a series rotation plus two extra hues taken by name (yellow, ink), bright identity plus deep tile stop ([section 17](#17-categorical-hues-tone-and-selection)) | `--hue-<name>`, `--hue-<name>-d`, `--glow-a` |
| On fill | Inks and overlays for content on a deep tile or the accent fill, mode-invariant, text certified at the gloss peak | `--on-fill-label`, `--on-fill-hint`, `--on-fill-chip`, `--on-fill-line`, `--on-fill-gloss`, `--on-fill-shade` |
| Scales | Radii, spacing, type, tracking, motion, stacking, layout | `--radius-*`, `--space-*`, `--fs-*`, `--track-*`, `--dur-*`, `--ease-*`, `--z-*`, `--sidebar-w`, `--topbar-h` |

**Colour and triplet tokens.** Most colour tokens are complete colours, used as `var(--surface-2)`.
The categorical hues and the `-rgb` tokens (`--hue-blue`, `--accent-rgb`, `--surface-1-rgb`,
`--canvas-rgb`) are space-separated triplets for alpha composites, used as
`rgb(var(--hue-blue) / 0.2)`.

**Modes.** Dark is the base. Light is a token swap with the same names, so no component branches
on theme. `html[data-theme="light"|"dark"]` is an explicit choice, no attribute follows the OS, and
print is always light. The generator writes every mode block from one declaration, so the blocks
cannot drift.

**Contrast is computed, not claimed** (rule 5). `build.py --check` runs in CI and fails the build
when a value drops below its rule: text inks 4.5:1 on every surface, coloured text 4.5:1 on content
and hover surfaces, white on every fill 4.5:1, form boundaries, focus rings and data marks 3:1.

**Acceptance:** static. `python3 tokens/build.py --check` exits 0 in the core. An app imports
`tokens.css` once and contains no colour literal outside it (`ui_lint`).

---

## 3. Tailwind Class Map

A Tailwind build uses the generated `tokens/tailwind.preset.cjs`
(`presets: [require("./tokens-core/tailwind.preset.cjs")]`) and imports `tokens.css`. Every key
maps onto a token, so a class never carries a value of its own:

| Theme key | Classes | Tokens |
|---|---|---|
| `colors` | `bg-canvas`, `bg-surface-1` to `bg-surface-5`, `bg-surface-inset` | surfaces |
| `colors` | `text-ink-primary`, `text-ink-secondary`, `text-ink-tertiary`, `text-ink-quaternary`, `text-ink-inverse` | text inks |
| `colors` | `border-line`, `border-line-subtle`, `border-line-strong`, `border-line-field`, `border-line-accent` | borders |
| `colors` | `bg-accent`, `bg-accent-hover`, `text-accent-bright`, `bg-accent-dim`, `bg-accent-50` to `bg-accent-800` | accent |
| `colors` | `text-success`, `bg-success-dim`, `border-success-border` (and warning, danger, info) | status |
| `colors` | `bg-hue-blue/20`, `text-hue-teal`, `bg-hue-violet-d` (alpha modifiers work on hues) | categorical |
| `borderRadius` | `rounded-xs` to `rounded-2xl`, `rounded-full` | `--radius-*`, `--radius-pill` |
| `boxShadow` | `shadow-elev-0` to `shadow-elev-5`, `shadow-glow`, `shadow-focus`, `shadow-inset-top` | elevation |
| `transitionDuration`, `transitionTimingFunction` | `duration-fast`, `duration-travel`, `ease-out`, `ease-spring` | motion |
| `zIndex` | `z-sticky`, `z-drawer`, `z-popover`, `z-modal`, `z-toast`, `z-tooltip` | stacking |
| `fontFamily`, `fontSize` | `font-sans`, `font-mono`, `text-hero`, `text-display`, `text-h1` to `text-h3`, `text-body`, `text-label`, `text-micro` | type |

An older build that carried its own `ds-*` class map on the retired palette moves to these names.
The retired palette tokens no longer exist, so its classes resolve to nothing.

---

## 4. Typography

- **Sans:** Geist, with Inter as the fallback (`--font-sans`, `--font-display`). Mono: Geist Mono,
  then IBM Plex Mono and any monospace fallback (`--font-mono`). Geist and Geist Mono are the
  house faces and **ship with the kit** as variable woff2 files (weights 100 to 900) with their
  `@font-face` rules in `kit.css`, so the first name in the stack actually renders and no app
  loads them from a third-party host. A token that names a font is only honest when the font
  ships alongside it: a stack whose first face needs a network fetch the app never makes silently
  renders the fallback. Both faces are under the SIL Open Font License 1.1. The licence text
  travels with the files (`kit/src/fonts/GEIST-LICENSE.txt`) and an app that bundles them keeps it
  next to them.
- Body base: `--fs-body` on `--lh-body`, antialiased, `font-feature-settings: 'kern','calt','ss01'`.
  `text-wrap: balance` on headings and card titles, `tabular-nums` on table cells.
- **Type scale** (`--fs-*`, tracking `--track-*`). Data text is never below 11px:

| Token | Size | Use | Tracking |
|---|---|---|---|
| `--fs-hero` | 38px | KPI and gauge numerals | `--track-display` |
| `--fs-display` | 34px | A page-level hero figure | `--track-display` |
| `--fs-h1` | 24px | Page title (21px below 768px) | `--track-title` |
| `--fs-h2` | 18px | Section title | `--track-title` |
| `--fs-h3` | 15px | Card title | `--track-body` |
| `--fs-body` | 14px | The default. Everything unmarked | `--track-body` |
| `--fs-label` | 12px | Field labels, table cells, secondary lines | `--track-body` |
| `--fs-micro` | 11px | Eyebrows, badges, footnotes | `--track-caps` when uppercase |
| `--fs-nano` | 9px | The mono sub-app badge only | `--track-caps-wide` |

- **Type roles** (v0.62.0). Role steps for a console that sets type by role rather than by heading
  level. Each role pairs a size, a line height and a tracking, all theme independent:

| Role | Size | Line height | Tracking | Use |
|---|---|---|---|---|
| display | `--fs-display` | `--lh-display` 1.04 | `--track-display` | A page-level hero figure |
| title | `--fs-title` 24px | `--lh-title` 1.15 | `--track-title` | Page or panel title |
| stat | `--fs-stat` 18px | `--lh-stat` 1.1 | `--track-stat` -0.018em | A stat value |
| subtitle | `--fs-subtitle` 15px | `--lh-subtitle` 1.3 | `--track-subtitle` -0.010em | A subtitle under a title |
| label | `--fs-label` | `--lh-label` 1.35 | `--track-label` 0.004em | Field labels |
| caption | `--fs-caption` 11px | `--lh-caption` 1.4 | `--track-caption` 0.008em | Captions and footnotes |
| eyebrow | `--fs-caption` | `--lh-caption` | `--track-eyebrow` 0.10em | Uppercase eyebrow, looser than `--track-caps` |
| mono | `--fs-mono` 12px | `--lh-label` | `--track-body` | Ids, paths and code |
| mono caption | `--fs-mono-caption` 11px | `--lh-caption` | `--track-body` | Monospace meta lines and hints |

  The role sizes repeat existing steps on purpose (`--fs-title` is `--fs-h1`, `--fs-caption` is
  `--fs-micro`): a role name says what the text is, a heading step says where it sits. Use a role
  token where the text has a role, never a bare pixel size. The kit sets its monospace captions on
  `--fs-mono-caption` and its monospace body on `--fs-mono`. The gallery shows every role in the
  Type roles specimen.
- **Font weights** (v0.65.0). Four tokens, theme independent: `--fw-medium` 500 (controls, quiet
  emphasis), `--fw-semibold` 600 (labels, titles, the default emphasis), `--fw-bold` 700 (strong
  titles and figures) and `--fw-extrabold` 800 (hero numerals). Body text stays at the normal 400,
  which needs no token. Set a weight with the token, never a bare number: the kit does, and the
  Tailwind preset exposes them as `font-medium`, `font-semibold`, `font-bold` and `font-extrabold`,
  and the WPF dictionaries as `Weight.FwMedium` and the rest. The gallery shows them in the Type
  roles specimen. The 650 weight on card titles and stat values is a deliberate step between
  semibold and bold and stays a literal until a fifth token is approved.
- **Text hierarchy for data** (tables, lists, dialogs): primary line `--fs-body` semibold, a second
  line `--fs-label` in `--text-secondary`, metadata `--fs-micro`. Never italic grey placeholders
  ("No assignment found"): use a calm sentence or an `EmptyState`.
- Micro-labels (eyebrows, table headers): `--fs-micro` uppercase, `--track-caps`, `--text-secondary`.
- Hero numerals: `--fs-hero`, weight 800, `tabular-nums`.

**ASCII punctuation in source.** UI strings and source use ASCII punctuation: no em or en dash,
curly quote, NBSP, zero-width character or ellipsis character. Typographic polish comes from the
font and from layout, not from special characters in source. The UI lint enforces it (UI006).

---

## 5. Geometry & Elevation

### Border radii

| Token | Value | Use |
|---|---|---|
| `--radius-xs` | 5px | Small marks |
| `--radius-sm` | 6px | Small buttons |
| `--radius-md` (alias `--radius`) | 10px | Pills, badges, controls |
| `--radius-lg` | 12px | Inner controls, buttons |
| `--radius-xl` | 16px | **Cards**, the search palette |
| `--radius-2xl` | 20px | **Hero cards, stat tiles, dialogs** |
| `--radius-pill` | 999px | Avatars, segmented toggles, dots |

### Elevation

Surfaces rest on the `--elev-*` ladder: `--elev-1` for cards at rest and controls, `--elev-2` for raised controls,
`--elev-3` for elevated cards and hover, `--elev-5` for the open rail and dialogs. Named shadows
serve the recipes: `--shadow-xs` under a selected tab or segment, `--shadow-lift` for an
interactive card on hover (with a 2px rise), `--shadow-pop` for panels over content (the palette,
popovers), `--shadow-key` under a stat tile's glow, `--shadow-glow` for an accent-lit surface. Never
write a shadow literal in an app.

### Spacing

`--space-1` to `--space-10`: 4, 8, 12, 16, 20, 24, 32, 40, 48 and 64px. Card padding is `--space-5`,
page gutters `--space-6` on desktop and `--space-4` below 900px.

---

## 6. Shell Layout

The kit's `AppShell` is the shell: `Rail` (sidebar), `Header`, the content column and `<main>`.

### Sidebar

- Desktop: the hover rail with a pin, owned by [section 19](#19-the-desktop-icon-rail). Below
  900px: the drawer of [section 11](#11-mobile--responsive-shell).
- The active item is marked by **one gliding highlight** (`useNavGlider`, `.nav-glider`) that
  slides to the new link instead of each link drawing its own. It wears the selection recipe of
  [section 17](#17-categorical-hues-tone-and-selection), with no bar (rule 1).
- The brand row is not a link (rule 9).
- **Nav icon hues.** Each nav item may carry a categorical hue (`brand`, `blue`, `green`, `amber`,
  `red`, `violet`, `teal`, the kit's `NavHue`) and its icon takes that hue in every state. `brand`
  resolves to the app accent, and an item with no hue keeps `--text-primary`. The hue identifies
  the destination and never signals selection, since the gliding marker alone shows the active
  link. Acceptance: a computed-style check asserts each `.nav-icon[data-hue]` resolves to its token
  in both themes and is the same colour idle and active.
- **Build card** at the foot of the sidebar, owned by
  [section 22](#22-build-card-and-release-notes).

### Header (`Header`, every page)

A bar of height `--topbar-h`. Left to right:

1. The current page's name, plain text, not a link. No root crumb. Home shows no name (the
   presenter greets there).
2. The **feed strip** with the presenter (`FeedStrip`), owned by
   [section 20](#20-announcements-the-pulse-feed-and-the-presenter).
3. **Search trigger** (`SearchTrigger`): opens the command palette of
   [section 13](#13-global-search-palette).
4. The **home button** (`.hub-btn`): the only route home (rule 9).
4a. The **Help button** (`HelpButton`), present while the page on screen registered help with
   `usePageHelp` and the shell mounts the help drawer (`helpDrawer`): it opens the help drawer of
   [section 27](#27-the-help-layer). `help={false}` hides it. A page that registers no help shows no button.
5. Copy-link and the theme toggle (`ThemeToggle`). The theme switch is revealed as a circle growing
   from the click (View Transitions API, instant where unsupported or under reduced motion). Where
   the header has no account menu offering System, use `ThemeToggle withSystem` (Light, System,
   Dark), so a user who picked a theme can return to following the OS.

### Home: a dashboard of current data

The home page shows current data only, and tools live in the sidebar.

- Date eyebrow, greeting, and a one-sentence summary of the day.
- Announcement banners ([section 20](#20-announcements-the-pulse-feed-and-the-presenter)).
- A bento of cards, one per data source the caller may view. A card appears only when the caller
  holds that tool's view permission, and the server omits the section otherwise. Cards size by
  weight (2, 3 or 4 of 6 columns), so what needs attention gets the heavier card.
- Live visuals: progress rings, countdowns that drop stops as the card narrows (container
  queries), avatars for people, count-up numbers, and "Updated N minutes ago" with Refresh. The
  data comes from one shared store, refreshed every 5 minutes while the page is visible.
- Tool cards appear only as a fallback when the caller has no live data at all.
- **Reorderable tiles:** when the person may arrange the dashboard, tiles reorder by drag and by
  keyboard (`useTileReorder`). With a tile focused, Alt and an arrow key moves it one place,
  Alt and Home or End moves it to the start or end, and a polite live region says where it went
  ("<tile> moved to position 2 of 5", or that it is already at the edge). Arrow keys alone never
  move a tile, so scrolling and the controls inside a tile keep working. Each tile points at one
  instruction line, and the order is kept per person through a store the host implements
  (`TileOrderStore`: `read`, `write`). A saved order is reconciled with the tiles that exist now:
  removed ids are dropped, new ones are appended in default order, so a release that adds or removes a
  tile never loses a person's arrangement. A tile the person has hidden keeps its place and is
  skipped by moves. A read or write that fails keeps the page working and says so.
  **Drop aids (optional):** the empty space after the last tile is a drop zone (`endZoneProps`), so a
  tile can be dragged last without aiming at the final tile. In edge mode the cursor is read against
  the tile midpoint and the drop lands before or after it, with that half of the tile tinted (`data-drop-edge`), since a side stripe is not allowed. The zone and the bar are for the pointer: the keyboard move
  is Alt and Home or End, so the zone is hidden from assistive technology.
  **Acceptance (test):** the saved order reconciles with a changed catalog, Alt and an arrow key
  moves a tile and announces it, a hidden tile is stepped over, a late read never overwrites a move,
  and a failed write is announced.

### Brand wordmark

The `.brand-wordmark` class applies `filter: brightness(0) invert(1)` in dark (white) and `brightness(0)`
in light (black). Never set the SVG fill directly.

---

## 7. Shared Primitives

Implementation: the kit (`kit/src/`, synced into apps as `kit-core/`), styled by the
`tokens/hub-layer.css` recipes plus `kit/src/styles/kit.css`. This section is the source of truth:
where the kit differs, the kit gets fixed. Apps import the components and never restyle them
locally.
Both stylesheets ship inside one cascade layer, `@layer core`, so unlayered app CSS wins by
default and a legacy class name in an app is never restyled by accident. Load order stays
`tokens.css` (unlayered), `hub-layer.css`, then `kit.css`.

The flip side: an app's bare element rules (`a`, `h1` to `h3`, `code`, `table`, `th`, `td`) are
unlayered too, so they also beat every kit class and restyle kit tables, nav links and headings.
Before the layer they lost to kit classes on specificity. Put them in a layer of their own below
the core: a first stylesheet that only declares the order, loaded before `tokens.css`, then the
element rules inside that layer. The core ships that first sheet as `tokens/layers.css` (synced as
`tokens-core/layers.css`): import it first and do not write a local copy of it.

```css
/* tokens-core/layers.css, the first import (shipped by the core) */
@layer base, core;

/* the app's element defaults */
@layer base {
  a { color: var(--accent-bright); }
  th { text-align: left; }
}
```

Class rules stay unlayered and keep winning. When upgrading an app from an unlayered core, compare
full-page screenshots of every route before and after: tables that lost row height or links that
changed colour are this case.

### Buttons (`Button`, `IconButton`)

`.btn` with `data-variant` and `data-size`:

| Variant | Look |
|---|---|
| `primary` | The accent fill gradient (`--accent-fill` to `--accent-fill-d`, the stops of `--accent-grad`), a soft `--accent-rgb` shadow, `--text-inverse` text |
| `secondary` (default) | `--surface-2` fill, `--border-default` hairline, `--surface-3` and `--border-strong` on hover |
| `ghost` | Transparent, `--text-secondary`, `--surface-3` on hover |
| `danger` | The deep red stop (`--hue-red-d`) with `--text-inverse` text |
| `success`, `warning` | Solid: the deep green or amber stop (`--hue-green-d`, `--hue-amber-d`) with `--text-inverse` text |
| `success-subtle`, `warning-subtle`, `danger-subtle` | The status tint (`--<status>-dim`), its `-border` hairline and its ink, the hairline turns the ink on hover |

An app never paints a button with a hue class or its own colour rule: a status action takes the
matching variant. White on each solid stop and each ink on its tint are certified in
`tokens/CONTRAST.md`.

A button is a single-line control: 34px minimum height (28px at `sm`), `nowrap`, centred. It grows
rather than clips when content is taller, but a title with a description under it is an option
card, not a button ([rule 10](#0-the-rules-non-negotiable)).

Every button presses with a spring (`scale(0.97)`), shows `--focus-ring` on keyboard focus, and
`loading` swaps the icon for a spinner. `IconButton` takes a required `label` (its `aria-label` and
tooltip).

A button that cannot be used now takes `disabledReason` instead of `disabled`. It renders
`aria-disabled`, so it stays in the tab order, a click does nothing (no handler, no form submit) and
the reason is its tip and its accessible description. The same prop is on `Modal`'s `primaryAction`.
Rule 2 of [section 27](#27-the-help-layer) says what the reason holds.

### Cards (`Card`, `CardHead`, `CardBody`)

`.card` is `--surface-1` with a `--border-default` hairline, `--radius-xl`, `--elev-1` and padding
`--space-5`. In light mode `--surface-1` is white on the light grey canvas, so a card never needs
an app colour override: the hairline and `--elev-1` carry the separation. `elevated` adds `--elev-3`, `interactive` lifts on hover (`--shadow-lift`), `tone`
applies a tone and `selected` the selection recipe ([section 17](#17-categorical-hues-tone-and-selection)).
`CardHead` is the title-left, controls-right contract: `.card-title` (`--fs-h3`, semibold),
`.card-sub` (`--fs-label`, `--text-secondary`), then `.card-controls`. Card headers wrap their
controls on narrow screens. The face carries `--card-sheen` as a background image (a faint top
light, dark only, `none` in light) and the card head icon takes `--accent-bright`
(`.card-head-text > svg`, `.section-head-icon`). `.card-title` is weight 650 with tight tracking.

`CardHead` is the only section head. `variant` picks the look, never a second part:

- `card` (default): the head inside a `Card`.
- `panel`: the head of a panel or tab region on the page itself, one title step larger.
- `label`: a small uppercase label over a group, with an optional `icon` and `count`.

Every variant is a real heading of `level` (2, 3 or 4, default 2), so the page outline holds
whatever the look. `count` puts a quiet count after the title. App libraries map `PanelHead`,
`CardTitle` and `SectionLabel` onto it ([kit/MIGRATION.md](../kit/MIGRATION.md)).

### Form controls and fields (`Field`, `Input`, `Select`, `Textarea`)

- `.input` sits on `--bg-input` with `--border-field`, `--border-strong` on hover, and
  `--border-accent-strong` plus `--focus-ring` on focus. `aria-invalid` turns the border `--danger`.
- Inside dialogs and forms every control sits in a `Field`: a sentence-case label, the control,
  then a hint or an inline error with an icon. Props: `required` (red asterisk), `optional` (pill),
  `counter` ("42 / 200" for any maxLength), `hint`, `error`. Never an uppercase eyebrow as a field
  label.
- Native controls are themed globally: `Select` has a chevron, checkboxes and radios are custom
  (brand fill when checked, spring check mark, focus ring), and `color-scheme` follows the theme
  so date pickers and dropdown menus match dark or light.
- A `Select` outside a `Field` (a toolbar filter) is named by `labelledBy`, the id of the visible
  text that labels it, or by `aria-label`.
- Choice controls (`Checkbox`, `Radio`, `RadioGroup`, `Switch`) carry their own visible label and
  an optional `description` (linked by `aria-describedby`), `hideLabel` for a screen-reader-only
  label, `disabled` and `size` sm or md. `Checkbox` and `Radio` are native inputs with a drawn box
  beside them, so Space, arrow keys inside a group and form submission behave as the platform
  does, and `indeterminate` marks a partial select-all. `RadioGroup` is a fieldset with a legend
  (`label`), `options` or `Radio` children, `value` or `defaultValue`, `orientation`, `hint` and
  `error`. `Switch` (`role="switch"`) is for a setting that applies at once, never for a choice
  that waits for Save, and submits through a hidden input when it has a `name`.

### Loading and empty states (`Skeleton`, `EmptyState`)

Page-level and main-area loading uses `Skeleton` shapes (line, table, card), never a "Loading..."
sentence. Main-area empties use `EmptyState` (`compact` inside cards) with an action that moves the
user on when there is one (for example "Show August" on an empty month). A short muted line is fine
only inside small panels, popovers and dropdowns. `EmptyState` may take a `pose` to show the stick
figure (`celebrate` for all-clear, `shrug` for no results, `megaphone`, `alert` and the other
`StickPose` values) instead of an icon. Use the figure only where it adds delight. Errors and plain
lists get the icon.

### Tables (`Table`, `useTableSort`)

### Loading and empty states

Page-level and main-area loading uses skeletons (`SkeletonLine`, `SkeletonTable`, `SkeletonCard`),
never a "Loading..." sentence. Work in progress on a row or nav item uses the kit `Spinner` or a
`live` Pill (spinner before the label, which carries the meaning). The spinner turns on
`--dur-spin` and holds still under reduced motion. Main-area empties use `EmptyState` (compact inside cards) with an
action that moves the user on when there is one (for example "Show August" on an empty month).
A short muted line is fine only inside small panels, popovers and dropdowns. Card headers
(`.card-head`) wrap their controls on narrow screens.

### Tables

`Table` requires a `caption` (visually hidden is fine). Header cells are `--fs-micro` uppercase on
`--track-caps` in `--text-secondary`, rows are separated by `--border-subtle` hairlines and take
`--surface-2` on hover (`--surface-3` when selected).

**Every data table is sortable and filterable (standard, not optional).**

- Sorting: every data column is sortable through `useTableSort`. A sortable header is a button
  inside the `th` (`.th-btn`) that inherits the header's font, case and colour, with `aria-sort`
  on the `th` and an arrow (`.th-arr`) in the accent for the active column. Default sort is the
  **first column ascending** (natural-number aware, case-insensitive). Clicking the active column
  flips the direction, clicking another sorts it ascending, and empty values always sort last.
  Action and icon-only columns are not sortable.
- Filtering: every table has a text filter (or the page's existing search) in the toolbar or
  `card-head` directly above it (rule 6). Filter first, then sort. A filter that matches nothing
  shows "No matching ...", not the empty-data state.
- Exceptions (order carries meaning, so no re-sorting): rotation orders, ring or stage sequences,
  chronological schedule and calendar grids, and ordered templates. Logs and audit trails default
  to newest first instead of first-column ascending. Document any new exception here.
- Server-paged tables sort on the server (`sort` and `dir` query params, filter then sort then
  page) so sorting covers the whole dataset, never just the current page.

**Table text.** Primary cell text, a second line in `--text-secondary`, metadata in `--fs-micro`,
numbers right-aligned and tabular. Small labels are `.tag`. Grouped tables that repeat the same
columns share widths (`table-layout: fixed` plus a common `colgroup`) so columns line up from group
to group. Buttons in cells never wrap. Truncated text needs no extra work: the tooltip layer shows
it in full.

### Month calendar (`MonthGrid`)

`MonthGrid` draws weeks of day cells and knows dates and layout only. What an event means (shift, leave,
coverage) stays in the app, which passes events and the `renderEvent`, `renderDay` and `dayHint` slots.
Dates are ISO day strings so no time zone moves a cell. Keys: arrows, Home, End, PageUp, PageDown, Enter
and Space.

- **Multi-day events.** An event with `endDate` (inclusive) covers every day from `date` to `endDate`.
  By default it is a chip on each of those days. With `laneBars` it is one bar per week, packed into
  lanes so bars never overlap: placed by first day, longer first, then in the order given, each in the
  lowest free lane. A bar that crosses a week edge is cut there, drawn with a flat end, and continues
  on the next week with its label repeated.
- `maxEvents` is the number of lanes. A bar with no free lane is not drawn and is counted in
  "+N more" on every day it covers, so nothing is hidden silently.
- A bar is a chip like any other: tone by `tone` (never alone: the label is always there), a button
  when `onEventClick` is passed, replaceable through `renderEvent`. It sits in the cell of its first
  day, so a screen reader meets it once, and each day label counts the events that cover the day.
- Interactive bars drag or resize only in the app; the grid has no pointer editing.

**Acceptance:** a component test asserts the packer (lanes, order, clipping, hidden counts) and that the
bars, continuations and "+N more" render, and the gallery specimen `month-grid-bars` carries baselines
in both themes.

### Filter panel and bulk runs (`FilterPanel`, `useBulkRun`)

**Filter panel.** A page that filters on several columns uses `FilterPanel`, not a row of ad hoc
inputs. It is a form named "Filters" with one typed cell per column: text (`contains`), number and
date (a from and a to, `gte` and `lte`), select and boolean (`eq`, with "Any" as the empty choice),
multiselect (`in`) and lookup (`eq` on a chosen option, or `in` with `multiple`). Apply and Clear are the two actions, Enter
in a cell applies, and Clear empties every cell and emits an empty list.

- The panel emits a neutral list of `{ key, op, value }` clauses and nothing else. It knows no
  business field and no query language. The host maps the list onto its own query, store or
  predicate, and passes the applied list back as `value` to seed the cells.
- A cell left empty adds no clause. A lookup counts only a chosen option, so typed text alone never
  filters.
- Every cell has a visible label. A range and a multiselect are a `fieldset` with a `legend`, and
  each end of a range is named "<label> from" and "<label> to".
- The lookup cell is a combobox (`role="combobox"`, `aria-expanded`, `aria-controls`,
  `aria-activedescendant`, a `listbox` of `option` rows). Arrow keys move, Enter picks, Escape
  closes, and a polite status line says "Loading suggestions", "N suggestions", "No matches" or
  "Suggestions could not be loaded". The loader gets an `AbortSignal` and a slower answer to an
  older query is dropped. The cell is local to the panel until the kit has a shared combobox.
- A lookup field with `multiple: true` keeps several chosen options. They show as chips in a list
  named "Selected <label>", each with a "Remove <option>" button, above the same combobox. Picking
  clears the text and keeps the list open without the options already chosen, Backspace on an empty
  input removes the last chip, and a removed chip returns focus to the input. The cell emits one
  `in` clause with the chosen values (none when no chip is left), and `value` seeds it from an `in`
  clause. The draft for it is a list of options. The default is the single lookup, unchanged.
- The cells sit in an auto-fit grid, so the panel is one column on a narrow screen.

**Bulk runs.** An action over many selected rows (one request per row) runs through `useBulkRun`,
never a bare `Promise.all`, so a large selection cannot flood the backend.

- `useBulkRun(task, { concurrency, itemKey })` starts the items in order with at most `concurrency`
  tasks in flight (default 4, a whole number from 1). A failed item is recorded with its key and
  message and never stops the others.
- State carries `status` (`idle`, `running`, `done`, `cancelled`), `total`, `done`, `succeeded`,
  `failed`, `active` and `errors`. `run(items)` resolves with the same counts plus `skipped`, and a
  second `run` while one is active returns the active run.
- `cancel()` aborts the `AbortSignal` handed to every task and starts no further task. Unmounting
  does the same. A task that does real network work must pass the signal on.
- `SelectionBar` takes `run` (the hook's state), `onCancel` and `itemNoun`. It shows a named
  progress bar, the line "N of M items processed" (a polite status), Cancel while running, the
  per-item error list afterwards, and locks Clear while the run is active.
- Reversible and irreversible bulk actions follow the undo and confirm rule in section 23:
  confirm once for the whole selection before `run`, never once per row.

### List and detail (`ListTable`, `Pagination`, `SplitLayout`)

A page that shows a list beside the item it opens uses `SplitLayout` with a `ListTable` in the list
pane. The kit has two parts for list data because the two shapes are different. `Table` is a grid of
sortable columns and a table is the right semantics for it. A list row is one item (a primary line,
a quieter second line, a leading and a trailing slot) that has to stay readable at the width of a
narrow pane, and it needs group headers and an open row, neither of which a column grid holds
without giving up its table semantics. So `ListTable` is a separate part that reuses the `Table`
selection contract (`useRowSelection`) and its rule for controls inside a row, and it is not a
layout mode of `Table`. A page whose data is comparable across columns keeps `Table`.

- Three states stay apart: the open row (`selectedKey`, `aria-current`, shown in the detail pane), the
  checked rows (a bulk action acts on them) and the focused row (arrow keys). A checkbox never opens
  its row, and the header checkbox is indeterminate over the rows on screen.
- Order is the caller's. Sort and filter first, then page. A server paged list sorts on the server
  like a `Table` does.
- `Pagination` always states the count. A list longer than one page offers page size choices
  (`pageSizeOptions`, `onPageSizeChange`, or `usePagination`), for example 25, 50, 100 and 200.
- A server paged list that cannot give a total leaves `total` out. `Pagination` then reads "Page N"
  with "N on this page" (`itemCount`) and never invents a last page. Next follows `hasMore` when the
  server says, and otherwise a full page means there may be more. `onPage(page)` is the single handler
  form for Previous and Next. Say the page number, not a guessed total.
- `SplitLayout` has a resize handle that works from the keyboard (a separator with a value, arrows,
  Shift for a large step, Home, End, Enter to reset) and by dragging. The list pane has a default
  width of 360 pixels between 240 and 640, and the detail pane never goes under 320. Under 720
  pixels of layout width the panes stack, list above detail, the handle is removed and the list is
  capped in height so the detail stays reachable. The width is a preference: persist it in the host
  through `width` and `onWidthChange` if the page wants that.

### Tabs and segmented toggles (`Tabs`, `Segmented`)

- `Tabs` is module-level secondary navigation (`role="tablist"`). The selected tab wears the
  selection recipe ([section 17](#17-categorical-hues-tone-and-selection)). Tab strips scroll the
  active tab into view and fade the edge that still has hidden tabs. With `withPanels` the panels
  are linked by `tabElementId` and `tabPanelId`. A page's selected tab lives in the URL (`?tab=`,
  replaced rather than pushed) so reload and links work, and an unknown value falls back to the
  first tab.
- `Segmented` (`.seg`, `.seg-btn`) is for ranges, view switchers and series filters. The selected
  option is a raised `--surface-1` pill with `--shadow-xs` that glides to the chosen option, arrow
  keys move the selection (radio-group semantics), and `full` stretches it to the container. Fill
  indicator only, no edge accent. An option may carry a decorative `icon` before its label, and
  `iconOnly` shows the icon alone with the label kept as the accessible name and the tooltip.

### Toggle chips (`ChipGroup`)

- `ChipGroup` (`.chip-group`, `.chip-btn`) is for filters where any number of options can be on,
  such as a severity or status set. `Segmented` picks exactly one, a `ChipGroup` picks none to all.
  `value` is the list of values that are on and `onChange` receives the new list in the order of
  `options`, so the host never sorts it.
- Each chip is a real button with `aria-pressed` inside one named group (a fieldset whose legend is
  `label`). Tab reaches every enabled chip and Space or Enter toggles it. The arrow keys, Home and
  End only move focus, they never change the selection. A disabled chip is skipped.
- Pressed is the selection recipe ([section 17](#17-categorical-hues-tone-and-selection)). An option
  `tone` adds a dot and tints the pressed chip from the status tokens (`-dim` fill, `-border`
  hairline), the label stays the accessible name so colour is never the only signal. A `badge`
  count may follow the label.
- Chips wrap onto further lines on a narrow screen, never scroll, and a long label truncates with
  an ellipsis. The chip height is 32px.

### Badges and marks (`Badge`, `Pill`, `StatusDot`, `HueTile`, `Tone`, `Kbd`)

`Badge` takes a status `tone` (its `-dim` fill, `-border` hairline and ink) or a categorical `hue`.
Status tokens are deep enough in the light theme to clear AA on white and on their own tint.
`StatusDot` marks live states and pulses on `--dur-pulse` ([section 14](#14-motion)). `Badge` and
`StatusDot` take `tip` (and `tipSide`): what the state means and whether it is normal (rule 3 of
[section 27](#27-the-help-layer)). A mark with a tip is a tab stop and the tip is its accessible
description. A bare `StatusDot` with a tip takes the tip as its name.

`.hue-chip` is the generic accent chip: a small label with a hue dot, on a tint of that hue and a
full hairline of it. Set `--hue` (a channel triplet) on the chip or any ancestor, usually with a
`.hue-<name>` class. Without one it takes the active accent. The text stays `--text-primary`, so
contrast never depends on the hue. Never set text colour from a hue.

### Art mark (`ArtMark`)

A picture with a layered, calm, token-driven effect on it, for brand and tool marks. The app
supplies the pictures (transparent, trimmed, square, 256 px with a 128 px copy for marks of 40 px
or less), the recipe per picture, the hue names and the anchors measured on the picture. The kit
supplies the layers: a glow behind, the picture, and an effect layer on top.

`<ArtMark src effect intensity hue hot anchors size title />`. `effect` names a recipe (`beacon`,
`glint`, `signal`, `ring`, `scan`, `lightning`, `fire`) and an unknown or missing name is a still
picture. `hue` and `hot` name kit hue tokens (the glow and soft parts, the bright parts). `size` is
a pixel number or `"fill"`. A `title` makes the mark an image with that label, otherwise it is
hidden from assistive technology. `ART_EFFECTS` lists each recipe's layers and the anchors it reads.

- **Hosts.** The layers are hidden until an ancestor with `data-art-host` turns them on:
  `data-art-live=""` for the normal level (gain 1.1), `data-art-live="soft"` for a calmer one (0.8),
  and `:hover` or `:focus-visible` on the host for the raised level (1.5). With no host the mark
  is a still picture.
- **Motion.** Only `transform`, `opacity` and `filter` animate. Every animation time is
  `--dur-pulse` times a plain factor. The mark pauses while off screen or while the tab is hidden
  (`data-paused`) and is fully static under `prefers-reduced-motion`.
- **Anchors** are percents of the box from the top left, measured on the trimmed picture:
  `focus`, `reach`, `spark`, `pivot`, `arcs`, `box` and `feed`. Swapping a picture means
  replacing its files and measuring the anchors again.
- **New recipes** are an entry in the effect table, its layer classes and its keyframes in
  `kit.css`. `lightning` and `fire` are generic recipes apps can use instead of carrying their
  own copies.

### Dialogs (`Modal`, `ModalSection`, `useConfirm`, `usePrompt`)

Every dialog uses `Modal`. No hand-rolled `fixed inset-0` overlays.

- **Look:** blurred, dimmed backdrop (`--backdrop`), layered panel (`--radius-2xl`, top sheen),
  header with a 40px icon tile tinted by `hue` (never the accent), a title in sentence case and a
  one-line subtitle, body sections (`ModalSection` with title and description, separated by a
  hairline), and scroll shadows when the body scrolls.
- **Footer:** `[footerStart] ... [Cancel] [primary]`. The primary button shows a spinner while
  `loading`, and `tone: 'danger'` marks destructive actions. With no `footerStart` the left side
  shows keyboard hints ("Esc to close | Ctrl+Enter to save").
- **Behaviour:** focus moves to `[data-autofocus]` or the first field, Tab is trapped, and Escape,
  backdrop, close and Cancel play the exit animation. `onSubmit` makes the body a form so Enter and
  Ctrl/Cmd+Enter submit, and `busy` blocks closing while saving. Dialogs stack: only the top one
  answers keys.
- **Variants:** `size` sm, md, lg, xl, `wide` (tables and side by side forms) and `full` (the
  viewport less the gutter). `variant="sheet"` docks a full-height panel on the right for long
  forms. Below 640px every dialog becomes a bottom sheet.
- **Headless:** `hideHead` drops the head row for a dialog whose body brings its own heading. The
  `title` is still required and still names the dialog: a string becomes `aria-label`, any other
  node stays as a visually hidden heading. The close button floats in the corner unless
  `hideClose`.
- **Attributes:** `data-*`, `id` and other HTML attributes pass through to the dialog panel.
- **Confirms and prompts:** `const { confirm, dialog } = useConfirm()`, render `{dialog}` once and
  `await confirm({ title, body, confirmLabel, danger })`. `usePrompt()` returns the trimmed value
  or null, with optional `validate`.

### Record preview (`RecordPreviewProvider`, `RecordChip`, `createRecordRegistry`)

One dialog previews any record by type and id from anywhere: a palette result, a cross link chip, a
detail header. The kit holds no record types. The host owns them.

- **Registry:** `const registry = createRecordRegistry()` once, then
  `registry.register('device', { label, load, render, title?, href?, icon? })` per record type.
  `load(id, signal)` returns the data (reject to show the error state, the signal aborts when the
  dialog moves on), `render(data, { ref, close })` returns the body, `title(data, ref)` replaces the
  default title and `href(id)` adds an "Open full page" link. `register` returns an unregister
  function. Keep each type in the module that owns it and register at startup.
- **Mount:** one `RecordPreviewProvider registry={registry}` near the root, inside the router. Pass
  `navigate` so a plain click on "Open full page" goes through the router.
- **Open:** `<RecordChip type id>label</RecordChip>` anywhere, or `useRecordPreview().open({ type, id })`
  from code (it returns false and opens nothing for an unregistered type). A chip for an unregistered
  type, or outside a provider, renders as plain text so it never looks clickable and does nothing.
- **States:** the dialog is a `Modal` named `<label> <id>` while loading and by `title` once loaded.
  Loading is a skeleton, a failed load is an `ErrorState` with Retry inside the dialog, and a body
  that throws is caught by a page scoped error boundary inside the dialog. Every open loads again.
  Below 640px the dialog is a bottom sheet like every dialog.
- **Seed:** a type may set `seed(ref, context?)` to return data the host already holds (a cached
  row). The dialog paints it at once instead of the skeleton, marks the body `aria-busy` and
  `data-pending` while the live `load` runs, then swaps in the live result. Set `merge(seed, live)`
  to keep fields only the seed has, without it the live result replaces the seed. Return undefined
  (or throw) for no seed and the skeleton shows. The live fetch stays in `load`, so a failure still
  shows the error with Retry (the seed is not kept behind the error) and Retry paints the seed
  again. A `merge` that throws shows the same error state. Do not move the fetch into the body.
- **Reload:** `render(data, { ref, close, reload, context })`. Call `reload()` after an edit in the
  body. The body stays on screen (busy) while the record loads again and is replaced by the fresh
  data. The reload result is merged over the same seed as the open.
- **Context:** `open({ type, id }, context)` and `<RecordChip context={...}>` take an optional bag
  (a tab to show, the row the user came from). The seed and the body read it, and an open without a
  bag clears it. Keep it small and serialisable, it is not a store.
- **Rules:** bodies take data from the loader, never from a global. A body that links elsewhere calls
  `close`. Keep the body short: the preview is a glance, the full page is the work.

### Error boundary (`ErrorBoundary`, `PageErrorBoundary`)

Two scopes. Mount `ErrorBoundary` once at the app root: the full screen crash with Reload and Reset
session. Mount `PageErrorBoundary` around the routed page, inside the shell, so a crash stays in the
page: the sidebar and header keep working, the panel says the rest of the app is unaffected, and the
stack sits in a closed "Technical details" disclosure.

- **Key it by the route.** `resetKey` is required on `PageErrorBoundary`:
  `<PageErrorBoundary resetKey={location.pathname}>`. When the value changes the crash clears in the
  same render and the new page mounts, so moving to another page recovers without Try again. An array
  key (`[pathname, search]`) compares element by element. A page that crashes again under the new key
  shows its own crash and reports once. Without a changed key the crash stays, so a re-render of the
  same page never hides it.
- **Reporting:** `onError(error, info)` runs once per caught crash. The crash is always logged.

### Tooltips (`TooltipLayer`, `data-tip`)

One layer serves the whole page. `AppShell` mounts it when given `tooltipLayer` (default off, so an app
that does not ask sees no change), and `data-tip` on a kit `Button`, the feed strip or the launcher then
shows with no wiring. An app that mounts its own `TooltipLayer` leaves the prop off: only the first layer
mounted is active, so a second mount never draws a tip twice. Put `data-tip="..."` on an element (optional
`data-tip-kbd` key chip, `data-tip-side="bottom"`, or `"right"` for icon rails). Native `title`
attributes and truncated or line-clamped text that is actually cut off are upgraded automatically.
Shows after `TOOLTIP_DELAY` on hover (`TOOLTIP_SKIP_DELAY` when moving between tips) or on keyboard
focus, never on touch, and hides on scroll, pointer down and Escape. Icon-only buttons always carry
`aria-label` and `data-tip`.

The layer's tip is a visual aid and is hidden from assistive technology, so the words reach a screen
reader through the element: `useTip(text, side)` returns the tip attributes plus a hidden description
wired with `aria-describedby`, and every kit part with a `tip` prop uses it. A tip is one or two short
plain sentences and never the only copy of something needed to act. What to put in a tip, and the parts
built on it (`Term`, `InfoTip`, `When`, `disabledReason`, `Badge tip`), are in
[section 27](#27-the-help-layer).

### Toasts (`Toaster`, `useToast`)

Bottom-right stack above dialogs (`--z-toast`), newest last, up to four.
`toast(variant, message, options)` with variants success, error, warning, info and options
`{ description, action, persistent, duration, id }`. Lifetime is `TOAST_DURATION`, or
`TOAST_ACTION_DURATION` when the toast offers an action. Hovering or focusing pauses the timer.
Toasts dedupe by `id` only, never by message text: a toast that reuses the id of one on screen
replaces it in place with a fresh timer (progress, a repeated save), and a call without an id is
always a new toast, so the same text twice and JSX messages both show.
`action: { label: 'Undo', onClick }` is how rule 8 works.

### Page header and toolbar (`PageHeader`, `Toolbar`)

`PageHeader`: title (`--fs-h1`, semibold), a one-line purpose, optional eyebrow and status on the
right. No action buttons (rule 6). The plain header is a flex row with no fill. The tinted header is
opt-in: pass `wash` to `PageHeader`, or put `data-wash` on a hand-written `.page-header`. It is a
tinted fill and a full hairline ring, never an edge bar: `--header-wash` over `--surface-1`, a
`1px solid var(--border-accent)` border, `--radius-xl` and `--shadow-inset-top`. The shell root
paints `--canvas-wash` over `--bg-canvas` through a fixed pseudo-element layer (never
`background-attachment: fixed`, which repaints on scroll), one soft radial of the active accent
behind the content and never a pattern. All three washes read `--accent-rgb`, which every accent
block defines, so they follow `data-app-accent` with no extra wiring. `Toolbar` sits above the
content it acts on: filters at the start, then the "updated Ns ago" freshness text
(`formatUpdated`, ticking every `CLOCK_TICK`) and the actions with Refresh first.

### Tags and search keywords

Keywords that exist to make a record findable are search metadata, not content: index them and
keep them out of the layout. Editors see and edit them only in edit mode, labelled "Keywords" or
"Search keywords". The server-side free-text search must match them. When a keyword is the only
reason a record matched, the search result may name it quietly ("matches \"term\"").
Tags that people manage as content use the neutral `.tag` chip (`--surface-3` fill,
`--text-secondary`, `--fs-micro`), never accent-tinted.

### People (`Avatar`) and chips

`Avatar` shows initials (`initialsOf`) on a stable categorical hue per name (`hueFor`), or an icon
for groups. Person and assignee chips (`.chip`) pair the avatar with the name. Actions appear on
hover or focus (always visible on touch).

### Typeahead chooser (`Combobox`)

One typeahead chooser serves every "type to find a thing" field: a person, a group, a device, a
catalogue entry. `Combobox` takes `search(query, signal)`, an async lookup the app owns, so the kit
knows no directory and no data shape. A person picker is a usage of it, not a second part: the row
slot (`renderOption`) draws each item, and `PersonOption` is the row for a person (an `Avatar`, the
name, a detail line and a muted meta).

- **Lookup.** It waits `debounceMs` (default 300) after the last keystroke and does not search
  below `minChars` (default 2). A newer query aborts the older one through the signal, and a reply
  that arrives late is dropped, so rows never belong to an earlier query.
- **States.** Loading is a spinner and text while there are no rows yet, empty names the query, and
  an error says the search failed and offers a retry (the button, or Enter on the input). Messages
  can be replaced through `messages`. A failure is also passed to `onSearchError`.
- **Keyboard (the ARIA combobox pattern).** The input is `role="combobox"` with `aria-expanded`,
  `aria-controls`, `aria-autocomplete="list"` and `aria-activedescendant`, and focus never leaves it.
  ArrowDown opens the list and moves down, ArrowUp moves up (both wrap), Enter picks the active row,
  Tab leaves and closes. Escape closes the list and nothing else: the list is a non-modal layer, so
  an enclosing dialog stays open and its unsaved choices survive, and the next Escape closes the
  dialog. A polite live region announces searching, the result count, none and failure.
- **After a pick.** The input shows the label of the item (a single value field), or is emptied with
  `clearOnSelect` (a picker that builds a list, with `excludeKeys` leaving out what is already
  chosen). Inside a `Field` the visible label names the input.
- **Touch.** Rows, the retry button and the input are 44px tall on a coarse pointer, so the field
  and the rows under it have one touch height. `size="sm"` gets the same 44px on touch.
- **Wrap.** ArrowDown on the last row goes to the first and ArrowUp on the first goes to the last.
  The list never stops at an end, so a keyboard or touch user is not left on a dead row.
- **Free entry when the lookup is unavailable.** A directory can be down for good (not configured,
  not licensed, not reachable) and then a retry never helps. The app says so by rejecting `search`
  with an `UnavailableError` (or any error carrying `unavailable: true`), or by returning
  `'unavailable'` from `onSearchError` for an error it cannot mark. The part then becomes a plain
  free entry field: the combobox role, the list and every lookup are gone, a one line hint under the
  input says why (`messages.unavailable`), and Enter hands `{ free: text }` (`ComboboxFreeEntry`)
  to `onSelect`. `validate(text)` checks the text: return null, undefined or true when it is fine,
  a message string (shown in the hint, and the input is `aria-invalid`) or false (the
  `messages.invalid` text) when it is not. Enter on an invalid text adds nothing. Without
  `validate` any non-empty text is accepted. `clearOnSelect` empties the input after the add. Type
  the part as `Combobox<Item, ComboboxFreeEntry>` to handle both shapes, left out the callback is
  typed as before. The state lasts until the part mounts again (change its `key`), and
  `defaultUnavailable` starts in it for an app that already knows. A failure that is not marked and
  not escalated by `onSearchError` keeps the error state with its retry.

### List controls (`ListControls`)

The bar above a list page: filters, a sort key with a direction button, and a group-by select, plus a
`rightSlot` for a count or an action. The page owns the state and the data. Every control is a
labelled select or a named button, the bar wraps, and below the phone breakpoint each control takes
its own row. The helpers turn a flat array into what the page draws: `applySort` (numbers as
numbers, text with numeric and case-insensitive collation, empty values last in either direction,
ties keep their order), `applyGrouping` (groups ordered by label, the unspecified group last, null
when there is no group key), `paginate` and `usePagedState` (a size change or `reset` returns to
page 1). `GroupHeader` is the sticky header above each group and `Pagination` is the footer. With
`onPageSizeChange` it adds a "Rows per page" select, and with `loading` it disables its controls.

### Keyboard (`ShortcutLayer`)

`?` opens the shortcut sheet, `/` opens search, `G` then a letter jumps to a tool (only tools
the user can open, waiting `SEQUENCE_TIMEOUT` for the second key), `[` pins the sidebar. Shortcuts
pause while typing and while a dialog is open.

### Stat tiles (`StatTile`)

The only hero KPI primitive (rule 4). Recipe, glow and count-up in
[section 18](#18-stat-tile-glow-and-count-up).

### Stats (`Stat`, `StatRow`)

The everyday summary card, light where `StatTile` is a deep fill: `--surface-1` with the card
hairline and `--elev-1`, a `--fs-label` label beside an optional hue tile (`icon`, `hue`), a
`--fs-h1` value in `--text-primary` or a status ink (`tone` success, warning, urgent, danger,
info, never the accent), and an optional hint. `onClick` makes it a button and `selected` raises
it with the accent ring, for a stat that filters the view below. `countUp` opts into the count-up.
`StatRow` lays Stats out in a wrapping grid (`min` sm, md, lg) and is a labelled group with
`label`. Use StatTile for the one hero row of a page and Stat for every other KPI.

### Facts and disclosure (`FactRow`, `FactList`, `Disclosure`)

Detail panels show label and value pairs with `FactList` and `FactRow`, never a hand-built flex row.
They render a description list, so each label is announced with its value. The label is
`--text-tertiary` at `--fs-label`, the value is `--text-secondary` (`tone` primary or tertiary),
`mono` sets ids, paths and hashes in the mono face, and an empty value is a quiet dash announced as
None. A long value wraps, and below 480px it sits under its label. `tone` also takes the status
inks `success`, `warning`, `urgent`, `danger` and `info` (the same tokens as the stat value). Ink is
never the only signal, so the value text must say the state (Almost full, Failed), not just be
coloured. Secondary detail goes behind `Disclosure`, a real button with `aria-expanded` and
`aria-controls`, never a hover or a bare click target. `lazy` mounts the children only while the
panel is open (they mount on open and unmount on close), for a panel that is heavy or fetches. The
panel element stays, hidden and empty, so `aria-controls` always resolves, and the default is off.

Spacing is set through custom properties, never by wrapping a part in a spacer. The row gap of a
list is `style={{ '--fact-gap': '14px' }}` (also the `gap` prop), a fixed label column is
`style={{ '--fact-label-width': '120px' }}` (also the `labelWidth` prop) and the space between a
disclosure button and its panel is `style={{ '--disclosure-gap': '12px' }}`. `FactRow`, `FactList`
and `Disclosure` take a `style` passthrough that is merged over their own custom properties, so a
caller sets those and a margin in one place, for example `style={{ '--fact-gap': '14px', marginTop: 8 }}`.

### Markdown reader (`Markdown`)

Use `Markdown` to show a document the app did not author as markup (a plan, a note, a release body).
It is safe by default and that is part of the contract: it never injects HTML (raw tags show as
text), renders no image, and makes an anchor only for http, https, mailto and tel, opened in a new
tab with `noopener noreferrer`. A relative link calls `onLink` so the host opens the document in
place, and is plain text without a handler. Any other scheme and any protocol-relative URL renders
as its label with no href. Do not replace it with `dangerouslySetInnerHTML` and a markdown library
unless that library's output is sanitised and the same tests pass. `headingOffset` keeps the page
heading the only h1.

### Global base styles

- `::selection` takes the accent wash with `--text-primary`.
- Scrollbars are thin, with a `--border-default` thumb on a transparent track.
- Focus is `:focus-visible` with `outline: none` and `box-shadow: var(--focus-ring)`, never a
  browser default outline.

---

## 8. Charts

- **`useChartTheme()`** (kit, `kit/src/charts/chartTheme.ts`) returns resolved colour strings read
  from the live tokens (Recharts writes SVG attributes where CSS `var()` is unreliable), so charts
  recolour instantly on a theme or accent change. Never hardcode a colour in a chart.
- Area: per-series `<linearGradient>` (hue at 0.35 to transparent), 2px stroke, dashed horizontal
  grid.
- Tooltip: a theme-aware callout from the chart theme (`tip` is `--surface-2`, `tipBorder` is
  `--border-strong`, `tipText` is `--text-primary`) with coloured series dots.
- Donut: `innerRadius~54 outerRadius~80 paddingAngle 2 cornerRadius 3` plus an absolutely-centered
  total overlay (`--fs-hero`, weight 800). Bars: `radius [6,6,0,0]`.
- Single-value meters (`Gauge`, `RingProgress`): one value against a `max`, clamped to 0 through
  `max`. The wrapper is `role="meter"` named by `label`, with `aria-valuenow`, `aria-valuemax` and
  an `aria-valuetext` that also says the state (healthy, warning, critical) so colour is never the
  only signal. The arc takes `--success`, `--warning` or `--danger` from `thresholds`, else `--accent`, and travels on `--dur-travel` with no transition
  under reduced motion. `thresholds` are in the units of `value` and `max` (a ring of 0 to 200 warns
  at `warning: 150`, a caller moving from 0 to 1 fraction pairs multiplies them by `max`) and a higher
  value is worse unless `higherIsBetter` is set, which flips the comparison to at or under. For a ring
  or gauge whose colour is not a status (a share, a category) pass `tone="info"`: it draws `--info`,
  wins over `thresholds`, is never produced by them and adds no state word to the value text, so the
  colour is decoration and the label and the number carry the meaning.
- `ChartLegend` (charts entry): a standalone legend for a chart the host composes itself. Items are
  `{ label, color?, line? }`, a missing `color` takes the next categorical hue in order and `line`
  draws the swatch as a short line. It is a named list (`label`, default "Legend") a screen reader
  reads, the swatch is decorative and the label names the series. The legend inside the kit charts
  stays hidden because each chart carries its own data table. It wraps on a narrow screen and
  renders nothing without items.
- Series cycle the categorical hues in order (blue, green, amber, red, violet, teal) minus the
  withheld hue (rule 2). `status.inProgress` is the accent (semantic, not a series) and
  `status.overdue` is red (reserved).
- Tooltip component prop: pass an **element**, not a render function:
  `content={<ChartTip t={t} />}`. Recharts v3 clones the element, and the render-function form
  triggers a `readonly payload` TS error.

### ChartTheme shape

```ts
interface ChartTheme {
  grid: string;    axis: string;    text: string;            // --border-default, --text-tertiary, --text-secondary
  tip: string;     tipBorder: string;  tipText: string;      // --surface-2, --border-strong, --text-primary
  accent: string;                                            // brand and in-progress only
  series: string[];                                          // categorical order minus the withheld hue
  status: {
    notStarted: string; inProgress: string; completed: string; overdue: string; warning: string;
  };
}
```

### Charts without a chart library

A hand-rolled chart is one `<svg className="chart" viewBox="0 0 W H" role="img" aria-label="...">`
with a fixed viewBox, scaled by CSS (`.chart { width: 100%; height: auto }`), so it stays sharp at
any width. Geometry (padding, ticks, bar sizes) is a small pure function that is unit tested.
Colours come only from tokens through classes, never literals: the grid strokes
`--border-default`, axis text fills `--text-tertiary`, and series classes fill a categorical hue
such as `rgb(var(--hue-violet))`. Legend dots use the same tokens, so both themes recolour with the
`data-theme` switch. Each mark carries a `<title>` for the hover tooltip, ticks sit at 0, 25, 50, 75
and 100 percent of the max, and x labels thin out (every second day) when crowded. Sparklines
follow the same rules (fixed viewBox, token strokes, `aria-label`).

---

## 9. Verification gate (before "done")

The full gate lives in the
[First-Party Build Standard](web-build.md#8-verification-gate). The design-specific
part: verify the surface in-browser in **both dark and light**, with no console errors, and confirm
the no-edge-bar rule (rule 1) and contrast hold. Run the overflow probe on every route the change
touches, at the widest and the narrowest supported width, and fix every finding (rule 10):
`node kit/scripts/overflow-probe.mjs out.json 1440,1024 name=<url> ...` loads each page through a
running browser's DevTools endpoint (`PROBE_CDP`, default `http://127.0.0.1:9222`), lists text
that escapes the nearest bordered or filled box around it, and text that a clipping box cuts off
without an ellipsis, and exits 1 when it finds any. The detector is `kit/visual/overflow.ts`, and
the kit's visual gate runs the same detector over the gallery in both themes. CI enforces the axe part (no critical or serious
violations) through the Playwright e2e job, see
[CI/CD and Release Standard](ci-cd-release.md#2-required-ci-checks).

### Gates and whether this standard enforces them

A rule with no check is a suggestion. Status of the gates:

| Gate | Status here |
|---|---|
| No edge bars, no native dialogs, ASCII punctuation, token-only colour, motion and stacking | Enforced by `lint-core/ui_lint.py` in every overlay's `core-drift.yml` |
| Token parity between the stylesheet and the typed token object | Enforced by construction: both are generated from `tokens.json`, and core CI runs `build.py --check` |
| Every token a standard names exists | Enforced in the core by `checks/check-token-names.py` |
| RBAC lockstep (permission registry, role seed, docs agree) | Recommended, enforce with [RBAC](rbac.md) where roles exist |
| Bundle-size baseline (growth over 10% needs a reason) | Recommended, not required |
| Content stays inside its box | Borrowed kit classes are flagged by `ui_lint.py` (UI009). The rendered part is `kit/scripts/overflow-probe.mjs`, run by hand before done |
| Actions live with content, one way home | Design rules, reviewed by hand, no check yet |
| Boards and wide tables keep their scrollbars | Rule 12, reviewed by hand at a window about 700px tall; the kit parts (`page-scroll`, `Table` `capped`, `LaneBoard` `fit`) carry the sizing |

An overlay may promote any recommended gate to required.

---

## 10. WPF / PowerShell translation (desktop tools)

Same DNA, mapped to PS 5.1 WPF. **No edge-bar indicators (rule 1):** the selected nav item is a
raised neutral surface with a hairline ring and stronger text, not a left or right accent bar.

- Tokens: the generated dictionaries in `tokens/wpf/` (`Tokens.Dark.xaml`, `Tokens.Light.xaml`),
  with the app accent from `build.py --wpf-accent <name> --mode dark|light`. Segoe UI and Consolas.
- Radii: card 12, control 8, badge 4. DataGrid: horizontal gridlines only, no zebra striping.
- Save as ANSI/ASCII. `XamlReader.Parse` or `Load`, no `x:Class`, code-behind or compiled
  MarkupExtensions. Do not set `Foreground` on inner label TextBlocks (template triggers own it).
  Wire events in PowerShell (`$el.Add_Click({...})`). Full control kit:
  [wpf-design-system.md](wpf-design-system.md).

---

## 11. Mobile / responsive shell

**Breakpoint:** 900px. At or below 900px the sidebar is a drawer, above it the desktop rail of
[section 19](#19-the-desktop-icon-rail). Dialogs and toasts have their own phone layout below 640px.
No other breakpoints are used for the shell itself.

### Shell structure (`AppShell`)

```text
AppShell (.shell, data-rail, data-mobile-nav)
  drawer backdrop   (--z-drawer-backdrop, --scrim, at or below 900px, tap to close)
  Rail (.sidebar)   (--z-drawer as a drawer, in flow as the desktop rail)
  content column (.shell-main)
    Header
    <main> (.shell-content)
```

- The drawer is `min(var(--sidebar-w), 86vw)` wide, never the collapsed rail width, slides in from
  the left over `--dur-travel` on `--ease-out`, and carries `--elev-5`.
- It closes on every route change (pass the router's path as `AppShell`'s `pathname`), on Escape,
  on the backdrop, on its close button, and when the window grows past 900px. No explicit close
  call is needed per nav item.
- The header shows a menu button at or below 900px, and the drawer shows an X close button in its
  brand row. Header search collapses to an icon button on phones.
- The pin and the hover bloom are desktop only. Phone users always get the full-width labeled
  drawer.
- Below 640px every `Modal` is a bottom sheet (full width, rounded top, slides up, safe-area
  padding) and keyboard hints are hidden. The presenter is hidden on phones, and the home page
  carries the same information in its cards.
- Every icon a nav item names must resolve. A missing icon is a defect, never a silent fallback.
- `AppShell` mounts the tip layer when given `tooltipLayer` ([Tooltips](#tooltips-tooltiplayer-data-tip)),
  the help drawer with the page help state when given `helpDrawer` ([section 27](#27-the-help-layer))
  and registers the app's glossary when given `glossary`. All three are off by default.

### z-index stack

Every layer is a `--z-*` token (UI004):

| Layer | Token |
|---|---|
| Sticky table head, sticky filter bar | `--z-sticky` |
| Fixed mobile top bar | `--z-topbar` |
| Drawer backdrop | `--z-drawer-backdrop` |
| Drawer | `--z-drawer` |
| Popovers, menus, pickers | `--z-popover` |
| Command palette and dialog backdrops | `--z-modal-backdrop` |
| Dialogs | `--z-modal` |
| Toasts, above dialogs by contract | `--z-toast` |
| Tooltip, above everything | `--z-tooltip` |

---

## 12. Per-app accent and plain-CSS port

The look is the standard for every first-party web surface, including small tools that are
not React/Tailwind apps. Two rules make that work.

### Per-app accent (token swap only)

Any first-party app **may** take its own accent so users can tell apps apart at a glance. The accent
is one choice made on the root, `html[data-app-accent="<name>"]`, and it re-points only the accent
tokens ([section 16](#16-one-accent-token-per-app)). Surfaces, status colours, categorical hues,
radii, shadows, glow, primitives and every rule in section 0 stay exactly as specified.

- Everything that takes the accent follows it: the primary button, focus rings, the in-progress
  status, the today marker, the active nav marker and the brand nav icon.
- Pick a named accent: cobalt (the default, no attribute), blue, indigo, violet, fuchsia, rose, red,
  orange, hub, amber, gold, green, teal or cyan. Each is generated from a seed and certified in both
  modes (`tokens/CONTRAST.md`).
- A brand colour that is not on the list becomes a custom accent: run
  `python3 tokens-core/build.py --accent <name>=#RRGGBB` in the overlay, commit the printed block
  in the app's stylesheet with its certification line, and record the seed in
  `standards-local/parameters.md`. The block fails to print as certified if the seed cannot be made
  to pass.
- The exact brand colour stays available as `--accent-seed` for identity marks (favicon, brand
  tile, logo). Fills and text use the certified ramp, which may sit darker or lighter than the seed so
  white text and accent text clear AA.
- The brand wordmark and any brand lockup stay as-is. The app accent never recolours branding.
- WPF and PowerShell tools take the same tokens from `tokens/wpf/` ([section 10](#10-wpf--powershell-translation-desktop-tools)).

### Plain-CSS port (no Tailwind)

Small single-file tools (for example a static `index.html` served by a Python stdlib server) do not
need a build step. They port the system as plain CSS:

- Link `tokens.css`, `hub-layer.css` and the kit's `kit.css` as copied files (no build step) and use
  the tokens as [section 2](#2-color-tokens) describes. Theme is `data-theme` on `<html>`,
  persisted in `localStorage`, applied in a tiny head script before first paint (the kit's
  `themeInitScript` is that script). The script is injected from the kit at build with the kit's
  HTML transform (`kitThemeInit()` from `kit-core/theme-init`), never pasted by hand, because a
  pasted copy drifts. Where a build step cannot inject it, a test runs `hasCurrentThemeInit(html)`
  from the same entry, which compares the inline script with the kit's byte for byte. A boot splash before mount
  is optional and, when used, uses only tokens and the same theme script.
- Use the kit's class names so markup reads the same as a React app: `.btn` with `data-variant`,
  `.card`, `.card-head`, `.tone`, `.is-selected`, `.kpi-tile`, `.seg`, `.badge`, `.input`, `.tabs`
  and `.tab`. Same radii, elevation, type scale and the Geist / Geist Mono typeface.
- Shell matches sections 6 and 11, with the rail of section 19: page title and subtitle with no
  buttons (rule 6), toolbars above the content they act on, drawer and menu button at or below
  900px.
- Tables follow the sortable and filterable rule ([section 7](#7-shared-primitives)) with a small
  shared helper.
- Icons are inline SVG paths from one icon set, never emoji or Unicode glyphs.
- The section 9 verification gate still applies: both themes, no console errors.

### Local tool patterns: charts, tabs, dialogs, sortable headers

Patterns for the plain-CSS port. They need no chart dependency.

- **Charts:** hand-rolled SVG as in [section 8](#charts-without-a-chart-library).
- **Tab switcher with freshness and Refresh.** Tabs on a page are a `.seg` with `role="tablist"` and
  `.seg-btn` buttons (`role="tab"`, `aria-selected`). The selected tab lives in the URL as in
  [section 7](#tabs-and-segmented-toggles-tabs-segmented). With many tabs the switcher scrolls
  horizontally and never wraps, so it never overflows a phone. Each tab body starts with a toolbar:
  its filters on the left, then a spacer, the text "updated Ns ago" (`--text-secondary`, "updated
  just now" under 2 seconds, seconds under 90, then minutes, ticking every second) and an icon-only
  Refresh button (disabled while loading). Polling and the manual Refresh share one hook that
  records when data last arrived. A section that cannot be read shows an empty-state card in place
  of the body, not a page-level error.
- **Native `<dialog open>` inside the `.modal` wrapper.** The app owns every dialog (rule 7). The
  wrapper `div.modal` is the fixed full-screen blurred backdrop, hidden until it has the `open`
  class (`display: flex` then). Inside it, render `<dialog open className="dialog">` (the semantic
  element, but always opened by attribute and positioned in flow: `dialog.dialog { position:
  relative; inset: auto; margin: 0; padding: 0; display: block }`). It holds a `.card-head`, a
  `.card-body` and a `.dialog-foot` (right-aligned buttons, `.left` pushes a button to the start).
  The palette uses the same trick. This avoids the browser's top-layer default styling and
  `showModal()` focus handling while keeping the dialog landmark.
- **Sortable header as a button inside `th`:** as in [section 7](#tables-table-usetablesort)
  (`.th-btn`, `aria-sort`, an arrow in the accent for the active column), with a shared hook
  holding `{ key, dir }`.

Reference implementation: the kit gallery (`kit/gallery/`) renders every primitive and pattern in
both themes.

## 13. Global search palette

The one global search surface (`CommandPalette`, backend pattern:
[First-Party Build Standard section 10](web-build.md#10-global-search-hybrid-semantic)).

- **Trigger:** the header `SearchTrigger` is a button ("Search everything" plus a `Cmd K` or
  `Ctrl K` hint chosen by platform). Cmd/Ctrl+K toggles, a bare `/` opens (never inside an input,
  textarea, select or editable region, never with a modifier held and never over another dialog),
  Escape closes from anywhere on the page, including a focused result row. On phones the trigger becomes an icon button.
- **Box:** 12vh from the top, 600px max, `--radius-xl`, `--shadow-pop` on `--surface-1` over a
  blurred `--backdrop` at `--z-modal-backdrop`. A large unboxed input with a search icon and an
  `Esc` key chip.
- **Kind filter:** `.seg-btn` chips (All and one per record kind) with live per-kind counts.
  Tab and Shift+Tab cycle them. A muted hint lists the `is:` filters.
- **Results:** an icon tile per kind, title on one line, a two-line snippet windowed around the
  first match, the record's own status and due badges on the right. Matched words are wrapped in
  `<mark class="search-hit">`: `--hue-blue` at 30% alpha, `--text-primary`, weight 700, never the
  accent. Synonym or typo hits show "Related: <terms>" in muted text, and semantic-only hits show
  "Related by meaning" the same way.
- **Selection:** arrow keys and hover move `.palette-row.is-active`, the selection recipe
  ([section 17](#17-categorical-hues-tone-and-selection)). Enter opens the record in place or runs
  the command.
- **Empty query:** recently updated open records plus commands ("Go to ...", "New ...", "Toggle
  theme", "Export"). No results: the standard empty state.
- **Ranking, toolbar and rows (optional):** a palette may take its own ranking function in place of the
  substring filter (it receives the raw query, an empty one too, so the host owns the empty-query
  order) and a row limit (default 50, unlimited allowed). A toolbar row under the search field holds
  filter chips: it is a named group, Tab reaches it after the field, and Enter or an arrow key pressed
  on a chip never opens or moves a result. A row may carry a one line description under its label and a
  status badge at its right end, and the badge says its state in text, not colour alone. A palette that
  sets none of these looks and behaves as before.
- **Footer:** key hints on the left, the search mode on the right with a status dot
  ("Semantic search on (<model>)" or "Keyword search only (model offline)").
- **Groups, filter tabs and keys (optional):** a row may carry a `group` (a header over its rows,
  groups in first-appearance order), `filters` add tabs under the input that Tab and Shift+Tab
  cycle, and a row `shortcut` shows its keys and registers them in the shared shortcut registry so
  the help sheet lists them. Ranking: exact label, label prefix, word start, label substring,
  keyword, then kind.
- **Preview pane (optional):** a `preview` slot renders a read-only view of the active row beside
  the list, in a labelled region (`previewLabel`) that follows the arrow keys and receives
  `undefined` when nothing matches. Use it when a person picks content, such as a saved reply or a
  template, and needs to see it before choosing. The panel widens to 880px. At 640px and below the
  pane is hidden and the list keeps the full width, so nothing the pane shows may be the only way
  to tell two rows apart (the row label must be enough).
- **Scoped shortcut rule:** two searches can share Cmd or Ctrl and K. A palette with a `scope`
  opens with the shortcut only while focus is inside a region marked `paletteScope(name)` (a
  composer, an editor), and the global palette stays shut inside such a region while a palette owns
  it. A region no mounted palette owns falls through to the global palette. The shortcut still
  closes whichever palette is open. A button outside the region opens a scoped palette with
  `openScopedPalette(name)`. The bare `/` key follows the same rule. Each scoped palette lists its
  own entry in the shortcut help sheet.

---

## 14. Motion

Motion explains change. It is never decoration for its own sake. One easing family and one
duration scale keep it coherent. App code never writes a time literal (ui_lint UI005).

| Token | Value | Use |
|---|---|---|
| `--dur-instant` | 80ms | Press feedback |
| `--dur-fast` | 120ms | Hover, colour and border changes |
| `--dur-base` | 180ms | Most transitions, dialog exits |
| `--dur-slow` | 260ms | Layout moves (the rail expanding) |
| `--dur-slower` | 300ms | Dialogs, popovers, hover lifts |
| `--dur-travel` | 400ms | Sheets, toasts, gliding markers, spring settles |
| `--dur-enter` | 480ms | Content entrances: fade up, staggered lists, table rows |
| `--dur-page` | 560ms | The route entrance |
| `--dur-chart` | 700ms | Chart bars growing, hero number count-up |
| `--dur-pulse` | 2400ms | The live heartbeat, shared by every live indicator |
| `--stagger-step` | 55ms | Delay between staggered siblings |

- **Easing:** `--ease-out` (expo out) for entrances and layout moves, `--ease-spring` for small pops
  (chips, check marks, icon swaps), `--ease-in` for exits only.
- **Route entrance:** the content wrapper takes `.page-enter` on every pathname change: a fade and
  rise over `--dur-page` on `--ease-out`. It lives in the layout, so every page and sub-route gets
  it without opting in. Pages never add their own entrance wrappers. The wrapper fills the height
  of `main` so full-height pages (diagram canvas, Gantt) can size against it, and long pages still
  scroll inside `main`.
- **Entrance cascade** (all in `hub-layer.css`, no opt-in beyond the container class):
  - Stat tiles in a `.kpi-strip` fade up over `--dur-enter`, each `--stagger-step` after the one
    before, up to 6 steps.
  - Children of a `.stagger` parent (lists that are not tiles or table rows) fade up over
    `--dur-enter`, `--stagger-step` apart, up to 7 steps.
  - Table rows (`tbody tr`) rise into place over `--dur-enter` together, with no per-row delay, so
    long tables stay quick. Tables re-enter when their filters change (key the `tbody` on the
    filter state).
- **Fill mode is `backwards`, never `both`,** for content entrances: a filled end state pins
  `transform` and silently kills hover lifts. Overlays (dialogs, sheets, toasts) may use `both`.
- **Dialogs:** backdrop fade over `--dur-base`, the panel rises and focuses in over `--dur-slower`
  and exits on `--dur-base`. Sheets slide in from the right over `--dur-travel`, phone sheets slide
  up.
- **Count-up** for hero numbers: [section 18](#18-stat-tile-glow-and-count-up).
- **Live heartbeat:** every live indicator pulses on `--dur-pulse`, so live states beat together
  instead of drifting out of phase.
- **Gliding markers:** the sidebar highlight and the segmented-control pill slide between items
  over `--dur-travel` on `--ease-out`.
- **Reduced motion:** under `prefers-reduced-motion: reduce` every animation and transition
  collapses to 1ms and loops run once (`animation-iteration-count: 1`), so nothing moves or
  flickers. The presenter skips walking and holds still poses.
- **Behaviour timings are not motion.** Hover intent on the rail, tooltip delays, toast lifetimes,
  the feed rotation and shortcut sequence timeouts are named constants in the kit
  (`kit/src/lib/timing.ts`: `RAIL_OPEN_DELAY`, `RAIL_CLOSE_DELAY`, `TOOLTIP_DELAY`,
  `TOAST_DURATION`, `FEED_INTERVAL`, `SEQUENCE_TIMEOUT`), never inline numbers in components.
- **Decorative assets** (illustrations, the presenter figure, the build card) may declare their own
  timing variables once at the asset root, for example `.stick { --sf-step: 620ms; }`. Interaction
  and entrance motion always uses the scale above.

---

## 15. Behavioural layer

Sections 16 to 24 are the behavioural layer: the accent tokens, hues and recipes, and the shell
chrome on top of the primitives. It ships once, in `tokens/hub-layer.css` and the kit, and every
app inherits it by importing them. An app that re-implements any of it locally is out of standard.
Accent values in these sections are worked examples, not requirements. The per-app accent rules
are in [section 12](#12-per-app-accent-and-plain-css-port).

## 16. One accent token per app

An app's accent is set once, on the root: `html[data-app-accent="<name>"]`. In a shell that
mounts several tools, each mounted tool is an app: it sets its accent once, through the kit's
accent provider, which puts the previous accent back when the tool unmounts, and the shell sets the
default. A tool never sets it twice at the same time. A consumer that needs the accent names as data
(a module registry, a picker) reads the kit's exported list and never keeps a second one, because a
copy drifts when the kit adds a name
([section 12](#per-app-accent-token-swap-only) lists the names and the custom-accent path). No
attribute means the default accent. App CSS never sets an accent token, except a certified block
printed by `build.py --accent` (UI007). The accent re-points these tokens and nothing else:

| Token | Role |
|---|---|
| `--accent-50` to `--accent-800` | The ramp, lightest to darkest, identical in both modes |
| `--accent` | The fill (step 600). White text clears 4.5:1 on it |
| `--accent-hover` | Hover face: lighter in dark, darker in light, still 4.5:1 with white |
| `--accent-bright` | Accent text and icon ink: 4.5:1 on every content surface and on the chip |
| `--accent-dim` | Opaque chip fill (a certified wash, never an alpha that shifts per surface) |
| `--accent-veil`, `--accent-glow` | Row shading and the one tinted shadow |
| `--accent-grad` | Primary button gradient. White clears 4.5:1 at both stops |
| `--border-accent`, `--border-accent-strong` | Accent hairlines and the focus outline |
| `--focus-ring` | Two-ring focus halo, 3:1 on every surface |
| `--accent-rgb`, `--accent-rgb-d`, `--accent-fill`, `--accent-fill-d` | Triplets for alpha composites: identity hue (500), deep stop (700), fill face and base |
| `--accent-seed` | The exact brand colour, identity marks only |
| `--accent-withheld-hue` | The categorical hue this app must not use for data, or `none` |

What the accent may mark is rule 2.

**Acceptance:** static. `lint-core/ui_lint.py` reports no UI007 finding: the attribute is set
once, at the root, and no component sets an accent token. A custom accent block carries the
certification line printed by `build.py --accent`.

## 17. Categorical hues, tone and selection

Six categorical hues exist for data, never for brand: blue, green, amber, red, violet and teal, in
that order. Two extra hues, yellow and ink (the solid neutral, near black in light and a light
slate in dark so the mark still clears 3:1), are for data that is that colour by name, such as a
yellow or a black toner. They take the same recipes and certification, and never enter the series
rotation, the avatar hash or the accent withholding. In the kit `CategoricalHue` and
`isCategoricalHue` mean the six only, and `MarkHue` (`isMarkHue`) is the wider set every `hue` prop
accepts (`EXTRA_HUES`). Each is a bright identity triplet (`--hue-<name>`) plus a deep stop (`--hue-<name>-d`)
that holds white text at 4.5:1 in both themes. The values live in `tokens/tokens.json` (group
`categorical`) and are certified in `tokens/CONTRAST.md`: bright values clear 3:1 as marks on every
content surface in both modes, and white text clears 4.5:1 on every deep stop. Data takes them in
order minus the hue the accent withholds (rule 2, the kit's `categoricalPalette`).

**Hue classes.** A `.hue-<name>` class sets `--hue` and `--hue-d` on the element, so any recipe
that reads them (tone, the hue tile, the stat tile, a bespoke gradient) follows. Add it alongside
any element that uses `--hue`. Nav icons use `data-hue` instead, which also accepts `brand`
([section 6](#sidebar)).

**Tone** (identity, status, severity) is `.tone` on an element with a `.hue-*` (the kit's `Tone`,
or `Card tone`): a radial wash from the top-left corner,
`radial-gradient(140% 120% at 0% 0%, hue/0.13, hue/0.04 45%, transparent 75%)`, plus a hairline
border of `hue/0.34` all the way round, paired with a `.hue-tile` icon (`HueTile`, fill
`hue/0.14`, border `hue/0.32`). `.tone-hover` applies the same on hover or focus only.

**Selection** (active nav marker, active tab, selected row or card, active search result, active
filter chip) is a raised neutral surface: `--surface-3` with a full
`inset 0 0 0 1px var(--border-strong)` ring, the `--shadow-inset-top` sheen and `--shadow-xs`, and
`--text-primary`. No indicator bar on any edge (rule 1) and no accent wash. Secondary text inside a
selected row stays `--text-secondary`, which is certified on `--surface-3`.

The `[class]` attribute in the `.tone[class]` and `.is-selected[class]` recipes doubles specificity
so the primitive wins over a card's own border and background utilities.

**Acceptance:** review. Chart and badge colours come from the kit palette helper in order, and
tone and selection use these recipes. Edge bars are rule 1 (UI001).

## 18. Stat tile, glow, and count-up

Hero KPIs use one primitive, the kit's `StatTile` (rule 4). It renders `.kpi-tile` with a
`data-tone` (accent, success, warning, danger, info) or a `.hue-*`, and `hub-layer.css` styles
`.kpi-tile`. The kit also emits `.stat-tile` on the same element so markup from before the kit
keeps matching, but no recipe styles `.stat-tile` and new CSS never targets it. Group tiles in a
`.kpi-strip` to get the entrance cascade ([section 14](#14-motion)).

- **Fill:** the deep hue stop, `rgb(var(--hue-d))`, `--radius-2xl`, with the gloss overlay
  `linear-gradient(150deg, var(--on-fill-gloss) 0%, transparent 44%, var(--on-fill-shade) 100%)`.
- **The one glow recipe** (rule 3): `0 10px 30px -10px rgb(var(--hue) / var(--glow-a)), var(--shadow-key)`,
  where `--glow-a` is theme-gated (strong in dark, faint in light).
- **Text** uses the on-fill inks, certified at the gloss peak: the value in `--text-inverse` at
  `--fs-hero` weight 800, the label in `--on-fill-label` (reserving two lines so values share a
  baseline across a row), the hint in `--on-fill-hint`, and the icon box on `--on-fill-chip` with
  an `--on-fill-line` border.
- **Phones:** below 640px a grid of tiles goes two-up with a compact tile, and an odd last tile
  spans the row.
- **Count-up:** numeric values count up once on mount over `--dur-chart` with an ease-out cubic.
  The animation depends on the value text only, preserves prefix, suffix, grouping and decimals,
  and is skipped for values below 2, non-numeric values, hidden tabs and under
  `prefers-reduced-motion: reduce`. It always lands on the real value, even when the browser
  throttles animation frames.

**Acceptance:** a unit test drives requestAnimationFrame with a fake clock and asserts an
intermediate value and the exact final value, and a second asserts the reduced-motion path renders
the final value with no frame requested.

## 19. The desktop icon rail

Above 900px the sidebar (`Rail`) is an icon rail `--rail-w` wide (58px, declared by
`hub-layer.css`). Hovering it for `RAIL_OPEN_DELAY`, or focusing any control inside it, opens it to
`--sidebar-w` over the page (the page does not reflow) with `--elev-5`, and leaving closes it after
`RAIL_CLOSE_DELAY`. Labels dissolve in one after another. A pin button in the brand row, and the
`[` key outside text fields, keeps it open, and then the page reflows to `--sidebar-w`. The pin is
one preference per browser, stored under `shell.sidebar.pinned`. Collapsed, nav labels stay in the
accessibility tree but are visually hidden, group labels, the build card and the footer are
hidden, and the rail shows a `v<major>` pill. The status line under the footer is either the
app's own `status`, rendered exactly as given (the kit adds no version to it), or the standard
line built from `environment` (an accent badge), `v<version>` and `statusText` (the organisation
or other app text). `showVersion={false}` drops the version from that line when the footer
already shows it, so the version never appears twice. The gliding marker is described in
[section 6](#sidebar). At or below 900px the drawer of
[section 11](#11-mobile--responsive-shell) applies.

**Acceptance:** runtime. A Playwright check asserts `data-rail` moves collapsed, open, pinned and
back with real mouse movement and the `[` key, that the pin persists across a reload, and that no
horizontal overflow exists at 390px.

## 20. Announcements, the pulse feed, and the presenter

Every app with an admin area and more than one audience ships announcements. An app with a single
audience does not owe them, and the rule does not apply to it.

- **Contract:** a table with `title` (120 characters), `body` (500), `tone` (`info`, `success`,
  `warning`, `critical`), `starts_on` and `ends_on` as inclusive local calendar days (a future
  start schedules it, no end keeps it up until removed), and `created_by`. The permission
  `action:admin:announcements` is held by the Admin role only. Create, update and delete are
  audited. `GET /api/announcements/active` is readable by every signed-in user and returns at most
  five, most severe first.
- **Editor:** live counters on title and body, a status of Live, Scheduled or Ended derived from
  the dates (the list orders Live most severe first, Scheduled soonest first, Ended faded), and a
  live preview of both surfaces with a one-line delivery summary.
- **Banners** (`AnnouncementBanner`, `AnnouncementStack`): tone cards (the tone recipe of
  [section 17](#17-categorical-hues-tone-and-selection), never the accent) with a severity glyph,
  on the home page only. Non-critical ones are dismissible per announcement id in local storage.
  Critical ones cannot be dismissed and carry `role="alert"`.
- **Pulse feed:** `GET /api/pulse` merges live announcements with operational signals the caller
  can already see.
- **Presenter** (`FeedStrip`, `Presenter`, in the header on every page): one item at a time, each
  for `FEED_INTERVAL`, with a mascot pose derived from the tone (a megaphone for announcements, a
  bubble outlined by tone), dots, previous and next controls, a pause control (hover and focus also
  hold it, WCAG 2.2.2) and a search trigger. Items keep rotating on their own. Previous, next and a
  dot jump straight to an item and restart the timer, so the operator can step through faster than
  the rotation without the next tick cutting the chosen item short. A health line shows even when the backend is down. Clicking an item opens its
  page.

**Acceptance:** static plus unit, for an app with more than one audience (a single-audience app owes
none of this). The migration exists on every database dialect the app ships,
the permission is in the RBAC registry and in the Admin role seed and grant map, and a unit test
asserts the window, the ordering, the cap and the 403 on each write.

## 21. System Health request analytics

System Health carries a request panel: a 1h, 24h and 7d range control, four tiles (requests,
error rate, average latency with p95 and max, uptime with peak memory) and a bar chart with
error segments. Data comes from an in-memory ring buffer (20,000 samples) holding only
time, status and duration, behind `action:admin:health`, and it resets on restart. It stores no
path, query, actor or request content. Demo traffic may be seeded only when the environment is
explicitly development.

**Acceptance:** unit. The summary asserts bucket counts (24 for 1h and 24h, 28 for 7d), the
error percentage, and that an unknown range is rejected.

## 22. Build card and release notes

The build card (`BuildCard`) sits at the foot of the sidebar, under the profile card:

- A live or offline dot, the version in a mono pill whose characters roll into place
  (`RollingText`, a prerelease suffix shows as a small violet tag), a "Built by" line, a soft
  aurora and a one-time sheen (again on hover).
- A "New" pill opens What's new (`ReleaseNotesDialog`) for the current major release, with the
  build date and commit. The pill clears once that version's notes have been opened.
- Builds stamp the version, the commit sha and the build time.
- Notes are generated at build time from git history by the kit's `scripts/gen-changelog.mjs`:
  `feat` becomes New, `perf` Improved, `fix` Fixed, other types are dropped, PR numbers, hashes,
  links and scopes are stripped, and a `Changelog:` line in the commit body replaces the subject.
  Where the build has no git history, see the deploy pitfall in
  [section 25](#25-required-chrome-what-every-app-with-a-sidebar-must-mount).

- When the notes must follow the user's permissions (an app hosting several tools, where people may
  not see what they cannot open), the app serves them from its API behind the same permission as the
  tool and the card reads them from there. Nothing about a tool ships in the bundle. Such notes may
  be summarised by category and carry no date, and the dialog may carry one `link` to the full
  changelog in the docs home, which applies the docs home's own access. A dialog that lists several
  tools gives each release its own `link`, and the card's `seenKey` changes with the newest
  releases so the New pill returns when any tool ships. Only http and https links render.

**Acceptance:** unit. The parser keeps only the three types, strips references, and prefers a
`Changelog:` line. The dialog renders a dateless release and drops a link that is not http or https.

## 23. Reversible actions undo, irreversible ones confirm

The rule is rule 8 of section 0. The toast mechanics are in [section 7](#toasts-toaster-usetoast)
(one action per toast, clicking it runs the callback and dismisses), and native dialogs are rule 7.

**Acceptance:** a unit test mounts the toast provider, clicks Undo, and asserts the callback ran
once and the toast closed.

## 24. Shell chrome added by the behavioural layer

The chrome itself is owned elsewhere: the palette by [section 13](#13-global-search-palette),
tab strips by [section 7](#tabs-and-segmented-toggles-tabs-segmented), the theme toggle by
[section 6](#header-header-every-page), the mascot in empty states by
[section 7](#loading-and-empty-states-skeleton-emptystate), the primary button press by
[section 7](#buttons-button-iconbutton). This section owns one rule: all of that chrome is
accessible.

**Acceptance:** runtime. axe-core reports zero violations on the home, health and announcements
pages in both themes, and the palette test asserts Escape closes it from a focused result row.

## 25. Required chrome: what every app with a sidebar must mount

An app is not on this standard until its shell mounts all of the following. Matching colours and
radii is not enough. The behaviour must be present and must work when clicked.

| Piece | Requirement | Acceptance |
|---|---|---|
| Icon rail | [Section 19](#19-the-desktop-icon-rail): `--rail-w` collapsed, opens on hover or focus, pin with `[`, gliding marker | `data-rail` moves collapsed, open, pinned |
| Nav icon hues | [Section 6](#sidebar): each destination carries a categorical hue, `brand` follows the app accent | Each `.nav-icon[data-hue]` resolves to its token in both themes |
| Build card | [Section 22](#22-build-card-and-release-notes): live dot, rolling version, "New" pill, and a "What's new" popover | Clicking the version opens a dialog with at least one entry |
| What's-new data | Built from git history, present in the deployed bundle | The deployed bundle contains entries. A build with no history fails CI rather than shipping a disabled button |
| Live feed strip | [Section 20](#20-announcements-the-pulse-feed-and-the-presenter): presenter with the mascot, pause, search trigger, health line always, pulse and announcements when the backend has them | The strip renders and shows a health line with the backend down |
| Announcement banners | [Section 20](#20-announcements-the-pulse-feed-and-the-presenter): home page only, dismissible per id | Banner absent off the home page |
| Command palette | [Section 13](#13-global-search-palette): Cmd or Ctrl and K, Escape closes from anywhere | Palette test passes |
| Theme toggle | [Section 6](#header-header-every-page): circle reveal, instant under reduced motion | Both themes verified with no console errors |
| Home button | Rule 9: the header mounts `.hub-btn`, which goes to the app home (the hub in a multi-tool shell) | A test finds one `.hub-btn` in the header and clicking it lands on the home route |

**Deploy pitfall.** A source upload to a hosting platform carries no git history, so a changelog
built from `git log` at build time is empty there and the build card shows a disabled version. Generate
the changelog in CI from a full-history checkout, write it to a file inside the app, and let the build
read that file when git is unavailable.

**Acceptance:** an overlay's CI fails when an app with a sidebar lacks the build card with changelog
data or the feed strip. A lint that greps the shell for both components is the minimum.

## 26. Several apps on one origin

A shell can mount several tools at different paths of one origin, as one single page app with a
module per tool or as separate bundles. They share the origin, so they share `localStorage`,
cookies and the auth cache.

1. **Each mounted app has an `appId`.** Pass it to the shell (`AppShell appId`, `StorageScope`) so
   seen and dismissed state (announcements, build card, tips) stays per app. Theme and rail pin stay
   shared on purpose, so the shell looks the same in every tool.
2. **Each tool owns one path prefix.** Its routes live under `/<id>/*`, the shell wraps it in a route
   guard, and the guard admits no one the server would refuse.
3. **Switching tools goes through the hub or the tool rail**, never through a link built by hand
   (rule 9).

**Acceptance (test):** two apps with different `appId`s on one origin dismiss a banner in one and
still show it in the other, while a theme change in one applies to both.

## 27. The help layer

A console explains itself where the person is looking: a short tip on the thing, a plain word list for
the domain, a help drawer for the page, and times and states that say what they mean. The kit has a part
for each and the eight rules below say when to use them. A tip is an aid for the pointer and the
keyboard. It is never the only place a fact lives (rule 7). The number of this section and of its rules
is provisional: the core assigns the final numbers when it merges.

| Need | Part | What it does |
|---|---|---|
| Show every tip | `TooltipLayer`, mounted by `AppShell tooltipLayer` | One layer per page. Off by default. A second mount never draws a second tip |
| Put a tip on anything | `useTip(text)`, or the `tip` prop of a kit part | `data-tip` plus a hidden description wired with `aria-describedby`, so a screen reader gets the words the layer shows |
| A control that cannot be used now | `Button disabledReason`, `Modal` `primaryAction.disabledReason` | `aria-disabled` instead of `disabled`: it stays focusable, a click does nothing and the reason is its tip and its description. `loading` wins while both are set |
| A status | `Badge tip`, `StatusDot tip` | A mark with a tip is focusable and reads the tip as its description |
| A domain word | `GlossaryProvider` (or `AppShell glossary`), `Term`, `InfoTip` | The app registers `{ id: { term, short, long?, href? } }` once. `<Term id>` shows the word with a dotted underline, focusable, with the short text as its tip. `InfoTip` is an info icon button with an accessible name whose click opens a popover with the long text and the link. An unknown id renders plain text and warns in development only |
| A time | `When` | Relative text ("2 h ago"), the absolute date, time and zone as the tip, a `timeZone` prop, and one shared clock for the page (`CLOCK_TICK`) |
| What this page is for | `usePageHelp`, `HelpDrawer`, the Header Help button | A page registers `{ title, summary, steps, terms, links }`. `AppShell helpDrawer` mounts the state and the drawer (off by default). The Help button shows while a page has help and opens the drawer. `useHelpPaletteItems()` lists the topics in the command palette |
| A process or a history | `Stepper`, `Timeline` | `Stepper`: steps in the state done, current, upcoming, failed or waiting, each with a detail, a meta, a "waiting on" line and an actions slot. `Timeline`: time, actor, one sentence, a source chip and a link. The connector line is a data mark (an order), not an accent |

1. **An icon-only control has an accessible name and a tip that says its verb.** "Remove host", not
   "Trash". `IconButton` requires `label` and uses it for both. A control that holds only an icon (a
   `button` or `a`, or a kit `Button` with `icon` and no children) carries `aria-label` and
   `data-tip`, and a native `title` counts as the tip. The UI lint reports UI012.
2. **A disabled control says why and how to enable it.** Use `disabledReason` instead of `disabled` on a
   kit `Button` or `IconButton`, in one or two sentences that name what is missing and how to get it
   ("Choose a pool first. The size applies to that pool."). The UI lint reports UI011 for a kit button
   with `disabled` and no `disabledReason`. A button that is `loading` is busy, not blocked, and is
   left alone.
3. **A status badge or dot says what the state means and whether it is normal.** The label is the short
   plain word. The tip says what it means, whether anyone has to act and, when the label translates a
   raw value, the raw value ("The scaling plan turned it off because nobody needed it. Not a problem.").
   Use `Badge tip` and `StatusDot tip`. The label and the tone carry the state as well, because colour is
   never the only signal.
4. **The first use of a domain term on a page is a glossary `Term`.** The app registers its glossary
   once. The page lists the ids it uses in `usePageHelp({ terms })`, so the drawer explains them in full.
   One `Term` per word per page, on its first use, is enough.
5. **A timestamp is relative, with the absolute date, time and zone in the tip.** Use `When`, and
   `Timeline` for a history. Pass `timeZone` when the people who read the page work in one zone, otherwise
   the viewer's zone is used. A date that is the subject of the page (a schedule, a due date) shows in
   full with its zone instead.
6. **A person is shown by name, with the email or login in the tip.** A login or an id is never the only
   label. `Timeline` takes `actor` and `actorTip`. Elsewhere put the address in the tip of the name
   through `useTip` on a focusable element.
7. **A tip never holds the only copy of something needed to act.** A tip explains and the page acts: a
   value, a step, a link or a warning that a person needs is text on the page or in the help drawer. Tips
   do not show on touch and hide on scroll and pointer down. The reason of a disabled control is a tip by
   design (rule 2), so when it is the next step, say the step in the page text too.
8. **A tip is one or two short plain sentences.** Never over 200 characters, with no markup and no
   list. Anything longer goes into the `InfoTip` popover, the page help or the page itself. The UI lint
   reports UI013 for a literal `data-tip`, `tip` or `disabledReason` over 200 characters or in three or
   more sentences.

**Acceptance:** `lint/ui_lint.py` reports no UI011, UI012 or UI013 finding in the app. Rules 3 to 7 are
checked in design review of each page. The kit tests `help-tips`, `help-time`, `help-drawer`,
`help-process` and `tooltip-shell` prove the parts, and `a11y.test.tsx` runs axe with the Help drawer
open.
