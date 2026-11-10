/* The blocks of the hub home (UI standard, shell section 9): feed, quick actions, and pinned pages with
   recents, plus the pieces they share (link, tool chip, item row). Every block is presentational:
   it takes plain data through props and renders it as text, so a module supplies numbers and short
   names, never markup. Loading is a skeleton, a source that could not be read is one quiet line,
   and an empty block says what that means. Navigation goes through `go`, so the host router
   mounts the page in place, while the link stays a real anchor (middle click and copy link work). */

import type { MouseEvent, ReactNode } from 'react';
import { IconChevronRight, IconPinOff } from '../icons/icons';
import { cx } from '../lib/env';
import type { MarkHue } from '../lib/hues';
import { safeHref } from '../lib/url';
import { Button, IconButton } from '../primitives/Button';
import { Card, CardBody, CardHead } from '../primitives/Card';
import { EmptyState, Skeleton } from '../primitives/EmptyState';
import { RelativeTime } from '../primitives/Text';
import { usePins } from './PinButton';
import type { Pin, PinsStore } from './PinButton';
import type { Recent } from './recents';

/** A module as the hub home knows it: where it is mounted, what to call it and its hue. */
export interface HomeTool {
  id: string;
  name: string;
  /** Where the module is mounted, for example `/reports`. */
  basePath: string;
  /** The module's mark hue. Absent, or `brand`, follows the app accent. */
  hue?: MarkHue | 'brand' | undefined;
}

export type HomeTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

/** One row of a feed block. A module supplies the numbers and short names, never markup. */
export interface HomeItem {
  key: string;
  label: string;
  /** One quiet line under the label. */
  detail?: string | undefined;
  /** When it happened, shown as a relative time. */
  at?: Date | string | number | undefined;
  /** The number or short word on the right. null or undefined shows a dash. */
  value?: number | string | null | undefined;
  tone?: HomeTone | undefined;
  /** The page inside the module's own router that the row opens. */
  route: string;
}

/** One module's contribution to a feed block. */
export interface HomeFeedSource {
  tool: HomeTool;
  status: 'loading' | 'error' | 'ready';
  items?: readonly HomeItem[] | undefined;
}

export interface HomeAction {
  key: string;
  tool: HomeTool;
  label: string;
  route: string;
  icon?: ReactNode;
}

/** The address of a page inside a module: its mount path plus the route, with one slash between. */
export function homeHref(tool: Pick<HomeTool, 'basePath'>, route: string): string {
  const base = tool.basePath.replace(/\/+$/, '');
  const r = route.startsWith('/') ? route : `/${route}`;
  return r === '/' ? base || '/' : `${base}${r}`;
}

const hueClass = (hue: HomeTool['hue']): string | undefined => (hue && hue !== 'brand' ? `hue-${hue}` : undefined);

export interface HubLinkProps {
  href: string;
  /** Opens the page in the shell. Called for a plain left click, never for a modified one. */
  go: (to: string) => void;
  className?: string | undefined;
  title?: string | undefined;
  children: ReactNode;
}

/**
 * A link that opens inside the shell: a real anchor, and a plain click goes through `go` so the
 * host router mounts the page in place. Its href goes through `safeHref`: an unsafe one renders an
 * anchor without an href and never calls `go`.
 */
export function HubLink({ href, go, className, title, children }: HubLinkProps) {
  const safe = safeHref(href);
  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    if (safe === undefined || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    go(safe);
  };
  return (
    <a href={safe} className={className} title={title} onClick={onClick}>
      {children}
    </a>
  );
}

export interface ToolChipProps {
  name: string;
  hue?: HomeTool['hue'];
}

/** The owning module as a small chip in its hue. No hue (or `brand`) follows the app accent. */
export function ToolChip({ name, hue }: ToolChipProps) {
  return <span className={cx('hue-chip', hueClass(hue))}>{name}</span>;
}

export interface HomeItemRowProps {
  item: HomeItem;
  tool: HomeTool;
  go: (to: string) => void;
}

