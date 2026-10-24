/* Combobox: one typeahead chooser over an async lookup, the ARIA combobox pattern with a list
   popup. The app passes search(query, signal) and gets items back, so the data source (a directory,
   a catalogue, a device list) stays in the app and the kit knows no data shape. It debounces the
   typing, aborts and ignores stale replies, and shows loading, empty and error states. A row render
   slot (renderOption) draws each row, so a person picker is a usage of it with Avatar rows (see
   PersonOption below), and a device or group chooser is another.

   Keyboard (the ARIA combobox pattern): ArrowDown opens the list and moves down, ArrowUp moves up
   (both wrap), Enter picks the active row, Escape closes the list and nothing else (an enclosing
   dialog stays open, the list is a non-modal layer above it), Tab leaves and closes. Focus never
   leaves the input: the active row is announced through aria-activedescendant. Status text (searching,
   count, none, failed) goes to a polite live region.

   Unavailable state: when the lookup cannot work at all (it rejects with an UnavailableError, or
   onSearchError returns 'unavailable') the input becomes a validated free entry field. No lookup runs,
   the list is gone, a one line hint says why, and Enter hands { free: text } to onSelect once
   validate(text) accepts it. The state lasts until the part is mounted again (change its key). */

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { InputHTMLAttributes, KeyboardEvent, ReactNode } from 'react';
import { IconAlert, IconSearch } from '../icons/icons';
import { cx } from '../lib/env';
import { useModalLayer } from '../lib/layers';
import { useFieldControl } from './Field';
import { Avatar } from './Avatar';
import { Spinner } from './Spinner';

export interface ComboboxRowState {
  /** The row the keyboard or pointer is on. */
  active: boolean;
  /** The text in the input, so a row can mark the matching part. */
  query: string;
}

/** What onSelect gets in the unavailable state: the text the user typed, accepted by validate. */
export interface ComboboxFreeEntry {
  free: string;
}

/** Throw or reject with this from search to say the lookup cannot work (not a one off failure), so the
    part falls back to free entry. Any error with `unavailable: true` counts too, for a host that cannot
    import the class. */
export class UnavailableError extends Error {
  readonly unavailable = true;

  constructor(message = 'Search is unavailable.') {
    super(message);
    this.name = 'UnavailableError';
  }
}

/** True for an UnavailableError or any object marked `unavailable: true`. */
export function isUnavailableError(error: unknown): boolean {
  return typeof error === 'object' && error !== null && (error as { unavailable?: unknown }).unavailable === true;
}

export interface ComboboxMessages {
  /** Shown while the first reply is pending. Default "Searching...". */
  loading?: string | undefined;
  /** Shown when the lookup returned nothing. Receives the query. Default `No matches for "<query>"`. */
  empty?: ((query: string) => string) | undefined;
  /** Shown when the lookup threw. Default "Search failed." */
  error?: string | undefined;
  /** The retry button in the error state. Default "Try again". */
  retry?: string | undefined;
  /** The hint in the unavailable state, while the text is empty or valid. Default "Search is unavailable. Type a full entry and press Enter." */
  unavailable?: string | undefined;
  /** The hint when validate answered false with no message. Default "Enter a valid value." */
  invalid?: string | undefined;
}

