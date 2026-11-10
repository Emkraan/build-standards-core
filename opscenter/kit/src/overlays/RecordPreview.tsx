/* RecordPreview: a labelled dialog that previews any record by type and id from anywhere in an
   app (a palette result, a cross link chip, a detail header). The kit knows nothing about the
   records. The host registers, per record type, a loader and a body in a registry, mounts one
   provider near the root and drops a RecordChip wherever a record is mentioned. The dialog shows a
   skeleton while the loader runs, an error with Retry when it fails (the failure stays inside the
   dialog) and the registered body when it resolves. A body that throws is caught by a page scoped
   error boundary inside the dialog, so a bad record never takes the app down.

   A type may also register a seed: data the host already holds, painted at once while the live load
   runs. The live result is merged over the seed (or replaces it) and the loading, error and retry
   handling stays the kit's. A body can ask for a quiet refresh with `reload`, and a host can hand
   one open a context bag that the seed and the body both read. */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { MouseEvent, ReactNode } from 'react';
import { ErrorBoundary } from '../chrome/ErrorBoundary';
import { cx } from '../lib/env';
import { safeHref } from '../lib/url';
import { ErrorState } from '../primitives/ErrorState';
import { Skeleton } from '../primitives/EmptyState';
import { Modal } from './Modal';

/** A record named by its registered type and its id. */
export interface RecordRef {
  type: string;
  id: string;
}

/** What a body receives next to the loaded data. */
export interface RecordBodyContext {
  ref: RecordRef;
  /** Closes the dialog, for a body that navigates away. */
  close: () => void;
  /** Loads the record again after an edit in the body. The body stays on screen while it runs and
      is replaced by the fresh data. A failed reload shows the error state with Retry. */
  reload: () => void;
  /** The bag the host passed to `open` for this record, or undefined. */
  context?: RecordOpenContext | undefined;
}

/** Free form data a host hands to one `open` call (a tab to show, a row the user came from). */
export type RecordOpenContext = Record<string, unknown>;

/** How one record type loads and renders. `T` is whatever the loader resolves. */
export interface RecordTypeDef<T = unknown> {
  /** Plain name of the type ("Device"). It names the dialog while loading and is its subtitle after. */
  label: string;
  /** Fetches the record. Reject to show the error state. The signal aborts when the dialog moves on. */
  load: (id: string, signal: AbortSignal) => Promise<T>;
  /** Data to paint at once, before the live `load` answers. Return undefined when there is none and
      the skeleton shows as before. A throw is treated as no seed. */
  seed?: ((ref: RecordRef, context?: RecordOpenContext) => T | undefined) | undefined;
  /** Combines the seed with the live result, so fields only the seed holds survive. Without it the
      live result replaces the seed. Called only when a seed was painted. */
  merge?: ((seed: T, live: T) => T) | undefined;
  /** The body shown once loaded. */
  render: (data: T, context: RecordBodyContext) => ReactNode;
  /** The dialog title once loaded. Defaults to `label` and the id. */
  title?: ((data: T, ref: RecordRef) => string) | undefined;
  /** Where the full page for the record lives. When set the footer offers "Open full page". */
  href?: ((id: string) => string | undefined) | undefined;
  /** Icon tile in the dialog head. */
  icon?: ReactNode;
}

/** The host's record types. Create one, register each type, pass it to the provider. */
export interface RecordRegistry {
  /** Adds or replaces a type. Returns a function that removes it again. */
  register: <T>(type: string, def: RecordTypeDef<T>) => () => void;
  get: (type: string) => RecordTypeDef | undefined;
  has: (type: string) => boolean;
  types: () => string[];
}

export function createRecordRegistry(): RecordRegistry {
  const defs = new Map<string, RecordTypeDef>();
  return {
    register: <T,>(type: string, def: RecordTypeDef<T>) => {
      const stored = def as unknown as RecordTypeDef;
      defs.set(type, stored);
      return () => {
        if (defs.get(type) === stored) defs.delete(type);
      };
    },
    get: (type) => defs.get(type),
    has: (type) => defs.has(type),
    types: () => Array.from(defs.keys()),
  };
}

