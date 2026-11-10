/* Timeline: what happened, one sentence per entry. Each entry has a time (relative, absolute in the
   tip), who did it, what they did, where the record came from (a source chip) and a link to the record.
   The caller orders the entries (newest first reads best on a record's page). */

import type { ReactNode } from 'react';
import { cx } from '../lib/env';
import { HelpLink } from './HelpLink';
import { Badge } from './marks';
import { useTip } from './Tooltip';
import { When } from './When';

export type TimelineTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

export interface TimelineEntry {
  id: string;
  /** When it happened: a Date, an ISO string or epoch milliseconds. */
  time: Date | string | number | null | undefined;
  /** Who did it, by name. A person is a name, never a login (the login goes in `actorTip`). */
  actor?: string | undefined;
  /** The login or email of the actor, shown as the actor's tip. */
  actorTip?: string | undefined;
  /** The sentence: "approved the request", "changed the pool size from 4 to 6". */
  text: ReactNode;
  /** Where the entry came from, as a short chip: "Audit log", "Monitor", "Console". */
  source?: string | undefined;
  /** The record this entry points at. */
  href?: string | undefined;
  hrefLabel?: string | undefined;
  /** Colours the marker's outline. Neutral by default. */
  tone?: TimelineTone | undefined;
}

export interface TimelineProps {
  entries: readonly TimelineEntry[];
  /** Accessible name of the list. */
  label?: string | undefined;
  /** IANA zone the absolute times in the tips are written in. Default: the viewer's zone. */
  timeZone?: string | undefined;
  /** Shown instead of the list when there are no entries. */
  empty?: ReactNode;
  className?: string | undefined;
}

function Actor({ name, tip }: { name: string; tip?: string | undefined }) {
  const { props, description } = useTip(tip);
  return (
    <span className="timeline-actor" {...props} tabIndex={tip?.trim() ? 0 : undefined}>
      {name}
      {description}
    </span>
  );
}

export function Timeline({ entries, label, timeZone, empty, className }: TimelineProps) {
  if (entries.length === 0) return empty ? <p className="timeline-empty">{empty}</p> : null;
  return (
    <ol className={cx('timeline', className)} aria-label={label}>
      {entries.map((entry) => (
        <li key={entry.id} className="timeline-item" data-tone={entry.tone && entry.tone !== 'neutral' ? entry.tone : undefined}>
          <span className="timeline-marker" aria-hidden="true" />
          <div className="timeline-body">
            <p className="timeline-line">
              {entry.actor ? (
                <>
                  <Actor name={entry.actor} tip={entry.actorTip} />{' '}
                </>
              ) : null}
              {entry.text}
            </p>
            <div className="timeline-meta">
              <When value={entry.time} timeZone={timeZone} />
              {entry.source ? <Badge className="timeline-source">{entry.source}</Badge> : null}
              {entry.href ? (
                <HelpLink href={entry.href} className="timeline-link">
                  {entry.hrefLabel ?? 'View'}
                </HelpLink>
              ) : null}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}
