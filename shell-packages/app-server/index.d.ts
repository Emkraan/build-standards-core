// Type declarations for shell-packages/app-server (hand-authored so CommonJS servers on
// moduleResolution "node" type-check it, the same as shell-packages/rbac).
export type GroupCacheStatus = "hit" | "miss" | "shared" | "error" | "none";

export interface GroupResolverOptions {
  /**
   * Return the user's group ids. null, undefined or a throw means the lookup failed.
   * With groupIds set, it is called with the referenced ids and should answer
   * only which of them the user is in (checkMemberGroups does that).
   */
  fetchGroups: (oid: string, groupIds?: string[]) => Promise<string[] | null | undefined>;
  /**
   * The group object ids the app's authorization references (a list, or a
   * function that returns one). A function is read on every
   * lookup (one read shared by concurrent lookups), the cache entry is tied to
   * a fingerprint of the list, so a new group grant takes effect on the next
   * request. null, undefined or a throw falls back to the last good list for
   * at most ttlMs, then fails the lookup closed (not cached). An empty list returns [] with no
   * Graph call.
   */
  groupIds?: string[] | (() => Promise<string[] | null | undefined> | string[] | null | undefined);
  /** Default 300000 (5 minutes). */
  ttlMs?: number;
  /** Default 5000. */
  maxEntries?: number;
  now?: () => number;
  onError?: (err: unknown, oid: string) => void;
}

export interface GroupResolver {
  lookup(oid: unknown, opts?: { fresh?: boolean }): Promise<{ groups: string[]; cache: GroupCacheStatus }>;
  resolve(oid: unknown, opts?: { fresh?: boolean }): Promise<string[]>;
  invalidate(oid: unknown): void;
  clear(): void;
  readonly size: number;
}

/** Trimmed, lowercased, de-duplicated and sorted ids. */
export declare function normalizeGroupIds(ids: unknown): string[];

export interface CheckMemberGroupsOptions {
  oid: string;
  groupIds: string[];
  getToken: () => Promise<string | null | undefined>;
  /** Default the global fetch. Any fetch that honours init.signal works (node-fetch 2 does). */
  fetch?: (url: string, init: any) => Promise<{ ok: boolean; status: number; json: () => Promise<any>; headers?: any }>;
  /** Called on a Graph 401 so the app can drop its cached token. */
  onUnauthorized?: () => void;
  /** Per Graph call. Default 10000. */
  timeoutMs?: number;
  /** Ids per call, at most 20 (the Graph limit). Default 20. */
  batchSize?: number;
  /** Batches in flight at once. Default 4. */
  concurrency?: number;
  log?: (message: string) => void;
}

/**
 * Which of groupIds the object is a member of (transitive), batched 20 ids per
 * Graph call, at most `concurrency` calls in flight. Ids that are not object
 * ids are skipped, a batch rejected with 400 is asked one id at a time (a
 * rejected id is not a member), a 429 is retried once. [] when no valid id is left (no Graph
 * call), null when any part of the lookup failed. Never throws.
 */
export declare function checkMemberGroups(options: CheckMemberGroupsOptions): Promise<string[] | null>;

export declare function createGroupResolver(options: GroupResolverOptions): GroupResolver;

export declare function parseExpiresOn(raw: unknown, now?: () => number): number;

export interface TokenCache {
  get(): Promise<string | null>;
  clear(): void;
}

export declare function createTokenCache(options: {
  fetchToken: () => Promise<{ token: string; expiresAt: number } | null | undefined>;
  refreshSkewMs?: number;
  now?: () => number;
}): TokenCache;

export interface CorsOptionsInput {
  allowedOrigins: string[];
  /** "omit" answers with no CORS headers (cb(null, false)), "error" passes an Error to next. */
  reject?: "omit" | "error";
  methods?: string[];
  allowedHeaders?: string[];
  exposedHeaders?: string[];
  /** Seconds. Default 7200. */
  maxAge?: number;
}

export interface CorsOptionsOutput {
  origin: (origin: string | undefined, cb: (err: Error | null, allow?: boolean) => void) => void;
  credentials: false;
  methods: string[];
  allowedHeaders: string[];
  exposedHeaders?: string[];
  maxAge: number;
}

export declare function corsOptions(options: CorsOptionsInput): CorsOptionsOutput;

export interface TimingMark { name: string; dur: number; desc?: string }

export interface RequestLogRecord {
  msg: "request";
  method: string;
  route: string;
  status: number;
  ms: number;
  timings: Record<string, number>;
  desc?: Record<string, string>;
  aborted?: boolean;
}

export declare function recordTiming(req: unknown, name: string, durMs: number, desc?: string): void;
export declare function timed<T>(req: unknown, name: string, fn: () => Promise<T> | T): Promise<T>;
export declare function formatServerTiming(marks: TimingMark[], totalMs: number): string;

