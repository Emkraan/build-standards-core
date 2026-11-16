/* The notice tray: severity order, no element while empty, the detail toggle, the one action, no dismiss control, and axe. */
import { fireEvent, render, screen } from '@testing-library/react';
import axe from 'axe-core';
import { describe, expect, it } from 'vitest';
import { Notice, NoticeTray, formatWhen, sortNotices } from '../src';
import type { NoticeItem } from '../src';

const list: NoticeItem[] = [
  { id: 'a', tone: 'info', title: 'A restart is pending' },
  { id: 'b', tone: 'critical', title: 'A schedule was missed', detail: <p>Last ran 3 hours ago.</p> },
  { id: 'c', tone: 'warning', title: 'The fallback is in use', action: <a href="#x">Open</a> },
  { id: 'd', tone: 'critical', title: 'A window is stuck' },
];

describe('sortNotices', () => {
  it('puts the most severe first and keeps the input order inside a tone', () => {
    expect(sortNotices(list).map((n) => n.id)).toEqual(['b', 'd', 'c', 'a']);
  });
  it('does not change its input', () => {
    const copy = list.map((n) => n.id);
    sortNotices(list);
    expect(list.map((n) => n.id)).toEqual(copy);
  });
  it('reads a missing tone as critical so an unmarked notice is never hidden below the rest', () => {
    expect(sortNotices([{ id: 'x' }, { tone: 'info' as const, id: 'y' }]).map((n) => n.id)).toEqual(['x', 'y']);
  });
});

describe('NoticeTray', () => {
  it('renders no element while the list is empty', () => {
    const { container } = render(<NoticeTray notices={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders one row per notice in severity order', () => {
    render(<NoticeTray notices={list} />);
    const titles = screen.getAllByRole('heading').map((h) => h.textContent);
    expect(titles).toEqual(['A schedule was missed', 'A window is stuck', 'The fallback is in use', 'A restart is pending']);
  });

  it('opens and closes the detail with the chevron and keeps it out of the page while closed', () => {
    render(<NoticeTray notices={list} />);
    const toggle = screen.getByRole('button', { name: 'Show the detail' });
    const detail = document.getElementById(toggle.getAttribute('aria-controls') ?? '');
    expect(detail?.hidden).toBe(true);
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(toggle);
    expect(detail?.hidden).toBe(false);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByRole('button', { name: 'Hide the detail' })).toBe(toggle);
  });

  it('has a chevron only where there is a detail, and no dismiss control at all', () => {
    render(<NoticeTray notices={list} />);
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: /dismiss|close/i })).toBeNull();
  });

  it('shows the one action next to the title', () => {
    render(<NoticeTray notices={list} />);
    expect(screen.getByRole('link', { name: 'Open' }).closest('.notice-action')).not.toBeNull();
  });

  it('uses alert for a problem and status for information', () => {
    render(<NoticeTray notices={list} />);
    expect(screen.getAllByRole('alert')).toHaveLength(3);
    expect(screen.getAllByRole('status')).toHaveLength(1);
  });

  it('has no axe violations', async () => {
    const { container } = render(<NoticeTray notices={list} />);
    const result = await axe.run(container);
    expect(result.violations).toEqual([]);
  });
});

describe('Notice', () => {
  it('stands alone on a page', () => {
    render(<Notice tone="warning" title="One notice" />);
    expect(screen.getByRole('alert').textContent).toContain('One notice');
  });
});

describe('formatWhen long wording', () => {
  const MIN = 60_000;
  it.each([
    [0, 'just now'],
    [30_000, '30 seconds ago'],
    [1000 * 61, '61 seconds ago'],
    [5 * MIN, '5 minutes ago'],
    [-5 * MIN, 'in 5 minutes'],
    [3 * 24 * 60 * MIN, '3 days ago'],
    [2 * 60 * MIN, '2 hours ago'],
  ])('writes %i ms as %s', (elapsed, text) => {
    expect(formatWhen(elapsed, 'long')).toBe(text);
  });
  it('keeps the short wording the default', () => {
    expect(formatWhen(5 * MIN)).toBe('5 min ago');
    expect(formatWhen(5 * MIN, 'short')).toBe('5 min ago');
  });
});
