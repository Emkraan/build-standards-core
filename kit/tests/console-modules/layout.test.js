import { test } from "node:test";
import assert from "node:assert/strict";
import {
  validateManifest, validateRegistry, effectiveLayout as rawLayout, visibleNav, landingRoute, visibleTiles, moduleForPath, canOpen, permissionSourceId, ownsPermissions, peerRef, peerModules,
  autoDescription, isDescription, DESCRIPTION_MAX, homeContributions,
} from "../../../shell-packages/console-modules/index.js";

// Synthetic module, not a real tool.
/** @returns {any} */
const base = () => ({
  id: "demo", name: "Demo", tagline: "Synthetic test module", accent: "blue", icon: "Box", order: 50,
  client: "apps/demo/client", api: { gateway: "demo", prefix: "/api", scopeEnv: "DEMO" },
  rbac: { shape: "hub", base: "/admin", me: "/admin/my-permissions" },
  groups: [{ key: "main", label: "Main", order: 10 }, { key: "admin", label: "Admin", order: 20 }],
  pages: [
    { key: "dashboard", route: "/dashboard", label: "Dashboard", icon: "LayoutDashboard", hue: "brand", requires: ["tab:dashboard"], group: "main", order: 10 },
    { key: "users", route: "/users", label: "Users", icon: "Users", hue: "teal", requires: ["tab:users"], group: "main", order: 20 },
    { key: "admin", route: "/admin", label: "Admin", icon: "Shield", hue: "red", requires: ["tab:admin", "tab:settings"], group: "admin", order: 10 },
  ],
  links: [{ key: "status", label: "Status", href: "https://status.example.com/", slot: "account", order: 10 }],
  tiles: [
    { key: "total", dashboard: "dashboard", label: "Total", permission: "action:dashboard:tile-total", order: 10 },
    { key: "active", dashboard: "dashboard", label: "Active", permission: "action:dashboard:tile-active", order: 20 },
  ],
});
const consoleMod = () => ({ ...base(), id: "console", client: "apps/shell/client", order: 0 });
/** Test view of the merge result: index access without undefined noise. @param {Parameters<typeof rawLayout>} a @returns {any} */
const effectiveLayout = (...a) => rawLayout(...a);
/** @param {string[]} perms */
const hasOf = (perms) => (/** @type {string} */ id) => perms.includes("*") || perms.includes(id);

test("validateManifest rejects bad shapes and non-https or non-ASCII values", () => {
  assert.deepEqual(validateManifest(base()), []);
  const bad = base();
  bad.pages[0].requires = [];
  bad.pages[1].group = "nope";
  bad.links[0].href = "javascript:alert(1)";
  bad.name = "Caf\u00e9";
  const errs = validateManifest(bad).join("\n");
  assert.match(errs, /requires must list/);
  assert.match(errs, /group nope is not declared/);
  assert.match(errs, /href must be https/);
  assert.match(errs, /name must be ASCII/);
  assert.match(validateRegistry([base(), base()]).join("\n"), /duplicate module id demo/);
  assert.match(validateRegistry([base()]).join("\n"), /must contain the console module/);
});

test("no overrides: code defaults render and every entry is flagged new", () => {
  const { modules, orphaned } = effectiveLayout([base(), consoleMod()]);
  assert.deepEqual(orphaned, []);
  assert.equal(modules[0].id, "console");
  const demo = modules[1];
  assert.equal(demo.basePath, "/demo");
  assert.equal(modules[0].basePath, "/");
  assert.deepEqual(demo.groups.map((/** @type {any} */ g) => g.key), ["main", "admin"]);
  assert.ok(demo.groups.every((/** @type {any} */ g) => g.isNew && g.items.every((/** @type {any} */ i) => i.isNew)));
  assert.deepEqual(demo.landing, ["/dashboard", "/users", "/admin"]);
  assert.equal(demo.account[0].key, "status");
  assert.equal(demo.enabled, true);
});

