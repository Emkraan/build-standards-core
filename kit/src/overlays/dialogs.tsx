/* useConfirm and usePrompt: promise-based replacements for the browser's native dialogs (rules 7 and 8
   of the UI standard). Render the returned `dialog` once, then await the function. */

import { useCallback, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { IconWarning } from '../icons/icons';
import type { MarkHue } from '../lib/hues';
import { Button } from '../primitives/Button';
import { Field, Input } from '../primitives/Field';
import { Modal } from './Modal';

export interface ConfirmOptions {
  /** A question: "Delete this schedule?" */
  title: string;
  /** The consequence in plain words: "Everyone on it stops getting reminders. This cannot be undone." */
  body?: ReactNode;
  /** The verb: "Delete". */
  confirmLabel?: string | undefined;
  cancelLabel?: string | undefined;
  /** Destructive: danger button, and Cancel takes the initial focus. */
  danger?: boolean | undefined;
  icon?: ReactNode;
  hue?: MarkHue | undefined;
  /** Typed confirmation for an irreversible action: the confirm button stays disabled until the
      operator types this text exactly (for example the name of what is being deleted). */
  requireText?: string | undefined;
  /** Label over the typed-confirmation field. Default "Type <requireText> to confirm". */
  requireTextLabel?: string | undefined;
}

export interface ConfirmApi {
  confirm: (options: ConfirmOptions) => Promise<boolean>;
  dialog: ReactNode;
}

interface Pending<O, R> {
  options: O;
  resolve: (value: R) => void;
}

/** Returns { confirm, dialog }. Render the dialog once, then await confirm(options) for true or false. */
export function useConfirm(): ConfirmApi {
  const [pending, setPending] = useState<Pending<ConfirmOptions, boolean> | null>(null);
  const pendingRef = useRef<Pending<ConfirmOptions, boolean> | null>(null);
  const lastOptions = useRef<ConfirmOptions | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const confirmRef = useRef<HTMLButtonElement | null>(null);
  const [typed, setTyped] = useState('');
  if (pending) lastOptions.current = pending.options;

  const settle = useCallback((value: boolean) => {
    const current = pendingRef.current;
    if (!current) return;
    pendingRef.current = null;
    setPending(null);
    current.resolve(value);
  }, []);

  const confirm = useCallback((options: ConfirmOptions) => {
    pendingRef.current?.resolve(false);
    setTyped('');
    return new Promise<boolean>((resolve) => {
      const next = { options, resolve };
      pendingRef.current = next;
      setPending(next);
    });
  }, []);

  const o = pending?.options ?? lastOptions.current;
  const typedOk = o?.requireText === undefined || typed === o.requireText;
  const dialog = (
    <Modal
      open={pending !== null}
      onClose={() => settle(false)}
      role="alertdialog"
      size="sm"
      title={o?.title ?? ''}
      icon={o?.icon ?? (o?.danger ? <IconWarning /> : undefined)}
      hue={o?.hue ?? (o?.danger ? 'red' : 'blue')}
      initialFocusRef={o?.requireText !== undefined ? undefined : o?.danger ? cancelRef : confirmRef}
      footer={
        <div className="modal-foot">
          <div className="modal-foot-start" />
          <Button ref={cancelRef} variant="secondary" onClick={() => settle(false)}>
            {o?.cancelLabel ?? 'Cancel'}
          </Button>
          <Button
            ref={confirmRef}
            variant={o?.danger ? 'danger' : 'primary'}
            disabled={!typedOk}
            onClick={() => {
              if (typedOk) settle(true);
            }}
          >
            {o?.confirmLabel ?? 'Confirm'}
          </Button>
        </div>
      }
    >
      {o?.body ? <div className="modal-text">{o.body}</div> : null}
      {o?.requireText !== undefined ? (
        <Field label={o.requireTextLabel ?? `Type ${o.requireText} to confirm`}>
          <Input
            value={typed}
            autoComplete="off"
            spellCheck={false}
            data-autofocus=""
            onChange={(event) => setTyped(event.target.value)}
          />
        </Field>
      ) : null}
    </Modal>
  );

  return { confirm, dialog };
}

export interface PromptOptions {
  title: string;
  /** Visible label of the field. */
  label: string;
  body?: ReactNode;
  initialValue?: string | undefined;
  placeholder?: string | undefined;
  hint?: ReactNode;
  confirmLabel?: string | undefined;
  cancelLabel?: string | undefined;
  /** Return an error message to block submit, or null when the value is fine. */
  validate?: ((value: string) => string | null) | undefined;
  maxLength?: number | undefined;
  required?: boolean | undefined;
}

export interface PromptApi {
  prompt: (options: PromptOptions) => Promise<string | null>;
  dialog: ReactNode;
}

/** Returns { prompt, dialog }. The promise resolves to the trimmed value, or null on cancel. */
export function usePrompt(): PromptApi {
  const [pending, setPending] = useState<Pending<PromptOptions, string | null> | null>(null);
  const pendingRef = useRef<Pending<PromptOptions, string | null> | null>(null);
  const lastOptions = useRef<PromptOptions | null>(null);
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  if (pending) lastOptions.current = pending.options;

  const settle = useCallback((result: string | null) => {
    const current = pendingRef.current;
    if (!current) return;
    pendingRef.current = null;
    setPending(null);
    current.resolve(result);
  }, []);

  const prompt = useCallback((options: PromptOptions) => {
    pendingRef.current?.resolve(null);
    setValue(options.initialValue ?? '');
    setError(null);
    return new Promise<string | null>((resolve) => {
      const next = { options, resolve };
      pendingRef.current = next;
      setPending(next);
    });
  }, []);

  const o = pending?.options ?? lastOptions.current;
  const submit = () => {
    const trimmed = value.trim();
    if (o?.required !== false && trimmed === '') {
      setError('Enter a value.');
      return;
    }
    const problem = o?.validate?.(trimmed) ?? null;
    if (problem) {
      setError(problem);
      return;
    }
    settle(trimmed);
  };

  const dialog = (
    <Modal
      open={pending !== null}
      onClose={() => settle(null)}
      size="sm"
      title={o?.title ?? ''}
      onSubmit={submit}
      cancelLabel={o?.cancelLabel ?? 'Cancel'}
      primaryAction={{ label: o?.confirmLabel ?? 'Save' }}
    >
      {o?.body ? <div className="modal-text">{o.body}</div> : null}
      <Field
        label={o?.label ?? ''}
        hint={o?.hint}
        error={error ?? undefined}
        counter={o?.maxLength ? { value: value.length, max: o.maxLength } : undefined}
      >
        <Input
          value={value}
          placeholder={o?.placeholder}
          maxLength={o?.maxLength}
          data-autofocus=""
          onChange={(event) => {
            setValue(event.target.value);
            if (error) setError(null);
          }}
        />
      </Field>
    </Modal>
  );

  return { prompt, dialog };
}
