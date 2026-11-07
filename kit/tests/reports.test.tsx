/* The `reports` entry: dashboard client with click to cross-filter, deep links, panels and the workbook. */
import { fireEvent, render, screen, within } from '@testing-library/react';
import axe from 'axe-core';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Dashboard, DashboardFilterBar, PanelView, activePicks, dashboardLink, dashboardSheets, drillLink, panelRows, readDashboardView, readDrill, setPick, togglePick, writeDashboardView } from '../src/reports';
import type { DashboardDefinition, DashboardRun } from '../src/reports';
import { buildXlsx } from '../src/export';
import { installMatchMedia, resetMedia } from './helpers';

beforeEach(() => {
  resetMedia();
  installMatchMedia();
});

const def: DashboardDefinition = {
  key: 'ops',
  title: 'Operations',
  description: 'How it is going',
  filters: [{ id: 'dept', label: 'Department' }],
  panels: [
    { id: 'total', title: 'Total', type: 'stat', stream: 's', measure: 'rows', stat: { warnAt: 10, badAt: 100 } },
    { id: 'by-dept', title: 'By department', type: 'bar', stream: 's', measure: 'by_dept', drill: 'dept', w: 6 },
    { id: 'rank', title: 'Ranked', type: 'table', stream: 's', measure: 'rank', drill: 'dept', w: 6 },
    { title: 'Broken', type: 'line', stream: 's', measure: 'x' },
  ],
};
const run: DashboardRun = {
  generatedAt: '2026-11-07T10:00:00Z',
  range: '30',
  options: { dept: ['IT', 'HR'] },
  panels: {
    total: { columns: [{ name: 'Rows' }], rows: [], stat: { value: 42, previous: 40, change: 5 } },
    'by-dept': { columns: [{ name: 'Department' }, { name: 'Rows' }], rows: [['IT', 7], ['HR', 3]] },
    rank: { columns: [{ name: 'Department' }, { name: 'Rows' }], rows: [['IT', 7], ['HR', 3]] },
    '3': { columns: [], rows: [], error: 'The stream is not available' },
  },
};
const ranges = [{ value: '7', label: '7 days' }, { value: '30', label: '30 days' }];

describe('cross-filter picks', () => {
  it('sets a pick, clears it on the same value, and drops empty values', () => {
    expect(togglePick({}, 'dept', 'IT')).toEqual({ dept: 'IT' });
    expect(togglePick({ dept: 'IT' }, 'dept', 'IT')).toEqual({});
    expect(togglePick({ dept: 'IT' }, 'dept', 'HR')).toEqual({ dept: 'HR' });
    expect(setPick({ a: '1' }, 'a', '')).toEqual({});
    expect(activePicks({ a: '1', b: '' })).toEqual([['a', '1']]);
  });
});

describe('deep links', () => {
  it('reads and writes the view in the address and keeps the other parameters', () => {
    const view = readDashboardView('?tab=x&d=ops&range=7&f.dept=IT&f.empty=');
    expect(view).toEqual({ d: 'ops', range: '7', f: { dept: 'IT' } });
    const next = writeDashboardView('?tab=x&d=old&f.gone=1', { d: 'ops', range: '30', f: { dept: 'HR', empty: '' } });
    expect(next.get('tab')).toBe('x');
    expect(next.get('d')).toBe('ops');
    expect(next.has('f.gone')).toBe(false);
    expect(next.get('f.dept')).toBe('HR');
    expect(next.has('f.empty')).toBe(false);
    expect(dashboardLink('https://app.example/reports?old=1#h', { d: 'ops', f: {} })).toBe('https://app.example/reports?d=ops');
  });

  it('round trips a drill target, and refuses a malformed or incomplete one', () => {
    const t = { stream: 's', measure: 'by_dept', filters: { dept: 'IT' }, name: 'Rows for \u00e9' };
    const link = drillLink('/explore?x=1', t);
    expect(link.startsWith('/explore?drill=')).toBe(true);
    expect(readDrill(link.slice(link.indexOf('?')))).toEqual(t);
    expect(readDrill('')).toBeNull();
    expect(readDrill('?drill=%%%')).toBeNull();
    expect(readDrill(`?drill=${btoa('{"stream":1}')}`)).toBeNull();
    expect(readDrill(`?drill=${btoa('null')}`)).toBeNull();
  });
});

