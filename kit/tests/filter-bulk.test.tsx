/* The filter panel (typed cells, lookup, neutral clause list) and the bulk run (useBulkRun with its
   concurrency cap, progress, per-item errors and cancel) with the selection bar that shows it. */
import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { describe, expect, it, vi } from 'vitest';
import { FilterPanel, SelectionBar, buildFilters, clampConcurrency, draftFromFilters, useBulkRun } from '../src';
import type { BulkRunState, FilterClause, FilterField, LookupLoader, LookupOption } from '../src';

async function noAxe(el: Element) {
  const r = await axe.run(el, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
  expect(r.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(' | ')}`)).toEqual([]);
}

const STATUS: LookupOption[] = [
  { value: 'open', label: 'Open' },
  { value: 'closed', label: 'Closed' },
];

const OWNERS: LookupOption[] = [
  { value: 'u1', label: 'Avery' },
  { value: 'u2', label: 'Blake' },
  { value: 'u3', label: 'Avery Stone' },
];

function fields(load: LookupLoader = vi.fn(async (q: string, _signal: AbortSignal) => OWNERS.filter((o) => o.label.toLowerCase().includes(q.toLowerCase())))): FilterField[] {
  return [
    { key: 'name', label: 'Name', type: 'text' },
    { key: 'size', label: 'Size', type: 'number' },
    { key: 'seen', label: 'Last seen', type: 'date' },
    { key: 'status', label: 'Status', type: 'select', options: STATUS },
    { key: 'tags', label: 'Tags', type: 'multiselect', options: [{ value: 'a', label: 'Alpha' }, { value: 'b', label: 'Beta' }] },
    { key: 'managed', label: 'Managed', type: 'boolean' },
    { key: 'owner', label: 'Owner', type: 'lookup', load },
  ];
}

describe('buildFilters and draftFromFilters', () => {
  it('emits one neutral clause per filled cell and nothing for an empty one', () => {
    const f = fields();
    expect(buildFilters(f, {})).toEqual([]);
    expect(
      buildFilters(f, {
        name: '  disk ',
        size: { from: '5', to: '' },
        seen: { from: '2026-01-01', to: '2026-02-01' },
        status: 'open',
        tags: ['a', 'b'],
        managed: 'false',
        owner: { value: 'u1', label: 'Avery' },
      }),
    ).toEqual([
      { key: 'name', op: 'contains', value: 'disk' },
      { key: 'size', op: 'gte', value: 5 },
      { key: 'seen', op: 'gte', value: '2026-01-01' },
      { key: 'seen', op: 'lte', value: '2026-02-01' },
      { key: 'status', op: 'eq', value: 'open' },
      { key: 'tags', op: 'in', value: ['a', 'b'] },
      { key: 'managed', op: 'eq', value: false },
      { key: 'owner', op: 'eq', value: 'u1' },
    ]);
  });

  it('round trips: a draft built from clauses builds the same clauses', () => {
    const f = fields();
    const clauses: FilterClause[] = [
      { key: 'name', op: 'contains', value: 'x' },
      { key: 'size', op: 'lte', value: 9 },
      { key: 'tags', op: 'in', value: ['b'] },
      { key: 'managed', op: 'eq', value: true },
      { key: 'owner', op: 'eq', value: 'u2' },
    ];
    expect(buildFilters(f, draftFromFilters(f, clauses))).toEqual(clauses);
  });
});

describe('FilterPanel', () => {
  it('names the form and gives every cell a label, with a labelled group for each range', async () => {
    const { container } = render(<FilterPanel fields={fields()} onApply={() => undefined} />);
    expect(screen.getByRole('form', { name: 'Filters' })).toBeTruthy();
    for (const name of ['Name', 'Status', 'Managed', 'Owner']) expect(screen.getByLabelText(name)).toBeTruthy();
    expect(screen.getByRole('group', { name: 'Size' })).toBeTruthy();
    expect(screen.getByLabelText('Size from')).toBeTruthy();
    expect(screen.getByLabelText('Last seen to')).toBeTruthy();
    expect(screen.getByRole('group', { name: 'Tags' })).toBeTruthy();
    expect(screen.getByRole('checkbox', { name: 'Alpha' })).toBeTruthy();
    expect(screen.getByRole('combobox', { name: 'Owner' }).getAttribute('aria-autocomplete')).toBe('list');
    await noAxe(container);
  });

  it('applies the neutral clause list from every cell type', async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(<FilterPanel fields={fields()} onApply={onApply} debounceMs={0} />);
    await user.type(screen.getByLabelText('Name'), 'disk');
    await user.type(screen.getByLabelText('Size from'), '5');
    await user.type(screen.getByLabelText('Size to'), '9');
    fireEvent.change(screen.getByLabelText('Last seen from'), { target: { value: '2026-01-02' } });
    await user.selectOptions(screen.getByLabelText('Status'), 'closed');
    await user.click(screen.getByRole('checkbox', { name: 'Beta' }));
    await user.selectOptions(screen.getByLabelText('Managed'), 'true');
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply.mock.calls[0]?.[0]).toEqual([
      { key: 'name', op: 'contains', value: 'disk' },
      { key: 'size', op: 'gte', value: 5 },
      { key: 'size', op: 'lte', value: 9 },
      { key: 'seen', op: 'gte', value: '2026-01-02' },
      { key: 'status', op: 'eq', value: 'closed' },
      { key: 'tags', op: 'in', value: ['b'] },
      { key: 'managed', op: 'eq', value: true },
    ]);
  });

  it('applies with Enter from a text cell and Clear empties every cell and emits an empty list', async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    const onClear = vi.fn();
    render(<FilterPanel fields={fields()} onApply={onApply} onClear={onClear} />);
    await user.type(screen.getByLabelText('Name'), 'abc{Enter}');
    expect(onApply).toHaveBeenLastCalledWith([{ key: 'name', op: 'contains', value: 'abc' }]);
    await user.click(screen.getByRole('button', { name: 'Clear' }));
    expect(onApply).toHaveBeenLastCalledWith([]);
    expect(onClear).toHaveBeenCalledTimes(1);
    expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('');
  });

  it('seeds the cells from the applied clauses and follows a changed value', () => {
    const f = fields();
    const { rerender } = render(<FilterPanel fields={f} value={[{ key: 'status', op: 'eq', value: 'open' }]} onApply={() => undefined} />);
    expect((screen.getByLabelText('Status') as HTMLSelectElement).value).toBe('open');
    rerender(<FilterPanel fields={f} value={[{ key: 'name', op: 'contains', value: 'zz' }]} onApply={() => undefined} />);
    expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('zz');
    expect((screen.getByLabelText('Status') as HTMLSelectElement).value).toBe('');
  });

  describe('lookup cell', () => {
    it('loads suggestions for the typed text with an abort signal and picks with the keyboard', async () => {
      const user = userEvent.setup();
      const load = vi.fn(async (q: string, _signal: AbortSignal) => OWNERS.filter((o) => o.label.toLowerCase().includes(q.toLowerCase())));
      const onApply = vi.fn();
      const { container } = render(<FilterPanel fields={fields(load)} onApply={onApply} debounceMs={0} />);
      const box = screen.getByRole('combobox', { name: 'Owner' });
      await user.type(box, 'ave');
      const list = await screen.findByRole('listbox');
      await waitFor(() => expect(within(list).getAllByRole('option')).toHaveLength(2));
      expect(load.mock.calls.at(-1)?.[0]).toBe('ave');
      expect(load.mock.calls.at(-1)?.[1]).toBeInstanceOf(AbortSignal);
      expect(box.getAttribute('aria-expanded')).toBe('true');
      expect(box.getAttribute('aria-controls')).toBe(list.id);
      const options = within(list).getAllByRole('option');
      expect(box.getAttribute('aria-activedescendant')).toBe(options[0]?.id);
      expect(options[0]?.getAttribute('aria-selected')).toBe('true');
      await noAxe(container);
      await user.keyboard('{ArrowDown}');
      expect(box.getAttribute('aria-activedescendant')).toBe(options[1]?.id);
      await user.keyboard('{Enter}');
      expect(screen.queryByRole('listbox')).toBeNull();
      expect((box as HTMLInputElement).value).toBe('Avery Stone');
      await user.click(screen.getByRole('button', { name: 'Apply' }));
      expect(onApply).toHaveBeenLastCalledWith([{ key: 'owner', op: 'eq', value: 'u3' }]);
    });

    it('typed text alone is not a value, and editing a chosen option drops it', async () => {
      const user = userEvent.setup();
      const onApply = vi.fn();
      render(<FilterPanel fields={fields()} onApply={onApply} debounceMs={0} />);
      const box = screen.getByRole('combobox', { name: 'Owner' });
      await user.type(box, 'bla');
      await user.click(await screen.findByRole('option', { name: 'Blake' }));
      await user.click(screen.getByRole('button', { name: 'Apply' }));
      expect(onApply).toHaveBeenLastCalledWith([{ key: 'owner', op: 'eq', value: 'u2' }]);
      await user.type(box, 'x');
      await user.click(screen.getByRole('button', { name: 'Apply' }));
      expect(onApply).toHaveBeenLastCalledWith([]);
    });

    it('closes on Escape and ignores a slow answer to an older query', async () => {
      const user = userEvent.setup();
      const pending: Record<string, (v: LookupOption[]) => void> = {};
      const load = vi.fn((q: string) => new Promise<LookupOption[]>((resolve) => (pending[q] = resolve)));
      render(<FilterPanel fields={fields(load)} onApply={() => undefined} debounceMs={0} />);
      const box = screen.getByRole('combobox', { name: 'Owner' });
      await user.type(box, 'a');
      await waitFor(() => expect(pending['a']).toBeTypeOf('function'));
      await user.type(box, 'b');
      await waitFor(() => expect(pending['ab']).toBeTypeOf('function'));
      await act(async () => {
        pending['ab']?.([{ value: 'new', label: 'Fresh' }]);
      });
      await act(async () => {
        pending['a']?.([{ value: 'old', label: 'Stale' }]);
      });
      expect(screen.getByRole('option', { name: 'Fresh' })).toBeTruthy();
      expect(screen.queryByRole('option', { name: 'Stale' })).toBeNull();
      await user.keyboard('{Escape}');
      expect(screen.queryByRole('listbox')).toBeNull();
      expect(box.getAttribute('aria-expanded')).toBe('false');
    });

    it('says so when the loader fails or finds nothing, and never throws', async () => {
      const user = userEvent.setup();
      const load = vi.fn(async (q: string, _signal: AbortSignal): Promise<LookupOption[]> => {
        if (q === 'q') throw new Error('down');
        return [];
      });
      render(<FilterPanel fields={fields(load)} onApply={() => undefined} debounceMs={0} />);
      const box = screen.getByRole('combobox', { name: 'Owner' });
      await user.type(box, 'q');
      await waitFor(() => expect(screen.getByRole('status').textContent).toContain('could not be loaded'));
      await user.type(box, 'r');
      await waitFor(() => expect(screen.getByRole('status').textContent).toBe('No matches'));
    });
  });

  describe('multiple lookup cell', () => {
    const multi = (load?: LookupLoader): FilterField[] => [{ key: 'owners', label: 'Owners', type: 'lookup', multiple: true, load: load ?? (async (q: string) => OWNERS.filter((o) => o.label.toLowerCase().includes(q.toLowerCase()))) }];

    it('buildFilters emits one in clause for the chosen options and none when empty', () => {
      const f = multi();
      expect(buildFilters(f, { owners: [OWNERS[0]!, OWNERS[1]!] })).toEqual([{ key: 'owners', op: 'in', value: ['u1', 'u2'] }]);
      expect(buildFilters(f, { owners: [] })).toEqual([]);
      expect(buildFilters(f, {})).toEqual([]);
    });

    it('draftFromFilters seeds chips from an in clause and from a single value', () => {
      const f = multi();
      expect(draftFromFilters(f, [{ key: 'owners', op: 'in', value: ['u1', 'u2'] }])).toEqual({
        owners: [
          { value: 'u1', label: 'u1' },
          { value: 'u2', label: 'u2' },
        ],
      });
      expect(draftFromFilters(f, [{ key: 'owners', op: 'eq', value: 'u3' }])).toEqual({ owners: [{ value: 'u3', label: 'u3' }] });
    });

    it('keeps several choices as chips, hides chosen options and applies one in clause', async () => {
      const user = userEvent.setup();
      const onApply = vi.fn();
      const { container } = render(<FilterPanel fields={multi()} onApply={onApply} debounceMs={0} />);
      const box = screen.getByRole('combobox', { name: 'Owners' });
      await user.type(box, 'ave');
      await user.click(await screen.findByRole('option', { name: 'Avery' }));
      expect((box as HTMLInputElement).value).toBe('');
      const chips = screen.getByRole('list', { name: 'Selected Owners' });
      expect(within(chips).getAllByRole('listitem')).toHaveLength(1);
      await user.type(box, 'ave');
      await waitFor(() => expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Avery Stone']));
      await user.keyboard('{Enter}');
      expect(within(screen.getByRole('list', { name: 'Selected Owners' })).getAllByRole('listitem')).toHaveLength(2);
      await noAxe(container);
      await user.click(screen.getByRole('button', { name: 'Apply' }));
      expect(onApply).toHaveBeenLastCalledWith([{ key: 'owners', op: 'in', value: ['u1', 'u3'] }]);
    });

    it('removes a chip with its button or Backspace on an empty input, and typed text alone is not a value', async () => {
      const user = userEvent.setup();
      const onApply = vi.fn();
      render(<FilterPanel fields={multi()} value={[{ key: 'owners', op: 'in', value: ['u1', 'u2'] }]} onApply={onApply} debounceMs={0} />);
      await user.click(screen.getByRole('button', { name: 'Remove u1' }));
      expect(screen.queryByRole('button', { name: 'Remove u1' })).toBeNull();
      const box = screen.getByRole('combobox', { name: 'Owners' });
      expect(document.activeElement).toBe(box);
      await user.type(box, 'zz');
      await user.keyboard('{Backspace}{Backspace}');
      expect(screen.getByRole('button', { name: 'Remove u2' })).toBeTruthy();
      await user.keyboard('{Backspace}');
      expect(screen.queryByRole('list', { name: 'Selected Owners' })).toBeNull();
      await user.type(box, 'bl');
      await user.click(screen.getByRole('button', { name: 'Apply' }));
      expect(onApply).toHaveBeenLastCalledWith([]);
    });

    it('keeps the loader signal, Escape and the failure message as in the single cell', async () => {
      const user = userEvent.setup();
      const load = vi.fn(async (q: string, _signal: AbortSignal): Promise<LookupOption[]> => {
        if (q === 'q') throw new Error('down');
        return OWNERS;
      });
      render(<FilterPanel fields={multi(load)} onApply={() => undefined} debounceMs={0} />);
      const box = screen.getByRole('combobox', { name: 'Owners' });
      await user.type(box, 'a');
      await screen.findByRole('listbox');
      expect(load.mock.calls.at(-1)?.[1]).toBeInstanceOf(AbortSignal);
      await user.keyboard('{Escape}');
      expect(screen.queryByRole('listbox')).toBeNull();
      await user.clear(box);
      await user.type(box, 'q');
      await waitFor(() => expect(screen.getByRole('status').textContent).toContain('could not be loaded'));
    });

    it('a single lookup is unchanged when multiple is off', () => {
      expect(buildFilters(fields(), { owner: { value: 'u2', label: 'Blake' } })).toEqual([{ key: 'owner', op: 'eq', value: 'u2' }]);
    });
  });
});

/* ---- bulk run ---- */

interface Gate {
  active: number;
  peak: number;
  started: number[];
  signals: AbortSignal[];
  release: (n: number, error?: Error) => void;
  task: (item: number, signal: AbortSignal) => Promise<void>;
}

/** A task that stays in flight until the test releases it, recording the most ever in flight. */
function gate(): Gate {
  const waiting = new Map<number, { ok: () => void; fail: (e: Error) => void }>();
  const g: Gate = {
    active: 0,
    peak: 0,
    started: [],
    signals: [],
    release: (n, error) => {
      const w = waiting.get(n);
      waiting.delete(n);
      if (error) w?.fail(error);
      else w?.ok();
    },
    task: (item, signal) => {
      g.active += 1;
      g.peak = Math.max(g.peak, g.active);
      g.started.push(item);
      g.signals.push(signal);
      return new Promise<void>((resolve, reject) => {
        waiting.set(item, {
          ok: () => {
            g.active -= 1;
            resolve();
          },
          fail: (e) => {
            g.active -= 1;
            reject(e);
          },
        });
      });
    },
  };
  return g;
}

const range = (n: number) => Array.from({ length: n }, (_, i) => i);

describe('clampConcurrency', () => {
  it('is a whole number from 1 and falls back to the default for junk', () => {
    expect(clampConcurrency(3)).toBe(3);
    expect(clampConcurrency(2.9)).toBe(2);
    expect(clampConcurrency(0)).toBe(1);
    expect(clampConcurrency(-5)).toBe(1);
    expect(clampConcurrency(Number.NaN)).toBe(4);
    expect(clampConcurrency(Number.POSITIVE_INFINITY)).toBe(4);
    expect(clampConcurrency(undefined)).toBe(4);
  });
});

describe('useBulkRun', () => {
  it('never has more tasks in flight than the cap, and starts the next as one finishes', async () => {
    const g = gate();
    const seen: BulkRunState[] = [];
    const { result } = renderHook(() => {
      const r = useBulkRun<number>(g.task, { concurrency: 3 });
      seen.push(r.state);
      return r;
    });
    let promise!: Promise<unknown>;
    act(() => {
      promise = result.current.run(range(10));
    });
    expect(g.started).toEqual([0, 1, 2]);
    expect(g.active).toBe(3);
    for (let n = 0; n < 10; n += 1) {
      await act(async () => {
        g.release(n);
        await Promise.resolve();
      });
      expect(g.active).toBeLessThanOrEqual(3);
    }
    await act(async () => {
      await promise;
    });
    expect(g.peak).toBe(3);
    expect(Math.max(...seen.map((s) => s.active))).toBeLessThanOrEqual(3);
    expect(g.started).toEqual(range(10));
    expect(result.current.state).toMatchObject({ status: 'done', total: 10, done: 10, succeeded: 10, failed: 0, active: 0 });
  });

  it.each([1, 2, 5, 50])('holds the cap with concurrency %i over 40 items that finish at random times', async (cap) => {
    let active = 0;
    let peak = 0;
    const task = async (item: number) => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((r) => setTimeout(r, (item * 7) % 5));
      active -= 1;
    };
    const { result } = renderHook(() => useBulkRun<number>(task, { concurrency: cap }));
    let out!: Awaited<ReturnType<typeof result.current.run>>;
    await act(async () => {
      out = await result.current.run(range(40));
    });
    expect(peak).toBeLessThanOrEqual(cap);
    expect(peak).toBe(Math.min(cap, 40));
    expect(out).toMatchObject({ status: 'done', total: 40, succeeded: 40, failed: 0, skipped: 0 });
  });

  it('defaults the cap to 4 and runs a short list wholly in parallel', async () => {
    const g = gate();
    const { result } = renderHook(() => useBulkRun<number>(g.task));
    act(() => {
      void result.current.run(range(9));
    });
    expect(g.active).toBe(4);
    const short = gate();
    const second = renderHook(() => useBulkRun<number>(short.task, { concurrency: 10 }));
    act(() => {
      void second.result.current.run(range(3));
    });
    expect(short.active).toBe(3);
  });

  it('reports progress as items finish', async () => {
    const g = gate();
    const { result } = renderHook(() => useBulkRun<number>(g.task, { concurrency: 2 }));
    act(() => {
      void result.current.run(range(4));
    });
    expect(result.current.state).toMatchObject({ status: 'running', total: 4, done: 0, active: 2 });
    await act(async () => {
      g.release(0);
      await Promise.resolve();
    });
    expect(result.current.state).toMatchObject({ done: 1, succeeded: 1, active: 2 });
  });

  it('keeps going after a failure and lists every failed item with its key and message', async () => {
    const task = async (item: number) => {
      if (item % 2 === 1) throw new Error(`item ${item} refused`);
      if (item === 4) throw 'plain text';
      if (item === 6) throw {};
    };
    const { result } = renderHook(() => useBulkRun<number>(task, { concurrency: 2, itemKey: (n) => `row-${n}` }));
    let out!: Awaited<ReturnType<typeof result.current.run>>;
    await act(async () => {
      out = await result.current.run(range(8));
    });
    expect(out.succeeded).toBe(2);
    expect(out.failed).toBe(6);
    expect(out.errors.map((e) => [e.key, e.index, e.message]).sort()).toEqual([
      ['row-1', 1, 'item 1 refused'],
      ['row-3', 3, 'item 3 refused'],
      ['row-4', 4, 'plain text'],
      ['row-5', 5, 'item 5 refused'],
      ['row-6', 6, 'The action failed'],
      ['row-7', 7, 'item 7 refused'],
    ].sort());
    expect(result.current.state).toMatchObject({ status: 'done', done: 8, failed: 6 });
    expect(result.current.state.errors).toHaveLength(6);
  });

  it('turns a task that throws before returning a promise into an item error', async () => {
    const task = (item: number): Promise<void> => {
      if (item === 1) throw new Error('sync boom');
      return Promise.resolve();
    };
    const { result } = renderHook(() => useBulkRun<number>(task));
    await act(async () => {
      await result.current.run([0, 1, 2]);
    });
    expect(result.current.state).toMatchObject({ succeeded: 2, failed: 1 });
    expect(result.current.state.errors[0]?.message).toBe('sync boom');
  });

  it('cancel aborts the signals, starts nothing more, and settles as cancelled once in flight tasks end', async () => {
    const g = gate();
    const { result } = renderHook(() => useBulkRun<number>(g.task, { concurrency: 2 }));
    let promise!: Promise<Awaited<ReturnType<typeof result.current.run>>>;
    act(() => {
      promise = result.current.run(range(6));
    });
    act(() => {
      result.current.cancel();
    });
    expect(g.signals.every((s) => s.aborted)).toBe(true);
    expect(result.current.state.status).toBe('running');
    let out: unknown;
    await act(async () => {
      g.release(0);
      g.release(1);
      out = await promise;
    });
    expect(g.started).toEqual([0, 1]);
    expect(out).toMatchObject({ status: 'cancelled', skipped: 4 });
    expect(result.current.state).toMatchObject({ status: 'cancelled', total: 6, done: 2, active: 0 });
  });

  it('resolves a cancelled run with the skipped count', async () => {
    const g = gate();
    const { result } = renderHook(() => useBulkRun<number>(g.task, { concurrency: 1 }));
    let out: unknown;
    act(() => {
      void result.current.run(range(5)).then((r) => (out = r));
    });
    act(() => {
      result.current.cancel();
    });
    await act(async () => {
      g.release(0);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(out).toMatchObject({ status: 'cancelled', total: 5, succeeded: 1, skipped: 4 });
  });

  it('refuses a second run while one is active and allows a new run after it settles', async () => {
    const g = gate();
    const { result } = renderHook(() => useBulkRun<number>(g.task, { concurrency: 2 }));
    let first!: Promise<unknown>;
    let again!: Promise<unknown>;
    act(() => {
      first = result.current.run([0, 1]);
      again = result.current.run([5, 6, 7]);
    });
    expect(again).toBe(first);
    expect(g.started).toEqual([0, 1]);
    await act(async () => {
      g.release(0);
      g.release(1);
      await first;
    });
    act(() => {
      void result.current.run([9]);
    });
    expect(g.started).toEqual([0, 1, 9]);
    act(() => {
      result.current.reset();
    });
    expect(result.current.state.status).toBe('running');
  });

  it('reset returns to idle once settled, and an empty list settles at once', async () => {
    const { result } = renderHook(() => useBulkRun<number>(async () => undefined));
    await act(async () => {
      await result.current.run([]);
    });
    expect(result.current.state).toMatchObject({ status: 'done', total: 0, done: 0 });
    act(() => {
      result.current.reset();
    });
    expect(result.current.state.status).toBe('idle');
  });

  it('aborts in flight tasks on unmount and does not update state after it', async () => {
    const g = gate();
    const errors = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { result, unmount } = renderHook(() => useBulkRun<number>(g.task, { concurrency: 2 }));
    act(() => {
      void result.current.run(range(4));
    });
    unmount();
    expect(g.signals.every((s) => s.aborted)).toBe(true);
    await Promise.resolve();
    g.release(0);
    g.release(1);
    await new Promise((r) => setTimeout(r, 0));
    expect(g.started).toEqual([0, 1]);
    expect(errors).not.toHaveBeenCalled();
    errors.mockRestore();
  });
});

describe('SelectionBar with a bulk run', () => {
  const idle: BulkRunState = { status: 'idle', total: 0, done: 0, succeeded: 0, failed: 0, active: 0, errors: [] };

  it('shows nothing extra while idle and still renders nothing at zero', () => {
    const { container, rerender } = render(<SelectionBar count={2} onClear={() => undefined} actions={[]} run={idle} />);
    expect(screen.queryByRole('progressbar')).toBeNull();
    rerender(<SelectionBar count={0} onClear={() => undefined} actions={[]} run={{ ...idle, status: 'running', total: 3 }} />);
    expect(container.firstChild).toBeNull();
  });

  it('shows a named progress bar, a Cancel button and locks Clear while running', async () => {
    const onCancel = vi.fn();
    const run: BulkRunState = { ...idle, status: 'running', total: 4, done: 1, active: 2 };
    const { container } = render(<SelectionBar count={4} onClear={() => undefined} actions={[]} run={run} onCancel={onCancel} itemNoun="devices" />);
    const bar = screen.getByRole('progressbar');
    expect(bar.getAttribute('aria-valuenow')).toBe('1');
    expect(bar.getAttribute('aria-valuemax')).toBe('4');
    expect(bar.getAttribute('aria-label')).toContain('1 of 4 devices processed');
    expect(screen.getByRole('status').textContent).toBe('1 of 4 devices processed');
    expect((screen.getByRole('button', { name: 'Clear selection' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    await noAxe(container);
  });

  it('lists the per-item errors after the run and drops Cancel', async () => {
    const run: BulkRunState = {
      ...idle,
      status: 'done',
      total: 3,
      done: 3,
      succeeded: 1,
      failed: 2,
      errors: [
        { key: 'row-1', index: 0, message: 'Refused' },
        { key: 'row-2', index: 1, message: 'Timed out' },
      ],
    };
    const { container } = render(<SelectionBar count={3} onClear={() => undefined} actions={[]} run={run} onCancel={() => undefined} />);
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();
    expect(screen.getByRole('status').textContent).toBe('Finished 3 of 3 items, 2 failed');
    const list = screen.getByRole('list', { name: 'Failed items' });
    expect(within(list).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['row-1Refused', 'row-2Timed out']);
    expect((screen.getByRole('button', { name: 'Clear selection' }) as HTMLButtonElement).disabled).toBe(false);
    await noAxe(container);
  });

  it('names the landmark so several bars can share a page', () => {
    render(<SelectionBar count={1} onClear={() => undefined} actions={[]} name="Selection, devices" />);
    expect(screen.getByRole('region', { name: 'Selection, devices' })).toBeTruthy();
  });

  it('says cancelled when the run was cancelled', () => {
    render(<SelectionBar count={5} onClear={() => undefined} actions={[]} run={{ ...idle, status: 'cancelled', total: 5, done: 2 }} />);
    expect(screen.getByRole('status').textContent).toBe('Cancelled after 2 of 5 items');
  });
});
