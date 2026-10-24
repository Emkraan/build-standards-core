import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import axe from 'axe-core';
import { describe, expect, it, vi } from 'vitest';
import {
  CommandPalette,
  TileReorderStatus,
  createMemoryTileOrderStore,
  moveInOrder,
  openCommandPalette,
  openScopedPalette,
  paletteScope,
  placeInOrder,
  reconcileOrder,
  useTileReorder,
} from '../src/index';
import type { PaletteItem, TileEntry, TileOrderStore } from '../src/index';

const NOTES = [
  { id: 'a', label: 'Alpha note', body: 'Body of alpha' },
  { id: 'b', label: 'Beta note', body: 'Body of beta' },
];

function items(): PaletteItem[] {
  return NOTES.map((n) => ({ id: n.id, label: n.label, kind: 'Template', onSelect: () => undefined }));
}

function Both() {
  return (
    <>
      <div {...paletteScope('notes')}>
        <textarea aria-label="Composer" />
      </div>
      <input aria-label="Elsewhere" />
      <CommandPalette items={items()} label="Page search" />
      <CommandPalette
        scope="notes"
        label="Template search"
        items={items()}
        preview={(item) => <p>{NOTES.find((n) => n.id === item?.id)?.body ?? 'Nothing selected'}</p>}
        previewLabel="Template preview"
      />
    </>
  );
}

describe('CommandPalette preview slot', () => {
  it('shows the active row in a labelled pane and follows the arrow keys', () => {
    render(<CommandPalette items={items()} preview={(item) => <p>{NOTES.find((n) => n.id === item?.id)?.body}</p>} previewLabel="Template preview" />);
    act(() => openCommandPalette());
    const pane = screen.getByRole('region', { name: 'Template preview' });
    expect(pane.textContent).toBe('Body of alpha');
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'ArrowDown' });
    expect(pane.textContent).toBe('Body of beta');
  });

  it('hands the slot undefined when nothing matches', () => {
    const seen: Array<string | undefined> = [];
    render(
      <CommandPalette
        items={items()}
        preview={(item) => {
          seen.push(item?.id);
          return <p>{item ? item.label : 'No match'}</p>;
        }}
      />,
    );
    act(() => openCommandPalette());
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'zzz' } });
    expect(screen.getByRole('region', { name: 'Preview' }).textContent).toBe('No match');
    expect(seen.at(-1)).toBeUndefined();
  });

  it('renders no pane and no wide layout without the slot', () => {
    render(<CommandPalette items={items()} />);
    act(() => openCommandPalette());
    expect(screen.queryByRole('region')).toBeNull();
    expect(screen.getByRole('dialog').className).not.toContain('palette-with-preview');
  });

  it('has no axe violations with the pane open', async () => {
    document.title = 'Palette';
    document.documentElement.lang = 'en';
    render(<CommandPalette items={items()} preview={() => <p>Body</p>} />);
    act(() => openCommandPalette());
    const result = await axe.run(document, { rules: { 'color-contrast': { enabled: false } }, resultTypes: ['violations'] });
    expect(result.violations.map((v) => v.id)).toEqual([]);
  });
});

