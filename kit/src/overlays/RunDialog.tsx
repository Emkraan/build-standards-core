/* RunDialog: start something that can publish or change data, with safe defaults (UI standard section 7,
   "Run with safe defaults"). The dialog opens with the dry-run settings, says plainly when a run will
   publish, and the primary button then reads "Run for real". The inputs and their defaults come from a
   spec the server owns and checks again: the dialog is a convenience, never the guard. A paused or
   running item is refused with a reason, shown before the run (`refusal`) or after it (the run callback
   throws RunRefusedError). The button only queues the run: environment approvals still gate any job that
   writes. The app fetches; this file knows the form, the defaults and the wording only.

   Contract with the server (the app's own code): one fixed spec per runnable thing, `{ ref?, inputs }`, every
   input named, typed and defaulted; the request carries `{ ref, inputs }`; the server refuses an unknown input
   or a value outside the spec, accepts the write from the same origin or loopback only, answers a repeated
   request inside a short window with `already: true`, and answers a paused or running item with a refusal
   (HTTP 409, `{ error, kind }`) that `runErrorFrom` turns into a RunRefusedError. */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Checkbox } from '../primitives/Choice';
import { Field, Input, Select } from '../primitives/Field';
import { Tone } from '../primitives/marks';
import { Modal } from './Modal';

export type RunInputType = 'string' | 'boolean' | 'choice';

/** One input of the run, as the server's spec lists it. */
export interface RunInput {
  name: string;
  type: RunInputType;
  /** The safe value the form opens with: dry run on, the cautious choice. */
  default: string | boolean;
  /** The values of a `choice`. */
  options?: readonly string[] | undefined;
  required?: boolean | undefined;
  /** The server's check for a string. The server is the guard, the form does not apply it. */
  pattern?: string | undefined;
  help?: string | undefined;
  /** Shown name. Default the input name with its underscores read as spaces. */
  label?: string | undefined;
}

export interface RunSpec {
  /** `branch` adds a branch field that opens on main. Default main only. */
  ref?: 'main' | 'branch' | undefined;
  inputs: readonly RunInput[];
}

export type RunValues = Record<string, string | boolean>;

export interface RunRequest {
  ref: string;
  inputs: RunValues;
}

export interface RunResult {
  /** The same run was started a moment ago and this click was folded into it. */
  already?: boolean | undefined;
}

/** Why a run cannot start: the item is paused, a run is already going, or the server said no for another reason. */
export interface RunRefusal {
  kind: string;
  reason: string;
}

/** Throw it from the run callback for a refusal; the form shows the reason and stays open. */
export class RunRefusedError extends Error {
  readonly kind: string;
  constructor(reason: string, kind = 'refused') {
    super(reason);
    this.name = 'RunRefusedError';
    this.kind = kind;
  }
}

/** Maps a failed run response to an error: 409, or a body with a `kind`, is a refusal. */
export function runErrorFrom(status: number, body: { error?: string | undefined; kind?: string | undefined } = {}): Error {
  const reason = body.error || `run -> ${status}`;
  return status === 409 || body.kind ? new RunRefusedError(reason, body.kind ?? 'refused') : new Error(reason);
}

const KIND_LABEL: Record<string, string> = { paused: 'Paused', running: 'Already running', refused: 'Refused' };
const pretty = (name: string): string => name.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
const labelOf = (i: RunInput): string => i.label ?? pretty(i.name);

/** The safe values of a spec. A string with no default takes the matching suggestion. */
export function runDefaults(spec: RunSpec, suggest?: Readonly<Record<string, string>>): RunValues {
  return Object.fromEntries(spec.inputs.map((i) => [i.name, i.type === 'string' && !i.default && suggest?.[i.name] ? (suggest[i.name] as string) : i.default]));
}

/** True when the values would publish or change something: `dry_run` turned off, or a `mode` other than `dry-run`. */
export function runPublishes(spec: RunSpec, values: RunValues): boolean {
  return spec.inputs.some((i) => (i.name === 'dry_run' && values[i.name] === false) || (i.name === 'mode' && values[i.name] !== 'dry-run'));
}

export interface UseRunFormOptions {
  spec: RunSpec;
  /** Starts the run. Resolve with the result, throw RunRefusedError for a refusal, any other error to show it. */
  onRun: (request: RunRequest) => Promise<RunResult | void>;
  /** Called after a run was queued, with its result. The dialog closes after it. */
  onDone?: ((result: RunResult) => void) | undefined;
  /** Values for string inputs that have no default, for example the current branch name. */
  suggest?: Readonly<Record<string, string>> | undefined;
  /** Replaces the rule for "this run publishes". */
  publishes?: ((values: RunValues) => boolean) | undefined;
  /** The item cannot run now (paused, already running): shown with its reason, the primary button waits. */
  refusal?: RunRefusal | undefined;
  /** Resets the form to its defaults when this turns true. Default true. */
  active?: boolean | undefined;
  runLabel?: string | undefined;
  realLabel?: string | undefined;
}

export interface RunForm {
  spec: RunSpec;
  ref: string;
  setRef: (ref: string) => void;
  values: RunValues;
  setValue: (name: string, value: string | boolean) => void;
  /** This run would publish or change something. */
  writes: boolean;
  /** Labels of required inputs that are empty. */
  missing: string[];
  busy: boolean;
  /** A refusal, from the `refusal` prop or from the last attempt. */
  refusal: RunRefusal | undefined;
  /** Any other failure of the last attempt. */
  error: string;
  /** "Run", or "Run for real" when the run writes. */
  primaryLabel: string;
  /** Why the primary button cannot be pressed yet. */
  disabledReason: string | undefined;
  submit: () => Promise<void>;
}

