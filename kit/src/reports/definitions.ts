/* Definitions are data (R2): validated in the browser the same way the server validates them, written as JSON by key,
   exported and imported as one file. The browser check is a courtesy so the editor can say what is wrong before a save;
   the server is the guard and refuses a bad definition whole, never half stored. */

import type { DashboardDefinition, DashboardPanel, PanelType } from './types';

export const PANEL_TYPES: readonly PanelType[] = ['stat', 'line', 'area', 'bar', 'hbar', 'donut', 'table'];
export const PANEL_LABEL: Readonly<Record<PanelType, string>> = {
  stat: 'Number tile',
  line: 'Line chart',
  area: 'Area chart',
  bar: 'Column chart',
  hbar: 'Ranked bars',
  donut: 'Donut',
  table: 'Table',
};

const KEY_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;
export const MAX_PANELS = 50;

/** The problems with a definition, empty when it is fine. The wording matches the server's. */
export function validateDefinition(definition: unknown): string[] {
  if (!definition || typeof definition !== 'object' || Array.isArray(definition)) return ['a definition must be a JSON object'];
  const d = definition as Record<string, unknown>;
  const out: string[] = [];
  if (typeof d['key'] !== 'string' || !KEY_RE.test(d['key'])) out.push('key must be a lowercase slug (letters, digits, dash, underscore)');
  if (typeof d['title'] !== 'string' || !d['title'].trim()) out.push('title must be a non-empty string');
  const panels = d['panels'];
  if (!Array.isArray(panels)) {
    out.push('panels must be a list');
    return out;
  }
  if (panels.length > MAX_PANELS) out.push(`at most ${MAX_PANELS} panels`);
  panels.forEach((p, i) => {
    if (!p || typeof p !== 'object' || Array.isArray(p)) {
      out.push(`panel ${i + 1} must be an object`);
      return;
    }
    for (const f of ['title', 'stream']) {
      const v = (p as Record<string, unknown>)[f];
      if (typeof v !== 'string' || !v.trim()) out.push(`panel ${i + 1}: ${f} must be a non-empty string`);
    }
    const m = (p as Record<string, unknown>)['measure'];
    const sp = (p as Record<string, unknown>)['spec'];
    if (!(typeof m === 'string' && m.trim()) && !(sp && typeof sp === 'object' && !Array.isArray(sp))) out.push(`panel ${i + 1}: a measure (a name) or a spec (the report query) is required`);
    const type = (p as Record<string, unknown>)['type'];
    if (type !== undefined && !PANEL_TYPES.includes(type as PanelType)) out.push(`panel ${i + 1}: type must be one of ${PANEL_TYPES.join(', ')}`);
  });
  return out;
}

export interface ParsedDefinitions {
  definitions: DashboardDefinition[];
  /** What is wrong, by position and key. Empty when every definition is fine; then `definitions` is all of them. */
  problems: string[];
}

/** Reads an exported file: one definition, a list of them, or `{ dashboards: [...] }`. Nothing is returned for a file with any problem. */
export function parseDefinitions(text: string): ParsedDefinitions {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (e) {
    return { definitions: [], problems: [`not valid JSON: ${e instanceof Error ? e.message : 'unreadable'}`] };
  }
  const list = Array.isArray(raw) ? raw : raw && typeof raw === 'object' && Array.isArray((raw as { dashboards?: unknown }).dashboards) ? (raw as { dashboards: unknown[] }).dashboards : [raw];
  const problems: string[] = [];
  const seen = new Set<string>();
  list.forEach((d, i) => {
    const label = d && typeof d === 'object' && typeof (d as { key?: unknown }).key === 'string' ? (d as { key: string }).key : `#${i + 1}`;
    for (const p of validateDefinition(d)) problems.push(`${label}: ${p}`);
    if (label !== `#${i + 1}`) {
      if (seen.has(label)) problems.push(`${label}: key is used twice`);
      seen.add(label);
    }
  });
  return problems.length ? { definitions: [], problems } : { definitions: list as DashboardDefinition[], problems: [] };
}

/** The file text for an export: the definitions as pretty JSON. */
export function exportDefinitions(definitions: readonly DashboardDefinition[]): string {
  return `${JSON.stringify(definitions, null, 2)}\n`;
}

/** A starting panel of a type, for the editor's "Add panel". The stream and measure are the app's to choose. */
export function newPanel(type: PanelType, stream: string, measure: string, n: number): DashboardPanel {
  const base = { id: `panel-${n}`, title: `New ${PANEL_LABEL[type].toLowerCase()}`, type, stream, measure };
  if (type === 'stat') return { ...base, w: 3 };
  if (type === 'table' || type === 'hbar' || type === 'donut') return { ...base, w: 4, h: 4 };
  return { ...base, w: 8, h: 4 };
}

/** A new definition to start from. */
export function blankDefinition(key = 'new-dashboard', title = 'New dashboard'): DashboardDefinition {
  return { key, title, defaultRange: '30', refreshSeconds: 300, filters: [], panels: [] };
}

/** A slug for a title: lowercase letters, digits and dashes, at most 64 characters, never empty. */
export function slugFor(title: string): string {
  const s = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64).replace(/-+$/g, '');
  return s || 'dashboard';
}
