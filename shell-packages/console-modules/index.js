// Shell module manifest validator, permission helpers and the layout merge (standards/web-shell-manifest.md).
// Pure ESM, no runtime dependencies, used by the shell client and server. validateManifest checks one
// manifest, validateRegistry the whole set (the checks a JSON schema cannot make: declared groups, unique
// routes, permission source and peer permission ids). Neither throws; both return a list of problem
// strings, empty when valid.
//
// Code is the discovery source: each module's manifest lists its rail entries (pages), groups, dashboard
// tiles and links with their default placement. The admin's saved layout only places, renames, hides or
// adds links. It can never change which permission a page requires: that always comes from code, and each
// module's own server enforces it regardless of what the rail shows. Display routing only.

export const ACCENTS = Object.freeze([
  "brand", "amber", "blue", "cyan", "fuchsia", "gold", "green", "indigo", "orange", "red", "rose", "teal", "violet",
]);
export const HUES = Object.freeze(["brand", "amber", "blue", "green", "red", "teal", "violet"]);
export const RBAC_SHAPES = Object.freeze(["console", "hub", "endpoint"]);
export const LINK_SLOTS = Object.freeze(["rail", "account"]);
/** The Home blocks a tool can feed: "waiting" (needs the caller), "live" (running now), "fleet". */
export const HOME_BLOCKS = Object.freeze(["waiting", "live", "fleet"]);
/** Bounds so one manifest cannot flood the front door. */
export const HOME_MAX_ACTIONS = 4;
export const HOME_MAX_FEEDS = 6;

const ID_RE = /^[a-z][a-z0-9-]{1,31}$/;
const KEY_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;
const ROUTE_RE = /^\/[a-z0-9\-/]*$/;
const PERM_RE = /^(tab:[a-z0-9-]+|action:[a-z0-9-]+:[a-z0-9-]+)$/;
// A peer permission: another module's own tab or action id, written "<module>/<id>". A page may
// list one next to its own source's ids, so it opens for the holders of any of them (any-of).
const PEER_RE = /^([a-z][a-z0-9-]{1,31})\/(tab:[a-z0-9-]+|action:[a-z0-9-]+:[a-z0-9-]+)$/;
const ICON_RE = /^[A-Z][A-Za-z0-9]{1,40}$/;
const PATH_RE = /^\/[a-z0-9\-/]*$/;
const SCOPE_ENV_RE = /^[A-Z][A-Z0-9_]{1,31}$/;

/** The longest tool description (manifest default or admin override), in characters. */
export const DESCRIPTION_MAX = 400;

/** @param {unknown} v @returns {v is string} */
const isStr = (v) => typeof v === "string" && v.length > 0;
/** @param {unknown} v @returns {v is number} */
const isOrder = (v) => typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= 100000;
/** @param {string} s */
const isAscii = (s) => /^[\x20-\x7e]*$/.test(s);
/**
 * A tool description: printable ASCII plain text (no markup brackets), 1..DESCRIPTION_MAX chars.
 * @param {unknown} v @returns {v is string}
 */
export const isDescription = (v) => isStr(v) && v.length <= DESCRIPTION_MAX && isAscii(v) && !/[<>]/.test(v) && v.trim() === v;
/** @param {unknown} v @returns {v is string} */
const isHttps = (v) => {
  if (!isStr(v) || !isAscii(v)) return false;
  try { return new URL(v).protocol === "https:"; } catch { return false; }
};

/**
 * Validate one manifest. Returns a list of problems (empty when valid). Never throws.
 * @param {unknown} input
 * @returns {string[]}
 */
