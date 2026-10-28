// TeamAway - who on my team is out today and in the next two weeks, announced by the feed presenter.
// Data: action-center.json team_away (bundle_data.py -> team_away.py, Outlook free/busy status oof,
// times only). Days are compared on the America/New_York calendar. A failed read shows as unknown,
// never as "whole team in".
import type { FeedItem } from '@kit'

export interface AwayBlock {
  start: string
  end: string
  all_day: boolean
}
export interface TeamAwayData {
  checked_utc?: string
  days?: number
  error?: string | null
  people: { name: string; first: string; error?: string | null; blocks: AwayBlock[] }[]
}

const TZ = 'America/New_York'
const etDate = (d: Date) => d.toLocaleDateString('en-CA', { timeZone: TZ })
// A bare YYYY-other_resource read at noon UTC formats as the same calendar day everywhere.
const day = (ymd: string) => new Date(`${ymd}T12:00:00Z`)
const addDays = (ymd: string, n: number) => {
  const d = day(ymd)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}
const fmtDay = (ymd: string) => day(ymd).toLocaleDateString('en-US', { timeZone: 'UTC', weekday: 'short', month: 'short', day: 'numeric' })
const fmtTime = (iso: string) => new Date(iso).toLocaleTimeString('en-US', { timeZone: TZ, hour: 'numeric', minute: '2-digit' })
const nextWorkday = (ymd: string) => {
  let d = addDays(ymd, 1)
  while ([0, 6].includes(day(d).getUTCDay())) d = addDays(d, 1)
  return d
}

interface Entry {
  first: string
  name: string
  text: string
  start: string
}

export function splitAway(data: TeamAwayData, now = new Date()): { today: Entry[]; soon: Entry[] } {
  const today = etDate(now)
  const out = { today: [] as Entry[], soon: [] as Entry[] }
  for (const p of data.people || []) {
    for (const b of p.blocks || []) {
      const first = b.start.slice(0, 10)
      const last = b.all_day ? addDays(b.end.slice(0, 10), -1) : b.end.slice(0, 10)
      if (last < today) continue
      if (first <= today) {
        const text = b.all_day
          ? `all day, back ${fmtDay(nextWorkday(last))}`
          : `${fmtTime(b.start)} to ${fmtTime(b.end)}${new Date(b.end) < now ? ', earlier' : ''}`
        out.today.push({ first: p.first, name: p.name, text, start: b.start })
      } else {
        const text = b.all_day
          ? first === last
            ? fmtDay(first)
            : `${fmtDay(first)} to ${fmtDay(last)}`
          : `${fmtDay(first)}, ${fmtTime(b.start)} to ${fmtTime(b.end)}`
        out.soon.push({ first: p.first, name: p.name, text, start: b.start })
      }
    }
  }
  out.soon.sort((a, b) => a.start.localeCompare(b.start))
  return out
}

/** Team availability as one feed announcement for the presenter (stick figure) under the header. */
export function awayAnnouncement(data: TeamAwayData | null | undefined, now = new Date()): Omit<FeedItem, 'id' | 'onOpen'> | null {
  if (!data) return null
  if (data.error && !data.people?.length) return { tone: 'warning', title: 'Team availability unknown.', body: data.error }
  const { today, soon } = splitAway(data, now)
  const checked = data.checked_utc ? new Date(data.checked_utc) : null
  const stale = !checked || now.getTime() - checked.getTime() > 2 * 3600e3
  const partial = (data.people || []).filter((p) => p.error).map((p) => p.first)
  const shown = soon.slice(0, 3).map((e) => `${e.first} ${e.text}`)
  const more = soon.length > 3 ? `, and ${soon.length - 3} more` : ''
  const notes = [
    soon.length ? `Coming up: ${shown.join(' \u00b7 ')}${more}.` : `Nothing booked in the next ${data.days ?? 14} days.`,
    data.error ? 'Last read failed, showing the previous answer.' : '',
    partial.length ? `No free/busy for ${partial.join(', ')}.` : '',
    stale && !data.error ? 'Not refreshed in over 2 hours.' : '',
  ].filter(Boolean)
  const warn = !!data.error || stale || partial.length > 0
  if (today.length) {
    return { tone: 'warning', title: `Out today: ${today.map((e) => `${e.first} (${e.text})`).join(' \u00b7 ')}.`, body: notes.join(' ') }
  }
  return { tone: warn ? 'warning' : 'success', title: 'Whole team in today.', body: notes.join(' ') }
}
