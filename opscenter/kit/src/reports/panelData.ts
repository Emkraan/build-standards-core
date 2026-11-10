/* Turning a panel result into what a chart reads, and into the rows a spreadsheet gets. */

import type { DashboardPanel, PanelResult } from './types';

/** Rows as objects keyed by column name. */
export function rowsToObjects(res: PanelResult): Record<string, string | number | null>[] {
  return res.rows.map((r) => {
    const o: Record<string, string | number | null> = {};
    res.columns.forEach((c, i) => {
      const v = r[i];
      o[c.name] = typeof v === 'number' || v === null ? (v as number | null) : String(v ?? '');
    });
    return o;
  });
}

/** The x column and the series columns of a panel: its own `x` and `y` when the result has them, else the first column and the rest. */
export function seriesOf(panel: DashboardPanel, res: PanelResult): { x: string; y: string[] } {
  const names = res.columns.map((c) => c.name);
  const x = panel.x && names.includes(panel.x) ? panel.x : (names[0] ?? '');
  const y = (panel.y ?? []).filter((n) => names.includes(n));
  return { x, y: y.length ? y : names.filter((n) => n !== x) };
}

/** The category values of a panel's x column, in order, without repeats: what a click on the panel can set. */
export function categoriesOf(panel: DashboardPanel, res: PanelResult): string[] {
  const { x } = seriesOf(panel, res);
  const at = res.columns.findIndex((c) => c.name === x);
  if (at < 0) return [];
  return [...new Set(res.rows.map((r) => String(r[at] ?? '')).filter(Boolean))];
}

/** The rows behind a panel exactly as drawn, headed for a spreadsheet. */
export function panelRows(panel: DashboardPanel, res: PanelResult): unknown[][] {
  if (res.stat) {
    return [
      ['Measure', 'Value', 'Previous period', res.stat.percent ? 'Change (points)' : 'Change (%)'],
      [panel.title, res.stat.value, res.stat.previous ?? null, res.stat.change ?? null],
    ];
  }
  return [res.columns.map((c) => c.name), ...res.rows.map((r) => [...r])];
}

/** A number as a short, grouped string. */
export function formatCell(v: unknown): string {
  if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString() : String(Math.round(v * 10) / 10);
  return v === null || v === undefined ? '' : String(v);
}
