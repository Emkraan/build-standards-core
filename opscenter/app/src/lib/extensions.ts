// The extension manifest: pages a consumer adds to the rail without a change to the core (GET api/extensions, GET api/extensions/<id>).
// The consumer declares each page as data and the core draws it, so a consumer page is never code in the shell. It is a provider slot, so a
// 404 means the consumer has none and the rail shows nothing extra. The decisions are here so a test can load them without the browser
// (issue 308, item 22). Read only on purpose: a page lists rows or links out, and it has no button that changes anything.

export type ExtensionKind = 'list' | 'link'

export interface ExtensionPage {
  id: string
  title: string
  group: string
  kind: ExtensionKind
  url: string | null
  lede: string | null
}

export interface ExtensionRow {
  id: string
  title: string
  detail: string | null
  state: string | null
  url: string | null
  at: string | null
  /** Up to four buttons the row declares; each needs a confirmation. Absent from an older server. */
  actions?: { id: string; label: string; confirm: string | null }[]
  /** The label and value pairs of the detail drawer. */
  fields?: { label: string; value: string }[]
}

export interface ExtensionManifest {
  fetched_utc: string
  pages: ExtensionPage[]
  truncated: number
  error: string | null
}

export type ExtensionsState = { configured: false } | ({ configured: true } & ExtensionManifest)

export interface ExtensionRows {
  fetched_utc: string
  page: ExtensionPage | null
  rows: ExtensionRow[]
  truncated: number
  /** All rows the source holds (at most 5000) and where this window starts; absent from an older server. */
  total?: number
  offset?: number
  error: string | null
}

/** The rail groups the core has. A page names one of these and anything else lands in Platform. */
export const EXTENSION_GROUPS = ['Operate', 'People', 'Knowledge', 'Platform'] as const

/** What the rail does with the manifest: add nothing (no provider), warn that the source failed, or add the pages. */
export type ExtensionsMode = 'none' | 'error' | 'pages'

export function extensionsMode(s: ExtensionsState | null | undefined): ExtensionsMode {
  if (!s || !s.configured) return 'none'
  if (s.error) return 'error'
  return s.pages.length > 0 ? 'pages' : 'none'
}

/** The address of an extension page. The prefix keeps it clear of every core route, and the server refuses an id that would shadow one. */
export function extensionPath(id: string): string {
  return `/extensions/${id}`
}

/** The pages in one rail group, in the order the consumer declared them. */
export function pagesIn(s: ExtensionsState | null | undefined, group: string): ExtensionPage[] {
  if (!s || !s.configured || s.error) return []
  return s.pages.filter((p) => p.group === group)
}

/** True only for an address safe to put in an href. The server already filters, and the client does not rely on that. */
export function safeHref(url: string | null | undefined): string | null {
  return typeof url === 'string' && /^https?:\/\//i.test(url) ? url : null
}

/** What a page does when opened: say the source failed, say there is nothing, or show what it has. A link page never lists rows. */
export type PageMode = 'error' | 'link' | 'empty' | 'rows'

export function pageMode(r: ExtensionRows | null | undefined): PageMode {
  if (!r) return 'empty'
  if (r.error) return 'error'
  if (r.page?.kind === 'link') return 'link'
  return r.rows.length > 0 ? 'rows' : 'empty'
}

/** The pages the rail adds: those of a working source, and none while it is failing or absent. */
export function pagesAll(s: ExtensionsState | null | undefined): ExtensionPage[] {
  return !s || !s.configured || s.error ? [] : s.pages
}

/** What the page route does: wait for the first answer, show the page, or leave for the home route when the manifest does not name it. */
export type ExtensionRoute = 'wait' | 'show' | 'leave'

export function extensionRoute(s: ExtensionsState | null | undefined, id: string, failed: boolean): ExtensionRoute {
  if (!s) return failed ? 'leave' : 'wait'
  if (!s.configured || s.error) return 'leave'
  return s.pages.some((p) => p.id === id) ? 'show' : 'leave'
}

/** The states the rows carry, with how many rows each has, most rows first. Fewer than two states means no filter tabs. */
export function stateTabs(rows: ExtensionRow[]): { state: string; n: number }[] {
  const n = new Map<string, number>()
  for (const r of rows) if (r.state) n.set(r.state, (n.get(r.state) || 0) + 1)
  return n.size < 2 ? [] : [...n.entries()].map(([state, count]) => ({ state, n: count })).sort((a, b) => b.n - a.n || a.state.localeCompare(b.state))
}

/** The rows of the chosen state; every row when no state is chosen or the state is gone. */
export function rowsInState(rows: ExtensionRow[], state: string): ExtensionRow[] {
  return state ? rows.filter((r) => r.state === state) : rows
}