/** One row: the module chip, label and detail on the left, the value in its tone on the right. */
export function HomeItemRow({ item, tool, go }: HomeItemRowProps) {
  const unknown = item.value === null || item.value === undefined;
  return (
    <li>
      <HubLink href={homeHref(tool, item.route)} go={go} className="home-item" title={`Open ${item.label}`}>
        <span className="home-item-main">
          <ToolChip name={tool.name} hue={tool.hue} />
          <span className="home-item-label">{item.label}</span>
          {item.detail ? <span className="home-item-detail">{item.detail}</span> : null}
          {item.at !== undefined ? (
            <span className="home-item-detail">
              <RelativeTime value={item.at} />
            </span>
          ) : null}
        </span>
        <span className="home-item-value" data-tone={item.tone ?? 'neutral'} data-unknown={unknown ? '' : undefined}>
          {unknown ? '-' : typeof item.value === 'number' ? item.value.toLocaleString() : item.value}
        </span>
        <IconChevronRight size={14} className="home-item-go" />
      </HubLink>
    </li>
  );
}

export interface FeedBlockProps {
  /** Stable id of the block, used for its heading id and `data-block`. */
  id: string;
  title: string;
  subtitle?: string | undefined;
  icon?: ReactNode;
  sources: readonly HomeFeedSource[];
  emptyTitle: string;
  emptyBody: string;
  /** Drop rows whose value is zero (a "waiting on you" block shows only what is waiting). */
  hideZero?: boolean | undefined;
  /** Shown under the rows, for example a link to the full list. */
  extra?: ReactNode;
  go: (to: string) => void;
}

/**
 * A feed-backed block. A skeleton while any source has no answer yet, one quiet line per module
 * whose source could not be read, and the rows of the rest.
 */
export function FeedBlock({ id, title, subtitle, icon, sources, emptyTitle, emptyBody, hideZero = false, extra, go }: FeedBlockProps) {
  const rows: Array<{ item: HomeItem; tool: HomeTool }> = [];
  const unread: string[] = [];
  let waiting = 0;
  for (const source of sources) {
    if (source.status === 'loading') {
      waiting += 1;
    } else if (source.status === 'error') {
      if (!unread.includes(source.tool.name)) unread.push(source.tool.name);
    } else {
      for (const item of source.items ?? []) {
        if (hideZero && item.value === 0) continue;
        rows.push({ item, tool: source.tool });
      }
    }
  }
  const settled = waiting === 0;
  const headingId = `home-${id}-t`;
  return (
    <Card as="section" className="home-block" aria-labelledby={headingId} data-block={id}>
      <CardBody>
        <CardHead icon={icon} title={<span id={headingId}>{title}</span>} subtitle={subtitle} level={2} />
        {rows.length > 0 ? (
          <ul className="home-list">
            {rows.map((r) => (
              <HomeItemRow key={`${r.tool.id}/${r.item.key}`} item={r.item} tool={r.tool} go={go} />
            ))}
          </ul>
        ) : null}
        {!settled && rows.length === 0 ? <Skeleton variant="lines" count={2} label={`Loading ${title}`} /> : null}
        {!settled && rows.length > 0 ? <Skeleton variant="line" label={`Loading more of ${title}`} /> : null}
        {settled && rows.length === 0 && unread.length === 0 ? <EmptyState compact title={emptyTitle} body={emptyBody} /> : null}
        {settled
          ? unread.map((name) => (
              <p key={name} className="home-quiet" role="status">
                {name} could not be read right now.
              </p>
            ))
          : null}
        {extra}
      </CardBody>
    </Card>
  );
}

export interface ActionsBlockProps {
  actions: readonly HomeAction[];
  go: (to: string) => void;
  title?: string | undefined;
}

