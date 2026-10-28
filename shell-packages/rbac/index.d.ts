// Type declarations for the RBAC core (hand-authored so CommonJS servers on moduleResolution
// "node" and bundler-resolved clients both type-check it).

export declare const WILDCARD: "*";

export interface RegistryEntry { id: string; label?: string; tab?: string; product?: string }
export interface Registry { tabs: RegistryEntry[]; actions: RegistryEntry[] }
export interface Subject { callerPermissions: Iterable<string>; callerIsWildcard: boolean; registry: Registry }
export interface RoleLike { id: string | number; permissions?: unknown; assignable?: boolean }

export declare function toPermissionList(value: unknown): string[];
export declare function registryIds(registry: Registry): string[];
export declare function expandPermissions(perms: unknown, registry: Registry): Set<string>;
export declare function accessibleTabs(perms: unknown, registry: Registry): string[];
export declare function permissionsBeyond(args: { requested: unknown; callerPermissions: Iterable<string>; callerIsWildcard: boolean; registry: Registry }): string[];
export declare function grantCeilingMessage(beyond: string[]): string;
export declare function viewAsCeilingMessage(beyond: string[]): string;
export declare function assignableRoleIds<R extends RoleLike>(roles: R[], subject: Subject): string[];
export declare function annotateRoles<R extends RoleLike>(roles: R[], caller: Subject): Array<R & { assignable: boolean; unknownPermissions: string[] }>;
export declare function grantableIds(caller: Subject): string[];
export declare function viewAsPreview(args: {
  subjectPermissions: Iterable<string>;
  subjectIsWildcard: boolean;
  caller: { callerPermissions: Iterable<string>; callerIsWildcard: boolean };
  registry: Registry;
  roles: Array<{ id: string | number; permissions?: unknown }>;
}): { beyond: string[]; permissions: string[]; tabs: string[]; assignableRoleIds: string[]; grantable: string[] };
export declare function stripRetiredPermissions(perms: unknown, retired: string[], registry: Registry): string[] | null;
export declare function findPermissionLiterals(source: string): string[];
export declare function filterRegistry<T extends { tabs?: Array<{ id: string }>; actions?: Array<{ id: string }> }>(registry: T, grantable: string[] | null | undefined): T & { tabs: NonNullable<T["tabs"]>; actions: NonNullable<T["actions"]> };
export declare function activeGrantable(registryResponse: { grantable?: string[] | null } | null | undefined, impersonating: object | null | undefined): string[] | null;
export declare function createAccess(source: { permissions?: string[] | null; tabs?: string[] | null } | null | undefined): {
  hasPermission: (id: string) => boolean;
  hasTab: (tabId: string) => boolean;
};
export declare function canAssignRole(role: { id: string | number; assignable?: boolean }, impersonating: object | null | undefined): boolean;
export declare function canGrantPermission(id: string, registryResponse: { grantable?: string[] | null } | null | undefined, impersonating: object | null | undefined): boolean;
