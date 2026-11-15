import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { GroupHeader, ListControls, Pagination, applyGrouping, applySort, paginate, usePagedState } from '../src/index';
import type { SortDirection } from '../src/index';

interface Row {
  name: string;
  site: string | null;
  size: number | null;
}

const ROWS: Row[] = [
  { name: 'item 10', site: 'North', size: 5 },
  { name: 'Item 2', site: 'south', size: null },
  { name: 'item 1', site: null, size: 12 },
  { name: 'item 3', site: 'North', size: 5 },
];
const GETTERS = { name: (r: Row) => r.name, size: (r: Row) => r.size, site: (r: Row) => r.site };

describe('applySort', () => {
  it('sorts text with numeric, case-insensitive collation and keeps ties in order', () => {
    expect(applySort(ROWS, 'name', 'asc', GETTERS).map((r) => r.name)).toEqual(['item 1', 'Item 2', 'item 3', 'item 10']);
    expect(applySort(ROWS, 'size', 'asc', GETTERS).map((r) => r.name)).toEqual(['item 10', 'item 3', 'item 1', 'Item 2']);
  });

  it('puts empty values last in both directions', () => {
    expect(applySort(ROWS, 'size', 'desc', GETTERS).map((r) => r.name)).toEqual(['item 1', 'item 10', 'item 3', 'Item 2']);
    expect(applySort(ROWS, 'site', 'desc', GETTERS).at(-1)?.site).toBeNull();
  });

  it('returns a copy for no key or an unknown key and never mutates the input', () => {
    const copy = [...ROWS];
    expect(applySort(ROWS, null, 'asc', GETTERS)).toEqual(ROWS);
    expect(applySort(ROWS, 'nope', 'asc', GETTERS)).not.toBe(ROWS);
    applySort(ROWS, 'name', 'desc', GETTERS);
    expect(ROWS).toEqual(copy);
  });
});

describe('applyGrouping', () => {
  it('groups by label, puts the unspecified group last and accepts its label', () => {
    const groups = applyGrouping(ROWS, 'site', GETTERS, 'No site');
    expect(groups?.map((g) => [g.label, g.items.length])).toEqual([['North', 2], ['south', 1], ['No site', 1]]);
  });

  it('returns null with no key or an unknown key', () => {
    expect(applyGrouping(ROWS, null, GETTERS)).toBeNull();
    expect(applyGrouping(ROWS, 'nope', GETTERS)).toBeNull();
  });
});

describe('paginate and usePagedState', () => {
  const nums = Array.from({ length: 7 }, (_, i) => i + 1);

  it('slices a page and clamps the page into range', () => {
    expect(paginate(nums, 1, 3)).toEqual([1, 2, 3]);
    expect(paginate(nums, 3, 3)).toEqual([7]);
    expect(paginate(nums, 99, 3)).toEqual([7]);
    expect(paginate(nums, 0, 3)).toEqual([1, 2, 3]);
    expect(paginate([], 1, 3)).toEqual([]);
  });

  it('returns to page 1 on a size change or a reset', async () => {
    const user = userEvent.setup();
    function Probe() {
      const s = usePagedState(10);
      return (
        <div>
          <output aria-label="state">{`${s.page}/${s.pageSize}`}</output>
          <button onClick={() => s.setPage(4)}>four</button>
          <button onClick={() => s.setPageSize(25)}>size</button>
          <button onClick={s.reset}>reset</button>
        </div>
      );
    }
    render(<Probe />);
    await user.click(screen.getByText('four'));
    expect(screen.getByLabelText('state').textContent).toBe('4/10');
    await user.click(screen.getByText('size'));
    expect(screen.getByLabelText('state').textContent).toBe('1/25');
    await user.click(screen.getByText('four'));
    await user.click(screen.getByText('reset'));
    expect(screen.getByLabelText('state').textContent).toBe('1/25');
  });
});