/** Quick actions the person's access allows, each a button into the module's page. */
export function ActionsBlock({ actions, go, title = 'Quick actions' }: ActionsBlockProps) {
  return (
    <Card as="section" className="home-block home-block-bar" aria-labelledby="home-actions-t" data-block="actions">
      <CardBody>
        <h2 className="home-bar-title" id="home-actions-t">
          {title}
        </h2>
        <div className="home-actions">
          {actions.map((a) => (
            <Button
              key={`${a.tool.id}/${a.key}`}
              variant="secondary"
              size="sm"
              className={cx('home-action', hueClass(a.tool.hue))}
              icon={a.icon}
              title={`${a.label} in ${a.tool.name}`}
              onClick={() => go(homeHref(a.tool, a.route))}
            >
              {a.label}
            </Button>
          ))}
        </div>
      </CardBody>
    </Card>
  );
}

export interface PinnedBlockProps {
  /** The same store the header pin control uses, so the two always agree. */
  store: PinsStore;
  tools: readonly HomeTool[];
  recents: readonly Recent[];
  /** Module ids the person can enter. A pin or recent for any other module is not shown. Default: all. */
  reachable?: ReadonlySet<string> | undefined;
  go: (to: string) => void;
  /** Called with the store's one-sentence reason when an unpin fails. */
  onError?: ((message: string) => void) | undefined;
  /** How many recents show (default 5). */
  recentLimit?: number | undefined;
}

/**
 * Pinned pages (kept by the store, unpin here) and recent pages (kept by the host, this browser).
 * A recent that is also pinned is not repeated. When the store is denied the pinned list is not
 * shown, and recents still are.
 */
export function PinnedBlock({ store, tools, recents, reachable, go, onError, recentLimit = 5 }: PinnedBlockProps) {
  const { status, pins } = usePins(store);
  const toolOf = (id: string) => tools.find((t) => t.id === id);
  const shown = (p: { moduleId: string }) => (reachable ? reachable.has(p.moduleId) : true) && toolOf(p.moduleId) !== undefined;
  const open = status === 'ready' ? pins.filter(shown) : [];
  const pinnedKeys = new Set(pins.map((p) => `${p.moduleId}${p.route}`));
  const trail = recents.filter((r) => shown(r) && !pinnedKeys.has(`${r.moduleId}${r.route}`)).slice(0, recentLimit);
  const unpin = async (p: Pin) => {
    const failed = await store.unpin(p);
    if (failed) onError?.(failed);
  };
  const row = (p: { moduleId: string; route: string; label: string }, end: ReactNode) => {
    const tool = toolOf(p.moduleId) as HomeTool;
    return (
      <HubLink href={homeHref(tool, p.route)} go={go} className="home-item" title={`Open ${p.label}`}>
        <span className="home-item-main">
          <ToolChip name={tool.name} hue={tool.hue} />
          <span className="home-item-label">{p.label}</span>
        </span>
        {end}
        <IconChevronRight size={14} className="home-item-go" />
      </HubLink>
    );
  };
  return (
    <Card as="section" className="home-block" aria-labelledby="home-pinned-t" data-block="pinned">
      <CardBody>
        <CardHead title={<span id="home-pinned-t">Pinned and recent pages</span>} subtitle="Use the pin in a page header to keep it here" level={2} />
        {open.length > 0 ? (
          <ul className="home-list" aria-label="Pinned pages">
            {open.map((p) => (
              <li key={`${p.moduleId}${p.route}`} className="home-pinned-row">
                {row(p, <span />)}
                <IconButton
                  label={`Unpin ${p.label}`}
                  icon={<IconPinOff size={14} />}
                  size="sm"
                  onClick={() => {
                    void unpin(p);
                  }}
                />
              </li>
            ))}
          </ul>
        ) : null}
        {trail.length > 0 ? (
          <>
            <h3 className="home-sub">Recent</h3>
            <ul className="home-list" aria-label="Recent pages">
              {trail.map((r) => (
                <li key={`${r.moduleId}${r.route}`}>
                  {row(
                    r,
                    <span className="home-item-detail">
                      <RelativeTime value={r.at} />
                    </span>,
                  )}
                </li>
              ))}
            </ul>
          </>
        ) : null}
        {open.length === 0 && trail.length === 0 ? (
          <EmptyState compact title="Nothing pinned yet" body="Pin a page from its header and it shows here. Pages you open show here too." />
        ) : null}
      </CardBody>
    </Card>
  );
}