export function validateManifest(input) {
  /** @type {string[]} */
  const errs = [];
  if (!input || typeof input !== "object" || Array.isArray(input)) return ["manifest must be an object"];
  const m = /** @type {Record<string, any>} */ (input);
  const where = isStr(m.id) ? m.id : "<no id>";
  const err = (/** @type {string} */ msg) => errs.push(`${where}: ${msg}`);

  if (!isStr(m.id) || !ID_RE.test(m.id)) err("id must match " + ID_RE);
  for (const f of ["name", "tagline"]) if (!isStr(m[f]) || !isAscii(m[f]) || m[f].length > 160) err(`${f} must be ASCII text up to 160 chars`);
  if (!ACCENTS.includes(m.accent)) err(`accent must be one of ${ACCENTS.join(", ")}`);
  if (m.description !== undefined && !isDescription(m.description)) err(`description must be plain ASCII text up to ${DESCRIPTION_MAX} chars`);
  if (!isStr(m.icon) || !ICON_RE.test(m.icon)) err("icon must be an icon name");
  if (!isOrder(m.order)) err("order must be a whole number 0..100000");
  if (!isStr(m.client) || !/^apps\/[a-z0-9-]+\/client$/.test(m.client)) err("client must be apps/<dir>/client");
  if (!m.api || !isStr(m.api.gateway) || !KEY_RE.test(m.api.gateway) || !isStr(m.api.prefix) || !PATH_RE.test(m.api.prefix)
      || !isStr(m.api.scopeEnv) || !SCOPE_ENV_RE.test(m.api.scopeEnv)) err("api needs gateway, prefix and scopeEnv");
  if (m.api && m.api.estateKey !== undefined && (!isStr(m.api.estateKey) || !KEY_RE.test(m.api.estateKey))) err("api.estateKey must be an estate app key");
  if (!m.rbac || !RBAC_SHAPES.includes(m.rbac.shape) || !isStr(m.rbac.base) || !PATH_RE.test(m.rbac.base)
      || !isStr(m.rbac.me) || !PATH_RE.test(m.rbac.me)) err("rbac needs shape, base and me");
  // A module may declare another module's permissions as its own (rbac.permissionSource names
  // that module). It then has no admin API or roles of its own: its pages keep the tab and action
  // ids of the source's registry, and the source's me answer decides who sees it.
  if (m.rbac && m.rbac.permissionSource !== undefined) {
    if (!isStr(m.rbac.permissionSource) || !ID_RE.test(m.rbac.permissionSource)) err("rbac.permissionSource must be a module id");
    else if (m.rbac.permissionSource === m.id) err("rbac.permissionSource cannot name the module itself");
    else if (m.rbac.shape !== "console") err("rbac.permissionSource is only for shape console");
  }

  const groups = Array.isArray(m.groups) ? m.groups : (err("groups must be a list"), []);
  const groupKeys = new Set();
  for (const g of groups) {
    if (!g || !isStr(g.key) || !KEY_RE.test(g.key)) { err("group key invalid"); continue; }
    if (groupKeys.has(g.key)) err(`duplicate group ${g.key}`);
    groupKeys.add(g.key);
    if (!isStr(g.label) || !isAscii(g.label)) err(`group ${g.key} label must be ASCII`);
    if (!isOrder(g.order)) err(`group ${g.key} order invalid`);
  }

  const itemKeys = new Set();
  const routes = new Set();
  const pages = Array.isArray(m.pages) ? m.pages : (err("pages must be a list"), []);
  for (const p of pages) {
    if (!p || !isStr(p.key) || !KEY_RE.test(p.key)) { err("page key invalid"); continue; }
    if (itemKeys.has(p.key)) err(`duplicate item ${p.key}`);
    itemKeys.add(p.key);
    if (!isStr(p.route) || !ROUTE_RE.test(p.route)) err(`page ${p.key} route invalid`);
    else if (routes.has(p.route)) err(`duplicate route ${p.route}`);
    else routes.add(p.route);
    if (!isStr(p.label) || !isAscii(p.label)) err(`page ${p.key} label must be ASCII`);
    if (!isStr(p.icon) || !ICON_RE.test(p.icon)) err(`page ${p.key} icon invalid`);
    if (!HUES.includes(p.hue)) err(`page ${p.key} hue must be one of ${HUES.join(", ")}`);
    if (!Array.isArray(p.requires) || p.requires.length === 0 || !p.requires.every((/** @type {unknown} */ r) => isStr(r) && (PERM_RE.test(r) || PEER_RE.test(r)))) {
      err(`page ${p.key} requires must list at least one tab or action id`);
    }
    if (!groupKeys.has(p.group)) err(`page ${p.key} group ${p.group} is not declared`);
    if (!isOrder(p.order)) err(`page ${p.key} order invalid`);
    if (p.keywords !== undefined && (!Array.isArray(p.keywords) || !p.keywords.every((/** @type {unknown} */ k) => isStr(k) && isAscii(k)))) err(`page ${p.key} keywords invalid`);
  }

  const links = Array.isArray(m.links) ? m.links : (err("links must be a list"), []);
  for (const l of links) {
    if (!l || !isStr(l.key) || !KEY_RE.test(l.key)) { err("link key invalid"); continue; }
    if (itemKeys.has(l.key)) err(`duplicate item ${l.key}`);
    itemKeys.add(l.key);
    if (!isStr(l.label) || !isAscii(l.label)) err(`link ${l.key} label must be ASCII`);
    if (!isHttps(l.href)) err(`link ${l.key} href must be https`);
    const slot = l.slot || "rail";
    if (!LINK_SLOTS.includes(slot)) err(`link ${l.key} slot invalid`);
    if (slot === "rail" && !groupKeys.has(l.group)) err(`link ${l.key} group ${l.group} is not declared`);
    if (!isOrder(l.order)) err(`link ${l.key} order invalid`);
  }

  const tiles = Array.isArray(m.tiles) ? m.tiles : (err("tiles must be a list"), []);
  const tileKeys = new Set();
  for (const t of tiles) {
    if (!t || !isStr(t.key) || !KEY_RE.test(t.key) || !isStr(t.dashboard) || !KEY_RE.test(t.dashboard)) { err("tile key or dashboard invalid"); continue; }
    const k = `${t.dashboard}/${t.key}`;
    if (tileKeys.has(k)) err(`duplicate tile ${k}`);
    tileKeys.add(k);
    if (!isStr(t.label) || !isAscii(t.label)) err(`tile ${k} label must be ASCII`);
    if (!isStr(t.permission) || !PERM_RE.test(t.permission)) err(`tile ${k} permission invalid`);
    if (!isOrder(t.order)) err(`tile ${k} order invalid`);
  }

  // What's new (ITEA-5784): the path on the module's own API that serves its release notes behind the
  // tool's own access check, and the https Changelog page with the full detail.
  if (m.whatsnew !== undefined) {
    const w = m.whatsnew;
    if (!w || typeof w !== "object" || Array.isArray(w)) err("whatsnew must be an object");
    else {
      if (!isStr(w.path) || !PATH_RE.test(w.path) || w.path.includes("//")) err("whatsnew path must be a plain API path");
      if (!isHttps(w.changelog)) err("whatsnew changelog must be an https link");
    }
  }

  // Home contributions (ITEA-5784 W16): quick actions and data feeds the console Home shows to
  // holders of the declared permission. Data only: a feed is a path on the module's own API that
  // answers { items }, an action is a page route the module already declares.
  if (m.home !== undefined) {
    const h = m.home;
    if (!h || typeof h !== "object" || Array.isArray(h)) err("home must be an object");
    else {
      const actions = Array.isArray(h.actions) ? h.actions : h.actions === undefined ? [] : (err("home.actions must be a list"), []);
      const feeds = Array.isArray(h.feeds) ? h.feeds : h.feeds === undefined ? [] : (err("home.feeds must be a list"), []);
      if (actions.length > HOME_MAX_ACTIONS) err(`home.actions holds at most ${HOME_MAX_ACTIONS}`);
      if (feeds.length > HOME_MAX_FEEDS) err(`home.feeds holds at most ${HOME_MAX_FEEDS}`);
      const permsOk = (/** @type {unknown} */ r) => Array.isArray(r) && r.length > 0 && r.every((x) => isStr(x) && (PERM_RE.test(x) || PEER_RE.test(x)));
      const seenA = new Set();
      for (const a of actions) {
        if (!a || !isStr(a.key) || !KEY_RE.test(a.key)) { err("home action key invalid"); continue; }
        if (seenA.has(a.key)) err(`duplicate home action ${a.key}`);
        seenA.add(a.key);
        if (!isStr(a.label) || !isAscii(a.label) || a.label.length > 40) err(`home action ${a.key} label must be ASCII up to 40 chars`);
        if (!isStr(a.icon) || !ICON_RE.test(a.icon)) err(`home action ${a.key} icon invalid`);
        if (!isStr(a.route) || !routes.has(a.route)) err(`home action ${a.key} route must be a declared page route`);
        if (!permsOk(a.requires)) err(`home action ${a.key} requires must list at least one tab or action id`);
        if (!isOrder(a.order)) err(`home action ${a.key} order invalid`);
      }
      const seenF = new Set();
      for (const f of feeds) {
        if (!f || !isStr(f.key) || !KEY_RE.test(f.key)) { err("home feed key invalid"); continue; }
        if (seenF.has(f.key)) err(`duplicate home feed ${f.key}`);
        seenF.add(f.key);
        if (!HOME_BLOCKS.includes(f.block)) err(`home feed ${f.key} block must be one of ${HOME_BLOCKS.join(", ")}`);
        if (!isStr(f.label) || !isAscii(f.label) || f.label.length > 60) err(`home feed ${f.key} label must be ASCII up to 60 chars`);
        if (!isStr(f.path) || !PATH_RE.test(f.path) || f.path.includes("//")) err(`home feed ${f.key} path must be a plain API path`);
        if (!permsOk(f.requires)) err(`home feed ${f.key} requires must list at least one tab or action id`);
        if (!isOrder(f.order)) err(`home feed ${f.key} order invalid`);
        // The module the item routes open in (the fleet numbers live in Endpoint Platform, the feed in Talos).
        if (f.linkModule !== undefined && (!isStr(f.linkModule) || !ID_RE.test(f.linkModule))) err(`home feed ${f.key} linkModule invalid`);
      }
    }
  }

  if (m.landing !== undefined) {
    if (!Array.isArray(m.landing) || !m.landing.every((/** @type {unknown} */ r) => isStr(r) && routes.has(r))) err("landing must list declared page routes");
  }
  return errs;
}

