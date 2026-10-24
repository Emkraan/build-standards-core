/* ChipGroup (multi-select toggle chips) and ChartLegend (standalone chart legend): semantics, keyboard,
   ordering, disabled chips, default colours and axe. */
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChartLegend } from '../src/charts';
import { ChipGroup } from '../src';
import type { ChipOption } from '../src';
import { installMatchMedia, resetMedia } from './helpers';

beforeEach(() => {
  resetMedia();
  installMatchMedia();
});
afterEach(() => resetMedia());

type Level = 'a' | 'b' | 'c' | 'd';
const OPTIONS: readonly ChipOption<Level>[] = [
  { value: 'a', label: 'Alpha', tone: 'danger' },
  { value: 'b', label: 'Beta', tone: 'urgent', badge: 3 },
  { value: 'c', label: 'Gamma' },
  { value: 'd', label: 'Delta', disabled: true },
];

function Harness({ initial = [] as Level[], onChange }: { initial?: Level[]; onChange?: (v: Level[]) => void }) {
  const [value, setValue] = useState<Level[]>(initial);
  return (
    <ChipGroup
      label="Level filter"
      options={OPTIONS}
      value={value}
      onChange={(v) => {
        setValue(v);
        onChange?.(v);
      }}
    />
  );
}

describe('ChipGroup', () => {
  it('is a named group of pressed-state buttons', () => {
    render(<Harness initial={['b']} />);
    expect(screen.getByRole('group', { name: 'Level filter' })).toBeTruthy();
    expect(screen.getAllByRole('button')).toHaveLength(4);
    expect(screen.getByRole('button', { name: /Beta/ }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'Alpha' }).getAttribute('aria-pressed')).toBe('false');
  });

  it('lets any number of chips be on and reports them in option order', async () => {
    const user = userEvent.setup();
    const seen = vi.fn();
    render(<Harness onChange={seen} />);
    await user.click(screen.getByRole('button', { name: 'Gamma' }));
    await user.click(screen.getByRole('button', { name: 'Alpha' }));
    expect(seen).toHaveBeenLastCalledWith(['a', 'c']);
    await user.click(screen.getByRole('button', { name: 'Gamma' }));
    expect(seen).toHaveBeenLastCalledWith(['a']);
    await user.click(screen.getByRole('button', { name: 'Alpha' }));
    expect(seen).toHaveBeenLastCalledWith([]);
    expect(screen.getAllByRole('button').every((b) => b.getAttribute('aria-pressed') === 'false')).toBe(true);
  });

  it('toggles from the keyboard with Space and Enter, and Tab reaches each enabled chip', async () => {
    const user = userEvent.setup();
    const seen = vi.fn();
    render(<Harness onChange={seen} />);
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Alpha' }));
    await user.keyboard(' ');
    expect(seen).toHaveBeenLastCalledWith(['a']);
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /Beta/ }));
    await user.keyboard('{Enter}');
    expect(seen).toHaveBeenLastCalledWith(['a', 'b']);
  });

  it('moves focus with the arrow keys, Home and End without changing the selection, skipping disabled chips', () => {
    const seen = vi.fn();
    render(<Harness onChange={seen} />);
    const alpha = screen.getByRole('button', { name: 'Alpha' });
    alpha.focus();
    fireEvent.keyDown(alpha, { key: 'ArrowRight' });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /Beta/ }));
    fireEvent.keyDown(document.activeElement as Element, { key: 'End' });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Gamma' }));
    fireEvent.keyDown(document.activeElement as Element, { key: 'ArrowRight' });
    expect(document.activeElement).toBe(alpha);
    fireEvent.keyDown(alpha, { key: 'ArrowLeft' });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Gamma' }));
    fireEvent.keyDown(document.activeElement as Element, { key: 'Home' });
    expect(document.activeElement).toBe(alpha);
    expect(seen).not.toHaveBeenCalled();
  });

  it('never toggles a disabled chip', async () => {
    const user = userEvent.setup();
    const seen = vi.fn();
    render(<Harness onChange={seen} />);
    const delta = screen.getByRole('button', { name: 'Delta' }) as HTMLButtonElement;
    expect(delta.disabled).toBe(true);
    await user.click(delta);
    expect(seen).not.toHaveBeenCalled();
  });

  it('marks a tone with a decorative dot and keeps the label as the name, and shows the badge', () => {
    render(<Harness />);
    const alpha = screen.getByRole('button', { name: 'Alpha' });
    expect(alpha.getAttribute('data-tone')).toBe('danger');
    expect(alpha.querySelector('.chip-dot')?.getAttribute('aria-hidden')).toBe('true');
    expect(screen.getByRole('button', { name: /Beta/ }).querySelector('.chip-badge')?.textContent).toBe('3');
    expect(screen.getByRole('button', { name: 'Gamma' }).getAttribute('data-tone')).toBeNull();
  });

  it('ignores a selected value that is not an option', () => {
    render(<ChipGroup label="Level filter" options={OPTIONS} value={['zzz' as Level]} onChange={() => undefined} />);
    expect(screen.getAllByRole('button').every((b) => b.getAttribute('aria-pressed') === 'false')).toBe(true);
  });

  it('has no axe violations with chips on, off and disabled', async () => {
    const { container } = render(<Harness initial={['a', 'b']} />);
    const result = await axe.run(container, { rules: { region: { enabled: false }, 'color-contrast': { enabled: false } } });
    expect(result.violations.map((v) => v.id)).toEqual([]);
  });
});

describe('ChartLegend', () => {
  it('is a named list with one item per series', () => {
    render(<ChartLegend label="Series" items={[{ label: 'Reads' }, { label: 'Writes' }]} />);
    const list = screen.getByRole('list', { name: 'Series' });
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Reads', 'Writes']);
    expect(list.getAttribute('aria-hidden')).toBeNull();
  });

  it('is named Legend by default and renders nothing without items', () => {
    const { container, rerender } = render(<ChartLegend items={[{ label: 'One' }]} />);
    expect(screen.getByRole('list', { name: 'Legend' })).toBeTruthy();
    rerender(<ChartLegend items={[]} />);
    expect(container.querySelector('.chart-legend')).toBeNull();
  });

  it('uses the given colour, else the categorical hue in order, and keeps swatches decorative', () => {
    const { container } = render(<ChartLegend items={[{ label: 'A', color: 'rgb(1, 2, 3)' }, { label: 'B' }, { label: 'C', line: true }]} />);
    const swatches = Array.from(container.querySelectorAll<HTMLElement>('.chart-swatch'));
    expect(swatches).toHaveLength(3);
    expect(swatches[0]?.style.backgroundColor).toBe('rgb(1, 2, 3)');
    expect(swatches.every((s) => s.getAttribute('aria-hidden') === 'true')).toBe(true);
    expect(swatches[2]?.hasAttribute('data-line')).toBe(true);
    expect(swatches[1]?.hasAttribute('data-line')).toBe(false);
  });

  it('has no axe violations', async () => {
    const { container } = render(<ChartLegend items={[{ label: 'Reads' }, { label: 'Limit', line: true }]} />);
    const result = await axe.run(container, { rules: { region: { enabled: false }, 'color-contrast': { enabled: false } } });
    expect(result.violations.map((v) => v.id)).toEqual([]);
  });
});
