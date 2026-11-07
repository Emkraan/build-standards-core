/* A dashboard as a workbook: a Summary tab (what was exported, plus every number tile) and a tab per panel as drawn.
   The sheets go to `downloadXlsx` of the export entry. Row tabs are real tables; no pivot tables. */

import type { Sheet } from '../export';
import { panelRows } from './panelData';
import type { DashboardDefinition, DashboardRun } from './types';
import { panelId } from './types';

export interface DashboardSheetsOptions {
  /** The words of the range, for the Summary. Default the range value. */
  rangeLabel?: string | undefined;
  /** The filter picks, for the Summary. */
  picks?: Readonly<Record<string, string>> | undefined;
}

export function dashboardSheets(def: DashboardDefinition, run: DashboardRun, options: DashboardSheetsOptions = {}): Sheet[] {
  const picks = Object.entries(options.picks ?? {}).filter(([, v]) => v);
  const summary: unknown[][] = [
    [def.title],
    ['Range', options.rangeLabel ?? run.range],
    ['Filters', picks.map(([k, v]) => `${k}=${v}`).join('; ') || 'none'],
    ['Generated', run.generatedAt],
    [],
    ['Measure', 'Value', 'Previous period', 'Change'],
  ];
  const sheets: Sheet[] = [{ name: 'Summary', rows: summary, header: false }];
  def.panels.forEach((p, i) => {
    const res = run.panels[panelId(p, i)];
    if (!res || res.error) return;
    if (res.stat) summary.push([p.title, res.stat.value, res.stat.previous ?? null, res.stat.change ?? null]);
    else sheets.push({ name: p.title, rows: panelRows(p, res), table: true });
  });
  return sheets;
}
