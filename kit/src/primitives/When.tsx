/* When: a relative time ("2 h ago") whose tip carries the absolute date, time and zone, so the page
   reads quickly and the exact moment is one hover or one focus away. It ticks on the shared clock, and
   it takes the zone the absolute time is written in (an operator reading a log in another zone). */

import { useMemo } from 'react';
import type { HTMLAttributes } from 'react';
import { useClockValue } from '../lib/clock';
import { cx, devWarn } from '../lib/env';
import { joinIds, useTip } from './Tooltip';
import type { TipSide } from './Tooltip';

/**
 * The age of a moment: "just now", "12s ago", "4 min ago", "2 h ago", "3 d ago", "2 mo ago", "1 y ago",
 * and "in 5 min" for a moment ahead. `elapsedMs` is now minus the moment, so a negative number is the
 * future. It follows the wording of the kit's "Updated ..." label and goes on to days, months and years.
 */
export function formatWhen(elapsedMs: number): string {
  const seconds = Math.floor(Math.abs(elapsedMs) / 1000);
  if (seconds < 2) return 'just now';
  let span: string;
  const minutes = Math.round(seconds / 60);
  const hours = Math.round(minutes / 60);
  const days = Math.round(hours / 24);
  const months = Math.round(days / 30);
  if (seconds < 90) span = `${seconds}s`;
  else if (minutes < 90) span = `${minutes} min`;
  else if (hours < 36) span = `${hours} h`;
  else if (days < 45) span = `${days} d`;
  else if (months < 18) span = `${months} mo`;
  else span = `${Math.round(months / 12)} y`;
  return elapsedMs < 0 ? `in ${span}` : `${span} ago`;
}

const ABSOLUTE: Intl.DateTimeFormatOptions = {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  second: '2-digit',
  timeZoneName: 'short',
};

/**
 * The date, time and zone of a moment in one line ("Oct 26, 2026, 3:04:12 PM EDT"), written in
 * `timeZone` (an IANA name such as "America/New_York" or "UTC"), or the viewer's own zone when it is
 * omitted. An unknown zone name falls back to the viewer's zone and warns in development.
 */
export function formatWhenAbsolute(date: Date, timeZone?: string | undefined, locale?: string | undefined): string {
  try {
    return new Intl.DateTimeFormat(locale, timeZone ? { ...ABSOLUTE, timeZone } : ABSOLUTE).format(date);
  } catch {
    devWarn(`when-zone:${timeZone ?? ''}`, `<When> got a time zone it does not know ("${timeZone ?? ''}"). It writes the time in the viewer's zone.`);
    return new Intl.DateTimeFormat(locale, ABSOLUTE).format(date);
  }
}

function toMillis(value: Date | string | number | null | undefined): number | null {
  if (value == null || value === '') return null;
  const ms = value instanceof Date ? value.getTime() : new Date(value).getTime();
  return Number.isNaN(ms) ? null : ms;
}

export interface WhenProps extends Omit<HTMLAttributes<HTMLElement>, 'children'> {
  /** The moment: a Date, an ISO string or epoch milliseconds. Empty or unreadable shows "undated". */
  value: Date | string | number | null | undefined;
  /** IANA zone the absolute time in the tip is written in. Default: the viewer's zone. */
  timeZone?: string | undefined;
  /** BCP 47 locale of the absolute time. Default: the viewer's locale. */
  locale?: string | undefined;
  tipSide?: TipSide | undefined;
}

export function When({ value, timeZone, locale, tipSide, className, ...rest }: WhenProps) {
  const at = toMillis(value);
  const label = useClockValue(() => (at === null ? 'undated' : formatWhen(Date.now() - at)));
  const absolute = useMemo(() => (at === null ? '' : formatWhenAbsolute(new Date(at), timeZone, locale)), [at, timeZone, locale]);
  const { props: tip, description } = useTip(absolute, tipSide);
  if (at === null) {
    return (
      <span {...rest} className={cx('when', className)} data-empty="">
        undated
      </span>
    );
  }
  return (
    <time
      {...rest}
      {...tip}
      aria-describedby={joinIds(rest['aria-describedby'], tip['aria-describedby'])}
      className={cx('when', className)}
      dateTime={new Date(at).toISOString()}
      suppressHydrationWarning
    >
      {label}
      {description}
    </time>
  );
}
