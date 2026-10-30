/* MatrixGrid: a dense two-axis grid, rows by columns, for matrices where every cell is a value
   (responsibility, coverage, access, vendor by product). It is the ARIA grid pattern: one roving tab
   stop, arrow keys, Home and End along a row, Ctrl with Home or End to the corners, Enter and Space to
   activate a cell. The head row and the first column stay in view while the body scrolls both ways.
   It knows layout and keys only: what a cell shows (a letter, a chip, a picker) arrives through
   renderCell, and what a row or column means stays in the app. Unlike Table it does not sort, because
   a matrix keeps its order. Density is its own scale, down to `dense` for large matrices. */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, HTMLAttributes, KeyboardEvent, ReactNode } from 'react';
import { cx } from '../lib/env';
import { EmptyState } from './EmptyState';

export type MatrixDensity = 'comfortable' | 'compact' | 'dense';
export type MatrixTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info';

export interface MatrixColumn {
  id: string;
  /** The column head. */
  label: ReactNode;
  /** Spoken name when `label` is not plain text. */
  name?: string | undefined;
  /** CSS width of the column, for example `96px`. Default the grid's `columnWidth`. */
  width?: string | undefined;
}

export interface MatrixRow {
  id: string;
  /** The row head, shown in the sticky first column. */
  label: ReactNode;
  /** Spoken name when `label` is not plain text. */
  name?: string | undefined;
  /** Rows with the same group value sit under one group heading. Rows must already be in order: a group that
      comes back after another group gets a second heading. */
  group?: string | undefined;
}

export interface MatrixGridProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children' | 'onSelect'> {
  /** Names the grid, for example "Responsibility matrix". Also the table caption, visually hidden. */
  label: string;
  columns: readonly MatrixColumn[];
  rows: readonly MatrixRow[];
  /** What one cell shows. */
  renderCell: (row: MatrixRow, column: MatrixColumn) => ReactNode;
  /** The spoken text of a cell, read after the row and column names in place of the cell's content. Leave it out when the
      content already reads well; the row and column heads are announced either way. */
  cellLabel?: ((row: MatrixRow, column: MatrixColumn) => string | undefined) | undefined;
  /** Tints a cell by meaning. */
  cellTone?: ((row: MatrixRow, column: MatrixColumn) => MatrixTone | undefined) | undefined;
  /** Enter, Space or a click on a cell. Without it the cells are read only. */
  onCellActivate?: ((row: MatrixRow, column: MatrixColumn) => void) | undefined;
  /** Text in the top left corner, over the row heads. */
  cornerLabel?: ReactNode;
  /** 'comfortable', 'compact' (default) or 'dense'. */
  density?: MatrixDensity | undefined;
  /** CSS width of the first column. Default `14rem`. */
  rowHeaderWidth?: string | undefined;
  /** CSS width of a column with no width of its own. Default `6rem`. */
  columnWidth?: string | undefined;
  /** Max height of the scroll area (a CSS length). Without it the grid takes its height and only scrolls sideways. */
  maxHeight?: string | undefined;
  /** Shown when there are no rows or no columns, since a grid without cells has nothing to focus. */
  empty?: ReactNode;
}