function Host({ onFilter }: { onFilter?: (v: string) => void }) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDirection>('asc');
  const [groupKey, setGroupKey] = useState<string | null>(null);
  const [status, setStatus] = useState('');
  return (
    <ListControls
      filters={[{ id: 'status', label: 'Status', allLabel: 'All statuses', value: status, onChange: (v) => { setStatus(v); onFilter?.(v); }, options: [{ value: 'on', label: 'Online' }, { value: 'off', label: 'Offline' }], showCount: true }]}
      sortOptions={[{ id: 'name', label: 'Name' }, { id: 'size', label: 'Size' }]}
      sortKey={sortKey}
      sortDir={sortDir}
      onSortKeyChange={setSortKey}
      onSortDirChange={setSortDir}
      groupOptions={[{ id: 'site', label: 'Site' }]}
      groupKey={groupKey}
      onGroupKeyChange={setGroupKey}
      rightSlot={<span>4 rows</span>}
    />
  );
}

describe('ListControls', () => {
  it('names every control, wires the filter, sort, direction and group, and passes axe', async () => {
    const user = userEvent.setup();
    const onFilter = vi.fn();
    const { container } = render(<Host onFilter={onFilter} />);
    const bar = screen.getByRole('group', { name: 'List controls' });
    const filter = within(bar).getByRole('combobox', { name: 'Status' }) as HTMLSelectElement;
    expect(within(filter).getAllByRole('option')[0]?.textContent).toBe('All statuses (2)');
    await user.selectOptions(filter, 'off');
    expect(onFilter).toHaveBeenCalledWith('off');

    const sort = within(bar).getByRole('combobox', { name: 'Sort' }) as HTMLSelectElement;
    await user.selectOptions(sort, 'size');
    expect(sort.value).toBe('size');
    await user.selectOptions(sort, 'Default order');
    expect(sort.value).toBe('');

    const dir = within(bar).getByRole('button', { name: 'Ascending, switch to descending' });
    await user.click(dir);
    expect(within(bar).getByRole('button', { name: 'Descending, switch to ascending' }).getAttribute('data-dir')).toBe('desc');

    const group = within(bar).getByRole('combobox', { name: 'Group by' }) as HTMLSelectElement;
    await user.selectOptions(group, 'site');
    expect(group.value).toBe('site');
    expect(within(bar).getByText('4 rows')).toBeTruthy();

    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } }, resultTypes: ['violations'] });
    expect(result.violations.map((v) => v.id)).toEqual([]);
  });

  it('draws only the controls it was given', () => {
    render(<ListControls label="Runs" sortOptions={[{ id: 'a', label: 'A' }]} onSortKeyChange={() => undefined} />);
    const bar = screen.getByRole('group', { name: 'Runs' });
    expect(within(bar).getByRole('combobox', { name: 'Sort' })).toBeTruthy();
    expect(within(bar).queryByRole('button')).toBeNull();
    expect(within(bar).queryByRole('combobox', { name: 'Group by' })).toBeNull();
  });
});

describe('GroupHeader and the Pagination page size', () => {
  it('shows the label and count', () => {
    render(<GroupHeader label="North" count={2} />);
    expect(screen.getByText('North')).toBeTruthy();
    expect(screen.getByText('2')).toBeTruthy();
  });

  it('adds a labelled page size select only when asked and disables everything while loading', async () => {
    const user = userEvent.setup();
    const onSize = vi.fn();
    const { rerender } = render(<Pagination page={2} pageSize={50} total={400} unit="rows" onPageSizeChange={onSize} />);
    const size = screen.getByRole('combobox', { name: 'Rows per page' }) as HTMLSelectElement;
    expect(size.value).toBe('50');
    await user.selectOptions(size, '100');
    expect(onSize).toHaveBeenCalledWith(100);
    rerender(<Pagination page={2} pageSize={50} total={400} unit="rows" onPageSizeChange={onSize} loading />);
    expect((screen.getByRole('combobox', { name: 'Rows per page' }) as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Next' }) as HTMLButtonElement).disabled).toBe(true);
    rerender(<Pagination page={2} pageSize={50} total={400} />);
    expect(screen.queryByRole('combobox')).toBeNull();
  });
});
