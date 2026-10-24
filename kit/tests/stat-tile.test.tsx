import { act, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StatTile, formatCountable, parseCountable } from '../src/index';
import { media } from './helpers';

function shown(container: HTMLElement): string {
  return container.querySelector('[data-count-up]')?.textContent ?? '';
}

afterEach(() => {
  vi.useRealTimers();
});

describe('StatTile', () => {
  it('renders the final value under reduced motion with no frame requested', () => {
    media.reducedMotion = true;
    const raf = vi.spyOn(window, 'requestAnimationFrame');
    const { container } = render(<StatTile label="Devices" value={4218} />);
    expect(shown(container)).toBe('4,218');
    expect(raf).not.toHaveBeenCalled();
    expect(container.querySelector('.kit-sr-only')?.textContent).toBe('4,218');
  });

  it('counts up on frames and lands on the exact value', () => {
    vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance', 'setTimeout', 'clearTimeout', 'Date'] });
    const { container } = render(<StatTile label="Spend" value="$12,480.50" />);
    expect(shown(container)).toBe('$0.00');
    act(() => {
      vi.advanceTimersByTime(200);
    });
    const mid = shown(container);
    expect(mid).toMatch(/^\$[\d,]+\.\d{2}$/);
    expect(mid).not.toBe('$0.00');
    expect(mid).not.toBe('$12,480.50');
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(shown(container)).toBe('$12,480.50');
  });

  it('skips values below 2 and non-numeric text', () => {
    const raf = vi.spyOn(window, 'requestAnimationFrame');
    const { container, rerender } = render(<StatTile label="Errors" value={1} />);
    expect(shown(container)).toBe('1');
    rerender(<StatTile label="State" value="Healthy" />);
    expect(shown(container)).toBe('Healthy');
    expect(raf).not.toHaveBeenCalled();
  });

  it('keeps prefix, suffix, grouping and decimals', () => {
    const c = parseCountable('~1,234.5 ms');
    expect(c).toEqual({ prefix: '~', value: 1234.5, suffix: ' ms', decimals: 1, grouped: true });
    expect(formatCountable(1234.5, { decimals: 1, grouped: true })).toBe('1,234.5');
    expect(parseCountable('n/a')).toBeNull();
  });

  it('is a button only when it opens something', () => {
    const onClick = vi.fn();
    const { container } = render(<StatTile label="Failed jobs" value={2} tone="danger" onClick={onClick} />);
    const tile = container.querySelector('.kpi-tile') as HTMLElement;
    expect(tile.getAttribute('role')).toBe('button');
    expect(tile.getAttribute('data-tone')).toBe('danger');
    act(() => {
      tile.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    });
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
