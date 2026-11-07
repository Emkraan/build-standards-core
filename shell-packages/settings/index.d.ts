// Types for shell-packages/settings.
export interface SecretboxOptions {
  /** The domain separation label for the key derivation. Required and fixed: changing it orphans every stored secret. */
  info: string;
  /** The environment variable that holds the master key (default SECRETBOX_MASTER_KEY). */
  masterEnv?: string;
  env?: Record<string, string | undefined>;
}
export interface Secretbox {
  isAvailable(): boolean;
  /** Throws when there is no master key. */
  seal(plaintext: string): string;
  /** Null on any failure (no master, wrong key, tampered or malformed value). */
  open(sealed: unknown): string | null;
}
export function createSecretbox(options: SecretboxOptions): Secretbox;

export interface AppSettingsOptions {
  db: { query: (text: string, params?: unknown[]) => Promise<{ rows: any[] }> };
  /** How long a read is cached (default 30000). */
  ttlMs?: number;
  now?: () => number;
}
export interface AppSettings {
  getSetting(name: string, fallback?: unknown): Promise<unknown>;
  setSetting(name: string, value: unknown, actorEmail?: string | null): Promise<void>;
}
export function createAppSettings(options: AppSettingsOptions): AppSettings;