describe('scoped shortcut rule', () => {
  it('opens the scoped palette from inside the region and not the global one', () => {
    render(<Both />);
    fireEvent.keyDown(screen.getByLabelText('Composer'), { key: 'k', ctrlKey: true });
    expect(screen.getByRole('dialog', { name: 'Template search' })).toBeTruthy();
    expect(screen.queryByRole('dialog', { name: 'Page search' })).toBeNull();
    fireEvent.keyDown(document.activeElement as Element, { key: 'k', ctrlKey: true });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('applies the scope rule to the slash key too', () => {
    const { unmount } = render(
      <>
        <div {...paletteScope('notes')}>
          <button type="button">Inside</button>
        </div>
        <button type="button">Outside</button>
        <CommandPalette items={items()} label="Page search" />
        <CommandPalette scope="notes" label="Template search" items={items()} />
      </>,
    );
    fireEvent.keyDown(screen.getByRole('button', { name: 'Inside' }), { key: '/' });
    expect(screen.getByRole('dialog', { name: 'Template search' })).toBeTruthy();
    expect(screen.queryByRole('dialog', { name: 'Page search' })).toBeNull();
    unmount();
    render(
      <>
        <div {...paletteScope('notes')} />
        <button type="button">Outside</button>
        <CommandPalette items={items()} label="Page search" />
        <CommandPalette scope="notes" label="Template search" items={items()} />
      </>,
    );
    fireEvent.keyDown(screen.getByRole('button', { name: 'Outside' }), { key: '/' });
    expect(screen.getByRole('dialog', { name: 'Page search' })).toBeTruthy();
    expect(screen.queryByRole('dialog', { name: 'Template search' })).toBeNull();
  });

  it('opens the global palette from anywhere else, and never the scoped one', () => {
    render(<Both />);
    fireEvent.keyDown(screen.getByLabelText('Elsewhere'), { key: 'k', metaKey: true });
    expect(screen.getByRole('dialog', { name: 'Page search' })).toBeTruthy();
    expect(screen.queryByRole('dialog', { name: 'Template search' })).toBeNull();
  });

  it('opens the global palette from the document with no focus target', () => {
    render(<Both />);
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
    expect(screen.getByRole('dialog', { name: 'Page search' })).toBeTruthy();
  });

  it('opens by scope name through openCommandPalette', () => {
    render(<Both />);
    act(() => openScopedPalette('notes'));
    expect(screen.getByRole('dialog', { name: 'Template search' })).toBeTruthy();
    expect(screen.queryByRole('dialog', { name: 'Page search' })).toBeNull();
  });

  it('lets the global palette take the key in a region no palette owns', () => {
    render(
      <>
        <div {...paletteScope('unowned')}>
          <input aria-label="Field" />
        </div>
        <CommandPalette items={items()} label="Page search" />
      </>,
    );
    fireEvent.keyDown(screen.getByLabelText('Field'), { key: 'k', ctrlKey: true });
    expect(screen.getByRole('dialog', { name: 'Page search' })).toBeTruthy();
  });

  it('lets the global palette take the key again once the scoped palette unmounts', () => {
    const { rerender } = render(<Both />);
    rerender(
      <>
        <div {...paletteScope('notes')}>
          <textarea aria-label="Composer" />
        </div>
        <CommandPalette items={items()} label="Page search" />
      </>,
    );
    fireEvent.keyDown(screen.getByLabelText('Composer'), { key: 'k', ctrlKey: true });
    expect(screen.getByRole('dialog', { name: 'Page search' })).toBeTruthy();
  });
});

const CATALOG: TileEntry[] = ['a', 'b', 'c', 'd'].map((id) => ({ id, label: `Tile ${id.toUpperCase()}` }));

describe('reconcileOrder, moveInOrder and placeInOrder', () => {
  it('drops removed ids and appends new ones in catalog order', () => {
    expect(reconcileOrder(['c', 'gone', 'a'], ['a', 'b', 'c', 'd'])).toEqual(['c', 'a', 'b', 'd']);
  });
  it('keeps the first place of a duplicate and treats junk as nothing saved', () => {
    expect(reconcileOrder(['b', 'b', 'a'], ['a', 'b'])).toEqual(['b', 'a']);
    expect(reconcileOrder(null, ['a', 'b'])).toEqual(['a', 'b']);
    expect(reconcileOrder('nope', ['a', 'b'])).toEqual(['a', 'b']);
    expect(reconcileOrder([1, {}, 'b'], ['a', 'b'])).toEqual(['b', 'a']);
  });
  it('moves by visible places and clamps at the ends', () => {
    expect(moveInOrder(['a', 'b', 'c'], 'a', 1)).toEqual(['b', 'a', 'c']);
    expect(moveInOrder(['a', 'b', 'c'], 'c', -Infinity)).toEqual(['c', 'a', 'b']);
    const same = ['a', 'b', 'c'];
    expect(moveInOrder(same, 'a', -1)).toBe(same);
    expect(moveInOrder(same, 'zz', 1)).toBe(same);
  });
  it('steps over hidden tiles and leaves them in place', () => {
    expect(moveInOrder(['a', 'h', 'b', 'c'], 'a', 1, new Set(['h']))).toEqual(['h', 'b', 'a', 'c']);
  });
  it('places before or after a target', () => {
    expect(placeInOrder(['a', 'b', 'c'], 'c', 'a')).toEqual(['c', 'a', 'b']);
    expect(placeInOrder(['a', 'b', 'c'], 'a', 'b', true)).toEqual(['b', 'a', 'c']);
  });
});

function Grid({ store, hidden }: { store?: TileOrderStore | undefined; hidden?: string[] | undefined }) {
  const reorder = useTileReorder({ catalog: CATALOG, store, hidden });
  return (
    <>
      <ul aria-label="Tiles">
        {reorder.tiles.map((t) => (
          <li key={t.id} {...reorder.tileProps(t.id)} aria-label={t.label}>
            {t.label}
          </li>
        ))}
      </ul>
      <button type="button" onClick={reorder.reset}>
        Reset
      </button>
      <TileReorderStatus reorder={reorder} />
    </>
  );
}

const names = () => screen.getAllByRole('listitem').map((el) => el.textContent);
const dataTransfer = () => {
  const data: Record<string, string> = {};
  return { effectAllowed: '', dropEffect: '', setData: (k: string, v: string) => (data[k] = v), getData: (k: string) => data[k] ?? '' };
};

describe('useTileReorder', () => {
  it('shows the saved order reconciled with the catalog once the store answers', async () => {
    const store = createMemoryTileOrderStore(['c', 'gone', 'a']);
    render(<Grid store={store} />);
    await waitFor(() => expect(names()).toEqual(['Tile C', 'Tile A', 'Tile B', 'Tile D']));
  });

  it('uses the catalog order with no store, an empty store, or a store whose read fails', async () => {
    const { unmount } = render(<Grid />);
    expect(names()).toEqual(['Tile A', 'Tile B', 'Tile C', 'Tile D']);
    unmount();
    const failing: TileOrderStore = { read: () => Promise.reject(new Error('down')), write: () => undefined };
    render(<Grid store={failing} />);
    await waitFor(() => expect(names()).toEqual(['Tile A', 'Tile B', 'Tile C', 'Tile D']));
  });

  it('moves a tile with Alt and the arrow keys, announces it and writes the order', async () => {
    const store = createMemoryTileOrderStore(null);
    const write = vi.spyOn(store, 'write');
    render(<Grid store={store} />);
    const tile = () => screen.getByRole('listitem', { name: 'Tile B' });
    act(() => tile().focus());
    fireEvent.keyDown(tile(), { key: 'ArrowRight', altKey: true });
    expect(names()).toEqual(['Tile A', 'Tile C', 'Tile B', 'Tile D']);
    expect(screen.getByRole('status').textContent).toBe('Tile B moved to position 3 of 4');
    expect(write).toHaveBeenCalledWith(['a', 'c', 'b', 'd']);
    fireEvent.keyDown(tile(), { key: 'ArrowUp', altKey: true });
    expect(names()).toEqual(['Tile A', 'Tile B', 'Tile C', 'Tile D']);
    fireEvent.keyDown(tile(), { key: 'End', altKey: true });
    expect(names().at(-1)).toBe('Tile B');
    fireEvent.keyDown(tile(), { key: 'Home', altKey: true });
    expect(names()[0]).toBe('Tile B');
    expect(screen.getByRole('status').textContent).toBe('Tile B moved to position 1 of 4');
  });

  it('says so at the edge, and ignores arrows without Alt', () => {
    render(<Grid />);
    const first = screen.getByRole('listitem', { name: 'Tile A' });
    fireEvent.keyDown(first, { key: 'ArrowLeft', altKey: true });
    expect(screen.getByRole('status').textContent).toBe('Tile A is already at the start');
    fireEvent.keyDown(first, { key: 'ArrowRight' });
    expect(names()[0]).toBe('Tile A');
  });

  it('ignores keys that come from inside a tile', () => {
    render(
      <TileInner />,
    );
    fireEvent.keyDown(screen.getByLabelText('Inside'), { key: 'ArrowRight', altKey: true });
    expect(names()[0]).toBe('Tile A');
  });

  it('skips hidden tiles and keeps them in the order', async () => {
    const store = createMemoryTileOrderStore(null);
    render(<Grid store={store} hidden={['b']} />);
    expect(names()).toEqual(['Tile A', 'Tile C', 'Tile D']);
    fireEvent.keyDown(screen.getByRole('listitem', { name: 'Tile A' }), { key: 'ArrowRight', altKey: true });
    expect(names()).toEqual(['Tile C', 'Tile A', 'Tile D']);
    expect(screen.getByRole('status').textContent).toBe('Tile A moved to position 2 of 3');
    await waitFor(() => expect(store.current()).toEqual(['b', 'c', 'a', 'd']));
  });

  it('reorders by drag and drop', () => {
    const store = createMemoryTileOrderStore(null);
    render(<Grid store={store} />);
    const dt = dataTransfer();
    fireEvent.dragStart(screen.getByRole('listitem', { name: 'Tile D' }), { dataTransfer: dt });
    fireEvent.dragOver(screen.getByRole('listitem', { name: 'Tile B' }), { dataTransfer: dt });
    expect(screen.getByRole('listitem', { name: 'Tile B' }).getAttribute('data-drop-target')).toBe('true');
    fireEvent.drop(screen.getByRole('listitem', { name: 'Tile B' }), { dataTransfer: dt });
    expect(names()).toEqual(['Tile A', 'Tile D', 'Tile B', 'Tile C']);
    expect(screen.getByRole('status').textContent).toBe('Tile D moved to position 2 of 4');
    fireEvent.dragEnd(screen.getByRole('listitem', { name: 'Tile D' }));
    expect(screen.getByRole('listitem', { name: 'Tile D' }).getAttribute('data-dragging')).toBe('false');
  });

  it('gives every tile the instruction and a drag handle contract', () => {
    render(<Grid />);
    const tile = screen.getByRole('listitem', { name: 'Tile A' });
    expect(tile.getAttribute('draggable')).toBe('true');
    expect(tile.getAttribute('tabindex')).toBe('0');
    const hint = document.getElementById(tile.getAttribute('aria-describedby') ?? '');
    expect(hint?.textContent).toContain('Alt');
  });

  it('keeps the order on screen and says so when a write fails', async () => {
    const store: TileOrderStore = { read: () => null, write: () => Promise.reject(new Error('down')) };
    render(<Grid store={store} />);
    fireEvent.keyDown(screen.getByRole('listitem', { name: 'Tile A' }), { key: 'ArrowRight', altKey: true });
    expect(names()).toEqual(['Tile B', 'Tile A', 'Tile C', 'Tile D']);
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('could not be saved'));
  });

  it('does not let a late read overwrite a move made before it answered', async () => {
    let answer: (v: string[]) => void = () => undefined;
    const store: TileOrderStore = { read: () => new Promise<string[]>((r) => (answer = r)), write: () => undefined };
    render(<Grid store={store} />);
    fireEvent.keyDown(screen.getByRole('listitem', { name: 'Tile A' }), { key: 'ArrowRight', altKey: true });
    await act(async () => answer(['d', 'c', 'b', 'a']));
    expect(names()).toEqual(['Tile B', 'Tile A', 'Tile C', 'Tile D']);
  });

  it('resets to the catalog order and writes it', async () => {
    const store = createMemoryTileOrderStore(['d', 'c', 'b', 'a']);
    render(<Grid store={store} />);
    await waitFor(() => expect(names()[0]).toBe('Tile D'));
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
    expect(names()).toEqual(['Tile A', 'Tile B', 'Tile C', 'Tile D']);
    expect(store.current()).toEqual(['a', 'b', 'c', 'd']);
  });

  it('picks up a tile added to the catalog later at the end', () => {
    const store = createMemoryTileOrderStore(['b', 'a']);
    function Dyn({ extra }: { extra: boolean }) {
      const catalog = extra ? [...CATALOG.slice(0, 2), { id: 'n', label: 'Tile N' }] : CATALOG.slice(0, 2);
      const r = useTileReorder({ catalog, store });
      return <ul>{r.tiles.map((t) => <li key={t.id}>{t.label}</li>)}</ul>;
    }
    const { rerender } = render(<Dyn extra={false} />);
    rerender(<Dyn extra />);
    return waitFor(() => expect(names()).toEqual(['Tile B', 'Tile A', 'Tile N']));
  });

  it('has no axe violations', async () => {
    document.title = 'Tiles';
    document.documentElement.lang = 'en';
    render(<Grid />);
    const result = await axe.run(document, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } }, resultTypes: ['violations'] });
    expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(',')}`)).toEqual([]);
  });
});

function TileInner() {
  const reorder = useTileReorder({ catalog: CATALOG });
  return (
    <ul>
      {reorder.tiles.map((t) => (
        <li key={t.id} {...reorder.tileProps(t.id)}>
          {t.label}
          {t.id === 'a' ? <input aria-label="Inside" type="text" /> : null}
        </li>
      ))}
    </ul>
  );
}
