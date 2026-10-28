# Shell module manifest (`console.module.json`)

Applies to a multi-module shell ([web-shell.md](web-shell.md)) whose modules declare their rail entries,
dashboard tiles, links, Home contributions, API gateway and permission read in one JSON file each. This is
the manifest a shell that runs today reads; the schema is
[schemas/console.module.schema.json](schemas/console.module.schema.json) (JSON Schema draft 2020-12).

The registry generator, its host extension flags and the staleness check are in
[web-shell.md](web-shell.md) section 3 and are not repeated here. This document adds the keys the shell
manifest carries on top of the seven kit keys, and the rules around them.

## 1. What a manifest is

One file per module, `apps/<dir>/console.module.json`. A second module hosted inside an app lives in
`apps/<dir>/modules/<id>/console.module.json`: the folder name equals `id` and `client` equals
`apps/<dir>/client`. The file is plain ASCII (tab, LF, CR and 0x20 to 0x7e); any other byte stops the
generator. A `$schema` key is an editor hint, deleted before validation and never written to the registry.

The generator reads every manifest and writes it, untouched apart from `$schema`, into the generated
registry. It applies no defaults: a default is applied when the shell reads the registry (section 3), so the
file on disk and the registry stay exactly what the author wrote. Modules sort by `order`, then `id`.

**Unknown keys are allowed.** The shell's validator has no allow list and no unknown-key check, so an extra
key at any level passes and is carried into the registry. The schema sets no `additionalProperties` for the
same reason. A host that wants a typo caught uses the generator's `--allow-keys` (web-shell.md section 3),
which is stricter than the shell's own validator; the two settings are a choice per host.

**Generator flags.** The shell keys are host extensions to the kit keys, so one command takes the
manifests as they are:

```sh
node scripts/build-registry.mjs --manifests "apps/*/console.module.json" --manifests "apps/*/modules/*/console.module.json" \
  --out src/generated/registry.ts \
  --allow-keys tagline,client,api,rbac,groups,pages,links,tiles,landing,whatsnew,home,'x-*' \
  --extra-accents brand
```

`brand` is the shell's own accent (the host owns its `data-app-accent` CSS, web-shell.md section 3); the
other accents in the schema are kit accents. The id rule here (section 2) is tighter than the kit's slug rule,
so a manifest that passes this document passes the generator.
`kit/tests/console-manifest.test.ts` builds the fixtures through the generator with exactly these flags.

## 2. Field reference

Printable ASCII means 0x20 to 0x7e. A key is `^[a-z0-9][a-z0-9-]{0,63}$`, a path is `^/[a-z0-9\-/]*$`, an icon
name is `^[A-Z][A-Za-z0-9]{1,40}$` (an icon component name looked up in the shell's icon map; an unknown name
draws the fallback), an order is an integer from 0 to 100000.

### 2.1 Top level

| Field | Required | Rule | Meaning |
|---|---|---|---|
| `id` | yes | `^[a-z][a-z0-9-]{1,31}$`, unique in the registry | Module id, the first URL path segment and the router basename (`/<id>`); the module that owns `/` is `console` |
| `name`, `tagline` | yes | printable ASCII, 1 to 160 characters | Launcher, rail switch and header text |
| `description` | no | printable ASCII, 1 to 400 characters, no `<` or `>`, no leading or trailing space | Launcher text. An admin can override it |
| `accent` | yes | `brand`, `amber`, `blue`, `cyan`, `fuchsia`, `gold`, `green`, `indigo`, `orange`, `red`, `rose`, `teal` or `violet` | Becomes `data-app-accent` while the module is active |
| `icon` | yes | icon name | Launcher and rail switch icon |
| `order` | yes | order | Position in the launcher and the registry; lower first |
| `client` | yes | `^apps/[a-z0-9-]+/client$` | The client package that draws the module; its own stylesheet is scoped from it ([web-shell.md](web-shell.md) section 5) |
| `api`, `rbac` | yes | sections 2.2 and 2.3 | Where the module's API is and how the shell reads the caller's permissions |
| `groups`, `pages`, `links`, `tiles` | yes | arrays, may be empty | Sections 2.4 to 2.7 |
| `landing` | no | each entry is a declared page route | Ordered routes to land on; the first one the caller can open wins |
| `whatsnew` | no | section 2.8 | Release notes source for the rail build card |
| `home` | no | section 2.9 | Quick actions and data feeds for Home |