/**
 * Validate a whole registry (a list of manifests): every manifest valid, ids unique, client unique.
 * @param {unknown[]} manifests
 * @returns {string[]}
 */
export function validateRegistry(manifests) {
  /** @type {string[]} */
  const errs = [];
  const ids = new Set();
  for (const m of manifests) {
    errs.push(...validateManifest(m));
    const id = /** @type {any} */ (m)?.id;
    if (ids.has(id)) errs.push(`duplicate module id ${id}`);
    ids.add(id);
  }
  if (!ids.has("console")) errs.push("registry must contain the console module");
  const byId = new Map(manifests.map((m) => [/** @type {any} */ (m)?.id, /** @type {any} */ (m)]));
  for (const m of byId.values()) {
    const src = m?.rbac?.permissionSource;
    if (!isStr(src) || src === m.id) continue;
    const target = byId.get(src);
    if (!target) { errs.push(`${m.id}: rbac.permissionSource ${src} is not a module in the registry`); continue; }
    if (target.rbac?.permissionSource !== undefined) errs.push(`${m.id}: rbac.permissionSource ${src} must own its permissions`);
    for (const k of ["shape", "base", "me"]) if (target.rbac?.[k] !== m.rbac?.[k]) errs.push(`${m.id}: rbac.${k} must match ${src}`);
    for (const k of ["gateway", "prefix", "scopeEnv"]) if (target.api?.[k] !== m.api?.[k]) errs.push(`${m.id}: api.${k} must match ${src}`);
  }
  // A peer permission names another module that owns its permissions and answers its own me read.
  for (const m of byId.values()) {
    for (const peer of peerModules(m)) {
      const target = byId.get(peer);
      if (peer === m.id || peer === m?.rbac?.permissionSource) errs.push(`${m.id}: a peer permission cannot name ${peer}, use its plain id`);
      else if (!target) errs.push(`${m.id}: peer permission module ${peer} is not a module in the registry`);
      else if (target.rbac?.permissionSource !== undefined) errs.push(`${m.id}: peer permission module ${peer} must own its permissions`);
      else if (target.rbac?.shape === "console") errs.push(`${m.id}: peer permission module ${peer} must be a tool with its own me read`);
    }
  }
  return errs;
}

