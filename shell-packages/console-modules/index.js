// Shell module manifest validator and permission helpers (standards/web-shell-manifest.md).
// Pure ESM, no runtime dependencies. validateManifest checks one manifest, validateRegistry the whole
// set (the checks a JSON schema cannot make: declared groups, unique routes, permission source and peer
// permission ids). Neither throws; both return a list of problem strings, empty when valid.
// Display routing only: a module's own server enforces every page and action.

export const ACCENTS = Object.freeze([
  "brand", "amber", "blue", "cyan", "fuchsia", "gold", "green", "indigo", "orange", "red", "rose", "teal", "violet",
]);
export const HUES = Object.freeze(["brand", "amber", "blue", "green", "red", "teal", "violet"]);
export const RBAC_SHAPES = Object.freeze(["console", "hub", "endpoint"]);
export const LINK_SLOTS = Object.freeze(["rail", "account"]);
export const HOME_BLOCKS = Object.freeze(["waiting", "live", "fleet"]);
export const HOME_MAX_ACTIONS = 4;
export const HOME_MAX_FEEDS = 6;
export const DESCRIPTION_MAX = 400;

const ID = /^[a-z][a-z0-9-]{1,31}$/;
const KEY = /^[a-z0-9][a-z0-9-]{0,63}$/;
const PATH = /^\/[a-z0-9\-/]*$/;
const OWN_PERM = /^(?:tab:[a-z0-9-]+|action:[a-z0-9-]+:[a-z0-9-]+)$/;
const PEER_PERM = /^([a-z][a-z0-9-]{1,31})\/((?:tab:[a-z0-9-]+|action:[a-z0-9-]+:[a-z0-9-]+))$/;
const ICON = /^[A-Z][A-Za-z0-9]{1,40}$/;
const SCOPE_ENV = /^[A-Z][A-Z0-9_]{1,31}$/;
const CLIENT = /^apps\/[a-z0-9-]+\/client$/;

const str = (v) => typeof v === "string" && v.length > 0;
const ascii = (v) => str(v) && /^[\x20-\x7e]+$/.test(v);
const order = (v) => Number.isInteger(v) && v >= 0 && v <= 100000;
const list = (v) => (Array.isArray(v) ? v : null);
const rec = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
const https = (v) => {
  if (!ascii(v)) return false;
  try {
    return new URL(v).protocol === "https:";
  } catch {
    return false;
  }
};
const perms = (v) => Array.isArray(v) && v.length > 0 && v.every((r) => str(r) && (OWN_PERM.test(r) || PEER_PERM.test(r)));

/** A tool description: printable ASCII, 1 to 400 characters, no angle brackets, no padding. */
export const isDescription = (v) => ascii(v) && v.length <= DESCRIPTION_MAX && !/[<>]/.test(v) && v.trim() === v;

