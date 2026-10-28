# Multi-module web shell

Applies when one origin serves more than one tool. [web-build.md](web-build.md) covers a single app
and its tools manifest; this adds what changes when several modules share a shell.

## 1. Two shapes

- **Several apps on one origin.** Each app is its own build and mounts its own provider. An auth
  library holds the one signed-in session and each app reads it.
- **One shell, many modules.** The shell signs in once and mounts modules into its content
  column. A module carries no sign-in UI. The shell signs in one of two ways: through the hosting
  platform (the platform holds the session in a cookie and no token ever reaches the browser), or
  through a sign-in client in the shell that holds the token and hands it to modules.

Pick one per product. Do not mix them: a module that signs in on its own inside a shell races the
shell's sign-in.

In the one-shell shape a module never tries a silent sign-in frame on load. A module with no
session bounces to the shell's sign-in (section 8). A hidden frame only waits out its timeout,
about 10 seconds, on every signed-out load.

## 2. Which client-runtime sections apply

| [web-client-runtime.md](web-client-runtime.md) section | Several apps | One shell, sign-in client | One shell, platform sign-in |
|---|---|---|---|
| 1. Auth boot | each app | the shell only | does not apply: the platform signs in before the page loads; the shell reads the identity endpoint once |
| 2. Token renewal | the auth library | the shell; modules ask it for a token | does not apply: no token is in the browser to renew or leak |
| 3. API client | each app | one client, shared by modules | one client, shared by modules, sending the platform cookie |
| 4. Bundles | per app | per module, loaded on first open | per module, loaded on first open; lazy routes matter more, since one shell is one entry |
| 5.1 One client package | the auth library | the module contract and registry | the module contract and registry |
| 5.2 One token cache | the auth library's shared cache | the shell's cache | does not apply: there is no token cache |
| 6. Live feed strip | each app | the shell, once | the shell, once |

Platform sign-in removes the token code entirely, so every rule the client runtime proves with tests
in sections 1, 2 and 5.2 holds by having no such code. The cost is one bundle for the whole shell.

## 3. Registry generated from manifests

Each module has a manifest. A script generates the registry (the module list and one icon map with
a fallback icon) from the manifests, and nobody edits the list by hand. CI regenerates it and fails
when the committed file differs (a staleness check).

The core ships the generator as `scripts/build-registry.mjs` (synced into the app from
`kit/scripts/`). It takes the manifest pattern, the output file and `--check`:

```sh
node scripts/build-registry.mjs --manifests "modules/*/module.json" --out src/generated/registry.ts
node scripts/build-registry.mjs --manifests "modules/*/module.json" --out src/generated/registry.ts --check
```

A manifest is ASCII JSON with `id`, `name`, `accent` and optionally `route`, `icon`, `order` and
`description` (the `ModuleManifest` type in the kit). The generator rejects an id that is not a
lowercase slug, a duplicate id or route, a route whose first segment is not the id, an unknown key
and an accent that is not a kit accent, and it reports every problem at once. Output is
deterministic: modules sort by `order`, then id. The generated file exports `MODULES` (every
default resolved), `ICONS` (module id to icon name) and `FALLBACK_ICON` (`--fallback-icon`, default
`Box`).

The shell's own per-module manifest (rail pages, links, tiles, Home feeds, API and permission read) is
documented in [web-shell-manifest.md](web-shell-manifest.md); it is a host extension of this manifest. The shared packages a shell keeps its cross-module logic in are in
[web-shell-packages.md](web-shell-packages.md).

### Host extensions (opt in)

A shell often needs more per module than the seven kit keys (a tagline, a client folder, links,
permissions). The generator keeps rejecting an unknown key unless the host names it, so a typo is
still caught:

- `--allow-keys a,b,x-*` (repeatable, comma separated). A name ending in `*` is a prefix, so `x-*`
  allows every key that starts with `x-`. The kit keys cannot be listed, and `__proto__`,
  `constructor` and `prototype` are never allowed.
- An allowed key is carried into the generated entry after the seven kit fields, sorted by name.
  The file exports `ModuleExtras`, a type inferred from the values (a key one manifest omits is
  optional, an array is `readonly`, an object merges by key), and types `MODULES` as
  `RegistryEntry<ModuleExtras>`. The values stay data, so a manifest is still checked into the
  staleness test: a changed host value fails `--check`.
