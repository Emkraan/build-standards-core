// The one time formatter for everything on screen (Ops Center Layout rule 21). Clock times are written in one configured zone with
// the abbreviation (EST, EDT), never UTC and never a trailing Z. Relative times are spelled out ("5 days ago", never "5d ago") and
// the exact time rides in the tip. Server stamps arrive as ISO strings in UTC, a bare YYYY-MM-DD date is read as that calendar day.
// The zone is a parameter: setTimeZone('America/New_York') once at start-up, the default is the viewer's own zone.
let zone: string | undefined
/** The IANA zone every clock time is written in. Without a call it is the viewer's own zone. */
export function setTimeZone(name: string | undefined) {
  zone = name
  cache.clear()
}
export type TimeInput = string | number | Date | null | undefined

/** A Date for an ISO string, epoch millis or Date, or null for an empty or unreadable value. */
export function toDate(v: TimeInput): Date | null {
  if (v === null || v === undefined || v === '') return null
  // A bare calendar date means that day wherever the browser sits, so it is read at noon UTC.
  const d = v instanceof Date ? v : typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) ? new Date(`${v}T12:00:00Z`) : new Date(v)
  return Number.isNaN(d.getTime()) ? null : d
}

const cache = new Map<string, Intl.DateTimeFormat>()
// A formatter per option set, built on first use in the configured zone and dropped when the zone changes.
const fmt = (opts: Intl.DateTimeFormatOptions) => {
  const key = JSON.stringify(opts)
  const get = () => {
    let f = cache.get(key)
    if (!f) {
      f = new Intl.DateTimeFormat('en-US', zone ? { timeZone: zone, ...opts } : opts)
      cache.set(key, f)
    }
    return f
  }
  return { format: (d: Date) => get().format(d), formatToParts: (d: Date) => get().formatToParts(d) }
}
const CLOCK = fmt({ hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
const DAY = fmt({ month: 'short', day: 'numeric' })
const DAY_YEAR = fmt({ month: 'short', day: 'numeric', year: 'numeric' })
const WEEKDAY_DAY = fmt({ weekday: 'short', month: 'short', day: 'numeric' })
const LONG_DAY = fmt({ weekday: 'long', month: 'long', day: 'numeric' })
const PARTS = fmt({ year: 'numeric', month: '2-digit', day: '2-digit' })

/** "11:20 PM EST". */
export function clockTime(v: TimeInput): string {
  const d = toDate(v)
  return d ? CLOCK.format(d) : ''
}

/** "Nov 15" (a bare date keeps its own calendar day). */
export function dayName(v: TimeInput): string {
  const d = toDate(v)
  if (!d) return ''
  return typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)
    ? new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric' }).format(d)
    : DAY.format(d)
}

/** "Sunday, November 15", the header date. */
export function longDay(v: TimeInput = Date.now()): string {
  const d = toDate(v)
  return d ? LONG_DAY.format(d) : ''
}

/** "Sun, Nov 15, 11:20 PM EST", the exact time for a tip or a log line. */
export function stamp(v: TimeInput): string {
  const d = toDate(v)
  return d ? `${WEEKDAY_DAY.format(d)}, ${CLOCK.format(d)}` : ''
}

/** "Nov 15, 2026, 11:20 PM EST", for a table column where the year matters. */
export function fullTime(v: TimeInput): string {
  const d = toDate(v)
  return d ? `${DAY_YEAR.format(d)}, ${CLOCK.format(d)}` : ''
}

/** The calendar day in the configured zone of a moment as YYYY-MM-DD (grouping by day). */
export function dayKey(v: TimeInput): string {
  const d = toDate(v)
  if (!d) return ''
  const p = Object.fromEntries(PARTS.formatToParts(d).map((x) => [x.type, x.value]))
  return `${p.year}-${p.month}-${p.day}`
}

const unit = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

/** "just now", "5 minutes ago", "3 hours ago", "2 days ago". `none` is what an empty value reads as. */
export function relAgo(v: TimeInput, now: number = Date.now(), none = 'never'): string {
  const d = toDate(v)
  if (!d) return v === null || v === undefined || v === '' ? none : 'unknown'
  const m = (now - d.getTime()) / 60_000
  if (m < 1) return 'just now'
  if (m < 60) return `${unit(Math.round(m), 'minute')} ago`
  if (m < 1440) return `${unit(Math.round(m / 60), 'hour')} ago`
  return `${unit(Math.round(m / 1440), 'day')} ago`
}

/** Forward looking twin: "in 5 minutes", "in 3 hours", "in 2 days". */
export function relIn(v: TimeInput, now: number = Date.now()): string {
  const d = toDate(v)
  if (!d) return 'unknown'
  const m = (d.getTime() - now) / 60_000
  if (m < 1) return 'now'
  if (m < 60) return `in ${unit(Math.round(m), 'minute')}`
  if (m < 1440) return `in ${unit(Math.round(m / 60), 'hour')}`
  return `in ${unit(Math.round(m / 1440), 'day')}`
}

/** A span in plain words: "45 seconds", "about 12 minutes", "about 3 hours". */
export function spanWords(seconds: number): string {
  if (seconds < 90) return unit(Math.max(0, Math.round(seconds)), 'second')
  if (seconds < 5400) return `about ${unit(Math.round(seconds / 60), 'minute')}`
  return `about ${unit(Math.round(seconds / 3600), 'hour')}`
}

/** Age in whole minutes, or null for an empty value. */
export function ageMinutes(v: TimeInput, now: number = Date.now()): number | null {
  const d = toDate(v)
  return d ? Math.max(0, (now - d.getTime()) / 60_000) : null
}
