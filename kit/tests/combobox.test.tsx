import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Combobox, Field, Modal, PersonOption, UnavailableError, isUnavailableError } from '../src/index';
import type { ComboboxFreeEntry, PersonOptionData } from '../src/index';

interface Person extends PersonOptionData {
  id: string;
}

const PEOPLE: Person[] = [
  { id: 'p1', name: 'Avery Stone', detail: 'Platform team', meta: 'Designer' },
  { id: 'p2', name: 'Avery Lin', detail: 'Support team' },
  { id: 'p3', name: 'Sam Lee', detail: 'Field team', meta: 'Lead' },
];

/** A lookup over PEOPLE that honours the abort signal like fetch does. */
function lookup() {
  return vi.fn(
    (query: string, signal: AbortSignal) =>
      new Promise<readonly Person[]>((resolve, reject) => {
        const timer = setTimeout(() => resolve(PEOPLE.filter((p) => p.name.toLowerCase().includes(query.toLowerCase()))), 0);
        signal.addEventListener('abort', () => {
          clearTimeout(timer);
          reject(new DOMException('aborted', 'AbortError'));
        });
      }),
  );
}

interface PickerProps {
  search: (query: string, signal: AbortSignal) => Promise<readonly Person[]>;
  onSelect?: (p: Person) => void;
  clearOnSelect?: boolean;
  excludeKeys?: readonly string[];
  onSearchError?: (error: unknown) => void;
}

/** The person picker usage: Avatar rows through the row slot. */
function PersonPicker({ search, onSelect, ...rest }: PickerProps) {
  return (
    <Combobox<Person>
      label="Find a person"
      placeholder="Search people"
      debounceMs={20}
      search={search}
      onSelect={onSelect ?? (() => undefined)}
      getKey={(p) => p.id}
      getLabel={(p) => p.name}
      renderOption={(p) => <PersonOption person={p} />}
      {...rest}
    />
  );
}

afterEach(() => {
  vi.useRealTimers();
});