export interface ComboboxProps<T, F extends ComboboxFreeEntry = never>
  extends Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'defaultValue' | 'onChange' | 'onSelect' | 'role' | 'size'> {
  /** The lookup. It gets the trimmed query and a signal that aborts when a newer query replaces it. */
  search: (query: string, signal: AbortSignal) => Promise<readonly T[]>;
  /** A row was picked (click or Enter). In the unavailable state it gets `{ free: text }`: type the
      part as `Combobox<Item, ComboboxFreeEntry>` and handle both shapes. Without the second type
      argument the callback type is unchanged. */
  onSelect: (item: T | F) => void;
  /** A stable key per item. */
  getKey: (item: T) => string;
  /** The item as text: the row's accessible name, and what the input shows after a pick. */
  getLabel: (item: T) => string;
  /** The row slot. Default: the label. */
  renderOption?: ((item: T, state: ComboboxRowState) => ReactNode) | undefined;
  /** Accessible name when the combobox is not inside a Field. */
  label?: string | undefined;
  /** Characters before the lookup runs. Default 2. */
  minChars?: number | undefined;
  /** Wait after the last keystroke, in ms. Default 300. */
  debounceMs?: number | undefined;
  /** Keys to leave out of the list (already chosen items). */
  excludeKeys?: readonly string[] | undefined;
  /** Empty the input after a pick, for a picker that builds a list. Default false: the input shows the label. */
  clearOnSelect?: boolean | undefined;
  /** Called with the error a lookup threw (an abort is not an error). Return 'unavailable' to switch
      the part to free entry for an error the lookup did not mark itself. */
  onSearchError?: ((error: unknown) => void | 'unavailable') | undefined;
  /** Checks the text in the unavailable state. Return null, undefined or true when it is acceptable,
      a message string (shown in the hint) or false when it is not. Without it any non-empty text is accepted. */
  validate?: ((text: string) => string | boolean | null | undefined) | undefined;
  /** Start in the unavailable state, for a host that already knows the lookup is down. */
  defaultUnavailable?: boolean | undefined;
  messages?: ComboboxMessages | undefined;
  /** 'md' (default, 36px) or 'sm', the compact toolbar height. */
  size?: 'sm' | 'md' | undefined;
  className?: string | undefined;
}

type Phase = 'idle' | 'loading' | 'ready' | 'error';

const UNAVAILABLE_HINT = 'Search is unavailable. Type a full entry and press Enter.';

function isAbort(error: unknown): boolean {
  return typeof error === 'object' && error !== null && (error as { name?: string }).name === 'AbortError';
}