- `--extra-accents brand` (repeatable, comma separated) adds host accent names to the kit list, for
  a shell whose own module carries an accent the kit does not define. The generated file then
  exports `ModuleAccent` (`AppAccent` or the host names) and types the entries with it. The host
  owns the CSS for the extra accent (the `data-app-accent` rules), the kit only validates the name.
- `--validate-with check.mjs` loads a module (relative to the project root) whose default export, or
  `validate` export, is called as `(manifest, { label, dir, root })` for every manifest that passed
  the kit checks. It returns a list of problem strings, for example that a `client` key names an
  existing folder or that the folder name equals the id. A throw is reported as a problem. Only the
  command line loads the hook. A program that calls `run()` passes `{ validate }` as the third
  argument instead.

With none of the three options the generator behaves and writes exactly as before.

On the type side, `ModuleManifest`, `RegistryEntry`, `GeneratedRegistry` and `ModuleDescriptor`
take optional type arguments: `ModuleDescriptor<TRoutes, TExtra, TAccent>`, where `TExtra` is the
host's own members and `TAccent` its accent union. The defaults are an empty extra and the kit
accents, so an existing descriptor is unchanged and a descriptor with an unknown accent still
fails the typecheck unless the host widened it.

**Acceptance (test):** a manifest added without regenerating fails CI (`--check` exits 1, as it does
for an edited or removed manifest and for a hand edit of the file). A module with no icon gets the
fallback in both `MODULES` and `ICONS`.

## 4. Standalone or hosted from one route table

A module exports one route table and a typed descriptor. The standalone entry mounts it in a
minimal host, and the shell mounts the same table. There is no second shell per module. A manifest
test per module keeps the manifest and the route table aligned.

