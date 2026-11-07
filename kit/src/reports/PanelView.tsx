/* One dashboard panel: a number tile, a chart or a table, drawn from a server result with the kit's own charts and
   tiles (never a colour of its own). A failed panel says so in its own card and leaves the others working. A panel
   that names a filter in `drill` is clickable (click to cross-filter), and offers the same choice to the keyboard as
   a list of buttons that appears when it takes focus. */

import type { ReactNode } from 'react';
import { AreaChart, BarChart, DonutChart, LineChart } from '../charts';
import { Button } from '../primitives/Button';
import { Card, CardHead } from '../primitives/Card';
import { Skeleton } from '../primitives/EmptyState';
import { StatTile } from '../primitives/StatTile';
import { categoriesOf, formatCell, rowsToObjects, seriesOf } from './panelData';
import type { DashboardPanel, PanelResult } from './types';

const ROW_PX = 64;

export interface PanelViewProps {
  panel: DashboardPanel;
  /** The panel's result. Absent while it loads. */
  result?: PanelResult | undefined;
  /** A mark was clicked (or its keyboard twin chosen): the value to set on the panel's `drill` filter. */
  onPick?: ((value: string) => void) | undefined;
  /** The value currently picked on this panel's filter, so it reads as selected. */
  picked?: string | undefined;
  /** Download this panel as a spreadsheet. Absent: no button. */
  onExport?: (() => void) | undefined;
  /** Open the rows behind this panel. Absent when the person cannot. */
  onRows?: (() => void) | undefined;
  className?: string | undefined;
}

function PickList({ values, picked, onPick, label }: { values: readonly string[]; picked: string | undefined; onPick: (v: string) => void; label: string }) {
  if (values.length === 0) return null;
  return (
    <div className="dash-pick" role="group" aria-label={label}>
      {values.slice(0, 40).map((v) => (
        <button key={v} type="button" className="dash-pick-btn" aria-pressed={picked === v} onClick={() => onPick(v)}>
          {v}
        </button>
      ))}
    </div>
  );
}

function StatBody({ panel, result }: { panel: DashboardPanel; result: PanelResult }) {
  const s = result.stat;
  const value = s?.value ?? null;
  const pct = s?.percent ?? false;
  const o = panel.stat ?? {};
  const tone = value !== null && (o.warnAt !== undefined || o.badAt !== undefined) ? (o.badAt !== undefined && value >= o.badAt ? 'danger' : o.warnAt !== undefined && value >= o.warnAt ? 'warning' : 'success') : undefined;
  const delta = s?.change !== null && s?.change !== undefined ? { direction: s.change >= 0 ? ('up' as const) : ('down' as const), text: `${Math.abs(s.change)}%` } : undefined;
  const hint = [o.note, s?.previous !== null && s?.previous !== undefined ? `was ${formatCell(s.previous)}${pct ? '%' : ''}` : ''].filter(Boolean).join(' - ');
  return <StatTile label={panel.title} value={value === null ? '-' : `${formatCell(value)}${pct ? '%' : ''}`} hint={hint || undefined} {...(o.hue ? { hue: o.hue } : {})} {...(tone ? { tone } : {})} {...(delta ? { delta } : {})} />;
}

function ChartBody({ panel, result, onPick }: { panel: DashboardPanel; result: PanelResult; onPick?: ((v: string) => void) | undefined }) {
  const data = rowsToObjects(result);
  const { x, y } = seriesOf(panel, result);
  const height = (panel.h ?? 3) * ROW_PX;
  if (data.length === 0) return <p className="dash-empty">Nothing in this range</p>;
  if (y.length === 0) return <p className="dash-empty">Nothing to draw</p>;
  const series = y.map((k) => ({ key: k, label: k }));
  const select = panel.drill ? onPick : undefined;
  if (panel.type === 'donut') {
    const slices = data.map((d) => ({ label: String(d[x] ?? ''), value: Number(d[y[0] ?? ''] ?? 0) }));
    return <DonutChart data={slices} label={panel.title} size={Math.min(height, 200)} {...(select ? { onSelect: select } : {})} />;
  }
  if (panel.type === 'line') return <LineChart data={data} x={x} series={series} label={panel.title} height={height} />;
  if (panel.type === 'area') return <AreaChart data={data} x={x} series={series} label={panel.title} height={height} />;
  return <BarChart data={data} x={x} series={series} label={panel.title} height={height} layout={panel.type === 'hbar' ? 'vertical' : 'horizontal'} {...(select ? { onSelect: select } : {})} />;
}

function TableBody({ panel, result, onPick, picked }: { panel: DashboardPanel; result: PanelResult; onPick?: ((v: string) => void) | undefined; picked?: string | undefined }) {
  if (result.rows.length === 0) return <p className="dash-empty">Nothing in this range</p>;
  const clickable = !!panel.drill && !!onPick;
  return (
    <div className="dash-table-wrap" style={{ maxHeight: (panel.h ?? 3) * ROW_PX }}>
      <table className="dash-table">
        <caption className="kit-sr-only">{panel.title}</caption>
        <thead>
          <tr>
            {result.columns.map((c) => (
              <th key={c.name} scope="col">
                {c.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((r, i) => (
            <tr key={i} data-picked={clickable && picked === String(r[0] ?? '') ? 'true' : undefined}>
              {r.map((v, j) => (
                <td key={j}>
                  {j === 0 && clickable ? (
                    <button type="button" className="dash-cell-btn" aria-pressed={picked === String(v ?? '')} onClick={() => onPick(String(v ?? ''))}>
                      {formatCell(v)}
                    </button>
                  ) : (
                    formatCell(v)
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PanelView({ panel, result, onPick, picked, onExport, onRows, className }: PanelViewProps) {
  if (panel.type === 'stat' && result && !result.error) return <StatBody panel={panel} result={result} />;
  const ok = result && !result.error;
  const controls: ReactNode = ok ? (
    <>
      {onRows && result?.rowsSpec ? (
        <Button size="sm" data-act="link" onClick={onRows}>
          View rows
        </Button>
      ) : null}
      {onExport ? (
        <Button size="sm" data-act="transfer" aria-label={`Download ${panel.title} as a spreadsheet`} onClick={onExport}>
          Download
        </Button>
      ) : null}
    </>
  ) : null;
  const picks = ok && panel.drill && onPick && panel.type !== 'table' && panel.type !== 'stat' ? categoriesOf(panel, result) : [];
  return (
    <Card className={className ?? 'dash-panel'}>
      <CardHead level={3} title={panel.title} subtitle={panel.subtitle} controls={controls} />
      {!result ? (
        <Skeleton variant="card" label={`Loading ${panel.title}`} />
      ) : result.error ? (
        <p className="dash-error" role="alert">
          {result.error}
        </p>
      ) : panel.type === 'table' ? (
        <TableBody panel={panel} result={result} onPick={onPick} picked={picked} />
      ) : (
        <>
          <ChartBody panel={panel} result={result} onPick={onPick} />
          {onPick ? <PickList values={picks} picked={picked} onPick={onPick} label={`Filter by ${panel.title}`} /> : null}
        </>
      )}
    </Card>
  );
}