### 2.2 `api`

| Field | Required | Rule | Meaning |
|---|---|---|---|
| `gateway` | yes | `^[a-z0-9][a-z0-9-]{0,63}$` | Gateway name; also names the API server that serves the module's release notes |
| `prefix` | yes | path | Joined to the base URL as `<base><prefix>` |
| `scopeEnv` | yes | `^[A-Z][A-Z0-9_]{1,31}$` | Names the build env pair `VITE_<SCOPEENV>_API_BASE_URL` and `VITE_<SCOPEENV>_API_SCOPE`. A name the build does not know means no probe client, so the module is not enterable |
| `estateKey` | no | key | Estate health app key when it differs from the gateway |

### 2.3 `rbac`

| Field | Required | Rule | Meaning |
|---|---|---|---|
| `shape` | yes | `console`, `hub` or `endpoint` | Which admin API shape the tool speaks. Display routing for the admin, never a gate |
| `base` | yes | path | Admin API base on the tool API |
| `me` | yes | path | The caller's own permission read. The shell calls it for the rail, the launcher probe and the Home gates |
| `permissionSource` | no | module id; only with `shape: console` | The module has no roles of its own and reads another module's permission answer. Display routing only: the source's server enforces ([web-api-runtime.md](web-api-runtime.md), [rbac.md](rbac.md)) |

### 2.4 `groups[]`

`key` (key, unique), `label` (printable ASCII), `order`. A group with no visible entry for the caller is dropped.

### 2.5 `pages[]`

| Field | Required | Rule | Meaning |
|---|---|---|---|
| `key` | yes | key, unique among pages and links | Item id; admin overrides and pins use it |
| `route` | yes | path, unique in the manifest | Path inside the module router: the URL is `/<id><route>` |
| `label`, `icon` | yes | printable ASCII, icon name | Rail label and icon |
| `hue` | yes | `brand`, `amber`, `blue`, `green`, `red`, `teal` or `violet` | Rail item tint |
| `requires` | yes | at least one id | Any-of. The entry shows and opens for a caller whose own permission read holds one id; `*` opens everything. It comes from code and an admin cannot change it |
| `group` | yes | a declared group | Rail section |
| `order` | yes | order | Position in the group |
| `keywords` | no | printable ASCII strings | Extra command palette terms |

A permission id is `tab:<id>`, `action:<tab>:<id>`, or a **peer id** `<module>/<id>` that another module's own
read answers. Peer ids are allowed in `requires` of pages and Home entries, never on a tile.

### 2.6 `links[]`

`key` (unique among pages and links), `label`, `href` (absolute `https:` URL, ASCII), `order`, optional `icon`
(read only when it is a valid icon name, else `ExternalLink`), and `slot`: `rail` (the default, needs `group`) or
`account` (the account menu, no group). A link has no `requires`: it always shows.

### 2.7 `tiles[]`

`key`, `dashboard` (the dashboard that shows it; `dashboard/key` is unique), `label`, `permission` (`tab:<id>` or
`action:<tab>:<id>`, no peer id), `order`. An admin can reorder or hide a tile, never change its `permission`.

### 2.8 `whatsnew`

`path` (a GET on the module's own API that serves release notes behind that tool's access check, no `//`) and
`changelog` (an `https:` URL). A release-notes script reads each manifest that has `whatsnew` plus the app's
`CHANGELOG.md` and writes the notes file the API serves; it fails when the manifest's `api.gateway` has no
server.

### 2.9 `home`

