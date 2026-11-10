/* FilterPanel: a form with one typed cell per filterable column and Apply and Clear. It emits a
   neutral list of { key, op, value } clauses and nothing about the host's data: the host maps the
   list onto its own query, store or in-memory predicate. Cell types: text, number (from and to),
   date (from and to), select, multiselect, boolean and lookup (suggestions from an async loader).
   Every cell is named by a visible label, a range is a labelled group, and the lookup cell is a
   small local combobox (role combobox, a listbox of options, arrow keys, Enter, Escape). With
   `multiple` the lookup keeps several chosen options as removable chips and emits one `in` clause.
   A cell left empty adds no clause. */

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import { cx } from '../lib/env';
import { Button } from './Button';
import { Field, Input, Select } from './Field';

export type FilterOp = 'eq' | 'neq' | 'contains' | 'gte' | 'lte' | 'in';
/** One value: text, a number, a boolean, a date as YYYY-MM-DD, or the list an `in` clause carries. */
export type FilterValue = string | number | boolean | readonly string[];

/** The neutral result: one clause per filled cell (two for a range with both ends). */
export interface FilterClause {
  key: string;
  op: FilterOp;
  value: FilterValue;
}

export interface LookupOption {
  value: string;
  label: string;
}

/** Loads suggestions for what was typed. Honour the signal: it aborts when a newer query starts. */
export type LookupLoader = (query: string, signal: AbortSignal) => Promise<readonly LookupOption[]>;

interface FilterFieldBase {
  /** The clause key. Unique in the panel. */
  key: string;
  /** The visible label of the cell. */
  label: string;
}

export type FilterField =
  | (FilterFieldBase & { type: 'text'; placeholder?: string | undefined })
  | (FilterFieldBase & { type: 'number' })
  | (FilterFieldBase & { type: 'date' })
  | (FilterFieldBase & { type: 'select'; options: readonly LookupOption[] })
  | (FilterFieldBase & { type: 'multiselect'; options: readonly LookupOption[] })
  | (FilterFieldBase & { type: 'boolean'; trueLabel?: string | undefined; falseLabel?: string | undefined })
  | (FilterFieldBase & { type: 'lookup'; load: LookupLoader; placeholder?: string | undefined; multiple?: boolean | undefined });

/** What a cell holds while the panel is being edited. Text for most, a list for multiselect, and a
    pair for a range. A lookup holds the chosen option (its typed text lives in the cell), and a
    `multiple` lookup holds the list of chosen options. */
export interface FilterDraft {
  [key: string]: string | readonly string[] | { from: string; to: string } | LookupOption | readonly LookupOption[] | null | undefined;
}

export interface FilterPanelProps {
  fields: readonly FilterField[];
  /** The clauses already applied, to seed the cells. Read when the panel mounts and whenever it changes. */
  value?: readonly FilterClause[] | undefined;
  onApply: (clauses: FilterClause[]) => void;
  /** Called after Clear, which also emits an empty list through onApply. */
  onClear?: (() => void) | undefined;
  /** The name of the form for assistive technology. Default "Filters". */
  label?: string | undefined;
  /** Minimum milliseconds between typing in a lookup and its load. Default 200. */
  debounceMs?: number | undefined;
  className?: string | undefined;
}

