/* ListControls: the filter, sort and group bar above a list, plus the helpers that apply what it
   chooses. The page owns the state and the data. This part draws the controls and keeps every list
   page the same, and applySort, applyGrouping, paginate and usePagedState turn a flat array into the
   sorted, grouped, paged rows to render. Pagination (the footer) lives in Nav and takes the same page
   state. GroupHeader is the section header to draw above each group.

   Every control is a labelled native select or a button with a name, so it is keyboard and screen
   reader complete with no extra wiring. Direction is a button named for the current state. The bar
   wraps, and below the phone breakpoint each control takes a full row so nothing scrolls sideways. */

import { useCallback, useId, useState } from 'react';
import type { ReactNode } from 'react';
import { IconArrowUp } from '../icons/icons';
import { cx } from '../lib/env';
import { Button } from './Button';
import { Select } from './Field';
import type { SelectOption } from './Field';

export type SortDirection = 'asc' | 'desc';

export interface ListControlOption {
  id: string;
  label: string;
}

export interface ListFilter {
  id: string;
  /** Visible name of the filter, for example "Status". */
  label: string;
  /** The chosen value, "" for all. */
  value?: string | undefined;
  onChange: (value: string) => void;
  options: readonly SelectOption[];
  /** Text of the first choice, which clears the filter. Default "All <label>" in lower case, for example "All status". */
  allLabel?: string | undefined;
  /** Leave out the first choice. */
  hideAllOption?: boolean | undefined;
  /** Show the number of choices in the "All" row, for example "All statuses (4)". */
  showCount?: boolean | undefined;
}

export interface ListControlsProps {
  filters?: readonly ListFilter[] | undefined;
  sortOptions?: readonly ListControlOption[] | undefined;
  sortKey?: string | null | undefined;
  sortDir?: SortDirection | undefined;
  onSortKeyChange?: ((key: string | null) => void) | undefined;
  /** With this, the bar shows the direction button. */
  onSortDirChange?: ((dir: SortDirection) => void) | undefined;
  groupOptions?: readonly ListControlOption[] | undefined;
  groupKey?: string | null | undefined;
  onGroupKeyChange?: ((key: string | null) => void) | undefined;
  /** Pushed to the end of the bar, for example a count or an export button. */
  rightSlot?: ReactNode;
  /** Accessible name of the bar. Default "List controls". */
  label?: string | undefined;
  className?: string | undefined;
}