`actions[]` (at most 4): `key`, `label` (at most 40 characters), `icon`, `route` (a declared page route),
`requires`, `order`. `feeds[]` (at most 6): `key`, `block` (`waiting`, `live` or `fleet`), `label` (at most 60
characters), `path` (a path on the module's own API that answers `{ items }`, no `//`), `requires`, `order`, and
optional `linkModule` (the module the items route into; default the module's own id). Home gates drop peer ids
in `home`, and the validator still accepts them.

## 3. Defaults applied at read time

| Absent | Default |
|---|---|
| `description` | An automatic text: name and tagline, then page labels in rail order, cut to 400 characters |
| link `slot`, `icon` | `rail`, `ExternalLink` |
| page `keywords` | `[]` |
| `landing` | Page routes in rail order (groups by `order`, then pages by `order`, hidden entries skipped) |
| `home` | `{ actions: [], feeds: [] }`; `feeds[].linkModule` is the module's own `id` |
| `whatsnew` | `null` |
| base path (derived, not a key) | `/` for `console`, else `/<id>` |

## 4. A full example

```json
{
  "id": "fleet",
  "name": "Fleet",
  "tagline": "The device fleet and the connections behind it",
  "accent": "teal",
  "icon": "MonitorSmartphone",
  "order": 25,
  "client": "apps/shell/client",
  "api": { "gateway": "console", "prefix": "/api", "scopeEnv": "CONSOLE", "estateKey": "fleet" },
  "rbac": { "shape": "console", "base": "/admin", "me": "/me", "permissionSource": "console" },
  "groups": [{ "key": "devices", "label": "Devices", "order": 10 }],
  "pages": [
    { "key": "agent", "route": "/agent", "label": "Agent", "icon": "MonitorSmartphone", "hue": "blue",
      "requires": ["tab:agent", "alerts/action:admin:mailbox"], "group": "devices", "order": 10 }
  ],
  "links": [],
  "tiles": [],
  "landing": ["/agent"]
}
```

The fixtures under `tests/fixtures/console-module/` also cover `home`, `whatsnew`, `links`, `tiles` and an
unknown key.

## 5. What the schema cannot say

These rules need more than one field or more than one file, so JSON Schema leaves them to the shell's
validator. A host that has no such validator runs them as a `--validate-with` hook
([web-shell.md](web-shell.md) section 3).

| Rule | Level |
|---|---|
| `pages[].group` and `links[].group` name a declared group | manifest |
| Page `route`, group `key`, `dashboard/key` of a tile, and home action and feed keys are unique; item `key` is unique among pages and links | manifest |
| `home.actions[].route` and every `landing` entry is a declared page route | manifest |
| `client` equals `apps/<dir>/client` of the folder that holds the file; `id` equals the folder for `modules/<id>/` | file |
| The registry holds one of each `id` and holds the `console` module | registry |
| A `permissionSource` target exists, owns its permissions (no chains), and has the same `shape`, `base`, `me`, `api.gateway`, `api.prefix` and `api.scopeEnv` | registry |
| A peer id names a module that exists, owns its permissions, is not shape `console`, and is neither the module itself nor its permission source | registry |

## 6. Static manifest in code (documented exception)

A hub that predates the shell can declare its tools in code (a typed array, for example `TOOLS`) instead of one
JSON file per module. That is a different manifest shape, not a failure of this standard, and it is recorded as
an exception (`excepted`, with this reason) for the rules that name the JSON manifest. What a static manifest
of that kind carries, and where it lines up with the JSON shape:

| Static manifest field | JSON shape equivalent |
|---|---|
| `id`, `label`, `description`, `icon` | `id`, `name`, `description`, `icon` |
| `path`, `nav[].path`, `nav[].label`, `nav[].icon` | the module base path, `pages[].route`, `label`, `icon` |
| `viewPermission`, `viewAnyPermission[]`, `nav[].permission`, `nav[].permissions[]` | `pages[].requires` (any-of list) |
| `visibleTo(subject)` (a function) | none: the JSON shape holds data only, so a scoped visibility function stays in the host code |
| `status` (`active`, `beta`, `coming-soon`), `nav[].previewFlag` | none today: a host extension key such as `x-status` carries it, or it stays in code |
| `accessPrefixes[]`, `hiddenWithPermission`, `external`, `end`, `iconClass`, `hue` | partly: `links[]` covers `external`, `hue` is per page; the rest stay in code |

A host with a static manifest keeps it as it is. It still meets the rules that do not depend on the JSON
shape (one accent per module, registry staleness for whatever it generates, the permission rules in
[rbac.md](rbac.md)), and it records the exception with the owner's approval. Moving onto the JSON shape is a
choice the host makes later; the shape accepts unknown keys, so a host extension carries what the table marks
"none" without a change here. The table lists what is known from the hub's own statement; whether each field
survives a move is decided with the host when it moves, not assumed.

**Acceptance (test):** `tests/test_console_module_schema.py` validates the fixtures against the schema,
checks that unknown keys pass at every level, and checks 24 rejected mutations; `kit/tests/console-manifest.test.ts`
builds the same fixtures through the generator with the flags in section 1 and fails on a stale registry.
