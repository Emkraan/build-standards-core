/* useChartTheme: series colours come from the live tokens, so a chart recolours when the theme or accent changes (R8). */
import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { useChartTheme } from '../src';

afterEach(() => {
  document.documentElement.removeAttribute('data-theme');
  document.documentElement.removeAttribute('style');
});

describe('useChartTheme', () => {
  it('reads colours from the tokens and updates when the theme attribute or a token changes', async () => {
    document.documentElement.style.setProperty('--border-default', '10 20 30');
    document.documentElement.style.setProperty('--hue-green', '1 2 3');
    const { result } = renderHook(() => useChartTheme());
    expect(result.current.grid).toBe('rgb(10, 20, 30)');
    expect(result.current.status.completed).toBe('rgb(1, 2, 3)');
    await act(async () => {
      document.documentElement.style.setProperty('--border-default', '40 50 60');
      document.documentElement.setAttribute('data-theme', 'light');
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(result.current.grid).toBe('rgb(40, 50, 60)');
  });

  it('keeps the accent out of the series', () => {
    document.documentElement.style.setProperty('--accent-withheld-hue', 'blue');
    const { result } = renderHook(() => useChartTheme());
    expect(result.current.series.length).toBe(5);
    document.documentElement.style.removeProperty('--accent-withheld-hue');
  });
});
