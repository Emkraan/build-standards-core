// The Platform areas rollup: one row per section of the problem list with a single status, its counts and an owner the consumer names in the
// problem map (issue 308, item 24). The server derives the rows from the same list as the rail badge (problems.py), so they cannot disagree
// with it. This file holds the decisions, free of React, so a test can load it as it is. The core never invents an owner: with none named
// the row says so in words and never shows a blank that reads as healthy.

export type AreaStatus = 'needs_me' | 'worth_a_look' | 'healthy'

export interface PlatformArea {
  section: string
  label: string
  owner: string | null
  status: AreaStatus
  needs_me: number
  worth_a_look: number
  healthy: number
  lines: number
}

/** The rows as the server sends them. A server older than this field sends none, and that is told apart from an empty list. */
export interface AreasSource {
  areas?: PlatformArea[] | null
}

const WORD: Record<AreaStatus, string> = { needs_me: 'Needs me', worth_a_look: 'Worth a look', healthy: 'Healthy' }

/** A status as a word. An unknown status is shown as it came, capitalised, and is never called healthy. */
export function statusWord(status: string): string {
  return WORD[status as AreaStatus] ?? (status ? status[0].toUpperCase() + status.slice(1) : 'Unknown')
}

/** The rows to draw: the server's order (worst first), and none when the server sent none. A missing field is not an empty answer. */
export function areaRows(src: AreasSource | null | undefined): PlatformArea[] | null {
  if (!src || !Array.isArray(src.areas)) return null
  return src.areas
}

/** Who owns an area, in words. No owner named is said plainly and never left blank. */
export function ownerLine(a: PlatformArea): string {
  return a.owner ? `Owner: ${a.owner}` : 'No owner named'
}

/** How many areas need me. This is the count of areas, while `lines` is the count of problem lines the badge adds up. */
export function areasNeedingMe(rows: readonly PlatformArea[]): number {
  return rows.filter((r) => r.status === 'needs_me').length
}

/** One line for the rollup: how many areas there are and how many need me, so it reads the same as the badge in the rail. */
export function rollupLine(rows: readonly PlatformArea[]): string {
  const n = rows.length
  const need = areasNeedingMe(rows)
  const areas = `${n} area${n === 1 ? '' : 's'}`
  if (need === 0) return `${areas}, none needs me.`
  return `${areas}, ${need} ${need === 1 ? 'needs' : 'need'} me.`
}