export declare function originGuard(options: { allowedOrigins: string[]; preflightHeaders?: string[] }): (req: any, res: any, next: (err?: unknown) => void) => void;

export declare function parseSettingString(raw: unknown): Record<string, string>;


export type WhatsNewLabel = "New features" | "Security improvements" | "Bug fixes" | "Faster performance" | "Maintenance and reliability";
export interface WhatsNewRelease { version: string; labels: WhatsNewLabel[]; highlight?: string }
export declare const WHATS_NEW_LABELS: readonly WhatsNewLabel[];
export declare function whatsNewNotes(notes: unknown, moduleId: string): { releases: WhatsNewRelease[]; changelog: string | null };
/** GET handler for one tool's release notes behind the tool's own entry check (allow). */
export declare function whatsNewHandler(options: { notes: unknown; moduleId: string; allow: (req: any) => boolean | Promise<boolean> }): (req: any, res: any) => Promise<unknown>;
export declare function safeMessage(err: unknown): string;
/** True when serverTiming resolved the route from the app's route definitions. */
export declare function isDeclaredRoute(route: string): boolean;
/** The declared path of an Express 4 mount layer, proven by recompiling it ("" for a root mount), or null. */
export declare function mountTemplateOf(layer: unknown): string | null;


export declare function serverTiming(options?: {
  timingAllowOrigins?: string[];
  headerForAll?: boolean;
  log?: ((line: string) => void) | null;
  sink?: ((record: RequestLogRecord) => void) | null;
  skip?: (req: any) => boolean;
  /** Also store the request's timing record under Symbol.for(timingKey), for a shell whose own code reads that key. */
  timingKey?: string;
}): (req: any, res: any, next: (err?: unknown) => void) => void;

export interface RequestTelemetryOptions {
  /** require() the client from the app: { exporter, traceBase, resources }. Called only when enabled. */
  load: () => { exporter: any; traceBase: any; resources: any };
  /** App Insights cloud role name. Default WEBSITE_SITE_NAME. */
  roleName?: string;
  roleVersion?: string;
  /** Default APPLICATIONINSIGHTS_CONNECTION_STRING. */
  connectionString?: string;
  /** Default APPLICATIONINSIGHTS_AUTHENTICATION_STRING. Must be Authorization=AAD. */
  authenticationString?: string;
  /** Token source for https://monitor.azure.com/. Default: App Service managed identity. */
  getToken?: (resource: string, clientId?: string) => Promise<{ token: string; expiresAt: number } | null>;
  log?: (line: string) => void;
  exporterOptions?: Record<string, unknown>;
  now?: () => number;
  /** Delays before each retry of a batch that failed with a transient error. Default [2000, 5000, 10000]. */
  retryDelaysMs?: number[];
  /** Most spans waiting for a retry at once, oldest dropped first. Default 2000. */
  maxBufferedSpans?: number;
  /** A token request that has not answered by then counts as no token. Default 10000. */
  tokenTimeoutMs?: number;
}

export interface RequestTelemetry {
  enabled: boolean;
  reason?: string;
  /** Pass to serverTiming({ sink }). null when disabled. */
  sink: ((record: RequestLogRecord) => void) | null;
  flush(): Promise<void>;
  close(): Promise<void>;
}

/** True when nothing of a failed export can have reached ingestion: a token or identity failure, a refused connection or unresolved name, or a 429 / 503 answer. */
export declare function isTransientExportFailure(result: unknown): boolean;

export interface ExportRetryOptions {
  /** Sends one batch, resolving with the exporter's first result ({ code, error }). */
  send: (spans: any[]) => Promise<any>;
  log: (line: string) => void;
  now?: () => number;
  /** Default [2000, 5000, 10000]: one retry after each delay, then the batch is dropped. */
  delaysMs?: number[];
  /** Default 2000. */
  maxBuffered?: number;
  /** One outcome line per event and reason per window. Default 5 minutes. */
  logIntervalMs?: number;
  /** A retry send that never answers counts as failed after this. Default 30000. */
  sendTimeoutMs?: number;
  /** Called for a failure that is not transient (not retried). */
  onFailure?: (spans: any[], result: any) => void;
}

export interface ExportRetry {
  /** Exporter-shaped export: done is called once, at once, with the first result. */
  export(spans: any[], done: (result: any) => void): void;
  /** Stop keeping new failures and make one last attempt for every waiting batch, each bounded by timeoutMs (default 1500). */
  drain(timeoutMs?: number): Promise<void>;
  /** Cancel timers, drop what still waits, log held counts. */
  stop(): void;
  stats(): { buffered: number; batches: number; inFlight: number; retried: number; dropped: number };
}

/** Bounded retry for span batches whose export failed with a transient error. */
export declare function createExportRetry(options: ExportRetryOptions): ExportRetry;

