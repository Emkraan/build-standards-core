// Types for shell-packages/health.
export interface SwrReading<T> {
  value: T | null;
  /** When the reading was taken (ms since the epoch), or null before the first one. */
  at: number | null;
  ageMs: number | null;
  refreshing: boolean;
  lastError: string | null;
}
export interface SwrReaderOptions<T> {
  read: () => Promise<T>;
  /** How old a reading may be before a get triggers a refresh (default 30000). */
  staleMs?: number;
  now?: () => number;
  log?: Pick<Console, "error">;
  onError?: (error: unknown) => void;
}
export interface SwrReader<T> {
  get(): SwrReading<T>;
  refresh(): Promise<void>;
}
export function createSwrReader<T>(options: SwrReaderOptions<T>): SwrReader<T>;
export interface HealthRouteOptions {
  version: string;
  /** Each check answers { ok, ... }; a throw counts as down. Any not ok makes the status degraded (503). */
  critical: Record<string, () => Promise<{ ok: boolean; [k: string]: unknown }>>;
  /** Readings that never change the status. */
  info?: Record<string, () => Record<string, unknown>>;
  env?: Record<string, string | undefined>;
  path?: string;
  log?: Pick<Console, "error">;
}
export function healthRoute(router: { get: Function }, options: HealthRouteOptions): void;
