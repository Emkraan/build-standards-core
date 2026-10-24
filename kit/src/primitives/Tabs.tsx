/* Tabs (route-agnostic) and Segmented (a small set of pressed buttons). Selection is the raised
   neutral surface from hub-layer. Tabs scroll the active tab into view and fade the edge that still
   hides tabs (.tabs-outer data-edge-left / data-edge-right). */

import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import { cx } from '../lib/env';
import type { StatusTone } from './marks';

export interface TabItem {
  id: string;
  label: string;
  icon?: ReactNode;
  badge?: ReactNode;
  disabled?: boolean | undefined;
}

export interface TabsProps {
  items: readonly TabItem[];
  value: string;
  onChange: (id: string) => void;
  /** Accessible name of the tab list. */
  label: string;
  variant?: 'default' | 'pills' | undefined;
  /** Base for element ids. Pair with <TabPanel idBase> to link tabs and panels. */
  idBase?: string | undefined;
  /** Set when matching <TabPanel> elements are rendered, so tabs point at them. */
  withPanels?: boolean | undefined;
  className?: string | undefined;
}

export function tabElementId(idBase: string, id: string): string {
  return `${idBase}-tab-${id}`;
}

export function tabPanelId(idBase: string, id: string): string {
  return `${idBase}-panel-${id}`;
}

