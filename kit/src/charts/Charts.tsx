/* Data charts on recharts, themed from the core tokens. The kit root never imports this file: it is
   the separate `charts` entry, so an app that draws no chart never pulls recharts. recharts writes
   fill and stroke as SVG attributes, where var() is unreliable, so the colours come from
   useChartTheme (computed token values that follow the theme and the accent).

   Every chart is a <figure> named by `label`. The drawing is hidden from assistive technology and a
   visually hidden table carries the same numbers, so a screen reader gets the data, not the SVG. */

import { useId, type ReactNode } from 'react';
import {
  Area,
  AreaChart as RechartsAreaChart,
  Bar,
  BarChart as RechartsBarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart as RechartsLineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { cx } from '../lib/env';
import { useMediaQuery } from '../lib/media';
import { useChartTheme, type ChartTheme } from './chartTheme';

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)';

/** One plotted value per row: `key` names the field, `label` is the legend and tooltip name. */
export interface ChartSeries<T> {
  key: keyof T & string;
  label: string;
  /** A resolved colour. Default: the next categorical hue from useChartTheme. */
  color?: string | undefined;
}

/** Turns a value into the text the axis, the tooltip and the data table show. */
export type ChartFormat = (value: number) => string;

interface CartesianProps<T> {
  data: readonly T[];
  /** The category field on the x axis (the y axis for a vertical bar chart). */
  x: keyof T & string;
  series: readonly ChartSeries<T>[];
  /** Accessible name of the chart, also the caption of the hidden data table. */
  label: string;
  /** Plot height in px. Default 240. */
  height?: number | undefined;
  /** Formats the values. Default: the number as is. */
  formatValue?: ChartFormat | undefined;
  /** Formats the category labels. Default: the value as text. */
  formatX?: ((value: unknown) => string) | undefined;
  /** Shows the series legend under the plot. Default true when there is more than one series. */
  legend?: boolean | undefined;
  className?: string | undefined;
}

const plain: ChartFormat = (value) => String(value);
const asText = (value: unknown): string => (value === null || value === undefined ? '' : String(value));

function field<T>(row: T, key: string): unknown {
  return (row as Record<string, unknown>)[key];
}

/** The colour of the i-th item: its own colour, else the categorical hue in order, else the accent. */
function nthColor(theme: ChartTheme, i: number, own?: string): string {
  return own ?? theme.series[i % Math.max(theme.series.length, 1)] ?? theme.accent;
}

function seriesColors<T>(series: readonly ChartSeries<T>[], theme: ChartTheme): (i: number) => string {
  const list = series.map((s, i) => nthColor(theme, i, s.color));
  return (i) => list[i] ?? theme.accent;
}

/** A row of tooltip or legend: a colour swatch, a name and a value. */
interface TipRow {
  name: string;
  value: string;
  color: string;
}

