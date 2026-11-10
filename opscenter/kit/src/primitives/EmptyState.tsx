/* The stick figure mascot (hub-layer .stick rig), the EmptyState and Skeleton loaders. */

import type { ReactNode } from 'react';
import { cx } from '../lib/env';
import type { MarkHue } from '../lib/hues';

export type StickPose =
  | 'idle' | 'walk' | 'wave' | 'point' | 'shrug' | 'celebrate' | 'megaphone' | 'alert' | 'clipboard'
  | 'phone' | 'calendar' | 'hammer' | 'vacation';

export interface StickFigureProps {
  pose?: StickPose | undefined;
  /** Mirror horizontally. */
  flip?: boolean | undefined;
  className?: string | undefined;
}

/**
 * The mascot. Limbs hang straight down and rotate about their joints in user units, so the
 * hub-layer rig animates every pose. Decorative: always hidden from assistive technology.
 */
export function StickFigure({ pose = 'idle', flip = false, className }: StickFigureProps) {
  return (
    <svg
      className={cx('stick', className)}
      data-pose={pose}
      data-flip={flip ? '' : undefined}
      viewBox="0 0 40 48"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {pose === 'vacation' ? <circle className="sf-sun sf-prop" cx="36" cy="1" r="3" /> : null}
      {pose === 'phone' ? (
        <g className="sf-prop">
          <path className="sf-ring" d="M29 4a6 6 0 0 1 0 8" />
          <path className="sf-ring sf-ring-2" d="M32 2a9 9 0 0 1 0 12" />
        </g>
      ) : null}
      {pose === 'celebrate' ? (
        <g>
          <rect className="sf-confetti sf-c-amber" x="6" y="0" width="2.5" height="2.5" stroke="none" />
          <rect className="sf-confetti sf-c-teal" x="31" y="2" width="2.5" height="2.5" stroke="none" />
          <rect className="sf-confetti sf-c-violet" x="18" y="-3" width="2.5" height="2.5" stroke="none" />
        </g>
      ) : null}
      {pose === 'hammer' ? <path className="sf-sparks sf-prop" d="M39 22l2-2M41 26h3M39 29l2 2" /> : null}
      <g className="sf-root">
        <g className="sf-body">
          <path d="M20 13v17" />
          <g className="sf-head">
            <circle cx="20" cy="8" r="5" />
            <g className="sf-eyes" stroke="none" fill="currentColor">
              <circle cx="18.2" cy="7.6" r="0.75" />
              <circle cx="21.8" cy="7.6" r="0.75" />
            </g>
          </g>
          {pose === 'clipboard' ? (
            <g className="sf-prop">
              <rect x="15" y="19" width="10" height="11" rx="1.5" strokeWidth={1.5} />
              <path className="sf-check" d="M17.5 23l1.3 1.3 2.7-2.6" strokeWidth={1.3} />
              <path className="sf-check sf-check-2" d="M17.5 27l1.3 1.3 2.7-2.6" strokeWidth={1.3} />
            </g>
          ) : null}
          <g className="sf-arm sf-arm-r">
            <path d="M20 17v7" />
            <g className="sf-fore sf-fore-r">
              <path d="M20 24v7" />
              {pose === 'megaphone' ? <path className="sf-prop" d="M18.5 31l-3 6h9l-3-6Z" strokeWidth={1.5} /> : null}
              {pose === 'alert' ? (
                <g className="sf-prop" strokeWidth={1.5}>
                  <path d="M20 31v4" />
                  <rect x="16" y="35" width="8" height="8" rx="1.5" />
                  <path d="M20 37.2v2.4M20 41.4h.01" />
                </g>
              ) : null}
              {pose === 'hammer' ? <path className="sf-prop" d="M20 31v6M16.5 37h7" strokeWidth={2} /> : null}
              {pose === 'calendar' ? <rect className="sf-prop" x="16" y="31" width="8" height="7" rx="1.2" strokeWidth={1.5} /> : null}
            </g>
          </g>
          <g className="sf-arm sf-arm-l">
            <path d="M20 17v7" />
            <g className="sf-fore sf-fore-l">
              <path d="M20 24v7" />
            </g>
          </g>
        </g>
        <g className="sf-leg sf-leg-r">
          <path d="M20 30v9" />
          <g className="sf-shin sf-shin-r">
            <path d="M20 39v9" />
          </g>
        </g>
        <g className="sf-leg sf-leg-l">
          <path d="M20 30v9" />
          <g className="sf-shin sf-shin-l">
            <path d="M20 39v9" />
          </g>
        </g>
      </g>
    </svg>
  );
}

