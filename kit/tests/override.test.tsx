/* OverrideBar, OverrideButton, OverrideTag, PendingReason: the gate override pieces (layout standard rules 10, 11). */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axe from 'axe-core';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { OverrideBar, OverrideButton, OverrideTag, PendingReason } from '../src';

const confirm = { title: 'Bypass the freeze?', body: 'Work merges once everything else passes.', confirmLabel: 'Bypass for all' };
const bar = (props: Partial<Parameters<typeof OverrideBar>[0]> = {}) =>
  render(<OverrideBar title="Change freeze" gate={<b>Q4 freeze is on.</b>} switchLabel="Bypass for all" confirm={confirm} onToggle={vi.fn().mockResolvedValue(undefined)} {...props} />);

describe('OverrideBar', () => {
  it('renders nothing without a gate', () => {
    const { container } = bar({ gate: undefined });
    expect(container.firstChild).toBeNull();
  });

  it('names the gate and the detail, with the switch off and no tag', () => {
    bar({ detail: 'Work waits for it to end.' });
    expect(screen.getByRole('region', { name: 'Change freeze' }).textContent).toContain('Q4 freeze is on. Work waits for it to end.');
    expect(screen.getByRole('switch').getAttribute('aria-checked')).toBe('false');
    expect(screen.queryByText('override on')).toBeNull();
  });

  it('asks first when turning on, and writes only after the confirm', async () => {
    const onToggle = vi.fn().mockResolvedValue(undefined);
    bar({ onToggle });
    fireEvent.click(screen.getByRole('switch'));
    expect(onToggle).not.toHaveBeenCalled();
    expect(screen.getByText('Bypass the freeze?')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Bypass for all' }));
    await waitFor(() => expect(onToggle).toHaveBeenCalledWith(true));
  });

  it('does not write when the confirm is cancelled', async () => {
    const onToggle = vi.fn();
    bar({ onToggle });
    fireEvent.click(screen.getByRole('switch'));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByText('Bypass the freeze?')).toBeNull());
    expect(onToggle).not.toHaveBeenCalled();
  });

  it('turns off with no confirm, and shows the on tag and border while on', async () => {
    const onToggle = vi.fn().mockResolvedValue(undefined);
    bar({ on: true, onToggle });
    expect(screen.getByText('override on')).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Change freeze' }).getAttribute('data-on')).toBe('true');
    fireEvent.click(screen.getByRole('switch'));
    await waitFor(() => expect(onToggle).toHaveBeenCalledWith(false));
    expect(screen.queryByText('Bypass the freeze?')).toBeNull();
  });

  it('shows a refused write in the dialog and keeps the dialog open', async () => {
    bar({ onToggle: vi.fn().mockRejectedValue(new Error('not your PR')) });
    fireEvent.click(screen.getByRole('switch'));
    fireEvent.click(screen.getByRole('button', { name: 'Bypass for all' }));
    await waitFor(() => expect(screen.getByText('not your PR')).toBeTruthy());
  });

  it('has no axe violations', async () => {
    const { container } = bar({ on: true, switchHint: 'Turns itself off at midnight' });
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } });
    expect(result.violations).toEqual([]);
  });
});

describe('OverrideButton', () => {
  const button = (props: Partial<Parameters<typeof OverrideButton>[0]> = {}) =>
    render(<OverrideButton held label="Bypass freeze" undoLabel="Undo freeze bypass" confirm={{ title: 'Bypass for PR 7?' }} onSet={vi.fn().mockResolvedValue(undefined)} {...props} />);

  it('writes true after the confirm', async () => {
    const onSet = vi.fn().mockResolvedValue(undefined);
    button({ onSet });
    fireEvent.click(screen.getByRole('button', { name: 'Bypass freeze' }));
    const buttons = screen.getAllByRole('button', { name: 'Bypass freeze' });
    fireEvent.click(buttons[buttons.length - 1] as HTMLElement);
    await waitFor(() => expect(onSet).toHaveBeenCalledWith(true));
  });

  it('shows Undo on an item bypassed one by one and takes it back with no confirm', async () => {
    const onSet = vi.fn().mockResolvedValue(undefined);
    button({ held: false, cover: 'item', onSet });
    fireEvent.click(screen.getByRole('button', { name: 'Undo freeze bypass' }));
    await waitFor(() => expect(onSet).toHaveBeenCalledWith(false));
    expect(screen.queryByText('Bypass for PR 7?')).toBeNull();
  });

  it('renders nothing when the all-items override covers it, or nothing holds it and nothing is on', () => {
    const a = button({ cover: 'all' });
    expect(a.container.firstChild).toBeNull();
    a.unmount();
    const b = button({ held: false, cover: null });
    expect(b.container.firstChild).toBeNull();
    b.unmount();
    const c = button({ held: undefined });
    expect(c.container.firstChild).toBeNull();
  });
});

describe('OverrideTag', () => {
  it('names the cover and renders nothing without one', () => {
    const { container, rerender } = render(<OverrideTag cover="item" itemLabel="freeze bypassed" allLabel="freeze bypassed (all)" />);
    expect(screen.getByText('freeze bypassed')).toBeTruthy();
    rerender(<OverrideTag cover="all" itemLabel="freeze bypassed" allLabel="freeze bypassed (all)" />);
    expect(screen.getByText('freeze bypassed (all)')).toBeTruthy();
    rerender(<OverrideTag cover={null} />);
    expect(container.firstChild).toBeNull();
    rerender(<OverrideTag />);
    expect(container.firstChild).toBeNull();
  });
});

describe('PendingReason (rule 11)', () => {
  it('shows the held reason when nothing is pending', () => {
    render(<PendingReason reason="Held by the freeze." />);
    expect(screen.getByText('Held by the freeze.')).toBeTruthy();
  });

  it('shows the pending next step and never the reason the action removed', () => {
    render(<PendingReason pending="freeze bypassed, re-checked within 3 minutes" reason="Held by the freeze." />);
    expect(screen.getByRole('status').textContent).toBe('freeze bypassed, re-checked within 3 minutes');
    expect(screen.queryByText('Held by the freeze.')).toBeNull();
  });

  it('goes back to the reason once the pending line is gone, and renders nothing with neither', () => {
    const { container, rerender } = render(<PendingReason pending="x" reason="Held." />);
    rerender(<PendingReason pending={null} reason="Held again." />);
    expect(screen.getByText('Held again.')).toBeTruthy();
    rerender(<PendingReason />);
    expect(container.firstChild).toBeNull();
  });
});

describe('stylesheet', () => {
  it('styles the bar, its on border and the pending line', () => {
    const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');
    expect(css).toMatch(/\.override-bar\[data-on\] \{[^}]*border-color: var\(--warning-border\)/);
    expect(css).toMatch(/\.override-pending \{[^}]*color: var\(--warning\)/);
  });
});
