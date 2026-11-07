// Types for shell-packages/announcements.
export type Tone = "info" | "success" | "warning" | "critical";
export interface AnnouncementRow {
  id: string; tone: string; title: string; body: string; href: string | null; starts_at: string | Date;
  ends_at: string | Date | null; expired_at: string | Date | null; created_by: string | null; created_at: string | Date;
  updated_by: string | null; updated_at: string | Date;
}
export interface AnnouncementApi {
  id: string; tone: string; title: string; body: string; href: string | null; startsAt: string; endsAt: string | null;
  expiredAt: string | null; createdBy: string | null; createdAt: string; updatedBy: string | null; updatedAt: string;
}
export const TONES: readonly Tone[];
export const TITLE_MAX: number;
export const BODY_MAX: number;
export const HREF_MAX: number;
export const STATE_SQL: string;
export function cleanText(value: unknown): string;
export function cleanHref(value: unknown): { ok: true; value: string | null } | { ok: false; error: string };
export function validate(
  body: Record<string, unknown>,
  options?: { partial?: boolean; current?: AnnouncementRow | null; now?: number },
): { ok: true; value: Record<string, any> } | { ok: false; error: string; field: string };
export function toApi(row: AnnouncementRow): AnnouncementApi;
export function stateOf(row: AnnouncementRow & { state?: string }, now?: number): "live" | "scheduled" | "expired";
export interface Db { query(text: string, params?: unknown[]): Promise<{ rows: any[] }> }
export interface AnnouncementStore {
  /** The announcements whose window is open now, newest start first, capped at 10. Cached briefly. */
  listActive(): Promise<AnnouncementRow[]>;
  /** Drop this instance's cache (a write calls it). */
  invalidate(): void;
}
export function createAnnouncements(options: { db: Db }): AnnouncementStore;
export interface AnnouncementRoutesOptions {
  db: Db;
  audit: { transaction: (work: (client: any, record: (actor: any, action: string, target: string | null, details?: Record<string, unknown>, opts?: any) => Promise<unknown>) => Promise<any>) => Promise<any> };
  store: AnnouncementStore;
  /** The gate for every route, for example the permission check for action:announcements:manage. */
  manage: Function;
  caller: (req: any) => { email?: string | null };
  log?: Pick<Console, "error">;
}
export function announcementRoutes(router: { get: Function; post: Function; put: Function; delete: Function }, options: AnnouncementRoutesOptions): void;