/**
 * Split a peer permission ("talos/action:admin:integration-itsm") into the module that owns it and
 * its id. Null for an ordinary id of the module's own permission source.
 * @param {string} id
 * @returns {{ module: string, permission: string } | null}
 */
export function peerRef(id) {
  const m = typeof id === "string" ? PEER_RE.exec(id) : null;
  return m ? { module: /** @type {string} */ (m[1]), permission: /** @type {string} */ (m[2]) } : null;
}

/**
 * The modules whose me answers a module's pages also read: every peer named in a page's
 * `requires`, sorted, once each.
 * @param {{ pages?: ReadonlyArray<{ requires: readonly string[] }>, groups?: ReadonlyArray<{ items: ReadonlyArray<{ requires: readonly string[] }> }> }} mod a manifest (pages) or an effective module (groups)
 * @returns {string[]}
 */
export function peerModules(mod) {
  const lists = [
    ...(Array.isArray(mod.pages) ? mod.pages : []).map((p) => (Array.isArray(p?.requires) ? p.requires : [])),
    ...(mod.groups || []).flatMap((g) => (g.items || []).map((i) => i.requires)),
  ];
  return [...new Set(lists.flat().map((r) => peerRef(r)?.module).filter((x) => typeof x === "string"))].sort();
}

/**
 * Does a permission set open an entry that requires any of `requires`? `*` opens everything.
 * The tool's own server already expanded its permissions, this only mirrors its answer.
 * @param {readonly string[]} requires
 * @param {(id: string) => boolean} has
 */
