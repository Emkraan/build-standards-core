/* ListTable, Pagination with page sizes, usePagination and SplitLayout: roles, names, keyboard,
   selection, the resize handle and the stacked narrow layout. */
import { act, fireEvent, render, renderHook, screen, within } from '@testing-library/react';
import axe from 'axe-core';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  ListTable,
  Pagination,
  SPLIT_DEFAULT_WIDTH,
  SplitLayout,
  clampSplitWidth,
  groupRows,
  useRowSelection,
  usePagination,
} from '../src';

interface Item {
  id: string;
  name: string;
  note: string;
  group: string | null;
}

const ITEMS: Item[] = [
  { id: 'a', name: 'Alpha', note: 'first note', group: 'North' },
  { id: 'b', name: 'Bravo', note: 'second note', group: 'South' },
  { id: 'c', name: 'Charlie', note: 'third note', group: 'North' },
  { id: 'd', name: 'Delta', note: 'fourth note', group: null },
];

async function noAxe(el: Element) {
  const r = await axe.run(el, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
  expect(r.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' ')}`)).toEqual([]);
}

function Harness({ onOpen = () => undefined, grouped = false }: { onOpen?: (item: Item) => void; grouped?: boolean }) {
  const ids = ITEMS.map((i) => i.id);
  const selection = useRowSelection(ids);
  const [open, setOpen] = useState<string | null>(null);
  return (
    <>
      <span data-testid="count">{selection.count}</span>
      <ListTable
        caption="Items"
        rows={ITEMS}
        rowKey={(r) => r.id}
        primary={(r) => r.name}
        secondary={(r) => r.note}
        leading={(r) => <span data-testid={`lead-${r.id}`}>L</span>}
        trailing={(r) => <button type="button">More {r.name}</button>}
        groupBy={grouped ? (r) => r.group : undefined}
        selectedKey={open}
        selection={selection}
        selectionLabel={(r) => `Pick ${r.name}`}
        isRowSelectable={(r) => r.id !== 'c'}
        header="Name"
        onRowActivate={(r) => {
          setOpen(r.id);
          onOpen(r);
        }}
      />
    </>
  );
}

describe('ListTable', () => {
  it('renders each row as a list item with primary, secondary, leading and trailing slots', () => {
    render(<Harness />);
    const list = screen.getByRole('list', { name: 'Items' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(4);
    expect(within(rows[0] as HTMLElement).getByText('Alpha')).toBeTruthy();
    expect(within(rows[0] as HTMLElement).getByText('first note')).toBeTruthy();
    expect(screen.getByTestId('lead-a')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'More Alpha' })).toBeTruthy();
  });

  it('groups rows under named headers in order of first use and keeps ungrouped rows apart', () => {
    render(<Harness grouped />);
    const north = screen.getByRole('list', { name: 'North' });
    const south = screen.getByRole('list', { name: 'South' });
    expect(within(north).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      expect.stringContaining('Alpha'),
      expect.stringContaining('Charlie'),
    ]);
    expect(within(south).getAllByRole('listitem')).toHaveLength(1);
    expect(screen.getByText('Delta')).toBeTruthy();
    expect(groupRows(ITEMS, (r) => r.group).map((s) => s.key)).toEqual(['North', 'South', null]);
    expect(groupRows(ITEMS).map((s) => s.key)).toEqual([null]);
  });

  it('opens a row on click and Enter, and marks it with aria-current', () => {
    const onOpen = vi.fn();
    render(<Harness onOpen={onOpen} />);
    const rows = screen.getAllByRole('listitem');
    fireEvent.click(rows[1] as HTMLElement);
    expect(onOpen).toHaveBeenLastCalledWith(ITEMS[1]);
    expect((screen.getAllByRole('listitem')[1] as HTMLElement).getAttribute('aria-current')).toBe('true');
    expect((screen.getAllByRole('listitem')[0] as HTMLElement).getAttribute('aria-current')).toBeNull();
    fireEvent.keyDown(rows[2] as HTMLElement, { key: 'Enter' });
    expect(onOpen).toHaveBeenLastCalledWith(ITEMS[2]);
  });

  it('moves focus with the arrow keys, Home and End, with one tab stop', () => {
    render(<Harness />);
    const rows = () => screen.getAllByRole('listitem');
    expect(rows().map((r) => r.tabIndex)).toEqual([0, -1, -1, -1]);
    (rows()[0] as HTMLElement).focus();
    fireEvent.keyDown(document.activeElement as Element, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(rows()[1]);
    fireEvent.keyDown(document.activeElement as Element, { key: 'End' });
    expect(document.activeElement).toBe(rows()[3]);
    fireEvent.keyDown(document.activeElement as Element, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(rows()[3]);
    fireEvent.keyDown(document.activeElement as Element, { key: 'Home' });
    expect(document.activeElement).toBe(rows()[0]);
    expect(rows().map((r) => r.tabIndex)).toEqual([0, -1, -1, -1]);
  });

  it('follows the visible order when rows are grouped', () => {
    render(<Harness grouped />);
    const rows = screen.getAllByRole('listitem').filter((li) => li.hasAttribute('data-list-row'));
    expect(rows.map((r) => r.querySelector('.list-row-primary')?.textContent)).toEqual(['Alpha', 'Charlie', 'Bravo', 'Delta']);
    (rows[0] as HTMLElement).focus();
    fireEvent.keyDown(document.activeElement as Element, { key: 'ArrowDown' });
    expect(document.activeElement?.textContent).toContain('Charlie');
  });

  it('checks a row without opening it, and a button in a row never opens it', () => {
    const onOpen = vi.fn();
    render(<Harness onOpen={onOpen} />);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Pick Alpha' }));
    expect(screen.getByTestId('count').textContent).toBe('1');
    fireEvent.click(screen.getByRole('button', { name: 'More Bravo' }));
    fireEvent.keyDown(screen.getByRole('button', { name: 'More Bravo' }), { key: 'Enter' });
    expect(onOpen).not.toHaveBeenCalled();
    expect(screen.getAllByRole('listitem').some((li) => li.getAttribute('aria-current'))).toBe(false);
  });

  it('turns the header checkbox indeterminate over a partial selection and selects only selectable rows', () => {
    render(<Harness />);
    const all = screen.getByRole('checkbox', { name: 'Select all visible rows' }) as HTMLInputElement;
    expect(all.indeterminate).toBe(false);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Pick Alpha' }));
    expect(all.indeterminate).toBe(true);
    fireEvent.click(all);
    expect(screen.getByTestId('count').textContent).toBe('3');
    expect((screen.getByRole('checkbox', { name: 'Pick Charlie' }) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole('checkbox', { name: 'Pick Charlie' }) as HTMLInputElement).checked).toBe(false);
    expect(all.checked).toBe(true);
    expect(all.indeterminate).toBe(false);
    fireEvent.click(all);
    expect(screen.getByTestId('count').textContent).toBe('0');
  });

  it('shows the empty state and no header controls when there are no rows', () => {
    render(<ListTable caption="Nothing" rows={[]} rowKey={(r: Item) => r.id} primary={(r: Item) => r.name} empty={<p>Nothing to list</p>} />);
    expect(screen.getByText('Nothing to list')).toBeTruthy();
    expect(screen.queryByRole('list')).toBeNull();
  });

  it('has no axe violations, plain and grouped with a selection', async () => {
    const { container, rerender } = render(<Harness />);
    await noAxe(container);
    rerender(<Harness grouped />);
    await noAxe(container);
  });
});

describe('Pagination page sizes', () => {
  it('offers the size choices, always including the current size, and reports a change', () => {
    const onSize = vi.fn();
    render(<Pagination page={1} pageSize={30} total={500} unit="rows" pageSizeOptions={[25, 50, 100, 200]} onPageSizeChange={onSize} />);
    const select = screen.getByRole('combobox', { name: 'Rows per page' }) as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual(['25', '30', '50', '100', '200']);
    expect(select.value).toBe('30');
    fireEvent.change(select, { target: { value: '100' } });
    expect(onSize).toHaveBeenCalledWith(100);
    expect(screen.getByText('1 to 30 of 500 rows')).toBeTruthy();
  });

  it('shows no select without a handler, so the old pager is unchanged', () => {
    render(<Pagination pageSize={25} total={80} pageSizeOptions={[25, 50]} />);
    expect(screen.queryByRole('combobox')).toBeNull();
  });

  it('has no axe violations with the select', async () => {
    const { container } = render(<Pagination page={2} pageSize={25} total={80} pageSizeOptions={[25, 50]} onPageSizeChange={() => undefined} />);
    await noAxe(container);
  });
});

describe('usePagination', () => {
  it('slices the page, walks pages through its props and clamps at the ends', () => {
    const rows = Array.from({ length: 60 }, (_, i) => i);
    const { result } = renderHook(() => usePagination(rows.length, 25));
    expect(result.current.slice(rows)).toHaveLength(25);
    act(() => result.current.props.onNext?.());
    act(() => result.current.props.onNext?.());
    expect(result.current.page).toBe(3);
    expect(result.current.slice(rows)).toEqual(rows.slice(50));
    act(() => result.current.setPage(99));
    expect(result.current.page).toBe(3);
    act(() => result.current.setPage(-4));
    expect(result.current.page).toBe(1);
  });

  it('keeps the first row on screen when the page size changes and pulls the page back when the total shrinks', () => {
    const { result, rerender } = renderHook(({ total }) => usePagination(total, 25), { initialProps: { total: 300 } });
    act(() => result.current.setPage(3));
    act(() => result.current.setPageSize(100));
    expect(result.current.page).toBe(1);
    act(() => result.current.setPage(3));
    act(() => result.current.setPageSize(50));
    expect(result.current.page).toBe(5);
    rerender({ total: 120 });
    expect(result.current.page).toBe(3);
    expect(result.current.pageCount).toBe(3);
  });
});

describe('clampSplitWidth', () => {
  it('stays inside the bounds and leaves the detail pane its minimum', () => {
    expect(clampSplitWidth(100, 240, 640)).toBe(240);
    expect(clampSplitWidth(900, 240, 640)).toBe(640);
    expect(clampSplitWidth(500, 240, 640, 800, 320)).toBe(472);
    expect(clampSplitWidth(500, 240, 640, 300, 320)).toBe(240);
  });
});

function setContainerWidth(width: number) {
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
    width,
    height: 400,
    top: 0,
    left: 0,
    right: width,
    bottom: 400,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  });
}

function Split(props: Partial<Parameters<typeof SplitLayout>[0]> = {}) {
  return <SplitLayout listLabel="Item list" detailLabel="Item detail" list={<p>list body</p>} detail={<p>detail body</p>} {...props} />;
}

describe('SplitLayout', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('renders a named list pane, a detail pane and a focusable vertical separator with its value', () => {
    setContainerWidth(1200);
    render(<Split />);
    expect(screen.getByRole('region', { name: 'Item list' }).textContent).toBe('list body');
    expect(screen.getByRole('region', { name: 'Item detail' }).textContent).toBe('detail body');
    const handle = screen.getByRole('separator', { name: 'Resize list pane' });
    expect(handle.getAttribute('aria-orientation')).toBe('vertical');
    expect(handle.getAttribute('aria-valuenow')).toBe(String(SPLIT_DEFAULT_WIDTH));
    expect(handle.getAttribute('aria-valuemin')).toBe('240');
    expect(handle.getAttribute('aria-valuemax')).toBe('640');
    expect(handle.tabIndex).toBe(0);
    expect(handle.getAttribute('aria-controls')).toBe(screen.getByRole('region', { name: 'Item list' }).id);
    expect(document.querySelector<HTMLElement>('.split')?.style.getPropertyValue('--split-list')).toBe('360px');
  });

  it('resizes from the keyboard: arrows, Shift, Home, End and Enter to reset', () => {
    setContainerWidth(1200);
    const onWidth = vi.fn();
    render(<Split onWidthChange={onWidth} />);
    const handle = screen.getByRole('separator');
    const now = () => Number(handle.getAttribute('aria-valuenow'));
    fireEvent.keyDown(handle, { key: 'ArrowRight' });
    expect(now()).toBe(376);
    fireEvent.keyDown(handle, { key: 'ArrowLeft' });
    fireEvent.keyDown(handle, { key: 'ArrowLeft' });
    expect(now()).toBe(344);
    fireEvent.keyDown(handle, { key: 'ArrowRight', shiftKey: true });
    expect(now()).toBe(408);
    fireEvent.keyDown(handle, { key: 'Home' });
    expect(now()).toBe(240);
    fireEvent.keyDown(handle, { key: 'ArrowLeft' });
    expect(now()).toBe(240);
    fireEvent.keyDown(handle, { key: 'End' });
    expect(now()).toBe(640);
    fireEvent.keyDown(handle, { key: 'Enter' });
    expect(now()).toBe(360);
    expect(onWidth).toHaveBeenLastCalledWith(360);
    expect(fireEvent.keyDown(handle, { key: 'a' })).toBe(true);
  });

  it('never lets the detail pane fall under its minimum', () => {
    setContainerWidth(800);
    render(<Split />);
    const handle = screen.getByRole('separator');
    fireEvent.keyDown(handle, { key: 'End' });
    expect(handle.getAttribute('aria-valuenow')).toBe(String(800 - 8 - 320));
    expect(handle.getAttribute('aria-valuemax')).toBe(String(800 - 8 - 320));
  });

  it('reverses the arrows in a right to left layout', () => {
    setContainerWidth(1200);
    render(
      <div dir="rtl">
        <Split />
      </div>,
    );
    const handle = screen.getByRole('separator');
    fireEvent.keyDown(handle, { key: 'ArrowLeft' });
    expect(handle.getAttribute('aria-valuenow')).toBe('376');
  });

  it('resizes by dragging and resets on a double click', () => {
    setContainerWidth(1200);
    render(<Split />);
    const handle = screen.getByRole('separator');
    fireEvent.pointerDown(handle, { clientX: 400, button: 0, pointerId: 1 });
    expect(document.querySelector('.split')?.hasAttribute('data-dragging')).toBe(true);
    fireEvent.pointerMove(handle, { clientX: 480, pointerId: 1 });
    expect(handle.getAttribute('aria-valuenow')).toBe('440');
    fireEvent.pointerMove(handle, { clientX: 2000, pointerId: 1 });
    expect(handle.getAttribute('aria-valuenow')).toBe('640');
    fireEvent.pointerUp(handle, { pointerId: 1 });
    expect(document.querySelector('.split')?.hasAttribute('data-dragging')).toBe(false);
    fireEvent.pointerMove(handle, { clientX: 100, pointerId: 1 });
    expect(handle.getAttribute('aria-valuenow')).toBe('640');
    fireEvent.doubleClick(handle);
    expect(handle.getAttribute('aria-valuenow')).toBe('360');
  });

  it('uses a controlled width and reports changes without keeping its own', () => {
    setContainerWidth(1200);
    const onWidth = vi.fn();
    const { rerender } = render(<Split width={300} onWidthChange={onWidth} />);
    const handle = screen.getByRole('separator');
    fireEvent.keyDown(handle, { key: 'ArrowRight' });
    expect(onWidth).toHaveBeenCalledWith(316);
    expect(handle.getAttribute('aria-valuenow')).toBe('300');
    rerender(<Split width={316} onWidthChange={onWidth} />);
    expect(handle.getAttribute('aria-valuenow')).toBe('316');
  });

  it('shows the empty detail until there is one', () => {
    setContainerWidth(1200);
    const { rerender } = render(<Split detail={null} />);
    expect(within(screen.getByRole('region', { name: 'Item detail' })).getByText('Nothing selected')).toBeTruthy();
    rerender(<Split detail={null} emptyDetail={<p>Choose one</p>} />);
    expect(screen.getByText('Choose one')).toBeTruthy();
  });

  it('stacks the panes under the stack width, with no handle, and side by side again when it grows', () => {
    setContainerWidth(500);
    let report: ((entries: { contentRect: { width: number } }[]) => void) | undefined;
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(cb: (entries: { contentRect: { width: number } }[]) => void) {
          report = cb;
        }
        observe(): void {}
        unobserve(): void {}
        disconnect(): void {}
      },
    );
    render(<Split />);
    const root = document.querySelector('.split') as HTMLElement;
    expect(root.hasAttribute('data-stacked')).toBe(true);
    expect(screen.queryByRole('separator')).toBeNull();
    const order = Array.from(root.children).map((c) => c.getAttribute('aria-label'));
    expect(order).toEqual(['Item list', 'Item detail']);
    act(() => report?.([{ contentRect: { width: 1000 } }]));
    expect(root.hasAttribute('data-stacked')).toBe(false);
    expect(screen.getByRole('separator')).toBeTruthy();
    act(() => report?.([{ contentRect: { width: 719 } }]));
    expect(root.hasAttribute('data-stacked')).toBe(true);
  });

  it('honours stackBelow', () => {
    setContainerWidth(900);
    render(<Split stackBelow={1000} />);
    expect(document.querySelector('.split')?.hasAttribute('data-stacked')).toBe(true);
  });

  it('ships the stacked rule in the stylesheet: one column, a capped list, tokens only', () => {
    const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');
    const rule = css.split('\n').find((l) => l.startsWith('.split[data-stacked] {')) ?? '';
    expect(rule).toContain('grid-template-columns: minmax(0, 1fr)');
    expect(css).toContain('.split[data-stacked] .split-list { max-block-size');
    const block = css.slice(css.indexOf('/* ---- Split layout'), css.indexOf('/* ---- Search input'));
    expect(block).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgba?\(/);
    expect(block).not.toContain('transition');
  });

  it('has no axe violations side by side or stacked', async () => {
    setContainerWidth(1200);
    const { container, unmount } = render(<Split />);
    await noAxe(container);
    unmount();
    setContainerWidth(400);
    const stacked = render(<Split />);
    await noAxe(stacked.container);
  });
});
