import { act, createEvent, fireEvent as rtlFire, render, screen } from '@testing-library/react';
import axe from 'axe-core';
import { describe, expect, it } from 'vitest';
import { TileReorderStatus, useTileReorder } from '../src/index';

const CATALOG = [
  { id: 'a', label: 'Tile A' },
  { id: 'b', label: 'Tile B' },
  { id: 'c', label: 'Tile C' },
  { id: 'd', label: 'Tile D' },
];

function Grid({ edge, hidden, rtl }: { edge?: boolean | 'x' | 'y'; hidden?: string[]; rtl?: boolean }) {
  const reorder = useTileReorder({ catalog: CATALOG, edge, hidden });
  return (
    <>
      <ul aria-label="Tiles" style={rtl ? { direction: 'rtl' } : undefined}>
        {reorder.tiles.map((t) => (
          <li key={t.id} {...reorder.tileProps(t.id)} aria-label={t.label}>
            {t.label}
          </li>
        ))}
      </ul>
      <div data-testid="end" {...reorder.endZoneProps} />
      <TileReorderStatus reorder={reorder} />
    </>
  );
}

const names = () => screen.getAllByRole('listitem').map((el) => el.textContent);
const tile = (name: string) => screen.getByRole('listitem', { name });
const dt = () => {
  const data: Record<string, string> = {};
  return { effectAllowed: '', dropEffect: '', setData: (k: string, v: string) => (data[k] = v), getData: (k: string) => data[k] ?? '' };
};
/** A tile 100 wide and 40 tall at the origin, so the midpoint is 50 and 20. */
function box(el: HTMLElement) {
  el.getBoundingClientRect = () => ({ left: 0, top: 0, right: 100, bottom: 40, width: 100, height: 40, x: 0, y: 0, toJSON: () => ({}) });
}

/** jsdom has no DragEvent, so the cursor position is set on the event by hand. */
const fireEvent = Object.assign(
  (el: Element, event: Event) => rtlFire(el, event),
  rtlFire,
  {
    dragOver: (el: Element, init: { dataTransfer?: unknown; clientX?: number; clientY?: number } = {}) => rtlFire(el, withPoint(createEvent.dragOver(el, init), init)),
    drop: (el: Element, init: { dataTransfer?: unknown; clientX?: number; clientY?: number } = {}) => rtlFire(el, withPoint(createEvent.drop(el, init), init)),
  },
);
function withPoint(event: Event, init: { clientX?: number; clientY?: number }): Event {
  Object.defineProperty(event, 'clientX', { value: init.clientX ?? 0 });
  Object.defineProperty(event, 'clientY', { value: init.clientY ?? 0 });
  return event;
}

describe('useTileReorder end zone', () => {
  it('moves a dragged tile last when dropped in the empty space', () => {
    render(<Grid />);
    const transfer = dt();
    fireEvent.dragStart(tile('Tile B'), { dataTransfer: transfer });
    const end = screen.getByTestId('end');
    fireEvent.dragOver(end, { dataTransfer: transfer });
    expect(end.getAttribute('data-drop-target')).toBe('true');
    fireEvent.drop(end, { dataTransfer: transfer });
    expect(names()).toEqual(['Tile A', 'Tile C', 'Tile D', 'Tile B']);
    expect(screen.getByRole('status').textContent).toBe('Tile B moved to position 4 of 4');
    expect(end.getAttribute('data-drop-target')).toBe('false');
  });

  it('says so when the tile is already last, and ignores a drop with nothing dragged', () => {
    render(<Grid />);
    const transfer = dt();
    fireEvent.dragStart(tile('Tile D'), { dataTransfer: transfer });
    fireEvent.drop(screen.getByTestId('end'), { dataTransfer: transfer });
    expect(names()).toEqual(['Tile A', 'Tile B', 'Tile C', 'Tile D']);
    expect(screen.getByRole('status').textContent).toBe('Tile D is already at the end');
    fireEvent.dragOver(screen.getByTestId('end'), { dataTransfer: dt() });
    expect(screen.getByTestId('end').getAttribute('data-drop-target')).toBe('false');
  });

  it('goes after the last visible tile and keeps a hidden tile in place', () => {
    render(<Grid hidden={['d']} />);
    const transfer = dt();
    fireEvent.dragStart(tile('Tile A'), { dataTransfer: transfer });
    fireEvent.drop(screen.getByTestId('end'), { dataTransfer: transfer });
    expect(names()).toEqual(['Tile B', 'Tile C', 'Tile A']);
  });

  it('clears its highlight on leave, on dragend and when the cursor moves to a tile', () => {
    render(<Grid />);
    const transfer = dt();
    const end = screen.getByTestId('end');
    fireEvent.dragStart(tile('Tile A'), { dataTransfer: transfer });
    fireEvent.dragOver(end, { dataTransfer: transfer });
    fireEvent.dragLeave(end);
    expect(end.getAttribute('data-drop-target')).toBe('false');
    fireEvent.dragOver(end, { dataTransfer: transfer });
    fireEvent.dragOver(tile('Tile C'), { dataTransfer: transfer });
    expect(end.getAttribute('data-drop-target')).toBe('false');
    expect(tile('Tile C').getAttribute('data-drop-target')).toBe('true');
    fireEvent.dragOver(end, { dataTransfer: transfer });
    expect(tile('Tile C').getAttribute('data-drop-target')).toBe('false');
    fireEvent.dragEnd(tile('Tile A'));
    expect(end.getAttribute('data-drop-target')).toBe('false');
  });

  it('is hidden from assistive technology and passes axe', async () => {
    document.title = 'Tiles';
    document.documentElement.lang = 'en';
    render(<Grid edge />);
    expect(screen.getByTestId('end').getAttribute('aria-hidden')).toBe('true');
    const result = await axe.run(document, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } }, resultTypes: ['violations'] });
    expect(result.violations.map((v) => v.id)).toEqual([]);
  });
});

