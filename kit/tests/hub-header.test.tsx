/* HubHeader: the two tab rows of a sectioned hub, the route shape and the redirect rules. */
import { fireEvent, render, screen, within } from '@testing-library/react';
import axe from 'axe-core';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { HubHeader, hubPath, resolveHubRoute } from '../src';
import type { HubSection } from '../src';

const sections: HubSection[] = [
  { key: 'builds', label: 'Builds and releases', items: [{ key: 'alpha', label: 'Alpha' }, { key: 'beta', label: 'Beta', count: 2 }, { key: 'gamma', label: 'Gamma', live: true }] },
  { key: 'automation', label: 'Automation', items: [{ key: 'jobs', label: 'Scheduled jobs', count: 1 }, { key: 'ci', label: 'CI and backup' }] },
  { key: 'cost', label: 'Cost', items: [{ key: 'spend', label: 'Spend' }] },
];

describe('hubPath', () => {
  it('builds <base>/<section>/<item>, a section opens its first item, an unknown key is the Overview', () => {
    expect(hubPath('/platform', sections, 'beta')).toBe('/platform/builds/beta');
    expect(hubPath('/platform/', sections, 'ci')).toBe('/platform/automation/ci');
    expect(hubPath('/platform', sections, 'automation')).toBe('/platform/automation/jobs');
    expect(hubPath('/platform', sections, 'nope')).toBe('/platform');
    expect(hubPath('/platform', sections)).toBe('/platform');
    expect(hubPath('/', sections, 'spend')).toBe('/cost/spend');
  });
});

describe('resolveHubRoute', () => {
  it('is the Overview with no section, an item for a known pair', () => {
    expect(resolveHubRoute('/p', sections)).toEqual({ kind: 'overview' });
    const r = resolveHubRoute('/p', sections, 'builds', 'beta');
    expect(r.kind === 'item' && r.item.label).toBe('Beta');
  });
  it('sends an old flat link (/p/<item>) to the item and a bare or wrong item to the first item', () => {
    expect(resolveHubRoute('/p', sections, 'jobs')).toEqual({ kind: 'redirect', to: '/p/automation/jobs' });
    expect(resolveHubRoute('/p', sections, 'automation')).toEqual({ kind: 'redirect', to: '/p/automation/jobs' });
    expect(resolveHubRoute('/p', sections, 'automation', 'missing')).toEqual({ kind: 'redirect', to: '/p/automation/jobs' });
    expect(resolveHubRoute('/p', sections, 'unknown-thing')).toEqual({ kind: 'redirect', to: '/p' });
  });
});

describe('HubHeader', () => {
  const header = (props: Partial<Parameters<typeof HubHeader>[0]> = {}, onNavigate = vi.fn()) =>
    render(<HubHeader title="Platform" subtitle="Everything we run" base="/platform" sections={sections} onNavigate={onNavigate} {...props} />);

  it('shows Overview and the section titles in one row and no item row on the Overview', () => {
    header();
    const row = screen.getByRole('tablist', { name: 'Platform sections' });
    expect(within(row).getAllByRole('tab').map((t) => t.textContent?.replace(/\d+|working/g, ''))).toEqual(['Overview', 'Builds and releases', 'Automation', 'Cost']);
    expect(within(row).getByRole('tab', { name: 'Overview' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getAllByRole('tablist')).toHaveLength(1);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Platform');
  });

  it('adds the item row once a section is open, one tab per item, with the item selected', () => {
    header({ section: 'builds', item: 'beta' });
    const items = screen.getByRole('tablist', { name: 'Builds and releases items' });
    expect(within(items).getAllByRole('tab')).toHaveLength(3);
    expect(within(items).getByRole('tab', { name: /Beta/ }).getAttribute('aria-selected')).toBe('true');
    expect(within(screen.getByRole('tablist', { name: 'Platform sections' })).getByRole('tab', { name: /Builds and releases/ }).getAttribute('aria-selected')).toBe('true');
  });

  it('selects the first item when the route has a section only', () => {
    header({ section: 'automation' });
    expect(within(screen.getByRole('tablist', { name: 'Automation items' })).getByRole('tab', { name: /Scheduled jobs/ }).getAttribute('aria-selected')).toBe('true');
  });

  it('adds item counts up for a section tab and shows a spinner, never a count, for work in progress', () => {
    header();
    const tabs = within(screen.getByRole('tablist', { name: 'Platform sections' }));
    expect(tabs.getByRole('tab', { name: /Builds and releases/ }).querySelector('.tab-badge')?.textContent).toContain('2');
    expect(tabs.getByRole('tab', { name: /Builds and releases/ }).querySelector('.spinner')).not.toBeNull();
    expect(tabs.getByRole('tab', { name: /Automation/ }).querySelector('.tab-badge')?.textContent).toBe('1');
    expect(tabs.getByRole('tab', { name: /Cost/ }).querySelector('.tab-badge')).toBeNull();
  });

  it('goes to <base> for Overview, to the first item for a section, to the item path for an item', () => {
    const go = vi.fn();
    header({ section: 'builds', item: 'alpha' }, go);
    const top = within(screen.getByRole('tablist', { name: 'Platform sections' }));
    fireEvent.click(top.getByRole('tab', { name: 'Overview' }));
    fireEvent.click(top.getByRole('tab', { name: /Automation/ }));
    fireEvent.click(within(screen.getByRole('tablist', { name: 'Builds and releases items' })).getByRole('tab', { name: /Gamma/ }));
    expect(go.mock.calls.map((c) => c[0])).toEqual(['/platform', '/platform/automation/jobs', '/platform/builds/gamma']);
  });

  it('takes arrow keys along a row and labels the Overview tab', () => {
    const go = vi.fn();
    header({ overviewLabel: 'Summary' }, go);
    const first = screen.getByRole('tab', { name: 'Summary' });
    fireEvent.keyDown(first, { key: 'ArrowRight' });
    expect(go).toHaveBeenCalledWith('/platform/builds/alpha');
  });

  it('has no axe violations on either row', async () => {
    const { container } = header({ section: 'builds', item: 'beta' });
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } });
    expect(result.violations).toEqual([]);
  });

  it('keeps the head spacing and the spinner colour in the stylesheet', () => {
    const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');
    expect(css).toMatch(/\.hub-head \{[^}]*margin-bottom: var\(--space-5\)/);
    expect(css).toMatch(/\.hub-head \.tab-badge \.spinner \{[^}]*color: var\(--info\)/);
  });
});