/** Sets APPLICATIONINSIGHTS_STATSBEAT_DISABLED=true for the process when enabled, unless already set. */
export declare function requestTelemetry(options: RequestTelemetryOptions): RequestTelemetry;

/**
 * Close (flush) telemetry on SIGTERM / SIGINT within timeoutMs (default 3000), then let the
 * signal exit the process as before. A no-op when telemetry is off. Returns an unregister function.
 */
export declare function closeTelemetryOnShutdown(
  telemetry: RequestTelemetry,
  options?: { signals?: NodeJS.Signals[]; timeoutMs?: number; exit?: (signal: NodeJS.Signals) => void },
): () => void;

// --- Gateway guard ---

/** Live binding: the preset header (the core's own, "x-gateway-token", until a preset is applied). */
export declare let GATEWAY_HEADER: string;

/** One place a shell names itself: read by every gateway function, the telemetry defaults and the timing key. */
export interface ConsumerPreset {
  /** Header the gateway puts its token in (lower case). */
  header: string;
  /** App role the gateway token must carry. An empty string skips the role check. */
  role: string;
  /** Request property set next to req.gateway. */
  requestProperty: string;
  /** Body message of the gateway 403. */
  refusalMessage: string;
  /** Names of the settings the guard reads from env. */
  settings: { enforce: string; principalId: string; audience: string; tenantId: string };
  /** Default service.name when neither roleName nor WEBSITE_SITE_NAME is set. */
  serviceName: string;
  /** Tracer scope name. */
  tracerScope: string;
  /** Base name of the Symbol.for key the request timing is stored under. */
  timingKey: string;
}
export declare const CONSUMER_PRESET_DEFAULTS: Readonly<ConsumerPreset>;
/** Set the preset once at startup. Fields left out keep the core default; each call replaces the previous preset. Per-call options still override it. */
export declare function setConsumerPreset(
  preset?: Partial<Omit<ConsumerPreset, "settings">> & { settings?: Partial<ConsumerPreset["settings"]> },
): Readonly<ConsumerPreset>;
export declare function getConsumerPreset(): Readonly<ConsumerPreset>;
/** True once setConsumerPreset has been called. gatewayGuard throws without it unless enforce is passed. */
export declare function isConsumerPresetApplied(): boolean;
/** Back to the core defaults and not applied (tests). */
export declare function resetConsumerPreset(): void;
export declare const GATEWAY_EXEMPT_PATHS: readonly string[];
export declare const GATEWAY_PLATFORM_PING_PATHS: readonly string[];
/** Live binding: the preset role (the core's own, "gateway", until a preset is applied). */
export declare let GATEWAY_ROLE: string;

export interface SigningKeySource {
  /** A key, null for an unknown key id, undefined when the keys cannot be read. */
  get(kid: string): Promise<import("node:crypto").KeyObject | null | undefined>;
  /** Start the first key read without waiting for it. Optional. */
  warm?(): void;
}

export declare function parseGatewayEnforce(raw: unknown): boolean;
export declare function gatewayAudiences(raw: string | string[] | undefined | null): string[];
export declare function createSigningKeyCache(options: {
  tenantId: string;
  fetchKeys?: (url: string) => Promise<any>;
  ttlMs?: number;
  minRefetchMs?: number;
  now?: () => number;
}): SigningKeySource & { warm(): void };

export interface GatewayVerifyResult {
  ok: boolean;
  reason?: string;
}

export declare function verifyGatewayToken(
  token: string | undefined,
  cfg: { tenantId: string; principalId: string; audiences: string[]; keys: SigningKeySource; role?: string; nowSeconds?: number },
): Promise<GatewayVerifyResult>;

/**
 * Read the gateway header and remove it from req.headers and req.rawHeaders (any case).
 * The header name defaults to the preset header.
 */
export declare function takeGatewayHeader(req: any, header?: string): string | undefined;

export interface GatewayGuardOptions {
  env?: Record<string, string | undefined>;
  enforce?: boolean | string;
  principalId?: string;
  audience?: string | string[];
  tenantId?: string;
  exempt?: readonly string[];
  /** Paths whose unauthenticated GET or HEAD refusals log as platform_ping. */
  platformPingPaths?: readonly string[];
  keys?: SigningKeySource;
  fetchKeys?: (url: string) => Promise<any>;
  log?: (line: string) => void;
  now?: () => number;
  logIntervalMs?: number;
  /** Header the gateway puts its token in. Default the preset header. It is stripped from the request whatever the settings. */
  header?: string;
  /** App role the token must carry. Default the preset role. An empty string skips the role check. */
  role?: string;
  /** Request property that carries { ok, reason } once checked, set next to req.gateway. Default the preset request property. */
  requestProperty?: string;
  /** Body message of the 403. Default the preset message. */
  refusalMessage?: string;
}

export declare function gatewayGuard(
  options?: GatewayGuardOptions,
): (req: any, res: any, next: (err?: unknown) => void) => void;