/** Validate one manifest. @param {unknown} input @returns {string[]} */
export function validateManifest(input) {
  if (!rec(input)) return ["manifest must be an object"];
  const m = input;
  const errs = [];
  const err = (msg) => errs.push(`${str(m.id) ? m.id : "<no id>"}: ${msg}`);
  const bad = (cond, msg) => cond && err(msg);

  bad(!str(m.id) || !ID.test(m.id), `id must match ${ID}`);
  for (const f of ["name", "tagline"]) bad(!ascii(m[f]) || m[f].length > 160, `${f} must be ASCII text up to 160 characters`);
  bad(!ACCENTS.includes(m.accent), `accent must be one of ${ACCENTS.join(", ")}`);
  bad(m.description !== undefined && !isDescription(m.description), `description must be plain ASCII text up to ${DESCRIPTION_MAX} characters`);
  bad(!str(m.icon) || !ICON.test(m.icon), "icon must be an icon name");
  bad(!order(m.order), "order must be a whole number 0 to 100000");
  bad(!str(m.client) || !CLIENT.test(m.client), "client must be apps/<dir>/client");

  const api = rec(m.api) ? m.api : {};
  bad(!str(api.gateway) || !KEY.test(api.gateway) || !str(api.prefix) || !PATH.test(api.prefix) || !str(api.scopeEnv) || !SCOPE_ENV.test(api.scopeEnv),
    "api needs gateway, prefix and scopeEnv");
  bad(api.estateKey !== undefined && (!str(api.estateKey) || !KEY.test(api.estateKey)), "api.estateKey must be a key");

  const rbac = rec(m.rbac) ? m.rbac : {};
  bad(!RBAC_SHAPES.includes(rbac.shape) || !str(rbac.base) || !PATH.test(rbac.base) || !str(rbac.me) || !PATH.test(rbac.me), "rbac needs shape, base and me");
  if (rbac.permissionSource !== undefined) {
    if (!str(rbac.permissionSource) || !ID.test(rbac.permissionSource)) err("rbac.permissionSource must be a module id");
    else if (rbac.permissionSource === m.id) err("rbac.permissionSource cannot name the module itself");
    else if (rbac.shape !== "console") err("rbac.permissionSource is only for shape console");
  }

  const groups = list(m.groups) ?? (err("groups must be a list"), []);
  const groupKeys = new Set();
  for (const g of groups) {
    if (!rec(g) || !str(g.key) || !KEY.test(g.key)) { err("group key invalid"); continue; }
    bad(groupKeys.has(g.key), `duplicate group ${g.key}`);
    groupKeys.add(g.key);
    bad(!ascii(g.label), `group ${g.key} label must be ASCII`);
    bad(!order(g.order), `group ${g.key} order invalid`);
  }

  const itemKeys = new Set();
  const routes = new Set();
  for (const p of list(m.pages) ?? (err("pages must be a list"), [])) {
    if (!rec(p) || !str(p.key) || !KEY.test(p.key)) { err("page key invalid"); continue; }
    bad(itemKeys.has(p.key), `duplicate item ${p.key}`);
    itemKeys.add(p.key);
    if (!str(p.route) || !PATH.test(p.route)) err(`page ${p.key} route invalid`);
    else if (routes.has(p.route)) err(`duplicate route ${p.route}`);
    else routes.add(p.route);
    bad(!ascii(p.label), `page ${p.key} label must be ASCII`);
    bad(!str(p.icon) || !ICON.test(p.icon), `page ${p.key} icon invalid`);
    bad(!HUES.includes(p.hue), `page ${p.key} hue must be one of ${HUES.join(", ")}`);
    bad(!perms(p.requires), `page ${p.key} requires must list at least one tab or action id`);
    bad(!groupKeys.has(p.group), `page ${p.key} group ${p.group} is not declared`);
    bad(!order(p.order), `page ${p.key} order invalid`);
    bad(p.keywords !== undefined && !(Array.isArray(p.keywords) && p.keywords.every(ascii)), `page ${p.key} keywords invalid`);
  }

  for (const l of list(m.links) ?? (err("links must be a list"), [])) {
    if (!rec(l) || !str(l.key) || !KEY.test(l.key)) { err("link key invalid"); continue; }
    bad(itemKeys.has(l.key), `duplicate item ${l.key}`);
    itemKeys.add(l.key);
    bad(!ascii(l.label), `link ${l.key} label must be ASCII`);
    bad(!https(l.href), `link ${l.key} href must be https`);
    const slot = l.slot ?? "rail";
    bad(!LINK_SLOTS.includes(slot), `link ${l.key} slot invalid`);
    bad(slot === "rail" && !groupKeys.has(l.group), `link ${l.key} group ${l.group} is not declared`);
    bad(!order(l.order), `link ${l.key} order invalid`);
  }

  const tileKeys = new Set();
  for (const t of list(m.tiles) ?? (err("tiles must be a list"), [])) {
    if (!rec(t) || !str(t.key) || !KEY.test(t.key) || !str(t.dashboard) || !KEY.test(t.dashboard)) { err("tile key or dashboard invalid"); continue; }
    const k = `${t.dashboard}/${t.key}`;
    bad(tileKeys.has(k), `duplicate tile ${k}`);
    tileKeys.add(k);
    bad(!ascii(t.label), `tile ${k} label must be ASCII`);
    bad(!str(t.permission) || !OWN_PERM.test(t.permission), `tile ${k} permission invalid`);
    bad(!order(t.order), `tile ${k} order invalid`);
  }

  if (m.whatsnew !== undefined) {
    const w = m.whatsnew;
    if (!rec(w)) err("whatsnew must be an object");
    else {
      bad(!str(w.path) || !PATH.test(w.path) || w.path.includes("//"), "whatsnew path must be a plain API path");
      bad(!https(w.changelog), "whatsnew changelog must be an https link");
    }
  }

  if (m.home !== undefined) {
    const h = m.home;
    if (!rec(h)) err("home must be an object");
    else {
      const actions = h.actions === undefined ? [] : list(h.actions) ?? (err("home.actions must be a list"), []);
      const feeds = h.feeds === undefined ? [] : list(h.feeds) ?? (err("home.feeds must be a list"), []);
      bad(actions.length > HOME_MAX_ACTIONS, `home.actions holds at most ${HOME_MAX_ACTIONS}`);
      bad(feeds.length > HOME_MAX_FEEDS, `home.feeds holds at most ${HOME_MAX_FEEDS}`);
      const seenA = new Set();
      for (const a of actions) {
        if (!rec(a) || !str(a.key) || !KEY.test(a.key)) { err("home action key invalid"); continue; }
        bad(seenA.has(a.key), `duplicate home action ${a.key}`);
        seenA.add(a.key);
        bad(!ascii(a.label) || a.label.length > 40, `home action ${a.key} label must be ASCII up to 40 characters`);
        bad(!str(a.icon) || !ICON.test(a.icon), `home action ${a.key} icon invalid`);
        bad(!str(a.route) || !routes.has(a.route), `home action ${a.key} route must be a declared page route`);
        bad(!perms(a.requires), `home action ${a.key} requires must list at least one tab or action id`);
        bad(!order(a.order), `home action ${a.key} order invalid`);
      }
      const seenF = new Set();
      for (const f of feeds) {
        if (!rec(f) || !str(f.key) || !KEY.test(f.key)) { err("home feed key invalid"); continue; }
        bad(seenF.has(f.key), `duplicate home feed ${f.key}`);
        seenF.add(f.key);
        bad(!HOME_BLOCKS.includes(f.block), `home feed ${f.key} block must be one of ${HOME_BLOCKS.join(", ")}`);
        bad(!ascii(f.label) || f.label.length > 60, `home feed ${f.key} label must be ASCII up to 60 characters`);
        bad(!str(f.path) || !PATH.test(f.path) || f.path.includes("//"), `home feed ${f.key} path must be a plain API path`);
        bad(!perms(f.requires), `home feed ${f.key} requires must list at least one tab or action id`);
        bad(!order(f.order), `home feed ${f.key} order invalid`);
        bad(f.linkModule !== undefined && (!str(f.linkModule) || !ID.test(f.linkModule)), `home feed ${f.key} linkModule invalid`);
      }
    }
  }

  bad(m.landing !== undefined && !(Array.isArray(m.landing) && m.landing.every((r) => str(r) && routes.has(r))), "landing must list declared page routes");
  return errs;
}

