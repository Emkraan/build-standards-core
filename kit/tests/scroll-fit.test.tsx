/* Table capped and LaneBoard fit: the scroll-keeping hooks (a short window never traps the page), and the CSS carries the floors. */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render, screen } from '@testing-library/react';
import axe from 'axe-core';
import { describe, expect, it } from 'vitest';
import { LaneBoard, Table } from '../src';

const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');
const columns = [{ key: 'name', header: 'Name' }];
const rows = [{ id: '1', name: 'One' }];

describe('scroll-keeping parts', () => {
  it('a capped table is a focusable named region', () => {
    render(<Table caption="Devices" capped columns={columns} rows={rows} rowKey={(r) => r.id} />);
    const region = screen.getByRole('region', { name: 'Devices' });
    expect(region.hasAttribute('data-capped')).toBe(true);
    expect(region.getAttribute('tabindex')).toBe('0');
  });

  it('an uncapped table, or one with maxHeight, is unchanged', () => {
    const { container, rerender } = render(<Table caption="Devices" columns={columns} rows={rows} rowKey={(r) => r.id} />);
    expect(container.querySelector('[data-capped]')).toBeNull();
    rerender(<Table caption="Devices" capped maxHeight="10rem" columns={columns} rows={rows} rowKey={(r) => r.id} />);
    expect(container.querySelector('[data-capped]')).toBeNull();
  });

  it('a fitted board marks itself and has no axe violations', async () => {
    const lanes = [{ id: 'a', label: 'To do', cards: [{ id: '1', label: 'One' }] }];
    const { container } = render(<LaneBoard lanes={lanes} onMove={() => {}} fit />);
    expect(container.querySelector('.lane-board')?.hasAttribute('data-fit')).toBe(true);
    const result = await axe.run(container);
    expect(result.violations).toEqual([]);
  });

  it('the stylesheet keeps the floors and never hides overflow on the board', () => {
    expect(css).toMatch(/\.table-wrap\[data-capped\][^}]*max-height: calc\(100vh - 15rem\)/);
    expect(css).not.toMatch(/\.table-wrap\[data-capped\][^}]*min-height/);
    expect(css).toMatch(/\.lane-board\[data-fit\][^}]*height: calc\(100vh - 6rem\)[^}]*min-height: 360px/);
    expect(css).toMatch(/\.page-scroll[^}]*overflow-y: auto/);
    expect(css).not.toMatch(/\.lane-board\[data-fit\][^}]*overflow: hidden/);
  });
});