test("overrides move, rename, reorder and hide, but never change what a page requires", () => {
  const { modules } = effectiveLayout([base()], {
    modules: [{ module_id: "demo", tagline: "Changed", order: 5, enabled: false }],
    groups: [{ module_id: "demo", group_key: "admin", order: 1, label: "Control" }],
    items: [
      { module_id: "demo", item_key: "users", group_key: "admin", order: 1, label: "People", icon: "Contact" },
      /** @type {any} */ ({ module_id: "demo", item_key: "dashboard", hidden: true, requires: ["tab:nothing"] }),
    ],
  });
  const demo = modules[0];
  assert.equal(demo.tagline, "Changed");
  assert.equal(demo.enabled, false);
  assert.deepEqual(demo.groups.map((/** @type {any} */ g) => g.label), ["Control", "Main"]);
  const control = demo.groups[0];
  assert.deepEqual(control.items.map((/** @type {any} */ i) => i.key), ["users", "admin"]);
  assert.equal(control.items[0].label, "People");
  assert.equal(control.items[0].icon, "Contact");
  assert.deepEqual(control.items[0].requires, ["tab:users"]);
  const dash = demo.groups[1].items[0];
  assert.equal(dash.hidden, true);
  assert.deepEqual(dash.requires, ["tab:dashboard"]);
});

test("orphaned overrides are reported and never rendered", () => {
  const { modules, orphaned } = effectiveLayout([base()], {
    modules: [{ module_id: "gone" }],
    groups: [{ module_id: "demo", group_key: "old" }],
    items: [{ module_id: "demo", item_key: "removed-page" }],
    tiles: [{ module_id: "demo", dashboard: "dashboard", tile_key: "old-tile" }],
  });
  assert.deepEqual(orphaned.map((/** @type {any} */ o) => `${o.kind}:${o.key}`).sort(), ["group:old", "item:removed-page", "module:gone", "tile:dashboard/old-tile"]);
  assert.ok(!modules[0].groups.some((/** @type {any} */ g) => g.key === "old"));
});

test("custom links: https only, permission must be in the module registry", () => {
  const registryIds = { demo: new Set(["tab:users"]) };
  const { modules, orphaned } = effectiveLayout([base()], {
    groups: [{ module_id: "demo", group_key: "extras", custom: true, label: "Extras", order: 30 }],
    items: [
      { module_id: "demo", item_key: "wiki", kind: "link", custom: true, href: "https://wiki.example.com/", label: "Wiki", group_key: "extras", order: 1 },
      { module_id: "demo", item_key: "gated", kind: "link", custom: true, href: "https://x.example.com/", permission: "tab:users", group_key: "extras", order: 2 },
      { module_id: "demo", item_key: "evil", kind: "link", custom: true, href: "http://insecure.example.com/" },
      { module_id: "demo", item_key: "ghost", kind: "link", custom: true, href: "https://x.example.com/", permission: "tab:not-real" },
    ],
  }, { registryIds });
  const extras = modules[0].groups.find((/** @type {any} */ g) => g.key === "extras");
  assert.ok(extras);
  assert.deepEqual(extras.items.map((/** @type {any} */ i) => i.key), ["wiki", "gated"]);
  assert.deepEqual(extras.items[1].requires, ["tab:users"]);
  assert.deepEqual(orphaned.map((/** @type {any} */ o) => o.key).sort(), ["evil", "ghost"]);
});

test("visibleNav filters by the tool's own permission check and drops empty groups", () => {
  const { modules } = effectiveLayout([base()]);
  const nav = visibleNav(modules[0], hasOf(["tab:users"]));
  assert.deepEqual(nav.groups.map((/** @type {any} */ g) => g.key), ["main"]);
  assert.deepEqual(nav.groups[0]?.items.map((/** @type {any} */ i) => i.key), ["users"]);
  assert.deepEqual(visibleNav(modules[0], hasOf(["tab:settings"])).groups.map((/** @type {any} */ g) => g.key), ["admin"]);
  assert.equal(visibleNav(modules[0], hasOf(["*"])).groups.length, 2);
  assert.deepEqual(visibleNav(modules[0], hasOf([])).groups, []);
});

