/* MonthGrid: a generic month calendar. Weeks of day cells with event slots, a today marker and roving
   keyboard navigation (arrows, Home, End, PageUp, PageDown). It knows dates and layout only; what an
   event means (coverage, shifts, leave) stays in the app and arrives through the event list and the
   renderEvent and renderDay slots. Dates are ISO day strings (YYYY-MM-DD), so no time zone shifts a
   cell. The title and the month buttons are the app's; this part is the grid. */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { HTMLAttributes, KeyboardEvent, ReactNode } from 'react';
import { cx } from '../lib/env';

export type MonthGridTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info';

export interface MonthGridEvent {
  id: string;
  /** ISO day, YYYY-MM-DD. */
  date: string;
  label: string;
  tone?: MonthGridTone | undefined;
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
  /** Events shown in a cell before "+N more". Default 3. */
  maxEvents?: number | undefined;
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

export function MonthGrid({
  year,
  month,
  label,
  today,
  weekStart = 0,
  events,
  maxEvents = 3,
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
  const byDate = useMemo(() => {
    const m = new Map<string, MonthGridEvent[]>();
    for (const e of events ?? []) {
      const list = m.get(e.date);
      if (list) list.push(e);
      else m.set(e.date, [e]);
    }
    return m;
  }, [events]);
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
      {weeks.map((week) => (
        <div role="row" className="month-grid-week" key={week[0]?.date}>
          {week.map((d) => {
            const list = byDate.get(d.date) ?? [];
            const shown = list.slice(0, maxEvents);
            const more = list.length - shown.length;
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
