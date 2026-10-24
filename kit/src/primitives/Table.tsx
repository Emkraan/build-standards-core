/* Data table: every column sortable by default (first column ascending, natural order, empty last),
   filtered before it is sorted, with a sticky head, keyboard row focus and an empty state
   (UI standard sections 7 and 12). Order-carrying tables pass sortable={false}. Sort is uncontrolled
   by default. Pass `sort` and `onSortChange` to own it (for example to persist it in the URL).
   Pass `selection` (from useRowSelection) for a checkbox column: select-all acts on the rows on
   screen after the filter, and rows that drop out of view stay selected until cleared. */

import { useCallback, useMemo, useState } from 'react';
import type { HTMLAttributes, KeyboardEvent, ReactNode } from 'react';
import { IconChevronDown } from '../icons/icons';
import { cx } from '../lib/env';
import { Checkbox } from './Choice';
import { EmptyState } from './EmptyState';

export type SortDir = 'asc' | 'desc';
export type SortValue = string | number | boolean | Date | null | undefined;

export interface SortState {
  key: string;
  dir: SortDir;
}

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

function isEmpty(v: SortValue): boolean {
  return v === null || v === undefined || (typeof v === 'string' && v.trim() === '');
}

/** Natural, case-insensitive comparison. Numbers and dates compare by value. */
export function compareValues(a: SortValue, b: SortValue): number {
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  if (a instanceof Date && b instanceof Date) return a.getTime() - b.getTime();
  return collator.compare(String(a), String(b));
}

/** Sorts rows by a value getter. Empty values always sort last, in both directions. */
export function sortRows<T>(rows: readonly T[], get: (row: T) => SortValue, dir: SortDir): T[] {
  const sign = dir === 'asc' ? 1 : -1;
  return rows
    .map((row, index) => ({ row, index, v: get(row) }))
    .sort((x, y) => {
      const ex = isEmpty(x.v);
      const ey = isEmpty(y.v);
      if (ex || ey) return ex === ey ? x.index - y.index : ex ? 1 : -1;
      return sign * compareValues(x.v, y.v) || x.index - y.index;
    })
    .map((x) => x.row);
}

/** The next sort after a header click: the active column flips, another column sorts ascending. */
export function nextSort(prev: SortState | null, key: string): SortState {
  return prev && prev.key === key ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' };
}

/** Holds { key, dir }. Clicking the active column flips it, and another column sorts ascending. */
export function useTableSort(initial: SortState | null) {
  const [sort, setSort] = useState<SortState | null>(initial);
  const toggle = useCallback((key: string) => {
    setSort((prev) => nextSort(prev, key));
  }, []);
  return { sort, setSort, toggle };
}

/** Controls inside a row that keep their own clicks and keys: the row does not activate from them. */
export const ROW_INTERACTIVE_SELECTOR = [
  'button', 'a[href]', 'input', 'select', 'textarea', 'label', 'summary', '[role="button"]', '[role="link"]',
  '[role="menuitem"]', '[role="checkbox"]', '[role="switch"]', '[role="option"]', '[contenteditable]:not([contenteditable="false"])',
  '[data-no-row-activate]',
].join(',');

/** True when an event on a row started on an interactive element inside it (not the row itself). */
export function isFromInteractiveDescendant(target: EventTarget | null, row: Element): boolean {
  if (!(target instanceof Element) || target === row) return false;
  const hit = target.closest(ROW_INTERACTIVE_SELECTOR);
  return hit !== null && hit !== row && row.contains(hit);
}

/** Extra attributes for one body row. data-* keys are allowed. */
export type TableRowProps = Omit<HTMLAttributes<HTMLTableRowElement>, 'children'> & {
  [key: `data-${string}`]: string | number | boolean | undefined;
};

/** The selected row ids and a setter. useRowSelection returns one; a plain state pair works too. */
export interface TableSelection {
  selected: ReadonlySet<string>;
  onSelectedChange: (next: ReadonlySet<string>) => void;
}

export interface RowSelection extends TableSelection {
  count: number;
  isSelected: (id: string) => boolean;
  toggle: (id: string, on?: boolean) => void;
  /** Select every visible id, or clear them all when `on` is false. */
  toggleAll: (on: boolean) => void;
  clear: () => void;
  /** Every visible id is selected (and there is at least one). */
  allSelected: boolean;
  /** At least one, but not every, visible id is selected. */
  someSelected: boolean;
  /** The selected ids, visible order first, as an array for a bulk call. */
  ids: string[];
}

const NO_IDS: readonly string[] = [];

