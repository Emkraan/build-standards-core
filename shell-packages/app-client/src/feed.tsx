/* ConsoleFeed: the live feed strip every console shows under its header. It reads the platform
   feed (estate health and announcements) from the console API, merges the module's own items and
   renders the kit FeedStrip with the mascot. The health line comes from the module's own health
   endpoint and the platform feed, so it is always there even when one of them is down. */

import { useMemo } from 'react';
import type { ReactNode } from 'react';
import { FeedStrip, safeHref } from '@build-standards/kit';
import type { FeedItem, FeedTone, HealthLine, HealthStatus } from '@build-standards/kit';
import type { Api } from './api';
import { useResource } from './useResource';
import { defaultStore } from './cache';

export interface FeedEntry {
  id: string;
  tone: FeedTone;
  title: string;
  body?: string | undefined;
  /** Same-origin path ("/estate") or https URL. Anything else renders as plain text. */
  href?: string | undefined;
}

/** GET /api/feed on the console API. */
export interface PlatformFeed {
  health: HealthLine;
  items: FeedEntry[];
}

/** Poll interval for the feed and the module health. */
export const FEED_POLL_MS = 60_000;
/** A mount within this window reuses the last answer (route changes do not refetch). */
export const FEED_FRESH_MS = 30_000;
/** At most this many items rotate in the strip. */
export const FEED_MAX_ITEMS = 12;

const TONES: readonly FeedTone[] = ['critical', 'warning', 'info', 'success'];
const STATUSES: readonly HealthStatus[] = ['ok', 'degraded', 'down', 'unknown'];
const RANK: Record<HealthStatus, number> = { ok: 0, unknown: 1, degraded: 2, down: 3 };

function isTone(v: unknown): v is FeedTone {
  return typeof v === 'string' && (TONES as readonly string[]).includes(v);
}

/** Read a health body in either estate shape ({ status } or { ok }). */
export function healthStatusOf(body: unknown): HealthStatus {
  if (!body || typeof body !== 'object') return 'unknown';
  const b = body as { status?: unknown; ok?: unknown };
  if (b.status === 'ok' || b.status === 'healthy') return 'ok';
  if (b.status === 'degraded') return 'degraded';
  if (b.status === 'down' || b.status === 'error') return 'down';
  if (typeof b.ok === 'boolean') return b.ok ? 'ok' : 'degraded';
  return 'unknown';
}

/** Validate a platform feed payload. Unknown tones and malformed items are dropped. */
export function parseFeed(raw: unknown): PlatformFeed | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as { health?: { status?: unknown; label?: unknown }; items?: unknown };
  const status = (STATUSES as readonly unknown[]).includes(r.health?.status) ? (r.health?.status as HealthStatus) : 'unknown';
  const label = typeof r.health?.label === 'string' ? r.health.label : '';
  const items: FeedEntry[] = [];
  if (Array.isArray(r.items)) {
    for (const it of r.items) {
      if (!it || typeof it !== 'object') continue;
      const o = it as Record<string, unknown>;
      if (typeof o['id'] !== 'string' || typeof o['title'] !== 'string' || !isTone(o['tone'])) continue;
      items.push({
        id: o['id'],
        tone: o['tone'],
        title: o['title'],
        body: typeof o['body'] === 'string' ? o['body'] : undefined,
        href: typeof o['href'] === 'string' ? o['href'] : undefined,
      });
    }
  }
  return { health: { status, label }, items };
}

/**
 * The one health line. The worst of the module's own health and the platform wins. A module that
 * cannot reach its own API says so, because that is what the person in front of it needs.
 */
export function mergeHealth(
  app: string,
  module: { status: HealthStatus; failed: boolean } | null,
  platform: HealthLine | null,
): HealthLine {
  if (module?.failed || module?.status === 'down') return { status: 'down', label: `${app} API unreachable, retrying` };
  if (module?.status === 'degraded') {
    const platformWorse = platform && RANK[platform.status] > RANK.degraded;
    return platformWorse ? platform : { status: 'degraded', label: `${app} reports degraded service` };
  }
  if (platform && platform.status !== 'unknown' && platform.label) {
    // A module that answered with an unknown status (or a 401) defers to the platform line.
    if (!module || module.status === 'ok' || module.status === 'unknown' || RANK[platform.status] >= RANK[module.status]) return platform;
  }
  if (module?.status === 'ok') return { status: 'ok', label: `${app} online` };
  return { status: 'unknown', label: 'Checking status' };
}

/** Platform and module items, most severe first, platform before module on a tie, unique ids, capped. */
export function mergeItems(platform: readonly FeedEntry[], module: readonly FeedEntry[]): FeedEntry[] {
  const seen = new Set<string>();
  const all: Array<{ e: FeedEntry; order: number }> = [];
  let order = 0;
  for (const e of [...platform, ...module]) {
    if (seen.has(e.id)) continue;
    seen.add(e.id);
    all.push({ e, order: order++ });
  }
  all.sort((a, b) => TONES.indexOf(a.e.tone) - TONES.indexOf(b.e.tone) || a.order - b.order);
  return all.slice(0, FEED_MAX_ITEMS).map((x) => x.e);
}

