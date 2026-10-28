// RBAC core for a multi-module shell: the functions every module's server and client share, so
// "what does this permission data mean" has one answer (standards/rbac.md, web-shell-packages.md).
//
// Pure functions only: no database, no HTTP framework, no UI library. Each module keeps its own
// permission registry and its own role, assignment and override tables; this file decides what that
// data means, identically everywhere:
//
//   - accessibleTabs: which tabs a permission set opens, computed from the registry on the server,
//     so a client never infers access from id strings.
//   - permissionsBeyond: the grant ceiling. A caller may only confer, edit or remove permissions
//     they already hold; the wildcard only by a genuine wildcard holder.
//   - assignableRoleIds / annotateRoles: which roles a subject could assign, used for the caller
//     (role pickers) and for a view-as subject.
//   - createAccess / canAssignRole: the client side, fed only by the server.
//
// Grammar: "tab:<name>", "action:<name>:<verb>", plus the super administrator wildcard "*".
// The server always re-checks; the client helpers only decide what to offer.

export const WILDCARD = "*";

/**
 * @typedef {{ id: string, label?: string, tab?: string, product?: string }} RegistryEntry
 * @typedef {{ tabs: RegistryEntry[], actions: RegistryEntry[] }} Registry
 */

/** @param {unknown} value @returns {string[]} */
export function toPermissionList(value) {
  let raw = value;
  if (typeof raw === "string") {
    // Stored JSON text. Unparseable is treated as "*" so a ceiling check fails closed.
    try { raw = JSON.parse(raw); } catch { return [WILDCARD]; }
  }
  return Array.isArray(raw) ? raw.map(String) : [];
}

/** @param {Registry} registry @returns {string[]} */
export function registryIds(registry) {
  return [...(registry?.tabs || []), ...(registry?.actions || [])].map((e) => e.id);
}

/**
 * Expand "*" to the registry and drop nothing else (stale ids stay visible to
 * the caller so drift is reported, never silently granted or removed).
 * @param {unknown} perms @param {Registry} registry @returns {Set<string>}
 */
export function expandPermissions(perms, registry) {
  const list = toPermissionList(perms);
  if (list.includes(WILDCARD)) return new Set(registryIds(registry));
  return new Set(list);
}

/**
 * Tabs a permission set opens, limited to tabs the registry defines. A tab is
 * open when its id is held, or when any held id starts "action:<tab-name>:".
 * That is the rule a client would otherwise apply by itself, so computing it
 * on the server changes no one's visible tabs.
 * @param {unknown} perms @param {Registry} registry @returns {string[]}
 */
export function accessibleTabs(perms, registry) {
  const held = expandPermissions(perms, registry);
  const out = [];
  for (const t of registry?.tabs || []) {
    if (held.has(t.id)) { out.push(t.id); continue; }
    const prefix = t.id.replace(/^tab:/, "action:") + ":";
    for (const p of held) { if (p.startsWith(prefix)) { out.push(t.id); break; } }
  }
  return out;
}

/**
 * The grant ceiling. Returns the ids in `requested` the caller does not hold
 * (empty = allowed). Ids the registry no longer defines are NOT dropped: a role
 * carrying a stale id stays outside a delegate's ceiling until a super admin
 * cleans it (fail closed). Dropping them would be unsafe where a registry is
 * scoped to one product and a shared role can carry another product's ids; the
 * role list reports them as `unknownPermissions`. "*" is not a snapshot of today's registry (it also picks
 * up every permission added later), so only a genuine "*" holder may confer it.
 * @param {{ requested: unknown, callerPermissions: Iterable<string>, callerIsWildcard: boolean, registry: Registry }} args
 * @returns {string[]}
 */
export function permissionsBeyond({ requested, callerPermissions, callerIsWildcard, registry }) {
  if (callerIsWildcard) return [];
  const list = toPermissionList(requested);
  if (list.includes(WILDCARD)) return [WILDCARD];
  const held = new Set(callerPermissions);
  if (held.has(WILDCARD)) return [];
  return [...expandPermissions(list, registry)].filter((p) => !held.has(p));
}

/** @param {string[]} beyond @returns {string} */
export function grantCeilingMessage(beyond) {
  const shown = beyond.slice(0, 10).join(", ") + (beyond.length > 10 ? ` (+${beyond.length - 10} more)` : "");
  return `You cannot grant permission(s) you do not hold yourself: ${shown}. Ask a super administrator.`;
}

