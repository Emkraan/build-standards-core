// Filters for the Debt and improvements page: kind, severity, goal, effort, status and the fold toggles.
// Pure functions over EngItem so tests/debtFilters.test.mjs can load this file as it is.

export interface DebtFilterItem {
  kind: 'TD' | 'IMP'
  severity: string
  goals: string[]
  effort: string
  status: string
  children?: string[]
  parent_uid?: string
}

export interface DebtFilters {
  /** all, TD (technical debt) or IMP (improvement). */
  kind: string
  severity: string
  goal: string
  effort: string
  status: string
  hasFolded: boolean
  foldedInto: boolean
}

export const NO_DEBT_FILTERS: DebtFilters = {
  kind: 'all',
  severity: 'all',
  goal: 'all',
  effort: 'all',
  status: 'all',
  hasFolded: false,
  foldedInto: false,
}

/** Effort is free text ("S", "2 days", "M, one PR"). It groups by its leading size word so the filter has few values. */
export function effortBand(effort: string): string {
  const e = (effort || '').trim().toLowerCase()
  if (!e) return 'unsized'
  const m = e.match(/^(xs|s|m|l|xl|small|medium|large|tiny|trivial|huge)\b/)
  if (m) {
    const w = m[1]
    if (w === 'xs' || w === 'tiny' || w === 'trivial') return 'xs'
    if (w === 's' || w === 'small') return 's'
    if (w === 'm' || w === 'medium') return 'm'
    return 'l'
  }
  if (/\bhalf a day\b/.test(e)) return 's'
  const d = e.match(/(\d+(?:\.\d+)?)\s*(hour|hr|day|week|wk)/)
  if (d) {
    const n = Number(d[1])
    const days = d[2].startsWith('h') ? n / 8 : d[2].startsWith('d') ? n : n * 5
    return days <= 0.5 ? 'xs' : days <= 2 ? 's' : days <= 5 ? 'm' : 'l'
  }
  return 'unsized'
}

export const isFoldedInto = (it: DebtFilterItem) => !!it.parent_uid
export const hasFoldedEntries = (it: DebtFilterItem) => (it.children?.length ?? 0) > 0

/** What each filter offers, counted over the rows the other filters leave, so no option leads to an empty list. */
export function optionsFor<T extends DebtFilterItem>(items: T[], pick: (it: T) => string[]): { value: string; n: number }[] {
  const n = new Map<string, number>()
  for (const it of items) for (const v of pick(it)) if (v) n.set(v, (n.get(v) || 0) + 1)
  return [...n.entries()].map(([value, count]) => ({ value, n: count })).sort((a, b) => b.n - a.n || a.value.localeCompare(b.value))
}

export function applyDebtFilters<T extends DebtFilterItem>(items: T[], f: DebtFilters): T[] {
  return items.filter((it) => {
    if (f.kind !== 'all' && it.kind !== f.kind) return false
    if (f.severity !== 'all' && it.severity !== f.severity) return false
    if (f.goal !== 'all' && !it.goals.includes(f.goal)) return false
    if (f.effort !== 'all' && effortBand(it.effort) !== f.effort) return false
    if (f.status !== 'all' && it.status.toLowerCase() !== f.status) return false
    if (f.hasFolded && !hasFoldedEntries(it)) return false
    if (f.foldedInto && !isFoldedInto(it)) return false
    return true
  })
}

export const activeFilterCount = (f: DebtFilters) =>
  (['kind', 'severity', 'goal', 'effort', 'status'] as const).filter((k) => f[k] !== 'all').length + (f.hasFolded ? 1 : 0) + (f.foldedInto ? 1 : 0)

/** Rows drawn at once. Done holds several hundred entries, so a list shows one window and loads the next on request. */
export const DEBT_WINDOW = 100

/** The window of a list: the rows to draw and how many are left. A text search spans the whole list, so it shows every match. */
export function pageDebtRows<T>(rows: T[], limit: number, searching: boolean): { shown: T[]; left: number } {
  if (searching || rows.length <= limit) return { shown: rows, left: 0 }
  return { shown: rows.slice(0, limit), left: rows.length - limit }
}
