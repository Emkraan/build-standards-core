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
  /** The lane the source named, for the Lane select; null for a session and for a source that names none. */
  lane?: string | null
  /** True for a build that carries a pull request (the Engineer PRs section); a build without one is a scheduled job. */
  hasPr?: boolean
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
      lane: b.lane ?? null,
      hasPr: !!b.pr,
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

/** The states of the Work by state control, in reading order. */
export const LIVE_STATES = ['needs', 'running', 'waiting', 'stuck', 'finished'] as const
export type LiveState = (typeof LIVE_STATES)[number]
export const LIVE_STATE_LABEL: Record<LiveState, string> = {
  needs: 'Needs me',
  running: 'Running',
  waiting: 'Waiting',
  stuck: 'Stuck',
  finished: 'Just finished',
}

/**
 * Every row of both sources with the state the control files it under: a failed build needs me, a running build or session is running,
 * a session that is still opening is waiting, a stuck build is stuck, a finished build just finished. The Live tab badge keeps counting
 * only what is acting (liveCount); the failed and finished rows are history the control can show on request.
 */
export function liveByState(
  sessions: Record<string, TackleSession> | null | undefined,
  feed: ActiveBuildsState | null | undefined,
): Record<LiveState, LiveRow[]> {
  const out: Record<LiveState, LiveRow[]> = { needs: [], running: [], waiting: [], stuck: [], finished: [] }
  for (const r of liveRows(sessions, feed)) {
    out[r.state === 'stuck' ? 'stuck' : r.state === 'launching' ? 'waiting' : 'running'].push(r)
  }
  if (feed && feed.configured && !feed.error) {
    for (const b of feed.builds) {
      if (b.state !== 'failed' && b.state !== 'finished') continue
      out[b.state === 'failed' ? 'needs' : 'finished'].push({
        id: `build:${b.id}`,
        kind: 'build',
        title: b.title,
        state: b.state,
        since: b.activity_at ?? b.finished ?? b.started,
        ticket: null,
        url: b.url !== null && /^https?:\/\//.test(b.url) ? b.url : null,
        lane: b.lane ?? null,
        hasPr: !!b.pr,
      })
    }
  }
  return out
}

/** The state the control opens on: the first one that has rows, in reading order. */
export function firstLiveState(by: Record<LiveState, LiveRow[]>): LiveState {
  return LIVE_STATES.find((k) => by[k].length > 0) ?? 'running'
}

/** The lanes the rows name, sorted, for the Lane select. No row names one, no select. */
export function liveLanes(rows: LiveRow[]): string[] {
  return [...new Set(rows.map((r) => r.lane).filter((l): l is string => !!l))].sort()
}

/** The rows of one lane (all lanes when `lane` is empty), grouped for the sections: builds with a pull request, builds without one (scheduled jobs), sessions. */
export function liveSections(rows: LiveRow[], lane: string): { prs: LiveRow[]; jobs: LiveRow[]; sessions: LiveRow[] } {
  const kept = lane ? rows.filter((r) => r.lane === lane) : rows
  return {
    prs: kept.filter((r) => r.kind === 'build' && r.hasPr),
    jobs: kept.filter((r) => r.kind === 'build' && !r.hasPr),
    sessions: kept.filter((r) => r.kind === 'session'),
  }
}
