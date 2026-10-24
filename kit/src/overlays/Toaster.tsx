/* Toaster and useToast (UI standard section 7, rule 8). Bottom-right stack above dialogs, newest
   last, up to four. Hovering or focusing a toast pauses its timer. A toast takes one action, and
   `action: { label: 'Undo', onClick }` is how reversible changes apply at once and stay undoable.
   Toasts dedupe by id only, never by message text: pass `id` to update one toast in place (a
   repeated save, a progress line), and every call without an id is a new toast, so the same text
   twice or a JSX message always shows. */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { IconAlert, IconCheckCircle, IconClose, IconInfo, IconWarning } from '../icons/icons';
import { isBrowser } from '../lib/env';
import { TOAST_ACTION_DURATION, TOAST_DURATION } from '../lib/timing';

export type ToastVariant = 'success' | 'error' | 'warning' | 'info';

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastOptions {
  description?: ReactNode;
  /** One action. Clicking it runs the callback and dismisses the toast. */
  action?: ToastAction | undefined;
  /** Stays until dismissed. */
  persistent?: boolean | undefined;
  /** Lifetime in ms. Default 5s, or 8s when the toast has an action. */
  duration?: number | undefined;
  /** Stable id. A toast with this id on screen is replaced in place (new message, options and a
      fresh timer) instead of stacking a second one. Omit it and every call is a new toast. */
  id?: string | undefined;
}

export interface ToastApi {
  /** Shows a toast and returns its id. */
  toast: (variant: ToastVariant, message: ReactNode, options?: ToastOptions) => string;
  dismiss: (id: string) => void;
}

interface ToastEntry extends ToastOptions {
  id: string;
  /** Internal identity: caller ids and generated ids live in separate spaces, so a generated id
      can never replace a caller's toast (or the other way round). */
  key: string;
  variant: ToastVariant;
  message: ReactNode;
  /** Bumps on every update of the same id, so the item restarts its timer in place. */
  rev: number;
}

const ToastContext = createContext<ToastApi | null>(null);

const ICONS: Record<ToastVariant, ReactNode> = {
  success: <IconCheckCircle />,
  error: <IconAlert />,
  warning: <IconWarning />,
  info: <IconInfo />,
};

let counter = 0;

export interface ToasterProps {
  children?: ReactNode;
  /** Most toasts on screen at once. The oldest leaves first. Default 4. */
  max?: number | undefined;
  /** Accessible name of the toast region. */
  label?: string | undefined;
  dismissLabel?: string | undefined;
}

/** Provides useToast to the tree and renders the toast stack. Mount once near the root. */
export function Toaster({ children, max = 4, label = 'Notifications', dismissLabel = 'Dismiss notification' }: ToasterProps) {
  const [toasts, setToasts] = useState<ToastEntry[]>([]);

  const dismiss = useCallback((id: string) => {
    setToasts((list) => list.filter((t) => t.id !== id));
  }, []);

  // The stack's own timers and buttons dismiss by the internal key, never by the public id.
  const dismissKey = useCallback((key: string) => {
    setToasts((list) => list.filter((t) => t.key !== key));
  }, []);

  const toast = useCallback(
    (variant: ToastVariant, message: ReactNode, options: ToastOptions = {}) => {
      counter += 1;
      const id = options.id ?? `toast-${counter}`;
      const key = options.id !== undefined ? `id:${options.id}` : `auto:${counter}`;
      const rev = counter;
      setToasts((list) => {
        const entry: ToastEntry = { ...options, id, key, variant, message, rev };
        const at = list.findIndex((t) => t.key === key);
        if (at < 0) return [...list, entry].slice(-max);
        const next = list.slice();
        next[at] = entry;
        return next;
      });
      return id;
    },
    [max],
  );

  const api = useMemo<ToastApi>(() => ({ toast, dismiss }), [toast, dismiss]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      {isBrowser
        ? createPortal(
            <section className="toast-region" aria-label={label}>
              {toasts.map((t) => (
                <ToastItem key={t.key} entry={t} onDismiss={dismissKey} dismissLabel={dismissLabel} />
              ))}
            </section>,
            document.body,
          )
        : null}
    </ToastContext.Provider>
  );
}

interface ToastItemProps {
  entry: ToastEntry;
  /** Called with the entry's internal key. */
  onDismiss: (key: string) => void;
  dismissLabel: string;
}

function ToastItem({ entry, onDismiss, dismissLabel }: ToastItemProps) {
  const [paused, setPaused] = useState(false);
  const life = entry.duration ?? (entry.action ? TOAST_ACTION_DURATION : TOAST_DURATION);
  const remaining = useRef(life);
  const started = useRef(0);
  const shownRev = useRef(entry.rev);

  useEffect(() => {
    if (shownRev.current !== entry.rev) {
      // Updated in place under the same id: a fresh lifetime for the new message.
      shownRev.current = entry.rev;
      remaining.current = life;
    }
    if (entry.persistent || paused) return undefined;
    started.current = Date.now();
    const t = window.setTimeout(() => onDismiss(entry.key), remaining.current);
    return () => {
      window.clearTimeout(t);
      remaining.current = Math.max(0, remaining.current - (Date.now() - started.current));
    };
  }, [entry.key, entry.rev, entry.persistent, paused, onDismiss, life]);

  return (
    <div
      className="toast"
      data-variant={entry.variant}
      role={entry.variant === 'error' ? 'alert' : 'status'}
      onPointerEnter={() => setPaused(true)}
      onPointerLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={(event) => {
        if (!(event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget))) setPaused(false);
      }}
    >
      <span className="toast-icon" aria-hidden="true">
        {ICONS[entry.variant]}
      </span>
      <div className="toast-text">
        <p className="toast-message">{entry.message}</p>
        {entry.description ? <p className="toast-desc">{entry.description}</p> : null}
      </div>
      {entry.action ? (
        <button
          type="button"
          className="toast-action"
          onClick={() => {
            entry.action?.onClick();
            onDismiss(entry.key);
          }}
        >
          {entry.action.label}
        </button>
      ) : null}
      <button type="button" className="toast-close" aria-label={dismissLabel} onClick={() => onDismiss(entry.key)}>
        <IconClose size={14} />
      </button>
    </div>
  );
}

/** Returns { toast, dismiss }. Example: toast('success', 'Saved', { action: { label: 'Undo', onClick } }). */
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside <Toaster>.');
  return ctx;
}
