/* HubHeader: the title block of a hub page whose items are grouped into sections (UI standard section 6,
   "Sectioned hubs"). Two tab rows under the page header: the top row is Overview plus one tab per titled
   section, the second row (shown once a section is open) is one tab per item. The route shape is
   `<base>/<section>/<item>`. It is router-free: the app passes the current section and item from its
   route and goes to a path in `onNavigate`. Counts and the working state of each item arrive from the app,
   which reads them from one server list; the header adds them up for a section tab and never applies a
   threshold of its own. Work in progress is a spinner, never a red count. */

import type { ReactNode } from 'react';
import { devWarn } from '../lib/env';
import { PageHeader } from './Header';
import { Spinner } from '../primitives/Spinner';
import { Tabs } from '../primitives/Tabs';
import type { TabItem } from '../primitives/Tabs';

export interface HubItem {
  /** Route segment of the item, for example `builds`. */
  key: string;
  label: string;
  /** Things that need attention under this item, from the server's problem list. Shown when above 0. */
  count?: number | undefined;
  /** Something under this item is running right now: a spinner next to the label. */
  live?: boolean | undefined;
}

export interface HubSection {
  /** Route segment of the section. */
  key: string;
  /** The section title, also the title of its group on the Overview. */
  label: string;
  items: readonly HubItem[];
}

/** Where a path inside a hub points: the Overview, one item, or somewhere else the app must send the visitor. */
export type HubRoute =
  | { kind: 'overview' }
  | { kind: 'item'; section: HubSection; item: HubItem }
  | { kind: 'redirect'; to: string };

