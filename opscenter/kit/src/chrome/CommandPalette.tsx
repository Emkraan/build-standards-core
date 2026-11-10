/* CommandPalette (UI standard sections 24 and 25): Cmd or Ctrl and K opens it from anywhere, and
   a bare / opens it too, but never while the person is typing in a field or a dialog is open.
   Typing filters by substring with the match highlighted, the arrow keys move, Enter opens, and Escape
   closes it from anywhere, a focused result row included. A palette may carry a `preview` slot (a
   pane beside the list that shows the active row) and a `scope`: a scoped palette answers Cmd or
   Ctrl and K (and /) only while focus is inside a region marked with `paletteScope(name)`, and the
   global palette then stays shut there, so two searches can share one shortcut without fighting.
   A palette may also carry its own `rank` (the default stays the substring filter), a `toolbar` slot
   under the search row for filter chips, a `limit` on the rows shown, and rows with a `description`
   second line and a `badge` status mark. */

import { Fragment, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { IconSearch } from '../icons/icons';
import { cx, isBrowser, isMacLike, isTypingTarget } from '../lib/env';
import { isDialogOpen, useModalLayer } from '../lib/layers';
import { ShortcutContext, comboLabel, parseKeys, useShortcut } from '../lib/shortcuts';
import { Kbd } from '../primitives/marks';

export interface PaletteItem {
  id: string;
  label: string;
  /** Right-hand hint: the kind of result, for example Page, Person, Action. */
  kind?: string | undefined;
  /** Extra text that matches without being shown (search keywords). */
  keywords?: readonly string[] | undefined;
  icon?: ReactNode;
  /** Second line under the label, one line, shortened with an ellipsis. Read as part of the row. */
  description?: ReactNode;
  /** Status mark at the right end of the row, next to `kind`. Give it text, not colour alone. */
  badge?: ReactNode;
  /** Header the row sits under. Rows of one group render together, groups in the order they first
      appear in the ranked results. Rows without a group sit above the headed ones, with no header. */
  group?: string | undefined;
  /** Keys in the shortcut grammar (`g h`, `shift+n`, `mod+j`), shown on the row. Inside a
      ShortcutLayer the palette also registers it, so the help sheet lists it and the keys run
      `onSelect`. */
  shortcut?: string | undefined;
  /** Runs on Enter or click. */
  onSelect: () => void;
}

/** The document event that opens the mounted palette. Exported so an app that still mounts its own
    palette during a migration can listen for it (or use onPaletteOpen) instead of hard-coding it. */
export const PALETTE_OPEN_EVENT = 'kit:open-palette';
const OPEN_EVENT = PALETTE_OPEN_EVENT;
const SCOPE_ATTR = 'data-palette-scope';

/** Scopes of the mounted scoped palettes, with a count so two mounts of one scope stay correct. */
const mountedScopes = new Map<string, number>();

/**
 * True for a bare `/` keydown that should open search: the key is `/`, no Ctrl, Meta, Alt or Shift
 * is held, it is not a key repeat or an input method composition, nothing else handled it, and the
 * target is not a text field, a select, a textarea or an editable region.
 */
export function isSlashOpen(event: Pick<globalThis.KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey' | 'repeat' | 'isComposing' | 'defaultPrevented' | 'target'>): boolean {
  if (event.key !== '/') return false;
  if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return false;
  if (event.repeat || event.isComposing || event.defaultPrevented) return false;
  return !isTypingTarget(event.target);
}

/** Opens the mounted CommandPalette from anywhere (a search button, the feed strip). */
export function openCommandPalette(): void {
  if (isBrowser) document.dispatchEvent(new CustomEvent(OPEN_EVENT, { detail: {} }));
}

/** Calls `listener` whenever something asks the palette to open (a SearchTrigger, the feed strip,
    openCommandPalette or openScopedPalette), with the requested scope if any. Returns the unsubscribe. */
export function onPaletteOpen(listener: (detail: { scope?: string | undefined }) => void): () => void {
  if (!isBrowser) return () => undefined;
  const handler = (event: Event) => listener((event as CustomEvent<{ scope?: string } | null>).detail ?? {});
  document.addEventListener(OPEN_EVENT, handler);
  return () => document.removeEventListener(OPEN_EVENT, handler);
}

/** Opens the scoped CommandPalette that owns `scope`, from a button outside its region. */
export function openScopedPalette(scope: string): void {
  if (isBrowser) document.dispatchEvent(new CustomEvent(OPEN_EVENT, { detail: { scope } }));
}

/**
 * Props that mark a region as a palette scope: spread them on the element (a composer, an editor)
 * where Cmd or Ctrl and K should open the palette with that `scope` instead of the global one.
 */
export function paletteScope(scope: string): { 'data-palette-scope': string } {
  return { [SCOPE_ATTR]: scope };
}

/** The scope names of the region that holds an element, innermost region first. */
function scopesAround(target: EventTarget | null): string[] {
  if (!(target instanceof Element)) return [];
  const out: string[] = [];
  let el: Element | null = target.closest(`[${SCOPE_ATTR}]`);
  while (el) {
    out.push(...(el.getAttribute(SCOPE_ATTR) ?? '').split(/\s+/).filter(Boolean));
    el = el.parentElement?.closest(`[${SCOPE_ATTR}]`) ?? null;
  }
  return out;
}

/**
 * The scoped shortcut rule. A scoped palette takes Cmd or Ctrl and K when focus is inside its
 * region. The global palette takes it everywhere except inside a region whose scope a mounted
 * palette owns.
 */
export function paletteOwnsKey(scope: string | undefined, target: EventTarget | null): boolean {
  const around = scopesAround(target);
  if (scope !== undefined) return around.includes(scope);
  return !around.some((name) => (mountedScopes.get(name) ?? 0) > 0);
}

/**
 * Rank of one item for a query, 0 for no match. Label matches outrank keyword matches, which outrank
 * the kind: exact label, label prefix, a word start in the label, any label substring, then an exact,
 * prefix or substring keyword, then the kind.
 */
export function scorePaletteItem(item: PaletteItem, query: string): number {
  const q = query.trim().toLowerCase();
  if (!q) return 1;
  const label = item.label.toLowerCase();
  if (label === q) return 100;
  if (label.startsWith(q)) return 90;
  if (label.split(/[\s\-_/.]+/).some((w) => w.startsWith(q))) return 80;
  if (label.includes(q)) return 70;
  let best = 0;
  for (const k of item.keywords ?? []) {
    const kw = k.toLowerCase();
    const score = kw === q ? 60 : kw.startsWith(q) ? 50 : kw.includes(q) ? 40 : 0;
    if (score > best) best = score;
  }
  if (best) return best;
  return item.kind?.toLowerCase().includes(q) ? 30 : 0;
}

/** Ranks by `scorePaletteItem` (best first, ties keep the given order) and drops non matches. */
export function filterPaletteItems(items: readonly PaletteItem[], query: string, limit = 50): PaletteItem[] {
  if (!query.trim()) return items.slice(0, limit);
  return items
    .map((item, index) => ({ item, index, score: scorePaletteItem(item, query) }))
    .filter((r) => r.score > 0)
    .sort((x, y) => y.score - x.score || x.index - y.index)
    .slice(0, limit)
    .map((r) => r.item);
}

/** Gathers rows by `group` (first appearance order, ungrouped rows first), keeping order inside each. */
export function groupPaletteItems(items: readonly PaletteItem[]): PaletteItem[] {
  if (!items.some((i) => i.group)) return [...items];
  const order: (string | undefined)[] = [undefined];
  for (const i of items) if (!order.includes(i.group)) order.push(i.group);
  return order.flatMap((g) => items.filter((i) => i.group === g));
}

/** Wraps the first case-insensitive match of `query` in <mark class="search-hit">. */
export function highlight(text: string, query: string): ReactNode {
  const q = query.trim();
  if (!q) return text;
  const i = text.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return text;
  return (
    <>
      {text.slice(0, i)}
      <mark className="search-hit">{text.slice(i, i + q.length)}</mark>
      {text.slice(i + q.length)}
    </>
  );
}

export interface PaletteFilter {
  id: string;
  label: string;
  /** Which rows the tab keeps. Default: rows whose `group` equals `id`. */
  match?: ((item: PaletteItem) => boolean) | undefined;
}

export interface CommandPaletteProps {
  items: readonly PaletteItem[];
  /** Controlled open state. Omit to let the palette manage it. */
  open?: boolean | undefined;
  onOpenChange?: ((open: boolean) => void) | undefined;
  placeholder?: string | undefined;
  label?: string | undefined;
  emptyText?: string | undefined;
  /** A bare / opens the palette outside text fields. Default true. Turn it off when the page gives
      / another meaning. */
  slashOpens?: boolean | undefined;
  /** Called with the query on every change, and with '' when the palette opens again with a
      cleared query. Feed async server results back in through `items`. */
  onQueryChange?: ((query: string) => void) | undefined;
  /**
   * Pane shown beside the list for the active row (`undefined` when no row is active). Render a
   * plain read-only view of the row. On a narrow screen (640px and below) the pane is hidden and
   * the list keeps the full width.
   */
  preview?: ((item: PaletteItem | undefined) => ReactNode) | undefined;
  /** Accessible name of the preview pane. */
  previewLabel?: string | undefined;
  /**
   * Makes this a scoped palette: it opens with Cmd or Ctrl and K only while focus is inside a
   * region marked with `paletteScope(scope)`, and `openScopedPalette(scope)` opens it. The global
   * palette (no scope) ignores the shortcut inside such a region.
   */
  scope?: string | undefined;
  /** Help sheet text for a scoped palette's shortcut. */
  shortcutDescription?: string | undefined;
  /**
   * Replaces the default substring filter. Called with the raw query (an empty string included, so
   * the host decides the empty-query order) and the full `items`. Return the matching items in the
   * order to show them. `limit` still caps what is shown.
   */
  rank?: ((query: string, items: readonly PaletteItem[]) => readonly PaletteItem[]) | undefined;
  /**
   * A row under the search field for filter chips or a scope switch. Keys pressed inside it keep
   * their own meaning (Enter on a chip never opens a result). Tab reaches it after the field.
   */
  toolbar?: ReactNode;
  /** Accessible name of the toolbar group. */
  toolbarLabel?: string | undefined;
  /** The most rows shown. Default 50, `Infinity` shows every match. */
  limit?: number | undefined;
  /** Filter tabs shown under the input after an All tab. Tab and Shift+Tab cycle them. */
  filters?: readonly PaletteFilter[] | undefined;
  /** Label of the tab that keeps every row. Default All. */
  allLabel?: string | undefined;
}

export function CommandPalette({
  items,
  open: openProp,
  onOpenChange,
  placeholder = 'Search pages, people and actions',
  label = 'Search',
  emptyText = 'No results',
  slashOpens = true,
  onQueryChange,
  preview,
  previewLabel = 'Preview',
  scope,
  shortcutDescription,
  rank,
  toolbar,
  toolbarLabel = 'Filters',
  limit = 50,
  filters,
  allLabel = 'All',
}: CommandPaletteProps) {
  const [openState, setOpenState] = useState(false);
  const open = openProp ?? openState;
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const [filterIndex, setFilterIndex] = useState(0);
  const registry = useContext(ShortcutContext);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const toolbarRef = useRef<HTMLDivElement | null>(null);
  const base = useId();
  const listId = `${base}-list`;

  const setOpen = useCallback(
    (next: boolean) => {
      if (openProp === undefined) setOpenState(next);
      onOpenChange?.(next);
    },
    [openProp, onOpenChange],
  );

  useShortcut({
    id: scope === undefined ? 'kit.palette' : `kit.palette.${scope}`,
    keys: 'mod+k',
    description: shortcutDescription ?? (scope === undefined ? 'Open search' : 'Open search here'),
    group: 'General',
  });

  useEffect(() => {
    if (!registry) return undefined;
    const offs = items
      .filter((i) => i.shortcut)
      .map((i) =>
        registry.register({
          id: `palette.${i.id}`,
          keys: i.shortcut as string,
          description: i.label,
          group: i.group ?? 'Actions',
          handler: () => i.onSelect(),
        }),
      );
    return () => {
      for (const off of offs) off();
    };
  }, [registry, items]);

  useEffect(() => {
    if (scope === undefined) return undefined;
    mountedScopes.set(scope, (mountedScopes.get(scope) ?? 0) + 1);
    return () => {
      const left = (mountedScopes.get(scope) ?? 1) - 1;
      if (left <= 0) mountedScopes.delete(scope);
      else mountedScopes.set(scope, left);
    };
  }, [scope]);
  // Display only: the listener below handles the key, and the help dialog lists it.
  useShortcut(
    slashOpens
      ? { id: scope === undefined ? 'kit.palette.slash' : `kit.palette.slash.${scope}`, keys: '/', description: shortcutDescription ?? (scope === undefined ? 'Open search' : 'Open search here'), group: 'General' }
      : null,
  );

  // Cmd or Ctrl and K toggles the palette from anywhere, text fields included, unless another
  // dialog is open.
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey) {
        // Another dialog is open: the palette must not stack on top of it (it may hold a pending
        // confirm or a half-filled form). The palette itself still closes with the shortcut.
        if (!open && isDialogOpen()) return;
        // Closing always works. Opening follows the scope rule.
        if (!open && !paletteOwnsKey(scope, event.target)) return;
        event.preventDefault();
        setOpen(!open);
        return;
      }
      // A bare / opens the palette, by the same scope rule. Another dialog or a text field keeps the key.
      if (slashOpens && !open && isSlashOpen(event) && !isDialogOpen() && paletteOwnsKey(scope, event.target)) {
        event.preventDefault();
        setOpen(true);
      }
    };
    // The open event (a search button, the feed strip) obeys the same guard as the shortcut.
    const onOpen = (event: Event) => {
      const wanted = (event as CustomEvent<{ scope?: string } | null>).detail?.scope;
      if (wanted !== scope) return;
      if (!open && isDialogOpen()) return;
      setOpen(true);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener(OPEN_EVENT, onOpen);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener(OPEN_EVENT, onOpen);
    };
  }, [open, setOpen, scope, slashOpens]);

  const queryRef = useRef(query);
  queryRef.current = query;
  const onQueryChangeRef = useRef(onQueryChange);
  onQueryChangeRef.current = onQueryChange;

  useEffect(() => {
    if (open) {
      if (queryRef.current !== '') onQueryChangeRef.current?.('');
      setQuery('');
      setActive(0);
      setFilterIndex(0);
    }
  }, [open]);

  const close = useCallback(() => setOpen(false), [setOpen]);
  useModalLayer(open, panelRef, { onEscape: close, initialFocus: () => inputRef.current });

  const tabs = useMemo(() => [{ id: '', label: allLabel } as PaletteFilter, ...(filters ?? [])], [filters, allLabel]);
  const tab = tabs[Math.min(filterIndex, tabs.length - 1)] as PaletteFilter;
  // With a toolbar, Tab keeps its native move into the toolbar and the filter tabs join the tab order.
  const tabCycles = tabs.length > 1 && !toolbar;
  const results = useMemo(() => {
    const pool = tab.id === '' ? items : items.filter((i) => (tab.match ? tab.match(i) : i.group === tab.id));
    if (!rank) return groupPaletteItems(filterPaletteItems(pool, query, limit));
    const ranked = rank(query, pool);
    return groupPaletteItems(Number.isFinite(limit) ? ranked.slice(0, Math.max(0, limit)) : [...ranked]);
  }, [items, query, tab, rank, limit]);
  const activeIndex = Math.min(active, Math.max(0, results.length - 1));
  const optionId = (i: number) => `${base}-opt-${i}`;
  const previewId = `${base}-preview`;

  useEffect(() => {
    if (!open) return;
    const row = document.getElementById(optionId(activeIndex));
    if (row && typeof row.scrollIntoView === 'function') row.scrollIntoView({ block: 'nearest' });
  }, [activeIndex, open]);

  const choose = (item: PaletteItem | undefined) => {
    if (!item) return;
    setOpen(false);
    item.onSelect();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // Inside the toolbar the keys belong to its controls.
    if (toolbarRef.current?.contains(event.target as Node)) return;
    if (event.key === 'Tab' && tabCycles) {
      event.preventDefault();
      setFilterIndex((filterIndex + (event.shiftKey ? tabs.length - 1 : 1)) % tabs.length);
      setActive(0);
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((activeIndex + 1) % Math.max(1, results.length));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((activeIndex - 1 + results.length) % Math.max(1, results.length));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      choose(results[activeIndex]);
    }
  };

  if (!open || !isBrowser) return null;
  return createPortal(
    <div
      className="palette-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div ref={panelRef} className={cx('palette', preview && 'palette-with-preview')} role="dialog" aria-modal="true" aria-label={label} tabIndex={-1} onKeyDown={onKeyDown}>
        <div className="palette-search">
          <IconSearch className="palette-search-icon" />
          <input
            ref={inputRef}
            className="palette-input"
            type="text"
            role="combobox"
            aria-label={label}
            aria-expanded={results.length > 0}
            aria-controls={results.length > 0 ? listId : undefined}
            aria-autocomplete="list"
            aria-activedescendant={results.length ? optionId(activeIndex) : undefined}
            autoComplete="off"
            spellCheck={false}
            placeholder={placeholder}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActive(0);
              onQueryChange?.(event.target.value);
            }}
          />
        </div>
        {tabs.length > 1 ? (
          <div className="palette-tabs" role="group" aria-label={`${label} filters`}>
            {tabs.map((t, i) => (
              <button
                key={t.id || '__all'}
                type="button"
                tabIndex={tabCycles ? -1 : 0}
                className="palette-tab"
                aria-pressed={i === filterIndex}
                onClick={() => {
                  setFilterIndex(i);
                  setActive(0);
                  inputRef.current?.focus();
                }}
              >
                {t.label}
              </button>
            ))}
          </div>
        ) : null}
        {toolbar ? (
          <div ref={toolbarRef} className="palette-toolbar" role="group" aria-label={toolbarLabel}>
            {toolbar}
          </div>
        ) : null}
        <div className="palette-body">
          <div className="palette-main">
            {results.length === 0 ? (
              <div className="palette-empty" role="status">
                {emptyText}
              </div>
            ) : (
              <div ref={listRef} id={listId} className="palette-list" role="listbox" aria-label={label}>
                {results.map((item, i) => (
                  <Fragment key={item.id}>
                    {item.group && item.group !== results[i - 1]?.group ? (
                      <div className="palette-group" role="presentation">
                        {item.group}
                      </div>
                    ) : null}
                  <div
                    id={optionId(i)}
                    role="option"
                    aria-selected={i === activeIndex}
                    tabIndex={-1}
                    className={cx('palette-row', i === activeIndex && 'is-active')}
                    onMouseMove={() => setActive(i)}
                    onClick={() => choose(item)}
                  >
                    <span className="palette-label">
                      {item.icon ? (
                        <span className="palette-icon" aria-hidden="true">
                          {item.icon}
                        </span>
                      ) : null}
                      {item.description ? (
                        <span className="palette-text">
                          <span>{highlight(item.label, query)}</span>
                          <span className="palette-desc">{item.description}</span>
                        </span>
                      ) : (
                        <span>{highlight(item.label, query)}</span>
                      )}
                    </span>
                    {item.badge ? (
                      <span className="palette-end">
                        {item.shortcut ? <PaletteKeys keys={item.shortcut} /> : item.kind ? <span className="palette-kind">{item.kind}</span> : null}
                        <span className="palette-badge">{item.badge}</span>
                      </span>
                    ) : item.shortcut ? (
                      <PaletteKeys keys={item.shortcut} />
                    ) : item.kind ? (
                      <span className="palette-kind">{item.kind}</span>
                    ) : null}
                  </div>
                  </Fragment>
                ))}
              </div>
            )}
          </div>
          {preview ? (
            <div id={previewId} className="palette-preview" role="region" aria-label={previewLabel} tabIndex={0}>
              {preview(results[activeIndex])}
            </div>
          ) : null}
        </div>
        <div className="palette-foot" aria-hidden="true">
          <Kbd>Up</Kbd>
          <Kbd>Down</Kbd> to move <Kbd>Enter</Kbd> to open{tabCycles ? (
            <>
              {' '}
              <Kbd>Tab</Kbd> to switch filter
            </>
          ) : null}{' '}
          <Kbd>Esc</Kbd> to close
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** The keys of an item shortcut, shown on its row. */
function PaletteKeys({ keys }: { keys: string }) {
  return (
    <span className="palette-keys" aria-hidden="true">
      {parseKeys(keys).map((combo, n) => (
        <span key={n} className="palette-combo">
          {comboLabel(combo).map((k) => (
            <Kbd key={k}>{k}</Kbd>
          ))}
        </span>
      ))}
    </span>
  );
}

