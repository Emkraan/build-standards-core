import { act, render, screen } from '@testing-library/react';
import axe from 'axe-core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FreshnessGrid, formatAge, liveFreshness } from '../src';

const src = [
  { id: 'a', label: 'Mail', state: 'fresh' as const, ageSeconds: 100, thresholdSeconds: 200 },
  { id: 'b', label: 'Jobs', state: 'failing' as const, ageSeconds: 50, thresholdSeconds: 200, reason: 'Token expired' },
  { id: 'c', label: 'New', state: 'unknown' as const, ageSeconds: null, thresholdSeconds: 200 },
];

describe('formatAge', () => {
  it('formats ranges', () => {
    expect(formatAge(null)).toBe('never');
    expect(formatAge(30)).toBe('just now');
    expect(formatAge(2520)).toBe('42m');
    expect(formatAge(11100)).toBe('3h 05m');
    expect(formatAge(187200)).toBe('2d 4h');
  });
});

describe('liveFreshness', () => {
  it('advances age and turns fresh into stale', () => {
    expect(liveFreshness(src[0]!, 0).state).toBe('fresh');
    expect(liveFreshness(src[0]!, 101000)).toEqual({ age: 201, state: 'stale' });
  });
  it('keeps failing and unknown', () => {
    expect(liveFreshness(src[1]!, 999000).state).toBe('failing');
    expect(liveFreshness(src[2]!, 5000)).toEqual({ age: null, state: 'unknown' });
  });
});

describe('FreshnessGrid', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('renders reason, threshold and never-succeeded text', () => {
    render(<FreshnessGrid sources={src} />);
    expect(screen.getByText('Last attempt: Token expired')).toBeTruthy();
    expect(screen.getAllByText('Stale after 3m')).toHaveLength(2);
    expect(screen.getByText('No success recorded')).toBeTruthy();
    expect(screen.getByRole('list', { name: 'Data freshness' })).toBeTruthy();
  });

  it('ticks the age and turns a tile stale', () => {
    render(<FreshnessGrid sources={src} tickMs={15000} />);
    expect(screen.getByText('Fresh')).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(105000);
    });
    expect(screen.getByText('Stale')).toBeTruthy();
    expect(screen.getAllByText('3m ago')).toHaveLength(2);
  });

  it('has no axe violations', async () => {
    vi.useRealTimers();
    const { container } = render(<FreshnessGrid sources={src} />);
    const r = await axe.run(container, { rules: { region: { enabled: false } } });
    expect(r.violations.map((v) => v.id)).toEqual([]);
  });
});