export function canOpen(requires, has) {
  return requires.some((r) => has(r));
}

/**
 * The id of the module whose permissions decide this module's pages: its permissionSource when it
 * declares one, else itself. Display and admin routing only, the source's server enforces.
 * @param {{ id: string, rbac?: { permissionSource?: string } }} mod
 * @returns {string}
 */
export function permissionSourceId(mod) {
  return (mod.rbac && mod.rbac.permissionSource) || mod.id;
}

/**
 * Does this module own its permissions (its own roles and admin API)? False for a module that
 * declares another module as its permission source.
 * @param {{ id: string, rbac?: { permissionSource?: string } }} mod
 */
export function ownsPermissions(mod) {
  return permissionSourceId(mod) === mod.id;
}

/**
 * @typedef {{ module_id: string, enabled?: boolean, tagline?: string | null, description?: string | null, order?: number | null, updated_at?: string }} ModuleOverride
 * @typedef {{ module_id: string, group_key: string, label?: string | null, order?: number | null, hidden?: boolean, custom?: boolean, updated_at?: string }} GroupOverride
 * @typedef {{ module_id: string, item_key: string, kind?: "page" | "link", group_key?: string | null, order?: number | null, label?: string | null, icon?: string | null, hidden?: boolean, href?: string | null, slot?: string | null, permission?: string | null, custom?: boolean, updated_at?: string }} ItemOverride
 * @typedef {{ module_id: string, dashboard: string, tile_key: string, order?: number | null, hidden?: boolean, updated_at?: string }} TileOverride
 * @typedef {{ modules?: ModuleOverride[], groups?: GroupOverride[], items?: ItemOverride[], tiles?: TileOverride[] }} Overrides
 */

/** @param {unknown} v @param {number} d */
const ord = (v, d) => (isOrder(v) ? v : d);
/** @param {unknown} v @param {string} d */
const txt = (v, d) => (isStr(v) && isAscii(v) ? v : d);
/** @param {Record<string, any>} a @param {Record<string, any>} b */
const byOrder = (a, b) => a.order - b.order || String(a.key).localeCompare(String(b.key));

/**
 * The description a tool shows when neither its manifest nor the admin set one: its name and
 * tagline, then its page labels in rail order (group order, then page order), cut to fit
 * DESCRIPTION_MAX with a count of the rest. Pure and deterministic.
 * @param {Record<string, any>} m a module manifest
 * @returns {string}
 */
export function autoDescription(m) {
  const groupOrder = new Map((m.groups || []).map((/** @type {any} */ g) => [g.key, g.order]));
  const labels = [];
  const seen = new Set();
  const pages = [...(m.pages || [])].sort((a, b) => (groupOrder.get(a.group) ?? 0) - (groupOrder.get(b.group) ?? 0) || a.order - b.order);
  for (const p of pages) {
    if (!isStr(p.label) || !isAscii(p.label) || seen.has(p.label)) continue;
    seen.add(p.label);
    labels.push(p.label.replace(/[<>]/g, ""));
  }
  const name = isStr(m.name) && isAscii(m.name) ? m.name.replace(/[<>]/g, "") : "This tool";
  const tagline = isStr(m.tagline) && isAscii(m.tagline) ? m.tagline.replace(/[<>]/g, "").replace(/[.\s]+$/, "") : "";
  const head = tagline ? `${name}: ${tagline}.` : `${name}.`;
  if (!labels.length) return head.slice(0, DESCRIPTION_MAX).trim();
  /** @param {string[]} list @param {number} rest */
  const sentence = (list, rest) => {
    const named = rest > 0 ? [...list, `${rest} more`] : list;
    const joined = named.length > 1 ? `${named.slice(0, -1).join(", ")} and ${named[named.length - 1]}` : named[0];
    return `${head} Pages: ${joined}.`;
  };
  for (let n = labels.length; n >= 1; n--) {
    const s = sentence(labels.slice(0, n), labels.length - n);
    if (s.length <= DESCRIPTION_MAX) return s;
  }
  return head.slice(0, DESCRIPTION_MAX).trim();
}