export function Tabs({ items, value, onChange, label, variant = 'default', idBase, withPanels = false, className }: TabsProps) {
  const autoId = useId();
  const base = idBase ?? autoId;
  const listRef = useRef<HTMLDivElement | null>(null);
  const [edges, setEdges] = useState({ left: false, right: false });

  const updateEdges = useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    const left = el.scrollLeft > 1;
    const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
    setEdges((prev) => (prev.left === left && prev.right === right ? prev : { left, right }));
  }, []);

  // Scroll the active tab into view inside the strip only, never the page.
  useEffect(() => {
    const list = listRef.current;
    const tab = list?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (list && tab) {
      const start = tab.offsetLeft - list.offsetLeft;
      const end = start + tab.offsetWidth;
      if (start < list.scrollLeft) list.scrollLeft = Math.max(0, start - 24);
      else if (end > list.scrollLeft + list.clientWidth) list.scrollLeft = end - list.clientWidth + 24;
    }
    updateEdges();
  }, [value, updateEdges]);

  useEffect(() => {
    const list = listRef.current;
    if (!list) return undefined;
    window.addEventListener('resize', updateEdges);
    const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(updateEdges) : null;
    ro?.observe(list);
    return () => {
      window.removeEventListener('resize', updateEdges);
      ro?.disconnect();
    };
  }, [updateEdges]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const enabled = items.filter((t) => !t.disabled);
    const index = enabled.findIndex((t) => t.id === value);
    let next: TabItem | undefined;
    if (event.key === 'ArrowRight') next = enabled[(index + 1) % enabled.length];
    else if (event.key === 'ArrowLeft') next = enabled[(index - 1 + enabled.length) % enabled.length];
    else if (event.key === 'Home') next = enabled[0];
    else if (event.key === 'End') next = enabled[enabled.length - 1];
    if (!next) return;
    event.preventDefault();
    onChange(next.id);
    document.getElementById(tabElementId(base, next.id))?.focus();
  };

  return (
    <div className={cx('tabs-outer', className)} data-edge-left={edges.left ? '' : undefined} data-edge-right={edges.right ? '' : undefined}>
      <div
        ref={listRef}
        className="tabs"
        role="tablist"
        aria-label={label}
        data-variant={variant === 'pills' ? 'pills' : undefined}
        onScroll={updateEdges}
        onKeyDown={onKeyDown}
      >
        {items.map((item) => {
          const selected = item.id === value;
          return (
            <button
              key={item.id}
              id={tabElementId(base, item.id)}
              type="button"
              role="tab"
              className="tab"
              aria-selected={selected}
              aria-controls={withPanels ? tabPanelId(base, item.id) : undefined}
              tabIndex={selected ? 0 : -1}
              disabled={item.disabled}
              onClick={() => onChange(item.id)}
            >
              {item.icon ? (
                <span className="tab-icon" aria-hidden="true">
                  {item.icon}
                </span>
              ) : null}
              <span>{item.label}</span>
              {item.badge !== undefined && item.badge !== null ? <span className="tab-badge">{item.badge}</span> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export interface TabPanelProps {
  idBase: string;
  tabId: string;
  children?: ReactNode;
  className?: string | undefined;
}

export function TabPanel({ idBase, tabId, children, className }: TabPanelProps) {
  return (
    <div role="tabpanel" id={tabPanelId(idBase, tabId)} aria-labelledby={tabElementId(idBase, tabId)} tabIndex={0} className={cx('tab-panel', className)}>
      {children}
    </div>
  );
}

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  /** Tooltip text. */
  tip?: string | undefined;
  /** A status cue on this option: a dot before the label and a tinted badge. The label still says
      what the option is, colour is never the only channel. */
  tone?: StatusTone | undefined;
  /** A small count after the label, for example the number of rows the option shows. */
  badge?: ReactNode;
  /** Leading icon, decorative (the label names the option). */
  icon?: ReactNode;
  /** Shows only the icon: the label stays as the accessible name and becomes the tooltip. */
  iconOnly?: boolean | undefined;
}

export interface SegmentedProps<T extends string> {
  options: readonly SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** Accessible name of the group. */
  label: string;
  /** Stretch to the container width. */
  full?: boolean | undefined;
  className?: string | undefined;
}

/** A segmented toggle (ranges, views, series). Arrow keys move the selection. */
export function Segmented<T extends string>({ options, value, onChange, label, full = false, className }: SegmentedProps<T>) {
  const groupRef = useRef<HTMLFieldSetElement | null>(null);
  const onKeyDown = (event: KeyboardEvent<HTMLFieldSetElement>) => {
    const index = options.findIndex((o) => o.value === value);
    let next: SegmentedOption<T> | undefined;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = options[(index + 1) % options.length];
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = options[(index - 1 + options.length) % options.length];
    else if (event.key === 'Home') next = options[0];
    else if (event.key === 'End') next = options[options.length - 1];
    if (!next) return;
    event.preventDefault();
    onChange(next.value);
    const i = options.indexOf(next);
    groupRef.current?.querySelectorAll<HTMLButtonElement>('.seg-btn')[i]?.focus();
  };
  return (
    <fieldset ref={groupRef} className={cx('seg', className)} data-full={full ? '' : undefined} onKeyDown={onKeyDown}>
      <legend className="kit-sr-only">{label}</legend>
      {options.map((o) => {
        const pressed = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            className="seg-btn"
            aria-pressed={pressed}
            tabIndex={pressed ? 0 : -1}
            data-tip={o.tip ?? (o.iconOnly && o.icon ? o.label : undefined)}
            data-tone={o.tone}
            data-icon-only={o.iconOnly && o.icon ? '' : undefined}
            aria-label={o.iconOnly && o.icon ? o.label : undefined}
            onClick={() => onChange(o.value)}
          >
            {o.tone && o.tone !== 'neutral' ? <span className="seg-dot" data-tone={o.tone} aria-hidden="true" /> : null}
            {o.icon ? (
              <span className="seg-icon" aria-hidden="true">
                {o.icon}
              </span>
            ) : null}
            {o.iconOnly && o.icon ? null : o.label}
            {o.badge !== undefined && o.badge !== null ? ' ' : null}
            {o.badge !== undefined && o.badge !== null ? (
              <span className="seg-badge" data-tone={o.tone}>
                {o.badge}
              </span>
            ) : null}
          </button>
        );
      })}
    </fieldset>
  );
}
