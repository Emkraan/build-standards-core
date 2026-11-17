/* HubStatTile: one tile for every KPI row. A neutral surface, the hub accent as an icon chip and a
   soft wash, a label, a big tabular number coloured ONLY when it carries state, one muted sub line
   and an optional link (the whole tile is the link and lifts on hover). A zero is muted. `hub`
   borrows another hub's accent, which is how an attention row colours each tile by its destination.
   The kit's StatTile stays the tile for metric panels with a delta, this one is the hub landing tile. */

import type { ReactNode } from 'react';
import { cx } from '../lib/env';
import { DefaultLink, GuardedLink, useShell } from '../shell/context';

export interface HubStatTileProps {
  label: string;
  value: number | string;
  sub?: ReactNode;
  icon?: ReactNode;
  /** The number's state colour. Omit for a neutral number. */
  tone?: 'danger' | 'warning' | 'success' | 'info' | undefined;
  /** The accent key of another hub. */
  hub?: string | undefined;
  to?: string | undefined;
  onClick?: (() => void) | undefined;
  selected?: boolean | undefined;
}

export function HubStatTile({ label, value, sub, icon, tone, hub, to, onClick, selected }: HubStatTileProps) {
  const shell = useShell();
  const zero = value === 0 || value === '0';
  const body = (
    <>
      {icon ? (
        <span className="hp-stat-chip" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <span className="hp-stat-body">
        <span className="hp-stat-label">{label}</span>
        <span className="hp-stat-value" data-tone={zero ? undefined : tone} data-zero={zero ? '' : undefined}>
          {typeof value === 'number' ? value.toLocaleString('en-US') : value}
        </span>
        {sub ? <span className="hp-stat-sub">{sub}</span> : null}
      </span>
    </>
  );
  const common = { className: cx('hp-stat'), 'data-hub': hub, 'data-selected': selected ? '' : undefined } as const;
  if (to) {
    return (
      <GuardedLink Link={shell?.Link ?? DefaultLink} {...common} href={to}>
        {body}
      </GuardedLink>
    );
  }
  if (onClick) {
    return (
      <button type="button" {...common} aria-pressed={selected ?? false} onClick={onClick}>
        {body}
      </button>
    );
  }
  return <div {...common}>{body}</div>;
}

export function HubStatRow({ children }: { children: ReactNode }) {
  return <div className="hp-stat-row">{children}</div>;
}
