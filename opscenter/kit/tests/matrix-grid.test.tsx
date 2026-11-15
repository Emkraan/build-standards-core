/* MatrixGrid: structure, density, group headings and the grid keyboard model. */
import { fireEvent, render, screen } from '@testing-library/react';
import axe from 'axe-core';
import { describe, expect, it, vi } from 'vitest';
import { MatrixGrid } from '../src';
import type { MatrixColumn, MatrixRow } from '../src';

const columns: MatrixColumn[] = [
  { id: 'a', label: 'Ana' },
  { id: 'b', label: 'Ben' },
  { id: 'c', label: 'Chloe', name: 'Chloe Lin' },
];
const rows: MatrixRow[] = [
  { id: 'r1', label: 'Patching', group: 'Ops' },
  { id: 'r2', label: 'Backups', group: 'Ops' },
  { id: 'r3', label: 'Audit', group: 'Gov' },
];
const cell = (r: number, c: number) => document.querySelector<HTMLElement>(`[data-r="${r}"][data-c="${c}"]`) as HTMLElement;
const show = (r: MatrixRow, c: MatrixColumn) => `${r.id}${c.id}`;

describe('MatrixGrid structure', () => {
  it('is a labelled grid with column heads, row heads and group headings', async () => {
    const { container } = render(<MatrixGrid label="Matrix" columns={columns} rows={rows} renderCell={show} cornerLabel="Task" />);
    expect(screen.getByRole('grid', { name: 'Matrix' })).toBeTruthy();
    expect(screen.getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Task', 'Ana', 'Ben', 'Chloe']);
    expect(screen.getAllByRole('rowheader').map((h) => h.textContent)).toEqual(['Ops', 'Patching', 'Backups', 'Gov', 'Audit']);
    expect(screen.getAllByRole('gridcell')).toHaveLength(9);
    expect(container.querySelectorAll('.matrix-group')).toHaveLength(2);
    const r = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } });
    expect(r.violations.map((v) => v.id)).toEqual([]);
  });

  it('defaults to compact, takes density, widths and a height cap, tones and spoken text', () => {
    const { container, rerender } = render(<MatrixGrid label="M" columns={columns} rows={rows} renderCell={show} />);
    const wrap = container.querySelector('.matrix-grid') as HTMLElement;
    expect(wrap.dataset['density']).toBe('compact');
    expect(wrap.hasAttribute('data-capped')).toBe(false);
    rerender(
      <MatrixGrid
        label="M"
        columns={columns}
        rows={rows}
        renderCell={show}
        density="dense"
        rowHeaderWidth="10rem"
        columnWidth="3rem"
        maxHeight="20rem"
        cellTone={(r, c) => (r.id === 'r1' && c.id === 'a' ? 'danger' : undefined)}
        cellLabel={(r, c) => (r.id === 'r1' && c.id === 'c' ? 'Responsible' : undefined)}
      />,
    );
    expect(wrap.dataset['density']).toBe('dense');
    expect(wrap.style.getPropertyValue('--matrix-row-head-w')).toBe('10rem');
    expect(wrap.style.getPropertyValue('--matrix-col-w')).toBe('3rem');
    expect(wrap.style.getPropertyValue('--matrix-max-h')).toBe('20rem');
    expect(wrap.hasAttribute('data-capped')).toBe(true);
    expect(cell(0, 0).dataset['tone']).toBe('danger');
    expect(cell(0, 2).getAttribute('aria-label')).toBe('Patching, Chloe Lin: Responsible');
    expect(cell(0, 1).getAttribute('aria-label')).toBeNull();
  });

  it('shows the empty state without rows', () => {
    render(<MatrixGrid label="M" columns={columns} rows={[]} renderCell={show} empty={<p>No people</p>} />);
    expect(screen.queryByRole('grid')).toBeNull();
    expect(screen.getByText('No people')).toBeTruthy();
  });
});

