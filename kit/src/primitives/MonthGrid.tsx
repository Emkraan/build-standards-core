/* MonthGrid: a generic month calendar. Weeks of day cells with event slots, a today marker and roving
   keyboard navigation (arrows, Home, End, PageUp, PageDown). It knows dates and layout only; what an
   event means (coverage, shifts, leave) stays in the app and arrives through the event list and the
   renderEvent and renderDay slots. Dates are ISO day strings (YYYY-MM-DD), so no time zone shifts a
   cell. The title and the month buttons are the app's; this part is the grid.

   Multi-day events: an event with an `endDate` (inclusive) covers each day from `date` to `endDate`. By
   default it shows as a chip on each of those days. With `laneBars` it draws as one bar that runs
   across the days of a week and is packed into lanes (rows) so bars never overlap: a bar that crosses
   a week edge continues on the next week, `maxEvents` is the number of lanes, and bars that do not
   fit are counted in "+N more" on each day they cover. Without `endDate` or `laneBars` nothing
   changes.

   Bad dates: an event whose `date` is not a real ISO day (YYYY-MM-DD, so not "2026-6-5" and not a date with
   a time) is left out. An `endDate` that is not a real ISO day, or is before `date`, makes it a one day
   event. The grid never throws on them. */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, HTMLAttributes, KeyboardEvent, ReactNode } from 'react';
import { cx } from '../lib/env';

export type MonthGridTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info';

export interface MonthGridEvent {
  id: string;
  /** ISO day, YYYY-MM-DD. */
  date: string;
  /** Last day of a multi-day event, ISO and inclusive. Omit, or give a day before `date`, for one day. */
  endDate?: string | undefined;
  label: string;
  tone?: MonthGridTone | undefined;
}

/** One bar of one week: the event, its lane (row), its first column (0 to 6), its width in days and whether it runs
    on from the week before or into the week after. */
export interface MonthGridBar {
  event: MonthGridEvent;
  lane: number;
  col: number;
  span: number;
  continuesLeft: boolean;
  continuesRight: boolean;
}

export interface MonthGridWeekPlan {
  /** Bars that fit in a lane. */
  bars: MonthGridBar[];
  /** Lanes used, at most `maxLanes`. */
  lanes: number;
  /** Per column, how many bars were left out for want of a lane. */
  hidden: number[];
}

export interface MonthGridDay {
  /** ISO day. */
  date: string;
  /** Day of the month, 1 to 31. */
  day: number;
  /** False for the leading and trailing days of the neighbouring months. */
  inMonth: boolean;
  today: boolean;
  /** 0 is Sunday. */
  weekday: number;
}

export interface MonthGridProps extends Omit<HTMLAttributes<HTMLDivElement>, 'onSelect' | 'children'> {
  /** Full year, for example 2026. */
  year: number;
  /** 0 to 11. */
  month: number;
  /** Names the grid for a screen reader, for example "Team calendar". */
  label: string;
  /** ISO day marked as today. Omit and the grid reads the clock. */
  today?: string | undefined;
  /** 0 Sunday (default) or 1 Monday. */
  weekStart?: 0 | 1 | undefined;
  events?: readonly MonthGridEvent[] | undefined;
  /** Events shown in a cell before "+N more" (with `laneBars`, the number of lanes). Default 3. */
  maxEvents?: number | undefined;
  /** Draws multi-day events as bars packed into lanes across the week, instead of a chip per day. Default false. */
  laneBars?: boolean | undefined;
  /** The chosen day, ISO. */
  selected?: string | undefined;
  onSelectDay?: ((date: string) => void) | undefined;
  /** Fired when keys move past the month (PageUp, PageDown, or an arrow off the edge). */
  onMonthChange?: ((year: number, month: number) => void) | undefined;
  onEventClick?: ((event: MonthGridEvent) => void) | undefined;
  /** Replaces the event chip. */
  renderEvent?: ((event: MonthGridEvent) => ReactNode) | undefined;
  /** Extra content under the day number, for example a coverage count. */
  renderDay?: ((day: MonthGridDay, events: readonly MonthGridEvent[]) => ReactNode) | undefined;
  /** Spoken text added to a day label. */
  dayHint?: ((day: MonthGridDay, events: readonly MonthGridEvent[]) => string | undefined) | undefined;
  locale?: string | undefined;
}