/**
 * The one merge rule. Code manifests plus admin overrides -> the effective console layout.
 *  - a code entry with no override renders at its code default and is flagged isNew (admin only cue)
 *  - an override whose code entry is gone is reported in `orphaned` and never rendered
 *  - a page's `requires` always comes from code, an override cannot change it
 *  - custom links (custom: true) render only with a valid https href, and their optional permission
 *    must be in that module's registry ids when `registryIds` is given (else they are dropped)
 *  - a hidden group hides its entries, an entry moved to a missing group falls back to its code group
 *  - a module's description is the admin's text, else the manifest's, else autoDescription()
 * Pure, deterministic, never throws on bad override rows (they are skipped and reported).
 *
 * @param {Array<Record<string, any>>} manifests
 * @param {Overrides} [overrides]
 * @param {{ registryIds?: Record<string, ReadonlySet<string>> }} [opts]
 */
export function effectiveLayout(manifests, overrides = {}, opts = {}) {
  const mods = new Map((overrides.modules || []).map((o) => [o.module_id, o]));
  /** @type {Array<{ kind: string, module_id: string, key: string, reason: string }>} */
  const orphaned = [];
  /** @type {Array<Record<string, any>>} */
  const modules = [];
  const known = new Set(manifests.map((m) => m.id));
  for (const o of overrides.modules || []) if (!known.has(o.module_id)) orphaned.push({ kind: "module", module_id: o.module_id, key: o.module_id, reason: "module not in code" });

  for (const m of manifests) {
    const mo = mods.get(m.id);
    const gOv = new Map((overrides.groups || []).filter((g) => g.module_id === m.id).map((g) => [g.group_key, g]));
    const iOv = new Map((overrides.items || []).filter((i) => i.module_id === m.id).map((i) => [i.item_key, i]));
    const tOv = new Map((overrides.tiles || []).filter((t) => t.module_id === m.id).map((t) => [`${t.dashboard}/${t.tile_key}`, t]));
    const regIds = opts.registryIds ? opts.registryIds[m.id] : undefined;

    /** @type {Map<string, Record<string, any>>} */
    const groups = new Map();
    for (const g of m.groups) {
      const o = gOv.get(g.key);
      groups.set(g.key, { key: g.key, label: txt(o?.label, g.label), order: ord(o?.order, g.order), hidden: Boolean(o?.hidden), custom: false, isNew: !o, items: [] });
    }
    for (const o of gOv.values()) {
      if (groups.has(o.group_key)) continue;
      if (o.custom && KEY_RE.test(o.group_key)) groups.set(o.group_key, { key: o.group_key, label: txt(o.label, o.group_key), order: ord(o.order, 1000), hidden: Boolean(o.hidden), custom: true, isNew: false, items: [] });
      else orphaned.push({ kind: "group", module_id: m.id, key: o.group_key, reason: "group not in code" });
    }

    /** @type {Array<Record<string, any>>} */
    const account = [];
    /** @param {string | null | undefined} want @param {string} codeGroup */
    const placeIn = (want, codeGroup) => (want && groups.has(want) ? want : codeGroup);

    for (const p of m.pages) {
      const o = iOv.get(p.key);
      const gk = placeIn(o?.group_key, p.group);
      const g = groups.get(gk);
      if (!g) continue;
      g.items.push({
        kind: "page", key: p.key, route: p.route, requires: [...p.requires],
        label: txt(o?.label, p.label), icon: isStr(o?.icon) && ICON_RE.test(o.icon) ? o.icon : p.icon, hue: p.hue,
        keywords: p.keywords ? [...p.keywords] : [], order: ord(o?.order, p.order), hidden: Boolean(o?.hidden),
        isNew: !o, custom: false, codeGroup: p.group,
      });
    }
    for (const l of m.links || []) {
      const o = iOv.get(l.key);
      const slot = LINK_SLOTS.includes(/** @type {string} */ (o?.slot)) ? o?.slot : (l.slot || "rail");
      const entry = { kind: "link", key: l.key, href: l.href, requires: [], label: txt(o?.label, l.label), icon: isStr(o?.icon) && ICON_RE.test(o.icon) ? o.icon : (l.icon || "ExternalLink"), hue: "brand", keywords: [], order: ord(o?.order, l.order), hidden: Boolean(o?.hidden), isNew: !o, custom: false, slot };
      if (slot === "account") account.push(entry);
      else { const g = groups.get(placeIn(o?.group_key, l.group)); if (g) g.items.push(entry); }
    }
    const codeItems = new Set([...m.pages.map((/** @type {any} */ p) => p.key), ...(m.links || []).map((/** @type {any} */ l) => l.key)]);
    for (const o of iOv.values()) {
      if (codeItems.has(o.item_key)) continue;
      if (!o.custom || o.kind !== "link" || !KEY_RE.test(o.item_key) || !isHttps(o.href)) {
        orphaned.push({ kind: "item", module_id: m.id, key: o.item_key, reason: o.custom ? "custom link invalid" : "item not in code" });
        continue;
      }
      const permission = isStr(o.permission) ? o.permission : null;
      if (permission && (!PERM_RE.test(permission) || (regIds && !regIds.has(permission)))) {
        orphaned.push({ kind: "item", module_id: m.id, key: o.item_key, reason: "custom link permission not in registry" });
        continue;
      }
      const slot = o.slot === "account" ? "account" : "rail";
      const entry = { kind: "link", key: o.item_key, href: o.href, requires: permission ? [permission] : [], label: txt(o.label, o.item_key), icon: isStr(o.icon) && ICON_RE.test(o.icon) ? o.icon : "ExternalLink", hue: "brand", keywords: [], order: ord(o.order, 1000), hidden: Boolean(o.hidden), isNew: false, custom: true, slot };
      if (slot === "account") account.push(entry);
      else {
        const g = groups.get(o.group_key || "") || [...groups.values()].sort(byOrder)[groups.size - 1];
        if (g) g.items.push(entry);
      }
    }

    /** @type {Array<Record<string, any>>} */
    const tiles = [];
    for (const t of m.tiles || []) {
      const o = tOv.get(`${t.dashboard}/${t.key}`);
      tiles.push({ key: t.key, dashboard: t.dashboard, label: t.label, permission: t.permission, order: ord(o?.order, t.order), hidden: Boolean(o?.hidden), isNew: !o });
    }
    const codeTiles = new Set((m.tiles || []).map((/** @type {any} */ t) => `${t.dashboard}/${t.key}`));
    for (const [k] of tOv) if (!codeTiles.has(k)) orphaned.push({ kind: "tile", module_id: m.id, key: k, reason: "tile not in code" });

    /** @type {Array<Record<string, any>>} */
    const groupList = [...groups.values()].sort(byOrder).map((g) => ({ ...g, items: g.items.sort(byOrder) }));
    const routeOrder = groupList.flatMap((g) => (g.hidden ? [] : g.items.filter((/** @type {any} */ i) => i.kind === "page" && !i.hidden).map((/** @type {any} */ i) => i.route)));
    const descriptionDefault = isDescription(m.description) ? m.description : autoDescription(m);
    const adminDescription = isDescription(mo?.description) ? mo.description : null;
    modules.push({
      id: m.id, name: m.name, tagline: txt(mo?.tagline, m.tagline),
      description: adminDescription ?? descriptionDefault, descriptionDefault,
      descriptionSource: adminDescription ? "admin" : isDescription(m.description) ? "manifest" : "auto",
      accent: m.accent, icon: m.icon,
      order: ord(mo?.order, m.order), enabled: mo?.enabled === undefined ? true : Boolean(mo.enabled), isNew: !mo,
      basePath: m.id === "console" ? "/" : `/${m.id}`, api: { ...m.api }, rbac: { ...m.rbac },
      groups: groupList, account: account.sort(byOrder),
      tiles: tiles.sort((a, b) => (a.dashboard === b.dashboard ? byOrder(a, b) : a.dashboard.localeCompare(b.dashboard))),
      // Landing: the code's own landing chain when it declares one (parity with today), else rail order.
      landing: Array.isArray(m.landing) ? [...m.landing] : routeOrder,
      whatsnew: m.whatsnew ? { path: m.whatsnew.path, changelog: m.whatsnew.changelog } : null,
      // Home contributions come from code only: the admin hides whole Home blocks (tiles), never edits a feed.
      home: {
        actions: (m.home?.actions || []).map((/** @type {any} */ a) => ({ ...a, requires: [...a.requires] })),
        feeds: (m.home?.feeds || []).map((/** @type {any} */ f) => ({ ...f, linkModule: f.linkModule || m.id, requires: [...f.requires] })),
      },
    });
  }
  modules.sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
  return { modules, orphaned };
}

