// Types for shell-packages/route-conformance. Every check answers a list of problem strings, empty when it conforms.
export const DEFAULT_GATE: RegExp;
export interface RouteRow { key: string; args: string }
export function routeTable(routesDir: string, options?: { router?: string; ext?: string[] }): { table: RouteRow[]; declared: number };
export function checkRoutes(options: { routesDir: string; allow?: Record<string, string>; gate?: RegExp; router?: string; minRoutes?: number }): string[];
export function checkGates(table: RouteRow[], file: string, expected: Record<string, RegExp | null>): string[];
export function checkAuthOrder(options: { indexSource: string; authMount?: string; publicPaths?: string[]; prefix?: string }): string[];
export function checkNoLiteralKeys(dirs: string[]): string[];
export function checkNoErrorDetail(file: string): string[];
