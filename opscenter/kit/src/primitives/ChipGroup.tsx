/* ChipGroup: a small set of toggle chips where any number can be on (filters such as a severity or
   a status set). Segmented picks exactly one, a ChipGroup picks none to all. Every chip is a real
   button with aria-pressed, in one named group, so a screen reader hears each chip and its state.
   A tone adds a dot and tints the chip when pressed, the label always says what it is, colour is
   never the only channel. Tab reaches every chip, Space and Enter toggle it, the arrow keys, Home
   and End only move focus. Chips wrap on a narrow screen and a long label truncates. */

import { useRef } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import { cx } from '../lib/env';
import type { StatusTone } from './marks';

export interface ChipOption<T extends string> {
  value: T;
  label: string;
  /** Tooltip text. */
  tip?: string | undefined;
  /** A status cue: a dot before the label and a tinted fill while pressed. */
  tone?: StatusTone | undefined;
  /** A small count after the label, for example the number of rows the chip matches. */
  badge?: ReactNode;
  disabled?: boolean | undefined;
}

export interface ChipGroupProps<T extends string> {
  options: readonly ChipOption<T>[];
  /** The values that are on. A value that is not an option is ignored. */
  value: readonly T[];
  /** Called with the new set of values that are on, in the order of `options`. */
  onChange: (value: T[]) => void;
  /** Accessible name of the group. */
  label: string;
  className?: string | undefined;
}

/** Toggle chips, any number on. The result keeps the order of `options`, whatever order was clicked. */
export function ChipGroup<T extends string>({ options, value, onChange, label, className }: ChipGroupProps<T>) {
  const groupRef = useRef<HTMLFieldSetElement | null>(null);
  const toggle = (option: ChipOption<T>) => {
    const on = new Set(value);
    if (on.has(option.value)) on.delete(option.value);
    else on.add(option.value);
    onChange(options.filter((o) => on.has(o.value)).map((o) => o.value));
  };
  const onKeyDown = (event: KeyboardEvent<HTMLFieldSetElement>) => {
    const buttons = Array.from(groupRef.current?.querySelectorAll<HTMLButtonElement>('.chip-btn:not(:disabled)') ?? []);
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (buttons.length === 0 || index < 0) return;
    let next: HTMLButtonElement | undefined;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = buttons[(index + 1) % buttons.length];
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = buttons[(index - 1 + buttons.length) % buttons.length];
    else if (event.key === 'Home') next = buttons[0];
    else if (event.key === 'End') next = buttons[buttons.length - 1];
    if (!next) return;
    event.preventDefault();
    next.focus();
  };
  return (
    <fieldset ref={groupRef} className={cx('chip-group', className)} onKeyDown={onKeyDown}>
      <legend className="kit-sr-only">{label}</legend>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className="chip-btn"
          aria-pressed={value.includes(o.value)}
          disabled={o.disabled}
          data-tip={o.tip}
          data-tone={o.tone && o.tone !== 'neutral' ? o.tone : undefined}
          onClick={() => toggle(o)}
        >
          {o.tone && o.tone !== 'neutral' ? <span className="chip-dot" aria-hidden="true" /> : null}
          <span className="chip-label">{o.label}</span>
          {o.badge !== undefined && o.badge !== null ? <span className="chip-badge">{o.badge}</span> : null}
        </button>
      ))}
    </fieldset>
  );
}
