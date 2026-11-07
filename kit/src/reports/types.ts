/* The shapes a dashboard client and its server agree on (the reports module, definitions are data). A definition is
   plain JSON: a key, a title, filters and panels. A panel names a stream and a measure, never a store; the server
   resolves them. A run is the server's answer for one dashboard, one range and one set of filter picks. Extra fields
   on a definition are kept untouched. */

import type { MarkHue } from '../lib/hues';

export type PanelType = 'stat' | 'line' | 'area' | 'bar' | 'hbar' | 'donut' | 'table';

export interface StatOptions {
  hue?: MarkHue | undefined;
  /** A note under the number. */
  note?: string | undefined;
  /** Colour thresholds come with the definition, not from code: at or above `warnAt` the tile is amber, at or above `badAt` red, below both green. */
  warnAt?: number | undefined;
  badAt?: number | undefined;
}

export interface DashboardPanel {
  /** Names the panel in a run. Default its position in the definition. */
  id?: string | undefined;
  title: string;
  subtitle?: string | undefined;
  type: PanelType;
  stream: string;
  measure: string;
  /** Width in twelfths of the grid, 1 to 12. Default 4. */
  w?: number | undefined;
  /** Height in rows of 64px for charts and tables. Default 3. */
  h?: number | undefined;
  /** The result column on the x axis (or the category). Default the first column. */
  x?: string | undefined;
  /** The result columns drawn as series. Default every column after the first. */
  y?: readonly string[] | undefined;
  /** The id of the filter a click on this panel sets (click to cross-filter). Absent: the panel is not clickable. */
  drill?: string | undefined;
  stat?: StatOptions | undefined;
}

export interface DashboardFilter {
  id: string;
  label: string;
  stream?: string | undefined;
  field?: string | undefined;
}

export interface DashboardDefinition {
  key: string;
  title: string;
  description?: string | undefined;
  /** Seconds between background refreshes. Absent or 0: none. */
  refreshSeconds?: number | undefined;
  /** The range a dashboard opens on, one of the server's presets. */
  defaultRange?: string | undefined;
  filters?: readonly DashboardFilter[] | undefined;
  panels: readonly DashboardPanel[];
}

/** A dashboard as the server lists it. */
export interface DashboardRow {
  key: string;
  title: string;
  description?: string | undefined;
  def: DashboardDefinition;
  /** Shipped with the app, as opposed to made here. */
  isDefault?: boolean | undefined;
  /** A shipped one that was edited (it can be reset). */
  modified?: boolean | undefined;
  canEdit?: boolean | undefined;
}

export interface PanelColumn {
  name: string;
  type?: string | undefined;
}

export interface PanelResult {
  columns: readonly PanelColumn[];
  rows: readonly (readonly unknown[])[];
  truncated?: boolean | undefined;
  /** A number tile's value, the previous period and the change. `percent` says the number is a percentage. */
  stat?: { value: number | null; previous?: number | null | undefined; change?: number | null | undefined; percent?: boolean | undefined } | undefined;
  /** This panel failed; the others still work. */
  error?: string | undefined;
  stale?: boolean | undefined;
  fetchedAt?: number | undefined;
}

export interface FutureDated {
  stream: string;
  field: string;
  rows: number;
  devices?: number | undefined;
}

export interface DashboardRun {
  generatedAt: string;
  range: string;
  /** The values each filter offers, by filter id. */
  options: Readonly<Record<string, readonly string[]>>;
  /** Results by panel id. */
  panels: Readonly<Record<string, PanelResult>>;
  /** Events dated in the future (a wrong clock) that were left off the charts and counts. */
  futureDated?: readonly FutureDated[] | undefined;
}

/** The id a panel has in a run. */
export const panelId = (panel: DashboardPanel, index: number): string => panel.id ?? String(index);