/** Pure: the clauses a draft stands for, in field order. Empty cells add nothing. */
export function buildFilters(fields: readonly FilterField[], draft: FilterDraft): FilterClause[] {
  const out: FilterClause[] = [];
  for (const field of fields) {
    const cell = draft[field.key];
    switch (field.type) {
      case 'text': {
        const text = typeof cell === 'string' ? cell.trim() : '';
        if (text) out.push({ key: field.key, op: 'contains', value: text });
        break;
      }
      case 'number':
      case 'date': {
        const range = cell && typeof cell === 'object' && 'from' in cell ? cell : null;
        if (range?.from) out.push({ key: field.key, op: 'gte', value: field.type === 'number' && !Number.isNaN(Number(range.from)) ? Number(range.from) : range.from });
        if (range?.to) out.push({ key: field.key, op: 'lte', value: field.type === 'number' && !Number.isNaN(Number(range.to)) ? Number(range.to) : range.to });
        break;
      }
      case 'select': {
        if (typeof cell === 'string' && cell) out.push({ key: field.key, op: 'eq', value: cell });
        break;
      }
      case 'multiselect': {
        if (Array.isArray(cell) && cell.length > 0) out.push({ key: field.key, op: 'in', value: cell.slice() });
        break;
      }
      case 'boolean': {
        if (cell === 'true' || cell === 'false') out.push({ key: field.key, op: 'eq', value: cell === 'true' });
        break;
      }
      case 'lookup': {
        if (field.multiple) {
          const picked = Array.isArray(cell) ? (cell as readonly LookupOption[]).map((o) => o.value).filter(Boolean) : [];
          if (picked.length > 0) out.push({ key: field.key, op: 'in', value: picked });
          break;
        }
        if (cell && typeof cell === 'object' && 'value' in cell && cell.value) out.push({ key: field.key, op: 'eq', value: cell.value });
        break;
      }
    }
  }
  return out;
}

/** Pure: a draft for the clauses already applied, so reopening a panel shows what is in force. */
export function draftFromFilters(fields: readonly FilterField[], clauses: readonly FilterClause[] = []): FilterDraft {
  const draft: FilterDraft = {};
  for (const field of fields) {
    const mine = clauses.filter((c) => c.key === field.key);
    if (mine.length === 0) continue;
    switch (field.type) {
      case 'text':
        draft[field.key] = String(mine[0]?.value ?? '');
        break;
      case 'number':
      case 'date':
        draft[field.key] = {
          from: String(mine.find((c) => c.op === 'gte')?.value ?? ''),
          to: String(mine.find((c) => c.op === 'lte')?.value ?? ''),
        };
        break;
      case 'select':
        draft[field.key] = String(mine[0]?.value ?? '');
        break;
      case 'boolean':
        draft[field.key] = String(mine[0]?.value ?? '');
        break;
      case 'multiselect': {
        const v = mine[0]?.value;
        draft[field.key] = Array.isArray(v) ? v.map(String) : [];
        break;
      }
      case 'lookup': {
        if (field.multiple) {
          const list = mine[0]?.value;
          const values = Array.isArray(list) ? list.map(String) : list === undefined || list === '' ? [] : [String(list)];
          if (values.length > 0) draft[field.key] = values.map((v) => ({ value: v, label: v }));
          break;
        }
        const v = String(mine[0]?.value ?? '');
        if (v) draft[field.key] = { value: v, label: v };
        break;
      }
    }
  }
  return draft;
}

export function FilterPanel({ fields, value, onApply, onClear, label = 'Filters', debounceMs = 200, className }: FilterPanelProps) {
  const [draft, setDraft] = useState<FilterDraft>(() => draftFromFilters(fields, value));
  const seed = useRef(value);

  useEffect(() => {
    if (seed.current === value) return;
    seed.current = value;
    setDraft(draftFromFilters(fields, value));
  }, [fields, value]);

  const set = useCallback((key: string, next: FilterDraft[string]) => setDraft((d) => ({ ...d, [key]: next })), []);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onApply(buildFilters(fields, draft));
  };

  const clear = () => {
    setDraft({});
    onApply([]);
    onClear?.();
  };

  const filled = useMemo(() => buildFilters(fields, draft).length, [fields, draft]);

  return (
    <form className={cx('filter-panel', className)} aria-label={label} onSubmit={submit} onReset={(e) => e.preventDefault()}>
      <div className="filter-panel-cells">
        {fields.map((field) => (
          <FilterCell key={field.key} field={field} draft={draft[field.key]} onChange={(next) => set(field.key, next)} debounceMs={debounceMs} />
        ))}
      </div>
      <div className="filter-panel-actions">
        <Button type="submit" variant="primary" size="sm">
          Apply
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={clear} disabled={filled === 0 && !value?.length}>
          Clear
        </Button>
      </div>
    </form>
  );
}

interface CellProps {
  field: FilterField;
  draft: FilterDraft[string];
  onChange: (next: FilterDraft[string]) => void;
  debounceMs: number;
}

