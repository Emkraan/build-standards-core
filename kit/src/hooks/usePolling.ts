/* usePolling: load something now and keep it fresh on an interval, following the web client
   runtime rule that polls pause while the tab is hidden (3.8). The poll stops on visibility
   hidden and, when the tab is visible again, refreshes once at once and restarts the interval. A
   poll never overlaps itself, an older reply never replaces a newer one, and a failed poll keeps
   the last good data and sets `error`. The hook never navigates: a 401 is the loader's to throw. */

import { useCallback, useEffect, useRef, useState } from 'react';

export interface UsePollingOptions {
  /** Pause without unmounting, for example while a dialog owns the page. Default true. */
  enabled?: boolean | undefined;
  /** Poll while the document is hidden. Default false, which is what 3.8 requires. */
  whileHidden?: boolean | undefined;
}

export interface Polled<T> {
  data: T | undefined;
  error: Error | undefined;
  /** True until the first reply or failure. */
  loading: boolean;
  /** Refresh now. Resolves when that load settles. */
  reload: () => Promise<void>;
  /** When the last good reply arrived, in milliseconds, or undefined. */
  updatedAt: number | undefined;
}

export function usePolling<T>(
  load: (signal: AbortSignal) => Promise<T>,
  everyMs: number,
  { enabled = true, whileHidden = false }: UsePollingOptions = {},
): Polled<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<Error | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<number | undefined>(undefined);
  const loadRef = useRef(load);
  loadRef.current = load;
  const seq = useRef(0);
  const inflight = useRef<AbortController | null>(null);
  const alive = useRef(true);

  const run = useCallback(async () => {
    if (inflight.current) return;
    const mine = ++seq.current;
    const ctl = new AbortController();
    inflight.current = ctl;
    try {
      const next = await loadRef.current(ctl.signal);
      if (!alive.current || mine !== seq.current || ctl.signal.aborted) return;
      setData(next);
      setError(undefined);
      setUpdatedAt(Date.now());
    } catch (e) {
      if (!alive.current || ctl.signal.aborted) return;
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      if (inflight.current === ctl) inflight.current = null;
      if (alive.current && mine === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    if (!enabled) return undefined;
    let timer: ReturnType<typeof setInterval> | undefined;
    const hidden = () => !whileHidden && typeof document !== 'undefined' && document.visibilityState === 'hidden';
    const stop = () => {
      if (timer !== undefined) clearInterval(timer);
      timer = undefined;
    };
    const start = () => {
      stop();
      if (everyMs > 0) timer = setInterval(() => void run(), everyMs);
    };
    const onVisibility = () => {
      if (hidden()) {
        stop();
      } else {
        void run();
        start();
      }
    };
    if (!hidden()) {
      void run();
      start();
    }
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      alive.current = false;
      stop();
      document.removeEventListener('visibilitychange', onVisibility);
      inflight.current?.abort();
      inflight.current = null;
    };
  }, [enabled, everyMs, whileHidden, run]);

  const reload = useCallback(async () => {
    inflight.current?.abort();
    inflight.current = null;
    await run();
  }, [run]);

  return { data, error, loading, reload, updatedAt };
}
