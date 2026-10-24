/* List table: the list shaped sibling of Table, for a master pane next to a detail pane. Where Table
   is a grid of sortable columns, a list row is one item with a primary line, an optional secondary
   line, a leading and a trailing slot, so it keeps its meaning at the width of a narrow pane. It is
   a separate part because a column grid cannot hold group headers or an open row without giving up
   the table semantics that make it a table: rows here are list items, groups are nested lists
   named by their header, and the order is the caller's (sort and filter before passing rows).
   Three states stay apart. The OPEN row (selectedKey) is the one the detail pane shows and carries
   aria-current. The CHECKED rows (selection, from useRowSelection) are the ones a bulk action
   acts on, and a checkbox never opens its row. The FOCUSED row is the one arrow keys moved to.
   Pair it with Pagination (usePagination) for a client paged list. */

import { useId, useMemo, useRef, useState } from 'react';
import type { HTMLAttributes, KeyboardEvent, ReactNode } from 'react';
import { cx } from '../lib/env';
import { Checkbox } from './Choice';
import { EmptyState } from './EmptyState';
import { isFromInteractiveDescendant } from './Table';
import type { TableSelection } from './Table';

/** Extra attributes for one row. data-* keys are allowed. */
export type ListRowProps = Omit<HTMLAttributes<HTMLLIElement>, 'children'> & {
  [key: `data-${string}`]: string | number | boolean | undefined;
};

export interface ListTableProps<T> {
  rows: readonly T[];
  rowKey: (row: T) => string;
  /** Accessible name of the list. */
  caption: string;
  /** The main line of a row. */
  primary: (row: T) => ReactNode;
  /** A quieter second line under the primary one. */
  secondary?: ((row: T) => ReactNode) | undefined;
  /** Before the text, for example an avatar or a status dot. */
  leading?: ((row: T) => ReactNode) | undefined;
  /** After the text, for example a badge or a time. Controls in it keep their own clicks and keys. */
  trailing?: ((row: T) => ReactNode) | undefined;
  /** The group a row belongs to. Groups appear in order of first use, each under a header. A
      null or empty key leaves the row outside any group. */
  groupBy?: ((row: T) => string | null | undefined) | undefined;
  /** The group header content. Default: the key. */
  groupLabel?: ((key: string, rows: readonly T[]) => ReactNode) | undefined;
  /** The key of the OPEN row, the one a detail pane shows. */
  selectedKey?: string | null | undefined;
  /** Makes rows focusable with the arrow keys. Enter, Space or a click opens the row. Controls inside
      a row (the checkbox, buttons, links) never open it. */
  onRowActivate?: ((row: T) => void) | undefined;
  /** Adds a checkbox to every row and a header with a select-all box over the rows on screen. */
  selection?: TableSelection | undefined;
  /** Accessible name of a row checkbox. Default "Select " and the row key. */
  selectionLabel?: ((row: T) => string) | undefined;
  /** Accessible name of the select-all checkbox. Default "Select all visible rows". */
  selectAllLabel?: string | undefined;
  /** Text shown beside the select-all box. */
  header?: ReactNode;
  /** False keeps a row out of the selection (its checkbox is disabled, select-all skips it). */
  isRowSelectable?: ((row: T) => boolean) | undefined;
  rowClassName?: ((row: T) => string | undefined) | undefined;
  rowProps?: ((row: T) => ListRowProps | undefined) | undefined;
  /** Shown when there are no rows. */
  empty?: ReactNode;
  /** Max height of the scroll area. */
  maxHeight?: string | undefined;
  className?: string | undefined;
}

interface Segment<T> {
  key: string | null;
  rows: T[];
}

/** Groups in order of first appearance. Rows with no group key share one unlabeled segment at the
    position of the first of them. Exported for hosts that count or label groups themselves. */
export function groupRows<T>(rows: readonly T[], groupBy?: (row: T) => string | null | undefined): Segment<T>[] {
  if (!groupBy) return [{ key: null, rows: [...rows] }];
  const segments: Segment<T>[] = [];
  const byKey = new Map<string | null, Segment<T>>();
  for (const row of rows) {
    const raw = groupBy(row);
    const key = raw === undefined || raw === null || raw === '' ? null : raw;
    let seg = byKey.get(key);
    if (!seg) {
      seg = { key, rows: [] };
      byKey.set(key, seg);
      segments.push(seg);
    }
    seg.rows.push(row);
  }
  return segments;
}