const seg = (key: string): string => encodeURIComponent(key);
/** A route segment as the router hands it over, decoded; a malformed escape stays as it is. */
function unseg(raw: string | undefined): string | undefined {
  if (raw === undefined) return undefined;
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

/**
 * What is wrong with a hub's keys: a section or item key used twice, or an item key that is also a section key
 * (a path would then mean two things). The first one wins in every helper here, so the result is the same on every
 * render; fix the keys. Empty when the keys are unique.
 */
export function hubSectionProblems(sections: readonly HubSection[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const s of sections) {
    if (seen.has(s.key)) out.push(`section key "${s.key}" is used twice`);
    seen.add(s.key);
  }
  const items = new Set<string>();
  for (const s of sections)
    for (const i of s.items) {
      if (items.has(i.key)) out.push(`item key "${i.key}" is used twice`);
      else if (seen.has(i.key)) out.push(`item key "${i.key}" is also a section key`);
      items.add(i.key);
    }
  return out;
}

function warnOnce(sections: readonly HubSection[]): void {
  const problems = hubSectionProblems(sections);
  if (problems.length > 0) devWarn(`hub-keys:${problems.join('|')}`, `HubHeader: ${problems.join('; ')}. The first one wins.`);
}

/**
 * The path of an item (`<base>/<section>/<item>`), of a section (its first item), or of the Overview for a key it
 * does not know and for a section with no items (there is nothing to open in it). Keys are encoded as route segments.
 */
export function hubPath(base: string, sections: readonly HubSection[], key?: string): string {
  const root = base.replace(/\/+$/, '');
  if (!key) return root || '/';
  for (const sec of sections) {
    if (sec.key === key) {
      const first = sec.items[0];
      return first ? `${root}/${seg(sec.key)}/${seg(first.key)}` : root || '/';
    }
    if (sec.items.some((i) => i.key === key)) return `${root}/${seg(sec.key)}/${seg(key)}`;
  }
  return root || '/';
}

/**
 * Reads the `section` and `item` segments of a route, as the router gives them (raw or decoded). No section is the
 * Overview. A section the hub does not have is an old flat link (`<base>/<item>`) and redirects to the item's new
 * path; a section with a missing or unknown item redirects to its first item, and a section with no items to the
 * Overview, so a redirect never points at itself. The app renders the redirect with its router and keeps the query
 * string and hash itself, so an old link never breaks.
 */
export function resolveHubRoute(base: string, sections: readonly HubSection[], section?: string, item?: string): HubRoute {
  warnOnce(sections);
  const secKey = unseg(section);
  const itemKey = unseg(item);
  if (!secKey) return { kind: 'overview' };
  const sec = sections.find((s) => s.key === secKey);
  if (!sec) return { kind: 'redirect', to: hubPath(base, sections, secKey) };
  const found = sec.items.find((i) => i.key === itemKey);
  if (found) return { kind: 'item', section: sec, item: found };
  return { kind: 'redirect', to: hubPath(base, sections, sec.key) };
}

export interface HubHeaderProps {
  title: string;
  /** One line saying what the hub is for. */
  subtitle?: string | undefined;
  eyebrow?: string | undefined;
  /** Status badges only. */
  status?: ReactNode;
  /** The route the hub lives at, for example `/platform`. Not needed with `headerOnly`. */
  base?: string | undefined;
  sections?: readonly HubSection[] | undefined;
  /** A flat hub with a single tab row: one tab per item, route `<base>/<item>`, no sections and no second row. Used instead of `sections`; the current tab is `item`. */
  tabs?: readonly HubItem[] | undefined;
  /** With `tabs`: the key of the index tab. Its route is `<base>` itself, not `<base>/<key>`, and it is the tab selected when the route has no item. Default the first tab selects with no item but keeps its `<base>/<key>` path. */
  indexKey?: string | undefined;
  /** Current section segment from the route. Omit on the Overview. */
  section?: string | undefined;
  /** Current item segment from the route. */
  item?: string | undefined;
  /** Goes to a path. Called with `<base>`, `<base>/<section>/<item>`. */
  onNavigate?: ((path: string) => void) | undefined;
  /** The page header only: no tabs and no Overview. For a page that sits in the hub's header style but has nothing to switch between. */
  headerOnly?: boolean | undefined;
  /** Label of the first tab. Default "Overview". */
  overviewLabel?: string | undefined;
}

function badge(count: number | undefined, live: boolean | undefined): ReactNode {
  if (!live && !(count !== undefined && count > 0)) return undefined;
  return (
    <>
      {live ? (
        <>
          <Spinner size="xs" arc />
          <span className="kit-sr-only">working</span>
        </>
      ) : null}
      {count !== undefined && count > 0 ? count : null}
    </>
  );
}

function sum(items: readonly HubItem[]): number | undefined {
  const n = items.reduce((t, i) => t + (i.count ?? 0), 0);
  return n > 0 ? n : undefined;
}

function FlatHubHeader({ title, subtitle, eyebrow, status, base, tabs, item, indexKey, onNavigate }: Pick<HubHeaderProps, 'title' | 'subtitle' | 'eyebrow' | 'status' | 'item' | 'indexKey'> & { base: string; onNavigate: (path: string) => void; tabs: readonly HubItem[] }) {
  const root = base.replace(/\/+$/, '');
  const items: TabItem[] = tabs.map((t) => ({ id: t.key === indexKey ? root || '/' : `${root}/${seg(t.key)}`, label: t.label, badge: badge(t.count, t.live) }));
  const cur = unseg(item);
  const value = items[tabs.findIndex((t) => t.key === cur)]?.id ?? items[Math.max(0, tabs.findIndex((t) => t.key === indexKey))]?.id ?? '';
  return (
    <div className="hub-head">
      <PageHeader eyebrow={eyebrow} title={title} subtitle={subtitle} status={status} />
      <Tabs label={`${title} tabs`} items={items} value={value} onChange={onNavigate} />
    </div>
  );
}

const noop = () => {};

export function HubHeader({
  title,
  subtitle,
  eyebrow,
  status,
  base = '/',
  sections = [],
  tabs,
  indexKey,
  section,
  item,
  onNavigate = noop,
  headerOnly,
  overviewLabel = 'Overview',
}: HubHeaderProps) {
  if (headerOnly) {
    return (
      <div className="hub-head">
        <PageHeader eyebrow={eyebrow} title={title} subtitle={subtitle} status={status} />
      </div>
    );
  }
  if (tabs) return <FlatHubHeader {...{ title, subtitle, eyebrow, status, base, tabs, item, indexKey, onNavigate }} />;
  warnOnce(sections);
  const root = base.replace(/\/+$/, '') || '/';
  const pre = root === '/' ? '' : root;
  const shown = sections.filter((s, i) => s.items.length > 0 && sections.findIndex((o) => o.key === s.key) === i);
  const sectionKey = unseg(section);
  const itemKey = unseg(item);
  const open = shown.find((s) => s.key === sectionKey);
  const top: TabItem[] = [
    { id: root, label: overviewLabel },
    ...shown.map((s) => ({
      id: `${pre}/${seg(s.key)}`,
      label: s.label,
      badge: badge(sum(s.items), s.items.some((i) => i.live)),
    })),
  ];
  const topValue = open ? `${pre}/${seg(open.key)}` : root;
  const second: TabItem[] = (open?.items ?? []).map((i) => ({
    id: `${pre}/${seg(open?.key ?? '')}/${seg(i.key)}`,
    label: i.label,
    badge: badge(i.count, i.live),
  }));
  // An item the section does not have selects the first tab (the app's route redirects there), never no tab.
  const secondValue = second.find((t) => t.id === `${pre}/${seg(open?.key ?? '')}/${seg(itemKey ?? '')}`)?.id ?? second[0]?.id ?? '';
  return (
    <div className="hub-head">
      <PageHeader eyebrow={eyebrow} title={title} subtitle={subtitle} status={status} />
      <Tabs
        label={`${title} sections`}
        items={top}
        value={topValue}
        onChange={(id) => {
          // A section tab opens the section's first item, so the second row always has a current tab.
          const sec = shown.find((s) => `${pre}/${seg(s.key)}` === id);
          onNavigate(sec ? hubPath(base, sections, sec.key) : id);
        }}
      />
      {open ? (
        <div className="hub-subtabs">
          <Tabs label={`${open.label} items`} variant="pills" items={second} value={secondValue} onChange={onNavigate} />
        </div>
      ) : null}
    </div>
  );
}
