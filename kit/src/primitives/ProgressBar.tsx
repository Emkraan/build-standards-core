/* ProgressBar: a determinate bar (value of max) or, with no value, an indeterminate one. The fill
   width is the --progress custom property, so the bar animates on --dur-slow and holds still under
   reduced motion. Always labelled, because a bar alone says nothing to a screen reader. `meter`
   turns it into a measured quantity (disk used, quota spent): role meter, a deeper inset well, a
   flat tone gradient (no glow), and a fill that grows from zero on mount. */

import type { CSSProperties, HTMLAttributes } from 'react';
import { cx } from '../lib/env';

export type ProgressTone = 'accent' | 'success' | 'warning' | 'danger' | 'info';

/** One part of a stacked bar, for example work done and work in progress. */
export interface ProgressSegment {
  value: number;
  tone?: ProgressTone | undefined;
  /** Named in the spoken value, for example "done". */
  label: string;
}

export interface ProgressBarProps extends HTMLAttributes<HTMLDivElement> {
  /** Omit (or null) for an indeterminate bar. */
  value?: number | null | undefined;
  max?: number | undefined;
  tone?: ProgressTone | undefined;
  label: string;
  /** A measurement, not a task: role meter and the richer meter look. Needs a value. */
  meter?: boolean | undefined;
  /** A stacked bar: parts drawn left to right, each of `max`. Replaces `value` and `tone`; the
      spoken value lists each part, so no part is told by colour alone. */
  segments?: readonly ProgressSegment[] | undefined;
}

export function ProgressBar({
  value,
  max = 100,
  tone = 'accent',
  label,
  meter = false,
  segments,
  className,
  style,
  ...rest
}: ProgressBarProps) {
  if (segments && segments.length > 0) {
    const parts = segments.map((g) => ({ ...g, v: Math.max(0, g.value) }));
    const total = parts.reduce((a, g) => a + g.v, 0);
    const scale = max <= 0 ? 0 : total > max ? 100 / total : 100 / max;
    let at = 0;
    return (
      <div
        {...rest}
        className={cx('progress', 'progress-stacked', className)}
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={Math.min(total, max)}
        aria-valuetext={`${parts.map((g) => `${g.v} ${g.label}`).join(', ')} of ${max}`}
        style={style}
      >
        {parts.map((g, i) => {
          const start = at;
          at += g.v * scale;
          return (
            <div
              key={`${g.label}-${i}`}
              className="progress-fill progress-segment"
              data-tone={g.tone === undefined || g.tone === 'accent' ? undefined : g.tone}
              style={{ '--seg-start': start, '--seg-size': g.v * scale } as CSSProperties}
            />
          );
        })}
      </div>
    );
  }
  const indeterminate = value == null && !meter;
  const num = value ?? 0;
  const pct = indeterminate || max <= 0 ? 0 : Math.max(0, Math.min(100, (num / max) * 100));
  return (
    <div
      {...rest}
      className={cx('progress', meter && 'meter', className)}
      data-tone={tone === 'accent' ? undefined : tone}
      data-state={indeterminate ? 'indeterminate' : undefined}
      role={meter ? 'meter' : 'progressbar'}
      aria-label={label}
      aria-valuemin={indeterminate ? undefined : 0}
      aria-valuemax={indeterminate ? undefined : max}
      aria-valuenow={indeterminate ? undefined : num}
      style={{ '--progress': pct, ...style } as CSSProperties}
    >
      <div className="progress-fill" />
    </div>
  );
}