export interface EmptyStateProps {
  title: string;
  body?: ReactNode;
  /** An icon in a tile. */
  icon?: ReactNode;
  /** Tint the icon tile with a categorical hue. */
  hue?: MarkHue | undefined;
  /** Show the mascot instead of the icon (celebrate for all-clear, shrug for no results). */
  pose?: StickPose | undefined;
  /** An action that moves the user on, for example "Show August". */
  action?: ReactNode;
  /** Tighter spacing for use inside cards and tables. */
  compact?: boolean | undefined;
  className?: string | undefined;
}

export function EmptyState({ title, body, icon, hue, pose, action, compact = false, className }: EmptyStateProps) {
  return (
    <div className={cx('empty-state', className)} data-compact={compact ? '' : undefined}>
      {pose ? (
        <div className="empty-icon" aria-hidden="true">
          <StickFigure pose={pose} />
        </div>
      ) : icon ? (
        <div className={cx('empty-icon', hue && `hue-tile hue-${hue}`)} aria-hidden="true">
          {icon}
        </div>
      ) : null}
      <p className="empty-title">{title}</p>
      {body ? <p className="empty-body">{body}</p> : null}
      {action ? <div className="empty-action">{action}</div> : null}
    </div>
  );
}

export interface SkeletonProps {
  /** `list` is a stack of full-width row blocks, the placeholder for a list or feed of rows. */
  variant?: 'line' | 'lines' | 'card' | 'table' | 'list' | undefined;
  /** Lines for `lines`, rows for `table` and `list`. */
  count?: number | undefined;
  /** Columns for `table`. */
  columns?: number | undefined;
  /** Announced to screen readers. Nothing is shown as text. */
  label?: string | undefined;
  className?: string | undefined;
}

/** Loading placeholders. Never a "Loading..." sentence on screen (UI standard section 7). */
export function Skeleton({ variant = 'lines', count = 3, columns = 4, label = 'Loading', className }: SkeletonProps) {
  let shapes: ReactNode;
  if (variant === 'line') shapes = <span className="skeleton-line" />;
  else if (variant === 'card')
    shapes = (
      <span className="skeleton-card">
        <span className="skeleton-line" data-w="40" />
        <span className="skeleton-block" />
        <span className="skeleton-line" data-w="70" />
      </span>
    );
  else if (variant === 'list')
    shapes = Array.from({ length: count }, (_, i) => <span key={i} className="skeleton-block" data-shape="row" />);
  else if (variant === 'table')
    shapes = (
      <span className="skeleton-table">
        {Array.from({ length: count }, (_, r) => (
          <span key={r} className="skeleton-row">
            {Array.from({ length: columns }, (_, c) => (
              <span key={c} className="skeleton-line" />
            ))}
          </span>
        ))}
      </span>
    );
  else
    shapes = Array.from({ length: count }, (_, i) => (
      <span key={i} className="skeleton-line" data-w={i === count - 1 ? '60' : undefined} />
    ));
  return (
    <div className={cx('skeleton', className)} role="status" aria-busy="true">
      <span className="kit-sr-only">{label}</span>
      <span className="skeleton-shapes" aria-hidden="true">
        {shapes}
      </span>
    </div>
  );
}