function FilterCell({ field, draft, onChange, debounceMs }: CellProps) {
  switch (field.type) {
    case 'text':
      return (
        <Field label={field.label}>
          <Input type="text" value={typeof draft === 'string' ? draft : ''} placeholder={field.placeholder} onChange={(e) => onChange(e.target.value)} />
        </Field>
      );
    case 'number':
    case 'date': {
      const range = draft && typeof draft === 'object' && 'from' in draft ? draft : { from: '', to: '' };
      return (
        <fieldset className="filter-range">
          <legend className="field-label">{field.label}</legend>
          <div className="filter-range-pair">
            <Input
              type={field.type}
              aria-label={`${field.label} from`}
              value={range.from}
              onChange={(e) => onChange({ ...range, from: e.target.value })}
            />
            <span className="filter-range-sep" aria-hidden="true">
              to
            </span>
            <Input type={field.type} aria-label={`${field.label} to`} value={range.to} onChange={(e) => onChange({ ...range, to: e.target.value })} />
          </div>
        </fieldset>
      );
    }
    case 'select':
      return (
        <Field label={field.label}>
          <Select value={typeof draft === 'string' ? draft : ''} onChange={(e) => onChange(e.target.value)}>
            <option value="">Any</option>
            {field.options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </Field>
      );
    case 'boolean':
      return (
        <Field label={field.label}>
          <Select value={typeof draft === 'string' ? draft : ''} onChange={(e) => onChange(e.target.value)}>
            <option value="">Any</option>
            <option value="true">{field.trueLabel ?? 'Yes'}</option>
            <option value="false">{field.falseLabel ?? 'No'}</option>
          </Select>
        </Field>
      );
    case 'multiselect': {
      const picked = Array.isArray(draft) ? (draft as readonly string[]) : [];
      return (
        <fieldset className="filter-multi">
          <legend className="field-label">{field.label}</legend>
          <div className="filter-multi-list">
            {field.options.map((o) => (
              <label key={o.value} className="filter-multi-option">
                <input
                  type="checkbox"
                  checked={picked.includes(o.value)}
                  onChange={(e) => onChange(e.target.checked ? [...picked, o.value] : picked.filter((v) => v !== o.value))}
                />
                <span>{o.label}</span>
              </label>
            ))}
          </div>
        </fieldset>
      );
    }
    case 'lookup': {
      if (field.multiple) {
        const list = Array.isArray(draft) ? (draft as readonly LookupOption[]) : [];
        return (
          <Field label={field.label}>
            <LookupCell multiple load={field.load} chosenList={list} onChooseList={onChange} label={field.label} placeholder={field.placeholder} debounceMs={debounceMs} />
          </Field>
        );
      }
      const chosen = draft && typeof draft === 'object' && 'value' in draft ? (draft as LookupOption) : null;
      return (
        <Field label={field.label}>
          <LookupCell load={field.load} chosen={chosen} onChoose={onChange} placeholder={field.placeholder} debounceMs={debounceMs} />
        </Field>
      );
    }
  }
}

type LookupStatus = 'idle' | 'loading' | 'ready' | 'error';

interface LookupCellProps {
  load: LookupLoader;
  chosen?: LookupOption | null;
  onChoose?: (next: LookupOption | null) => void;
  /** Several choices as chips: the chosen list, its setter and the field label for the chip list name. */
  multiple?: boolean;
  chosenList?: readonly LookupOption[];
  onChooseList?: (next: readonly LookupOption[]) => void;
  label?: string;
  placeholder?: string | undefined;
  debounceMs: number;
}

/* The one place a combobox is needed here, kept local and small on purpose: a shared Combobox is
   built separately in the kit, and this cell can move onto it later without changing the panel's
   contract. Only a chosen option counts as a value, so typed text alone never filters. */
function LookupCell({ load, chosen = null, onChoose, multiple = false, chosenList = [], onChooseList, label = '', placeholder, debounceMs }: LookupCellProps) {
  const listId = useId();
  const statusId = useId();
  const [text, setText] = useState(multiple ? '' : (chosen?.label ?? ''));
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<readonly LookupOption[]>([]);
  const [status, setStatus] = useState<LookupStatus>('idle');
  const [active, setActive] = useState(-1);
  const controller = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const chosenLabel = chosen?.label ?? '';

  useEffect(() => {
    if (!multiple) setText(chosenLabel);
  }, [chosenLabel, multiple]);

  useEffect(
    () => () => {
      controller.current?.abort();
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const search = (query: string) => {
    if (timer.current) clearTimeout(timer.current);
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    setStatus('loading');
    timer.current = setTimeout(() => {
      load(query, next.signal).then(
        (result) => {
          if (next.signal.aborted) return;
          setOptions(result);
          setActive(result.length > 0 ? 0 : -1);
          setStatus('ready');
        },
        () => {
          if (next.signal.aborted) return;
          setOptions([]);
          setActive(-1);
          setStatus('error');
        },
      );
    }, debounceMs);
  };

  const pickedValues = useMemo(() => new Set(chosenList.map((o) => o.value)), [chosenList]);
  const shown = multiple ? options.filter((o) => !pickedValues.has(o.value)) : options;
  const inputRef = useRef<HTMLInputElement | null>(null);

  const pick = (option: LookupOption) => {
    if (multiple) {
      if (!pickedValues.has(option.value)) onChooseList?.([...chosenList, option]);
      setText('');
      setActive(0);
      search('');
      return;
    }
    onChoose?.(option);
    setText(option.label);
    setOpen(false);
  };

  const remove = (value: string) => {
    onChooseList?.(chosenList.filter((o) => o.value !== value));
    inputRef.current?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!open) {
        setOpen(true);
        if (status === 'idle') search(text);
        return;
      }
      if (shown.length === 0) return;
      setActive((i) => (e.key === 'ArrowDown' ? (i + 1) % shown.length : (i - 1 + shown.length) % shown.length));
    } else if (e.key === 'Enter') {
      const option = open ? shown[active] : undefined;
      if (option) {
        e.preventDefault();
        pick(option);
      }
    } else if (e.key === 'Backspace' && multiple && text === '' && chosenList.length > 0) {
      e.preventDefault();
      onChooseList?.(chosenList.slice(0, -1));
    } else if (e.key === 'Escape' && open) {
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
    }
  };

  const message =
    status === 'loading' ? 'Loading suggestions' : status === 'error' ? 'Suggestions could not be loaded' : status === 'ready' ? (shown.length === 0 ? 'No matches' : `${shown.length} suggestions`) : '';
  const expanded = open && status !== 'idle';

  return (
    <div className="filter-lookup">
      {multiple && chosenList.length > 0 ? (
        <ul className="filter-lookup-chips" aria-label={`Selected ${label}`}>
          {chosenList.map((o) => (
            <li key={o.value} className="filter-lookup-chip">
              <span className="filter-lookup-chip-label">{o.label}</span>
              <button type="button" className="filter-lookup-chip-remove" aria-label={`Remove ${o.label}`} onClick={() => remove(o.value)}>
                <span aria-hidden="true">x</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <Input
        ref={inputRef}
        type="text"
        role="combobox"
        autoComplete="off"
        aria-autocomplete="list"
        aria-expanded={expanded}
        aria-controls={listId}
        aria-activedescendant={expanded && active >= 0 && active < shown.length ? `${listId}-${active}` : undefined}
        aria-describedby={statusId}
        placeholder={placeholder ?? 'Type to search'}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          if (!multiple && chosen) onChoose?.(null);
          setOpen(true);
          search(e.target.value);
        }}
        onFocus={() => {
          if (status === 'idle') search(text);
          setOpen(true);
        }}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
      />
      <span id={statusId} className="filter-lookup-status" role="status">
        {open ? message : ''}
      </span>
      {expanded ? (
        <ul id={listId} role="listbox" className="filter-lookup-list" aria-label="Suggestions">
          {shown.map((o, i) => (
            <li
              key={o.value}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className="filter-lookup-option"
              data-active={i === active ? '' : undefined}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(o);
              }}
            >
              {o.label}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
