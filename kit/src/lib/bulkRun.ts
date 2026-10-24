/* useBulkRun: runs one task per selected item with a hard cap on how many run at once, a progress
   count, a per-item error list and cancel. Items are started in order from a shared cursor, so at
   most `concurrency` tasks are ever in flight, however many items there are. A failed item never
   stops the others. Cancel aborts the signal handed to every task and starts no new one, then the
   run settles once the tasks already in flight have. A new run is refused while one is active. */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

export type BulkRunStatus = 'idle' | 'running' | 'done' | 'cancelled';

export interface BulkRunError {
  /** The item key (see itemKey) of the item that failed. */
  key: string;
  /** Position of the item in the list the run was started with. */
  index: number;
  message: string;
}

export interface BulkRunState {
  status: BulkRunStatus;
  /** Items in the current run. */
  total: number;
  /** Items that finished, whether they succeeded or failed. */
  done: number;
  succeeded: number;
  failed: number;
  /** Tasks in flight right now. Never above the cap. */
  active: number;
  errors: readonly BulkRunError[];
}

export interface BulkRunResult {
  status: Exclude<BulkRunStatus, 'idle' | 'running'>;
  total: number;
  succeeded: number;
  failed: number;
  /** Items never started because the run was cancelled. */
  skipped: number;
  errors: readonly BulkRunError[];
}

export interface BulkRunOptions<T> {
  /** Most tasks in flight at once. A whole number from 1. Default 4. */
  concurrency?: number | undefined;
  /** The key an error is reported under. Default is the item's index as text. */
  itemKey?: ((item: T, index: number) => string) | undefined;
}

export interface BulkRun<T> {
  state: BulkRunState;
  /** Starts a run. Resolves when it settles. While a run is active it returns that run's promise. */
  run: (items: readonly T[]) => Promise<BulkRunResult>;
  /** Aborts the signal of every task and starts no further task. */
  cancel: () => void;
  /** Back to idle, dropping the counts and errors. Ignored while a run is active. */
  reset: () => void;
}

export const DEFAULT_BULK_CONCURRENCY = 4;

const IDLE: BulkRunState = { status: 'idle', total: 0, done: 0, succeeded: 0, failed: 0, active: 0, errors: [] };

/** The cap in force for a requested value: a whole number from 1, the default when it is not one. */
export function clampConcurrency(value: number | undefined): number {
  if (value === undefined || !Number.isFinite(value)) return DEFAULT_BULK_CONCURRENCY;
  return Math.max(1, Math.floor(value));
}

function messageOf(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === 'string' && error) return error;
  return 'The action failed';
}

/** Runs `task` once per item, at most `concurrency` at a time. The task gets an AbortSignal that
    is aborted by cancel and when the component unmounts. */
export function useBulkRun<T>(task: (item: T, signal: AbortSignal) => Promise<unknown>, options: BulkRunOptions<T> = {}): BulkRun<T> {
  const [state, setState] = useState<BulkRunState>(IDLE);
  const taskRef = useRef(task);
  const optionsRef = useRef(options);
  taskRef.current = task;
  optionsRef.current = options;
  const activeRun = useRef<{ controller: AbortController; promise: Promise<BulkRunResult> } | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      activeRun.current?.controller.abort();
    };
  }, []);

  const run = useCallback((items: readonly T[]): Promise<BulkRunResult> => {
    if (activeRun.current) return activeRun.current.promise;
    const list = items.slice();
    const cap = clampConcurrency(optionsRef.current.concurrency);
    const keyOf = optionsRef.current.itemKey;
    const controller = new AbortController();
    const errors: BulkRunError[] = [];
    let cursor = 0;
    let done = 0;
    let succeeded = 0;
    let active = 0;

    const publish = (status: BulkRunStatus) => {
      if (!mounted.current) return;
      setState({ status, total: list.length, done, succeeded, failed: errors.length, active, errors: errors.slice() });
    };

    const worker = async (): Promise<void> => {
      while (!controller.signal.aborted && cursor < list.length) {
        const index = cursor;
        cursor += 1;
        const item = list[index] as T;
        active += 1;
        publish('running');
        try {
          await taskRef.current(item, controller.signal);
          succeeded += 1;
        } catch (error) {
          errors.push({ key: keyOf ? keyOf(item, index) : String(index), index, message: messageOf(error) });
        } finally {
          active -= 1;
          done += 1;
        }
        publish('running');
      }
    };

    const promise = (async (): Promise<BulkRunResult> => {
      publish('running');
      const workers: Promise<void>[] = [];
      for (let i = 0; i < Math.min(cap, list.length); i += 1) workers.push(worker());
      await Promise.all(workers);
      const status = controller.signal.aborted && done < list.length ? 'cancelled' : 'done';
      publish(status);
      activeRun.current = null;
      return { status, total: list.length, succeeded, failed: errors.length, skipped: list.length - done, errors: errors.slice() };
    })();

    activeRun.current = { controller, promise };
    return promise;
  }, []);

  const cancel = useCallback(() => {
    activeRun.current?.controller.abort();
  }, []);

  const reset = useCallback(() => {
    if (!activeRun.current) setState(IDLE);
  }, []);

  return useMemo(() => ({ state, run, cancel, reset }), [state, run, cancel, reset]);
}