/**
 * Split a peer permission ("<module>/<id>") into its module and id; null for an own id.
 * @param {string} id @returns {{ module: string, permission: string } | null}
 */
export function peerRef(id) {
  const m = typeof id === "string" ? PEER_PERM.exec(id) : null;
  return m ? { module: m[1], permission: m[2] } : null;
}

/**
 * The modules whose permission reads a module's pages also use: every peer named in a page's
 * `requires`, sorted, once each. Takes a manifest (pages) or a laid-out module (groups with items).
 */
export function peerModules(mod) {
  const lists = [
    ...(Array.isArray(mod.pages) ? mod.pages : []).map((p) => (Array.isArray(p?.requires) ? p.requires : [])),
    ...(mod.groups || []).flatMap((g) => (g.items || []).map((i) => i.requires || [])),
  ];
  return [...new Set(lists.flat().map((r) => peerRef(r)?.module).filter((x) => typeof x === "string"))].sort();
}

/** The id of the module whose permissions decide this module's pages: its source, else itself. */
export const permissionSourceId = (mod) => mod.rbac?.permissionSource || mod.id;
/** Does this module own its permissions (its own roles and admin API)? */
export const ownsPermissions = (mod) => permissionSourceId(mod) === mod.id;
/** Any-of: does a permission set open an entry that requires any of `requires`? */
export const canOpen = (requires, has) => requires.some((r) => has(r));

