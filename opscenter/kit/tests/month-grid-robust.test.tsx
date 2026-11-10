/* MonthGrid review fixes: bad dates never throw or misplace a bar, events are indexed by the shown weeks only,
   no empty event lists are announced, and the bar width reads the grid's own cell variables. */
import { render } from '@testing-library/react';
import axe from 'axe-core';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { MonthGrid, isIsoDay, planWeek } from '../src';
import type { MonthGridEvent } from '../src';

const week = ['2026-10-11', '2026-10-12', '2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16', '2026-10-17'];
const ev = (id: string, date: string, endDate?: string): MonthGridEvent => ({ id, date, endDate, label: id });
const cell = (d: string) => document.querySelector<HTMLElement>(`[data-date="${d}"]`) as HTMLElement;
const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');
const rule = (selector: string): string => css.split('\n').filter((l) => l.startsWith(selector)).join('\n');

describe('isIsoDay', () => {
  it('accepts real ISO days only', () => {
    for (const ok of ['2026-10-14', '2024-02-29', '2000-01-01']) expect(isIsoDay(ok)).toBe(true);
    for (const bad of ['2026-6-5', '2026-02-30', '2026-13-01', '2026-10-14T09:00:00Z', ' 2026-10-14', 'nope', '', undefined, null, 20261014]) {
      expect(isIsoDay(bad)).toBe(false);
    }
  });
});

describe('bad dates', () => {
  it('leaves events without a real date out of the plan and treats a bad end as one day', () => {
    const p = planWeek(
      [ev('short', '2026-10-14'), ev('time', '2026-10-14T09:00:00Z'), ev('loose', '2026-10-5'), ev('junk', 'soon'), ev('bad-end', '2026-10-15', '2026-10-9x'), ev('ok', '2026-10-12', '2026-10-13')],
      week,
    );
    expect(p.bars.map((b) => [b.event.id, b.col, b.span])).toEqual([['ok', 1, 2], ['short', 3, 1], ['bad-end', 4, 1]]);
  });

  it('renders without throwing and puts a bar where its date says', () => {
    const events = [ev('time', '2026-10-14T09:00:00Z', '2026-10-16'), ev('end', '2026-10-13', 'later'), ev('fine', '2026-10-14', '2026-10-15')];
    expect(() => render(<MonthGrid year={2026} month={9} label="Cal" today="2026-10-01" events={events} laneBars />)).not.toThrow();
    expect(cell('2026-10-14').querySelector('.month-grid-bar')?.textContent).toBe('fine');
    expect(cell('2026-10-13').querySelector('.month-grid-bar')?.textContent).toBe('end');
    expect(document.body.textContent).not.toContain('time');
  });

  it('does not throw in chip mode either', () => {
    const events = [ev('a', '2026-10-14', 'never'), ev('b', 'x', '2026-10-16')];
    expect(() => render(<MonthGrid year={2026} month={9} label="Cal" today="2026-10-01" events={events} />)).not.toThrow();
    expect(cell('2026-10-14').textContent).toContain('a');
  });
});

describe('day index', () => {
  it('shows a year long event on a day in view and nowhere outside the shown weeks', () => {
    const events = [ev('Year', '2026-01-01', '2026-12-31'), ev('Old', '2020-01-01', '2020-12-31')];
    render(<MonthGrid year={2026} month={9} label="Cal" today="2026-10-01" events={events} />);
    expect(cell('2026-10-15').textContent).toContain('Year');
    expect(cell('2026-10-31').textContent).toContain('Year');
    expect(document.body.textContent).not.toContain('Old');
  });

  it('caps an event at a year from its first day', () => {
    const events = [ev('Long', '2025-01-01', '2030-01-01')];
    render(<MonthGrid year={2026} month={0} label="Cal" today="2026-01-01" events={events} />);
    expect(cell('2026-01-01').textContent).toContain('Long');
    const { unmount } = render(<MonthGrid year={2027} month={0} label="Cal2" today="2027-01-01" events={events} />);
    expect(document.querySelectorAll('[data-date="2027-01-15"]')[0]?.textContent).not.toContain('Long');
    unmount();
  });

  it('keeps input order within a day', () => {
    const events = [ev('first', '2026-10-14'), ev('second', '2026-10-10', '2026-10-20'), ev('third', '2026-10-14')];
    render(<MonthGrid year={2026} month={9} label="Cal" today="2026-10-01" events={events} />);
    const names = Array.from(cell('2026-10-14').querySelectorAll('.month-grid-chip')).map((c) => c.textContent);
    expect(names).toEqual(['first', 'second', 'third']);
  });
});

describe('announced lists', () => {
  it('renders no empty event list in any cell, with or without lane bars', async () => {
    const events = [ev('Release', '2026-10-12', '2026-10-15'), ev('Away', '2026-10-15', '2026-10-21')];
    for (const laneBars of [true, false]) {
      const { container, unmount } = render(<MonthGrid year={2026} month={9} label="Cal" today="2026-10-01" events={events} laneBars={laneBars} />);
      const lists = Array.from(container.querySelectorAll('ul'));
      expect(lists.length).toBeGreaterThan(0);
      for (const ul of lists) expect(ul.querySelectorAll('li').length).toBeGreaterThan(0);
      if (laneBars) {
        const gap = cell('2026-10-14').querySelector('.month-grid-lane-gap');
        expect(gap?.getAttribute('aria-hidden')).toBe('true');
        expect(cell('2026-10-14').querySelector('ul')).toBeNull();
      }
      const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } });
      expect(result.violations).toEqual([]);
      unmount();
    }
  });
});

describe('bar geometry', () => {
  it('derives the bar width and the cell box from the same grid variables', () => {
    const grid = rule('.month-grid {');
    expect(grid).toContain('--month-grid-cell-pad:');
    expect(grid).toContain('--month-grid-cell-line:');
    expect(rule('.month-grid-day {')).toMatch(/padding: var\(--month-grid-cell-pad\)/);
    expect(rule('.month-grid-day {')).toMatch(/border-right: var\(--month-grid-cell-line\)/);
    const bar = css.slice(css.indexOf('.month-grid-bar {'), css.indexOf('}', css.indexOf('.month-grid-bar {')));
    expect(bar).toContain('var(--month-grid-cell-pad)');
    expect(bar).toContain('var(--month-grid-cell-line)');
    expect(bar).not.toMatch(/var\(--space-2\)|\b1px\b/);
  });
});