describe('Combobox', () => {
  it('has the combobox roles inside a Field and finds nothing for axe to flag', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <Field label="Owner">
        <PersonPicker search={lookup()} />
      </Field>,
    );
    const input = screen.getByRole('combobox', { name: 'Owner' });
    expect(input.getAttribute('aria-expanded')).toBe('false');
    expect(input.getAttribute('aria-autocomplete')).toBe('list');
    await user.type(input, 'av');
    const list = await screen.findByRole('listbox');
    expect(input.getAttribute('aria-expanded')).toBe('true');
    expect(input.getAttribute('aria-controls')).toBe(list.id);
    expect(screen.getAllByRole('option')).toHaveLength(2);
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } }, resultTypes: ['violations'] });
    expect(result.violations.map((v) => v.id)).toEqual([]);
  });

  it('waits for the debounce and never searches below the minimum', async () => {
    const search = lookup();
    render(<PersonPicker search={search} />);
    const input = screen.getByRole('combobox');
    fireEvent.change(input, { target: { value: 'a' } });
    await new Promise((r) => setTimeout(r, 60));
    expect(search).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: 'av' } });
    fireEvent.change(input, { target: { value: 'ave' } });
    fireEvent.change(input, { target: { value: 'aver' } });
    await screen.findAllByRole('option');
    expect(search).toHaveBeenCalledTimes(1);
    expect(search.mock.calls[0]?.[0]).toBe('aver');
  });

  it('aborts a stale lookup and drops its late reply', async () => {
    let first: AbortSignal | undefined;
    const resolvers: Array<(v: readonly Person[]) => void> = [];
    const search = vi.fn((query: string, signal: AbortSignal) => {
      if (query === 'av') first = signal;
      return new Promise<readonly Person[]>((resolve) => resolvers.push(resolve));
    });
    render(<PersonPicker search={search} />);
    const input = screen.getByRole('combobox');
    fireEvent.change(input, { target: { value: 'av' } });
    await waitFor(() => expect(search).toHaveBeenCalledTimes(1));
    fireEvent.change(input, { target: { value: 'jo' } });
    await waitFor(() => expect(search).toHaveBeenCalledTimes(2));
    expect(first?.aborted).toBe(true);
    // The newer reply lands, then the older one arrives late and must not replace it.
    await act(async () => {
      resolvers[1]?.([PEOPLE[2] as Person]);
    });
    await act(async () => {
      resolvers[0]?.([PEOPLE[0] as Person]);
    });
    expect(screen.getAllByRole('option').map((r) => r.getAttribute('aria-label'))).toEqual(['Sam Lee']);
  });

  it('shows loading, then empty, then an error whose retry runs the lookup again', async () => {
    let fail = true;
    const search = vi.fn(async (query: string) => {
      if (query === 'zz') return [] as Person[];
      if (fail) throw new Error('down');
      return [PEOPLE[0] as Person];
    });
    const user = userEvent.setup();
    render(<PersonPicker search={search} />);
    const input = screen.getByRole('combobox');
    expect(screen.queryByText('Searching...')).toBeNull();
    fireEvent.change(input, { target: { value: 'zz' } });
    expect(screen.getAllByText('Searching...').length).toBeGreaterThan(0);
    expect((await screen.findAllByText('No matches for "zz"')).length).toBeGreaterThan(0);

    fireEvent.change(input, { target: { value: 'av' } });
    expect((await screen.findAllByText('Search failed.')).length).toBeGreaterThan(0);
    fail = false;
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('option', { name: 'Avery Stone' })).toBeTruthy();
  });

  it('reports a lookup error to onSearchError', async () => {
    const boom = new Error('boom');
    const onSearchError = vi.fn();
    render(<PersonPicker search={async () => { throw boom; }} onSearchError={onSearchError} />);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'ab' } });
    await waitFor(() => expect(onSearchError).toHaveBeenCalledWith(boom));
  });

  it('follows the ARIA keyboard pattern: arrows wrap, Enter picks, focus stays in the input', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<PersonPicker search={lookup()} onSelect={onSelect} />);
    const input = screen.getByRole('combobox');
    await user.type(input, 'av');
    const rows = await screen.findAllByRole('option');
    expect(rows[0]?.getAttribute('aria-selected')).toBe('true');
    expect(input.getAttribute('aria-activedescendant')).toBe(rows[0]?.id);
    await user.keyboard('{ArrowDown}');
    expect(input.getAttribute('aria-activedescendant')).toBe(rows[1]?.id);
    await user.keyboard('{ArrowDown}');
    expect(input.getAttribute('aria-activedescendant')).toBe(rows[0]?.id);
    await user.keyboard('{ArrowUp}');
    expect(input.getAttribute('aria-activedescendant')).toBe(rows[1]?.id);
    expect(document.activeElement).toBe(input);
    await user.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalledWith(PEOPLE[1]);
    expect(screen.queryByRole('listbox')).toBeNull();
    expect((input as HTMLInputElement).value).toBe('Avery Lin');
    // The label now in the input is not searched again.
    await new Promise((r) => setTimeout(r, 60));
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  it('picks with the pointer and empties the input when clearOnSelect is set', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<PersonPicker search={lookup()} onSelect={onSelect} clearOnSelect />);
    await user.type(screen.getByRole('combobox'), 'jo');
    await user.click(await screen.findByRole('option', { name: 'Sam Lee' }));
    expect(onSelect).toHaveBeenCalledWith(PEOPLE[2]);
    expect((screen.getByRole('combobox') as HTMLInputElement).value).toBe('');
  });

  it('leaves out excluded keys', async () => {
    const user = userEvent.setup();
    render(<PersonPicker search={lookup()} excludeKeys={['p1']} />);
    await user.type(screen.getByRole('combobox'), 'av');
    expect((await screen.findAllByRole('option')).map((r) => r.getAttribute('aria-label'))).toEqual(['Avery Lin']);
  });

  it('renders the row slot as a person: Avatar, detail and meta', async () => {
    const user = userEvent.setup();
    render(<PersonPicker search={lookup()} />);
    await user.type(screen.getByRole('combobox'), 'Sam');
    const row = await screen.findByRole('option', { name: 'Sam Lee' });
    expect(row.querySelector('.avatar')).not.toBeNull();
    expect(row.textContent).toContain('Field team');
    expect(row.textContent).toContain('Lead');
  });

  it('closes on an outside press', async () => {
    const user = userEvent.setup();
    render(
      <>
        <PersonPicker search={lookup()} />
        <button type="button">Elsewhere</button>
      </>,
    );
    await user.type(screen.getByRole('combobox'), 'av');
    await screen.findByRole('listbox');
    await user.click(screen.getByRole('button', { name: 'Elsewhere' }));
    expect(screen.queryByRole('listbox')).toBeNull();
  });
});

