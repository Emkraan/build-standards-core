// The Live tab of the Action Center: what is acting right now, from feeds that already exist. Two sources are merged into one list,
// the tackle sessions that are live (a chat I started from an item) and the consumer's active builds feed when it has one.
// The decisions are here so a test can load them without the browser (issue 308, item 5). Read only on purpose.

import type { ActiveBuild, ActiveBuildsState } from './activeBuilds'
import type { TackleSession } from './data'

export interface LiveRow {
  /** Stable key across both sources. */
  id: string
  kind: 'session' | 'build'
  title: string
  /** running, stuck or failed for a build, launching or running for a session. */
  state: string
  /** Epoch seconds of the last sign of life, or null when the source gave none. */
  since: number | null
  /** The ticket key a session works, when it has one. */
  ticket: string | null
  /** An http or https address only, never anything else. */
  url: string | null
}

export type LiveMode = 'loading' | 'error' | 'list' | 'quiet'

const SECONDS = (iso: string | undefined): number | null => {
  if (!iso) return null
  const ms = Date.parse(iso)
  return Number.isNaN(ms) ? null : Math.floor(ms / 1000)
}

/** A session is acting while it is opening or running. A finished, failed or resolved one is history and is left out. */
export function liveSessions(sessions: Record<string, TackleSession> | null | undefined): LiveRow[] {
  return Object.entries(sessions ?? {})
    .filter(([, s]) => s.live === true && !s.archived && (s.state === 'launching' || s.state === 'claimed' || s.state === 'running'))
    .map(([fp, s]) => ({
      id: `session:${fp}`,
      kind: 'session' as const,
      title: s.title || fp,
      state: s.state === 'running' ? 'running' : 'launching',
      since: SECONDS(s.last_active) ?? SECONDS(s.started),
      ticket: s.ticket ?? null,
      url: null,
    }))
}

/** A build is acting while it is running or stuck. A failed one needs a look but is not acting, and a finished one is history. */
export function liveBuilds(feed: ActiveBuildsState | null | undefined): LiveRow[] {
  if (!feed || !feed.configured || feed.error) return []
  return feed.builds
    .filter((b: ActiveBuild) => b.state === 'running' || b.state === 'stuck')
    .map((b) => ({
      id: `build:${b.id}`,
      kind: 'build' as const,
      title: b.title,
      state: b.state,
      since: b.activity_at ?? b.started,
      ticket: null,
      url: b.url !== null && /^https?:\/\//.test(b.url) ? b.url : null,
    }))
}

/** Stuck first, then the rest by most recent sign of life. A row with no time sorts after the ones that have one. */
export function liveRows(sessions: Record<string, TackleSession> | null | undefined, feed: ActiveBuildsState | null | undefined): LiveRow[] {
  const rows = [...liveBuilds(feed), ...liveSessions(sessions)]
  return rows
    .map((r, i) => ({ r, i }))
    .sort((a, b) => Number(b.r.state === 'stuck') - Number(a.r.state === 'stuck') || (b.r.since ?? -1) - (a.r.since ?? -1) || a.i - b.i)
    .map((x) => x.r)
}

/**
 * What the tab does. A builds source that failed is an error and never a calm board, because nothing acting and unable to tell are
 * different answers. A builds provider that is not configured is simply not a source, and the sessions alone decide.
 */
export function liveMode(
  sessions: Record<string, TackleSession> | null | undefined,
  feed: ActiveBuildsState | null | undefined,
  feedLoaded: boolean,
): LiveMode {
  if (sessions === null || sessions === undefined || !feedLoaded) return 'loading'
  if (feed && feed.configured && feed.error) return 'error'
  return liveRows(sessions, feed).length > 0 ? 'list' : 'quiet'
}

/** The count for the tab: what is acting, as the rows say. Zero draws no badge. */
export function liveCount(sessions: Record<string, TackleSession> | null | undefined, feed: ActiveBuildsState | null | undefined): number {
  return liveRows(sessions, feed).length
}