test("landingRoute honours the code landing chain and still lands on a hidden page the caller can open", () => {
  const m = { ...base(), landing: ["/admin", "/dashboard", "/users"] };
  const { modules } = effectiveLayout([m], { items: [{ module_id: "demo", item_key: "users", hidden: true }] });
  assert.equal(landingRoute(modules[0], hasOf(["tab:users", "tab:dashboard"])), "/dashboard");
  assert.equal(landingRoute(modules[0], hasOf(["tab:users"])), "/users");
  assert.equal(landingRoute(modules[0], hasOf([])), null);
});

test("visibleTiles applies admin order and hiding on top of the tile permission", () => {
  const { modules } = effectiveLayout([base()], { tiles: [{ module_id: "demo", dashboard: "dashboard", tile_key: "active", order: 1 }, { module_id: "demo", dashboard: "dashboard", tile_key: "total", hidden: true }] });
  assert.deepEqual(visibleTiles(modules[0], "dashboard", hasOf(["*"])).map((t) => t.key), ["active"]);
  assert.deepEqual(visibleTiles(modules[0], "dashboard", hasOf(["action:dashboard:tile-total"])), []);
});

test("bad override rows are skipped, never thrown", () => {
  assert.doesNotThrow(() => effectiveLayout([base()], { items: [/** @type {any} */ ({ module_id: "demo", item_key: "users", order: -5, label: 42, icon: "<script>" })] }));
  const { modules } = effectiveLayout([base()], { items: [/** @type {any} */ ({ module_id: "demo", item_key: "users", order: -5, label: 42, icon: "bad icon" })] });
  const users = modules[0].groups[0].items.find((/** @type {any} */ i) => i.key === "users");
  assert.equal(users?.order, 20);
  assert.equal(users?.label, "Users");
  assert.equal(users?.icon, "Users");
});

test("moduleForPath and canOpen", () => {
  const ids = ["console", "gamma", "beta"];
  assert.equal(moduleForPath("/gamma/users", ids), "gamma");
  assert.equal(moduleForPath("/beta", ids), "beta");
  assert.equal(moduleForPath("/access", ids), "console");
  assert.equal(moduleForPath("/", ids), "console");
  assert.equal(moduleForPath("/console/x", ids), "console");
  assert.equal(canOpen(["tab:a", "tab:b"], hasOf(["tab:b"])), true);
  assert.equal(canOpen(["tab:a"], hasOf([])), false);
});

test("description: admin text wins, then the manifest, then the automatic summary from page labels", () => {
  const auto = effectiveLayout([base()]).modules[0];
  assert.equal(auto.descriptionSource, "auto");
  assert.equal(auto.description, "Demo: Synthetic test module. Pages: Dashboard, Users and Admin.");
  assert.equal(auto.descriptionDefault, auto.description);

  const coded = { ...base(), description: "Synthetic manifest description." };
  const fromCode = effectiveLayout([coded]).modules[0];
  assert.equal(fromCode.descriptionSource, "manifest");
  assert.equal(fromCode.description, "Synthetic manifest description.");

  const admin = effectiveLayout([coded], { modules: [{ module_id: "demo", description: "Synthetic admin description." }] }).modules[0];
  assert.equal(admin.descriptionSource, "admin");
  assert.equal(admin.description, "Synthetic admin description.");
  assert.equal(admin.descriptionDefault, "Synthetic manifest description.");

  // A bad saved row (markup, too long, non-ASCII) is skipped, never rendered.
  for (const bad of ["<b>x</b>", "x".repeat(DESCRIPTION_MAX + 1), "Caf\u00e9", null]) {
    const m = effectiveLayout([coded], { modules: [{ module_id: "demo", description: bad }] }).modules[0];
    assert.equal(m.description, "Synthetic manifest description.", String(bad));
    assert.equal(m.descriptionSource, "manifest");
  }
});

