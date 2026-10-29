// Types for shell-packages/console-modules.

export type Accent = "brand" | "amber" | "blue" | "cyan" | "fuchsia" | "gold" | "green" | "indigo" | "orange" | "red" | "rose" | "teal" | "violet";
export type Hue = "brand" | "amber" | "blue" | "green" | "red" | "teal" | "violet";
export type RbacShape = "console" | "hub" | "endpoint";
export type LinkSlot = "rail" | "account";

export interface ManifestGroup { key: string; label: string; order: number }
export interface ManifestPage { key: string; route: string; label: string; icon: string; hue: Hue; requires: string[]; group: string; order: number; keywords?: string[] }
export interface ManifestLink { key: string; label: string; href: string; slot?: LinkSlot; group?: string; order: number; icon?: string }
export type HomeBlock = "waiting" | "live" | "fleet";
export interface HomeAction { key: string; label: string; icon: string; route: string; requires: string[]; order: number }
export interface HomeFeed { key: string; block: HomeBlock; label: string; path: string; requires: string[]; order: number; linkModule?: string }
export interface ManifestHome { actions?: HomeAction[]; feeds?: HomeFeed[] }
export interface ManifestTile { key: string; dashboard: string; label: string; permission: string; order: number }
export interface ModuleManifest {
  id: string; name: string; tagline: string; description?: string; accent: Accent; icon: string; order: number; client: string;
  api: { gateway: string; prefix: string; scopeEnv: string; estateKey?: string };
  rbac: { shape: RbacShape; base: string; me: string; permissionSource?: string };
  groups: ManifestGroup[]; pages: ManifestPage[]; links: ManifestLink[]; tiles: ManifestTile[];
  landing?: string[];
  home?: ManifestHome;
  /** Release notes: a path on the module's own API (served behind its access check) and its Changelog page. */
  whatsnew?: ManifestWhatsNew;
}
export interface ManifestWhatsNew { path: string; changelog: string }

export interface ModuleOverride { module_id: string; enabled?: boolean; tagline?: string | null; description?: string | null; order?: number | null; updated_at?: string }
export interface GroupOverride { module_id: string; group_key: string; label?: string | null; order?: number | null; hidden?: boolean; custom?: boolean; updated_at?: string }
export interface ItemOverride { module_id: string; item_key: string; kind?: "page" | "link"; group_key?: string | null; order?: number | null; label?: string | null; icon?: string | null; hidden?: boolean; href?: string | null; slot?: string | null; permission?: string | null; custom?: boolean; updated_at?: string }
export interface TileOverride { module_id: string; dashboard: string; tile_key: string; order?: number | null; hidden?: boolean; updated_at?: string }
export interface Overrides { modules?: ModuleOverride[]; groups?: GroupOverride[]; items?: ItemOverride[]; tiles?: TileOverride[] }

export interface NavEntry {
  kind: "page" | "link"; key: string; route?: string; href?: string; requires: string[]; label: string; icon: string; hue: Hue;
  keywords: string[]; order: number; hidden: boolean; isNew: boolean; custom: boolean; codeGroup?: string; slot?: LinkSlot;
}
export interface NavGroupOut { key: string; label: string; order: number; hidden: boolean; custom: boolean; isNew: boolean; items: NavEntry[] }
export interface TileOut { key: string; dashboard: string; label: string; permission: string; order: number; hidden: boolean; isNew: boolean }
export interface EffectiveModule {
  id: string; name: string; tagline: string; accent: Accent; icon: string; order: number; enabled: boolean; isNew: boolean;
  /** What the launcher shows: the admin's text, else the manifest's, else the automatic summary. */
  description: string;
  /** The description from code (manifest, else the automatic summary): what a reset returns to. */
  descriptionDefault: string;
  descriptionSource: "admin" | "manifest" | "auto";
  basePath: string; api: ModuleManifest["api"]; rbac: ModuleManifest["rbac"];
  groups: NavGroupOut[]; account: NavEntry[]; tiles: TileOut[]; landing: string[];
  home: { actions: HomeAction[]; feeds: Array<HomeFeed & { linkModule: string }> };
  whatsnew: ManifestWhatsNew | null;
}
export interface Orphan { kind: "module" | "group" | "item" | "tile"; module_id: string; key: string; reason: string }

export const ACCENTS: readonly Accent[];
export const HUES: readonly Hue[];
export const RBAC_SHAPES: readonly RbacShape[];
export const LINK_SLOTS: readonly LinkSlot[];
export const DESCRIPTION_MAX: number;
export function isDescription(v: unknown): v is string;
export function autoDescription(manifest: ModuleManifest | Record<string, unknown>): string;
export function validateManifest(input: unknown): string[];
export function validateRegistry(manifests: unknown[]): string[];
export function permissionSourceId(mod: { id: string; rbac?: { permissionSource?: string } }): string;
export function ownsPermissions(mod: { id: string; rbac?: { permissionSource?: string } }): boolean;
export function peerRef(id: string): { module: string; permission: string } | null;
export function peerModules(mod: { pages?: ReadonlyArray<{ requires: readonly string[] }>; groups?: ReadonlyArray<{ items: ReadonlyArray<{ requires: readonly string[] }> }> }): string[];
export function canOpen(requires: readonly string[], has: (id: string) => boolean): boolean;
export function effectiveLayout(
  manifests: ReadonlyArray<ModuleManifest | Record<string, any>>,
  overrides?: Overrides,
  opts?: { registryIds?: Record<string, ReadonlySet<string>> },
): { modules: EffectiveModule[]; orphaned: Orphan[] };
export function visibleNav(mod: EffectiveModule, has: (id: string) => boolean): { groups: Array<{ key: string; label: string; items: NavEntry[] }>; account: NavEntry[] };
export function landingRoute(mod: EffectiveModule, has: (id: string) => boolean): string | null;
export function visibleTiles(mod: EffectiveModule, dashboard: string, has: (id: string) => boolean): TileOut[];
export function moduleForPath(pathname: string, moduleIds: readonly string[]): string;

export const HOME_BLOCKS: readonly HomeBlock[];
export const HOME_MAX_ACTIONS: number;
export const HOME_MAX_FEEDS: number;
export type HomeActionOut = HomeAction & { moduleId: string; moduleName: string; accent: Accent };
export type HomeFeedOut = HomeFeed & { linkModule: string; moduleId: string; moduleName: string };
export function homeContributions(
  modules: ReadonlyArray<EffectiveModule>,
  hasFor: (mod: EffectiveModule) => ((id: string) => boolean) | null
): { actions: HomeActionOut[]; feeds: HomeFeedOut[] };
