export declare const ACCENTS: readonly string[];
export declare const HUES: readonly string[];
export declare const RBAC_SHAPES: readonly string[];
export declare const LINK_SLOTS: readonly string[];
export declare const HOME_BLOCKS: readonly string[];
export declare const HOME_MAX_ACTIONS: 4;
export declare const HOME_MAX_FEEDS: 6;
export declare const DESCRIPTION_MAX: 400;

export type Manifest = Record<string, any>;

export declare function isDescription(v: unknown): v is string;
export declare function validateManifest(input: unknown): string[];
export declare function validateRegistry(manifests: unknown[]): string[];
export declare function peerRef(id: string): { module: string; permission: string } | null;
export declare function peerModules(mod: { pages?: ReadonlyArray<{ requires?: readonly string[] }>; groups?: ReadonlyArray<{ items?: ReadonlyArray<{ requires?: readonly string[] }> }> }): string[];
export declare function permissionSourceId(mod: { id: string; rbac?: { permissionSource?: string } }): string;
export declare function ownsPermissions(mod: { id: string; rbac?: { permissionSource?: string } }): boolean;
export declare function canOpen(requires: readonly string[], has: (id: string) => boolean): boolean;
export declare function autoDescription(m: Manifest): string;