export interface RecordPreviewApi {
  /** Opens the preview. Returns false, and opens nothing, when the type is not registered. The
      optional context bag reaches the type's `seed` and the body. */
  open: (ref: RecordRef, context?: RecordOpenContext) => boolean;
  close: () => void;
  /** The record being shown, or null when the dialog is closed. */
  current: RecordRef | null;
  /** True when the type has a registered definition. */
  supports: (type: string) => boolean;
}

const RecordPreviewContext = createContext<RecordPreviewApi | null>(null);

/** The preview api. Throws outside a RecordPreviewProvider: a missing provider is a wiring bug. */
export function useRecordPreview(): RecordPreviewApi {
  const api = useContext(RecordPreviewContext);
  if (!api) throw new Error('useRecordPreview needs a RecordPreviewProvider above it');
  return api;
}

/** `pending` is true while data is on screen (a seed, or the body during a reload) and the live load still runs. */
type Load<T> = { status: 'loading' } | { status: 'error'; error: unknown } | { status: 'ready'; data: T; pending: boolean };

function runSeed(def: RecordTypeDef, ref: RecordRef, context: RecordOpenContext | undefined): { data: unknown } | null {
  if (!def.seed) return null;
  try {
    const data = def.seed(ref, context);
    return data === undefined || data === null ? null : { data };
  } catch {
    return null;
  }
}

export interface RecordPreviewProviderProps {
  registry: RecordRegistry;
  /** Called for a plain click on "Open full page" so a router can take it. Without it the link navigates normally. */
  navigate?: ((href: string) => void) | undefined;
  children?: ReactNode;
}