export function useRunForm({ spec, onRun, onDone, suggest, publishes, refusal, active = true, runLabel = 'Run', realLabel = 'Run for real' }: UseRunFormOptions): RunForm {
  const [ref, setRef] = useState('main');
  const [values, setValues] = useState<RunValues>(() => runDefaults(spec, suggest));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [refused, setRefused] = useState<RunRefusal | undefined>(undefined);
  const inFlight = useRef(false);

  useEffect(() => {
    if (!active) return;
    setRef('main');
    setValues(runDefaults(spec, suggest));
    setError('');
    setRefused(undefined);
    // Reset when the form opens; later changes of the spec or the suggestions keep what was typed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  const writes = publishes ? publishes(values) : runPublishes(spec, values);
  const missing = spec.inputs.filter((i) => i.required && !String(values[i.name] ?? '').trim()).map(labelOf);
  const shownRefusal = refusal ?? refused;
  const disabledReason = shownRefusal ? shownRefusal.reason : missing.length ? `Fill in ${missing.join(', ')}` : undefined;

  const submit = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError('');
    setRefused(undefined);
    try {
      const result = await onRun({ ref: ref.trim() || 'main', inputs: values });
      onDone?.(result ?? {});
    } catch (e) {
      if (e instanceof RunRefusedError) setRefused({ kind: e.kind, reason: e.message });
      else setError(e instanceof Error ? e.message : String(e));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }, [onRun, onDone, ref, values]);

  return {
    spec,
    ref,
    setRef,
    values,
    setValue: (name, value) => setValues((v) => ({ ...v, [name]: value })),
    writes,
    missing,
    busy,
    refusal: shownRefusal,
    error,
    primaryLabel: writes ? realLabel : runLabel,
    disabledReason,
    submit,
  };
}

export interface RunFieldsProps {
  form: RunForm;
  /** The first sentence of the note above the fields. Default "Starts the run with these inputs." */
  intro?: ReactNode;
  /** Hint under the branch field. Default "main, or a branch name." */
  refHint?: ReactNode;
}

/** The body of the dialog: the plain-words note, the branch and the inputs, the refusal and any error. */
export function RunFields({ form, intro = 'Starts the run with these inputs.', refHint = 'main, or a branch name.' }: RunFieldsProps) {
  const { spec, values, setValue, writes, refusal, error } = form;
  return (
    <div className="run-fields">
      <p className="run-note">
        {intro}{' '}
        {writes ? 'This run publishes or changes something. Any job that writes still waits on its environment approval.' : 'Defaults are the dry-run settings, nothing is published.'}
      </p>
      {refusal ? (
        <Tone hue="amber" as="p" className="run-alert" role="status" data-kind={refusal.kind}>
          <strong>{KIND_LABEL[refusal.kind] ?? KIND_LABEL['refused']}:</strong> {refusal.reason}
        </Tone>
      ) : null}
      {spec.ref === 'branch' ? (
        <Field label="Branch" hint={refHint}>
          <Input value={form.ref} onChange={(e) => form.setRef(e.target.value)} placeholder="main" />
        </Field>
      ) : null}
      {spec.inputs.map((i) =>
        i.type === 'boolean' ? (
          <Checkbox key={i.name} label={labelOf(i)} description={i.help} checked={values[i.name] === true} onCheckedChange={(c) => setValue(i.name, c)} />
        ) : i.type === 'choice' ? (
          <Field key={i.name} label={labelOf(i)} hint={i.help}>
            <Select value={String(values[i.name])} onChange={(e) => setValue(i.name, e.target.value)} options={(i.options ?? []).map((o) => ({ value: o, label: o }))} />
          </Field>
        ) : (
          <Field key={i.name} label={labelOf(i)} hint={i.help} required={i.required} optional={!i.required}>
            <Input value={String(values[i.name] ?? '')} onChange={(e) => setValue(i.name, e.target.value)} />
          </Field>
        ),
      )}
      {error ? (
        <Tone hue="red" as="p" className="run-alert" role="alert">
          {error}
        </Tone>
      ) : null}
    </div>
  );
}

export interface RunDialogProps extends Omit<UseRunFormOptions, 'active'> {
  open: boolean;
  onClose: () => void;
  /** Names the dialog, for example "Run release". */
  title: string;
  /** What is started, for example the workflow file. */
  subtitle?: ReactNode;
  intro?: RunFieldsProps['intro'];
  refHint?: RunFieldsProps['refHint'];
  cancelLabel?: string | undefined;
}

export function RunDialog({ open, onClose, title, subtitle, intro, refHint, cancelLabel = 'Cancel', onDone, ...options }: RunDialogProps) {
  const form = useRunForm({
    ...options,
    active: open,
    onDone: (result) => {
      onDone?.(result);
      onClose();
    },
  });
  return (
    <Modal
      open={open}
      onClose={onClose}
      busy={form.busy}
      title={title}
      subtitle={subtitle}
      hue={form.writes ? 'amber' : 'blue'}
      primaryAction={{
        label: form.primaryLabel,
        onClick: () => void form.submit(),
        loading: form.busy,
        ...(form.disabledReason ? { disabledReason: form.disabledReason } : {}),
      }}
      cancelLabel={cancelLabel}
    >
      <RunFields form={form} intro={intro} refHint={refHint} />
    </Modal>
  );
}