export interface SearchTriggerProps {
  label?: string | undefined;
  /** Icon-only form. `auto` switches to it below the phone breakpoint (640px), `true` always.
      Default false (label and keys at every width). The accessible name keeps the shortcut. */
  compact?: boolean | 'auto' | undefined;
  className?: string | undefined;
  /** Called instead of opening the kit palette, for an app that routes search to its own palette.
      Unset (the default), the button dispatches PALETTE_OPEN_EVENT as before. */
  onSearch?: (() => void) | undefined;
}

/** The header or feed strip button that opens the palette, showing its shortcut. */
export function SearchTrigger({ label = 'Search', compact = false, className, onSearch }: SearchTriggerProps) {
  const mod = isMacLike() ? 'Cmd' : 'Ctrl';
  const mode = compact === 'auto' ? 'auto' : compact ? 'on' : undefined;
  return (
    <button
      type="button"
      className={cx('search-btn', className)}
      onClick={onSearch ?? openCommandPalette}
      aria-keyshortcuts={isMacLike() ? 'Meta+K' : 'Control+K'}
      aria-label={mode ? `${label} (${mod}+K)` : undefined}
      data-compact={mode}
      data-tip={mode === 'on' ? label : undefined}
      data-tip-kbd={mode === 'on' ? `${mod}+K` : undefined}
    >
      <IconSearch size={14} />
      <span className="search-btn-label">{label}</span>
      <span className="search-btn-keys" aria-hidden="true">
        <Kbd>{mod}</Kbd>
        <Kbd>K</Kbd>
      </span>
    </button>
  );
}