function Labelled({ label, children }: { label: string; children: (labelId: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="list-controls-item">
      <span id={id} className="list-controls-label">
        {label}
      </span>
      {children(id)}
    </div>
  );
}

function FilterSelect({ filter }: { filter: ListFilter }) {
  const all: SelectOption[] = filter.hideAllOption
    ? []
    : [{ value: '', label: `${filter.allLabel ?? `All ${filter.label.toLowerCase()}`}${filter.showCount ? ` (${filter.options.length})` : ''}` }];
  return (
    <Labelled label={filter.label}>
      {(labelId) => (
        <Select size="sm" labelledBy={labelId} value={filter.value ?? ''} options={[...all, ...filter.options]} onChange={(e) => filter.onChange(e.target.value)} />
      )}
    </Labelled>
  );
}

export function ListControls({
  filters,
  sortOptions,
  sortKey,
  sortDir = 'asc',
  onSortKeyChange,
  onSortDirChange,
  groupOptions,
  groupKey,
  onGroupKeyChange,
  rightSlot,
  label = 'List controls',
  className,
}: ListControlsProps) {
  const sorts = sortOptions ?? [];
  const groups = groupOptions ?? [];
  const asc = sortDir === 'asc';
  return (
    <div role="group" aria-label={label} className={cx('list-controls', className)}>
      {(filters ?? []).map((filter) => (
        <FilterSelect key={filter.id} filter={filter} />
      ))}
      {sorts.length > 0 && onSortKeyChange ? (
        <Labelled label="Sort">
          {(labelId) => (
            <>
              <Select
                size="sm"
                labelledBy={labelId}
                value={sortKey ?? ''}
                options={[{ value: '', label: 'Default order' }, ...sorts.map((o) => ({ value: o.id, label: o.label }))]}
                onChange={(e) => onSortKeyChange(e.target.value || null)}
              />
              {onSortDirChange ? (
                <Button
                  size="sm"
                  variant="secondary"
                  className="list-controls-dir"
                  data-dir={sortDir}
                  aria-label={asc ? 'Ascending, switch to descending' : 'Descending, switch to ascending'}
                  title={asc ? 'Ascending (click to flip)' : 'Descending (click to flip)'}
                  icon={<IconArrowUp size={12} />}
                  onClick={() => onSortDirChange(asc ? 'desc' : 'asc')}
                >
                  {asc ? 'Asc' : 'Desc'}
                </Button>
              ) : null}
            </>
          )}
        </Labelled>
      ) : null}
      {groups.length > 0 && onGroupKeyChange ? (
        <Labelled label="Group by">
          {(labelId) => (
            <Select
              size="sm"
              labelledBy={labelId}
              value={groupKey ?? ''}
              options={[{ value: '', label: 'None' }, ...groups.map((o) => ({ value: o.id, label: o.label }))]}
              onChange={(e) => onGroupKeyChange(e.target.value || null)}
            />
          )}
        </Labelled>
      ) : null}
      {rightSlot ? <div className="list-controls-end">{rightSlot}</div> : null}
    </div>
  );
}

export type ValueGetters<T> = Readonly<Record<string, (item: T) => unknown>>;

/**
 * A sorted copy of items. `getters[sortKey](item)` gives the value to compare. Numbers compare as
 * numbers, everything else as text with numeric and case-insensitive collation. Empty values go last
 * in either direction, and ties keep their original order, so rows never shuffle. An unknown key or
 * no key returns the items unchanged.
 */
export function applySort<T>(items: readonly T[], sortKey: string | null | undefined, sortDir: SortDirection | undefined, getters: ValueGetters<T> = {}): T[] {
  const getter = sortKey ? getters[sortKey] : undefined;
  if (!getter) return [...items];
  const dir = sortDir === 'desc' ? -1 : 1;
  const keyed = items.map((item, index) => ({ item, index, value: getter(item) }));
  keyed.sort((a, b) => {
    const aEmpty = a.value === null || a.value === undefined || a.value === '';
    const bEmpty = b.value === null || b.value === undefined || b.value === '';
    if (aEmpty && bEmpty) return a.index - b.index;
    if (aEmpty) return 1;
    if (bEmpty) return -1;
    const cmp =
      typeof a.value === 'number' && typeof b.value === 'number'
        ? a.value - b.value
        : String(a.value).localeCompare(String(b.value), undefined, { numeric: true, sensitivity: 'base' });
    return cmp === 0 ? a.index - b.index : cmp * dir;
  });
  return keyed.map((k) => k.item);
}

export interface ListGroup<T> {
  key: string;
  label: string;
  items: T[];
}

/**
 * Items split into groups by `getters[groupKey](item)`, ordered by label (numeric aware). Items with
 * no value share one last group labelled `unspecifiedLabel` (default "Unspecified"). Returns null
 * for no key or an unknown key, so the caller renders one flat list.
 */
export function applyGrouping<T>(
  items: readonly T[],
  groupKey: string | null | undefined,
  getters: ValueGetters<T> = {},
  unspecifiedLabel = 'Unspecified',
): ListGroup<T>[] | null {
  const getter = groupKey ? getters[groupKey] : undefined;
  if (!getter) return null;
  const empty = '__unspecified';
  const byKey = new Map<string, ListGroup<T>>();
  for (const item of items) {
    const raw = getter(item);
    const none = raw === null || raw === undefined || raw === '';
    const key = none ? empty : String(raw);
    let group = byKey.get(key);
    if (!group) {
      group = { key, label: none ? unspecifiedLabel : key, items: [] };
      byKey.set(key, group);
    }
    group.items.push(item);
  }
  return [...byKey.values()].sort((a, b) => {
    if (a.key === empty) return 1;
    if (b.key === empty) return -1;
    return a.label.localeCompare(b.label, undefined, { numeric: true, sensitivity: 'base' });
  });
}

/** One page of items. `page` is one based and clamped into range, `pageSize` below 1 counts as 1. */
export function paginate<T>(items: readonly T[], page: number, pageSize: number): T[] {
  const size = Math.max(1, Math.floor(pageSize));
  const last = Math.max(1, Math.ceil(items.length / size));
  const at = Math.min(Math.max(1, Math.floor(page)), last);
  return items.slice((at - 1) * size, at * size);
}

export interface PagedState {
  page: number;
  setPage: (page: number) => void;
  pageSize: number;
  /** Sets the size and goes back to page 1. */
  setPageSize: (size: number) => void;
  /** Back to page 1. Call it when a filter, sort or search changes. */
  reset: () => void;
}

/** Page and page size state for a list. Changing the size or calling reset returns to page 1. */
export function usePagedState(initialPageSize = 50): PagedState {
  const [page, setPage] = useState(1);
  const [pageSize, setSize] = useState(initialPageSize);
  const reset = useCallback(() => setPage(1), []);
  const setPageSize = useCallback((size: number) => {
    setSize(size);
    setPage(1);
  }, []);
  return { page, setPage, pageSize, setPageSize, reset };
}

export interface GroupHeaderProps {
  label: ReactNode;
  count?: ReactNode;
  className?: string | undefined;
}

/** The header above one group of rows: the label and a count. It sticks to the top of a scrolling list. */
export function GroupHeader({ label, count, className }: GroupHeaderProps) {
  return (
    <div className={cx('group-header', className)}>
      <span className="group-header-label">{label}</span>
      {count !== undefined && count !== null ? <span className="group-header-count">{count}</span> : null}
    </div>
  );
}