test("autoDescription fits the cap and counts the pages it could not name", () => {
  const many = base();
  many.pages = Array.from({ length: 60 }, (_, i) => ({ ...many.pages[0], key: `p${i}`, route: `/p${i}`, label: `Synthetic page number ${i}`, order: i }));
  const s = autoDescription(many);
  assert.ok(s.length <= DESCRIPTION_MAX, String(s.length));
  assert.match(s, /^Demo: Synthetic test module\. Pages: Synthetic page number 0, /);
  assert.match(s, /and \d+ more\.$/);
  assert.ok(isDescription(s));
  assert.equal(autoDescription({ ...base(), pages: [] }), "Demo: Synthetic test module.");
});

test("validateManifest checks the optional description", () => {
  assert.deepEqual(validateManifest({ ...base(), description: "Plain synthetic text." }), []);
  for (const bad of ["", " padded", "<script>", "x".repeat(DESCRIPTION_MAX + 1), "Caf\u00e9", 7]) {
    assert.match(validateManifest({ ...base(), description: bad }).join("\n"), /description must be plain ASCII text/, String(bad));
  }
});

// Support Desk: a module that declares the console as its permission source.
const supportMod = () => ({
  ...base(), id: "support", name: "Support Desk", order: 25, client: "apps/shell/client",
  api: { gateway: "console", prefix: "/api", scopeEnv: "CONSOLE", estateKey: "support" },
  rbac: { shape: "console", base: "/admin", me: "/me", permissionSource: "console" },
});
const sourceConsole = () => ({ ...consoleMod(), api: { gateway: "console", prefix: "/api", scopeEnv: "CONSOLE" }, rbac: { shape: "console", base: "/admin", me: "/me" } });

test("rbac.permissionSource: a module can declare the console as its permission source", () => {
  assert.deepEqual(validateManifest(supportMod()), []);
  assert.deepEqual(validateRegistry([sourceConsole(), supportMod()]), []);
  assert.equal(permissionSourceId(supportMod()), "console");
  assert.equal(permissionSourceId(base()), "demo");
  assert.equal(ownsPermissions(supportMod()), false);
  assert.equal(ownsPermissions(sourceConsole()), true);
});

test("rbac.permissionSource is checked: shape, self, unknown source, chains and a matching read", () => {
  const hub = { ...supportMod(), rbac: { shape: "hub", base: "/admin", me: "/admin/my-permissions", permissionSource: "console" } };
  assert.match(validateManifest(hub).join("\n"), /only for shape console/);
  const self = supportMod(); self.rbac.permissionSource = "support";
  assert.match(validateManifest(self).join("\n"), /cannot name the module itself/);
  const bad = supportMod(); bad.rbac.permissionSource = "Not An Id";
  assert.match(validateManifest(bad).join("\n"), /must be a module id/);
  const unknown = supportMod(); unknown.rbac.permissionSource = "ghost";
  assert.match(validateRegistry([sourceConsole(), unknown]).join("\n"), /ghost is not a module in the registry/);
  const other = { ...supportMod(), id: "other" };
  other.rbac = { ...other.rbac, permissionSource: "support" };
  assert.match(validateRegistry([sourceConsole(), supportMod(), other]).join("\n"), /must own its permissions/);
  const drift = supportMod(); drift.rbac.me = "/whoami";
  assert.match(validateRegistry([sourceConsole(), drift]).join("\n"), /rbac\.me must match console/);
  const gw = supportMod(); gw.api = { ...gw.api, gateway: "elsewhere" };
  assert.match(validateRegistry([sourceConsole(), gw]).join("\n"), /api\.gateway must match console/);
  const est = supportMod(); est.api.estateKey = "Bad Key";
  assert.match(validateManifest(est).join("\n"), /estateKey/);
});

