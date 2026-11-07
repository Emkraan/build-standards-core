// Types for shell-packages/audit.
export const ZERO_HASH: string;
export interface AuditActor { email?: string | null; name?: string | null; oid?: string | null }
export interface AuditContext { ip: string | null; userAgent: string | null; requestId: string | null; method: string | null; path: string | null }
export interface AuditEntry {
  id: string; ts: string; schemaVersion: number; actor: AuditActor; action: string; target: string | null; outcome: string;
  context: AuditContext; details: Record<string, unknown>; prevHash?: string | null; hash?: string;
}
export interface AuditWriteOpts { req?: any; outcome?: string; before?: unknown; after?: unknown; changed?: unknown; errorMessage?: string }
export interface AuditQuery { action?: string; actor?: string; outcome?: string; target?: string; startDate?: string; endDate?: string; q?: string }
export interface AuditListResult { items: AuditEntry[]; total: number; page: number; limit: number; pages: number }
export interface AuditVerifyResult {
  ok: boolean; length: number; chainedCount: number; okFromIndex: number | null; firstBreakAt: number | null;
  firstBreakReason: string | null; secretMode: "hmac-sha256" | "sha256-nosecret";
}
export interface AuditRecord { (actor: AuditActor, action: string, target: string | null, details?: Record<string, unknown>, opts?: AuditWriteOpts): Promise<{ id: string; hash: string }> }
export interface AuditOptions {
  db: { query: (text: string, params?: unknown[]) => Promise<{ rows: any[] }>; getClient?: () => Promise<any> };
  env?: Record<string, string | undefined>;
  /** The environment variable that holds the HMAC key (default AUDIT_HMAC_SECRET). */
  hmacEnv?: string;
  /** The caller's address for an entry's context (default: clientPublicIp). */
  clientIp?: (req: any) => string | null;
  log?: Pick<Console, "error">;
}
export interface Audit {
  write(actor: AuditActor, action: string, target: string | null, details?: Record<string, unknown>, opts?: AuditWriteOpts): Promise<{ id: string; hash: string } | null>;
  transaction<T>(work: (client: any, record: AuditRecord) => Promise<T>): Promise<T>;
  list(query?: AuditQuery, page?: { page?: number; limit?: number }): Promise<AuditListResult>;
  listAll(query?: AuditQuery): Promise<AuditEntry[]>;
  count(): Promise<number>;
  stats(opts?: { days?: number }): Promise<Record<string, unknown>>;
  verify(): Promise<AuditVerifyResult>;
  extractContext(req?: any): AuditContext;
  auditHash(canonical: string): string;
  canonicalizeEntry(entry: AuditEntry): string;
  lastChainedHash(q?: { query: AuditOptions["db"]["query"] }): Promise<string>;
}
export function createAudit(options: AuditOptions): Audit;
export function stableStringify(value: unknown): string;
export function canonicalizeEntry(entry: AuditEntry): string;
export function csvCell(value: unknown): string;
export function clientPublicIp(req: any): string | null;
