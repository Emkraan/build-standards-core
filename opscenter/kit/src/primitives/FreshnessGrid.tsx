/* FreshnessGrid: one tile per upstream source with its state, a ticking age and either the last
   failure reason or the stale threshold. The age keeps advancing between polls and a tile turns
   stale on its own when it passes its threshold, so a page never looks fresher than it is. */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { cx } from '../lib/env';
import { Badge } from './marks';
import type { StatusTone } from './marks';

export type FreshnessState = 'fresh' | 'stale' | 'failing' | 'unknown';

export interface FreshnessSource {
  id: string;
  label: ReactNode;
  /** The state the source reported. A fresh source is re-derived from its live age. */
  state: FreshnessState;
  /** Seconds since the last success when the data was fetched. Null or omitted: never succeeded. */
  ageSeconds?: number | null | undefined;
  /** The age after which the source counts as stale. */
  thresholdSeconds: number;
  /** The last failure reason. Shown in place of the threshold line. */
  reason?: string | null | undefined;
  /** Optional icon before the label. */
  icon?: ReactNode;
}

export interface FreshnessGridProps {
  sources: readonly FreshnessSource[];
  /** Milliseconds between age updates. Default 15000. */
  tickMs?: number | undefined;
  /** Accessible name of the grid. Default "Data freshness". */
  label?: string | undefined;
  className?: string | undefined;
}

const STATE_LABEL: Record<FreshnessState, string> = { fresh: 'Fresh', stale: 'Stale', failing: 'Failing', unknown: 'No data' };
const STATE_TONE: Record<FreshnessState, StatusTone> = { fresh: 'success', stale: 'warning', failing: 'danger', unknown: 'neutral' };

/** "just now", "42m", "3h 05m", "2d 4h". Null or negative reads "never". */
export function formatAge(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return 'never';
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${String(Math.floor((seconds % 3600) / 60)).padStart(2, '0')}m`;
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
}

/** The age advanced by the seconds since the data was fetched, and the state re-derived from it. */
export function liveFreshness(
  s: Pick<FreshnessSource, 'state' | 'ageSeconds' | 'thresholdSeconds'>,
  elapsedMs: number,
): { age: number | null; state: FreshnessState } {
  const age = s.ageSeconds == null ? null : s.ageSeconds + Math.max(0, Math.round(elapsedMs / 1000));
  if (s.state === 'failing' || s.state === 'unknown') return { age, state: s.state };
  return { age, state: age != null && age > s.thresholdSeconds ? 'stale' : 'fresh' };
}

export function FreshnessGrid({ sources, tickMs = 15000, label = 'Data freshness', className }: FreshnessGridProps) {
  const [now, setNow] = useState(() => Date.now());
  const fetchedAt = useRef(now);
  useMemo(() => {
    fetchedAt.current = Date.now();
  }, [sources]);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), Math.max(1000, tickMs));
    return () => clearInterval(id);
  }, [tickMs]);
  const elapsed = Math.max(0, now - fetchedAt.current);
  return (
    <ul className={cx('fresh-grid', className)} aria-label={label}>
      {sources.map((s) => {
        const { age, state } = liveFreshness(s, elapsed);
        return (
          <li key={s.id} className="fresh-tile" data-state={state}>
            <div className="fresh-top">
              <span className="fresh-name">
                {s.icon}
                {s.label}
              </span>
              <Badge tone={STATE_TONE[state]}>{STATE_LABEL[state]}</Badge>
            </div>
            <div className="fresh-age tnum">{age == null ? 'No success recorded' : `${formatAge(age)}${age < 60 ? '' : ' ago'}`}</div>
            <div className="fresh-note">{s.reason ? `Last attempt: ${s.reason}` : `Stale after ${formatAge(s.thresholdSeconds)}`}</div>
          </li>
        );
      })}
    </ul>
  );
}