describe('PanelView', () => {
  it('draws a number tile with the definition thresholds and the change', () => {
    render(<PanelView panel={def.panels[0]!} result={run.panels['total']} />);
    expect(screen.getByText('42')).toBeTruthy();
    expect(screen.getByText(/was 40/)).toBeTruthy();
    expect(screen.getByText(/5%/)).toBeTruthy();
  });

  it('shows a failed panel in its own card and a placeholder while loading', () => {
    const { rerender } = render(<PanelView panel={def.panels[3]!} result={run.panels['3']} />);
    expect(screen.getByRole('alert').textContent).toBe('The stream is not available');
    rerender(<PanelView panel={def.panels[3]!} />);
    expect(screen.getByText(/Loading Broken/)).toBeTruthy();
  });

  it('turns a table row label into a button that picks, and marks the pick', () => {
    const onPick = vi.fn();
    render(<PanelView panel={def.panels[2]!} result={run.panels['rank']} onPick={onPick} picked="HR" />);
    fireEvent.click(screen.getByRole('button', { name: 'IT' }));
    expect(onPick).toHaveBeenCalledWith('IT');
    expect(screen.getByRole('button', { name: 'HR' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('offers the chart click to the keyboard as a list of buttons', () => {
    const onPick = vi.fn();
    render(<PanelView panel={def.panels[1]!} result={run.panels['by-dept']} onPick={onPick} />);
    const group = screen.getByRole('group', { name: 'Filter by By department' });
    fireEvent.click(within(group).getByRole('button', { name: 'HR' }));
    expect(onPick).toHaveBeenCalledWith('HR');
  });

  it('says so when a range has nothing, and offers download and rows only on a good result', () => {
    const onExport = vi.fn();
    const onRows = vi.fn();
    const empty = { columns: [{ name: 'Day' }, { name: 'Rows' }], rows: [] as unknown[][] };
    const { rerender } = render(<PanelView panel={def.panels[3]!} result={empty} onExport={onExport} onRows={onRows} />);
    expect(screen.getByText('Nothing in this range')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Download Broken/ }));
    fireEvent.click(screen.getByRole('button', { name: 'View rows' }));
    expect(onExport).toHaveBeenCalled();
    expect(onRows).toHaveBeenCalled();
    rerender(<PanelView panel={def.panels[3]!} result={{ ...empty, error: 'x' }} onExport={onExport} onRows={onRows} />);
    expect(screen.queryByRole('button', { name: /Download/ })).toBeNull();
  });
});

describe('DashboardFilterBar', () => {
  it('has a range, a choice per filter and no Run button; a choice and a chip change the picks', () => {
    const onPicks = vi.fn();
    const onRange = vi.fn();
    render(<DashboardFilterBar ranges={ranges} range="30" onRange={onRange} filters={def.filters} options={run.options} picks={{ dept: 'IT' }} onPicks={onPicks} />);
    expect(screen.queryByRole('button', { name: /^Run/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '7 days' }));
    expect(onRange).toHaveBeenCalledWith('7');
    fireEvent.change(screen.getByLabelText('Department'), { target: { value: 'HR' } });
    expect(onPicks).toHaveBeenLastCalledWith({ dept: 'HR' });
    fireEvent.click(screen.getByRole('button', { name: /Remove filter Department: IT/ }));
    expect(onPicks).toHaveBeenLastCalledWith({});
    fireEvent.click(screen.getByRole('button', { name: 'Clear all' }));
    expect(onPicks).toHaveBeenLastCalledWith({});
  });

  it('keeps a picked value that the run does not offer, and shows no dashboard chooser for one dashboard', () => {
    render(<DashboardFilterBar dashboards={[{ key: 'ops', title: 'Operations' }]} onDashboard={vi.fn()} filters={def.filters} options={{ dept: ['IT'] }} picks={{ dept: 'Legal' }} onPicks={vi.fn()} />);
    expect(screen.queryByLabelText('Dashboard')).toBeNull();
    expect((screen.getByLabelText('Department') as HTMLSelectElement).value).toBe('Legal');
  });
});

describe('Dashboard', () => {
  it('opens populated, narrows every panel by one click, and clears on a second click', () => {
    const onPicks = vi.fn();
    const { rerender } = render(<Dashboard definition={def} run={run} range="30" ranges={ranges} picks={{}} onPicks={onPicks} />);
    expect(screen.getByRole('heading', { level: 3, name: 'By department' })).toBeTruthy();
    expect(screen.getByRole('heading', { level: 3, name: 'Ranked' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^Run/ })).toBeNull();
    fireEvent.click(within(screen.getByRole('table', { name: 'Ranked' })).getByRole('button', { name: 'IT' }));
    expect(onPicks).toHaveBeenLastCalledWith({ dept: 'IT' });
    rerender(<Dashboard definition={def} run={run} range="30" ranges={ranges} picks={{ dept: 'IT' }} onPicks={onPicks} />);
    fireEvent.click(within(screen.getByRole('table', { name: 'Ranked' })).getByRole('button', { name: 'IT' }));
    expect(onPicks).toHaveBeenLastCalledWith({});
  });

  it('shows placeholders without a run, the future dated note with a link, and refreshes on its timer while visible', () => {
    vi.useFakeTimers();
    const onRefresh = vi.fn();
    const onFutureRows = vi.fn();
    const { rerender } = render(<Dashboard definition={{ ...def, refreshSeconds: 60 }} picks={{}} onPicks={vi.fn()} onRefresh={onRefresh} />);
    expect(screen.getAllByText(/Loading/).length).toBeGreaterThan(0);
    rerender(<Dashboard definition={{ ...def, refreshSeconds: 60 }} run={{ ...run, futureDated: [{ stream: 's', field: 'at', rows: 1500 }] }} picks={{}} onPicks={vi.fn()} onRefresh={onRefresh} onFutureRows={onFutureRows} />);
    expect(screen.getByRole('status').textContent).toContain('1,500 events are dated in the future');
    fireEvent.click(screen.getAllByRole('button', { name: 'View rows' })[0] as HTMLElement);
    expect(onFutureRows).toHaveBeenCalled();
    vi.advanceTimersByTime(60_000);
    expect(onRefresh).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it('has no axe violations', async () => {
    const { container } = render(<Dashboard definition={def} run={run} range="30" ranges={ranges} picks={{ dept: 'IT' }} onPicks={vi.fn()} />);
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
    expect(result.violations.map((v) => v.id)).toEqual([]);
  });
});

describe('dashboard workbook', () => {
  it('makes a Summary tab with the number tiles and a table tab per panel that worked', () => {
    const sheets = dashboardSheets(def, run, { rangeLabel: '30 days', picks: { dept: 'IT', none: '' } });
    expect(sheets.map((s) => s.name)).toEqual(['Summary', 'By department', 'Ranked']);
    const summary = sheets[0]?.rows ?? [];
    expect(summary[1]).toEqual(['Range', '30 days']);
    expect(summary[2]).toEqual(['Filters', 'dept=IT']);
    expect(summary.at(-1)).toEqual(['Total', 42, 40, 5]);
    expect(sheets[1]?.table).toBe(true);
    expect(sheets[1]?.rows[0]).toEqual(['Department', 'Rows']);
    expect(buildXlsx(sheets).length).toBeGreaterThan(100);
  });

  it('writes the rows of a panel as drawn, with the change column named for a percentage', () => {
    expect(panelRows(def.panels[0]!, { columns: [], rows: [], stat: { value: 3, previous: 2, change: 1, percent: true } })[0]?.[3]).toBe('Change (points)');
  });
});

describe('stylesheet', () => {
  it('keeps the chart click twin out of sight until it takes focus', () => {
    const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');
    expect(css).toMatch(/\.dash-pick \{[^}]*clip-path: inset\(50%\)/);
    expect(css).toMatch(/\.dash-pick:focus-within \{[^}]*position: static/);
  });
});