/** Validate a whole registry: every manifest, unique ids, the console module, permission sources and peers. */
export function validateRegistry(manifests) {
  const errs = [];
  const ids = new Set();
  for (const m of manifests) {
    errs.push(...validateManifest(m));
    if (ids.has(m?.id)) errs.push(`duplicate module id ${m?.id}`);
    ids.add(m?.id);
  }
  if (!ids.has("console")) errs.push("registry must contain the console module");
  const byId = new Map(manifests.map((m) => [m?.id, m]));
  for (const m of byId.values()) {
    const src = m?.rbac?.permissionSource;
    if (!str(src) || src === m.id) continue;
    const target = byId.get(src);
    if (!target) { errs.push(`${m.id}: rbac.permissionSource ${src} is not a module in the registry`); continue; }
    if (target.rbac?.permissionSource !== undefined) errs.push(`${m.id}: rbac.permissionSource ${src} must own its permissions`);
    for (const k of ["shape", "base", "me"]) if (target.rbac?.[k] !== m.rbac?.[k]) errs.push(`${m.id}: rbac.${k} must match ${src}`);
    for (const k of ["gateway", "prefix", "scopeEnv"]) if (target.api?.[k] !== m.api?.[k]) errs.push(`${m.id}: api.${k} must match ${src}`);
  }
  for (const m of byId.values()) {
    for (const peer of peerModules(m)) {
      const target = byId.get(peer);
      if (peer === m.id || peer === m.rbac?.permissionSource) errs.push(`${m.id}: a peer permission cannot name ${peer}, use its plain id`);
      else if (!target) errs.push(`${m.id}: peer permission module ${peer} is not a module in the registry`);
      else if (target.rbac?.permissionSource !== undefined) errs.push(`${m.id}: peer permission module ${peer} must own its permissions`);
      else if (target.rbac?.shape === "console") errs.push(`${m.id}: peer permission module ${peer} must be a tool with its own permission read`);
    }
  }
  return errs;
}

/** The launcher text when neither the manifest nor an admin set one: name and tagline, then page labels in rail order. */
export function autoDescription(m) {
  const groupOrder = new Map((m.groups || []).map((g) => [g.key, g.order]));
  const pages = [...(m.pages || [])].sort((a, b) => (groupOrder.get(a.group) ?? 0) - (groupOrder.get(b.group) ?? 0) || a.order - b.order);
  const clean = (s) => s.replace(/[<>]/g, "");
  const labels = [...new Set(pages.filter((p) => ascii(p.label)).map((p) => clean(p.label)))];
  const name = ascii(m.name) ? clean(m.name) : "This tool";
  const tagline = ascii(m.tagline) ? clean(m.tagline).replace(/[.\s]+$/, "") : "";
  const head = tagline ? `${name}: ${tagline}.` : `${name}.`;
  if (!labels.length) return head.slice(0, DESCRIPTION_MAX).trim();
  let shown = labels.length;
  for (; shown > 0; shown--) {
    const rest = labels.length - shown;
    const text = `${head} Covers ${labels.slice(0, shown).join(", ")}${rest ? ` and ${rest} more` : ""}.`;
    if (text.length <= DESCRIPTION_MAX) return text;
  }
  return head.slice(0, DESCRIPTION_MAX).trim();
}