/**
 * What one caller sees of a module: hidden entries and groups dropped, entries the caller cannot
 * open dropped, empty groups dropped. `has` is that tool's own permission check (createAccess).
 * Display only. The tool's server enforces every page and action whatever this returns.
 * @param {Record<string, any>} mod a module from effectiveLayout
 * @param {(id: string) => boolean} has
 */
export function visibleNav(mod, has) {
  const groups = [];
  for (const g of mod.groups) {
    if (g.hidden) continue;
    const items = g.items.filter((/** @type {any} */ i) => !i.hidden && (i.requires.length === 0 || canOpen(i.requires, has)));
    if (items.length) groups.push({ key: g.key, label: g.label, items });
  }
  const account = mod.account.filter((/** @type {any} */ i) => !i.hidden && (i.requires.length === 0 || canOpen(i.requires, has)));
  return { groups, account };
}

/**
 * The route a caller lands on: the first landing route whose page they can open, else null.
 * Hidden entries are still valid landings when the caller can open them, so hiding a rail entry
 * never strands someone whose only page it is.
 * @param {Record<string, any>} mod
 * @param {(id: string) => boolean} has
 * @returns {string | null}
 */
export function landingRoute(mod, has) {
  const pages = new Map(mod.groups.flatMap((/** @type {any} */ g) => g.items).filter((/** @type {any} */ i) => i.kind === "page").map((/** @type {any} */ i) => [i.route, i]));
  for (const r of mod.landing) {
    const p = pages.get(r);
    if (p && canOpen(p.requires, has)) return r;
  }
  for (const p of pages.values()) if (canOpen(p.requires, has)) return p.route;
  return null;
}