export function MatrixGrid({
  label,
  columns,
  rows,
  renderCell,
  cellLabel,
  cellTone,
  onCellActivate,
  cornerLabel,
  density = 'compact',
  rowHeaderWidth = '14rem',
  columnWidth = '6rem',
  maxHeight,
  empty,
  className,
  style,
  ...rest
}: MatrixGridProps) {
  const root = useRef<HTMLDivElement>(null);
  const moveFocus = useRef(false);
  const [focus, setFocus] = useState<[number, number]>([0, 0]);
  const rowCount = rows.length;
  const colCount = columns.length;

  // Keep the tab stop on a cell that exists when rows or columns change.
  useEffect(() => {
    setFocus(([r, c]) => [Math.min(r, Math.max(rowCount - 1, 0)), Math.min(c, Math.max(colCount - 1, 0))]);
  }, [rowCount, colCount]);

  useEffect(() => {
    if (!moveFocus.current) return;
    moveFocus.current = false;
    root.current?.querySelector<HTMLElement>(`[data-r="${focus[0]}"][data-c="${focus[1]}"]`)?.focus();
  }, [focus]);

  // Group headings go before the first row of each group.
  const body = useMemo(() => {
    const out: Array<{ kind: 'group'; group: string; index: number } | { kind: 'row'; row: MatrixRow; index: number }> = [];
    let last: string | undefined;
    rows.forEach((row, index) => {
      if (row.group !== undefined && row.group !== last) out.push({ kind: 'group', group: row.group, index });
      last = row.group;
      out.push({ kind: 'row', row, index });
    });
    return out;
  }, [rows]);

  const go = (r: number, c: number) => {
    moveFocus.current = true;
    setFocus([Math.max(0, Math.min(rowCount - 1, r)), Math.max(0, Math.min(colCount - 1, c))]);
  };

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.altKey || e.shiftKey) return;
    const cell = (e.target as HTMLElement).closest<HTMLElement>('[data-r]');
    if (!cell || (e.target as HTMLElement) !== cell) return;
    const r = Number(cell.dataset['r']);
    const c = Number(cell.dataset['c']);
    const ctrl = e.ctrlKey || e.metaKey;
    switch (e.key) {
      case 'ArrowLeft': go(r, c - 1); break;
      case 'ArrowRight': go(r, c + 1); break;
      case 'ArrowUp': go(r - 1, c); break;
      case 'ArrowDown': go(r + 1, c); break;
      case 'Home': go(ctrl ? 0 : r, 0); break;
      case 'End': go(ctrl ? rowCount - 1 : r, colCount - 1); break;
      case 'Enter':
      case ' ': {
        // Space on a read only cell would otherwise scroll the page.
        if (e.key === ' ') e.preventDefault();
        const row = rows[r];
        const col = columns[c];
        if (!onCellActivate || !row || !col) return;
        e.preventDefault();
        onCellActivate(row, col);
        return;
      }
      default: return;
    }
    e.preventDefault();
  }

  const vars = { '--matrix-row-head-w': rowHeaderWidth, '--matrix-col-w': columnWidth, ...(maxHeight ? { '--matrix-max-h': maxHeight } : {}), ...style } as CSSProperties;
  const spoken = (row: MatrixRow, col: MatrixColumn): string | undefined => {
    const extra = cellLabel?.(row, col);
    if (!extra) return undefined;
    return `${row.name ?? (typeof row.label === 'string' ? row.label : '')}, ${col.name ?? (typeof col.label === 'string' ? col.label : '')}: ${extra}`;
  };

  return (
    <div
      {...rest}
      ref={root}
      className={cx('matrix-grid', className)}
      data-density={density}
      data-capped={maxHeight ? '' : undefined}
      style={vars}
      onKeyDown={onKeyDown}
    >
      {rowCount === 0 || colCount === 0 ? (
        empty ?? <EmptyState compact title="Nothing here yet" />
      ) : (
        <table className="matrix-table" role="grid" aria-label={label} aria-rowcount={rowCount + 1} aria-colcount={colCount + 1}>
          <thead>
            <tr>
              <th scope="col" className="matrix-corner">{cornerLabel}</th>
              {columns.map((col) => (
                <th key={col.id} scope="col" className="matrix-colhead" style={col.width ? { minWidth: col.width, width: col.width } : undefined} aria-label={col.name}>
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((item) =>
              item.kind === 'group' ? (
                <tr key={`g:${item.index}`} className="matrix-group">
                  <th scope="rowgroup" colSpan={colCount + 1}>{item.group}</th>
                </tr>
              ) : (
                <tr key={item.row.id}>
                  <th scope="row" className="matrix-rowhead" aria-label={item.row.name}>{item.row.label}</th>
                  {columns.map((col, c) => {
                    const tone = cellTone?.(item.row, col);
                    return (
                      <td
                        key={col.id}
                        role="gridcell"
                        className="matrix-cell"
                        tabIndex={focus[0] === item.index && focus[1] === c ? 0 : -1}
                        data-r={item.index}
                        data-c={c}
                        data-tone={tone}
                        data-active={onCellActivate ? '' : undefined}
                        aria-label={spoken(item.row, col)}
                        onClick={(ev) => {
                          if ((ev.target as HTMLElement).closest('button, a, input, select, textarea')) return;
                          setFocus([item.index, c]);
                          onCellActivate?.(item.row, col);
                        }}
                      >
                        {renderCell(item.row, col)}
                      </td>
                    );
                  })}
                </tr>
              ),
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