test("the landing is the first page the caller can open, in rail order", () => {
  const { modules } = effectiveLayout([sourceConsole(), { ...supportMod(), landing: ["/agent", "/integrations"], pages: [
    { key: "agent", route: "/agent", label: "Endpoint agent", icon: "Cpu", hue: "blue", requires: ["tab:agent"], group: "main", order: 10 },
    { key: "integrations", route: "/integrations", label: "Integrations", icon: "Plug", hue: "teal", requires: ["tab:integrations"], group: "admin", order: 10 },
  ], tiles: [], links: [] }], {});
  const layout = modules.find((/** @type {any} */ m) => m.id === "support");
  assert.equal(landingRoute(layout, hasOf(["tab:integrations"])), "/integrations");
  assert.equal(landingRoute(layout, hasOf(["tab:agent", "tab:integrations"])), "/agent");
  assert.equal(landingRoute(layout, hasOf([])), null);
});

// Peer permissions: a page can also open for the holders of a permission that lives in another tool.
test("peerRef splits a peer id and leaves a plain id alone", () => {
  assert.deepEqual(peerRef("alpha/action:admin:integration-one"), { module: "alpha", permission: "action:admin:integration-one" });
  assert.deepEqual(peerRef("beta/tab:admin"), { module: "beta", permission: "tab:admin" });
  assert.equal(peerRef("tab:integrations"), null);
  assert.equal(peerRef("action:admin:mailbox"), null);
  assert.equal(peerRef("alpha/not a permission"), null);
});

/** @param {string[]} requires @returns {any} */
const peerPage = (requires) => ({ ...supportMod(), pages: [{ key: "connections", route: "/connections", label: "Connections", icon: "Plug", hue: "teal", requires, group: "g", order: 10 }], groups: [{ key: "g", label: "G", order: 1 }] });
/** @param {string} id @returns {any} */
const peerTool = (id) => ({ ...base(), id, client: `apps/${id}-console/client`, rbac: { shape: "endpoint", base: "/support/admin", me: "/support/me" } });

test("a page may list a peer permission next to its own ids, and peerModules names the tools to read", () => {
  const ep = peerPage(["tab:integrations", "alpha/action:admin:integration-one", "beta/action:admin:mailbox", "alpha/action:admin:integration-two"]);
  assert.deepEqual(validateManifest(ep), []);
  assert.deepEqual(peerModules(ep), ["alpha", "beta"]);
  assert.deepEqual(peerModules(peerPage(["tab:integrations"])), []);
  // canOpen stays any-of: the host answers a peer id from that tool's me read.
  const has = (/** @type {string} */ id) => id === "beta/action:admin:mailbox";
  assert.equal(canOpen(ep.pages[0].requires, has), true);
  assert.equal(canOpen(ep.pages[0].requires, () => false), false);
});

test("a peer permission must name a registered tool that owns its permissions", () => {
  const ok = [sourceConsole(), peerTool("alpha"), peerTool("beta"), peerPage(["tab:integrations", "alpha/action:admin:integration-one", "beta/action:admin:mailbox"])];
  assert.deepEqual(validateRegistry(ok), []);
  assert.match(validateRegistry([sourceConsole(), peerPage(["alpha/action:admin:integration-one"])]).join("\n"), /alpha is not a module in the registry/);
  assert.match(validateRegistry([sourceConsole(), peerTool("alpha"), peerPage(["support/tab:agent"])]).join("\n"), /cannot name support/);
  assert.match(validateRegistry([sourceConsole(), peerTool("alpha"), peerPage(["console/tab:agent"])]).join("\n"), /cannot name console/);
  const sourced = { ...peerTool("alpha"), rbac: { ...peerTool("alpha").rbac, permissionSource: "console" } };
  assert.match(validateRegistry([sourceConsole(), sourced, peerPage(["alpha/tab:admin"])]).join("\n"), /must own its permissions/);
  assert.match(validateManifest(peerPage(["Talos/tab:admin"])).join("\n"), /requires must list/);
});

