/* Small marks: Badge and Pill, StatusDot, Kbd, Tone and HueTile. Status takes the certified status
   inks. Identity takes a categorical hue as a fill and a dot, with primary text for contrast. */

import type { ElementType, HTMLAttributes, ReactNode } from 'react';
import { IconClose } from '../icons/icons';
import { cx } from '../lib/env';
import type { MarkHue } from '../lib/hues';
import { Spinner } from './Spinner';

/** `urgent` is the orange high-priority step between warning and danger. */
export type StatusTone = 'neutral' | 'accent' | 'success' | 'warning' | 'urgent' | 'danger' | 'info';

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: StatusTone | undefined;
  /** Identity colour. Overrides `tone` with a hue fill and dot. */
  hue?: MarkHue | undefined;
  /** Leading dot in the tone or hue colour. */
  dot?: boolean | undefined;
  /** Work in progress: a spinner in the tone colour before the label (it replaces the dot). The
      label carries the meaning, so the spinner is hidden from screen readers. */
  live?: boolean | undefined;
  /** Makes the badge a removable tag: a trailing remove button that warms to danger on hover. */
  onRemove?: (() => void) | undefined;
  /** Removal is in flight: the remove button is disabled and turns into a spinner. The text keeps
      its full contrast, the badge reports aria-busy. */
  removing?: boolean | undefined;
  /** What the remove button names, "Remove <removeLabel>". Default the text children. */
  removeLabel?: string | undefined;
}

export function Badge({
  tone = 'neutral',
  hue,
  dot,
  live,
  onRemove,
  removing = false,
  removeLabel,
  className,
  children,
  ...rest
}: BadgeProps) {
  const what = removeLabel ?? (typeof children === 'string' || typeof children === 'number' ? String(children) : 'item');
  return (
    <span
      {...rest}
      className={cx('badge', hue && `hue-${hue}`, className)}
      data-tone={hue ? undefined : tone}
      data-hue={hue}
      data-live={live ? '' : undefined}
      data-removable={onRemove ? '' : undefined}
      data-removing={removing ? '' : undefined}
      aria-busy={removing || undefined}
    >
      {live ? <Spinner size="xs" className="badge-spinner" /> : dot || hue ? <span className="badge-dot" aria-hidden="true" /> : null}
      {children}
      {onRemove ? (
        <button
          type="button"
          className="badge-remove"
          onClick={onRemove}
          disabled={removing}
          aria-label={`Remove ${what}`}
          data-tip={`Remove ${what}`}
        >
          {removing ? <Spinner size="xs" /> : <IconClose size={10} />}
        </button>
      ) : null}
    </span>
  );
}

/** A fully rounded badge for informational labels. `live` marks a row that is still working. */
export function Pill({ className, ...rest }: BadgeProps) {
  return <Badge {...rest} className={cx('pill', className)} />;
}

export type DotTone = 'success' | 'warning' | 'urgent' | 'danger' | 'info' | 'neutral';

export interface StatusDotProps {
  tone?: DotTone | undefined;
  /** Accessible text. Shown beside the dot when `showLabel`. */
  label?: string | undefined;
  showLabel?: boolean | undefined;
  /** Success dots pulse by default. False keeps the dot still. */
  pulse?: boolean | undefined;
  className?: string | undefined;
}

export function StatusDot({ tone = 'neutral', label, showLabel = false, pulse = true, className }: StatusDotProps) {
  const dot = (
    <span
      className={cx('status-dot', !pulse && 'is-still', className)}
      data-tone={tone}
      role={label && !showLabel ? 'img' : undefined}
      aria-label={label && !showLabel ? label : undefined}
      aria-hidden={label && !showLabel ? undefined : true}
    />
  );
  if (!label || !showLabel) return dot;
  return (
    <span className="status-dot-wrap">
      {dot}
      <span>{label}</span>
    </span>
  );
}

export function Kbd({ className, ...rest }: HTMLAttributes<HTMLElement>) {
  return <kbd {...rest} className={cx('kbd', className)} />;
}

export interface ToneProps extends HTMLAttributes<HTMLElement> {
  hue: MarkHue;
  as?: ElementType | undefined;
}

/** Wraps content in the .tone recipe: a corner wash and a tinted hairline all the way round. */
export function Tone({ hue, as = 'div', className, ...rest }: ToneProps) {
  const Tag = as;
  return <Tag {...rest} className={cx('tone', `hue-${hue}`, className)} />;
}

export interface HueTileProps {
  hue: MarkHue;
  children?: ReactNode;
  size?: 'sm' | 'md' | 'lg' | undefined;
  /** Accessible name when the tile carries meaning. Omit for a decorative tile. */
  label?: string | undefined;
  className?: string | undefined;
}

/** An icon tile tinted by a categorical hue. */
export function HueTile({ hue, children, size = 'md', label, className }: HueTileProps) {
  return (
    <span
      className={cx('hue-tile', `hue-${hue}`, className)}
      data-size={size}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {children}
    </span>
  );
}
