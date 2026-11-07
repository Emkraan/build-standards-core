/* HubHeader: the two tab rows of a sectioned hub, the route shape and the redirect rules. */
import { fireEvent, render, screen, within } from '@testing-library/react';
import axe from 'axe-core';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { HubHeader, hubPath, hubSectionProblems, resolveHubRoute } from '../src';
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

describe('routing edge cases (H1 and the hub routing set)', () => {
  const empty: HubSection[] = [{ key: 'none', label: 'None', items: [] }, ...sections];

  it('never loops on a section with no items: hubPath and resolveHubRoute both land on the Overview', () => {
    expect(hubPath('/p', empty, 'none')).toBe('/p');
    const r = resolveHubRoute('/p', empty, 'none');
    expect(r).toEqual({ kind: 'redirect', to: '/p' });
    // following the redirect is the Overview, not another redirect
    expect(resolveHubRoute('/p', empty)).toEqual({ kind: 'overview' });
  });

  it('decodes raw route segments and encodes keys it writes', () => {
    const odd: HubSection[] = [{ key: 'a b', label: 'A B', items: [{ key: 'x/y', label: 'XY' }] }];
    expect(hubPath('/p', odd, 'x/y')).toBe('/p/a%20b/x%2Fy');
    const r = resolveHubRoute('/p', odd, 'a%20b', 'x%2Fy');
    expect(r.kind).toBe('item');
    expect(resolveHubRoute('/p', odd, 'a b', 'x/y').kind).toBe('item');
    expect(resolveHubRoute('/p', odd, '%E0%A4%A', undefined).kind).toBe('redirect');
  });

  it('reports a key used twice, and keeps the first in every helper', () => {
    const dup: HubSection[] = [
      { key: 'a', label: 'A', items: [{ key: 'one', label: 'One' }, { key: 'one', label: 'One again' }] },
      { key: 'a', label: 'A again', items: [{ key: 'two', label: 'Two' }] },
      { key: 'one', label: 'Clash', items: [{ key: 'three', label: 'Three' }] },
    ];
    const problems = hubSectionProblems(dup);
    expect(problems).toEqual(expect.arrayContaining(['section key "a" is used twice', 'item key "one" is used twice', 'item key "one" is also a section key']));
    expect(hubSectionProblems(sections)).toEqual([]);
    expect(hubPath('/p', dup, 'one')).toBe('/p/a/one');
  });

  it('shows no tab for an empty section and one tab for a section key used twice', () => {
    render(<HubHeader title="Platform" base="/platform" sections={[...empty, { ...sections[0]!, label: 'Builds again' }]} onNavigate={vi.fn()} />);
    expect(screen.getAllByRole('tab').map((t) => (t.textContent ?? '').replace(/working|\d+$/g, ''))).toEqual(['Overview', 'Builds and releases', 'Automation', 'Cost']);
  });

  it('selects the first item tab when the route names an item the section does not have', () => {
    render(<HubHeader title="Platform" base="/platform" sections={sections} section="builds" item="nope" onNavigate={vi.fn()} />);
    const tabs = within(screen.getByRole('tablist', { name: 'Builds and releases items' })).getAllByRole('tab');
    expect(tabs.filter((t) => t.getAttribute('aria-selected') === 'true').map((t) => t.textContent)).toEqual(['Alpha']);
  });

  it('selects the item for an encoded route segment', () => {
    render(<HubHeader title="Team" base="/team" tabs={[{ key: 'a b', label: 'AB' }, { key: 'c', label: 'C' }]} item="a%20b" onNavigate={vi.fn()} />);
    expect(screen.getByRole('tab', { name: 'AB' }).getAttribute('aria-selected')).toBe('true');
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

  it('takes a flat tab list: one row, no sections, paths <base>/<item>, counts and spinner kept', () => {
    const onNavigate = vi.fn();
    const tabs = [{ key: 'one', label: 'One' }, { key: 'two', label: 'Two', count: 3 }, { key: 'three', label: 'Three', live: true }];
    render(<HubHeader title="Team" base="/team/" tabs={tabs} item="two" onNavigate={onNavigate} />);
    expect(screen.getAllByRole('tablist')).toHaveLength(1);
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(['One', 'Two3', 'Threeworking']);
    expect(screen.getByRole('tab', { name: /Two/ }).getAttribute('aria-selected')).toBe('true');
    fireEvent.click(screen.getByRole('tab', { name: /Three/ }));
    expect(onNavigate).toHaveBeenCalledWith('/team/three');
  });

  it('selects the first flat tab when the route has no item', () => {
    render(<HubHeader title="Team" base="/team" tabs={[{ key: 'one', label: 'One' }, { key: 'two', label: 'Two' }]} onNavigate={vi.fn()} />);
    expect(screen.getByRole('tab', { name: 'One' }).getAttribute('aria-selected')).toBe('true');
  });

  it('renders the header only, with no tabs and no Overview, and needs no base or onNavigate', () => {
    const { container } = render(<HubHeader title="Plans" subtitle="All plans" headerOnly />);
    expect(screen.getByRole('heading', { name: 'Plans' })).toBeTruthy();
    expect(screen.queryAllByRole('tab')).toHaveLength(0);
    expect(screen.queryByText('Overview')).toBeNull();
    expect(container.querySelector('.hub-head')).toBeTruthy();
  });

  it('uses the open-arc spinner for the working marker on every tab row', () => {
    const { container } = render(<HubHeader title="Team" base="/t" tabs={[{ key: 'a', label: 'A', live: true }]} onNavigate={vi.fn()} />);
    expect(container.querySelector('.spinner[data-arc]')).toBeTruthy();
  });

  it('keeps the head spacing and the spinner colour in the stylesheet', () => {
    const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');
    expect(css).toMatch(/\.hub-head \{[^}]*margin-bottom: var\(--space-5\)/);
    expect(css).toMatch(/\.hub-head \.tab-badge \.spinner \{[^}]*color: var\(--info\)/);
  });
});