The descriptor type is declared once in the shell's shared package and imported by every module, so
a module that drifts fails the typecheck. It carries at least: the module id (the same as the
manifest's and the first path segment), the display name, the route table, the rail entries with
the permission check that filters them, the accent name, the icon name, and the module's banner and
feed sources. A module also exports a host hook (`configureHost`) through which the shell hands it
the shared sign-in client; the first call wins and later calls are ignored, so a module never
imports the shell.

The kit declares the contract once, in `kit/src/shell/module.d.ts`, and exports it from the kit
root: `ModuleManifest`, `RegistryEntry` and `GeneratedRegistry` (what the generator writes),
`ModuleDescriptor<TRoutes>` with `ModuleRailEntry` and `ModuleFeedSource`, and `ConfigureHost`.
`TRoutes` is the router's own table type, so the kit stays free of a router. The accent is typed as
a kit accent, so a descriptor with an unknown accent fails the typecheck.

**Acceptance (test):** a descriptor that drifts from the type (an unknown accent, a missing rail)
fails the typecheck, and a manifest test per module keeps the manifest and the descriptor aligned.

## 5. Per-module CSS scope

Build each module stylesheet inside `:where([data-module="<id>"])`. `:where` adds zero
specificity, so the cascade stays as [web-ui.md section 7](web-ui.md#7-shared-primitives) defines
it (unlayered app CSS beats the kit) and one module's CSS cannot restyle another. Keyframes cannot
be scoped, so they stay global: name each one `<id>-<name>`. Font faces stay global too. The
build maps `:root`, `html`, `body` and `#root` in a module sheet onto the element that carries
`data-module`, and that element wraps the module's portal root, so dialogs and toasts still match
the module's rules. The shell loads the one token sheet once; a module sheet never imports it again.

The core ships the build step as `scripts/scope-css.mjs` (synced into the app from `kit/scripts/`),
a PostCSS plugin written as a plain object, so the app imports nothing extra. It takes a map of
absolute sheet path to module id and leaves every other sheet alone:

```js
import { scopeModuleCss } from './scripts/scope-css.mjs';
// vite: css.postcss.plugins
scopeModuleCss({ [resolve('src/modules/a/index.css')]: 'a' });
```

Rules inside `@media`, `@supports` and `@layer` are scoped and the at-rule is kept. A keyframes name
without the `<id>-` prefix is a warning (an error with `strictKeyframes: true`). A root token is
mapped only at the start of a selector, so a module sheet styles the theme through the kit tokens
and not through a theme attribute on the root, which lives on the document element.

Two opt-in options cover hosts that differ from the default. `root: 'document'` is for a host that
sets `data-module` on the document element itself: `:root` and `html` stay on the document element
and are scoped to it (`:where(html[data-module="<id>"])`), while `body` and `#root` stay descendants
of it. The default, `root: 'wrapper'`, is the behaviour above. `keyframes: 'rename'` prefixes an
unprefixed keyframes name with `<id>-` and rewrites the `animation` and `animation-name` references
in the same sheet, instead of only warning (`'warn'` is the default, `'strict'` errors). A reference
from another sheet or a script is not seen, so name those keyframes by hand.

**Acceptance (test):** a rule in a module sheet matches only inside that module's `data-module`
element, portal root included, and never inside another module or outside any module. `:root`,
`html`, `body` and `#root` map onto the module element. Keyframes and font faces come out unchanged.
Scoping twice gives the same selector. With `root: 'document'`, `:root` and `html` match the document
element only while it carries the module's `data-module`, and `body` and `#root` match as its
descendants. With `keyframes: 'rename'`, the keyframes and every reference to it in the sheet carry
the `<id>-` prefix.

## 6. Per-module storage scope

Give each module its own `appId` so a seen version, a dismissed banner or a saved filter in one
module never hides another's. The kit already keys local storage by `appId`.

## 7. One accent per mounted module

Mount each module inside the kit `AccentProvider` with its own accent. The provider restores the
previous accent on unmount, so moving between modules switches the accent with no leftovers.
The names are data (`@build-standards/kit/accents.json`), so a manifest check can validate them.

## 8. Safe return-target bounce

A module that finds no session sends the user to the shell's sign-in with a return target, and the
shell sends them back after. The shell validates the target and falls back to home. Reject:

- a protocol-relative target (`//host`);
- a backslash;
- any control character;
- a target longer than 2,048 characters;
- anything that resolves to another origin.

Only a same-origin path is accepted. **Acceptance (test):** each rejected shape returns the home
route; a plain in-origin path survives.

## 9. Home is the hub

In a multi-module shell, home is the hub: the page that lists the modules the user can open. Module
pages never claim `/`. The header Home link, the bounce fallback and the palette all point there.

The hub is built from the kit's hub home parts, which take their data through props and never name a
module:

- **Layout.** `HubHome` places keyed blocks in three zones: the strip (`waiting`, `actions`), the
  main pair (`live`, `fleet`) and the side (`pinned`). The host's own tile list says which blocks
  show and in what order. A hidden or empty block leaves no gap, and DOM order is reading order.
- **Blocks.** `FeedBlock` renders the feed sources of the modules the person can open: a skeleton
  while a source has not answered, one quiet line for a source that could not be read, an empty
  state otherwise. A module supplies numbers and short names as plain data, never markup, and a
  contribution shows only when the person holds the permission it names. `ActionsBlock` is one
  button per quick action. `PinnedBlock` lists pinned pages with an unpin button, then recent pages
  (kept by the host, per account, never the hub itself).
- **Navigation.** Rows are real anchors (`HubLink`) that open through the shell navigator on a plain
  click, so a new tool mounts in place and middle click and copy link still work.
- **Pinning the current page.** `PinButton` sits in every module header and pins the page the person
  is on, but only a page the module declares (the rail's own pages, found with `pageAt`), never a
  dynamic detail route, and never the hub itself. The host implements the `PinsStore` contract
  (`snapshot`, `subscribe`, `pin`, `unpin`, an optional `load`) over its own storage, and the header
  control and the pinned block read the same store so they always agree. A read that is refused or
  fails puts the store in the `denied` state: the control is absent and the block shows recents only.
  A pin is display only, the page it opens still enforces its own access. The store has a maximum
  (default 12), and at the maximum the control is disabled and says why.

**Acceptance (test):** pinning then unpinning the current page changes the store and the control's
label; with a denied read the control renders nothing; a block fed a source in `error` shows one
quiet line and still renders the other sources.

## 10. Layout and mounting

- **One `AppShell` per active module,** not one shell wrapped around all of them. The shell passes
  the module's `appId` (section 6), so seen versions and dismissed banners stay per module.
- **Rail.** A tool switcher sits in the rail brand row through the kit `Rail` `brandSlot`, never by
  finding the kit's markup by class name. Below it come the active module's own entries, filtered
  by the module's own permission check. Rail entries are display only: each module's server
  enforces its own permissions. The account menu sits in the rail `footer`.
- **Tool switcher.** `ToolSwitchButton` in the `brandSlot` names the active tool and opens
  `ToolLauncher`, a full window `Modal` carousel of every tool the person can enter. The host passes
  plain `LauncherTool` data (id, name, tagline, description, hue, an optional mark, `external`) and
  decides who can enter what, the launcher only displays it. The focused tool sits large in the
  centre with the others smaller and dimmed (three or more wrap around), and its details and an
  Open button show below. Left and Right, Home and End, the arrow buttons, the dots, a swipe and a
  click on a side tile move it, Enter or a click on the centre tile opens, Escape and Back close
  and focus returns to the control that opened it. `t` opens it from anywhere outside a text field
  (`useToolLauncher`, listed in the shortcut help). The current tool is marked and never opens
  itself, an external tool opens outside the shell and says so. A tool list still being read shows a
  quiet loading line, and an empty list an empty state. The `prominent` button variant is for a
  screen with no rail (a no-access screen). By default the collapsed rail hides the
  `brandSlot`, so the shortcut and that variant are the other ways in. To keep the control there, set
  `keepBrandSlotCollapsed` on `Rail` and `collapsible` on the button: the slot then stays on its own line
  under the brand mark and the control shows only its mark with a small corner glyph chip (the same form
  is `variant="mark"`). Its name, tooltip, `T` hint and popup state do not change, Enter on the current
  tool in the launcher stays a no op, and the full form returns when the rail opens or pins and in the
  mobile drawer. Every duration and curve is a motion token
  (`--dur-travel`, `--ease-out`): the dialog grows from the control that opened it, the tiles slide,
  the details crossfade in the direction of travel, the active ring turns and the focused tile
  breathes. The carousel advances by itself (`autoAdvanceMs`, default 4.2 s) and holds still on
  hover, keyboard focus and any interaction (`idleMs`, default 9 s), with a Stop button. Under
  `prefers-reduced-motion` nothing moves on its own: no auto-advance, no Stop button, no
  animation. Below 640px the far tiles are dropped and the step shrinks, so the focused tile and
  its neighbours always fit.
- **Account menu.** `AccountMenu` is the signed-in account: the avatar, the name and the role (or
  the email) in a trigger, and in the panel the email, the role, the facts the host supplies as
  `AccountFact` rows (how access was granted, when the person was last seen), the Light, Dark and
  System choice (`Segmented`, through `ThemeProvider`), the host's links (new tab, `noopener`,
  passed through `safeHref`) and Sign out. It takes an `AccountIdentity` and never reads one from
  anywhere, and it renders nothing without a name or an email. Sign out is the host's
  `onSignOut`: the panel closes when it resolves, and when it rejects the panel stays open with an
  inline alert and the button works again. Leave `onSignOut` out for no button, and set
  `showTheme={false}` where there is no `ThemeProvider`.
- **Search key.** A bare `/` opens the `CommandPalette` (next to Cmd or Ctrl and K) and the help
  dialog lists it. It never fires inside an input, a textarea, a select or an editable region
  (`isTypingTarget`, which reads the `contenteditable` attribute as well as the computed value),
  with Ctrl, Meta, Alt or Shift held, on a key repeat, during input method composition, when
  another handler already took the key, or while another dialog is open. `slashOpens={false}` turns
  it off for a page that gives `/` another meaning.
- **Header and strip** come from the kit (search, pin, theme). The strip shows the active module's
  banner and feed.
- **Mount.** Each module is a lazy chunk. The shell calls its host hook, then renders it inside the
  accent provider (section 7) under the `data-module` root, with its own router at
  `basename="/<id>"`. Switching modules remounts, so no module state leaks into the next one.
- **Route.** The first path segment names the module. A plain same-origin link into another module
  navigates in place with no full reload. The static host rewrites every module prefix to the one
  index page.
- **Brand.** The product name is a build-time setting. A module's accent is its only per-module
  brand.

**Adding a module:** add its manifest (id, name, route prefix, accent, icon), export the descriptor
and host hook from its client package, add the package to the shell with its loader entry, its API
base URL and the static host rewrite for its prefix, then regenerate the registry (section 3). Keep
the lists the shell still holds by hand to that one change.

**Acceptance (test):** switching modules remounts the module (state set in one is gone in the
other); a same-origin link into another module does not reload the page; a module's rail entry the
caller lacks permission for is not shown, and its route still answers 403 from the server.

**Acceptance (test):** the switcher opens centred on the active tool, moves with the keyboard, the
buttons and the dots, never moves on its own under reduced motion, and gives focus back to its
button on close. The account menu shows the identity and facts it is given, changes the theme,
signs out and keeps its panel open with an alert when sign out fails. `/` opens search from the
page and does nothing in a field, an editable region, with a modifier or over another dialog.