export function RecordPreviewProvider({ registry, navigate, children }: RecordPreviewProviderProps) {
  const [ref, setRef] = useState<RecordRef | null>(null);
  const [open, setOpen] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [load, setLoad] = useState<Load<unknown>>({ status: 'loading' });
  const def = ref ? registry.get(ref.type) : undefined;
  // What the next load should do: a fresh open or retry paints the seed, a reload keeps the body.
  const modeRef = useRef<'open' | 'reload'>('open');
  const contextRef = useRef<RecordOpenContext | undefined>(undefined);
  const [context, setContext] = useState<RecordOpenContext | undefined>(undefined);
  const seedRef = useRef<{ data: unknown } | null>(null);

  // The ref is kept while the dialog animates out, so the content does not blank before it leaves.
  const refType = ref?.type;
  const refId = ref?.id;
  useEffect(() => {
    if (refType === undefined || refId === undefined) return undefined;
    const current = registry.get(refType);
    if (!current) {
      setLoad({ status: 'error', error: new Error(`No preview is registered for ${refType}`) });
      return undefined;
    }
    const controller = new AbortController();
    const reloading = modeRef.current === 'reload';
    modeRef.current = 'open';
    if (reloading) {
      setLoad((prev) => (prev.status === 'ready' ? { ...prev, pending: true } : { status: 'loading' }));
    } else {
      const seeded = runSeed(current, { type: refType, id: refId }, contextRef.current);
      seedRef.current = seeded;
      setLoad(seeded ? { status: 'ready', data: seeded.data, pending: true } : { status: 'loading' });
    }
    let live = true;
    Promise.resolve()
      .then(() => current.load(refId, controller.signal))
      .then(
        (data) => {
          if (!live) return;
          const base = seedRef.current;
          let next: unknown = data;
          if (base && current.merge) {
            try {
              next = current.merge(base.data, data);
            } catch (error) {
              setLoad({ status: 'error', error });
              return;
            }
          }
          setLoad({ status: 'ready', data: next, pending: false });
        },
        (error: unknown) => {
          if (live && !controller.signal.aborted) setLoad({ status: 'error', error });
        },
      );
    return () => {
      live = false;
      controller.abort();
    };
  }, [registry, refType, refId, attempt]);

  const close = useCallback(() => setOpen(false), []);
  const reload = useCallback(() => {
    modeRef.current = 'reload';
    setAttempt((n) => n + 1);
  }, []);
  const api = useMemo<RecordPreviewApi>(
    () => ({
      open: (next, bag) => {
        if (!registry.has(next.type)) return false;
        contextRef.current = bag;
        setContext(bag);
        modeRef.current = 'open';
        setRef((prev) => (prev && prev.type === next.type && prev.id === next.id ? prev : { type: next.type, id: next.id }));
        // Every open loads again, so a record changed since the last look is never shown stale.
        setAttempt((n) => n + 1);
        setOpen(true);
        return true;
      },
      close,
      current: open ? ref : null,
      supports: (type) => registry.has(type),
    }),
    [registry, close, open, ref],
  );

  let title: ReactNode = 'Record preview';
  let subtitle: ReactNode;
  let body: ReactNode = null;
  let footer: ReactNode;
  if (ref && def) {
    title = `${def.label} ${ref.id}`;
    if (load.status === 'ready') {
      title = def.title ? def.title(load.data, ref) : title;
      if (title !== `${def.label} ${ref.id}`) subtitle = def.label;
      body = (
        <ErrorBoundary variant="page" resetKey={`${ref.type}:${ref.id}`}>
          <RecordBody def={def} data={load.data} recordRef={ref} close={close} reload={reload} context={context} />
        </ErrorBoundary>
      );
    } else if (load.status === 'error') {
      body = <ErrorState title="Could not load this record." error={load.error} onRetry={() => {
          modeRef.current = 'open';
          setAttempt((n) => n + 1);
        }} />;
    } else {
      body = <Skeleton variant="lines" count={4} label={`Loading ${def.label}`} />;
    }
    const href = safeHref(def.href?.(ref.id));
    if (href) {
      footer = (
        <div className="modal-foot">
          <div className="modal-foot-start" />
          <a
            className="btn"
            data-variant="secondary"
            data-size="md"
            href={href}
            onClick={(event: MouseEvent<HTMLAnchorElement>) => {
              if (!navigate || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
              event.preventDefault();
              close();
              navigate(href);
            }}
          >
            Open full page
          </a>
          <button type="button" className="btn" data-variant="primary" data-size="md" onClick={close}>
            Close
          </button>
        </div>
      );
    }
  }

  return (
    <RecordPreviewContext.Provider value={api}>
      {children}
      <Modal
        open={open && ref !== null && def !== undefined}
        onClose={close}
        title={title}
        subtitle={subtitle}
        icon={def?.icon}
        size="lg"
        className="record-preview"
        cancelLabel="Close"
        footer={footer}
      >
        <div className="record-preview-body" data-state={load.status} data-pending={load.status === 'ready' && load.pending ? '' : undefined} aria-busy={load.status === 'ready' && load.pending ? true : undefined}>
          {body}
        </div>
      </Modal>
    </RecordPreviewContext.Provider>
  );
}

/** Calls the host's body as a component, so a throwing body is caught by the boundary above it. */
function RecordBody({ def, data, recordRef, close, reload, context }: { def: RecordTypeDef; data: unknown; recordRef: RecordRef; close: () => void; reload: () => void; context: RecordOpenContext | undefined }) {
  return <>{def.render(data, { ref: recordRef, close, reload, context })}</>;
}

export interface RecordChipProps {
  type: string;
  id: string;
  /** What the chip shows. Defaults to the id. */
  children?: ReactNode;
  className?: string | undefined;
  /** Passed to `open` on click, for the type's seed and body. */
  context?: RecordOpenContext | undefined;
}

/** A small button that opens the record's preview. Outside a provider, or for a type that is not
    registered, it renders the same text as plain text: a chip that cannot open anything is never a button. */
export function RecordChip({ type, id, children, className, context }: RecordChipProps) {
  const api = useContext(RecordPreviewContext);
  const text = children ?? id;
  if (!api || !api.supports(type)) return <span className={cx('record-chip', className)} data-inert="">{text}</span>;
  return (
    <button type="button" className={cx('record-chip', className)} aria-haspopup="dialog" onClick={() => api.open({ type, id }, context)}>
      {text}
    </button>
  );
}
