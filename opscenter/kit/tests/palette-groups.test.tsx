import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { CommandPalette, ShortcutLayer, filterPaletteItems, groupPaletteItems, openCommandPalette, scorePaletteItem } from '../src/index';
import type { PaletteItem } from '../src/index';

const none = () => undefined;
const sample: PaletteItem[] = [
  { id: 'a', label: 'Open report', group: 'Actions', onSelect: none },
  { id: 'b', label: 'Reports', group: 'Pages', onSelect: none },
  { id: 'c', label: 'Run audit', group: 'Actions', keywords: ['report'], onSelect: none },
  { id: 'd', label: 'Team', group: 'Pages', kind: 'Reporting', onSelect: none },
];

describe('palette ranking', () => {
  it('orders exact, prefix, word start, substring, keyword, kind', () => {
    const items: PaletteItem[] = [
      { id: 'kind', label: 'Zed', kind: 'report', onSelect: none },
      { id: 'kw', label: 'Zeta', keywords: ['report'], onSelect: none },
      { id: 'sub', label: 'Xreport', onSelect: none },
      { id: 'word', label: 'Open report', onSelect: none },
      { id: 'pre', label: 'Reports', onSelect: none },
      { id: 'exact', label: 'Report', onSelect: none },
    ];
    expect(filterPaletteItems(items, 'report').map((i) => i.id)).toEqual(['exact', 'pre', 'word', 'sub', 'kw', 'kind']);
    expect(scorePaletteItem(items[0] as PaletteItem, 'nope')).toBe(0);
  });

  it('ranks an exact keyword above a keyword substring and keeps ties in order', () => {
    const items: PaletteItem[] = [
      { id: 'a', label: 'Alpha', keywords: ['prefs'], onSelect: none },
      { id: 'b', label: 'Beta', keywords: ['pref'], onSelect: none },
      { id: 'c', label: 'Gamma', keywords: ['pref'], onSelect: none },
    ];
    expect(filterPaletteItems(items, 'pref').map((i) => i.id)).toEqual(['b', 'c', 'a']);
  });
});

describe('palette grouping and filters', () => {
  it('gathers groups by first appearance', () => {
    expect(groupPaletteItems(sample).map((i) => i.id)).toEqual(['a', 'c', 'b', 'd']);
    expect(groupPaletteItems([{ id: 'x', label: 'x', onSelect: none }]).length).toBe(1);
  });

  it('renders group headers and moves with the arrows in display order', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const items = sample.map((i) => ({ ...i, onSelect: () => onSelect(i.id) }));
    render(<CommandPalette items={items} />);
    act(() => openCommandPalette());
    await user.type(screen.getByRole('combobox'), 'report');
    const list = screen.getByRole('listbox');
    expect(within(list).getAllByText(/^(Actions|Pages)$/).map((n) => n.textContent)).toEqual(['Pages', 'Actions']);
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Reports', 'TeamReporting', 'Open report', 'Run audit']);
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}');
    expect(onSelect).toHaveBeenCalledWith('a');
  });

  it('cycles filter tabs with Tab and Shift+Tab', async () => {
    const user = userEvent.setup();
    render(<CommandPalette items={sample} filters={[{ id: 'Actions', label: 'Actions' }, { id: 'Pages', label: 'Pages' }]} />);
    act(() => openCommandPalette());
    expect(screen.getAllByRole('option')).toHaveLength(4);
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Tab' });
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Open report', 'Run audit']);
    expect(screen.getByRole('button', { name: 'Actions' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Tab' });
    expect(screen.getAllByRole('option')).toHaveLength(2);
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Tab' });
    expect(screen.getAllByRole('option')).toHaveLength(4);
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Tab', shiftKey: true });
    expect(screen.getByRole('button', { name: 'Pages' }).getAttribute('aria-pressed')).toBe('true');
    await user.click(screen.getByRole('button', { name: 'All' }));
    expect(screen.getAllByRole('option')).toHaveLength(4);
  });

  it('leaves Tab to the toolbar when one is present and ranks inside the active filter', () => {
    const rank = vi.fn((_q: string, items: readonly PaletteItem[]) => [...items].reverse());
    render(
      <CommandPalette
        items={sample}
        rank={rank}
        toolbar={<button type="button">Chip</button>}
        filters={[{ id: 'Actions', label: 'Actions' }]}
      />,
    );
    act(() => openCommandPalette());
    const tab = fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Tab' });
    expect(tab).toBe(true);
    expect(screen.getByRole('button', { name: 'All' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'Actions' }).tabIndex).toBe(0);
    fireEvent.click(screen.getByRole('button', { name: 'Actions' }));
    expect(rank).toHaveBeenLastCalledWith('', sample.filter((i) => i.group === 'Actions'));
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Run audit', 'Open report']);
  });
});

describe('palette shortcuts in the shared registry', () => {
  it('shows the keys, lists them in the help sheet and runs onSelect', () => {
    const onSelect = vi.fn();
    const items: PaletteItem[] = [{ id: 'new', label: 'New note', group: 'Actions', shortcut: 'shift+n', onSelect }];
    render(
      <ShortcutLayer>
        <CommandPalette items={items} />
      </ShortcutLayer>,
    );
    fireEvent.keyDown(document.body, { key: 'N', shiftKey: true });
    expect(onSelect).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document.body, { key: '?', shiftKey: true });
    expect(within(screen.getByRole('dialog', { name: 'Keyboard shortcuts' })).getByText('New note')).toBeTruthy();
  });

  it('shows keys on the row in place of the kind', () => {
    render(<CommandPalette items={[{ id: 'n', label: 'New note', kind: 'Action', shortcut: 'g h', onSelect: none }]} />);
    act(() => openCommandPalette());
    const row = screen.getByRole('option');
    expect(row.querySelectorAll('kbd').length).toBe(2);
    expect(row.textContent).not.toContain('Action');
  });
});
