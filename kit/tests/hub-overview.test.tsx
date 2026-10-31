/* AreaCard and HubOverview: the Overview of a sectioned hub. */
import { render, screen, within } from '@testing-library/react';
import axe from 'axe-core';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { AREA_DETAIL_LINES, AreaCard, HubOverview } from '../src';
import type { AreaCardData } from '../src';

const sections = [
  { key: 'builds', label: 'Builds and releases', items: [{ key: 'alpha' }, { key: 'beta' }] },
  { key: 'automation', label: 'Automation', items: [{ key: 'jobs' }, { key: 'ci' }] },
];
const card = (key: string, extra: Partial<AreaCardData> = {}): AreaCardData => ({ key, label: key.toUpperCase(), to: `/p/x/${key}`, tone: 'good', headline: `${key} headline`, ...extra });

describe('AreaCard', () => {
  it('shows the tone pill, the headline and a link to the item', () => {
    render(<AreaCard label="Beta" to="/p/builds/beta" tone="alert" headline="2 runs failed on main" detail={['one', 'two']} />);
    expect(screen.getByRole('heading', { level: 3 }).textContent).toBe('Beta');
    expect(screen.getByRole('link', { name: 'Beta' }).getAttribute('href')).toBe('/p/builds/beta');
    expect(screen.getByText('needs me')).toBeTruthy();
    expect(screen.getByText('2 runs failed on main')).toBeTruthy();
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual(['one', 'two']);
  });

  it('names the three tones healthy, worth a look and needs me', () => {
    const { rerender } = render(<AreaCard label="A" to="/a" tone="good" headline="h" />);
    expect(screen.getByText('healthy')).toBeTruthy();
    rerender(<AreaCard label="A" to="/a" tone="warn" headline="h" />);
    expect(screen.getByText('worth a look')).toBeTruthy();
    rerender(<AreaCard label="A" to="/a" tone="alert" headline="h" />);
    expect(screen.getByText('needs me')).toBeTruthy();
  });

  it('shows at most four detail lines and counts the rest', () => {
    const detail = ['1', '2', '3', '4', '5', '6'];
    render(<AreaCard label="A" to="/a" tone="warn" headline="h" detail={detail} />);
    expect(AREA_DETAIL_LINES).toBe(4);
    const items = screen.getAllByRole('listitem').map((li) => li.textContent);
    expect(items).toEqual(['1', '2', '3', '4', 'and 2 more']);
  });

  it('renders no list without detail, and exactly four lines without a "more" line', () => {
    const { container, rerender } = render(<AreaCard label="A" to="/a" tone="good" headline="h" />);
    expect(container.querySelector('ul')).toBeNull();
    rerender(<AreaCard label="A" to="/a" tone="warn" headline="h" detail={['1', '2', '3', '4']} />);
    expect(screen.getAllByRole('listitem')).toHaveLength(4);
  });

  it('reads a running healthy item as running, and keeps the words of a running problem item with the info tone so work is never red', () => {
    const { rerender, container } = render(<AreaCard label="A" to="/a" tone="good" live headline="h" />);
    expect(screen.getByText('running')).toBeTruthy();
    expect(container.querySelector('.badge')?.getAttribute('data-tone')).toBe('info');
    expect(container.querySelector('.badge .spinner')).not.toBeNull();
    rerender(<AreaCard label="A" to="/a" tone="alert" live headline="h" />);
    expect(screen.getByText('needs me')).toBeTruthy();
    expect(container.querySelector('.badge')?.getAttribute('data-tone')).toBe('info');
    rerender(<AreaCard label="A" to="/a" tone="alert" headline="h" />);
    expect(container.querySelector('.badge')?.getAttribute('data-tone')).toBe('danger');
  });

  it('marks only a needs-me card for the danger border', () => {
    const { container } = render(<AreaCard label="A" to="/a" tone="alert" headline="h" />);
    expect(container.querySelector('.area-card')?.getAttribute('data-tone')).toBe('alert');
    const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');
    expect(css).toMatch(/\.area-card\[data-tone="alert"\] \{[^}]*border-color: var\(--danger-border\)/);
  });

  it('does not render an unsafe link target as a link', () => {
    render(<AreaCard label="A" to="javascript:alert(1)" tone="good" headline="h" />);
    expect(screen.queryByRole('link')).toBeNull();
  });
});

describe('HubOverview', () => {
  it('groups one card per item under the section titles, in section and item order', () => {
    const areas = [card('ci'), card('alpha'), card('jobs'), card('beta')];
    render(<HubOverview sections={sections} areas={areas} />);
    const groups = screen.getAllByRole('region');
    expect(groups.map((g) => g.getAttribute('aria-label'))).toEqual(['Builds and releases', 'Automation']);
    expect(within(groups[0] as HTMLElement).getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual(['ALPHA', 'BETA']);
    expect(within(groups[1] as HTMLElement).getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual(['JOBS', 'CI']);
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(['Builds and releases', 'Automation']);
  });

  it('shows no card for an item without data yet, and takes a summary line', () => {
    render(<HubOverview sections={sections} areas={[card('alpha')]} summary="1 area needs me." />);
    expect(screen.getAllByRole('heading', { level: 3 })).toHaveLength(1);
    expect(screen.getByText('1 area needs me.')).toBeTruthy();
  });

  it('has no axe violations', async () => {
    const areas = [card('alpha', { tone: 'alert', detail: ['x'] }), card('beta', { live: true }), card('jobs', { tone: 'warn' }), card('ci')];
    const { container } = render(<HubOverview sections={sections} areas={areas} summary="Summary." />);
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } });
    expect(result.violations).toEqual([]);
  });
});
