/* Chart helpers with no chart library: resolved colours read from the live CSS tokens, so a chart
   (Recharts or hand-rolled SVG) recolours with the theme and the accent. Data never takes the
   accent: the categorical palette drops the hue named by --accent-withheld-hue. */

import { useEffect, useState } from 'react';
import { isBrowser, mediaQuery, onMediaChange } from '../lib/env';
import { CATEGORICAL_HUES, isSeriesHue } from '../lib/hues';
import type { SeriesHue } from '../lib/hues';

function rootEl(el?: Element): Element | null {
  if (el) return el;
  return isBrowser ? document.documentElement : null;
}

function readVar(name: string, el: Element | null): string {
  if (!el) return '';
  return getComputedStyle(el).getPropertyValue(name).trim();
}

/** "59 130 246" becomes "rgb(59, 130, 246)". Other values (hex) pass through. Empty stays empty. */
export function resolveColor(value: string): string {
  const parts = value.split(/[\s,]+/).filter(Boolean);
  if (parts.length === 3 && parts.every((p) => /^\d+(\.\d+)?$/.test(p))) return `rgb(${parts.join(', ')})`;
  return value;
}

/** The categorical hue the app accent withholds from data, or null ('none' or unset). */
export function withheldHue(el?: Element): SeriesHue | null {
  const raw = readVar('--accent-withheld-hue', rootEl(el)).replace(/["']/g, '').trim().toLowerCase();
  return isSeriesHue(raw) ? raw : null;
}

/** Names of the categorical hues available for data in this app, in series order. */
export function categoricalHueNames(el?: Element): SeriesHue[] {
  const withheld = withheldHue(el);
  return CATEGORICAL_HUES.filter((h) => h !== withheld);
}

export interface HueSwatch {
  name: SeriesHue;
  /** Bright identity colour, for marks, lines, dots and series. */
  color: string;
  /** Deep stop, for fills that carry white text. */
  deep: string;
}

/** The six categorical hues minus the one the accent withholds, resolved from the live tokens. */
export function categoricalPalette(el?: Element): HueSwatch[] {
  const target = rootEl(el);
  return categoricalHueNames(el).map((name) => ({
    name,
    color: resolveColor(readVar(`--hue-${name}`, target)) || 'currentColor',
    deep: resolveColor(readVar(`--hue-${name}-d`, target)) || 'currentColor',
  }));
}

export interface ChartTheme {
  grid: string;
  axis: string;
  text: string;
  /** Tooltip surface, border and text. */
  tip: string;
  tipBorder: string;
  tipText: string;
  /** The app accent. Brand and the in-progress status only, never a series. */
  accent: string;
  /** Series colours in order: the categorical palette minus the withheld hue. */
  series: string[];
  status: {
    notStarted: string;
    inProgress: string;
    completed: string;
    overdue: string;
    warning: string;
  };
}

/** Reads the chart colours from computed CSS variables. Call again after a theme or accent change. */
export function chartTheme(el?: Element): ChartTheme {
  const target = rootEl(el);
  const v = (name: string) => resolveColor(readVar(name, target)) || 'currentColor';
  const accent = v('--accent-rgb');
  return {
    grid: v('--border-default'),
    axis: v('--text-tertiary'),
    text: v('--text-secondary'),
    tip: v('--surface-2'),
    tipBorder: v('--border-strong'),
    tipText: v('--text-primary'),
    accent,
    series: categoricalPalette(el).map((s) => s.color),
    status: {
      notStarted: v('--text-quaternary'),
      inProgress: accent,
      completed: v('--hue-green'),
      overdue: v('--hue-red'),
      warning: v('--hue-amber'),
    },
  };
}

/** Calls `onChange` when the theme, the accent or the OS colour scheme changes. */
export function watchTheme(onChange: () => void): () => void {
  if (!isBrowser) return () => undefined;
  const mo = new MutationObserver(onChange);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'data-app-accent', 'style', 'class'] });
  const mq = mediaQuery('(prefers-color-scheme: light)');
  const offMedia = mq ? onMediaChange(mq, onChange) : () => undefined;
  return () => {
    mo.disconnect();
    offMedia();
  };
}

/** ChartTheme that stays current across theme and accent switches. */
export function useChartTheme(): ChartTheme {
  const [theme, setTheme] = useState<ChartTheme>(() => chartTheme());
  useEffect(() => {
    setTheme(chartTheme());
    return watchTheme(() => setTheme(chartTheme()));
  }, []);
  return theme;
}

/** Categorical hue names for data in this app, kept current across accent switches. */
export function useCategoricalHues(): SeriesHue[] {
  const [hues, setHues] = useState<SeriesHue[]>(() => categoricalHueNames());
  useEffect(() => {
    const update = () => {
      const next = categoricalHueNames();
      setHues((prev) => (prev.join() === next.join() ? prev : next));
    };
    update();
    return watchTheme(update);
  }, []);
  return hues;
}
