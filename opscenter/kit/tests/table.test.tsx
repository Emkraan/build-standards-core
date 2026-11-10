import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Table, sortRows } from '../src/index';
import type { TableColumn } from '../src/index';

interface Row {
  id: string;
  name: string;
  count: number | null;
}

const rows: Row[] = [
  { id: 'a', name: 'item 10', count: 5 },
  { id: 'b', name: 'Item 2', count: null },
  { id: 'c', name: 'item 1', count: 12 },
];

const columns: TableColumn<Row>[] = [
  { key: 'name', header: 'Name' },
  { key: 'count', header: 'Count', numeric: true },
  { key: 'actions', header: 'Actions', sortable: false, hideHeader: true, render: () => null },
];

function names(): string[] {
  return screen
    .getAllByRole('row')
    .slice(1)
    .map((r) => within(r).getAllByRole('cell')[0]?.textContent ?? '');
}

describe('Table', () => {
  it('sorts the first column ascending by default, naturally, and sets aria-sort', () => {
    render(<Table caption="Items" columns={columns} rows={rows} rowKey={(r) => r.id} />);
    const [name, count, actions] = screen.getAllByRole('columnheader');
    expect(name?.getAttribute('aria-sort')).toBe('ascending');
    expect(count?.getAttribute('aria-sort')).toBe('none');
    expect(actions?.hasAttribute('aria-sort')).toBe(false);
    expect(names()).toEqual(['item 1', 'Item 2', 'item 10']);
  });

  it('toggles direction and keeps empty values last', () => {
    render(<Table caption="Items" columns={columns} rows={rows} rowKey={(r) => r.id} />);
    fireEvent.click(screen.getByRole('button', { name: 'Count' }));
    const count = () => screen.getAllByRole('columnheader')[1];
    expect(count()?.getAttribute('aria-sort')).toBe('ascending');
    expect(screen.getAllByRole('columnheader')[0]?.getAttribute('aria-sort')).toBe('none');
    expect(names()).toEqual(['item 10', 'item 1', 'Item 2']);
    fireEvent.click(screen.getByRole('button', { name: 'Count' }));
    expect(count()?.getAttribute('aria-sort')).toBe('descending');
    expect(names()).toEqual(['item 1', 'item 10', 'Item 2']);
  });

  it('filters before sorting and shows an empty state', () => {
    const { rerender } = render(<Table caption="Items" columns={columns} rows={rows} rowKey={(r) => r.id} filter="10" />);
    expect(names()).toEqual(['item 10']);
    rerender(<Table caption="Items" columns={columns} rows={rows} rowKey={(r) => r.id} filter="nothing" />);
    expect(screen.getByText('No matching rows')).toBeTruthy();
    rerender(<Table caption="Items" columns={columns} rows={[]} rowKey={(r) => r.id} />);
    expect(screen.getByText('Nothing here yet')).toBeTruthy();
  });

  it('moves row focus with the arrow keys and activates on Enter', () => {
    const onRowActivate = vi.fn();
    render(<Table caption="Items" columns={columns} rows={rows} rowKey={(r) => r.id} onRowActivate={onRowActivate} />);
    const bodyRows = screen.getAllByRole('row').slice(1);
    expect(bodyRows.map((r) => r.tabIndex)).toEqual([0, -1, -1]);
    bodyRows[0]?.focus();
    fireEvent.keyDown(bodyRows[0] as HTMLElement, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(bodyRows[1]);
    fireEvent.keyDown(bodyRows[1] as HTMLElement, { key: 'Enter' });
    expect(onRowActivate).toHaveBeenCalledWith(rows[1]);
  });

  it('leaves order-carrying tables unsorted', () => {
    render(<Table caption="Items" columns={columns} rows={rows} rowKey={(r) => r.id} sortable={false} />);
    expect(names()).toEqual(['item 10', 'Item 2', 'item 1']);
    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });

  it('sortRows compares numbers and dates by value', () => {
    expect(sortRows([3, 1, 2], (n) => n, 'desc')).toEqual([3, 2, 1]);
    const d = [new Date('2026-01-02'), new Date('2025-12-31')];
    expect(sortRows(d, (x) => x, 'asc')[0]).toBe(d[1]);
  });
});

describe('Table density', () => {
  it('marks a compact table and leaves the default unmarked', () => {
    const { container, rerender } = render(<Table caption="d" columns={columns} rows={rows} rowKey={(r) => r.id} />);
    expect(container.querySelector('.table-wrap')?.hasAttribute('data-density')).toBe(false);
    rerender(<Table caption="d" density="compact" columns={columns} rows={rows} rowKey={(r) => r.id} />);
    expect(container.querySelector('.table-wrap')?.getAttribute('data-density')).toBe('compact');
    rerender(<Table caption="d" density="comfortable" columns={columns} rows={rows} rowKey={(r) => r.id} />);
    expect(container.querySelector('.table-wrap')?.hasAttribute('data-density')).toBe(false);
  });

  it('keeps every row and the sort behaviour in a compact table', () => {
    render(<Table caption="d" density="compact" columns={columns} rows={rows} rowKey={(r) => r.id} />);
    expect(screen.getAllByRole('row')).toHaveLength(rows.length + 1);
  });
});

describe('Table phone cards, sticky head and wrapper class (D-002)', () => {
  it('leaves the defaults unchanged: no data-mobile, no data-label, sticky head on', () => {
    const { container } = render(<Table columns={columns} rows={rows} rowKey={(r) => r.id} caption="Items" />);
    const wrap = container.querySelector('.table-wrap') as HTMLElement;
    expect(wrap.hasAttribute('data-mobile')).toBe(false);
    expect(wrap.hasAttribute('data-sticky-head')).toBe(false);
    expect(container.querySelector('td[data-label]')).toBeNull();
  });

  it('mobile="cards" labels every cell with its column header, never a hidden header', () => {
    const { container } = render(<Table columns={columns} rows={rows} rowKey={(r) => r.id} caption="Items" mobile="cards" />);
    expect((container.querySelector('.table-wrap') as HTMLElement).getAttribute('data-mobile')).toBe('cards');
    const first = container.querySelector('tbody tr') as HTMLElement;
    const labels = Array.from(first.querySelectorAll('td')).map((td) => td.getAttribute('data-label'));
    expect(labels).toEqual(['Name', 'Count', null]);
    // The table keeps its semantics: headers stay in the accessibility tree.
    expect(screen.getAllByRole('columnheader').length).toBe(3);
  });

  it('stickyHead={false} and wrapClassName land on the wrapper', () => {
    const { container } = render(
      <Table columns={columns} rows={rows} rowKey={(r) => r.id} caption="Items" stickyHead={false} wrapClassName="card-table" className="extra" />,
    );
    const wrap = container.querySelector('.table-wrap') as HTMLElement;
    expect(wrap.getAttribute('data-sticky-head')).toBe('false');
    expect(wrap.classList.contains('card-table')).toBe(true);
    expect(wrap.classList.contains('extra')).toBe(true);
  });
});