/** Selection state keyed by row id, for a Table `selection` prop or a card grid. `visibleIds` is the
    page on screen: toggleAll acts on it. Ids that drop out of it (a filter change, a page turn) stay
    selected until cleared, so a bulk action never silently loses rows the operator picked. A Table
    computes its own select-all from the rows it shows, so it needs no visibleIds. */
export function useRowSelection(visibleIds: readonly string[] = NO_IDS): RowSelection {
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set());

  const toggle = useCallback((id: string, on?: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on ?? !prev.has(id)) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  const toggleAll = useCallback(
    (on: boolean) => {
      setSelected((prev) => {
        const next = new Set(prev);
        for (const id of visibleIds) {
          if (on) next.add(id);
          else next.delete(id);
        }
        return next;
      });
    },
    [visibleIds],
  );

  const clear = useCallback(() => setSelected(new Set()), []);
  const onSelectedChange = useCallback((next: ReadonlySet<string>) => setSelected(new Set(next)), []);

  return useMemo(() => {
    const visibleSelected = visibleIds.filter((id) => selected.has(id));
    const allSelected = visibleIds.length > 0 && visibleSelected.length === visibleIds.length;
    const visibleSet = new Set(visibleIds);
    return {
      selected,
      onSelectedChange,
      count: selected.size,
      isSelected: (id: string) => selected.has(id),
      toggle,
      toggleAll,
      clear,
      allSelected,
      someSelected: visibleSelected.length > 0 && !allSelected,
      ids: [...visibleSelected, ...Array.from(selected).filter((id) => !visibleSet.has(id))],
    };
  }, [selected, visibleIds, toggle, toggleAll, clear, onSelectedChange]);
}

export interface TableColumn<T> {
  key: string;
  header: string;
  /** Value used to sort and filter. Default: row[key]. */
  value?: ((row: T) => SortValue) | undefined;
  /** Cell content. Default: the value as text. */
  render?: ((row: T) => ReactNode) | undefined;
  /** Default true. Action and icon columns set false. */
  sortable?: boolean | undefined;
  /** Right-aligned tabular numbers. */
  numeric?: boolean | undefined;
  /** Visually hide the header text (it stays for screen readers). */
  hideHeader?: boolean | undefined;
  width?: string | undefined;
}

export interface TableProps<T> {
  columns: readonly TableColumn<T>[];
  rows: readonly T[];
  rowKey: (row: T) => string;
  /** Accessible name of the table. */
  caption: string;
  /** Show the caption visibly. Default false (visually hidden). */
  showCaption?: boolean | undefined;
  /** Row height. `compact` tightens the cell padding for long, scan-heavy lists; a touch screen
      (coarse pointer) always keeps `comfortable` so rows stay easy to hit. Default comfortable. */
  density?: 'comfortable' | 'compact' | undefined;
  /** Text filter, applied before sorting. */
  filter?: string | undefined;
  /** Initial sort. Default: the first sortable column ascending. Null starts unsorted. */
  defaultSort?: SortState | null | undefined;
  /** Controlled sort. When set (null included) the table shows it and reports clicks through
      onSortChange instead of keeping its own state. */
  sort?: SortState | null | undefined;
  /** Called with the next sort on every header click, controlled or not. */
  onSortChange?: ((sort: SortState) => void) | undefined;
  /** Extra class for a body row, for state tints (critical, needs attention). */
  rowClassName?: ((row: T) => string | undefined) | undefined;
  /** Extra attributes for a body row (data-*, title, style, handlers). The kit's own keyboard and
      click handling still runs after yours. */
  rowProps?: ((row: T) => TableRowProps | undefined) | undefined;
  /** False for tables whose order carries meaning (rotations, sequences, logs). */
  sortable?: boolean | undefined;
  /** Shown when there are no rows at all. */
  empty?: ReactNode;
  /** Shown when the filter matches nothing. */
  noMatch?: ReactNode;
  /** Makes rows focusable with the arrow keys. Enter or a click activates. Clicks and keys on
      controls inside a cell (buttons, links, fields, [data-no-row-activate]) never activate the
      row, and neither does an event a handler already called preventDefault on. */
  onRowActivate?: ((row: T) => void) | undefined;
  isRowSelected?: ((row: T) => boolean) | undefined;
  /** Adds a checkbox column. Selected rows also get the selected tint. */
  selection?: TableSelection | undefined;
  /** Accessible name of a row checkbox. Default "Select " plus the first column's value. */
  selectionLabel?: ((row: T) => string) | undefined;
  /** Accessible name of the select-all checkbox. Default "Select all visible rows". */
  selectAllLabel?: string | undefined;
  /** False keeps a row out of the selection (its checkbox is disabled, select-all skips it). */
  isRowSelectable?: ((row: T) => boolean) | undefined;
  /** Max height of the scroll area, for a sticky head inside a card. */
  maxHeight?: string | undefined;
  /** Phone layout (640px and below). `scroll` keeps the table and scrolls it sideways; `cards` turns
      each row into a stacked card of label and value pairs, the label being the column header.
      Default `scroll`. */
  mobile?: 'scroll' | 'cards' | undefined;
  /** False keeps the head in place instead of sticking to the top of the scroll area, for a short
      table inside a card. Default true. */
  stickyHead?: boolean | undefined;
  /** Class on the scroll wrapper, applied with `className` (both land on the wrapper element). */
  wrapClassName?: string | undefined;
  className?: string | undefined;
}

