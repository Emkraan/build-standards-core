/* When and its pieces: the relative wording, the absolute time and zone, and the shared clock that
   ticks every timestamp on a page from one interval. */
import { act, render, screen } from '@testing-library/react';
import axe from 'axe-core';
import { Profiler } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { When, formatWhen, formatWhenAbsolute } from '../src';
import { subscribeClock } from '../src/lib/clock';
import { resetDevWarnings } from '../src/lib/env';
import { CLOCK_TICK } from '../src/lib/timing';

const NOW = new Date('2026-10-26T19:04:12Z');
const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const flat = (text: string | null | undefined): string => (text ?? '').replace(/\s/g, ' ');
// The words a reader sees: the element's own text, without the hidden description node inside it.
const visible = (el: Element): string =>
  [...el.childNodes]
    .filter((node) => node.nodeType === Node.TEXT_NODE)
    .map((node) => node.textContent ?? '')
    .join('');

describe('formatWhen', () => {
  it.each([
    [0, 'just now'],
    [1500, 'just now'],
    [2 * SECOND, '2s ago'],
    [89 * SECOND, '89s ago'],
    [90 * SECOND, '2 min ago'],
    [4 * MINUTE, '4 min ago'],
    [89 * MINUTE, '89 min ago'],
    [90 * MINUTE, '2 h ago'],
    [2 * HOUR, '2 h ago'],
    [35 * HOUR, '35 h ago'],
    [36 * HOUR, '2 d ago'],
    [3 * DAY, '3 d ago'],
    [44 * DAY, '44 d ago'],
    [45 * DAY, '2 mo ago'],
    [200 * DAY, '7 mo ago'],
    [17 * 30 * DAY, '17 mo ago'],
    [18 * 30 * DAY, '2 y ago'],
    [3 * 365 * DAY, '3 y ago'],
  ])('writes %i ms as %s', (ms, text) => {
    expect(formatWhen(ms)).toBe(text);
  });

  it('writes a moment ahead with "in"', () => {
    expect(formatWhen(-5 * MINUTE)).toBe('in 5 min');
    expect(formatWhen(-3 * HOUR)).toBe('in 3 h');
    expect(formatWhen(-1000)).toBe('just now');
  });
});

describe('formatWhenAbsolute', () => {
  it('writes the date, the time and the zone in the zone it is given', () => {
    expect(flat(formatWhenAbsolute(NOW, 'America/New_York', 'en-US'))).toBe('Oct 26, 2026, 3:04:12 PM EDT');
    expect(flat(formatWhenAbsolute(NOW, 'UTC', 'en-US'))).toBe('Oct 26, 2026, 7:04:12 PM UTC');
  });

  it('follows the daylight saving rule of the zone', () => {
    const winter = new Date('2026-01-15T17:00:00Z');
    expect(flat(formatWhenAbsolute(winter, 'America/New_York', 'en-US'))).toContain('EST');
    expect(flat(formatWhenAbsolute(winter, 'America/New_York', 'en-US'))).toContain('12:00:00 PM');
  });

  it('crosses the date line with the zone', () => {
    const late = new Date('2026-10-26T23:30:00Z');
    expect(flat(formatWhenAbsolute(late, 'Asia/Tokyo', 'en-US'))).toContain('Oct 27, 2026');
  });

  describe('with a zone it does not know', () => {
    beforeEach(() => resetDevWarnings());
    afterEach(() => vi.restoreAllMocks());

    it('falls back to the viewer zone and warns once in development', () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
      const text = formatWhenAbsolute(NOW, 'Nowhere/Invalid_Zone', 'en-US');
      formatWhenAbsolute(NOW, 'Nowhere/Invalid_Zone', 'en-US');
      expect(flat(text)).toContain('2026');
      expect(warn).toHaveBeenCalledTimes(1);
      expect(String(warn.mock.calls[0]?.[0])).toContain('Nowhere/Invalid_Zone');
    });
  });
});

