/* StatTile: the ONLY hero KPI primitive (UI standard rule 4 and section 18). Deep hue fill, gloss,
   the one glow recipe (hub-layer .kpi-tile), and a count-up that lands on the real value. */

import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import { cx, isBrowser, prefersReducedMotion } from '../lib/env';
import { InfoTip } from '../overlays/InfoTip';
import { useTipLayerMounted } from './Tooltip';
import type { MarkHue } from '../lib/hues';
import { COUNT_UP_FALLBACK, COUNT_UP_LAND_MARGIN, tokenDuration } from '../lib/timing';

export interface Countable {
  prefix: string;
  value: number;
  suffix: string;
  decimals: number;
  grouped: boolean;
}

const NUMBER_TEXT = /^(\D*?)(-?\d[\d,]*(?:\.\d+)?)(\D.*)?$/s;

/** Splits "$1,234.50 USD" into prefix, number, suffix, decimals and grouping. Null if not numeric. */
export function parseCountable(text: string): Countable | null {
  const m = NUMBER_TEXT.exec(text.trim());
  if (!m || m[2] === undefined) return null;
  const numText = m[2];
  const value = Number(numText.replace(/,/g, ''));
  if (!Number.isFinite(value)) return null;
  const dot = numText.indexOf('.');
  return {
    prefix: m[1] ?? '',
    value,
    suffix: m[3] ?? '',
    decimals: dot >= 0 ? numText.length - dot - 1 : 0,
    grouped: numText.includes(','),
  };
}

export function formatCountable(n: number, c: Pick<Countable, 'decimals' | 'grouped'>): string {
  const fixed = Math.abs(n).toFixed(c.decimals);
  const [int = '0', frac] = fixed.split('.');
  const body = c.grouped ? int.replace(/\B(?=(\d{3})+(?!\d))/g, ',') : int;
  return (n < 0 ? '-' : '') + body + (frac ? `.${frac}` : '');
}

function animatable(c: Countable | null): c is Countable {
  if (!c || Math.abs(c.value) < 2) return false;
  if (!isBrowser || prefersReducedMotion()) return false;
  return !document.hidden;
}

/**
 * Counts a numeric value text up from zero once, on mount, over --dur-chart with an ease-out cubic.
 * Prefix, suffix, grouping and decimals are kept. Values below 2, non-numeric text, hidden tabs and
 * reduced motion show the final text at once with no frame requested. A timer lands on the real
 * value even when the browser throttles animation frames.
 */
export function useCountUp(text: string): string {
  const [shown, setShown] = useState(() => {
    const c = parseCountable(text);
    return animatable(c) ? c.prefix + formatCountable(0, c) + c.suffix : text;
  });
  const mounted = useRef(false);

  useEffect(() => {
    const c = parseCountable(text);
    if (mounted.current || !animatable(c)) {
      mounted.current = true;
      setShown(text);
      return undefined;
    }
    mounted.current = true;
    const duration = tokenDuration('--dur-chart') || COUNT_UP_FALLBACK;
    const start = performance.now();
    let frame = 0;
    const tick = () => {
      const t = Math.min(1, (performance.now() - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(t >= 1 ? text : c.prefix + formatCountable(c.value * eased, c) + c.suffix);
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    const land = window.setTimeout(() => {
      cancelAnimationFrame(frame);
      setShown(text);
    }, duration + COUNT_UP_LAND_MARGIN);
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(land);
    };
  }, [text]);

  return shown;
}

export type StatTone = 'accent' | 'success' | 'warning' | 'danger' | 'info';

export interface StatTileProps {
  label: string;
  /** A number (formatted with grouping) or display text such as "98.5%" or "$1,200". */
  value: number | string;
  hint?: ReactNode;
  icon?: ReactNode;
  /** Semantic tone. Default accent. */
  tone?: StatTone | undefined;
  /** A categorical hue instead of a semantic tone. */
  hue?: MarkHue | undefined;
  /** Change against the last period: an arrow and a short text such as "3% this week". The arrow
      and a hidden word carry the direction, the colour never does. */
  delta?: StatDelta | undefined;
  /** Marks the tile as the active filter. On an interactive tile it sets aria-pressed. */
  selected?: boolean | undefined;
  /** Help text. With the tip layer mounted (AppShell `tooltipLayer`, or a TooltipLayer) it shows as a visible
      info icon beside the label (hover or focus for the tip, click for a popover) and the tile itself carries
      no second tip. Without the layer the tile serves it as a plain `data-tip`, as before. Off when empty. On a
      tile that has `onClick` the icon sits in the tile's corner, outside the button, so a button never holds
      a button. */
  tip?: string | undefined;
  /** Makes the tile a button that opens the detail. */
  onClick?: (() => void) | undefined;
  className?: string | undefined;
}

export interface StatDelta {
  text: string;
  direction: 'up' | 'down' | 'flat';
}

const DELTA_WORD = { up: 'Up', down: 'Down', flat: 'Unchanged' } as const;

function DeltaArrow({ direction }: { direction: StatDelta['direction'] }) {
  const d = direction === 'up' ? 'M12 19V5M5 12l7-7 7 7' : direction === 'down' ? 'M12 5v14M19 12l-7 7-7-7' : 'M5 12h14';
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={d} />
    </svg>
  );
}

export function StatTile({ label, value, hint, icon, tone = 'accent', hue, delta, selected, tip, onClick, className }: StatTileProps) {
  const text = typeof value === 'number' ? value.toLocaleString('en-US') : value;
  const shown = useCountUp(text);
  const interactive = Boolean(onClick);
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (onClick && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault();
      onClick();
    }
  };
  const layerMounted = useTipLayerMounted();
  const helpIcon = tip && layerMounted ? <InfoTip short={tip} label={`About ${label}`} /> : null;
  const tileNode = (
    <div
      className={cx('kpi-tile', 'stat-tile', hue && `hue-${hue}`, selected && 'is-selected', className)}
      data-tone={hue ? 'hue' : tone}
      data-tip={layerMounted ? undefined : tip}
      role={interactive ? 'button' : undefined}
      aria-pressed={interactive && selected !== undefined ? selected : undefined}
      tabIndex={interactive ? 0 : undefined}
      onClick={onClick}
      onKeyDown={interactive ? onKeyDown : undefined}
    >
      {icon ? (
        <span className="kpi-icon" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <div className="kpi-body">
        {helpIcon && !interactive ? (
          <span className="kpi-label-row">
            <span className="kpi-label">{label}</span>
            <span className="kpi-label-info">{helpIcon}</span>
          </span>
        ) : (
          <span className="kpi-label">{label}</span>
        )}
        <span className="kpi-value">
          <span className="kit-sr-only">{text}</span>
          <span aria-hidden="true" data-count-up="">
            {shown}
          </span>
        </span>
        {delta ? (
          <span className="kpi-delta" data-direction={delta.direction}>
            <DeltaArrow direction={delta.direction} />
            <span className="kit-sr-only">{DELTA_WORD[delta.direction]} </span>
            {delta.text}
          </span>
        ) : null}
        {hint ? <span className="kpi-hint">{hint}</span> : null}
      </div>
    </div>
  );
  if (helpIcon && interactive) {
    return (
      <div className="kpi-tile-wrap">
        {tileNode}
        <span className="kpi-tile-corner">{helpIcon}</span>
      </div>
    );
  }
  return tileNode;
}