export interface UseConsoleFeedOptions {
  /** The module's display name, used in the health line ("Example Shell API unreachable"). */
  app: string;
  /**
   * The console API client. null when the feed is not configured (local dev): the module health
   * still shows. The feed read is always a side read (on401 "throw"), so a poll never navigates.
   */
  consoleApi: Api | null;
  /**
   * The module's own API client. The feed polls its health route as a side read (on401 "throw"),
   * so the poll never starts a sign-in or a redirect, whatever the client's on401. null or
   * omitted: no module health, the line follows the platform feed.
   */
  toolApi?: Api | null | undefined;
  /** The health route under the module API's base. Default "/health". */
  toolHealthPath?: string | undefined;
  /** The module's own items (connector state, alerts). */
  items?: readonly FeedEntry[] | undefined;
  interval?: number | undefined;
  enabled?: boolean | undefined;
}

export interface ConsoleFeedState {
  health: HealthLine;
  items: FeedEntry[];
  platform: PlatformFeed | null;
}

const NO_ITEMS: readonly FeedEntry[] = Object.freeze([]);
/**
 * Store key of the platform feed side read. Apart from an interactive '/feed' resource, and still
 * under the '/feed' prefix so invalidate('/feed') refreshes the strip too.
 */
export const FEED_SIDE_KEY = '/feed#side';

export function useConsoleFeed({
  app,
  consoleApi,
  toolApi,
  toolHealthPath = '/health',
  items = NO_ITEMS,
  interval = FEED_POLL_MS,
  enabled = true,
}: UseConsoleFeedOptions): ConsoleFeedState {
  const feed = useResource<unknown>(
    // Its own key, so an interactive useApiResource(consoleApi, '/feed') never shares a fetch
    // with this side read (the store dedupes by key only).
    consoleApi ? FEED_SIDE_KEY : null,
    // A background poll must never start a sign-in or a redirect, whatever the client's on401.
    () => (consoleApi as Api).request('/feed', { on401: 'throw' }),
    { store: consoleApi?.store ?? defaultStore, ttl: FEED_FRESH_MS, refreshInterval: interval, enabled },
  );
  const module = useResource<unknown>(
    toolApi ? `feed:${app}:health` : null,
    // A side read as well: a background health poll never signs in or navigates.
    () => (toolApi as Api).request(toolHealthPath, { on401: 'throw' }),
    // In the console API's store when there is one, so a logout or account change drops it too.
    // Without one (local dev) it sits in defaultStore, which no session owns. It is only a status.
    { store: consoleApi?.store ?? defaultStore, ttl: FEED_FRESH_MS, refreshInterval: interval, enabled },
  );

  const platform = useMemo(() => parseFeed(feed.data), [feed.data]);
  const toolState = useMemo(() => {
    if (!toolApi) return null;
    if (module.data === undefined && module.error === undefined) return null;
    // A failed fetch counts until a fetch succeeds, also while the next retry runs, so the line
    // does not flicker back to "Checking status" on every poll.
    if (module.error !== undefined) {
      const status = (module.error as { status?: number })?.status;
      // An HTTP answer with a body (503 degraded) is not unreachable.
      if (status === 503) return { status: 'degraded' as HealthStatus, failed: false };
      // A 401 or 403 means the API answered: the line falls back to the platform status.
      if (status === 401 || status === 403) return { status: 'unknown' as HealthStatus, failed: false };
      return { status: 'down' as HealthStatus, failed: true };
    }
    // The API answered 2xx. A body in neither health shape still means it is up.
    const status = healthStatusOf(module.data);
    return { status: status === 'unknown' ? ('ok' as HealthStatus) : status, failed: false };
  }, [toolApi, module.data, module.error]);

  const health = useMemo(() => mergeHealth(app, toolState, platform?.health ?? null), [app, toolState, platform]);
  const merged = useMemo(() => mergeItems(platform?.items ?? [], items), [platform, items]);
  return { health, items: merged, platform };
}

function opener(href: string | undefined, navigate: ((href: string) => void) | undefined): (() => void) | undefined {
  const safe = safeHref(href);
  if (!safe) return undefined;
  if (safe.startsWith('/') && !safe.startsWith('//') && !safe.startsWith('/\\')) {
    return () => (navigate ? navigate(safe) : window.location.assign(safe));
  }
  if (/^https:\/\//i.test(safe)) return () => void window.open(safe, '_blank', 'noopener,noreferrer');
  return undefined;
}

export interface ConsoleFeedProps extends UseConsoleFeedOptions {
  /** Opens a same-origin href. Pass the router's navigate for in-app paths. Default: a page load. */
  navigate?: ((href: string) => void) | undefined;
  greeting?: ReactNode;
  /** Show the strip's search trigger. Default false: every console header already has one. */
  search?: boolean | undefined;
  label?: string | undefined;
}

export function ConsoleFeed({ navigate, greeting, search = false, label, ...opts }: ConsoleFeedProps) {
  const { health, items } = useConsoleFeed(opts);
  const feedItems: FeedItem[] = useMemo(
    () => items.map((e) => ({ id: e.id, tone: e.tone, title: e.title, body: e.body, onOpen: opener(e.href, navigate) })),
    [items, navigate],
  );
  return <FeedStrip health={health} items={feedItems} greeting={greeting} search={search} label={label} />;
}