/**
 * The tiles a caller sees on a dashboard, in admin order: hidden tiles and tiles without the
 * caller's permission dropped.
 * @param {Record<string, any>} mod
 * @param {string} dashboard
 * @param {(id: string) => boolean} has
 */
export function visibleTiles(mod, dashboard, has) {
  return mod.tiles.filter((/** @type {any} */ t) => t.dashboard === dashboard && !t.hidden && has(t.permission));
}

/**
 * The Home contributions a caller sees: only the actions and feeds whose permission the caller holds
 * in that module's own permission answer, in module then declared order, disabled modules dropped.
 * `hasFor(mod)` returns that module's has(id), or null when its answer is not (yet) known: a module
 * with no answer contributes nothing (fail closed). Display only, the tool's server gates each feed.
 * @param {ReadonlyArray<Record<string, any>>} modules effective modules
 * @param {(mod: Record<string, any>) => ((id: string) => boolean) | null} hasFor
 * @returns {{ actions: Array<Record<string, any>>, feeds: Array<Record<string, any>> }}
 */
export function homeContributions(modules, hasFor) {
  /** @type {Array<Record<string, any>>} */
  const actions = [];
  /** @type {Array<Record<string, any>>} */
  const feeds = [];
  for (const mod of modules) {
    if (mod.enabled === false || !mod.home) continue;
    const base = hasFor(mod);
    if (!base) continue;
    const has = (/** @type {string} */ id) => {
      const ref = peerRef(id);
      return ref ? false : base(id);
    };
    for (const a of [...mod.home.actions].sort((x, y) => x.order - y.order)) {
      if (canOpen(a.requires, has)) actions.push({ ...a, moduleId: mod.id, moduleName: mod.name, accent: mod.accent });
    }
    for (const f of [...mod.home.feeds].sort((x, y) => x.order - y.order)) {
      if (canOpen(f.requires, has)) feeds.push({ ...f, moduleId: mod.id, moduleName: mod.name });
    }
  }
  return { actions, feeds };
}

/** The module a pathname belongs to: the first segment when it names a module, else console. */
/** @param {string} pathname @param {readonly string[]} moduleIds */
export function moduleForPath(pathname, moduleIds) {
  const seg = (pathname || "/").split("/")[1] || "";
  return seg && seg !== "console" && moduleIds.includes(seg) ? seg : "console";
}
