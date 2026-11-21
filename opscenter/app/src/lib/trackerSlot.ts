// The tracker slot: the Jira pages (needs me, sprint, backlog, changes) are a consumer-provided optional slot that renders
// nothing by default (opscenter/DESIGN.md 12.67). The server adds the tracker routes only when OPSCENTER_TRACKER is on, so a
// 404 from GET api/jira/needs-me means the slot is off. This file holds the decision, free of React and the data layer, so
// tests/trackerSlot.test.mjs can load it as it is. It mirrors peopleSlot.ts on purpose.

/** on: the slot answered. off: the server has no tracker routes. unknown: not answered yet, or the server is unreachable. */
export type TrackerSlot = 'on' | 'off' | 'unknown'

/** What a tracker route does: show the page, wait for the first answer, or say the slot is off (the page names the slot it needs, opscenter/DESIGN.md 12.72). */
export type TrackerRoute = 'show' | 'wait' | 'off'

export interface TrackerFlag {
  slot?: 'off'
}

/** The answer the app uses while the slot is off: no ticket, no change, and marked so no chip or badge reads it as a failure. */
export const TRACKER_OFF = {
  generated_utc: '',
  count: 0,
  items: [] as never[],
  slot: 'off' as const,
}

export function trackerSlot(data: TrackerFlag | null | undefined): TrackerSlot {
  if (!data) return 'unknown'
  return data.slot === 'off' ? 'off' : 'on'
}

/** An unreachable server (an error and no answer) still shows the page, which reports its own failure. */
export function trackerRoute(slot: TrackerSlot, failed: boolean): TrackerRoute {
  if (slot === 'off') return 'off'
  if (slot === 'on' || failed) return 'show'
  return 'wait'
}
