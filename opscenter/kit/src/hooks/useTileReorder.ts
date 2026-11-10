/* useTileReorder: a dashboard whose tiles the person can put in their own order, with a mouse or
   with the keyboard, and keep it. The hook owns three things: reconciling the saved order with the
   tiles that exist now (`reconcileOrder`), the moves (drag, or Alt and an arrow key on a focused
   tile) and what a screen reader hears after each move. It never owns the storage: the host
   implements `TileOrderStore` over whatever it keeps per person (an account setting, a user
   record), so each person has their own order and a read or write that fails never blocks the
   page. Tiles that are hidden keep their place in the saved order and are skipped by a move.
   Two opt-in drop aids: `endZoneProps` makes the empty space after the last tile a place to drop
   a tile last, and `edge` reads the cursor against a tile's midpoint so a drop lands before or
   after it (with `data-drop-edge` for the indicator) instead of always taking the target's place. */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { DragEvent, KeyboardEvent } from 'react';

/** Which side of a tile a drop lands on in `edge` mode. */
export type DropEdge = 'before' | 'after';

/** One tile the page can show. `label` is what a screen reader hears when it moves. */
export interface TileEntry {
  id: string;
  label: string;
}

/**
 * The contract a host implements, one store per person. `read` resolves to the saved order, or
 * null when nothing is saved yet. `write` resolves when the order is kept. Either may reject,
 * and the hook then keeps the catalog order (read) or the order on screen (write) and says so.
 */
export interface TileOrderStore {
  read: () => Promise<readonly string[] | null> | readonly string[] | null;
  write: (order: readonly string[]) => Promise<void> | void;
}

/**
 * The saved order made to fit the catalog: ids that are no longer in the catalog are dropped,
 * duplicates collapse to their first place, and ids the saved order has never seen are appended in
 * catalog order. Anything that is not a list of strings counts as nothing saved.
 */
export function reconcileOrder(saved: unknown, catalog: readonly string[]): string[] {
  const known = new Set(catalog);
  const out: string[] = [];
  const seen = new Set<string>();
  if (Array.isArray(saved)) {
    for (const id of saved as unknown[]) {
      if (typeof id === 'string' && known.has(id) && !seen.has(id)) {
        seen.add(id);
        out.push(id);
      }
    }
  }
  for (const id of catalog) {
    if (!seen.has(id)) {
      seen.add(id);
      out.push(id);
    }
  }
  return out;
}

/**
 * The order after moving `id` to be `delta` visible places along (negative is earlier). Hidden ids
 * are stepped over and keep their place. Returns the same array when nothing moves.
 */
export function moveInOrder(order: readonly string[], id: string, delta: number, hidden: ReadonlySet<string> = new Set()): readonly string[] {
  const visible = order.filter((x) => !hidden.has(x));
  const from = visible.indexOf(id);
  if (from < 0) return order;
  const to = Math.max(0, Math.min(visible.length - 1, from + delta));
  if (to === from) return order;
  return placeInOrder(order, id, visible[to] as string, to > from);
}

/** Moves `id` to sit just before `target` (or just after it when `after`). */
export function placeInOrder(order: readonly string[], id: string, target: string, after = false): readonly string[] {
  if (id === target || !order.includes(id) || !order.includes(target)) return order;
  const rest = order.filter((x) => x !== id);
  const at = rest.indexOf(target) + (after ? 1 : 0);
  const next = [...rest.slice(0, at), id, ...rest.slice(at)];
  return next.every((x, i) => x === order[i]) ? order : next;
}

/** The reference store: keeps one order in memory, for tests, demos and hosts with no storage yet. */
export function createMemoryTileOrderStore(initial: readonly string[] | null = null): TileOrderStore & { current: () => readonly string[] | null } {
  let kept: readonly string[] | null = initial;
  return {
    read: () => kept,
    write: (order) => {
      kept = [...order];
    },
    current: () => kept,
  };
}

export interface UseTileReorderOptions {
  /** Every tile the page can show now, in its default order. */
  catalog: readonly TileEntry[];
  /** Where the order is kept. Omit to keep it for the life of the page only. */
  store?: TileOrderStore | undefined;
  /** Ids of tiles the person has hidden. They keep their place and are skipped by moves. */
  hidden?: readonly string[] | undefined;
  /**
   * Edge mode. Off by default: a drop on a tile takes that tile's place, which moves a tile
   * forward or back depending on where it came from. On, the cursor is read against the tile
   * midpoint and the drop lands just before or just after it, and `data-drop-edge` says which.
   * `true` and `'x'` read the horizontal midpoint (a row or a grid), `'y'` the vertical one (a column).
   */
  edge?: boolean | 'x' | 'y' | undefined;
}

