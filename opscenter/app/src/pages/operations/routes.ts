// Old routes and where they land (layout rule 9: an old link never breaks). Pure functions, so a unit test can follow every
// redirect and check that the tab and the query string survive.
import { OLD_INFRA_TAB, OPERATIONS_BASE } from './sections'

const first = (path: string) => (path.endsWith('/') ? path.slice(0, -1) : path)

/** The new path of an old route, with the old query string and hash kept, or null when the path is not an old route. */
export function redirectOld(pathname: string, search = '', hash = ''): string | null {
  const path = first(pathname)
  const keep = `${search}${hash}`
  if (path === '/builds') return `${OPERATIONS_BASE}/builds${keep}`
  if (path === '/core') return `${OPERATIONS_BASE}/cost/core${keep}`
  if (path === '/infra') return `${OPERATIONS_BASE}${keep}`
  const m = path.match(/^\/infra\/([^/]+)$/)
  if (m) {
    const item = OLD_INFRA_TAB[m[1] as string]
    if (item === 'spend' || item === 'core') return `${OPERATIONS_BASE}/cost/${item}${keep}`
    return item ? `${OPERATIONS_BASE}/automation/${item}${keep}` : `${OPERATIONS_BASE}${keep}`
  }
  return null
}
