/* List chrome around a data surface (UI standard section 7). SelectionBar is the sticky "N selected"
   bar with the bulk actions, shown only while something is selected. Given a bulk run (useBulkRun)
   it also shows the progress, a Cancel button and the per-item errors. ListFooter is the
   "Showing N of M" line with the freshness of the data and an optional pager slot. */

import type { ReactNode } from 'react';
import { IconClose } from '../icons/icons';
import type { BulkRunState } from '../lib/bulkRun';
import { cx } from '../lib/env';
import { Button } from './Button';
import { ProgressBar } from './ProgressBar';
import { RelativeTime } from './Text';

export interface BulkAction {
  label: string;
  onClick: () => void;
  /** A destructive action: the danger button variant. */
  danger?: boolean | undefined;
  disabled?: boolean | undefined;
  /** The action is in flight: spinner and disabled. */
  loading?: boolean | undefined;
}

/** What the bar shows of a bulk run: the useBulkRun state satisfies it as is. */
export type SelectionBarRun = Pick<BulkRunState, 'status' | 'total' | 'done' | 'errors'>;

export interface SelectionBarProps {
  /** Selected row count. The bar renders nothing at zero. */
  count: number;
  onClear: () => void;
  actions: readonly BulkAction[];
  /** The count line. Default "N selected". */
  label?: ((count: number) => ReactNode) | undefined;
  /** The bulk run in progress or just finished. Idle or omitted shows nothing extra. */
  run?: SelectionBarRun | undefined;
  /** Shown as Cancel while the run is running. */
  onCancel?: (() => void) | undefined;
  /** Names the items in the progress and error lines. Default "items". */
  itemNoun?: string | undefined;
  /** The landmark name. Default "Selection". Give each bar a different one when several share a page. */
  name?: string | undefined;
  className?: string | undefined;
}

/** Sticky "N selected" bar with the bulk actions. Renders nothing at zero. */
export function SelectionBar({ count, onClear, actions, label, run, onCancel, itemNoun = 'items', name = 'Selection', className }: SelectionBarProps) {
  if (count <= 0) return null;
  const running = run?.status === 'running';
  return (
    <section className={cx('selection-bar', className)} aria-label={name}>
      <span className="selection-bar-count" aria-live="polite">
        {label ? label(count) : `${count} selected`}
      </span>
      <div className="selection-bar-actions">
        {actions.map((act) => (
          <Button
            key={act.label}
            size="sm"
            variant={act.danger ? 'danger' : 'secondary'}
            onClick={act.onClick}
            disabled={act.disabled}
            loading={act.loading}
          >
            {act.label}
          </Button>
        ))}
      </div>
      <button type="button" className="selection-bar-clear" onClick={onClear} disabled={running} aria-label="Clear selection">
        <IconClose size={12} />
        <span aria-hidden="true">Clear</span>
      </button>
      {run && run.status !== 'idle' ? <SelectionBarRunView run={run} running={running} onCancel={onCancel} itemNoun={itemNoun} /> : null}
    </section>
  );
}

function runSummary(run: SelectionBarRun, itemNoun: string): string {
  const failed = run.errors.length;
  const base = `${run.done} of ${run.total} ${itemNoun}`;
  if (run.status === 'running') return `${base} processed`;
  const tail = failed > 0 ? `, ${failed} failed` : '';
  return run.status === 'cancelled' ? `Cancelled after ${base}${tail}` : `Finished ${base}${tail}`;
}

interface SelectionBarRunViewProps {
  run: SelectionBarRun;
  running: boolean;
  onCancel: (() => void) | undefined;
  itemNoun: string;
}

/** The progress line, the Cancel button and the per-item error list under the bar's row. */
function SelectionBarRunView({ run, running, onCancel, itemNoun }: SelectionBarRunViewProps) {
  const summary = runSummary(run, itemNoun);
  return (
    <div className="selection-bar-run">
      <div className="selection-bar-progress">
        <ProgressBar value={run.done} max={Math.max(run.total, 1)} label={`Progress, ${summary}`} tone={run.errors.length > 0 && !running ? 'warning' : 'accent'} />
        <span className="selection-bar-progress-text" role="status">
          {summary}
        </span>
        {running && onCancel ? (
          <Button size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        ) : null}
      </div>
      {run.errors.length > 0 ? (
        <ul className="selection-bar-errors" aria-label={`Failed ${itemNoun}`}>
          {run.errors.map((err) => (
            <li key={`${err.index}-${err.key}`} className="selection-bar-error">
              <span className="selection-bar-error-key">{err.key}</span>
              <span>{err.message}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export interface ListFooterProps {
  /** Rows on screen. */
  shown: number;
  /** Rows in the whole result. */
  total: number;
  /** When the data last arrived. Omitted or null hides the freshness line. */
  updatedAt?: Date | string | number | null | undefined;
  /** Pagination or any trailing control. */
  children?: ReactNode;
  className?: string | undefined;
}

/** "Showing N of M", the freshness of the data, and an optional pager slot. */
export function ListFooter({ shown, total, updatedAt, children, className }: ListFooterProps) {
  return (
    <div className={cx('list-footer', className)}>
      <span>
        Showing <span className="list-footer-strong">{shown}</span> of {total}
      </span>
      {updatedAt != null ? (
        <span>
          Updated <RelativeTime value={updatedAt} className="list-footer-soft" />
        </span>
      ) : null}
      {children ? <div className="list-footer-pager">{children}</div> : null}
    </div>
  );
}