export function Combobox<T, F extends ComboboxFreeEntry = never>({
  search,
  onSelect,
  getKey,
  getLabel,
  renderOption,
  label,
  minChars = 2,
  debounceMs = 300,
  excludeKeys,
  clearOnSelect = false,
  onSearchError,
  validate,
  defaultUnavailable = false,
  messages,
  size,
  className,
  placeholder = 'Search',
  disabled,
  onKeyDown,
  onBlur,
  ...rest
}: ComboboxProps<T, F>) {
  const fieldProps = useFieldControl(rest);
  const baseId = useId();
  const listId = `${baseId}-list`;
  const optionId = (index: number) => `${baseId}-opt-${index}`;
  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<readonly T[]>([]);
  const [phase, setPhase] = useState<Phase>('idle');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [unavailable, setUnavailable] = useState(defaultUnavailable);
  // Bumped on every new query, pick and clear, so a reply that arrives late is dropped.
  const generation = useRef(0);
  // The text of the last pick: typing that text again does not run a lookup for it.
  const picked = useRef<string | null>(null);
  const latest = useRef({ search, onSearchError });
  latest.current = { search, onSearchError };

  // Inside a Field the visible label names the input (label is then only the list's name), otherwise
  // label, aria-label or the placeholder does.
  const insideField = rest.id === undefined && fieldProps.id !== undefined;
  const name = insideField ? undefined : (label ?? rest['aria-label'] ?? placeholder);
  const term = query.trim();
  const excluded = useMemo(() => new Set(excludeKeys ?? []), [excludeKeys]);
  const visible = useMemo(() => items.filter((item) => !excluded.has(getKey(item))), [items, excluded, getKey]);
  const activeIndex = Math.min(active, Math.max(visible.length - 1, 0));

  useEffect(() => {
    const mine = (generation.current += 1);
    if (unavailable || term.length < minChars || term === picked.current) {
      setPhase('idle');
      setItems([]);
      setOpen(false);
      return undefined;
    }
    setPhase('loading');
    setOpen(true);
    const controller = new AbortController();
    const timer = setTimeout(() => {
      latest.current
        .search(term, controller.signal)
        .then((found) => {
          if (generation.current !== mine || controller.signal.aborted) return;
          setItems(found);
          setActive(0);
          setPhase('ready');
        })
        .catch((error: unknown) => {
          if (generation.current !== mine || controller.signal.aborted || isAbort(error)) return;
          setItems([]);
          const verdict = latest.current.onSearchError?.(error);
          if (isUnavailableError(error) || verdict === 'unavailable') {
            setPhase('idle');
            setOpen(false);
            setUnavailable(true);
          } else {
            setPhase('error');
          }
        });
    }, debounceMs);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [term, minChars, debounceMs, attempt, unavailable]);

  // An outside press closes the list. The input owns its own blur, a document listener is the
  // reliable path when the press lands on a row.
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  // The open list is a non-modal layer on the kit stack, so Escape closes the list first and never
  // reaches a dialog around it. Focus stays in the input.
  useModalLayer(open, boxRef, {
    modal: false,
    restoreFocus: false,
    initialFocus: () => inputRef.current,
    onEscape: () => setOpen(false),
  });

  useEffect(() => {
    if (!open || phase !== 'ready') return;
    const row = listRef.current?.children[activeIndex] as HTMLElement | undefined;
    if (row && typeof row.scrollIntoView === 'function') row.scrollIntoView({ block: 'nearest' });
  }, [activeIndex, open, phase]);

  const pick = useCallback(
    (item: T) => {
      generation.current += 1;
      onSelect(item);
      picked.current = clearOnSelect ? null : getLabel(item);
      setQuery(clearOnSelect ? '' : getLabel(item));
      setItems([]);
      setPhase('idle');
      setOpen(false);
    },
    [onSelect, clearOnSelect, getLabel],
  );

  // Free entry: the verdict on the typed text. A message string or false is invalid, anything else is fine.
  const verdict = unavailable && term !== '' && validate ? validate(term) : null;
  const freeProblem =
    verdict === false ? (messages?.invalid ?? 'Enter a valid value.') : typeof verdict === 'string' && verdict !== '' ? verdict : null;
  const freeHint = freeProblem ?? messages?.unavailable ?? UNAVAILABLE_HINT;
  const hintId = `${baseId}-hint`;

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    onKeyDown?.(event);
    if (event.defaultPrevented) return;
    if (unavailable) {
      if (event.key === 'Enter' && term !== '') {
        event.preventDefault();
        if (freeProblem !== null) return;
        onSelect({ free: term } as F);
        if (clearOnSelect) setQuery('');
      }
      return;
    }
    const count = visible.length;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!open) {
        if (term.length >= minChars) setOpen(true);
        return;
      }
      if (count === 0) return;
      const step = event.key === 'ArrowDown' ? 1 : -1;
      setActive((activeIndex + step + count) % count);
    } else if (event.key === 'Enter') {
      if (!open) return;
      event.preventDefault();
      if (phase === 'error') setAttempt((n) => n + 1);
      else if (phase === 'ready' && visible[activeIndex] !== undefined) pick(visible[activeIndex] as T);
    } else if (event.key === 'Tab') {
      setOpen(false);
    }
  };

  const text = {
    loading: messages?.loading ?? 'Searching...',
    empty: messages?.empty ?? ((q: string) => `No matches for "${q}"`),
    error: messages?.error ?? 'Search failed.',
    retry: messages?.retry ?? 'Try again',
  };
  const showList = phase === 'ready' && visible.length > 0;
  const showEmpty = phase === 'ready' && visible.length === 0;
  const showLoading = phase === 'loading' && visible.length === 0;
  const announce = unavailable
    ? freeHint
    : !open
    ? ''
    : phase === 'loading'
      ? text.loading
      : phase === 'error'
        ? text.error
        : showEmpty
          ? text.empty(term)
          : phase === 'ready'
            ? `${visible.length} ${visible.length === 1 ? 'result' : 'results'}`
            : '';

  return (
    <div ref={boxRef} className={cx('combobox', className)} data-size={size === 'sm' ? 'sm' : undefined} data-mode={unavailable ? 'free' : undefined}>
      <div className="combobox-field">
        <IconSearch size={14} />
        <input
          {...fieldProps}
          ref={inputRef}
          type="text"
          role={unavailable ? undefined : 'combobox'}
          autoComplete="off"
          aria-label={name}
          aria-expanded={unavailable ? undefined : open && (showList || showEmpty || showLoading || phase === 'error')}
          aria-controls={unavailable ? undefined : listId}
          aria-autocomplete={unavailable ? undefined : 'list'}
          aria-haspopup={unavailable ? undefined : 'listbox'}
          aria-busy={phase === 'loading' ? true : undefined}
          aria-activedescendant={open && showList ? optionId(activeIndex) : undefined}
          aria-describedby={unavailable ? [fieldProps['aria-describedby'], hintId].filter(Boolean).join(' ') : fieldProps['aria-describedby']}
          aria-invalid={unavailable && freeProblem !== null ? true : fieldProps['aria-invalid']}
          className="input combobox-input"
          data-size={size === 'sm' ? 'sm' : undefined}
          placeholder={placeholder}
          disabled={disabled}
          value={query}
          onChange={(event) => {
            picked.current = null;
            setQuery(event.target.value);
          }}
          onFocus={() => {
            if (phase !== 'idle' && term.length >= minChars) setOpen(true);
          }}
          onBlur={onBlur}
          onKeyDown={handleKeyDown}
        />
      </div>
      <span className="kit-sr-only" role="status" aria-live="polite">
        {announce}
      </span>
      {unavailable ? (
        <p id={hintId} className="combobox-hint" data-tone={freeProblem !== null ? 'danger' : undefined}>
          {freeHint}
        </p>
      ) : null}
      {open && !unavailable ? (
        <div className="combobox-panel" data-phase={phase}>
          {showLoading ? (
            <div className="combobox-msg">
              <Spinner size="sm" /> {text.loading}
            </div>
          ) : null}
          {phase === 'error' ? (
            <div className="combobox-msg" data-tone="danger">
              <IconAlert size={14} />
              <span className="combobox-msg-text">{text.error}</span>
              <button
                type="button"
                className="combobox-retry"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => setAttempt((n) => n + 1)}
              >
                {text.retry}
              </button>
            </div>
          ) : null}
          {showEmpty ? <div className="combobox-msg">{text.empty(term)}</div> : null}
          <ul ref={listRef} id={listId} role="listbox" aria-label={label ?? rest['aria-label'] ?? placeholder} className="combobox-list" hidden={!showList}>
            {showList
              ? visible.map((item, index) => {
                  const isActive = index === activeIndex;
                  return (
                    <li
                      key={getKey(item)}
                      id={optionId(index)}
                      role="option"
                      aria-selected={isActive}
                      aria-label={getLabel(item)}
                      className="combobox-option"
                      data-active={isActive ? 'true' : undefined}
                      onMouseDown={(event) => {
                        event.preventDefault();
                        pick(item);
                      }}
                      onMouseEnter={() => setActive(index)}
                    >
                      {renderOption ? renderOption(item, { active: isActive, query: term }) : getLabel(item)}
                    </li>
                  );
                })
              : null}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/** A person for the PersonOption row: a neutral shape the app maps its directory entry to. */
export interface PersonOptionData {
  name: string;
  /** Second line, for example an address. */
  detail?: string | undefined;
  /** Right aligned and muted, for example a job title. */
  meta?: string | undefined;
  /** Photo URL. Initials show when omitted. */
  src?: string | undefined;
}

/** The row slot for a person picker: an Avatar, the name, a detail line and a muted meta. Use it
    as `renderOption={(p) => <PersonOption person={p} />}` after mapping the item to this shape. */
export function PersonOption({ person }: { person: PersonOptionData }) {
  return (
    <span className="person-option">
      <Avatar name={person.name} src={person.src} size="sm" />
      <span className="person-option-text">
        <span className="person-option-name">{person.name}</span>
        {person.detail ? <span className="person-option-detail">{person.detail}</span> : null}
      </span>
      {person.meta ? <span className="person-option-meta">{person.meta}</span> : null}
    </span>
  );
}