/** @param {string[]} beyond @returns {string} */
export function viewAsCeilingMessage(beyond) {
  const shown = beyond.slice(0, 10).join(", ") + (beyond.length > 10 ? ` (+${beyond.length - 10} more)` : "");
  return `You can only preview access within your own: this subject holds ${shown}. Ask a super administrator.`;
}

/**
 * @template {{ id: string | number, permissions?: unknown }} R
 * @param {R[]} roles
 * @param {{ callerPermissions: Iterable<string>, callerIsWildcard: boolean, registry: Registry }} subject
 * @returns {string[]} ids of the roles the subject could assign under the ceiling
 */
export function assignableRoleIds(roles, subject) {
  const held = [...subject.callerPermissions];
  return (roles || [])
    .filter((r) => permissionsBeyond({ requested: r.permissions, callerPermissions: held, callerIsWildcard: subject.callerIsWildcard, registry: subject.registry }).length === 0)
    .map((r) => String(r.id));
}

/**
 * Add `assignable` (the caller may assign it, view as it, and edit or delete it
 * under the ceiling) and `unknownPermissions` (stored ids no longer in the
 * registry) to each role row the admin API returns.
 * @template {{ id: string | number, permissions?: unknown }} R
 * @param {R[]} roles
 * @param {{ callerPermissions: Iterable<string>, callerIsWildcard: boolean, registry: Registry }} caller
 * @returns {Array<R & { assignable: boolean, unknownPermissions: string[] }>}
 */
export function annotateRoles(roles, caller) {
  const ok = new Set(assignableRoleIds(roles, caller));
  const known = new Set(registryIds(caller.registry));
  return (roles || []).map((r) => ({
    ...r,
    assignable: ok.has(String(r.id)),
    unknownPermissions: toPermissionList(r.permissions).filter((p) => p !== WILDCARD && !known.has(p)),
  }));
}

/**
 * Registry ids the caller may grant (role editor and override editor tick boxes).
 * @param {{ callerPermissions: Iterable<string>, callerIsWildcard: boolean, registry: Registry }} caller
 * @returns {string[]}
 */
export function grantableIds(caller) {
  const all = registryIds(caller.registry);
  if (caller.callerIsWildcard) return all;
  const held = new Set(caller.callerPermissions);
  if (held.has(WILDCARD)) return all;
  return all.filter((id) => held.has(id));
}

/**
 * Everything a view-as preview needs, computed with the same ceiling the server
 * enforces. `subjectIsWildcard` marks a super administrator subject (break-glass or a
 * "*" role), whose permission set is "*" for ceiling purposes. `beyond` is what
 * the subject holds that the caller does not (non-empty = refuse the preview).
 * @param {{ subjectPermissions: Iterable<string>, subjectIsWildcard: boolean, caller: { callerPermissions: Iterable<string>, callerIsWildcard: boolean }, registry: Registry, roles: Array<{ id: string | number, permissions?: unknown }> }} args
 */
export function viewAsPreview({ subjectPermissions, subjectIsWildcard, caller, registry, roles }) {
  const held = [...subjectPermissions].filter((p) => p !== WILDCARD);
  const permissions = subjectIsWildcard ? registryIds(registry) : held;
  const beyond = permissionsBeyond({
    requested: subjectIsWildcard ? [WILDCARD] : held,
    callerPermissions: caller.callerPermissions,
    callerIsWildcard: caller.callerIsWildcard,
    registry,
  });
  const subject = { callerPermissions: permissions, callerIsWildcard: subjectIsWildcard, registry };
  return {
    beyond,
    permissions,
    tabs: accessibleTabs(permissions, registry),
    assignableRoleIds: assignableRoleIds(roles, subject),
    grantable: grantableIds(subject),
  };
}

/**
 * Every permission-id string literal in a source file ("tab:x", "action:x:y").
 * Used by each tool's registry-conformance test: a gate naming an id the
 * registry does not define fails the build instead of silently hiding a feature.
 * @param {string} source @returns {string[]}
 */
