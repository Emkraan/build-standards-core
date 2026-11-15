/* MonthGrid: layout of the weeks, the today marker, event slots and the keyboard model. */
import { fireEvent, render, screen } from '@testing-library/react';
import axe from 'axe-core';
import { describe, expect, it, vi } from 'vitest';
import { MonthGrid, addDays, monthWeeks } from '../src';

const events = [
  { id: 'a', date: '2026-10-23', label: 'Alpha', tone: 'accent' as const },
  { id: 'b', date: '2026-10-23', label: 'Bravo' },
  { id: 'c', date: '2026-10-23', label: 'Charlie' },
  { id: 'd', date: '2026-10-23', label: 'Delta' },
];
const cell = (d: string) => document.querySelector<HTMLElement>(`[data-date="${d}"]`) as HTMLElement;

describe('monthWeeks', () => {
  it('pads to whole weeks and flags the month and today', () => {
    const w = monthWeeks(2026, 9, 0, '2026-10-23');
    expect(w.every((r) => r.length === 7)).toBe(true);
    expect(w[0]?.[0]?.date).toBe('2026-09-27');
    expect(w.flat().filter((d) => d.inMonth)).toHaveLength(31);
    expect(w.flat().filter((d) => d.today).map((d) => d.date)).toEqual(['2026-10-23']);
  });
  it('starts on Monday when asked', () => {
    expect(monthWeeks(2026, 9, 1, '')[0]?.[0]?.date).toBe('2026-09-28');
  });
  it('adds days across a month edge', () => {
    expect(addDays('2026-10-31', 1)).toBe('2026-11-01');
  });
});

describe('MonthGrid', () => {
  it('renders a labelled grid with weekday headers and a today marker', async () => {
    const { container } = render(<MonthGrid year={2026} month={9} label="Team calendar" today="2026-10-23" events={events} />);
    expect(screen.getByRole('grid', { name: 'Team calendar' })).toBeTruthy();
    expect(screen.getAllByRole('columnheader')).toHaveLength(7);
    expect(cell('2026-10-23').getAttribute('aria-current')).toBe('date');
    expect(cell('2026-10-23').getAttribute('aria-label')).toContain('today');
    const r = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } });
    expect(r.violations.map((v) => v.id)).toEqual([]);
  });
  it('caps events per cell and says how many more', () => {
    render(<MonthGrid year={2026} month={9} label="c" today="2026-10-23" events={events} maxEvents={2} />);
    expect(screen.getByText('+2 more')).toBeTruthy();
    expect(screen.queryByText('Charlie')).toBeNull();
    expect(cell('2026-10-23').getAttribute('aria-label')).toContain('4 events');
  });
  it('fills the renderEvent and renderDay slots and fires onEventClick', () => {
    const onEventClick = vi.fn();
    render(<MonthGrid year={2026} month={9} label="c" today="2026-10-23" events={events} onEventClick={onEventClick} renderDay={(d) => (d.today ? <i>cover 3</i> : null)} />);
    expect(screen.getByText('cover 3')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Alpha' }));
    expect(onEventClick).toHaveBeenCalledWith(events[0]);
  });
  it('moves focus with arrows, Home and End, one tab stop', () => {
    render(<MonthGrid year={2026} month={9} label="c" today="2026-10-23" />);
    expect(document.querySelectorAll('[role="gridcell"][tabindex="0"]')).toHaveLength(1);
    cell('2026-10-23').focus();
    fireEvent.keyDown(cell('2026-10-23'), { key: 'ArrowRight' });
    expect(document.activeElement).toBe(cell('2026-10-24'));
    fireEvent.keyDown(cell('2026-10-24'), { key: 'ArrowDown' });
    expect(document.activeElement).toBe(cell('2026-10-31'));
    fireEvent.keyDown(cell('2026-10-31'), { key: 'Home' });
    expect(document.activeElement).toBe(cell('2026-10-25'));
    fireEvent.keyDown(cell('2026-10-25'), { key: 'End' });
    expect(document.activeElement).toBe(cell('2026-10-31'));
  });
  it('asks for another month on PageDown and on an arrow off the edge', () => {
    const onMonthChange = vi.fn();
    render(<MonthGrid year={2026} month={9} label="c" today="2026-10-23" onMonthChange={onMonthChange} />);
    fireEvent.keyDown(cell('2026-10-23'), { key: 'PageDown' });
    expect(onMonthChange).toHaveBeenLastCalledWith(2026, 10);
    fireEvent.keyDown(cell('2026-10-01'), { key: 'ArrowUp' });
    expect(onMonthChange).toHaveBeenLastCalledWith(2026, 8);
  });
  it('selects a day on Enter, Space and click', () => {
    const onSelectDay = vi.fn();
    render(<MonthGrid year={2026} month={9} label="c" today="2026-10-23" onSelectDay={onSelectDay} selected="2026-10-05" />);
    fireEvent.keyDown(cell('2026-10-05'), { key: 'Enter' });
    fireEvent.keyDown(cell('2026-10-05'), { key: ' ' });
    fireEvent.click(cell('2026-10-12'));
    expect(onSelectDay.mock.calls.map((c) => c[0])).toEqual(['2026-10-05', '2026-10-05', '2026-10-12']);
    expect(cell('2026-10-05').getAttribute('aria-selected')).toBe('true');
  });
});
