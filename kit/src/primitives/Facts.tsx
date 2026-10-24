/* Facts: label and value rows for a detail panel, and Disclosure for secondary detail behind a real
   control. A FactList is a description list, so a screen reader hears each label with its value. An
   empty value shows a quiet dash that is announced as "None". On a narrow container the value wraps
   under its label instead of being cut off. Colours and type come from tokens (UI standard 0.1). */

import type { CSSProperties, ReactNode } from 'react';
import { createContext, useContext, useId, useState } from 'react';
import { IconChevronRight } from '../icons/icons';
import { cx } from '../lib/env';

/** Ink of a value: the neutral text ranks, then the status inks the kit text parts share. */
export type FactTone = 'primary' | 'secondary' | 'tertiary' | 'success' | 'warning' | 'urgent' | 'danger' | 'info';

export interface FactRowProps {
  label: ReactNode;
  /** The value. Children win over `value` when both are given. */
  value?: ReactNode;
  children?: ReactNode;
  /** Monospace value, for ids, paths and hashes. */
  mono?: boolean | undefined;
  /** Ink of the value. Default secondary. */
  tone?: FactTone | undefined;
  /** Longer explanation, shown as the native tooltip of the row. */
  hint?: string | undefined;
  /** Fixed label column width (a number is pixels), to line several lists up. */
  labelWidth?: number | string | undefined;
  className?: string | undefined;
  /** Layout hook: merged over the row's own custom properties (`--fact-label-width`), so a caller can set spacing or width. */
  style?: CSSProperties | undefined;
}

// Inside a FactList the row is a div in the list's dl. On its own it carries its own dl.
const InList = createContext(false);

export function FactRow({ label, value, children, mono = false, tone = 'secondary', hint, labelWidth, className, style: styleProp }: FactRowProps) {
  const content = children !== undefined ? children : value;
  const empty = content === null || content === undefined || content === false || content === '';
  const own = labelWidth !== undefined ? ({ '--fact-label-width': typeof labelWidth === 'number' ? `${labelWidth}px` : labelWidth } as CSSProperties) : undefined;
  const style = own || styleProp ? { ...own, ...styleProp } : undefined;
  const inList = useContext(InList);
  const row = (
    <div className={cx('fact-row', className)} title={hint} style={style} data-fixed={labelWidth !== undefined ? '' : undefined}>
      <dt className="fact-label">{label}</dt>
      <dd className="fact-value" data-tone={tone} data-mono={mono ? '' : undefined} data-empty={empty ? '' : undefined}>
        {empty ? (
          <>
            <span aria-hidden="true">-</span>
            <span className="kit-sr-only">None</span>
          </>
        ) : (
          content
        )}
      </dd>
    </div>
  );
  return inList ? row : <dl className="fact-list">{row}</dl>;
}

export interface FactListProps {
  children?: ReactNode;
  /** Accessible name of the list. */
  label?: string | undefined;
  /** Space between rows in pixels. Default 7. */
  gap?: number | undefined;
  className?: string | undefined;
  /** Layout hook: merged over the list's own custom properties (`--fact-gap`). */
  style?: CSSProperties | undefined;
}

/** A column of FactRows on one vertical rhythm. */
export function FactList({ children, label, gap, className, style: styleProp }: FactListProps) {
  const own = gap !== undefined ? ({ '--fact-gap': `${gap}px` } as CSSProperties) : undefined;
  const style = own || styleProp ? { ...own, ...styleProp } : undefined;
  return (
    <InList.Provider value={true}>
      <dl className={cx('fact-list', className)} style={style} aria-label={label}>
        {children}
      </dl>
    </InList.Provider>
  );
}

export interface DisclosureProps {
  label: ReactNode;
  /** A count shown after the label, such as the number of hidden rows. */
  count?: ReactNode;
  children?: ReactNode;
  /** Start open (uncontrolled). */
  defaultOpen?: boolean | undefined;
  /** Controlled open state. Pair with `onOpenChange`. */
  open?: boolean | undefined;
  onOpenChange?: ((open: boolean) => void) | undefined;
  dense?: boolean | undefined;
  /** Mount the children only while open: they mount on open and unmount on close, so a heavy or fetching panel costs nothing until asked for. The panel element stays, hidden and empty, so `aria-controls` always resolves. Default off. */
  lazy?: boolean | undefined;
  className?: string | undefined;
  /** Layout hook on the wrapper. `--disclosure-gap` sets the space between the button and the panel. */
  style?: CSSProperties | undefined;
}

/** Secondary detail behind a button with aria-expanded. The panel stays in the document while closed (hidden), its children too unless `lazy`. */
export function Disclosure({ label, count, children, defaultOpen = false, open: controlled, onOpenChange, dense = false, lazy = false, className, style }: DisclosureProps) {
  const [inner, setInner] = useState(defaultOpen);
  const open = controlled ?? inner;
  const panelId = `${useId()}-panel`;
  const toggle = () => {
    const next = !open;
    if (controlled === undefined) setInner(next);
    onOpenChange?.(next);
  };
  return (
    <div className={cx('disclosure-wrap', className)} style={style} data-open={open ? '' : undefined}>
      <button type="button" className="disclosure" data-dense={dense ? '' : undefined} aria-expanded={open} aria-controls={panelId} onClick={toggle}>
        <IconChevronRight size={12} className="disclosure-chevron" aria-hidden="true" />
        <span className="disclosure-label">{label}</span>
        {count !== undefined && count !== null ? <span className="disclosure-count">{count}</span> : null}
      </button>
      <div id={panelId} className="disclosure-panel" data-dense={dense ? '' : undefined} hidden={!open}>
        {lazy && !open ? null : children}
      </div>
    </div>
  );
}
