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
  // Builds in flight and runs waiting on an environment approval (badges.builds), null when the feed is not served.
  builds: { running: number; waiting: number } | null
}

/** The tiles to show, in the order I read them. A tile whose source is off is left out, not shown as zero. */
export function counterTiles(i: CounterInputs): CounterTile[] {
  const c = i.counts
  const tiles: CounterTile[] = [
    { key: 'actions', label: 'Actions open', count: c.actions, to: '/action', tone: 'warn' },
    { key: 'reviews', label: 'Reviews waiting', count: c.reviews, to: c.platform > 0 || c.team === 0 ? '/reviews/platform' : '/reviews/team', tone: 'warn' },
    { key: 'alerts', label: 'Alerts', count: c.alerts, to: '/action/alerts', tone: 'alert' },
    { key: 'operations', label: 'Platform problems', count: c.operations, to: '/operations', tone: 'alert' },
    { key: 'knowledge', label: 'Knowledge to decide', count: c.knowledge, to: '/knowledge', tone: 'warn' },
    { key: 'debt', label: 'Debt entries', count: c.debt, to: '/debt', tone: 'calm' },
  ]
  if (i.trackerWaiting !== null) {
    tiles.splice(2, 0, { key: 'work', label: 'Work waiting', count: i.trackerWaiting, to: '/jira', tone: 'warn' })
  }
  if (i.builds !== null) {
    tiles.push({ key: 'builds', label: 'Builds waiting', count: i.builds.waiting, to: '/operations/builds', tone: i.builds.waiting > 0 ? 'warn' : 'calm' })
  }
  return tiles
}

/** True when anything needs me, which decides whether the row leads with a calm "nothing waiting" line. */
export function anythingWaiting(tiles: CounterTile[]): boolean {
  return tiles.some((t) => t.tone !== 'calm' && t.count > 0)
}