const DAY_MS = 86400000;
const pad = (n: number): string => String(n).padStart(2, '0');

export function isoDay(year: number, month: number, day: number): string {
  const d = new Date(Date.UTC(year, month, day));
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/** True for a real calendar day written as YYYY-MM-DD ("2026-02-30" and "2026-6-5" are not). */
export function isIsoDay(value: unknown): value is string {
  if (typeof value !== 'string' || !ISO_DAY.test(value)) return false;
  const [y = 0, m = 0, d = 0] = value.split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
}

function parse(iso: string): Date {
  const [y = 1970, m = 1, d = 1] = iso.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

export function addDays(iso: string, n: number): string {
  return new Date(parse(iso).getTime() + n * DAY_MS).toISOString().slice(0, 10);
}

function clockToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** The weeks of a month, each seven days, padded with the neighbouring months' days. */
export function monthWeeks(year: number, month: number, weekStart: 0 | 1 = 0, today: string = clockToday()): MonthGridDay[][] {
  const first = new Date(Date.UTC(year, month, 1));
  const lead = (first.getUTCDay() - weekStart + 7) % 7;
  const count = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const total = Math.ceil((lead + count) / 7) * 7;
  const weeks: MonthGridDay[][] = [];
  for (let i = 0; i < total; i++) {
    const date = isoDay(year, month, 1 - lead + i);
    const d = parse(date);
    const row = Math.floor(i / 7);
    (weeks[row] ??= []).push({
      date,
      day: d.getUTCDate(),
      inMonth: d.getUTCMonth() === month && d.getUTCFullYear() === year,
      today: date === today,
      weekday: d.getUTCDay(),
    });
  }
  return weeks;
}

const MAX_SPAN_DAYS = 366;

/** An event with its first and last covered day, both valid ISO days with start <= end. */
interface Span {
  event: MonthGridEvent;
  order: number;
  start: string;
  end: string;
}

/** The covered days of each event: `endDate` when it is a real day on or after `date`, else `date`; capped at a
    year. Events with no real `date` are dropped. */
function spansOf(events: readonly MonthGridEvent[]): Span[] {
  const out: Span[] = [];
  events.forEach((event, order) => {
    if (!isIsoDay(event.date)) return;
    let end = event.date;
    if (isIsoDay(event.endDate) && event.endDate > event.date) {
      const cap = addDays(event.date, MAX_SPAN_DAYS - 1);
      end = event.endDate < cap ? event.endDate : cap;
    }
    out.push({ event, order, start: event.date, end });
  });
  return out;
}

function packWeek(spans: readonly Span[], week: readonly string[], maxLanes: number): MonthGridWeekPlan {
  const first = week[0] ?? '';
  const last = week[week.length - 1] ?? '';
  const items = spans
    .filter((x) => x.start <= last && x.end >= first)
    .map((x) => {
      const col = Math.max(0, week.indexOf(x.start < first ? first : x.start));
      const endCol = week.indexOf(x.end > last ? last : x.end);
      return { ...x, col, span: Math.max(1, endCol - col + 1), continuesLeft: x.start < first, continuesRight: x.end > last };
    })
    .sort((a, b) => a.col - b.col || b.span - a.span || a.order - b.order);
  const laneEnds: number[] = [];
  const bars: MonthGridBar[] = [];
  const hidden = week.map(() => 0);
  for (const it of items) {
    let lane = laneEnds.findIndex((end) => end < it.col);
    if (lane === -1) lane = laneEnds.length;
    if (lane >= maxLanes) {
      for (let c = it.col; c < it.col + it.span; c++) hidden[c] = (hidden[c] ?? 0) + 1;
      continue;
    }
    laneEnds[lane] = it.col + it.span - 1;
    bars.push({ event: it.event, lane, col: it.col, span: it.span, continuesLeft: it.continuesLeft, continuesRight: it.continuesRight });
  }
  return { bars, lanes: laneEnds.length, hidden };
}

/**
 * Packs the events that touch one week (seven ISO days) into lanes. Events are placed by first column, longer
 * first, then in the order given, each in the lowest lane that is free for its whole width. A bar that does not
 * fit in `maxLanes` is counted in `hidden` for every column it covers. Events with no real ISO `date` are left out.
 */
export function planWeek(events: readonly MonthGridEvent[], week: readonly string[], maxLanes = 3): MonthGridWeekPlan {
  return packWeek(spansOf(events), week, maxLanes);
}

export function MonthGrid({
  year,
  month,
  label,
  today,
  weekStart = 0,
  events,
  maxEvents = 3,
  laneBars = false,
  selected,
  onSelectDay,
  onMonthChange,
  onEventClick,
  renderEvent,
  renderDay,
  dayHint,
  locale = 'en-US',
  className,
  ...rest
}: MonthGridProps) {
  const todayIso = today ?? clockToday();
  const weeks = useMemo(() => monthWeeks(year, month, weekStart, todayIso), [year, month, weekStart, todayIso]);
  const spans = useMemo(() => spansOf(events ?? []), [events]);
  // Events are indexed by the days of the shown weeks only, so an event costs at most 42 steps however long it is.
  const byDate = useMemo(() => {
    const m = new Map<string, MonthGridEvent[]>();
    const days = weeks.flat().map((d) => d.date);
    const firstDay = days[0];
    const lastDay = days[days.length - 1];
    if (!firstDay || !lastDay) return m;
    const origin = parse(firstDay).getTime();
    const index = (iso: string) => Math.round((parse(iso).getTime() - origin) / DAY_MS);
    for (const sp of spans) {
      if (sp.start > lastDay || sp.end < firstDay) continue;
      const from = Math.max(0, index(sp.start));
      const to = Math.min(days.length - 1, index(sp.end));
      for (let i = from; i <= to; i++) {
        const key = days[i] as string;
        const list = m.get(key);
        if (list) list.push(sp.event);
        else m.set(key, [sp.event]);
      }
    }
    return m;
  }, [spans, weeks]);
  const plans = useMemo(
    () => (laneBars ? weeks.map((w) => packWeek(spans, w.map((d) => d.date), maxEvents)) : []),
    [laneBars, weeks, spans, maxEvents],
  );
  const inMonthDates = useMemo(() => weeks.flat().filter((d) => d.inMonth).map((d) => d.date), [weeks]);

  const defaultFocus = (): string => {
    if (selected && inMonthDates.includes(selected)) return selected;
    if (inMonthDates.includes(todayIso)) return todayIso;
    return inMonthDates[0] ?? isoDay(year, month, 1);
  };
  const [focus, setFocus] = useState<string>(defaultFocus);
  const root = useRef<HTMLDivElement>(null);
  const moveFocus = useRef(false);

  // Keep the roving stop inside the shown month when the month changes.
  useEffect(() => {
    setFocus((f) => (inMonthDates.includes(f) ? f : defaultFocus()));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inMonthDates]);

  useEffect(() => {
    if (!moveFocus.current) return;
    moveFocus.current = false;
    root.current?.querySelector<HTMLElement>(`[data-date="${focus}"]`)?.focus();
  }, [focus, inMonthDates]);

  const fmtLong = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'full', timeZone: 'UTC' }), [locale]);
  const fmtWeekday = useMemo(() => new Intl.DateTimeFormat(locale, { weekday: 'short', timeZone: 'UTC' }), [locale]);
  const fmtWeekdayLong = useMemo(() => new Intl.DateTimeFormat(locale, { weekday: 'long', timeZone: 'UTC' }), [locale]);

  function go(target: string) {
    const d = parse(target);
    moveFocus.current = true;
    if (d.getUTCFullYear() !== year || d.getUTCMonth() !== month) {
      setFocus(target);
      onMonthChange?.(d.getUTCFullYear(), d.getUTCMonth());
    } else {
      setFocus(target);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const cell = (e.target as HTMLElement).closest<HTMLElement>('[data-date]');
    if (!cell || (e.target as HTMLElement) !== cell) return;
    const cur = cell.getAttribute('data-date') as string;
    const wd = parse(cur).getUTCDay();
    const rowStart = (wd - weekStart + 7) % 7;
    let next: string | null = null;
    switch (e.key) {
      case 'ArrowLeft': next = addDays(cur, -1); break;
      case 'ArrowRight': next = addDays(cur, 1); break;
      case 'ArrowUp': next = addDays(cur, -7); break;
      case 'ArrowDown': next = addDays(cur, 7); break;
      case 'Home': next = addDays(cur, -rowStart); break;
      case 'End': next = addDays(cur, 6 - rowStart); break;
      case 'PageUp': next = isoDay(parse(cur).getUTCFullYear(), parse(cur).getUTCMonth() - 1, Math.min(parse(cur).getUTCDate(), 28)); break;
      case 'PageDown': next = isoDay(parse(cur).getUTCFullYear(), parse(cur).getUTCMonth() + 1, Math.min(parse(cur).getUTCDate(), 28)); break;
      case 'Enter':
      case ' ':
        e.preventDefault();
        onSelectDay?.(cur);
        return;
      default: return;
    }
    e.preventDefault();
    go(next);
  }

  const headers = weeks[0] ?? [];
  return (
    <div {...rest} ref={root} className={cx('month-grid', className)} role="grid" aria-label={label} aria-colcount={7} aria-rowcount={weeks.length + 1} onKeyDown={onKeyDown}>
      <div role="row" className="month-grid-head">
        {headers.map((d) => (
          <div key={d.weekday} role="columnheader" className="month-grid-dow" aria-label={fmtWeekdayLong.format(parse(d.date))}>
            {fmtWeekday.format(parse(d.date))}
          </div>
        ))}
      </div>
      {weeks.map((week, w) => (
        <div role="row" className="month-grid-week" key={week[0]?.date} style={laneBars ? ({ '--month-grid-lanes': plans[w]?.lanes ?? 0 } as CSSProperties) : undefined}>
          {week.map((d, col) => {
            const list = byDate.get(d.date) ?? [];
            const plan = plans[w];
            const shown = laneBars ? [] : list.slice(0, maxEvents);
            const more = laneBars ? (plan?.hidden[col] ?? 0) : list.length - shown.length;
            const hint = dayHint?.(d, list);
            const spoken = [
              fmtLong.format(parse(d.date)),
              d.today ? 'today' : '',
              list.length ? `${list.length} ${list.length === 1 ? 'event' : 'events'}` : '',
              hint ?? '',
            ].filter(Boolean).join(', ');
            return (
              <div
                key={d.date}
                role="gridcell"
                tabIndex={focus === d.date ? 0 : -1}
                data-date={d.date}
                data-today={d.today || undefined}
                data-outside={d.inMonth ? undefined : ''}
                aria-label={spoken}
                aria-selected={selected ? selected === d.date : undefined}
                aria-current={d.today ? 'date' : undefined}
                className="month-grid-day"
                onClick={(ev) => {
                  if ((ev.target as HTMLElement).closest('button')) return;
                  setFocus(d.date);
                  onSelectDay?.(d.date);
                }}
              >
                <span className="month-grid-num">{d.day}</span>
                {renderDay?.(d, list)}
                {laneBars && plan && plan.lanes > 0 && (() => {
                  const here = plan.bars.filter((b) => b.col === col);
                  // A cell with no bar of its own still reserves the lanes, so a bar from the left runs over empty space.
                  if (here.length === 0) return <div className="month-grid-lane-gap" aria-hidden="true" />;
                  return (
                    <ul className="month-grid-lanes" aria-label="Events">
                      {here.map((b) => (
                        <li
                          key={b.event.id}
                          className="month-grid-event month-grid-bar"
                          data-tone={b.event.tone ?? 'neutral'}
                          data-left={b.continuesLeft ? '' : undefined}
                          data-right={b.continuesRight ? '' : undefined}
                          style={{ '--month-grid-lane': b.lane, '--month-grid-span': b.span } as CSSProperties}
                        >
                          {renderEvent ? renderEvent(b.event) : onEventClick ? (
                            <button type="button" className="month-grid-chip" onClick={() => onEventClick(b.event)}>{b.event.label}</button>
                          ) : (
                            <span className="month-grid-chip">{b.event.label}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  );
                })()}
                {shown.length > 0 && (
                  <ul className="month-grid-events" aria-label="Events">
                    {shown.map((ev) => (
                      <li key={ev.id} className="month-grid-event" data-tone={ev.tone ?? 'neutral'}>
                        {renderEvent ? renderEvent(ev) : onEventClick ? (
                          <button type="button" className="month-grid-chip" onClick={() => onEventClick(ev)}>{ev.label}</button>
                        ) : (
                          <span className="month-grid-chip">{ev.label}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                {more > 0 && <span className="month-grid-more">+{more} more</span>}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
