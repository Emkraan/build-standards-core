/* The live feed strip (UI standard sections 20 and 25): the presenter shows one item at a time with
   a mascot pose from its tone, dots, previous and next controls, a pause control and a search
   trigger. The items keep rotating on their own. Previous and next step through them faster and
   restart the timer, so a stepped item gets its full time on screen. The health line is always
   shown, even with the backend down, so the strip never disappears. */

import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { IconChevronLeft, IconChevronRight, IconPause, IconPlay } from '../icons/icons';
import { prefersReducedMotion } from '../lib/env';
import { FEED_INTERVAL } from '../lib/timing';
import { StickFigure } from '../primitives/EmptyState';
import type { StickPose } from '../primitives/EmptyState';
import { StatusDot } from '../primitives/marks';
import type { DotTone } from '../primitives/marks';
import { SearchTrigger } from './CommandPalette';

export type FeedTone = 'info' | 'success' | 'warning' | 'critical';

export interface FeedItem {
  id: string;
  tone: FeedTone;
  title: string;
  body?: string | undefined;
  /** Makes the item a button, for example to open the announcement. */
  onOpen?: (() => void) | undefined;
}

export type HealthStatus = 'ok' | 'degraded' | 'down' | 'unknown';

export interface HealthLine {
  status: HealthStatus;
  /** "All systems normal", "Backend unreachable, retrying". */
  label: string;
}

const POSE: Record<FeedTone, StickPose> = {
  info: 'megaphone',
  success: 'celebrate',
  warning: 'point',
  critical: 'alert',
};

const HEALTH_DOT: Record<HealthStatus, DotTone> = {
  ok: 'success',
  degraded: 'warning',
  down: 'danger',
  unknown: 'neutral',
};

export interface FeedStripProps {
  /** Always rendered. Pass the last known state when the backend is down. */
  health: HealthLine;
  /** Pulse and announcement items, when the backend has them. */
  items?: readonly FeedItem[] | undefined;
  greeting?: ReactNode;
  /** Show the search trigger (default true). */
  search?: boolean | undefined;
  label?: string | undefined;
  interval?: number | undefined;
}

export function FeedStrip({ health, items = [], greeting, search = true, label = 'Live feed', interval = FEED_INTERVAL }: FeedStripProps) {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const count = items.length;
  const current = count > 0 ? items[index % count] : undefined;
  const rotating = count > 1 && !paused && !hovered;

  // Bumped by a manual step so the rotation timer restarts from zero.
  const [stepped, setStepped] = useState(0);

  useEffect(() => {
    if (!rotating) return undefined;
    // A zero, negative or non-numeric interval falls back to the default instead of a tight loop.
    const every = Number.isFinite(interval) && interval >= 1000 ? interval : FEED_INTERVAL;
    const t = window.setInterval(() => setIndex((i) => (i + 1) % count), every);
    return () => window.clearInterval(t);
  }, [rotating, count, interval, stepped]);

  const show = (i: number) => {
    setIndex(((i % count) + count) % count);
    setStepped((n) => n + 1);
  };
  const at = count > 0 ? index % count : 0;

  const pose: StickPose = current ? POSE[current.tone] : health.status === 'down' ? 'shrug' : 'wave';

  return (
    <div className="hub-strip">
      <section
        className="presenter"
        aria-label={label}
        onPointerEnter={() => setHovered(true)}
        onPointerLeave={() => setHovered(false)}
      >
        <span className="presenter-figure">
          <StickFigure pose={prefersReducedMotion() ? 'idle' : pose} />
        </span>
        <div className="presenter-main">
          <p className="presenter-health" data-status={health.status}>
            <StatusDot tone={HEALTH_DOT[health.status]} pulse={health.status === 'ok'} />
            <span>{health.label}</span>
          </p>
          {current ? (
            <div key={current.id} className="presenter-bubble" aria-live={rotating ? 'off' : 'polite'}>
              {current.onOpen ? (
                <button type="button" className="presenter-link" onClick={current.onOpen}>
                  <b>{current.title}</b>
                  {current.body ? <span className="presenter-body"> {current.body}</span> : null}
                </button>
              ) : (
                <span>
                  <b>{current.title}</b>
                  {current.body ? <span className="presenter-body"> {current.body}</span> : null}
                </span>
              )}
            </div>
          ) : greeting ? (
            <div className="presenter-bubble">{greeting}</div>
          ) : null}
        </div>
        {count > 1 ? (
          <div className="presenter-controls">
            <button
              type="button"
              className="btn presenter-step"
              data-variant="ghost"
              data-size="sm"
              data-icon-only=""
              aria-label="Previous item"
              data-tip="Previous"
              onClick={() => show(at - 1)}
            >
              <IconChevronLeft size={14} />
            </button>
            <div className="presenter-dots" role="group" aria-label="Feed items">
              {items.map((item, i) => (
                <button
                  key={item.id}
                  type="button"
                  className={i === at ? 'presenter-dot is-active' : 'presenter-dot'}
                  aria-label={`Show item ${i + 1} of ${count}`}
                  aria-current={i === at ? 'true' : undefined}
                  onClick={() => show(i)}
                />
              ))}
            </div>
            <button
              type="button"
              className="btn presenter-step"
              data-variant="ghost"
              data-size="sm"
              data-icon-only=""
              aria-label="Next item"
              data-tip="Next"
              onClick={() => show(at + 1)}
            >
              <IconChevronRight size={14} />
            </button>
            <button
              type="button"
              className="btn presenter-pause"
              data-variant="ghost"
              data-size="sm"
              data-icon-only=""
              aria-label={paused ? 'Resume feed' : 'Pause feed'}
              aria-pressed={paused}
              data-tip={paused ? 'Resume' : 'Pause'}
              onClick={() => setPaused((p) => !p)}
            >
              {paused ? <IconPlay size={14} /> : <IconPause size={14} />}
            </button>
          </div>
        ) : null}
        {search ? <SearchTrigger /> : null}
      </section>
    </div>
  );
}

/** Alias: the presenter is the strip's main element. */
export const Presenter = FeedStrip;