describe('useTileReorder edge mode', () => {
  it('without edge, data-drop-edge is never set and a drop takes the target place', () => {
    render(<Grid />);
    const transfer = dt();
    fireEvent.dragStart(tile('Tile A'), { dataTransfer: transfer });
    box(tile('Tile C'));
    fireEvent.dragOver(tile('Tile C'), { dataTransfer: transfer, clientX: 10 });
    expect(tile('Tile C').hasAttribute('data-drop-edge')).toBe(false);
    fireEvent.drop(tile('Tile C'), { dataTransfer: transfer, clientX: 10 });
    expect(names()).toEqual(['Tile B', 'Tile C', 'Tile A', 'Tile D']);
  });

  it('reads the cursor against the midpoint and drops before or after', () => {
    render(<Grid edge />);
    const transfer = dt();
    box(tile('Tile C'));
    fireEvent.dragStart(tile('Tile A'), { dataTransfer: transfer });
    fireEvent.dragOver(tile('Tile C'), { dataTransfer: transfer, clientX: 80 });
    expect(tile('Tile C').getAttribute('data-drop-edge')).toBe('after');
    fireEvent.dragOver(tile('Tile C'), { dataTransfer: transfer, clientX: 20 });
    expect(tile('Tile C').getAttribute('data-drop-edge')).toBe('before');
    expect(tile('Tile B').hasAttribute('data-drop-edge')).toBe(false);
    fireEvent.drop(tile('Tile C'), { dataTransfer: transfer, clientX: 20 });
    expect(names()).toEqual(['Tile B', 'Tile A', 'Tile C', 'Tile D']);
    expect(tile('Tile C').hasAttribute('data-drop-edge')).toBe(false);
  });

  it('places a tile before an earlier one and after a later one', () => {
    render(<Grid edge />);
    box(tile('Tile B'));
    let transfer = dt();
    fireEvent.dragStart(tile('Tile D'), { dataTransfer: transfer });
    fireEvent.drop(tile('Tile B'), { dataTransfer: transfer, clientX: 20 });
    expect(names()).toEqual(['Tile A', 'Tile D', 'Tile B', 'Tile C']);
    box(tile('Tile C'));
    transfer = dt();
    fireEvent.dragStart(tile('Tile A'), { dataTransfer: transfer });
    fireEvent.drop(tile('Tile C'), { dataTransfer: transfer, clientX: 90 });
    expect(names()).toEqual(['Tile D', 'Tile B', 'Tile C', 'Tile A']);
  });

  it('reads the vertical midpoint with edge y and adds the axis class', () => {
    render(<Grid edge="y" />);
    box(tile('Tile B'));
    expect(tile('Tile B').className).toContain('tile-reorder-y');
    const transfer = dt();
    fireEvent.dragStart(tile('Tile D'), { dataTransfer: transfer });
    fireEvent.dragOver(tile('Tile B'), { dataTransfer: transfer, clientX: 5, clientY: 35 });
    expect(tile('Tile B').getAttribute('data-drop-edge')).toBe('after');
    fireEvent.drop(tile('Tile B'), { dataTransfer: transfer, clientX: 5, clientY: 35 });
    expect(names()).toEqual(['Tile A', 'Tile B', 'Tile D', 'Tile C']);
  });

  it('flips the horizontal sides in a right to left list', () => {
    render(<Grid edge rtl />);
    box(tile('Tile C'));
    const transfer = dt();
    fireEvent.dragStart(tile('Tile A'), { dataTransfer: transfer });
    fireEvent.dragOver(tile('Tile C'), { dataTransfer: transfer, clientX: 80 });
    expect(tile('Tile C').getAttribute('data-drop-edge')).toBe('before');
  });

  it('shows no edge on the tile being dragged', () => {
    render(<Grid edge />);
    const transfer = dt();
    box(tile('Tile A'));
    fireEvent.dragStart(tile('Tile A'), { dataTransfer: transfer });
    fireEvent.dragOver(tile('Tile A'), { dataTransfer: transfer, clientX: 90 });
    expect(tile('Tile A').hasAttribute('data-drop-edge')).toBe(false);
  });

  it('keeps the keyboard moves working in edge mode', () => {
    render(<Grid edge />);
    act(() => tile('Tile B').focus());
    fireEvent.keyDown(tile('Tile B'), { key: 'End', altKey: true });
    expect(names()).toEqual(['Tile A', 'Tile C', 'Tile D', 'Tile B']);
  });
});
