/* usePolling (pauses while hidden, one refresh on resume, no overlap, keeps last good data) and the
   stacked ProgressBar. */
import { act, render, renderHook, screen } from '@testing-library/react';
import axe from 'axe-core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ProgressBar, usePolling } from '../src';

function setVisibility(state: 'hidden' | 'visible') {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
  document.dispatchEvent(new Event('visibilitychange'));
}

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setVisibility('visible');
  });
  afterEach(() => {
    vi.useRealTimers();
    setVisibility('visible');
  });

  it('loads at once and then on the interval', async () => {
    const load = vi.fn(async () => 'x');
    const { result } = renderHook(() => usePolling(load, 1000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(load).toHaveBeenCalledTimes(1);
    expect(result.current.data).toBe('x');
    expect(result.current.loading).toBe(false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(load).toHaveBeenCalledTimes(3);
  });

  it('fires no poll while the document is hidden and refreshes once when it is visible again', async () => {
    const load = vi.fn(async () => 'x');
    renderHook(() => usePolling(load, 1000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(load).toHaveBeenCalledTimes(1);
    act(() => setVisibility('hidden'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(load).toHaveBeenCalledTimes(1);
    act(() => setVisibility('visible'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(load).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(load).toHaveBeenCalledTimes(3);
  });

  it('does not start while hidden at mount', async () => {
    setVisibility('hidden');
    const load = vi.fn(async () => 'x');
    renderHook(() => usePolling(load, 1000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(load).not.toHaveBeenCalled();
  });

  it('polls while hidden only when asked to', async () => {
    setVisibility('hidden');
    const load = vi.fn(async () => 'x');
    renderHook(() => usePolling(load, 1000, { whileHidden: true }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(load).toHaveBeenCalled();
  });

  it('never overlaps a slow poll with the next one', async () => {
    let calls = 0;
    const load = vi.fn(() => {
      calls += 1;
      return new Promise<string>((r) => setTimeout(() => r('slow'), 3500));
    });
    renderHook(() => usePolling(load, 1000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(calls).toBe(1);
  });

  it('keeps the last good data when a poll fails and clears the error on the next success', async () => {
    let n = 0;
    const load = vi.fn(async () => {
      n += 1;
      if (n === 2) throw new Error('boom');
      return `v${n}`;
    });
    const { result } = renderHook(() => usePolling(load, 1000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data).toBe('v1');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.error?.message).toBe('boom');
    expect(result.current.data).toBe('v1');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.error).toBeUndefined();
    expect(result.current.data).toBe('v3');
  });

  it('stops when disabled or unmounted and reload loads now', async () => {
    const load = vi.fn(async () => 'x');
    const { result, rerender, unmount } = renderHook(({ on }) => usePolling(load, 1000, { enabled: on }), { initialProps: { on: false } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(load).not.toHaveBeenCalled();
    await act(async () => {
      await result.current.reload();
    });
    expect(load).toHaveBeenCalledTimes(1);
    rerender({ on: true });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const before = load.mock.calls.length;
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(load.mock.calls.length).toBe(before);
  });
});

describe('ProgressBar segments', () => {
  it('draws parts left to right and speaks each part', () => {
    const { container } = render(
      <ProgressBar label="Work" max={20} segments={[{ value: 9, tone: 'success', label: 'done' }, { value: 4, tone: 'info', label: 'in progress' }]} />,
    );
    const bar = screen.getByRole('progressbar', { name: 'Work' });
    expect(bar.getAttribute('aria-valuenow')).toBe('13');
    expect(bar.getAttribute('aria-valuemax')).toBe('20');
    expect(bar.getAttribute('aria-valuetext')).toBe('9 done, 4 in progress of 20');
    const segs = container.querySelectorAll<HTMLElement>('.progress-segment');
    expect(segs).toHaveLength(2);
    expect(segs[0]?.style.getPropertyValue('--seg-start')).toBe('0');
    expect(segs[0]?.style.getPropertyValue('--seg-size')).toBe('45');
    expect(segs[1]?.style.getPropertyValue('--seg-start')).toBe('45');
    expect(segs[1]?.style.getPropertyValue('--seg-size')).toBe('20');
  });

  it('scales down when the parts exceed max, and ignores negatives', () => {
    const { container } = render(<ProgressBar label="Work" max={10} segments={[{ value: 10, label: 'a' }, { value: 10, label: 'b' }, { value: -5, label: 'c' }]} />);
    const segs = container.querySelectorAll<HTMLElement>('.progress-segment');
    expect(segs[1]?.style.getPropertyValue('--seg-start')).toBe('50');
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('10');
  });

  it('keeps the single value bar when no segments are given', () => {
    const { container } = render(<ProgressBar label="One" value={40} />);
    expect(container.querySelector('.progress-segment')).toBeNull();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('40');
  });

  it('has no axe violations', async () => {
    const { container } = render(<ProgressBar label="Work" max={20} segments={[{ value: 9, tone: 'success', label: 'done' }]} />);
    expect((await axe.run(container)).violations).toEqual([]);
  });
});
