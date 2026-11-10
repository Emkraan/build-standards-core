/* MonthGrid multi-day events: planWeek packing, endDate chips, and the laneBars rendering. */
import { render, screen, within } from '@testing-library/react';
import axe from 'axe-core';
import { describe, expect, it } from 'vitest';
import { MonthGrid, planWeek } from '../src';
import type { MonthGridEvent } from '../src';

// The week of Sun 2026-10-11 to Sat 2026-10-17.
const week = ['2026-10-11', '2026-10-12', '2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16', '2026-10-17'];
const ev = (id: string, date: string, endDate?: string): MonthGridEvent => ({ id, date, endDate, label: id });
const cell = (d: string) => document.querySelector<HTMLElement>(`[data-date="${d}"]`) as HTMLElement;

describe('planWeek', () => {
  it('puts non-overlapping events in one lane and overlapping ones below', () => {
    const p = planWeek([ev('a', '2026-10-11', '2026-10-12'), ev('b', '2026-10-13', '2026-10-14'), ev('c', '2026-10-12', '2026-10-13')], week);
    expect(p.lanes).toBe(2);
    const by = Object.fromEntries(p.bars.map((b) => [b.event.id, b]));
    expect([by['a']?.lane, by['a']?.col, by['a']?.span]).toEqual([0, 0, 2]);
    expect([by['b']?.lane, by['b']?.col, by['b']?.span]).toEqual([0, 2, 2]);
    expect([by['c']?.lane, by['c']?.col, by['c']?.span]).toEqual([1, 1, 2]);
  });

  it('places the longer bar first when two start on the same day', () => {
    const p = planWeek([ev('short', '2026-10-12'), ev('long', '2026-10-12', '2026-10-15')], week);
    expect(p.bars.find((b) => b.event.id === 'long')?.lane).toBe(0);
    expect(p.bars.find((b) => b.event.id === 'short')?.lane).toBe(1);
  });

  it('clips to the week and flags the sides it continues past', () => {
    const p = planWeek([ev('x', '2026-10-09', '2026-10-13'), ev('y', '2026-10-16', '2026-10-20')], week);
    const x = p.bars.find((b) => b.event.id === 'x');
    const y = p.bars.find((b) => b.event.id === 'y');
    expect([x?.col, x?.span, x?.continuesLeft, x?.continuesRight]).toEqual([0, 3, true, false]);
    expect([y?.col, y?.span, y?.continuesLeft, y?.continuesRight]).toEqual([5, 2, false, true]);
  });

  it('leaves out events outside the week, and treats a bad end as one day', () => {
    const p = planWeek([ev('before', '2026-10-01', '2026-10-10'), ev('after', '2026-10-18'), ev('bad', '2026-10-14', '2026-10-01')], week);
    expect(p.bars.map((b) => b.event.id)).toEqual(['bad']);
    expect(p.bars[0]?.span).toBe(1);
  });

  it('counts bars past maxLanes as hidden on every day they cover', () => {
    const p = planWeek([ev('a', '2026-10-12', '2026-10-14'), ev('b', '2026-10-12', '2026-10-14'), ev('c', '2026-10-13', '2026-10-15')], week, 2);
    expect(p.lanes).toBe(2);
    expect(p.bars).toHaveLength(2);
    expect(p.hidden).toEqual([0, 0, 1, 1, 1, 0, 0]);
  });

  it('reuses a lane once the earlier bar has ended', () => {
    const p = planWeek([ev('a', '2026-10-11', '2026-10-12'), ev('b', '2026-10-13'), ev('c', '2026-10-11', '2026-10-17')], week);
    expect(p.bars.find((b) => b.event.id === 'c')?.lane).toBe(0);
    expect(p.lanes).toBe(2);
    expect(p.bars.find((b) => b.event.id === 'b')?.lane).toBe(1);
  });
});

describe('MonthGrid endDate without laneBars', () => {
  it('shows a chip on each covered day and counts it in the day label', () => {
    render(<MonthGrid year={2026} month={9} label="Cal" today="2026-10-01" events={[ev('Trip', '2026-10-13', '2026-10-15')]} />);
    for (const d of ['2026-10-13', '2026-10-14', '2026-10-15']) expect(within(cell(d)).getByText('Trip')).toBeTruthy();
    expect(within(cell('2026-10-16')).queryByText('Trip')).toBeNull();
    expect(cell('2026-10-14').getAttribute('aria-label')).toContain('1 event');
    expect(document.querySelector('.month-grid-lanes')).toBeNull();
  });
});

describe('MonthGrid laneBars', () => {
  const events = [ev('Release', '2026-10-12', '2026-10-15'), ev('Review', '2026-10-14'), ev('Away', '2026-10-15', '2026-10-21')];

  it('draws one bar at the first day with its lane and span, and a continuation in the next week', async () => {
    const { container } = render(<MonthGrid year={2026} month={9} label="Cal" today="2026-10-01" events={events} laneBars />);
    const bar = within(cell('2026-10-12')).getByText('Release').closest('li') as HTMLElement;
    expect(bar.style.getPropertyValue('--month-grid-span')).toBe('4');
    expect(bar.style.getPropertyValue('--month-grid-lane')).toBe('0');
    expect(within(cell('2026-10-13')).queryByText('Release')).toBeNull();
    const away = within(cell('2026-10-15')).getByText('Away').closest('li') as HTMLElement;
    expect(away.dataset['right']).toBe('');
    const cont = within(cell('2026-10-18')).getByText('Away').closest('li') as HTMLElement;
    expect(cont.dataset['left']).toBe('');
    expect(cont.style.getPropertyValue('--month-grid-span')).toBe('4');
    expect(cell('2026-10-13').getAttribute('aria-label')).toContain('1 event');
    const r = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } });
    expect(r.violations.map((v) => v.id)).toEqual([]);
  });

  it('uses maxEvents as the lane count and reports the rest as +N more', () => {
    const many = [ev('A', '2026-10-13', '2026-10-14'), ev('B', '2026-10-13', '2026-10-14'), ev('C', '2026-10-13', '2026-10-14')];
    render(<MonthGrid year={2026} month={9} label="Cal" today="2026-10-01" events={many} laneBars maxEvents={2} />);
    expect(screen.queryByText('C')).toBeNull();
    expect(within(cell('2026-10-13')).getByText('+1 more')).toBeTruthy();
    expect(within(cell('2026-10-14')).getByText('+1 more')).toBeTruthy();
  });

  it('keeps the event click and the renderEvent slot on a bar', () => {
    let hit = '';
    render(<MonthGrid year={2026} month={9} label="Cal" today="2026-10-01" events={[ev('Click', '2026-10-13', '2026-10-14')]} laneBars onEventClick={(e) => { hit = e.id; }} />);
    screen.getByRole('button', { name: 'Click' }).click();
    expect(hit).toBe('Click');
  });

  it('renders no lane layer when there are no events', () => {
    render(<MonthGrid year={2026} month={9} label="Cal" today="2026-10-01" laneBars />);
    expect(document.querySelector('.month-grid-lanes')).toBeNull();
  });
});