/** The props to spread on a tile's wrapping element. */
export interface TileProps {
  draggable: true;
  tabIndex: 0;
  className: string;
  'aria-roledescription': string;
  'aria-describedby': string | undefined;
  'data-dragging': boolean;
  'data-drop-target': boolean;
  /** Edge mode only, and only on the tile under the cursor: which side the drop would land on. */
  'data-drop-edge': DropEdge | undefined;
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
  onDragStart: (event: DragEvent<HTMLElement>) => void;
  onDragOver: (event: DragEvent<HTMLElement>) => void;
  onDrop: (event: DragEvent<HTMLElement>) => void;
  onDragEnd: () => void;
}

/** The props to spread on the empty space after the last tile. A drop there moves the tile last. */
export interface EndZoneProps {
  className: string;
  /** The zone is for the pointer. The keyboard move is Alt and End on a tile. */
  'aria-hidden': true;
  'data-drop-target': boolean;
  onDragOver: (event: DragEvent<HTMLElement>) => void;
  onDragLeave: (event: DragEvent<HTMLElement>) => void;
  onDrop: (event: DragEvent<HTMLElement>) => void;
}

export interface TileReorder {
  /** All catalog ids in the person's order, hidden ones included. */
  order: readonly string[];
  /** The catalog entries to render, in order, with hidden tiles removed. */
  tiles: readonly TileEntry[];
  /** False until the first read has answered. Render the default order meanwhile or a skeleton. */
  ready: boolean;
  /** Spread on each tile's wrapper. */
  tileProps: (id: string) => TileProps;
  /** Spread on an element placed after the last tile (it spans the grid row it sits in). */
  endZoneProps: EndZoneProps;
  /** Moves a tile by `delta` visible places. The same move the arrow keys make. */
  move: (id: string, delta: number) => void;
  /** Back to the catalog order. */
  reset: () => void;
  /** The sentence for the live region. Render it with `TileReorderStatus` or your own region. */
  announcement: string;
  /** Id for the instruction text that each tile points at with aria-describedby. */
  hintId: string;
  /** The instruction text itself, for a visually hidden element with id `hintId`. */
  hint: string;
}

const HINT = 'Drag to reorder, or hold Alt and press an arrow key to move this tile. Alt and Home or End moves it to the start or end.';
const DRAG_TYPE = 'text/plain';

let hintCount = 0;

/** Reorderable tiles, reconciled with the catalog and kept through the host's store. */
/** Which side of `el` the cursor is on, from its midpoint on `axis`. */
function edgeOf(event: DragEvent<HTMLElement>, axis: 'x' | 'y'): DropEdge {
  const rect = event.currentTarget.getBoundingClientRect();
  if (axis === 'y') return event.clientY >= rect.top + rect.height / 2 ? 'after' : 'before';
  const right = event.clientX >= rect.left + rect.width / 2;
  const rtl = typeof getComputedStyle === 'function' && getComputedStyle(event.currentTarget).direction === 'rtl';
  return right !== rtl ? 'after' : 'before';
}

