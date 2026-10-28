/* The visible help cues: an info icon on StatTile, Stat and CardHead, and the glossary underline at rest.
   Each is off until a tip or info is passed. */
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { fireEvent, render, screen } from '@testing-library/react';
import axe from 'axe-core';
import { describe, expect, it, vi } from 'vitest';
import { CardHead, InfoTip, Stat, StatTile, TooltipLayer } from '../src';

const here = dirname(fileURLToPath(import.meta.url));
const kitCss = readFileSync(resolve(here, '../src/styles/kit.css'), 'utf8');

describe('StatTile help icon', () => {
  it('renders no icon and the previous label markup without a tip', () => {
    const { container } = render(<StatTile label="Open" value="12" />);
    expect(screen.queryByRole('button', { name: /About/ })).toBeNull();
    expect(container.querySelector('.kpi-label-row')).toBeNull();
    expect(container.querySelector('.kpi-tile-wrap')).toBeNull();
    expect(container.querySelector('.kpi-body > .kpi-label')?.textContent).toBe('Open');
  });

  it('shows one focusable icon named About <label> beside the label', () => {
    const { container } = render(
      <>
        <TooltipLayer />
        <StatTile label="Open" value="12" tip="Items waiting for a reply." />
      </>,
    );
    const icon = screen.getByRole('button', { name: 'About Open' });
    expect(icon.getAttribute('data-tip')).toBe('Items waiting for a reply.');
    expect(icon.tabIndex).toBe(0);
    expect(container.querySelector('.kpi-label-row .info-tip')).not.toBeNull();
    expect(container.querySelectorAll('[data-tip]')).toHaveLength(1);
  });

  it('puts the icon in the corner of a clickable tile, outside the button', () => {
    const onClick = vi.fn();
    const { container } = render(
      <>
        <TooltipLayer />
        <StatTile label="Open" value="12" tip="Items waiting." onClick={onClick} />
      </>,
    );
    const icon = screen.getByRole('button', { name: 'About Open' });
    const tile = container.querySelector('.kpi-tile') as HTMLElement;
    expect(tile.contains(icon)).toBe(false);
    expect(icon.closest('.kpi-tile-corner')).not.toBeNull();
    expect(tile.parentElement?.className).toBe('kpi-tile-wrap');
    expect(container.querySelectorAll('[role="button"] button')).toHaveLength(0);
    fireEvent.click(icon);
    expect(onClick).not.toHaveBeenCalled();
    fireEvent.click(tile);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('has no axe violations with a tip, clickable or not', async () => {
    const { container } = render(
      <>
        <TooltipLayer />
        <StatTile label="Open" value="12" tip="Items waiting." />
        <StatTile label="Review" value="3" tip="Items older than two days." onClick={() => undefined} />
      </>,
    );
    expect((await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })).violations).toEqual([]);
  });
});

describe('Stat help icon', () => {
  it('renders no icon and the previous top row without help', () => {
    const { container } = render(<Stat label="Online" value={4} />);
    expect(container.querySelector('.stat-info')).toBeNull();
    expect(container.querySelector('.stat-wrap')).toBeNull();
    expect(container.querySelector('.stat-top')?.children).toHaveLength(1);
  });

  it('shows an icon named About <label> for a tip', () => {
    const { container } = render(<Stat label="Online" value={4} tip="Checked in within 15 minutes." />);
    expect(screen.getByRole('button', { name: 'About Online' }).getAttribute('data-tip')).toBe('Checked in within 15 minutes.');
    expect(container.querySelector('.stat-top .stat-info')).not.toBeNull();
  });

  it('puts the icon in the corner of a clickable Stat', () => {
    const onClick = vi.fn();
    const { container } = render(<Stat label="Online" value={4} tip="Checked in." onClick={onClick} />);
    const icon = screen.getByRole('button', { name: 'About Online' });
    const card = container.querySelector('.stat') as HTMLElement;
    expect(card.contains(icon)).toBe(false);
    expect(icon.closest('.stat-corner')).not.toBeNull();
    fireEvent.click(icon);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('takes an info node ahead of tip', () => {
    render(<Stat label="Online" value={4} tip="Ignored." info={<InfoTip short="From the node." label="About online devices" />} />);
    expect(screen.getByRole('button', { name: 'About online devices' }).getAttribute('data-tip')).toBe('From the node.');
    expect(screen.queryByRole('button', { name: 'About Online' })).toBeNull();
  });
});

describe('CardHead info', () => {
  it('renders the previous markup without info', () => {
    const { container } = render(<CardHead title="Devices" />);
    expect(container.querySelector('.card-title-row')).toBeNull();
    expect(screen.queryByRole('button', { name: /About/ })).toBeNull();
    expect(container.querySelector('.card-titles > h2.card-title')?.textContent).toBe('Devices');
  });

  it('shows the icon beside the title for a string', () => {
    const { container } = render(<CardHead title="Devices" info="Every enrolled device." />);
    expect(screen.getByRole('button', { name: 'About Devices' }).getAttribute('data-tip')).toBe('Every enrolled device.');
    expect(container.querySelector('.card-title-row > h2.card-title')).not.toBeNull();
  });

  it('places a node as given', () => {
    render(<CardHead title="Devices" info={<span data-testid="custom">i</span>} />);
    expect(screen.getByTestId('custom')).toBeTruthy();
  });
});

describe('glossary term underline', () => {
  const rule = /^\.term \{[^}]*\}/m.exec(kitCss)?.[0] ?? '';
  it('is dotted, 2px, offset 3px and token coloured at rest', () => {
    expect(rule).toContain('text-decoration: underline dotted');
    expect(rule).toContain('text-decoration-thickness: 2px');
    expect(rule).toContain('text-underline-offset: 3px');
    expect(rule).toContain('text-decoration-color: var(--text-secondary)');
    expect(rule).not.toMatch(/#[0-9a-f]{3,8}|rgb\(/i);
  });
  it('goes to the primary ink on hover and focus', () => {
    expect(kitCss).toMatch(/\.term:hover \{ text-decoration-color: var\(--text-primary\); \}/);
    expect(kitCss).toMatch(/\.term:focus-visible \{[^}]*text-decoration-color: var\(--text-primary\)/);
  });
});