function defaultValue<T>(row: T, key: string): SortValue {
  const v = (row as Record<string, unknown>)[key];
  if (v === null || v === undefined || typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean' || v instanceof Date) return v;
  return String(v);
}

export function Table<T>({
  columns,
  rows,
  rowKey,
  caption,
  showCaption = false,
  density = 'comfortable',
  filter = '',
  defaultSort,
  sort: sortProp,
  onSortChange,
  rowClassName,
  rowProps,
  sortable = true,
  empty,
  noMatch,
  onRowActivate,
  isRowSelected,
  selection,
  selectionLabel,
  selectAllLabel = 'Select all visible rows',
  isRowSelectable,
  maxHeight,
  mobile = 'scroll',
  stickyHead = true,
  wrapClassName,
  className,
}: TableProps<T>) {
  const firstSortable = columns.find((c) => c.sortable !== false);
  const initial = defaultSort === undefined ? (firstSortable ? { key: firstSortable.key, dir: 'asc' as const } : null) : defaultSort;
  const own = useTableSort(sortable ? initial : null);
  const controlled = sortProp !== undefined;
  const sort = !sortable ? null : controlled ? sortProp : own.sort;
  const toggle = (key: string) => {
    const next = nextSort(sort, key);
    if (!controlled) own.setSort(next);
    onSortChange?.(next);
  };
  const [focusIndex, setFocusIndex] = useState(0);

  const valueOf = useCallback(
    (row: T, key: string): SortValue => {
      const col = columns.find((c) => c.key === key);
      return col?.value ? col.value(row) : defaultValue(row, key);
    },
    [columns],
  );

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const filtered = q
      ? rows.filter((row) => columns.some((c) => String(valueOf(row, c.key) ?? '').toLowerCase().includes(q)))
      : [...rows];
    if (!sort) return filtered;
    return sortRows(filtered, (row) => valueOf(row, sort.key), sort.dir);
  }, [rows, columns, filter, sort, valueOf]);

  const selectableIds = useMemo(
    () => (selection ? visible.filter((row) => isRowSelectable?.(row) ?? true).map(rowKey) : []),
    [selection, visible, isRowSelectable, rowKey],
  );
  const selectedVisible = selection ? selectableIds.filter((id) => selection.selected.has(id)).length : 0;
  const allSelected = selectableIds.length > 0 && selectedVisible === selectableIds.length;
  const setRow = (id: string, on: boolean) => {
    if (!selection) return;
    const next = new Set(selection.selected);
    if (on) next.add(id);
    else next.delete(id);
    selection.onSelectedChange(next);
  };
  const setAll = (on: boolean) => {
    if (!selection) return;
    const next = new Set(selection.selected);
    for (const id of selectableIds) {
      if (on) next.add(id);
      else next.delete(id);
    }
    selection.onSelectedChange(next);
  };
  const firstKey = columns[0]?.key;
  const rowLabel = (row: T) =>
    selectionLabel?.(row) ?? `Select ${firstKey ? String(valueOf(row, firstKey) ?? rowKey(row)) : rowKey(row)}`;

  const focusable = Boolean(onRowActivate);
  const onRowKeyDown = (event: KeyboardEvent<HTMLTableRowElement>, index: number, row: T) => {
    let next = index;
    if (event.key === 'ArrowDown') next = Math.min(visible.length - 1, index + 1);
    else if (event.key === 'ArrowUp') next = Math.max(0, index - 1);
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = visible.length - 1;
    else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onRowActivate?.(row);
      return;
    } else return;
    event.preventDefault();
    setFocusIndex(next);
    const body = event.currentTarget.parentElement;
    (body?.children[next] as HTMLElement | undefined)?.focus();
  };

  return (
    <div
      className={cx('table-wrap', wrapClassName, className)}
      data-density={density === 'compact' ? 'compact' : undefined}
      data-mobile={mobile === 'cards' ? 'cards' : undefined}
      data-sticky-head={stickyHead ? undefined : 'false'}
      style={maxHeight ? { maxHeight } : undefined}
    >
      <table className="table">
        <caption className={showCaption ? 'table-caption' : 'kit-sr-only'}>{caption}</caption>
        <thead>
          <tr>
            {selection ? (
              <th scope="col" className="table-select">
                <Checkbox
                  label={selectAllLabel}
                  hideLabel
                  size="sm"
                  checked={allSelected}
                  indeterminate={selectedVisible > 0 && !allSelected}
                  disabled={selectableIds.length === 0}
                  onCheckedChange={setAll}
                />
              </th>
            ) : null}
            {columns.map((col) => {
              const canSort = sortable && col.sortable !== false;
              const active = canSort && sort?.key === col.key;
              const ariaSort = !canSort ? undefined : active ? (sort?.dir === 'asc' ? 'ascending' : 'descending') : 'none';
              return (
                <th
                  key={col.key}
                  scope="col"
                  aria-sort={ariaSort}
                  className={cx(col.numeric && 'cell-num', canSort && 'sortable')}
                  style={col.width ? { width: col.width } : undefined}
                >
                  {canSort ? (
                    <button type="button" className="th-btn" onClick={() => toggle(col.key)}>
                      <span className={col.hideHeader ? 'kit-sr-only' : undefined}>{col.header}</span>
                      <span className="th-arr" data-dir={active ? sort?.dir : undefined} aria-hidden="true">
                        <IconChevronDown size={12} />
                      </span>
                    </button>
                  ) : (
                    <span className={col.hideHeader ? 'kit-sr-only' : undefined}>{col.header}</span>
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {visible.length === 0 ? (
            <tr className="table-empty-row">
              <td colSpan={columns.length + (selection ? 1 : 0)}>
                {rows.length === 0
                  ? empty ?? <EmptyState compact title="Nothing here yet" />
                  : noMatch ?? <EmptyState compact title="No matching rows" body="Try a shorter or different filter." />}
              </td>
            </tr>
          ) : (
            visible.map((row, index) => {
              const extra = rowProps?.(row) ?? {};
              const { className: extraClass, onClick, onKeyDown, onFocus, ...attrs } = extra;
              const key = rowKey(row);
              const picked = selection?.selected.has(key) ?? false;
              return (
                <tr
                  {...attrs}
                  key={key}
                  className={cx('table-row', (picked || isRowSelected?.(row)) && 'is-selected', focusable && 'is-focusable', rowClassName?.(row), extraClass)}
                  tabIndex={focusable ? (index === Math.min(focusIndex, visible.length - 1) ? 0 : -1) : attrs.tabIndex}
                  onClick={
                    focusable || onClick
                      ? (event) => {
                          onClick?.(event);
                          if (!focusable || event.defaultPrevented) return;
                          if (isFromInteractiveDescendant(event.target, event.currentTarget)) return;
                          onRowActivate?.(row);
                        }
                      : undefined
                  }
                  onKeyDown={
                    focusable || onKeyDown
                      ? (event) => {
                          onKeyDown?.(event);
                          if (!focusable || event.defaultPrevented) return;
                          // Keys typed into a control inside a cell belong to that control.
                          if (isFromInteractiveDescendant(event.target, event.currentTarget)) return;
                          onRowKeyDown(event, index, row);
                        }
                      : undefined
                  }
                  onFocus={
                    focusable || onFocus
                      ? (event) => {
                          onFocus?.(event);
                          if (focusable) setFocusIndex(index);
                        }
                      : undefined
                  }
                >
                  {selection ? (
                    <td className="table-select">
                      <Checkbox
                        label={rowLabel(row)}
                        hideLabel
                        size="sm"
                        checked={picked}
                        disabled={isRowSelectable ? !isRowSelectable(row) : undefined}
                        onCheckedChange={(on) => setRow(key, on)}
                      />
                    </td>
                  ) : null}
                  {columns.map((col) => (
                    <td key={col.key} className={col.numeric ? 'cell-num' : undefined} data-label={mobile === 'cards' && !col.hideHeader ? col.header : undefined}>
                      {col.render ? col.render(row) : String(valueOf(row, col.key) ?? '')}
                    </td>
                  ))}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
