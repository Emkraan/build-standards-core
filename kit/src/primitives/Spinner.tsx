/* Spinner: the working indicator for in-progress rows, pills and nav items. A ring with one turning
   arc on --dur-spin, coloured by currentColor (or by the tone of the Pill it sits in). Decorative by
   default. With a `label` it becomes a polite status with that text for screen readers. Under
   reduced motion the arc holds still (UI standard section 14), so the ring stays visible and nothing
   moves. */

import { cx } from '../lib/env';

export type SpinnerSize = 'xs' | 'sm' | 'md' | 'lg';

export interface SpinnerProps {
  /** xs 10px (inside a pill or badge), sm 14px (default, inline text), md 18px, lg 24px. */
  size?: SpinnerSize | undefined;
  /** Screen reader text, for example "Syncing". Omit when nearby text already says it is working. */
  label?: string | undefined;
  /** Open-arc form: one turning arc with no track ring, for a small working marker such as a tab badge. */
  arc?: boolean | undefined;
  className?: string | undefined;
}

export function Spinner({ size = 'sm', label, arc, className }: SpinnerProps) {
  const ring = <span className={cx('spinner', className)} data-size={size} data-arc={arc || undefined} aria-hidden="true" />;
  if (!label) return ring;
  return (
    <span className="spinner-wrap" role="status">
      {ring}
      <span className="kit-sr-only">{label}</span>
    </span>
  );
}
