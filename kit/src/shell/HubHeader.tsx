/* HubHeader: the title block of a hub page whose items are grouped into sections (UI standard section 6,
   "Sectioned hubs"). Two tab rows under the page header: the top row is Overview plus one tab per titled
   section, the second row (shown once a section is open) is one tab per item. The route shape is
   `<base>/<section>/<item>`. It is router-free: the app passes the current section and item from its
   route and goes to a path in `onNavigate`. Counts and the working state of each item arrive from the app,
   which reads them from one server list; the header adds them up for a section tab and never applies a
   threshold of its own. Work in progress is a spinner, never a red count. */

import type { ReactNode } from 'react';
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

/** The path of an item (`<base>/<section>/<item>`), of a section (its first item), or of the Overview for a key it does not know. */
export function hubPath(base: string, sections: readonly HubSection[], key?: string): string {
  const root = base.replace(/\/+$/, '');
  if (!key) return root || '/';
  for (const sec of sections) {
    if (sec.key === key) {
      const first = sec.items[0];
      return first ? `${root}/${sec.key}/${first.key}` : `${root}/${sec.key}`;
    }
    if (sec.items.some((i) => i.key === key)) return `${root}/${sec.key}/${key}`;
  }
  return root || '/';
}

/**
 * Reads the `section` and `item` segments of a route. No section is the Overview. A section the hub does not
 * have is an old flat link (`<base>/<item>`) and redirects to the item's new path; a section with a missing or
 * unknown item redirects to its first item. The app renders the redirect with its router and keeps the query
 * string and hash itself, so an old link never breaks.
 */
export function resolveHubRoute(base: string, sections: readonly HubSection[], section?: string, item?: string): HubRoute {
  if (!section) return { kind: 'overview' };
  const sec = sections.find((s) => s.key === section);
  if (!sec) return { kind: 'redirect', to: hubPath(base, sections, section) };
  const found = sec.items.find((i) => i.key === item);
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
  /** The route the hub lives at, for example `/platform`. */
  base: string;
  sections: readonly HubSection[];
  /** Current section segment from the route. Omit on the Overview. */
  section?: string | undefined;
  /** Current item segment from the route. */
  item?: string | undefined;
  /** Goes to a path. Called with `<base>`, `<base>/<section>/<item>`. */
  onNavigate: (path: string) => void;
  /** Label of the first tab. Default "Overview". */
  overviewLabel?: string | undefined;
}

function badge(count: number | undefined, live: boolean | undefined): ReactNode {
  if (!live && !(count !== undefined && count > 0)) return undefined;
  return (
    <>
      {live ? (
        <>
          <Spinner size="xs" />
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

export function HubHeader({
  title,
  subtitle,
  eyebrow,
  status,
  base,
  sections,
  section,
  item,
  onNavigate,
  overviewLabel = 'Overview',
}: HubHeaderProps) {
  const root = base.replace(/\/+$/, '') || '/';
  const open = sections.find((s) => s.key === section);
  const top: TabItem[] = [
    { id: root, label: overviewLabel },
    ...sections.map((s) => ({
      id: `${root === '/' ? '' : root}/${s.key}`,
      label: s.label,
      badge: badge(sum(s.items), s.items.some((i) => i.live)),
    })),
  ];
  const topValue = open ? `${root === '/' ? '' : root}/${open.key}` : root;
  const second: TabItem[] = (open?.items ?? []).map((i) => ({
    id: hubPath(base, sections, i.key),
    label: i.label,
    badge: badge(i.count, i.live),
  }));
  const secondValue = open && item ? hubPath(base, sections, item) : (second[0]?.id ?? '');
  return (
    <div className="hub-head">
      <PageHeader eyebrow={eyebrow} title={title} subtitle={subtitle} status={status} />
      <Tabs
        label={`${title} sections`}
        items={top}
        value={topValue}
        onChange={(id) => {
          // A section tab opens the section's first item, so the second row always has a current tab.
          const sec = sections.find((s) => `${root === '/' ? '' : root}/${s.key}` === id);
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
