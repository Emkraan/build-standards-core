/* Small marks: Badge and Pill, StatusDot, Kbd, Tone and HueTile. Status takes the certified status
   inks. Identity takes a categorical hue as a fill and a dot, with primary text for contrast. */

import type { ElementType, HTMLAttributes, ReactNode } from 'react';
import { IconClose } from '../icons/icons';
import { cx } from '../lib/env';
import type { MarkHue } from '../lib/hues';
import { Spinner } from './Spinner';
import { joinIds, useTip } from './Tooltip';
import type { TipSide } from './Tooltip';

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
  /** What the state means and whether it is normal, one or two short sentences. Shows as the tip, is
      read as the description, and makes the badge focusable so a keyboard user can reach it. Pass
      tabIndex={-1} where the badge already sits inside a focusable row. Not for a badge inside a button or link. */
  tip?: string | undefined;
  tipSide?: TipSide | undefined;
}

export function Badge({
  tone = 'neutral',
  hue,
  dot,
  live,
  onRemove,
  removing = false,
  removeLabel,
  tip,
  tipSide,
  className,
  children,
  ...rest
}: BadgeProps) {
  const what = removeLabel ?? (typeof children === 'string' || typeof children === 'number' ? String(children) : 'item');
  const { props: tipProps, description } = useTip(tip, tipSide);
  return (
    <span
      {...rest}
      {...tipProps}
      aria-describedby={joinIds(rest['aria-describedby'], tipProps['aria-describedby'])}
      tabIndex={rest.tabIndex ?? (tipProps['data-tip'] ? 0 : undefined)}
      className={cx('badge', hue && `hue-${hue}`, tipProps['data-tip'] && 'has-tip', className)}
      data-tone={hue ? undefined : tone}
      data-hue={hue}
      data-live={live ? '' : undefined}
      data-removable={onRemove ? '' : undefined}
      data-removing={removing ? '' : undefined}
      aria-busy={removing || undefined}
    >
      {live ? <Spinner size="xs" className="badge-spinner" /> : dot || hue ? <span className="badge-dot" aria-hidden="true" /> : null}
      {children}
      {description}
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
  /** What the state means and whether it is normal, one or two short sentences. Shows as the tip, is
      read as the description and makes the dot focusable. A dot with a tip and no `label` takes the
      tip as its accessible name. */
  tip?: string | undefined;
  tipSide?: TipSide | undefined;
}

export function StatusDot({ tone = 'neutral', label, showLabel = false, pulse = true, className, tip, tipSide }: StatusDotProps) {
  const tipText = tip?.trim() ?? '';
  const labelled = Boolean(label) && showLabel;
  // A bare dot has no text of its own, so its tip stands in as the name. With a label the tip describes it.
  const named = label || tipText || undefined;
  const { props: described, description } = useTip(label ? tipText : undefined, tipSide);
  const bare = !label && tipText ? { 'data-tip': tipText, 'data-tip-side': tipSide } : {};
  const mark = { ...described, ...bare, ...(tipText ? { tabIndex: 0 } : {}) };
  const dot = (
    <span
      className={cx('status-dot', !pulse && 'is-still', tipText && !labelled && 'has-tip', className)}
      data-tone={tone}
      role={named && !labelled ? 'img' : undefined}
      aria-label={named && !labelled ? named : undefined}
      aria-hidden={named && !labelled ? undefined : true}
      {...(labelled ? {} : mark)}
    >
      {labelled ? null : description}
    </span>
  );
  if (!labelled) return dot;
  return (
    <span className={cx('status-dot-wrap', tipText && 'has-tip')} {...mark}>
      {dot}
      <span>{label}</span>
      {description}
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
