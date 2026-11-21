// The people slot: the 1:1 board, team performance, member reviews and the yearly review are a consumer-provided
// optional slot that renders nothing by default (opscenter/DESIGN.md 12.14). The server adds the people routes only
// when OPSCENTER_PEOPLE names the slot, so a 404 from GET api/one-on-ones means the slot is off. This file holds the
// decision, free of React and the data layer, so tests/peopleSlot.test.mjs can load it as it is.

/** on: the slot answered. off: the server has no people routes. unknown: not answered yet, or the server is unreachable. */
export type PeopleSlot = 'on' | 'off' | 'unknown'

/** What a people route does: show the page, wait for the first answer, or say the slot is off (the page names the slot it needs, opscenter/DESIGN.md 12.72). */
export type PeopleRoute = 'show' | 'wait' | 'off'

export interface SlotFlag {
  slot?: 'off'
}

/** The board the app uses while the slot is off: empty, and marked so no chip, badge or page treats it as a failure. */
export const PEOPLE_OFF_BOARD = {
  generated_utc: '',
  people: [] as never[],
  sources: { agenda_items: 0, calendar_ok: false },
  slot: 'off' as const,
}

export function peopleSlot(data: SlotFlag | null | undefined): PeopleSlot {
  if (!data) return 'unknown'
  return data.slot === 'off' ? 'off' : 'on'
}

/** An unreachable server (an error and no answer) still shows the page, which reports its own failure. */
export function peopleRoute(slot: PeopleSlot, failed: boolean): PeopleRoute {
  if (slot === 'off') return 'off'
  if (slot === 'on' || failed) return 'show'
  return 'wait'
}
