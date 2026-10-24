export interface RegistryOptions {
  manifests: string[];
  out: string;
  check: boolean;
  root: string;
  fallbackIcon: string;
  types: string;
  accents: string;
  extraAccents: string[];
  allowKeys: string[];
  validateWith: string;
}
export interface ManifestEntry {
  label: string;
  manifest: Record<string, unknown> & { id: string };
}
export interface ManifestContext {
  label: string;
  dir: string;
  root: string;
}
export type ManifestValidator = (manifest: Record<string, unknown> & { id: string }, context: ManifestContext) => readonly string[] | void | undefined;
export interface Io {
  out(line: string): void;
  err(line: string): void;
}
export function parseArgs(argv: string[]): RegistryOptions;
export function expandGlob(root: string, pattern: string): string[];
export function loadAccents(explicit?: string): string[] | null;
export function isAllowedKey(key: string, allowKeys?: readonly string[]): boolean;
export function jsonType(values: readonly unknown[]): string;
export function validateManifest(m: unknown, label: string, accents?: string[] | null, options?: { allowKeys?: readonly string[] }): string[];
export function validateRegistry(entries: ManifestEntry[]): string[];
export function readManifests(root: string, patterns: string[], accents?: string[] | null, options?: { allowKeys?: readonly string[]; validate?: ManifestValidator | undefined }): { entries: ManifestEntry[]; errors: string[] };
export function buildRegistry(entries: ManifestEntry[], options?: { fallbackIcon?: string; types?: string; extraAccents?: readonly string[] }): string;
export function run(argv: string[], io?: Io, hooks?: { validate?: ManifestValidator | undefined }): number;
export function runCli(argv: string[], io?: Io): Promise<number>;
