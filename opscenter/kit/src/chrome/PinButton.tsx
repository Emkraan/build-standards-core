/* The pin control for a page header (UI standard, shell section 9). It pins the page the person is on as
   a shortcut on the hub home, and unpins it again. The kit owns the control and the contract, the
   host owns the storage: a host implements `PinsStore` (read, subscribe, pin, unpin and a denied
   state) over whatever it keeps pins in. The control is absent until the store has answered and
   whenever the read was denied, so a person without hub access never sees a button that cannot
   work. The pinned block on the hub home (HomeBlocks) reads the same store, so both always agree. */

import { useEffect, useSyncExternalStore } from 'react';
import { IconPin, IconPinOff } from '../icons/icons';
import { IconButton } from '../primitives/Button';
import { useToast } from '../overlays/Toaster';

/** One pinned page: the module that owns it, its route inside that module and a short label. */
export interface Pin {
  moduleId: string;
  route: string;
  label: string;
}

/**
 * What the store knows right now.
 * loading: the first read has not answered. denied: the read was refused or failed, pins are not
 * available to this person. ready: `pins` is the list and `max` the most the host keeps.
 */
export interface PinsSnapshot {
  status: 'loading' | 'ready' | 'denied';
  pins: readonly Pin[];
  max: number;
}

/**
 * The contract a host implements. `snapshot` must return the same object until something changes
 * (it feeds useSyncExternalStore). `pin` and `unpin` resolve to null on success or one plain
 * sentence on failure, and never throw.
 */
export interface PinsStore {
  snapshot: () => PinsSnapshot;
  subscribe: (listener: () => void) => () => void;
  /** Start the first read if it has not started. Called once when a pin control or block mounts. */
  load?: (() => void) | undefined;
  pin: (pin: Pin) => Promise<string | null>;
  unpin: (pin: Pin) => Promise<string | null>;
}

export const DEFAULT_MAX_PINS = 12;

const sameRoute = (a: Pin, b: { moduleId: string; route: string }) => a.moduleId === b.moduleId && a.route === b.route;

/** True when the page is in the list. */
export function isPinned(pins: readonly Pin[], page: { moduleId: string; route: string }): boolean {
  return pins.some((p) => sameRoute(p, page));
}

/** The pins as a hosted list, dropping anything that is not a complete pin. */
export function sanitizePins(list: unknown): Pin[] {
  if (!Array.isArray(list)) return [];
  const out: Pin[] = [];
  for (const p of list as unknown[]) {
    if (!p || typeof p !== 'object') continue;
    const { moduleId, route, label } = p as Record<string, unknown>;
    if (typeof moduleId === 'string' && typeof route === 'string' && typeof label === 'string' && moduleId && route && label) {
      out.push({ moduleId, route, label });
    }
  }
  return out;
}

/** The pins state of a store, kept in step with it. Starts the first read. */
export function usePins(store: PinsStore): PinsSnapshot {
  const snap = useSyncExternalStore(store.subscribe, store.snapshot, store.snapshot);
  // The first read starts from the first component that mounts. A store that has no `load` reads on its own.
  useEffect(() => {
    store.load?.();
  }, [store]);
  return snap;
}

export interface DeclaredPage {
  route: string;
  label: string;
}

/**
 * The declared page a pathname is on: the longest declared route that equals it or prefixes it, or
 * null. Only declared pages pin, so a dynamic detail route never pins by accident.
 */
export function pageAt(pages: readonly DeclaredPage[], pathname: string): DeclaredPage | null {
  let best: DeclaredPage | null = null;
  for (const page of pages) {
    const r = page.route;
    if (!r) continue;
    const hit = r === '/' ? pathname === '/' : pathname === r || pathname.startsWith(`${r}/`);
    if (hit && (!best || r.length > best.route.length)) best = page;
  }
  return best;
}

export interface PinButtonProps {
  store: PinsStore;
  moduleId: string;
  /** The page's route inside its module. */
  route: string;
  /** The page's name, used in the label, the toasts and the pin itself. */
  label: string;
  /** Hide the control: the hub home itself, where pins live, passes true. */
  hidden?: boolean | undefined;
}

/**
 * Pins or unpins one page. Render it inside `Toaster` (it reports the result with a toast). It
 * renders nothing until the store is ready and nothing when the read was denied. When the store is
 * full the control is disabled and says why.
 */
export function PinButton({ store, moduleId, route, label, hidden = false }: PinButtonProps) {
  const { status, pins, max } = usePins(store);
  const { toast } = useToast();
  if (hidden || status !== 'ready' || !route) return null;
  const page = { moduleId, route, label };
  const pinned = isPinned(pins, page);
  const full = !pinned && pins.length >= max;
  const name = pinned ? `Unpin ${label} from the hub` : full ? `The hub is full, unpin a page first (${max} pins)` : `Pin ${label} to the hub`;
  const run = async () => {
    const failed = await (pinned ? store.unpin(page) : store.pin(page));
    if (failed) toast('error', `Could not update your pins. ${failed}`);
    else toast('success', pinned ? `Unpinned ${label}` : `Pinned ${label} to the hub`);
  };
  return (
    <IconButton
      label={name}
      icon={pinned ? <IconPinOff size={16} /> : <IconPin size={16} />}
      disabled={full}
      aria-pressed={pinned}
      onClick={() => {
        void run();
      }}
    />
  );
}

export interface MemoryPinsStoreOptions {
  pins?: readonly Pin[] | undefined;
  max?: number | undefined;
  /** Start in the denied state, as a host does for a person with no hub access. */
  denied?: boolean | undefined;
}

/**
 * A store that keeps pins in memory. It is the reference implementation of the contract: the
 * gallery and the tests use it, and a host copies its shape over its own storage. Every pin and
 * unpin resolves at once.
 */
export function createMemoryPinsStore({ pins = [], max = DEFAULT_MAX_PINS, denied = false }: MemoryPinsStoreOptions = {}): PinsStore {
  let state: PinsSnapshot = denied ? { status: 'denied', pins: [], max } : { status: 'ready', pins: sanitizePins([...pins]), max };
  const listeners = new Set<() => void>();
  const set = (next: PinsSnapshot) => {
    state = next;
    for (const l of [...listeners]) l();
  };
  return {
    snapshot: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    pin: (pin) => {
      if (state.status !== 'ready') return Promise.resolve('Pins are not available.');
      if (isPinned(state.pins, pin)) return Promise.resolve(null);
      if (state.pins.length >= state.max) return Promise.resolve(`Only ${state.max} pages can be pinned.`);
      set({ ...state, pins: [...state.pins, pin] });
      return Promise.resolve(null);
    },
    unpin: (pin) => {
      if (state.status !== 'ready') return Promise.resolve('Pins are not available.');
      set({ ...state, pins: state.pins.filter((p) => !sameRoute(p, pin)) });
      return Promise.resolve(null);
    },
  };
}