/** The kit chart tooltip: a token-styled card (.chart-tip) for recharts' Tooltip `content`. */
export function ChartTooltip({ title, rows }: { title?: ReactNode; rows: readonly TipRow[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="chart-tip">
      {title !== undefined && title !== '' ? <div className="chart-tip-title">{title}</div> : null}
      <ul className="chart-tip-rows">
        {rows.map((row) => (
          <li key={row.name} className="chart-tip-row">
            <span className="chart-swatch" style={{ backgroundColor: row.color }} aria-hidden="true" />
            <span className="chart-tip-name">{row.name}</span>
            <span className="chart-tip-value">{row.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface TipEntry {
  name?: unknown;
  value?: unknown;
  color?: string | undefined;
  dataKey?: unknown;
}

function tipContent(
  format: ChartFormat,
  formatX: (value: unknown) => string,
  colorFor: (key: string) => string | undefined,
) {
  return function TipContent(props: { active?: boolean; label?: unknown; payload?: readonly TipEntry[] }) {
    if (!props.active || !props.payload) return null;
    const rows = props.payload
      .filter((p) => typeof p.value === 'number')
      .map((p) => ({
        name: asText(p.name),
        value: format(p.value as number),
        color: colorFor(asText(p.dataKey)) ?? p.color ?? 'currentColor',
      }));
    return <ChartTooltip title={formatX(props.label)} rows={rows} />;
  };
}

function Legend({ rows }: { rows: readonly { name: string; color: string; value?: string | undefined }[] }) {
  return (
    <ul className="chart-legend" aria-hidden="true">
      {rows.map((row) => (
        <li key={row.name} className="chart-legend-item">
          <span className="chart-swatch" style={{ backgroundColor: row.color }} />
          <span>{row.name}</span>
          {row.value !== undefined ? <span className="chart-legend-value">{row.value}</span> : null}
        </li>
      ))}
    </ul>
  );
}

export interface ChartLegendItem {
  label: string;
  /** A resolved colour. Default: the next categorical hue, in order. */
  color?: string | undefined;
  /** Draws the swatch as a short line, for a line or threshold series. */
  line?: boolean | undefined;
}

export interface ChartLegendProps {
  items: readonly ChartLegendItem[];
  /** Accessible name of the list. Default "Legend". */
  label?: string | undefined;
  className?: string | undefined;
}

/** A standalone legend for a chart the host composes itself. Unlike the legend inside the kit charts
    (hidden, because the chart carries its own data table) this one is a real list a screen reader
    reads, with the swatch decorative and the label naming the series. Wraps on a narrow screen. */
export function ChartLegend({ items, label = 'Legend', className }: ChartLegendProps) {
  const theme = useChartTheme();
  if (items.length === 0) return null;
  return (
    <ul className={cx('chart-legend', className)} role="list" aria-label={label}>
      {items.map((item, i) => (
        <li key={item.label} className="chart-legend-item">
          <span
            className="chart-swatch"
            data-line={item.line ? '' : undefined}
            style={{ backgroundColor: nthColor(theme, i, item.color) }}
            aria-hidden="true"
          />
          <span className="chart-legend-text">{item.label}</span>
        </li>
      ))}
    </ul>
  );
}

/** The visually hidden data table every chart carries. */
function DataTable({ caption, head, rows }: { caption: string; head: readonly string[]; rows: readonly string[][] }) {
  return (
    <table className="kit-sr-only">
      <caption>{caption}</caption>
      <thead>
        <tr>
          {head.map((h, i) => (
            <th key={`${i}-${h}`} scope="col">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, r) => (
          <tr key={r}>
            {row.map((cell, c) =>
              c === 0 ? (
                <th key={c} scope="row">
                  {cell}
                </th>
              ) : (
                <td key={c}>{cell}</td>
              ),
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Frame({
  label,
  className,
  height,
  children,
  legend,
  table,
}: {
  label: string;
  className?: string | undefined;
  height: number;
  children: ReactNode;
  legend?: ReactNode;
  table: ReactNode;
}) {
  return (
    <figure className={cx('chart', className)} aria-label={label}>
      <div className="chart-plot" style={{ height }} aria-hidden="true">
        {children}
      </div>
      {legend}
      {table}
    </figure>
  );
}

function cartesianTable<T>(props: CartesianProps<T>, format: ChartFormat, formatX: (v: unknown) => string) {
  const head = [props.x, ...props.series.map((s) => s.label)];
  const rows = props.data.map((row) => [
    formatX(field(row, props.x)),
    ...props.series.map((s) => {
      const v = field(row, s.key);
      return typeof v === 'number' ? format(v) : asText(v);
    }),
  ]);
  return <DataTable caption={props.label} head={head} rows={rows} />;
}

function useCartesian<T>(props: CartesianProps<T>) {
  const theme = useChartTheme();
  const reduced = useMediaQuery(REDUCED_MOTION);
  const format = props.formatValue ?? plain;
  const formatX = props.formatX ?? asText;
  const colors = seriesColors(props.series, theme);
  const colorFor = (key: string) => {
    const i = props.series.findIndex((s) => s.key === key);
    return i < 0 ? undefined : colors(i);
  };
  const axis = {
    stroke: theme.axis,
    tick: { fill: theme.text, fontSize: 11 },
    tickLine: false,
    axisLine: { stroke: theme.grid },
  } as const;
  const showLegend = props.legend ?? props.series.length > 1;
  const legend = showLegend ? <Legend rows={props.series.map((s, i) => ({ name: s.label, color: colors(i) }))} /> : null;
  const tooltip = (
    <Tooltip
      content={tipContent(format, formatX, colorFor)}
      cursor={{ stroke: theme.grid, fill: theme.grid, fillOpacity: 0.35 }}
      wrapperStyle={{ outline: 'none' }}
      isAnimationActive={false}
    />
  );
  return {
    theme,
    animate: !reduced,
    format,
    formatX,
    colors,
    axis,
    legend,
    tooltip,
    table: cartesianTable(props, format, formatX),
    height: props.height ?? 240,
    // recharts types dataKey against the row type; the series keys are checked on ChartSeries<T>.
    data: props.data as unknown as Record<string, unknown>[],
  };
}

export interface LineChartProps<T> extends CartesianProps<T> {
  /** Line interpolation. Default 'monotone'. */
  curve?: 'monotone' | 'linear' | 'step' | undefined;
}

/** Trends over a category or time axis, one line per series. */
export function LineChart<T extends object>(props: LineChartProps<T>) {
  const c = useCartesian(props);
  return (
    <Frame label={props.label} className={props.className} height={c.height} legend={c.legend} table={c.table}>
      <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 480, height: c.height }}>
        <RechartsLineChart accessibilityLayer={false} data={c.data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={c.theme.grid} vertical={false} />
          <XAxis dataKey={props.x as string} tickFormatter={c.formatX} {...c.axis} />
          <YAxis tickFormatter={c.format} width={44} {...c.axis} />
          {c.tooltip}
          {props.series.map((s, i) => (
            <Line
              key={s.key}
              dataKey={s.key as string}
              name={s.label}
              type={props.curve ?? 'monotone'}
              stroke={c.colors(i)}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 0 }}
              isAnimationActive={c.animate}
            />
          ))}
        </RechartsLineChart>
      </ResponsiveContainer>
    </Frame>
  );
}

export interface AreaChartProps<T> extends CartesianProps<T> {
  /** Stacks the series on one another. Default false (overlaid). */
  stacked?: boolean | undefined;
  curve?: 'monotone' | 'linear' | 'step' | undefined;
}

/** Volume over time: lines with a soft fill, overlaid or stacked. */
export function AreaChart<T extends object>(props: AreaChartProps<T>) {
  const c = useCartesian(props);
  const gradient = `chart-fill-${useId().replace(/[^A-Za-z0-9_-]/g, '')}`;
  return (
    <Frame label={props.label} className={props.className} height={c.height} legend={c.legend} table={c.table}>
      <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 480, height: c.height }}>
        <RechartsAreaChart accessibilityLayer={false} data={c.data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <defs>
            {props.series.map((s, i) => (
              <linearGradient key={s.key} id={`${gradient}-${i}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={c.colors(i)} stopOpacity={0.32} />
                <stop offset="100%" stopColor={c.colors(i)} stopOpacity={0.02} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid stroke={c.theme.grid} vertical={false} />
          <XAxis dataKey={props.x as string} tickFormatter={c.formatX} {...c.axis} />
          <YAxis tickFormatter={c.format} width={44} {...c.axis} />
          {c.tooltip}
          {props.series.map((s, i) => (
            <Area
              key={s.key}
              dataKey={s.key as string}
              name={s.label}
              type={props.curve ?? 'monotone'}
              stroke={c.colors(i)}
              strokeWidth={2}
              fill={`url(#${gradient}-${i})`}
              {...(props.stacked ? { stackId: 'stack' } : {})}
              isAnimationActive={c.animate}
            />
          ))}
        </RechartsAreaChart>
      </ResponsiveContainer>
    </Frame>
  );
}

export interface BarChartProps<T> extends CartesianProps<T> {
  /** Stacks the series in one bar per category. Default false (grouped side by side). */
  stacked?: boolean | undefined;
  /** 'vertical' lays the bars out horizontally with the categories down the y axis. Default 'horizontal'. */
  layout?: 'horizontal' | 'vertical' | undefined;
  /** Width of the category axis for a vertical layout, in px. Default 96. */
  categoryWidth?: number | undefined;
}

/** Comparisons across categories, grouped or stacked. */
export function BarChart<T extends object>(props: BarChartProps<T>) {
  const c = useCartesian(props);
  const vertical = props.layout === 'vertical';
  const last = props.series.length - 1;
  const radius = (i: number): [number, number, number, number] => {
    if (props.stacked && i !== last) return [0, 0, 0, 0];
    return vertical ? [0, 3, 3, 0] : [3, 3, 0, 0];
  };
  return (
    <Frame label={props.label} className={props.className} height={c.height} legend={c.legend} table={c.table}>
      <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 480, height: c.height }}>
        <RechartsBarChart accessibilityLayer={false} data={c.data} layout={vertical ? 'vertical' : 'horizontal'} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={c.theme.grid} vertical={vertical} horizontal={!vertical} />
          {vertical ? (
            <>
              <XAxis type="number" tickFormatter={c.format} {...c.axis} />
              <YAxis type="category" dataKey={props.x as string} tickFormatter={c.formatX} width={props.categoryWidth ?? 96} {...c.axis} />
            </>
          ) : (
            <>
              <XAxis dataKey={props.x as string} tickFormatter={c.formatX} {...c.axis} />
              <YAxis tickFormatter={c.format} width={44} {...c.axis} />
            </>
          )}
          {c.tooltip}
          {props.series.map((s, i) => (
            <Bar
              key={s.key}
              dataKey={s.key as string}
              name={s.label}
              fill={c.colors(i)}
              radius={radius(i)}
              maxBarSize={32}
              {...(props.stacked ? { stackId: 'stack' } : {})}
              isAnimationActive={c.animate}
            />
          ))}
        </RechartsBarChart>
      </ResponsiveContainer>
    </Frame>
  );
}

export interface SparklineProps {
  data: readonly number[];
  /** Accessible name, for example "Requests, last 24 hours". */
  label: string;
  /** A resolved colour. Default: the accent. */
  color?: string | undefined;
  /** Fills under the line. Default true. */
  area?: boolean | undefined;
  /** Width in px, or '100%'. Default 96. */
  width?: number | '100%' | undefined;
  /** Height in px. Default 28. */
  height?: number | undefined;
  formatValue?: ChartFormat | undefined;
  className?: string | undefined;
}

/** A word-sized trend line with no axes, for tiles and table cells. */
export function Sparkline({ data, label, color, area = true, width = 96, height = 28, formatValue, className }: SparklineProps) {
  const theme = useChartTheme();
  const reduced = useMediaQuery(REDUCED_MOTION);
  const stroke = color ?? theme.accent;
  const gradient = `chart-spark-${useId().replace(/[^A-Za-z0-9_-]/g, '')}`;
  const rows = data.map((v, i) => ({ i, v }));
  const format = formatValue ?? plain;
  return (
    <figure className={cx('chart', 'chart-spark', className)} aria-label={label} style={{ width }}>
      <div className="chart-plot" style={{ height }} aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: typeof width === 'number' ? width : 96, height }}>
          <RechartsAreaChart accessibilityLayer={false} data={rows} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
            <defs>
              <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={stroke} stopOpacity={area ? 0.28 : 0} />
                <stop offset="100%" stopColor={stroke} stopOpacity={0} />
              </linearGradient>
            </defs>
            <Area dataKey="v" type="monotone" stroke={stroke} strokeWidth={1.5} fill={`url(#${gradient})`} dot={false} isAnimationActive={!reduced} />
          </RechartsAreaChart>
        </ResponsiveContainer>
      </div>
      <DataTable caption={label} head={['Point', 'Value']} rows={data.map((v, i) => [String(i + 1), format(v)])} />
    </figure>
  );
}

export interface DonutSlice {
  label: string;
  value: number;
  /** A resolved colour. Default: the next categorical hue. */
  color?: string | undefined;
}

export interface DonutChartProps {
  data: readonly DonutSlice[];
  label: string;
  /** Text in the hole, for example the total. */
  center?: ReactNode;
  /** A small caption under the centre text. */
  centerLabel?: ReactNode;
  /** Diameter in px. Default 180. */
  size?: number | undefined;
  formatValue?: ChartFormat | undefined;
  /** Shows the legend beside the ring with each value. Default true. */
  legend?: boolean | undefined;
  className?: string | undefined;
}

/** Parts of a whole, as a ring with an optional figure in the hole. */
export function DonutChart({ data, label, center, centerLabel, size = 180, formatValue, legend = true, className }: DonutChartProps) {
  const theme = useChartTheme();
  const reduced = useMediaQuery(REDUCED_MOTION);
  const format = formatValue ?? plain;
  const colors = (i: number) => nthColor(theme, i, data[i]?.color);
  const rows = data.map((d) => ({ name: d.label, value: d.value }));
  const content = (props: { active?: boolean; payload?: readonly TipEntry[] }) => {
    const entry = props.active ? props.payload?.[0] : undefined;
    if (!entry || typeof entry.value !== 'number') return null;
    const index = data.findIndex((d) => d.label === asText(entry.name));
    return <ChartTooltip rows={[{ name: asText(entry.name), value: format(entry.value), color: colors(index) }]} />;
  };
  return (
    <figure className={cx('chart', 'chart-donut', className)} aria-label={label}>
      <div className="chart-donut-ring" style={{ width: size, height: size }} aria-hidden="true">
        <PieChart accessibilityLayer={false} width={size} height={size}>
          <Pie
            data={rows}
            dataKey="value"
            nameKey="name"
            rootTabIndex={-1}
            innerRadius="66%"
            outerRadius="100%"
            paddingAngle={data.length > 1 ? 2 : 0}
            cornerRadius={3}
            stroke="none"
            isAnimationActive={!reduced}
          >
            {data.map((d, i) => (
              <Cell key={d.label} fill={colors(i)} />
            ))}
          </Pie>
          <Tooltip content={content} wrapperStyle={{ outline: 'none' }} isAnimationActive={false} />
        </PieChart>
        {center !== undefined ? (
          <div className="chart-donut-center">
            <span className="chart-donut-value">{center}</span>
            {centerLabel !== undefined ? <span className="chart-donut-label">{centerLabel}</span> : null}
          </div>
        ) : null}
      </div>
      {legend ? <Legend rows={data.map((d, i) => ({ name: d.label, color: colors(i), value: format(d.value) }))} /> : null}
      <DataTable caption={label} head={['Part', 'Value']} rows={data.map((d) => [d.label, format(d.value)])} />
    </figure>
  );
}
