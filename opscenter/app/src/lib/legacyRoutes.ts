// Routes that moved when the rail took the reference names (issue 327, opscenter/DESIGN.md 12.73): /jira is /work and /operations is
// /platform. An old bookmark or relay link never breaks (ops-center-layout rule 9): it lands on the same tab with its query and hash.
// /platform used to be a redirect into the platform review lane, so its three lane tabs keep going there. Free of React so
// tests/legacyRoutes.test.mjs can load it as it is.

const MOVED: [string, string][] = [
  ['/jira', '/work'],
  ['/operations', '/platform'],
]

/** The review lane tabs an old /platform/<tab> link meant. They are not Platform sections. */
export const PLATFORM_LANE_TABS = ['progress', 'mine', 'shipped'] as const

/** The new path of a moved route, query and hash kept, or null when the path did not move. */
export function movedTo(pathname: string, search = '', hash = ''): string | null {
  const path = pathname.length > 1 && pathname.endsWith('/') ? pathname.slice(0, -1) : pathname
  for (const [from, to] of MOVED) {
    if (path === from || path.startsWith(`${from}/`)) return `${to}${path.slice(from.length)}${search}${hash}`
  }
  return null
}

/** What /platform/<section> shows: the Platform hub, or the platform review lane when the segment is one of its old tabs. */
export function platformTarget(section: string | undefined): { kind: 'hub' } | { kind: 'lane'; to: string } {
  if (section && (PLATFORM_LANE_TABS as readonly string[]).includes(section)) return { kind: 'lane', to: `/reviews/platform/${section}` }
  return { kind: 'hub' }
}
