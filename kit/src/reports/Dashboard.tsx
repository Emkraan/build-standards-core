/* Dashboard: the consumer surface of the reports module. It opens populated (no criteria to pick, no Run button),
   draws the definition's panels on a twelve column grid, and a click on a panel sets its filter, so every panel narrows
   (click to cross-filter). Router free and data free: the app owns the address (see viewState), fetches the run and
   passes it in; the kit draws it. Explore is the builder, not part of this surface. */

import { useEffect } from 'react';
import type { ReactNode } from 'react';
import { useMediaQuery } from '../lib/media';
import { Button } from '../primitives/Button';
import { Card } from '../primitives/Card';
import { DashboardFilterBar } from './DashboardFilterBar';
import type { DashboardFilterBarProps } from './DashboardFilterBar';
import { PanelView } from './PanelView';
import { togglePick } from './crossFilter';
import type { Picks } from './crossFilter';
import type { DashboardDefinition, DashboardRun, FutureDated } from './types';
import { panelId } from './types';

export interface DashboardProps extends Pick<DashboardFilterBarProps, 'dashboards' | 'onDashboard' | 'ranges' | 'onRange'> {
  definition: DashboardDefinition;
  /** The server's answer for this definition, range and picks. Absent while it loads: the panels show placeholders. */
  run?: DashboardRun | null | undefined;
  range?: string | undefined;
  picks: Picks;
  onPicks: (picks: Picks) => void;
  /** Called every `definition.refreshSeconds` while the page is visible. The app refreshes quietly. */
  onRefresh?: (() => void) | undefined;
  /** Download one panel. Absent: no per-panel button. */
  onExportPanel?: ((panelIndex: number) => void) | undefined;
  /** Open the rows behind a panel (its `rowsSpec` from the run). Absent when the person cannot explore; a panel without a `rowsSpec` shows no button. */
  onRows?: ((panelIndex: number, rowsSpec: Readonly<Record<string, unknown>>) => void) | undefined;
  /** Opens the rows behind the future-dated events, shown in the note, with the first one's stream and `rowsSpec`. Absent: no button. */
  onFutureRows?: ((item: FutureDated) => void) | undefined;
  /** Actions on the right of the filter bar: refresh, export, copy link, edit. */
  actions?: ReactNode;
  className?: string | undefined;
}

export function Dashboard({ definition, run, range, picks, onPicks, onRefresh, onExportPanel, onRows, onFutureRows, actions, dashboards, onDashboard, ranges, onRange, className }: DashboardProps) {
  const wide = useMediaQuery('(min-width: 1024px)');
  const every = definition.refreshSeconds ?? 0;
  useEffect(() => {
    if (!every || !onRefresh) return;
    const t = window.setInterval(() => {
      if (!document.hidden) onRefresh();
    }, every * 1000);
    return () => window.clearInterval(t);
  }, [every, onRefresh]);

  const future = run?.futureDated ?? [];
  const futureRows = future.reduce((n, f) => n + f.rows, 0);
  return (
    <div className={['dash', className].filter(Boolean).join(' ')}>
      <DashboardFilterBar dashboards={dashboards} dashboardKey={definition.key} onDashboard={onDashboard} ranges={ranges} range={range ?? definition.defaultRange} onRange={onRange} filters={definition.filters} options={run?.options} picks={picks} onPicks={onPicks}>
        {run ? <span className="dash-updated">Updated {new Date(run.generatedAt).toLocaleTimeString()}</span> : null}
        {actions}
      </DashboardFilterBar>
      {definition.description ? <p className="dash-desc">{definition.description}</p> : null}
      {futureRows > 0 ? (
        <Card className="dash-note" role="status">
          <span>{futureRows.toLocaleString()} events are dated in the future (a wrong device clock). They are left off the charts and counts.</span>
          {onFutureRows && future[0]?.rowsSpec ? (
            <Button size="sm" data-act="link" onClick={() => onFutureRows(future[0] as FutureDated)}>
              View rows
            </Button>
          ) : null}
        </Card>
      ) : null}
      <div className="dash-grid" style={{ gridTemplateColumns: wide ? 'repeat(12, minmax(0, 1fr))' : 'minmax(0, 1fr)' }}>
        {definition.panels.map((p, i) => {
          const id = panelId(p, i);
          return (
            <div key={id} style={wide ? { gridColumn: `span ${Math.min(12, Math.max(1, p.w ?? 4))}` } : undefined}>
              <PanelView
                panel={p}
                result={run?.panels[id]}
                picked={p.drill ? picks[p.drill] : undefined}
                onPick={p.drill ? (v) => onPicks(togglePick(picks, p.drill as string, v)) : undefined}
                onExport={onExportPanel ? () => onExportPanel(i) : undefined}
                onRows={onRows ? () => { const spec = run?.panels[id]?.rowsSpec; if (spec) onRows(i, spec); } : undefined}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