describe('When', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('shows the relative time, with the absolute date, time and zone as the tip and the description', () => {
    render(<When value={new Date(NOW.getTime() - 2 * HOUR)} timeZone="America/New_York" locale="en-US" />);
    const el = screen.getByText('2 h ago');
    expect(el.tagName).toBe('TIME');
    expect(flat(el.getAttribute('data-tip'))).toBe('Oct 26, 2026, 1:04:12 PM EDT');
    expect(flat(document.getElementById(el.getAttribute('aria-describedby') ?? '')?.textContent)).toBe('Oct 26, 2026, 1:04:12 PM EDT');
    expect(el.getAttribute('datetime')).toBe('2026-10-26T17:04:12.000Z');
  });

  it('takes the zone as a prop and rewrites the tip when it changes', () => {
    const at = new Date(NOW.getTime() - 2 * HOUR);
    const { rerender } = render(<When value={at} timeZone="UTC" locale="en-US" />);
    expect(flat(screen.getByText('2 h ago').getAttribute('data-tip'))).toContain('5:04:12 PM UTC');
    rerender(<When value={at} timeZone="Asia/Tokyo" locale="en-US" />);
    expect(flat(screen.getByText('2 h ago').getAttribute('data-tip'))).toContain('Oct 27, 2026');
  });

  it('reads an ISO string and epoch milliseconds the same as a Date', () => {
    const iso = new Date(NOW.getTime() - 5 * MINUTE).toISOString();
    const epoch = NOW.getTime() - 5 * MINUTE;
    render(
      <>
        <When value={iso} data-testid="iso" />
        <When value={epoch} data-testid="epoch" />
      </>,
    );
    expect(visible(screen.getByTestId('iso'))).toBe('5 min ago');
    expect(visible(screen.getByTestId('epoch'))).toBe('5 min ago');
  });

  it('writes a moment ahead as "in ..."', () => {
    render(<When value={NOW.getTime() + 5 * MINUTE} />);
    expect(screen.getByText('in 5 min')).toBeTruthy();
  });

  it.each([[null], [undefined], [''], ['not a date']])('shows "undated" for %j, with no tip', (value) => {
    const { container } = render(<When value={value} />);
    expect(container.textContent).toBe('undated');
    expect(container.querySelector('[data-tip]')).toBeNull();
  });

  it('ticks on the kit clock constant: one tick moves the words when a threshold is crossed', () => {
    render(<When value={NOW.getTime() - 89 * SECOND} />);
    expect(screen.getByText('89s ago')).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(CLOCK_TICK);
    });
    expect(screen.getByText('2 min ago')).toBeTruthy();
  });

  it('keeps counting as time passes', () => {
    render(<When value={NOW.getTime() - 2 * HOUR} />);
    act(() => {
      vi.advanceTimersByTime(HOUR);
    });
    expect(screen.getByText('3 h ago')).toBeTruthy();
  });

  it('renders again only when its words change, not on every tick', () => {
    let commits = 0;
    render(
      <Profiler id="when" onRender={() => (commits += 1)}>
        <When value={NOW.getTime() - 4 * MINUTE} />
      </Profiler>,
    );
    const before = commits;
    act(() => {
      vi.advanceTimersByTime(10 * CLOCK_TICK);
    });
    expect(commits).toBe(before);
    act(() => {
      vi.advanceTimersByTime(MINUTE);
    });
    expect(commits).toBeGreaterThan(before);
  });

  it('runs one interval for any number of timestamps, and none when there are none', () => {
    const many = Array.from({ length: 25 }, (_, i) => <When key={i} value={NOW.getTime() - i * MINUTE} />);
    const { unmount } = render(<div>{many}</div>);
    expect(vi.getTimerCount()).toBe(1);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('does not tick an undated value into a date', () => {
    render(<When value={null} />);
    act(() => {
      vi.advanceTimersByTime(HOUR);
    });
    expect(screen.getByText('undated')).toBeTruthy();
  });

  it('passes the tip side, a class and other attributes through', () => {
    render(<When value={NOW.getTime() - 2 * MINUTE} tipSide="right" className="mine" data-x="1" />);
    const el = screen.getByText('2 min ago');
    expect(el.getAttribute('data-tip-side')).toBe('right');
    expect(el.className).toContain('when');
    expect(el.className).toContain('mine');
    expect(el.getAttribute('data-x')).toBe('1');
  });

  it('is not a tab stop unless the caller makes it one', () => {
    render(
      <>
        <When value={NOW.getTime() - MINUTE} data-testid="plain" />
        <When value={NOW.getTime() - MINUTE} tabIndex={0} data-testid="stop" />
      </>,
    );
    expect(screen.getByTestId('plain').hasAttribute('tabindex')).toBe(false);
    expect(screen.getByTestId('stop').getAttribute('tabindex')).toBe('0');
  });

  it('has no axe violations in a table cell and inline', async () => {
    vi.useRealTimers();
    const { container } = render(
      <table>
        <caption>Events</caption>
        <thead>
          <tr>
            <th>Seen</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <When value={Date.now() - 3 * HOUR} timeZone="UTC" />
            </td>
          </tr>
          <tr>
            <td>
              <When value={null} />
            </td>
          </tr>
        </tbody>
      </table>,
    );
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } }, resultTypes: ['violations'] });
    expect(result.violations.map((v) => v.id)).toEqual([]);
  });
});

describe('the shared clock', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('starts on the first subscriber, calls every subscriber each tick and stops on the last', () => {
    const a = vi.fn();
    const b = vi.fn();
    expect(vi.getTimerCount()).toBe(0);
    const offA = subscribeClock(a);
    const offB = subscribeClock(b);
    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(CLOCK_TICK * 3);
    expect(a).toHaveBeenCalledTimes(3);
    expect(b).toHaveBeenCalledTimes(3);
    offA();
    vi.advanceTimersByTime(CLOCK_TICK);
    expect(a).toHaveBeenCalledTimes(3);
    expect(b).toHaveBeenCalledTimes(4);
    expect(vi.getTimerCount()).toBe(1);
    offB();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('survives a subscriber that unsubscribes during a tick', () => {
    const calls: string[] = [];
    let offFirst = (): void => undefined;
    offFirst = subscribeClock(() => {
      calls.push('first');
      offFirst();
    });
    const offSecond = subscribeClock(() => calls.push('second'));
    vi.advanceTimersByTime(CLOCK_TICK);
    expect(calls).toEqual(['first', 'second']);
    offSecond();
  });
});