export function useTileReorder({ catalog, store, hidden, edge }: UseTileReorderOptions): TileReorder {
  const axis: 'x' | 'y' | null = edge === 'y' ? 'y' : edge ? 'x' : null;
  const ids = useMemo(() => catalog.map((t) => t.id), [catalog]);
  const idsKey = ids.join('\u0000');
  const [saved, setSaved] = useState<unknown>(null);
  const [ready, setReady] = useState(store === undefined);
  const [announcement, setAnnouncement] = useState('');
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);
  const [overEdge, setOverEdge] = useState<DropEdge>('before');
  const [overEnd, setOverEnd] = useState(false);
  const [hintId] = useState(() => `tile-reorder-hint-${++hintCount}`);

  const order = useMemo(() => reconcileOrder(saved, ids), [saved, idsKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const orderRef = useRef<readonly string[]>(order);
  orderRef.current = order;
  const hiddenSet = useMemo(() => new Set(hidden ?? []), [hidden]);
  const hiddenRef = useRef(hiddenSet);
  hiddenRef.current = hiddenSet;
  const catalogRef = useRef(catalog);
  catalogRef.current = catalog;
  const storeRef = useRef(store);
  storeRef.current = store;
  const touched = useRef(false);

  // First read. A person who reorders before it answers wins: the late answer is dropped.
  useEffect(() => {
    if (!store) {
      setReady(true);
      return undefined;
    }
    let live = true;
    setReady(false);
    Promise.resolve()
      .then(() => store.read())
      .then(
        (value) => {
          if (live && !touched.current) setSaved(value);
        },
        () => undefined,
      )
      .then(() => {
        if (live) setReady(true);
      });
    return () => {
      live = false;
    };
  }, [store]);

  const commit = useCallback((next: readonly string[]) => {
    touched.current = true;
    setSaved(next);
    orderRef.current = next;
    const target = storeRef.current;
    if (!target) return;
    const failed = () => setAnnouncement('The new order could not be saved. It is kept until you leave this page.');
    try {
      Promise.resolve(target.write(next)).catch(failed);
    } catch {
      failed();
    }
  }, []);

  const labelOf = useCallback((id: string) => catalogRef.current.find((t) => t.id === id)?.label ?? id, []);

  const announce = useCallback(
    (id: string, next: readonly string[]) => {
      const visible = next.filter((x) => !hiddenRef.current.has(x));
      setAnnouncement(`${labelOf(id)} moved to position ${visible.indexOf(id) + 1} of ${visible.length}`);
    },
    [labelOf],
  );

  const apply = useCallback(
    (id: string, next: readonly string[], edge?: 'start' | 'end') => {
      if (next === orderRef.current) {
        const visible = orderRef.current.filter((x) => !hiddenRef.current.has(x));
        const where = edge ?? (visible.indexOf(id) === 0 ? 'start' : 'end');
        setAnnouncement(`${labelOf(id)} is already at the ${where}`);
        return;
      }
      commit(next);
      announce(id, next);
    },
    [announce, commit, labelOf],
  );

  const move = useCallback(
    (id: string, delta: number) => {
      apply(id, moveInOrder(orderRef.current, id, delta, hiddenRef.current), delta < 0 ? 'start' : 'end');
    },
    [apply],
  );

  const reset = useCallback(() => {
    const next = ids;
    commit(next);
    setAnnouncement('Tile order reset to the default');
  }, [commit, ids]);

  const endZoneProps = useMemo<EndZoneProps>(
    () => ({
      className: 'tile-reorder-end',
      'aria-hidden': true,
      'data-drop-target': overEnd && dragId !== null,
      onDragOver: (event) => {
        if (dragId === null) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        if (overId !== null) setOverId(null);
        if (!overEnd) setOverEnd(true);
      },
      onDragLeave: (event) => {
        if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return;
        setOverEnd(false);
      },
      onDrop: (event) => {
        event.preventDefault();
        const from = dragId ?? event.dataTransfer.getData(DRAG_TYPE);
        setDragId(null);
        setOverId(null);
        setOverEnd(false);
        if (!from) return;
        const visible = orderRef.current.filter((x) => !hiddenRef.current.has(x));
        const last = visible[visible.length - 1];
        if (last === undefined) return;
        apply(from, placeInOrder(orderRef.current, from, last, true), 'end');
      },
    }),
    [apply, dragId, overEnd, overId],
  );

  const tileProps = useCallback(
    (id: string): TileProps => ({
      draggable: true,
      tabIndex: 0,
      className: axis === 'y' ? 'tile-reorder tile-reorder-y' : 'tile-reorder',
      'aria-roledescription': 'reorderable tile',
      'aria-describedby': hintId,
      'data-dragging': dragId === id,
      'data-drop-target': overId === id && dragId !== null && dragId !== id,
      'data-drop-edge': axis !== null && overId === id && dragId !== null && dragId !== id ? overEdge : undefined,
      onKeyDown: (event) => {
        if (event.target !== event.currentTarget || !event.altKey || event.ctrlKey || event.metaKey) return;
        const key = event.key;
        if (key === 'ArrowUp' || key === 'ArrowLeft') move(id, -1);
        else if (key === 'ArrowDown' || key === 'ArrowRight') move(id, 1);
        else if (key === 'Home') move(id, -Infinity);
        else if (key === 'End') move(id, Infinity);
        else return;
        event.preventDefault();
      },
      onDragStart: (event) => {
        setDragId(id);
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData(DRAG_TYPE, id);
      },
      onDragOver: (event) => {
        if (dragId === null) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        if (overId !== id) setOverId(id);
        if (overEnd) setOverEnd(false);
        if (axis !== null) {
          const side = edgeOf(event, axis);
          if (side !== overEdge) setOverEdge(side);
        }
      },
      onDrop: (event) => {
        event.preventDefault();
        const from = dragId ?? event.dataTransfer.getData(DRAG_TYPE);
        setDragId(null);
        setOverId(null);
        setOverEnd(false);
        if (!from || from === id) return;
        const visible = orderRef.current.filter((x) => !hiddenRef.current.has(x));
        const after = axis !== null ? edgeOf(event, axis) === 'after' : visible.indexOf(from) < visible.indexOf(id);
        apply(from, placeInOrder(orderRef.current, from, id, after));
      },
      onDragEnd: () => {
        setDragId(null);
        setOverId(null);
        setOverEnd(false);
      },
    }),
    [apply, axis, dragId, hintId, move, overEdge, overEnd, overId],
  );

  const tiles = useMemo(() => {
    const byId = new Map(catalog.map((t) => [t.id, t] as const));
    return order.filter((id) => !hiddenSet.has(id)).map((id) => byId.get(id) as TileEntry);
  }, [catalog, order, hiddenSet]);

  return { order, tiles, ready, tileProps, endZoneProps, move, reset, announcement, hintId, hint: HINT };
}
