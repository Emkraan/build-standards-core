// The rail layout is a consumer parameter (issue 326 item 1, opscenter/DESIGN.md 12.72): labels, order, and flat versus
// grouped. The default is one flat rail in the core's own order with the core's own labels. A consumer sets one build time
// variable, VITE_NAV, to a JSON object:
//   { "layout": "flat" | "grouped",
//     "order":  ["/action", "/work", ...],                 route paths, first to last; a route not listed follows in core order
//     "labels": { "/work": "Jira" },                       a label per route path; a route not listed keeps the core label
//     "groups": [ { "label": "Deliver", "items": ["/work", "/reviews"] } ] }   used by "grouped" only
// Anything that does not parse, or names no known value, falls back to the default, so a typo never empties the rail.
// Free of React so tests/navLayout.test.mjs can load it as it is.

export type NavLayoutKind = 'flat' | 'grouped'

export interface NavGroupSpec {
  label: string
  items: string[]
}

export interface NavLayout {
  layout: NavLayoutKind
  order: string[]
  labels: Record<string, string>
  groups: NavGroupSpec[]
}

/** The grouped layout when a consumer picks "grouped" and names no groups of its own. */
export const DEFAULT_GROUPS: NavGroupSpec[] = [
  { label: 'Today', items: ['/action'] },
  { label: 'Deliver', items: ['/work', '/reviews', '/platform'] },
  { label: 'Improve', items: ['/debt'] },
  { label: 'People', items: ['/people', '/team'] },
  { label: 'Knowledge', items: ['/knowledge', '/plans', '/links'] },
]

export const DEFAULT_NAV_LAYOUT: NavLayout = { layout: 'flat', order: [], labels: {}, groups: DEFAULT_GROUPS }

const isRoute = (v: unknown): v is string => typeof v === 'string' && /^\/[a-z0-9/_-]*$/i.test(v)

/** Reads the VITE_NAV value. Unknown or malformed parts are dropped one by one; nothing here throws. */
export function parseNavLayout(raw: string | null | undefined): NavLayout {
  if (!raw || !raw.trim()) return DEFAULT_NAV_LAYOUT
  let v: unknown
  try {
    v = JSON.parse(raw)
  } catch {
    return DEFAULT_NAV_LAYOUT
  }
  if (!v || typeof v !== 'object' || Array.isArray(v)) return DEFAULT_NAV_LAYOUT
  const o = v as Record<string, unknown>
  const labels: Record<string, string> = {}
  if (o.labels && typeof o.labels === 'object' && !Array.isArray(o.labels)) {
    for (const [k, l] of Object.entries(o.labels as Record<string, unknown>)) {
      if (isRoute(k) && typeof l === 'string' && l.trim()) labels[k] = l.trim()
    }
  }
  const groups: NavGroupSpec[] = Array.isArray(o.groups)
    ? (o.groups as unknown[]).flatMap((g) => {
        if (!g || typeof g !== 'object') return []
        const { label, items } = g as { label?: unknown; items?: unknown }
        if (typeof label !== 'string' || !label.trim() || !Array.isArray(items)) return []
        const list = items.filter(isRoute)
        return list.length ? [{ label: label.trim(), items: list }] : []
      })
    : []
  return {
    layout: o.layout === 'grouped' ? 'grouped' : 'flat',
    order: Array.isArray(o.order) ? o.order.filter(isRoute) : [],
    labels,
    groups: groups.length ? groups : DEFAULT_GROUPS,
  }
}

export interface Routed {
  to: string
  label: string
}

export interface Arranged<T> {
  /** Empty for the flat rail: one group with no heading. */
  label: string
  items: T[]
}

/** A route path matches an item when it is the item's path (a consumer names the top level path of a page). */
const same = (a: string, b: string) => a === b

/** Applies the layout to the items a viewer can see (the slots already took theirs out). Items keep their core order unless `order` moves them. */
export function arrange<T extends Routed>(items: T[], layout: NavLayout): Arranged<T>[] {
  const labelled = items.map((i) => ({ ...i, label: layout.labels[i.to] ?? i.label }))
  const rank = (i: T) => {
    const at = layout.order.findIndex((p) => same(p, i.to))
    return at < 0 ? layout.order.length : at
  }
  const ordered = labelled
    .map((item, at) => ({ item, at }))
    .sort((a, b) => rank(a.item) - rank(b.item) || a.at - b.at)
    .map((x) => x.item)
  if (layout.layout === 'flat') return ordered.length ? [{ label: '', items: ordered }] : []
  const used = new Set<string>()
  const out: Arranged<T>[] = []
  for (const g of layout.groups) {
    const here = g.items.flatMap((p) => ordered.filter((i) => same(i.to, p) && !used.has(i.to)))
    here.forEach((i) => used.add(i.to))
    // Order inside a group follows the order parameter when given, else the group's own list.
    const sorted = layout.order.length ? [...here].sort((a, b) => rank(a) - rank(b)) : here
    if (sorted.length) out.push({ label: g.label, items: sorted })
  }
  // A page no group names (a consumer extension, a route a custom group list left out) still shows, in a last group, never dropped.
  const rest = ordered.filter((i) => !used.has(i.to))
  if (rest.length) out.push({ label: 'More', items: rest })
  return out
}

/** The group heading a route sits under in the grouped layout (the consumer's groups, or the default five), for the header breadcrumb in any layout. */
export function groupOf(route: string, layout: NavLayout): string | undefined {
  return layout.groups.find((g) => g.items.includes(route))?.label
}

/** The header breadcrumb: "<Group> / <Page> / <Tab>", leaving out the parts a page does not have. */
export function breadcrumb(parts: (string | null | undefined)[]): string {
  return parts.filter((p): p is string => !!p).join(' / ')
}
