import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { CommandPalette, filterPaletteItems, openCommandPalette } from '../src/index';
import type { PaletteItem } from '../src/index';

function items(onSelect: (id: string) => void): PaletteItem[] {
  return ['Devices', 'Device groups', 'Reports', 'Settings'].map((label) => ({
    id: label.toLowerCase().replace(/ /g, '-'),
    label,
    kind: 'Page',
    keywords: label === 'Settings' ? ['preferences'] : undefined,
    onSelect: () => onSelect(label),
  }));
}

describe('CommandPalette', () => {
  it('opens on Ctrl+K and on Cmd+K', () => {
    render(<CommandPalette items={items(() => undefined)} />);
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
    expect(screen.getByRole('dialog', { name: 'Search' })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole('combobox'));
    fireEvent.keyDown(document.activeElement as Element, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.keyDown(document, { key: 'K', metaKey: true });
    expect(screen.getByRole('dialog', { name: 'Search' })).toBeTruthy();
  });

  it('filters by substring and highlights the match', async () => {
    const user = userEvent.setup();
    render(<CommandPalette items={items(() => undefined)} />);
    act(() => openCommandPalette());
    await user.type(screen.getByRole('combobox'), 'dev');
    const options = screen.getAllByRole('option');
    expect(options.map((o) => o.textContent)).toEqual(['DevicesPage', 'Device groupsPage']);
    const hit = options[0]?.querySelector('mark.search-hit');
    expect(hit?.textContent).toBe('Dev');
    await user.clear(screen.getByRole('combobox'));
    await user.type(screen.getByRole('combobox'), 'zzz');
    expect(screen.queryAllByRole('option')).toHaveLength(0);
    expect(screen.getByRole('status').textContent).toBe('No results');
  });

  it('moves with the arrow keys and opens on Enter', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<CommandPalette items={items(onSelect)} />);
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
    await user.keyboard('{ArrowDown}{ArrowDown}');
    expect(screen.getAllByRole('option')[2]?.getAttribute('aria-selected')).toBe('true');
    await user.keyboard('{ArrowUp}{Enter}');
    expect(onSelect).toHaveBeenCalledWith('Device groups');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('closes on Escape from a focused result row', () => {
    render(<CommandPalette items={items(() => undefined)} />);
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
    const row = screen.getAllByRole('option')[1] as HTMLElement;
    act(() => row.focus());
    expect(document.activeElement).toBe(row);
    fireEvent.keyDown(row, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('matches keywords after labels', () => {
    const list = filterPaletteItems(items(() => undefined), 'pref');
    expect(list.map((i) => i.label)).toEqual(['Settings']);
  });
});
