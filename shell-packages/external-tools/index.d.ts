// Types for shell-packages/external-tools.
export const HUES: readonly string[];
export const ID_RE: RegExp;
export const UUID_RE: RegExp;
export const ORDER_MAX: number;
export const MAX_TOOLS: number;
export class Invalid extends Error {
  constructor(field: string, message: string);
  field: string;
}
export type Audience =
  | { kind: "group"; groupId: string; groupLabel: string | null }
  | { kind: "permission"; permission: string };
export interface ToolInput {
  id: string; name: string; url: string; icon: string; hue: string; tagline: string; description: string;
  order: number; enabled: boolean; audience: Audience;
}
export interface Tool extends Omit<ToolInput, "audience"> {
  audience: Audience;
  createdBy: string | null; createdAt: unknown; updatedBy: string | null; updatedAt: unknown;
}
export interface PublicTool { id: string; name: string; url: string; icon: string; hue: string; tagline: string; description: string; order: number }
/** Throws Invalid with the field the editor highlights. */
export function validateTool(body: unknown, options: { id?: string; permissionIds: Iterable<string>; hues?: readonly string[] }): ToolInput;
export function toTool(row: Record<string, any>): Tool;
export function publicTool(tool: Tool): PublicTool;
export function auditShape(tool: Tool | null): Omit<Tool, "createdAt" | "updatedAt"> | null;
export function visibleTools(
  tools: Tool[],
  options: {
    callerGroups: (wanted: string[]) => Promise<Set<string>>;
    callerHasPermission: (permission: string) => Promise<boolean>;
    log?: Pick<Console, "error">;
  },
): Promise<PublicTool[]>;
export interface Q { query(text: string, params?: unknown[]): Promise<{ rows: any[] }> }
export interface ExternalToolRoutesOptions {
  db: Q;
  audit: { transaction: (work: (client: any, record: (...args: any[]) => Promise<unknown>) => Promise<any>) => Promise<any> };
  /** The gate for every admin route. */
  manage: Function;
  caller: (req: any) => { email?: string | null };
  /** The console permissions an audience may name (the registry). */
  permissions: () => Array<{ id: string; label?: string }>;
  callerGroups: (req: any, wanted: string[]) => Promise<Set<string>>;
  callerHasPermission: (req: any, permission: string) => Promise<boolean>;
  log?: Pick<Console, "error">;
}
export function externalToolRoutes(router: { get: Function; post: Function; put: Function; delete: Function }, options: ExternalToolRoutesOptions): void;
