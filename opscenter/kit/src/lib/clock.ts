/* One shared clock for every relative time on a page. A single interval ticks on CLOCK_TICK and calls
   each subscriber, so fifty timestamps in a table cost one timer, not fifty. */

import { useSyncExternalStore } from 'react';
import { CLOCK_TICK } from './timing';

const listeners = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | undefined;

/** Calls `listener` on every clock tick. The interval runs only while someone listens. */
export function subscribeClock(listener: () => void): () => void {
  listeners.add(listener);
  if (listeners.size === 1) {
    timer = setInterval(() => {
      for (const fn of [...listeners]) fn();
    }, CLOCK_TICK);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && timer !== undefined) {
      clearInterval(timer);
      timer = undefined;
    }
  };
}

/**
 * A value derived from the current time, re-read on every clock tick. The component renders again only
 * when `read` returns something different from last time, so a label that changes once a minute renders
 * once a minute even though the clock ticks every second. `read` must return a primitive (a string or
 * a number), because the result is compared by identity.
 */
export function useClockValue<T extends string | number | boolean>(read: () => T): T {
  return useSyncExternalStore(subscribeClock, read, read);
}
