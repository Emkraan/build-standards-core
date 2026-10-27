/* Stat and StatRow: the light KPI card (UI standard section 18). A Stat sits on the card surface
   with a label, a value, an optional hint and an optional hue icon tile, for the everyday summary
   row above a table or a chart. StatTile stays the deep-fill hero tile, one row per page at most.
   The value can take a status ink (certified on every content surface), never the accent. */

import type { KeyboardEvent, ReactNode } from 'react';
import { cx } from '../lib/env';
import { InfoTip } from '../overlays/InfoTip';
import type { MarkHue } from '../lib/hues';
import { useCountUp } from './StatTile';

/** Status ink for the value. `neutral` is the primary text colour. */
export type StatValueTone = 'neutral' | 'success' | 'warning' | 'urgent' | 'danger' | 'info';

export interface StatProps {
  label: ReactNode;
  /** A number (formatted with grouping) or display text such as "98.5%". */
  value: number | string;
  hint?: ReactNode;
  /** Icon in a small hue tile beside the label. */
  icon?: ReactNode;
  /** Hue of the icon tile. Default blue. */
  hue?: MarkHue | undefined;
  /** Ink of the value. Default neutral. */
  tone?: StatValueTone | undefined;
  /** Help text. Shows as a visible info icon after the label (hover or focus for the tip, click for a
      popover). Off when empty. Use `info` instead for a glossary entry. On a Stat that has `onClick` the
      icon sits in the card's corner, outside the button. */
  tip?: string | undefined;
  /** A node placed where the help icon goes, such as an InfoTip with a glossary id. Wins over `tip`. */
  info?: ReactNode;
  /** Counts the value up once on mount, like StatTile. Default false. */
  countUp?: boolean | undefined;
  /** Makes the whole card a button that opens the detail. */
  onClick?: (() => void) | undefined;
  /** Raised selection ring, for a Stat that filters the view below it. */
  selected?: boolean | undefined;
  className?: string | undefined;
}

function StatValue({ text, countUp }: { text: string; countUp: boolean }) {
  const shown = useCountUp(countUp ? text : '');
  if (!countUp) return <>{text}</>;
  return (
    <>
      <span className="kit-sr-only">{text}</span>
      <span aria-hidden="true" data-count-up="">
        {shown || text}
      </span>
    </>
  );
}

export function Stat({ label, value, hint, icon, hue = 'blue', tone = 'neutral', countUp = false, tip, info, onClick, selected, className }: StatProps) {
  const text = typeof value === 'number' ? value.toLocaleString('en-US') : value;
  const interactive = Boolean(onClick);
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (onClick && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault();
      onClick();
    }
  };
  const helpIcon = info ?? (tip ? <InfoTip short={tip} label={typeof label === 'string' ? `About ${label}` : undefined} /> : null);
  const cardNode = (
    <div
      className={cx('stat', interactive && 'card-interactive', selected && 'is-selected', className)}
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      aria-pressed={interactive && selected !== undefined ? selected : undefined}
      onClick={onClick}
      onKeyDown={interactive ? onKeyDown : undefined}
    >
      <div className="stat-top">
        {icon ? (
          <span className={cx('stat-icon', 'hue-tile', `hue-${hue}`)} aria-hidden="true">
            {icon}
          </span>
        ) : null}
        <span className="stat-label">{label}</span>
        {helpIcon && !interactive ? <span className="stat-info">{helpIcon}</span> : null}
      </div>
      <span className="stat-value" data-tone={tone}>
        <StatValue text={text} countUp={countUp} />
      </span>
      {hint ? <span className="stat-hint">{hint}</span> : null}
    </div>
  );
  if (helpIcon && interactive) {
    return (
      <div className="stat-wrap">
        {cardNode}
        <span className="stat-corner">{helpIcon}</span>
      </div>
    );
  }
  return cardNode;
}

export interface StatRowProps {
  children?: ReactNode;
  /** Accessible name of the row. With it the row is a labelled group. */
  label?: string | undefined;
  /** Narrowest a Stat may get before the row wraps. Default `md` (180px), `sm` is 140px. */
  min?: 'sm' | 'md' | 'lg' | undefined;
  className?: string | undefined;
}

/** A responsive row of Stats that wraps on narrow screens. */
export function StatRow({ children, label, min = 'md', className }: StatRowProps) {
  return (
    <div className={cx('stat-row', className)} data-min={min} role={label ? 'group' : undefined} aria-label={label}>
      {children}
    </div>
  );
}
