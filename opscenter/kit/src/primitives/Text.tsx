/* Text helpers for operational data. Mono: a monospaced run with tabular, slashed-zero figures.
   RelativeTime: a friendly age with the absolute timestamp in title and a machine-readable
   dateTime. CopyButton: a value with a copy affordance that flashes a check and announces the
   result politely (a check glyph alone is invisible to anyone not watching that corner).
   freshness: an age as a tone, so staleness is visible without reading a date. */

import { type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode, useEffect, useRef, useState } from 'react';
import { IconCheck, IconCopy } from '../icons/icons';
import { cx } from '../lib/env';
import type { StatusTone } from './marks';

export interface MonoProps extends HTMLAttributes<HTMLSpanElement> {
  /** For a separator or a disabled glyph only. Quaternary ink must never carry a datum. */
  dim?: boolean | undefined;
}

export function Mono({ dim = false, className, ...rest }: MonoProps) {
  return <span {...rest} className={cx('mono', className)} data-dim={dim ? '' : undefined} />;
}

const MINUTE = 60;
const HOUR = 3600;
const DAY = 86400;

/** "just now", "5m ago", "3h ago", "2d ago", "4mo ago", "1y ago". */
export function formatRelative(seconds: number): string {
  if (seconds < MINUTE) return 'just now';
  if (seconds < HOUR) return `${Math.floor(seconds / MINUTE)}m ago`;
  if (seconds < DAY) return `${Math.floor(seconds / HOUR)}h ago`;
  if (seconds < DAY * 30) return `${Math.floor(seconds / DAY)}d ago`;
  if (seconds < DAY * 365) return `${Math.floor(seconds / (DAY * 30))}mo ago`;
  return `${Math.floor(seconds / (DAY * 365))}y ago`;
}

export interface RelativeTimeProps extends HTMLAttributes<HTMLElement> {
  value: Date | string | number | null | undefined;
}

export function RelativeTime({ value, className, ...rest }: RelativeTimeProps) {
  const date = value instanceof Date ? value : new Date(value ?? Number.NaN);
  if (value == null || value === '' || Number.isNaN(date.getTime())) {
    return (
      <span {...rest} className={className}>
        undated
      </span>
    );
  }
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  return (
    <time {...rest} className={className} dateTime={date.toISOString()} title={date.toLocaleString()}>
      {formatRelative(seconds)}
    </time>
  );
}

export interface CopyButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'value'> {
  value: string;
  label?: string | undefined;
  children?: ReactNode;
}

export function CopyButton({ value, label = 'Copy', className, children, ...rest }: CopyButtonProps) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setState('copied');
    } catch {
      setState('failed');
    }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setState('idle'), 2000);
  };

  return (
    <>
      <button
        type="button"
        {...rest}
        className={cx('copy-btn', 'mono', className)}
        data-state={state === 'copied' ? 'copied' : undefined}
        onClick={() => void copy()}
        aria-label={`${label}: ${value}`}
        title={label}
      >
        <span>{children ?? value}</span>
        {state === 'copied' ? <IconCheck size={12} /> : <IconCopy size={12} />}
      </button>
      <span className="kit-sr-only" role="status" aria-live="polite">
        {state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed' : ''}
      </span>
    </>
  );
}

/** Age in days as a tone: up to 30 days success, up to 90 warning, older danger. */
export function freshness(date: string | null | undefined): { tone?: StatusTone; label: string } {
  if (!date) return { label: 'undated' };
  const days = Math.floor((Date.now() - new Date(date).getTime()) / 86400000);
  if (Number.isNaN(days)) return { label: date };
  if (days <= 30) return { tone: 'success', label: `${days}d` };
  if (days <= 90) return { tone: 'warning', label: `${days}d` };
  return { tone: 'danger', label: `${days}d` };
}