export function ListTable<T>({
  rows,
  rowKey,
  caption,
  primary,
  secondary,
  leading,
  trailing,
  groupBy,
  groupLabel,
  selectedKey,
  onRowActivate,
  selection,
  selectionLabel,
  selectAllLabel = 'Select all visible rows',
  header,
  isRowSelectable,
  rowClassName,
  rowProps,
  empty,
  maxHeight,
  className,
}: ListTableProps<T>) {
  const base = useId();
  const root = useRef<HTMLDivElement | null>(null);
  const [focusIndex, setFocusIndex] = useState(0);
  const segments = useMemo(() => groupRows(rows, groupBy), [rows, groupBy]);
  const ordered = useMemo(() => segments.flatMap((s) => s.rows), [segments]);
  const indexOf = useMemo(() => new Map(ordered.map((row, i) => [rowKey(row), i])), [ordered, rowKey]);

  const selectableIds = useMemo(
    () => (selection ? ordered.filter((row) => isRowSelectable?.(row) ?? true).map(rowKey) : []),
    [selection, ordered, isRowSelectable, rowKey],
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

  const focusable = Boolean(onRowActivate);
  const tabStop = Math.min(focusIndex, ordered.length - 1);

  const onRowKeyDown = (event: KeyboardEvent<HTMLLIElement>, index: number, row: T) => {
    let next = index;
    if (event.key === 'ArrowDown') next = Math.min(ordered.length - 1, index + 1);
    else if (event.key === 'ArrowUp') next = Math.max(0, index - 1);
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = ordered.length - 1;
    else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onRowActivate?.(row);
      return;
    } else return;
    event.preventDefault();
    setFocusIndex(next);
    root.current?.querySelectorAll<HTMLElement>('[data-list-row]')[next]?.focus();
  };

  const renderRow = (row: T) => {
    const key = rowKey(row);
    const index = indexOf.get(key) ?? 0;
    const extra = rowProps?.(row) ?? {};
    const { className: extraClass, onClick, onKeyDown, onFocus, ...attrs } = extra;
    const picked = selection?.selected.has(key) ?? false;
    const open = selectedKey !== undefined && selectedKey !== null && selectedKey === key;
    const second = secondary?.(row);
    const lead = leading?.(row);
    const trail = trailing?.(row);
    return (
      <li
        {...attrs}
        key={key}
        data-list-row=""
        aria-current={open ? 'true' : undefined}
        className={cx('list-row', picked && 'is-checked', open && 'is-open', focusable && 'is-focusable', rowClassName?.(row), extraClass)}
        tabIndex={focusable ? (index === tabStop ? 0 : -1) : attrs.tabIndex}
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
          <span className="list-row-check">
            <Checkbox
              label={selectionLabel?.(row) ?? `Select ${key}`}
              hideLabel
              size="sm"
              checked={picked}
              disabled={isRowSelectable ? !isRowSelectable(row) : undefined}
              onCheckedChange={(on) => setRow(key, on)}
            />
          </span>
        ) : null}
        {lead ? <span className="list-row-lead">{lead}</span> : null}
        <span className="list-row-main">
          <span className="list-row-primary">{primary(row)}</span>
          {second ? <span className="list-row-secondary">{second}</span> : null}
        </span>
        {trail ? <span className="list-row-trail">{trail}</span> : null}
      </li>
    );
  };

  return (
    <div className={cx('list-table', className)} ref={root} style={maxHeight ? { maxHeight } : undefined}>
      {selection ? (
        <div className="list-table-head">
          <Checkbox
            label={selectAllLabel}
            hideLabel
            size="sm"
            checked={allSelected}
            indeterminate={selectedVisible > 0 && !allSelected}
            disabled={selectableIds.length === 0}
            onCheckedChange={setAll}
          />
          {header ? <span className="list-table-head-text">{header}</span> : null}
        </div>
      ) : null}
      {ordered.length === 0 ? (
        <div className="list-table-empty">{empty ?? <EmptyState compact title="Nothing here yet" />}</div>
      ) : (
        <ul className="list-table-list" aria-label={caption}>
          {segments.map((seg, i) => {
            if (seg.key === null) return seg.rows.map(renderRow);
            const headId = `${base}-g${i}`;
            return (
              <li key={`group:${seg.key}`} className="list-table-group">
                <div className="list-table-group-head" id={headId}>
                  {groupLabel ? groupLabel(seg.key, seg.rows) : seg.key}
                </div>
                <ul className="list-table-group-rows" aria-labelledby={headId}>
                  {seg.rows.map(renderRow)}
                </ul>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