export function findPermissionLiterals(source) {
  const re = /["'`]((?:tab|action):[a-z0-9-]+(?::[a-z0-9-]+)?)["'`]/g;
  /** @type {Set<string>} */
  const out = new Set();
  for (const m of String(source).matchAll(re)) out.add(/** @type {string} */ (m[1]));
  return [...out];
}

/**
 * Remove retired permission ids from a stored permission list (roles and
 * overrides). Only ids in `retired` that the registry no longer defines are
 * removed, so a retired list can never strip a live permission. Returns null
 * when nothing changes. "*" is never touched.
 * @param {unknown} perms @param {string[]} retired @param {Registry} registry
 * @returns {string[] | null}
 */
export function stripRetiredPermissions(perms, retired, registry) {
  const list = toPermissionList(perms);
  if (list.includes(WILDCARD)) return null;
  const live = new Set(registryIds(registry));
  const drop = new Set((retired || []).filter((id) => !live.has(id)));
  const kept = list.filter((p) => !drop.has(p));
  return kept.length === list.length ? null : kept;
}

// client side ---------------------------------------------------------------------

/**
 * The registry narrowed to the ids in `grantable` (role and override editors
 * only offer what the current subject may grant). null keeps everything. A tab
 * is kept as a group header when any of its actions is grantable, so an action
 * is never hidden just because its tab id is not; the server still refuses the
 * tab id itself if it is ticked.
 * @template {{ tabs?: Array<{ id: string }>, actions?: Array<{ id: string }> }} T
 * @param {T} registry @param {string[] | null | undefined} grantable
 */
export function filterRegistry(registry, grantable) {
  const tabs = registry?.tabs || [];
  const actions = registry?.actions || [];
  if (!Array.isArray(grantable)) return { ...registry, tabs, actions };
  const ok = new Set(grantable);
  const keptActions = actions.filter((a) => ok.has(a.id));
  const headerTabs = new Set(keptActions.map((a) => /** @type {{ tab?: string }} */ (a).tab).filter(Boolean));
  return { ...registry, tabs: tabs.filter((t) => ok.has(t.id) || headerTabs.has(t.id)), actions: keptActions };
}

/**
 * The grantable list in force: the view-as subject's while previewing,
 * otherwise the caller's from GET /permissions. null = no narrowing known.
 * @param {{ grantable?: string[] | null } | null | undefined} registryResponse
 * @param {object | null | undefined} impersonating
 * @returns {string[] | null}
 */
export function activeGrantable(registryResponse, impersonating) {
  const imp = /** @type {{ grantable?: unknown } | null | undefined} */ (impersonating);
  if (imp && Array.isArray(imp.grantable)) return imp.grantable;
  if (registryResponse && Array.isArray(registryResponse.grantable)) return registryResponse.grantable;
  return null;
}

/**
 * Permission checks for an client, fed only by the server. `tabs` is the server's
 * accessibleTabs result; when an older API omits it, the historical prefix rule
 * is the fallback so a web deploy that lands before its API never hides a tab.
 * @param {{ permissions?: string[] | null, tabs?: string[] | null }} source
 */
export function createAccess(source) {
  const perms = Array.isArray(source?.permissions) ? source.permissions : [];
  const tabs = Array.isArray(source?.tabs) ? new Set(source.tabs) : null;
  const all = perms.includes(WILDCARD);
  /** @param {string} id */
  const hasPermission = (id) => all || perms.includes(id);
  /** @param {string} tabId */
  const hasTab = (tabId) => {
    if (all) return true;
    // Server-computed tabs are authoritative and complete (accessibleTabs); the
    // prefix rule below is only for an older API that does not send them.
    if (tabs) return tabs.has(tabId);
    if (perms.includes(tabId)) return true;
    const prefix = tabId.replace(/^tab:/, "action:") + ":";
    return perms.some((p) => p.startsWith(prefix));
  };
  return { hasPermission, hasTab };
}

/**
 * Whether a role picker should offer `role`. While previewing (view-as) the
 * subject's own ceiling applies; otherwise the server's `assignable` flag. A
 * missing flag (older API) defers to the server, which enforces regardless.
 * @param {{ id: string | number, assignable?: boolean }} role
 * @param {object | null | undefined} impersonating
 */
export function canAssignRole(role, impersonating) {
  const imp = /** @type {{ assignableRoleIds?: unknown } | null | undefined} */ (impersonating);
  if (imp && Array.isArray(imp.assignableRoleIds)) {
    return imp.assignableRoleIds.includes(String(role.id));
  }
  return role.assignable !== false;
}

/**
 * Whether a permission tick box should be enabled for the current subject.
 * @param {string} id
 * @param {{ grantable?: string[] | null } | null | undefined} registryResponse
 * @param {object | null | undefined} impersonating
 */
export function canGrantPermission(id, registryResponse, impersonating) {
  const list = activeGrantable(registryResponse, impersonating);
  return list ? list.includes(id) : true;
}
