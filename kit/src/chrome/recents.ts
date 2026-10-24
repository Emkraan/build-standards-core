/* Recent pages for the hub home: pure helpers over a list the host keeps (usually in this browser's
   storage, per account). A recent is a page the person opened in any module: { moduleId, route,
   label, at }. Newest first, one entry per page, at most RECENT_MAX. The kit stores nothing itself. */

export const RECENT_MAX = 8;

export interface Recent {
  moduleId: string;
  route: string;
  label: string;
  /** Milliseconds since the epoch. */
  at: number;
}

/** The list a host read from storage, dropping anything that is not a complete recent. */
export function sanitizeRecents(list: unknown, max: number = RECENT_MAX): Recent[] {
  if (!Array.isArray(list)) return [];
  const out: Recent[] = [];
  for (const r of list as unknown[]) {
    if (!r || typeof r !== 'object') continue;
    const { moduleId, route, label, at } = r as Record<string, unknown>;
    if (typeof moduleId === 'string' && typeof route === 'string' && typeof label === 'string' && typeof at === 'number' && Number.isFinite(at)) {
      out.push({ moduleId, route, label, at });
    }
  }
  return out.slice(0, max);
}

/**
 * The list after a visit: the page moves to the front, its older entry is dropped, the label is cut
 * to 60 characters and the list is capped. The hub home itself is never recorded (`isHome`).
 */
export function addRecent(
  list: readonly Recent[],
  page: { moduleId: string; route: string; label: string },
  at: number = Date.now(),
  { max = RECENT_MAX, isHome = false }: { max?: number | undefined; isHome?: boolean | undefined } = {},
): Recent[] {
  if (isHome || !page.moduleId || !page.route || !page.label) return [...list];
  const rest = list.filter((r) => !(r.moduleId === page.moduleId && r.route === page.route));
  return [{ moduleId: page.moduleId, route: page.route, label: page.label.slice(0, 60), at }, ...rest].slice(0, max);
}