describe('MatrixGrid keyboard', () => {
  it('keeps one tab stop and moves it with the arrows, clamped at the edges', () => {
    render(<MatrixGrid label="M" columns={columns} rows={rows} renderCell={show} />);
    expect(document.querySelectorAll('[role="gridcell"][tabindex="0"]')).toHaveLength(1);
    cell(0, 0).focus();
    fireEvent.keyDown(cell(0, 0), { key: 'ArrowLeft' });
    expect(document.activeElement).toBe(cell(0, 0));
    fireEvent.keyDown(cell(0, 0), { key: 'ArrowRight' });
    expect(document.activeElement).toBe(cell(0, 1));
    fireEvent.keyDown(cell(0, 1), { key: 'ArrowDown' });
    expect(document.activeElement).toBe(cell(1, 1));
    fireEvent.keyDown(cell(1, 1), { key: 'ArrowUp' });
    fireEvent.keyDown(cell(0, 1), { key: 'ArrowUp' });
    expect(document.activeElement).toBe(cell(0, 1));
    expect(cell(0, 1).tabIndex).toBe(0);
    expect(cell(0, 0).tabIndex).toBe(-1);
  });

  it('Home and End go along the row, with Ctrl to the corners', () => {
    render(<MatrixGrid label="M" columns={columns} rows={rows} renderCell={show} />);
    cell(1, 1).focus();
    fireEvent.keyDown(cell(1, 1), { key: 'End' });
    expect(document.activeElement).toBe(cell(1, 2));
    fireEvent.keyDown(cell(1, 2), { key: 'Home' });
    expect(document.activeElement).toBe(cell(1, 0));
    fireEvent.keyDown(cell(1, 0), { key: 'End', ctrlKey: true });
    expect(document.activeElement).toBe(cell(2, 2));
    fireEvent.keyDown(cell(2, 2), { key: 'Home', ctrlKey: true });
    expect(document.activeElement).toBe(cell(0, 0));
  });

  it('Enter, Space and a click activate a cell; a control inside keeps its own click', () => {
    const onCellActivate = vi.fn();
    render(
      <MatrixGrid
        label="M"
        columns={columns}
        rows={rows}
        renderCell={(r, c) => (r.id === 'r2' && c.id === 'a' ? <button type="button">edit</button> : show(r, c))}
        onCellActivate={onCellActivate}
      />,
    );
    cell(0, 1).focus();
    fireEvent.keyDown(cell(0, 1), { key: 'Enter' });
    fireEvent.keyDown(cell(0, 1), { key: ' ' });
    expect(onCellActivate).toHaveBeenCalledTimes(2);
    expect(onCellActivate).toHaveBeenLastCalledWith(rows[0], columns[1]);
    fireEvent.click(cell(2, 2));
    expect(onCellActivate).toHaveBeenLastCalledWith(rows[2], columns[2]);
    onCellActivate.mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'edit' }));
    expect(onCellActivate).not.toHaveBeenCalled();
  });

  it('is read only without onCellActivate', () => {
    render(<MatrixGrid label="M" columns={columns} rows={rows} renderCell={show} />);
    expect(cell(0, 0).hasAttribute('data-active')).toBe(false);
    expect(() => fireEvent.keyDown(cell(0, 0), { key: 'Enter' })).not.toThrow();
  });
});

describe('MatrixGrid review fixes', () => {
  it('gives a group that returns after another group its own heading and key', () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const split: MatrixRow[] = [
      { id: 'r1', label: 'One', group: 'Team A' },
      { id: 'r2', label: 'Two', group: 'Team B' },
      { id: 'r3', label: 'Three', group: 'Team A' },
    ];
    const { container } = render(<MatrixGrid label="M" columns={columns} rows={split} renderCell={show} />);
    const headings = Array.from(container.querySelectorAll('.matrix-group th')).map((h) => h.textContent);
    expect(headings).toEqual(['Team A', 'Team B', 'Team A']);
    expect(err.mock.calls.flat().join(' ')).not.toMatch(/same key|unique "key"/);
    err.mockRestore();
  });

  it('shows the empty state, not a cell-less grid, when there are no columns', () => {
    render(<MatrixGrid label="M" columns={[]} rows={rows} renderCell={show} empty={<p>No columns</p>} />);
    expect(screen.queryByRole('grid')).toBeNull();
    expect(screen.getByText('No columns')).toBeTruthy();
  });

  it('keeps Space from scrolling the page on a read only cell, and leaves Enter alone', () => {
    render(<MatrixGrid label="M" columns={columns} rows={rows} renderCell={show} />);
    expect(fireEvent.keyDown(cell(0, 0), { key: ' ' })).toBe(false);
    expect(fireEvent.keyDown(cell(0, 0), { key: 'Enter' })).toBe(true);
  });
});
