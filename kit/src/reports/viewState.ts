/* Deep links (R4): the address holds the view, so a link opens exactly what was on screen. A dashboard is
   `?d=<key>&range=<preset>&f.<filterId>=<value>`: readable, shareable, and the other parameters of the page are kept.
   A drill link carries the rows behind a panel as one `drill` parameter, base64url JSON of {stream, measure, filters,
   name}, so an app can open its own explorer on them. Router free: the app reads and writes its own location. */

export interface DashboardView {
  /** Dashboard key. */
  d?: string | undefined;
  range?: string | undefined;
  /** Filter picks by filter id. A pick that is empty is not a pick. */
  f: Record<string, string>;
}

const asParams = (search: string | URLSearchParams): URLSearchParams => (typeof search === 'string' ? new URLSearchParams(search.replace(/^\?/, '')) : new URLSearchParams(search));

export function readDashboardView(search: string | URLSearchParams): DashboardView {
  const sp = asParams(search);
  const f: Record<string, string> = {};
  for (const [k, v] of sp.entries()) if (k.startsWith('f.') && k.length > 2 && v) f[k.slice(2)] = v;
  return { d: sp.get('d') || undefined, range: sp.get('range') || undefined, f };
}

/** The parameters for `view`, keeping every parameter that is not part of the view (a tab, a page). */
export function writeDashboardView(search: string | URLSearchParams, view: DashboardView): URLSearchParams {
  const sp = asParams(search);
  for (const k of [...sp.keys()]) if (k === 'd' || k === 'range' || k.startsWith('f.')) sp.delete(k);
  if (view.d) sp.set('d', view.d);
  if (view.range) sp.set('range', view.range);
  for (const [id, v] of Object.entries(view.f)) if (v) sp.set(`f.${id}`, v);
  return sp;
}

/** A full link to a view on a page: `<pageUrl>?d=...`. */
export function dashboardLink(pageUrl: string, view: DashboardView, currentSearch: string | URLSearchParams = ''): string {
  const qs = writeDashboardView(currentSearch, view).toString();
  const base = pageUrl.split(/[?#]/)[0] ?? pageUrl;
  return qs ? `${base}?${qs}` : base;
}

/** The rows behind a panel: what an explorer needs to reproduce it. */
export interface DrillTarget {
  stream: string;
  measure: string;
  filters?: Record<string, string> | undefined;
  /** A name for the explorer's tab. */
  name?: string | undefined;
}

function toBase64Url(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64Url(raw: string): string {
  const std = raw.replace(/-/g, '+').replace(/_/g, '/');
  const bin = atob(std + '='.repeat((4 - (std.length % 4)) % 4));
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

/** `<path>?drill=...` for a target, so the link can be shared and reopened. */
export function drillLink(path: string, target: DrillTarget): string {
  return `${path.split(/[?#]/)[0]}?drill=${toBase64Url(JSON.stringify(target))}`;
}

/** The drill target in an address, or null when there is none or it is not a valid one. */
export function readDrill(search: string | URLSearchParams): DrillTarget | null {
  const raw = asParams(search).get('drill');
  if (!raw) return null;
  try {
    const t = JSON.parse(fromBase64Url(raw)) as Partial<DrillTarget> | null;
    if (!t || typeof t.stream !== 'string' || typeof t.measure !== 'string') return null;
    const filters = t.filters && typeof t.filters === 'object' ? Object.fromEntries(Object.entries(t.filters).filter(([, v]) => typeof v === 'string')) : undefined;
    return { stream: t.stream, measure: t.measure, ...(filters ? { filters } : {}), ...(typeof t.name === 'string' ? { name: t.name } : {}) };
  } catch {
    return null;
  }
}
