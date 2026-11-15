/* Split layout: a list pane beside a detail pane, for a master and detail page. The list pane has a
   width the reader can change with a resize handle (a window splitter: a focusable separator with
   a value, moved by the arrow keys, Home and End, or by dragging, and reset by Enter or a double
   click). The width is clamped so the detail pane never shrinks under its minimum. When the layout
   itself is narrower than `stackBelow` pixels (measured on the layout, not on the window, so a
   layout inside a narrow column stacks too) the panes stack, list above detail, the handle goes
   away and the list is capped in height so the detail stays reachable. Pass `width` and
   `onWidthChange` to own the width (for example to persist it), otherwise it is kept here. */

import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { CSSProperties, KeyboardEvent, PointerEvent as ReactPointerEvent, ReactNode } from 'react';
import { cx } from '../lib/env';
import { EmptyState } from '../primitives/EmptyState';

export const SPLIT_DEFAULT_WIDTH = 360;
export const SPLIT_MIN_WIDTH = 240;
export const SPLIT_MAX_WIDTH = 640;
/** The narrowest the detail pane is allowed to get while the panes sit side by side. */
export const SPLIT_MIN_DETAIL = 320;
/** The layout width, in pixels, under which the panes stack. */
export const SPLIT_STACK_BELOW = 720;
const HANDLE_PX = 8;
const KEY_STEP = 16;
const KEY_STEP_LARGE = 64;

/** Keeps a list pane width inside its bounds and, when the layout width is known, leaves the
    detail pane its minimum. The lower bound always wins, so a very small layout never inverts. */
export function clampSplitWidth(width: number, min: number, max: number, container = 0, minDetail = SPLIT_MIN_DETAIL): number {
  const room = container > 0 ? container - HANDLE_PX - minDetail : Infinity;
  const upper = Math.max(min, Math.min(max, room));
  return Math.round(Math.min(Math.max(width, min), upper));
}

export interface SplitLayoutProps {
  /** The list pane content. It scrolls on its own. */
  list: ReactNode;
  /** The detail pane content. Null or absent shows `emptyDetail`. */
  detail?: ReactNode;
  /** Accessible name of the list pane. */
  listLabel: string;
  /** Accessible name of the detail pane. */
  detailLabel: string;
  /** Shown in the detail pane while there is no detail. */
  emptyDetail?: ReactNode;
  /** Uncontrolled starting width of the list pane in pixels. Default 360. */
  defaultWidth?: number | undefined;
  /** Controlled width of the list pane in pixels. */
  width?: number | undefined;
  /** Called with every new width (a key press or a drag step). */
  onWidthChange?: ((width: number) => void) | undefined;
  minWidth?: number | undefined;
  maxWidth?: number | undefined;
  minDetailWidth?: number | undefined;
  /** Stack the panes when the layout is narrower than this many pixels. Default 720. */
  stackBelow?: number | undefined;
  /** Accessible name of the resize handle. */
  handleLabel?: string | undefined;
  /** CSS height of the layout. Default: fills its parent. */
  height?: string | undefined;
  className?: string | undefined;
}

export function SplitLayout({
  list,
  detail,
  listLabel,
  detailLabel,
  emptyDetail,
  defaultWidth = SPLIT_DEFAULT_WIDTH,
  width: widthProp,
  onWidthChange,
  minWidth = SPLIT_MIN_WIDTH,
  maxWidth = SPLIT_MAX_WIDTH,
  minDetailWidth = SPLIT_MIN_DETAIL,
  stackBelow = SPLIT_STACK_BELOW,
  handleLabel = 'Resize list pane',
  height,
  className,
}: SplitLayoutProps) {
  const listId = `${useId()}-list`;
  const root = useRef<HTMLDivElement | null>(null);
  const [own, setOwn] = useState(defaultWidth);
  const [container, setContainer] = useState(0);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ startX: number; startWidth: number; sign: number } | null>(null);

  useEffect(() => {
    const el = root.current;
    if (!el) return undefined;
    setContainer(el.getBoundingClientRect().width);
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver((entries) => {
      const entry = entries[entries.length - 1];
      if (entry) setContainer(entry.contentRect.width);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const stacked = container > 0 && container < stackBelow;
  const clamp = useCallback(
    (w: number) => clampSplitWidth(w, minWidth, maxWidth, container, minDetailWidth),
    [minWidth, maxWidth, container, minDetailWidth],
  );
  const width = clamp(widthProp ?? own);
  const upper = clampSplitWidth(Infinity, minWidth, maxWidth, container, minDetailWidth);

  const setWidth = useCallback(
    (next: number) => {
      const value = clamp(next);
      if (widthProp === undefined) setOwn(value);
      onWidthChange?.(value);
    },
    [clamp, widthProp, onWidthChange],
  );

  const isRtl = () => (root.current ? getComputedStyle(root.current).direction === 'rtl' : false);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? KEY_STEP_LARGE : KEY_STEP;
    const grow = isRtl() ? 'ArrowLeft' : 'ArrowRight';
    const shrink = isRtl() ? 'ArrowRight' : 'ArrowLeft';
    if (event.key === grow) setWidth(width + step);
    else if (event.key === shrink) setWidth(width - step);
    else if (event.key === 'Home') setWidth(minWidth);
    else if (event.key === 'End') setWidth(upper);
    else if (event.key === 'Enter') setWidth(defaultWidth);
    else return;
    event.preventDefault();
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    drag.current = { startX: event.clientX, startWidth: width, sign: isRtl() ? -1 : 1 };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setDragging(true);
    event.preventDefault();
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (d) setWidth(d.startWidth + (event.clientX - d.startX) * d.sign);
  };
  const endDrag = () => {
    drag.current = null;
    setDragging(false);
  };

  const style = { '--split-list': `${width}px`, ...(height ? { '--split-height': height } : {}) } as CSSProperties;

  return (
    <div
      ref={root}
      className={cx('split', className)}
      style={style}
      data-stacked={stacked ? '' : undefined}
      data-dragging={dragging ? '' : undefined}
    >
      <section className="split-pane split-list" id={listId} aria-label={listLabel}>
        {list}
      </section>
      {stacked ? null : (
        <div
          className="split-handle"
          role="separator"
          aria-orientation="vertical"
          aria-label={handleLabel}
          aria-controls={listId}
          aria-valuenow={width}
          aria-valuemin={minWidth}
          aria-valuemax={upper}
          aria-valuetext={`${width} pixels wide`}
          tabIndex={0}
          onKeyDown={onKeyDown}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onLostPointerCapture={endDrag}
          onDoubleClick={() => setWidth(defaultWidth)}
        />
      )}
      <section className="split-pane split-detail" aria-label={detailLabel}>
        {detail ?? emptyDetail ?? <EmptyState compact title="Nothing selected" body="Pick an item from the list to see it here." />}
      </section>
    </div>
  );
}
