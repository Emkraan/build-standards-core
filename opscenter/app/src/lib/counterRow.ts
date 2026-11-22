// The Action Center counters row: one tile per thing that needs me, each a link to the page that holds it.
// The decisions live here so a test can load them without the browser (issue 308, item 6).

import type { ActionCounts } from './counts'

export interface CounterTile {
  key: string
  label: string
  count: number
  to: string
  // 'alert' when the number is a problem, 'warn' when it waits on me, 'calm' when it is only for information.
  tone: 'alert' | 'warn' | 'calm'
}

export interface CounterInputs {
  counts: ActionCounts
  // Jira work I owe (needs me plus approvals) is only known while the tracker slot is on, so it is null when off.
  trackerWaiting: number | null
  // Open 1:1 topics, only known while the people slot is on, so it is null when off.
  oneOnOneTopics: number | null
  // Open plans that stopped moving, counted by the server; null when the plans feed is not served or an older server does not count them.
  stuckPlans?: number | null
}

/**
 * The tiles to show, in the order the reference reads them: Action items, Pull requests, Work, Platform, Stuck plans, Improvements, 1:1 topics. A tile whose
 * source is off is left out, not shown as zero. Alerts, Knowledge and Builds have their own tab or rail badge and are not tiles.
 */
export function counterTiles(i: CounterInputs): CounterTile[] {
  const c = i.counts
  const tiles: CounterTile[] = [
    { key: 'actions', label: 'Action items', count: c.actions, to: '/action', tone: 'warn' },
    { key: 'reviews', label: 'Pull requests', count: c.reviews, to: c.platform > 0 || c.team === 0 ? '/reviews/platform' : '/reviews/team', tone: 'warn' },
    { key: 'operations', label: 'Platform', count: c.operations, to: '/platform', tone: 'alert' },
    { key: 'debt', label: 'Improvements', count: c.debt, to: '/debt', tone: 'calm' },
  ]
  if (i.trackerWaiting !== null) {
    tiles.splice(2, 0, { key: 'work', label: 'Work', count: i.trackerWaiting, to: '/work', tone: 'warn' })
  }
  if (i.stuckPlans !== null && i.stuckPlans !== undefined) {
    // Reads in the reference order: after Platform, before Improvements.
    tiles.splice(tiles.findIndex((t) => t.key === 'debt'), 0, { key: 'plans', label: 'Stuck plans', count: i.stuckPlans, to: '/plans', tone: 'warn' })
  }
  if (i.oneOnOneTopics !== null) {
    tiles.push({ key: 'oneonone', label: '1:1 topics', count: i.oneOnOneTopics, to: '/people', tone: 'warn' })
  }
  return tiles
}

/** True when anything needs me, which decides whether the row leads with a calm "nothing waiting" line. */
export function anythingWaiting(tiles: CounterTile[]): boolean {
  return tiles.some((t) => t.tone !== 'calm' && t.count > 0)
}
