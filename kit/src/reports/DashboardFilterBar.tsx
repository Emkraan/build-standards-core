/* The one slim filter bar of a dashboard: which dashboard, which range, one choice per filter, and the picks that are on
   as removable chips. There is no Run button: a dashboard opens populated and every change refreshes it. The range
   presets, the dashboards and the filter options all come from the app and its server. Actions (refresh, export, copy
   link, edit) go in `children`, on the right. */

import type { ReactNode } from 'react';
import { Button } from '../primitives/Button';
import { Select } from '../primitives/Field';
import { Segmented } from '../primitives/Tabs';
import { activePicks, setPick } from './crossFilter';
import type { Picks } from './crossFilter';
import type { DashboardFilter } from './types';

export interface DashboardFilterBarProps {
  /** The dashboards to choose from. One or none: the chooser is not shown. */
  dashboards?: readonly { key: string; title: string }[] | undefined;
  dashboardKey?: string | undefined;
  onDashboard?: ((key: string) => void) | undefined;
  /** The range presets with their words, for example [{ value: '30', label: '30 days' }]. */
  ranges?: readonly { value: string; label: string }[] | undefined;
  range?: string | undefined;
  onRange?: ((range: string) => void) | undefined;
  filters?: readonly DashboardFilter[] | undefined;
  /** The values each filter offers, from the run. */
  options?: Readonly<Record<string, readonly string[]>> | undefined;
  picks: Picks;
  onPicks: (picks: Picks) => void;
  /** Actions on the right. */
  children?: ReactNode;
  className?: string | undefined;
}

export function DashboardFilterBar({ dashboards = [], dashboardKey, onDashboard, ranges = [], range, onRange, filters = [], options = {}, picks, onPicks, children, className }: DashboardFilterBarProps) {
  const active = activePicks(picks);
  return (
    <section className={['dash-bar', className].filter(Boolean).join(' ')} aria-label="Dashboard filters">
      <div className="dash-bar-row">
        {dashboards.length > 1 && onDashboard ? <Select size="sm" aria-label="Dashboard" value={dashboardKey ?? ''} onChange={(e) => onDashboard(e.target.value)} options={dashboards.map((d) => ({ value: d.key, label: d.title }))} /> : null}
        {ranges.length > 0 && onRange ? <Segmented label="Time range" options={ranges} value={range ?? ranges[0]?.value ?? ''} onChange={onRange} /> : null}
        {filters.map((f) => (
          <Select
            key={f.id}
            size="sm"
            aria-label={f.label}
            value={picks[f.id] ?? ''}
            onChange={(e) => onPicks(setPick(picks, f.id, e.target.value))}
            options={[{ value: '', label: `${f.label}: all` }, ...(options[f.id] ?? []).map((o) => ({ value: o, label: o })), ...(picks[f.id] && !(options[f.id] ?? []).includes(picks[f.id] as string) ? [{ value: picks[f.id] as string, label: picks[f.id] as string }] : [])]}
          />
        ))}
        {children ? <div className="dash-bar-actions">{children}</div> : null}
      </div>
      {active.length > 0 ? (
        <div className="dash-bar-chips">
          {active.map(([id, v]) => (
            <Button key={id} size="sm" aria-label={`Remove filter ${filters.find((f) => f.id === id)?.label ?? id}: ${v}`} onClick={() => onPicks(setPick(picks, id, ''))}>
              {filters.find((f) => f.id === id)?.label ?? id}: {v} <span aria-hidden="true">x</span>
            </Button>
          ))}
          <Button size="sm" variant="ghost" onClick={() => onPicks({})}>
            Clear all
          </Button>
        </div>
      ) : null}
    </section>
  );
}