/** @returns {any} */
const withHome = () => {
  const m = base();
  m.home = {
    actions: [{ key: "find-user", label: "Find a user", icon: "UserSearch", route: "/users", requires: ["action:users:search"], order: 10 }],
    feeds: [
      { key: "approvals", block: "waiting", label: "Approvals", path: "/demo/home/waiting", requires: ["action:approve:any"], order: 10 },
      { key: "live", block: "live", label: "Live", path: "/demo/home/live", requires: ["tab:dashboard"], order: 20 },
    ],
  };
  return m;
};

test("home contributions validate: shape, bounds, declared route, relay only with a permission source", () => {
  assert.deepEqual(validateManifest(withHome()), []);
  const bad = withHome();
  bad.home.actions[0].route = "/nowhere";
  bad.home.actions[0].requires = [];
  bad.home.feeds[0].block = "stars";
  bad.home.feeds[1].path = "https://evil.example/x";
  bad.home.feeds.push({ ...bad.home.feeds[1], key: "r", path: "/demo/r", linkModule: "Bad Id" });
  bad.home.feeds.push({ ...bad.home.feeds[1], key: "dup" }, { ...bad.home.feeds[1], key: "dup" });
  const errs = validateManifest(bad).join("\n");
  assert.match(errs, /route must be a declared page route/);
  assert.match(errs, /home action find-user requires must list/);
  assert.match(errs, /block must be one of waiting, live, fleet/);
  assert.match(errs, /path must be a plain API path/);
  assert.match(errs, /linkModule invalid/);
  assert.match(errs, /duplicate home feed dup/);
  const many = withHome();
  many.home.actions = Array.from({ length: 5 }, (_, i) => ({ ...withHome().home.actions[0], key: `a${i}` }));
  assert.match(validateManifest(many).join("\n"), /home.actions holds at most 4/);
  const notObj = base();
  notObj.home = [];
  assert.match(validateManifest(notObj).join("\n"), /home must be an object/);
});

test("the effective layout carries home from code, with linkModule defaulted", () => {
  const { modules } = effectiveLayout([withHome(), consoleMod()]);
  const demo = modules.find((/** @type {any} */ x) => x.id === "demo");
  assert.equal(demo.home.feeds[0].linkModule, "demo");
  assert.equal(demo.home.actions.length, 1);
  assert.deepEqual(modules.find((/** @type {any} */ x) => x.id === "console").home, { actions: [], feeds: [] });
});

test("homeContributions shows only what the caller holds, drops disabled modules, fails closed", () => {
  const { modules } = effectiveLayout([withHome(), consoleMod()]);
  const holds = (/** @type {string[]} */ perms) => () => hasOf(perms);
  const all = homeContributions(modules, holds(["action:users:search", "action:approve:any", "tab:dashboard"]));
  assert.deepEqual(all.actions.map((/** @type {any} */ a) => a.key), ["find-user"]);
  assert.deepEqual(all.feeds.map((/** @type {any} */ f) => f.key), ["approvals", "live"]);
  assert.equal(all.feeds[0]?.moduleId, "demo");
  const some = homeContributions(modules, holds(["tab:dashboard"]));
  assert.deepEqual(some.actions, []);
  assert.deepEqual(some.feeds.map((/** @type {any} */ f) => f.key), ["live"]);
  assert.deepEqual(homeContributions(modules, holds([])), { actions: [], feeds: [] });
  // no permission answer for the module (not read yet, failed, 401): nothing
  assert.deepEqual(homeContributions(modules, () => null), { actions: [], feeds: [] });
  // a peer id never opens a Home entry, the admin-disabled module contributes nothing
  const off = effectiveLayout([withHome(), consoleMod()], { modules: [{ module_id: "demo", enabled: false }] }).modules;
  assert.deepEqual(homeContributions(off, holds(["*"])), { actions: [], feeds: [] });
});