describe('Combobox Escape inside a dialog', () => {
  it('closes the list first and keeps the dialog open, then the second Escape closes the dialog', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="Editor">
        <PersonPicker search={lookup()} />
      </Modal>,
    );
    const input = screen.getByRole('combobox');
    await user.type(input, 'av');
    await screen.findByRole('listbox');

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog', { name: 'Editor' })).toBeTruthy();
    expect(document.activeElement).toBe(input);

    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('Combobox free entry fallback (unavailable state)', () => {
  const down = () => vi.fn(async (): Promise<readonly Person[]> => { throw new UnavailableError(); });
  const looksLikeCode = (text: string) => (/^[A-Z]{2}-\d{3}$/.test(text) ? null : 'Enter a code like AB-123.');

  function FreePicker({ search, onSelect, ...rest }: { search: PickerProps['search']; onSelect: (v: Person | ComboboxFreeEntry) => void } & Partial<React.ComponentProps<typeof Combobox<Person, ComboboxFreeEntry>>>) {
    return (
      <Combobox<Person, ComboboxFreeEntry>
        label="Find a person"
        placeholder="Search people"
        debounceMs={5}
        search={search}
        onSelect={onSelect}
        getKey={(p) => p.id}
        getLabel={(p) => p.name}
        validate={looksLikeCode}
        {...rest}
      />
    );
  }

  it('marks UnavailableError and any object with unavailable true', () => {
    expect(isUnavailableError(new UnavailableError())).toBe(true);
    expect(isUnavailableError(Object.assign(new Error('x'), { unavailable: true }))).toBe(true);
    expect(isUnavailableError(new Error('x'))).toBe(false);
    expect(isUnavailableError(null)).toBe(false);
  });

  it('enters free entry on an UnavailableError: no list, a hint, a plain text input, no further lookups', async () => {
    const search = down();
    render(<FreePicker search={search} onSelect={() => undefined} validate={undefined} />);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'av' } });
    const input = await screen.findByRole('textbox', { name: 'Find a person' });
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(input.getAttribute('aria-expanded')).toBeNull();
    expect(screen.getAllByText('Search is unavailable. Type a full entry and press Enter.').length).toBeGreaterThan(0);
    expect(input.getAttribute('aria-describedby')).toBe(document.querySelector('.combobox-hint')?.id);
    fireEvent.change(input, { target: { value: 'avery' } });
    await new Promise((r) => setTimeout(r, 40));
    expect(search).toHaveBeenCalledTimes(1);
  });

  it('enters free entry when onSearchError returns unavailable and still reports the error', async () => {
    const onSearchError = vi.fn(() => 'unavailable' as const);
    const search = vi.fn(async (): Promise<readonly Person[]> => { throw new Error('501'); });
    render(<FreePicker search={search} onSelect={() => undefined} onSearchError={onSearchError} />);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'av' } });
    await screen.findByRole('textbox');
    expect(onSearchError).toHaveBeenCalledTimes(1);
  });

  it('keeps the retry state for an unmarked error when onSearchError returns nothing', async () => {
    const search = vi.fn(async (): Promise<readonly Person[]> => { throw new Error('boom'); });
    render(<FreePicker search={search} onSelect={() => undefined} onSearchError={() => undefined} />);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'av' } });
    expect((await screen.findAllByText('Search failed.')).length).toBeGreaterThan(0);
    expect(screen.getByRole('combobox')).toBeTruthy();
  });

  it('Enter adds { free: text } through onSelect once validate accepts, and an invalid text shows its message', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<FreePicker search={down()} onSelect={onSelect} defaultUnavailable />);
    const input = screen.getByRole('textbox', { name: 'Find a person' });
    await user.type(input, 'someone{Enter}');
    expect(onSelect).not.toHaveBeenCalled();
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect(document.querySelector('.combobox-hint')?.textContent).toBe('Enter a code like AB-123.');
    expect(document.querySelector('.combobox-hint')?.getAttribute('data-tone')).toBe('danger');
    await user.clear(input);
    await user.type(input, 'AB-123{Enter}');
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith({ free: 'AB-123' });
    expect(input.getAttribute('aria-invalid')).toBeNull();
    expect((input as HTMLInputElement).value).toBe('AB-123');
  });

  it('accepts any non-empty text without validate, ignores Enter on empty text, and clearOnSelect empties the input', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<FreePicker search={down()} onSelect={onSelect} defaultUnavailable validate={undefined} clearOnSelect />);
    const input = screen.getByRole('textbox') as HTMLInputElement;
    await user.type(input, '{Enter}');
    expect(onSelect).not.toHaveBeenCalled();
    await user.type(input, 'anything{Enter}');
    expect(onSelect).toHaveBeenCalledWith({ free: 'anything' });
    expect(input.value).toBe('');
  });

  it('treats validate false as invalid with the default or replaced message', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const { rerender } = render(<FreePicker search={down()} onSelect={onSelect} defaultUnavailable validate={() => false} />);
    await user.type(screen.getByRole('textbox'), 'x{Enter}');
    expect(onSelect).not.toHaveBeenCalled();
    expect(document.querySelector('.combobox-hint')?.textContent).toBe('Enter a valid value.');
    rerender(<FreePicker search={down()} onSelect={onSelect} defaultUnavailable validate={() => false} messages={{ invalid: 'Not usable.' }} />);
    expect(document.querySelector('.combobox-hint')?.textContent).toBe('Not usable.');
  });

  it('replaces the unavailable hint through messages and announces it in the live region', () => {
    render(<FreePicker search={down()} onSelect={() => undefined} defaultUnavailable messages={{ unavailable: 'Directory offline.' }} />);
    expect(document.querySelector('.combobox-hint')?.textContent).toBe('Directory offline.');
    expect(screen.getByRole('status').textContent).toBe('Directory offline.');
  });

  it('adds the hint to a Field description and has no axe violations in either text state', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <Field label="Owner" hint="Pick one.">
        <FreePicker search={down()} onSelect={() => undefined} defaultUnavailable />
      </Field>,
    );
    const input = screen.getByRole('textbox', { name: 'Owner' });
    expect((input.getAttribute('aria-describedby') ?? '').split(' ').length).toBe(2);
    const skip = { rules: { 'color-contrast': { enabled: false } }, resultTypes: ['violations' as const] };
    expect((await axe.run(container, skip)).violations.map((v) => v.id)).toEqual([]);
    await user.type(input, 'nope');
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect((await axe.run(container, skip)).violations.map((v) => v.id)).toEqual([]);
  });

  it('leaves the lookup untouched when nothing is unavailable: arrows still wrap and rows still pick', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<PersonPicker search={lookup()} onSelect={onSelect} />);
    const input = screen.getByRole('combobox');
    await user.type(input, 'av');
    await screen.findAllByRole('option');
    await user.keyboard('{ArrowUp}');
    expect(screen.getAllByRole('option')[1]?.getAttribute('aria-selected')).toBe('true');
    await user.keyboard('{ArrowDown}');
    expect(screen.getAllByRole('option')[0]?.getAttribute('aria-selected')).toBe('true');
    await user.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalledWith(PEOPLE[0]);
  });
});
