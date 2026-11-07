/* Pinned pages: a person's own shortcuts, stored on the server per person. A small shared store so a header pin
   control and a Home block always agree. It has the shape of the kit's PinsStore (snapshot, subscribe, load,
   pin, unpin) without importing the kit. Every failure is quiet: a refused read, a 401 or an outage leaves the
   status denied, and a pin control built on it simply does not show. A pin is display only: the page it opens
   still enforces its own access. The server side is shell-packages/home-pins. */

/** One pinned page. */
export interface Pin {
  moduleId: string;
  route: string;
  label: string;
}

export interface PinsSnapshot {
  status: 'loading' | 'ready' | 'denied';
  pins: readonly Pin[];
  max: number;
}

export interface ServerPinsStoreOptions {
  /** The request function of the API client that reaches the pins routes (api.request). */
  request: (path: string, options?: { method?: string; body?: unknown; on401?: 'login' | 'throw' }) => Promise<unknown>;
  /** The pins route on that API. Default /home/pins. */
  path?: string;
  /** The limit shown before the server has answered. Default 12. */
  max?: number;
}

export interface ServerPinsStore {
  snapshot: () => PinsSnapshot;
  subscribe: (listener: () => void) => () => void;
  /** Start the first read if it has not started (shared by every caller). */
  load: () => void;
  /** Read again even if loaded. Resolves when the read has answered. Never rejects. */
  reload: () => Promise<void>;
  pin: (pin: Pin) => Promise<string | null>;
  unpin: (pin: Pin) => Promise<string | null>;
  /** Forget everything (sign-out, account change). */
  reset: () => void;
}

const DEFAULT_MAX = 12;

function pinsOf(body: unknown): Pin[] | null {
  const list = body && typeof body === 'object' ? (body as { pins?: unknown }).pins : null;
  if (!Array.isArray(list)) return null;
  return list.filter(
    (p): p is Pin => !!p && typeof p.moduleId === 'string' && typeof p.route === 'string' && typeof p.label === 'string',
  );
}

export function createServerPinsStore(options: ServerPinsStoreOptions): ServerPinsStore {
  const path = options.path ?? '/home/pins';
  const fallbackMax = options.max ?? DEFAULT_MAX;
  const initial = (): PinsSnapshot => ({ status: 'loading', pins: [], max: fallbackMax });
  let state = initial();
  const listeners = new Set<() => void>();
  let reading: Promise<void> | null = null;
  let started = false;
  // Bumped by reset(): an answer to a read started before it is dropped.
  let epoch = 0;

  const set = (next: Partial<PinsSnapshot>) => {
    state = { ...state, ...next };
    for (const l of [...listeners]) l();
  };

  const read = (): Promise<void> => {
    if (reading) return reading;
    started = true;
    const mine = epoch;
    reading = options
      .request(path, { on401: 'throw' })
      .then(
        (body) => {
          if (mine !== epoch) return;
          const pins = pinsOf(body);
          const max = Number((body as { max?: unknown } | null)?.max);
          if (pins) set({ status: 'ready', pins, max: Number.isFinite(max) && max > 0 ? max : fallbackMax });
          else set({ status: 'denied' });
        },
        () => {
          if (mine === epoch) set({ status: 'denied' });
        },
      )
      .finally(() => {
        if (mine === epoch) reading = null;
      });
    return reading;
  };

  const write = async (verb: 'put' | 'delete', pin: Pin): Promise<string | null> => {
    const mine = epoch;
    try {
      const body =
        verb === 'put'
          ? await options.request(path, { method: 'PUT', body: pin, on401: 'throw' })
          : await options.request(
              `${path}?moduleId=${encodeURIComponent(pin.moduleId)}&route=${encodeURIComponent(pin.route)}`,
              { method: 'DELETE', on401: 'throw' },
            );
      const pins = pinsOf(body);
      if (pins && mine === epoch) set({ pins });
      return null;
    } catch (e) {
      return (e as { message?: string } | null)?.message || 'Could not save the pin.';
    }
  };

  return {
    snapshot: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    load() {
      if (!started) void read();
    },
    reload: () => read(),
    pin: (pin) => write('put', pin),
    unpin: (pin) => write('delete', pin),
    reset() {
      epoch += 1;
      reading = null;
      started = false;
      state = initial();
      for (const l of [...listeners]) l();
    },
  };
}
