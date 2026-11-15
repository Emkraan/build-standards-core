/* HubOverview and AreaCard: the Overview of a sectioned hub (UI standard section 6, "Sectioned hubs"). One
   card per item, grouped under the same section titles in the same order as the tabs. A card shows a tone
   pill (healthy, worth a look, needs me), a one line headline (live facts from the provider, then the server status text), at most four detail lines and a link to the
   item. The tone comes from the server's problem list, the same list the rail badge and the tab counts read:
   the card never judges a number itself. A running item reads as running, never red. */

import type { ReactNode } from 'react';
import { IconChevronRight } from '../icons/icons';
import { cx } from '../lib/env';
import { Card, CardHead } from '../primitives/Card';
import { Badge } from '../primitives/marks';
import type { StatusTone } from '../primitives/marks';
import { DefaultLink, GuardedLink, useShell } from './context';

/** healthy, worth a look, needs me. */
export type AreaTone = 'good' | 'warn' | 'alert';

const LABEL: Record<AreaTone, string> = { good: 'healthy', warn: 'worth a look', alert: 'needs me' };
const PILL: Record<AreaTone, StatusTone> = { good: 'success', warn: 'warning', alert: 'danger' };
/** Detail lines a card shows before "and N more". */
export const AREA_DETAIL_LINES = 4;

export interface AreaCardData {
  /** Matches an item `key` of the hub's sections. */
  key: string;
  label: string;
  /** Where the card links: the item's route. */
  to: string;
  tone: AreaTone;
  /** Something under this item is running now. A running item wears the info tone with a spinner, so work is never red; a healthy one reads "running". */
  live?: boolean | undefined;
  /** Something under this item is running now. Same as `live`, named as the server payload names it (`running` per item). */
  running?: boolean | undefined;
  /** One line of live facts the provider fills, for example "v1.114 payload, 3 runners online". Shown first. */
  headline?: ReactNode;
  /** The server's status text, for example "Healthy". Shown after the headline, or alone when there is no headline. */
  status?: ReactNode;
  /** What needs a look, one short line each. Four show, the rest are counted. */
  detail?: readonly string[] | undefined;
}

export interface AreaCardProps extends Omit<AreaCardData, 'key'> {
  className?: string | undefined;
}

export function AreaCard({ label, to, tone, live: liveProp, running: runningProp, headline, status, detail = [], className }: AreaCardProps) {
  const shell = useShell();
  const Link = shell?.Link ?? DefaultLink;
  const live = !!liveProp || !!runningProp;
  const running = live && tone === 'good';
  const shown = detail.slice(0, AREA_DETAIL_LINES);
  return (
    <Card className={cx('area-card', className)} data-tone={tone}>
      <CardHead
        level={3}
        title={
          <GuardedLink Link={Link} href={to} className="area-card-link">
            {label}
            <IconChevronRight />
          </GuardedLink>
        }
        controls={
          <Badge className="pill" tone={live ? 'info' : PILL[tone]} live={live} dot={!live}>
            {running ? 'running' : LABEL[tone]}
          </Badge>
        }
      />
      {headline ? <p className="area-card-headline">{headline}</p> : null}
      {status ? <p className={headline ? 'area-card-status' : 'area-card-headline'}>{status}</p> : null}
      {shown.length > 0 ? (
        <ul className="area-card-detail">
          {shown.map((d, i) => (
            <li key={`${i}:${d}`}>{d}</li>
          ))}
          {detail.length > AREA_DETAIL_LINES ? <li className="area-card-more">and {detail.length - AREA_DETAIL_LINES} more</li> : null}
        </ul>
      ) : null}
    </Card>
  );
}

/** The sections of the hub, in tab order. The `HubSection` of `HubHeader` fits. */
export interface OverviewSection {
  key: string;
  /** The title of the group. */
  label: string;
  items: readonly { key: string }[];
}

export interface HubOverviewProps {
  sections: readonly OverviewSection[];
  /** One entry per item. An item with no entry yet shows no card. */
  areas: readonly AreaCardData[];
  /** A line above the groups, for example how many areas need attention. */
  summary?: ReactNode;
  className?: string | undefined;
}

export function HubOverview({ sections, areas, summary, className }: HubOverviewProps) {
  return (
    <div className={cx('hub-overview', className)}>
      {summary ? <div className="hub-overview-summary">{summary}</div> : null}
      {sections.map((sec, si) => {
        if (sec.items.length === 0) return null;
        const seen = new Set<string>();
        const cards = sec.items
          .filter((it) => (seen.has(it.key) ? false : (seen.add(it.key), true)))
          .map((it) => areas.find((a) => a.key === it.key))
          .filter((a): a is AreaCardData => !!a);
        return (
          <section key={`${si}:${sec.key}`} className="hub-overview-section" aria-label={sec.label}>
            <h2 className="hub-overview-title">{sec.label}</h2>
            <div className="hub-overview-grid">
              {cards.map(({ key, ...card }) => (
                <AreaCard key={key} {...card} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
