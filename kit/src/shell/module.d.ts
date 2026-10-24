/* Module contract for a multi-module shell (the web shell standard, sections 3 and 4). Types
   only: the manifest is the JSON file a module ships, the registry entry is what the generator
   writes from it (scripts/build-registry.mjs), and the descriptor is what the module's client
   package exports so the shell and the standalone host mount the same route table. Declared once
   here and imported by every module, so a module that drifts fails the typecheck. */

import type { Announcement } from '../chrome/Announcement';
import type { HomeItem } from '../chrome/HomeBlocks';
import type { NavHue } from '../lib/hues';
import type { AppAccent } from '../theme/accent';

/** The manifest file of one module. Nothing else lists the modules. */
export type ModuleManifest<TExtra extends object = Record<never, never>, TAccent extends string = AppAccent> = ModuleManifestBase<TAccent> & TExtra;

interface ModuleManifestBase<TAccent extends string> {
  /** Short stable slug: lowercase letters, digits, `-` or `_`. Also the first path segment, the
      `data-module` value, the storage `appId` and the keyframes prefix. */
  id: string;
  name: string;
  /** The mount path. Defaults to `/<id>`. Its first segment must be the id. */
  route?: string | undefined;
  /** One of the kit accent names. */
  accent: TAccent;
  /** An icon name the shell resolves. A module with none gets the registry's fallback icon. */
  icon?: string | undefined;
  /** Sort order in the hub and the tool switcher (default 0, then by id). */
  order?: number | undefined;
  /** One short line for the hub tile. */
  description?: string | undefined;
}

/** One module as the generated registry holds it: every default resolved, icon always present. */
export type RegistryEntry<TExtra extends object = Record<never, never>, TAccent extends string = AppAccent> = RegistryEntryBase<TAccent> & TExtra;

interface RegistryEntryBase<TAccent extends string> {
  readonly id: string;
  readonly name: string;
  readonly route: string;
  readonly accent: TAccent;
  readonly icon: string;
  readonly order: number;
  readonly description?: string;
}

/** What the generated registry file exports. */
export interface GeneratedRegistry<TExtra extends object = Record<never, never>, TAccent extends string = AppAccent> {
  readonly MODULES: readonly RegistryEntry<TExtra, TAccent>[];
  /** Module id to icon name, with the fallback already applied. */
  readonly ICONS: Readonly<Record<string, string>>;
  readonly FALLBACK_ICON: string;
}

/** One entry in the module's rail. Display only: the module's server enforces access. */
export interface ModuleRailEntry {
  key: string;
  label: string;
  /** Route inside the module's own router. */
  route: string;
  icon?: string | undefined;
  hue?: NavHue | undefined;
  /** Permission names the module's own check reads. Empty or absent shows to everyone signed in. */
  requires?: readonly string[] | undefined;
}

/** A feed the hub reads for this module: plain data rows, never markup. */
export interface ModuleFeedSource {
  key: string;
  label: string;
  /** Shown only when the person holds the permission it names. */
  requires?: string | undefined;
  load: () => Promise<readonly HomeItem[]>;
}

/**
 * What a module exports. `TRoutes` is the router's own route table type, so the kit does not
 * depend on a router. The id equals the manifest's.
 */
export type ModuleDescriptor<TRoutes = unknown, TExtra extends object = Record<never, never>, TAccent extends string = AppAccent> = ModuleDescriptorBase<TRoutes, TAccent> & TExtra;

interface ModuleDescriptorBase<TRoutes, TAccent extends string> {
  id: string;
  name: string;
  routes: TRoutes;
  rail: readonly ModuleRailEntry[];
  /** The module's own permission check, applied to each rail entry before it shows. */
  canSee: (entry: ModuleRailEntry) => boolean;
  accent: TAccent;
  icon: string;
  /** Announcements for the strip, most severe first is applied by the kit. */
  banner?: (() => Promise<readonly Announcement[]>) | undefined;
  feeds?: readonly ModuleFeedSource[] | undefined;
}

/**
 * The host hook (`configureHost`) through which the shell hands a module the shared sign-in
 * client. The first call wins and later calls are ignored, so a module never imports the shell.
 */
export type ConfigureHost<THost = unknown> = (host: THost) => void;
