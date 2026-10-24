import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { CommandPalette, filterPaletteItems, openCommandPalette } from '../src/index';
import type { PaletteItem } from '../src/index';

function make(count: number, onSelect: (id: string) => void = () => undefined): PaletteItem[] {
  return Array.from({ length: count }, (_, i) => ({ id: `r${i}`, label: `Row ${i}`, onSelect: () => onSelect(`r${i}`) }));
}

describe('CommandPalette rank', () => {
  it('keeps the substring filter when no rank is given', async () => {
    const user = userEvent.setup();
    render(<CommandPalette items={make(5)} />);
    act(() => openCommandPalette());
    await user.type(screen.getByRole('combobox'), 'row 3');
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Row 3']);
  });

  it('shows the order the rank function returns, for an empty query too', async () => {
    const user = userEvent.setup();
    const rank = vi.fn((query: string, list: readonly PaletteItem[]) => [...list].reverse().filter((i) => i.label.toLowerCase().includes(query.toLowerCase())));
    render(<CommandPalette items={make(3)} rank={rank} />);
    act(() => openCommandPalette());
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Row 2', 'Row 1', 'Row 0']);
    expect(rank).toHaveBeenCalledWith('', expect.any(Array));
    await user.type(screen.getByRole('combobox'), '1');
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Row 1']);
    expect(rank).toHaveBeenLastCalledWith('1', expect.any(Array));
  });

  it('opens the first ranked row on Enter', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<CommandPalette items={make(3, onSelect)} rank={(_q, list) => [...list].reverse()} />);
    act(() => openCommandPalette());
    await user.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalledWith('r2');
  });
});

describe('CommandPalette limit', () => {
  it('caps the rows at 50 by default', () => {
    render(<CommandPalette items={make(80)} />);
    act(() => openCommandPalette());
    expect(screen.getAllByRole('option')).toHaveLength(50);
  });

  it('takes a number, Infinity, and applies to a custom rank', () => {
    const { unmount } = render(<CommandPalette items={make(80)} limit={5} />);
    act(() => openCommandPalette());
    expect(screen.getAllByRole('option')).toHaveLength(5);
    unmount();
    const second = render(<CommandPalette items={make(80)} limit={Infinity} />);
    act(() => openCommandPalette());
    expect(screen.getAllByRole('option')).toHaveLength(80);
    second.unmount();
    render(<CommandPalette items={make(80)} limit={3} rank={(_q, list) => list} />);
    act(() => openCommandPalette());
    expect(screen.getAllByRole('option')).toHaveLength(3);
  });

  it('filterPaletteItems accepts Infinity', () => {
    expect(filterPaletteItems(make(80), '', Infinity)).toHaveLength(80);
  });
});

describe('CommandPalette rows', () => {
  const rows: PaletteItem[] = [
    { id: 'a', label: 'Alpha', description: 'The first one', badge: 'Open', kind: 'Page', onSelect: () => undefined },
    { id: 'b', label: 'Beta', kind: 'Page', onSelect: () => undefined },
  ];

  it('renders a description line and a badge, and leaves plain rows unchanged', () => {
    render(<CommandPalette items={rows} />);
    act(() => openCommandPalette());
    const [first, second] = screen.getAllByRole('option');
    expect(first?.querySelector('.palette-desc')?.textContent).toBe('The first one');
    expect(first?.querySelector('.palette-badge')?.textContent).toBe('Open');
    expect(first?.textContent).toBe('AlphaThe first onePageOpen');
    expect(second?.querySelector('.palette-desc')).toBeNull();
    expect(second?.querySelector('.palette-badge')).toBeNull();
    expect(second?.querySelector('.palette-end')).toBeNull();
    expect(second?.textContent).toBe('BetaPage');
  });

  it('still highlights the label match', async () => {
    const user = userEvent.setup();
    render(<CommandPalette items={rows} />);
    act(() => openCommandPalette());
    await user.type(screen.getByRole('combobox'), 'alp');
    expect(screen.getAllByRole('option')[0]?.querySelector('mark.search-hit')?.textContent).toBe('Alp');
  });
});

describe('CommandPalette toolbar', () => {
  function Host({ onSelect }: { onSelect: (id: string) => void }) {
    const [kind, setKind] = useState('all');
    const list = make(3, onSelect).map((i, n) => ({ ...i, kind: n === 0 ? 'A' : 'B' }));
    const shown = kind === 'all' ? list : list.filter((i) => i.kind === kind);
    return (
      <CommandPalette
        items={shown}
        toolbarLabel="Kinds"
        toolbar={['all', 'A', 'B'].map((k) => (
          <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)}>
            {k}
          </button>
        ))}
      />
    );
  }

  it('renders the slot in a named group under the search field', () => {
    render(<Host onSelect={() => undefined} />);
    act(() => openCommandPalette());
    const group = screen.getByRole('group', { name: 'Kinds' });
    expect(within(group).getAllByRole('button')).toHaveLength(3);
    const dialog = screen.getByRole('dialog');
    expect(dialog.querySelector('.palette-search + .palette-toolbar')).not.toBeNull();
  });

  it('keeps Enter and arrow keys inside the toolbar for the chips', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<Host onSelect={onSelect} />);
    act(() => openCommandPalette());
    await user.tab();
    const chip = screen.getByRole('button', { name: 'A' });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'all' }));
    chip.focus();
    await user.keyboard('{Enter}');
    expect(onSelect).not.toHaveBeenCalled();
    expect(chip.getAttribute('aria-pressed')).toBe('true');
    expect(screen.getAllByRole('option')).toHaveLength(1);
    fireEvent.keyDown(chip, { key: 'ArrowDown' });
    expect(screen.getAllByRole('option')[0]?.getAttribute('aria-selected')).toBe('true');
  });

  it('adds no toolbar element when the slot is omitted', () => {
    render(<CommandPalette items={make(2)} />);
    act(() => openCommandPalette());
    expect(screen.getByRole('dialog').querySelector('.palette-toolbar')).toBeNull();
  });

  it('has no axe violations with a toolbar, descriptions and badges', async () => {
    document.title = 'Palette';
    document.documentElement.lang = 'en';
    render(
      <CommandPalette
        items={[{ id: 'a', label: 'Alpha', description: 'Line two', badge: 'Open', kind: 'Page', onSelect: () => undefined }]}
        toolbar={<button type="button">All</button>}
      />,
    );
    act(() => openCommandPalette());
    const result = await axe.run(document, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } }, resultTypes: ['violations'] });
    expect(result.violations.map((v) => v.id)).toEqual([]);
  });
});
