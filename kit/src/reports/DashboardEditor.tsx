/* DashboardEditor: edit mode for a dashboard definition (R2, definitions are data). Viewing a dashboard never asks for
   criteria; building one does, so it lives on its own screen: a name, a description, the definition as JSON with its
   problems named before a save, a live preview, add panel, save, reset to the shipped copy and delete (after a
   confirm). The kit knows no store: the app saves, resets, deletes and runs the preview, and shows what comes back. */

import { useMemo, useState } from 'react';
import { useConfirm } from '../overlays/dialogs';
import { Button } from '../primitives/Button';
import { Field, Input, Select, Textarea } from '../primitives/Field';
import { Dashboard } from './Dashboard';
import { PANEL_LABEL, PANEL_TYPES, newPanel, validateDefinition } from './definitions';
import type { DashboardDefinition, DashboardRun, PanelType } from './types';

export interface DashboardEditorProps {
  /** The definition to start from (a blank one for a new dashboard). */
  definition: DashboardDefinition;
  /** True for a dashboard that is already saved: key is fixed, reset and delete can show. */
  existing?: boolean | undefined;
  /** Shipped with the app and edited since: Reset to shipped shows. */
  modified?: boolean | undefined;
  /** The streams the app can read, for a new panel. The first is used. */
  streams?: readonly string[] | undefined;
  /** The measure a new panel starts with. Default `rows`. */
  defaultMeasure?: string | undefined;
  /** Saves the definition. Reject with the server's message to show it. */
  onSave: (definition: DashboardDefinition) => Promise<unknown> | void;
  /** Runs the definition for the preview. Absent: no Preview button. */
  onPreview?: ((definition: DashboardDefinition) => Promise<DashboardRun>) | undefined;
  onReset?: (() => Promise<unknown> | void) | undefined;
  onDelete?: (() => Promise<unknown> | void) | undefined;
  onClose: () => void;
  /** Explains the measures and streams, shown above the form. */
  help?: string | undefined;
  className?: string | undefined;
}

function parse(text: string): { value?: DashboardDefinition; problems: string[] } {
  try {
    const value = JSON.parse(text) as DashboardDefinition;
    return { value, problems: validateDefinition(value) };
  } catch (e) {
    return { problems: [`not valid JSON: ${e instanceof Error ? e.message : 'unreadable'}`] };
  }
}

export function DashboardEditor({ definition, existing, modified, streams = [], defaultMeasure = 'rows', onSave, onPreview, onReset, onDelete, onClose, help, className }: DashboardEditorProps) {
  const { confirm, dialog } = useConfirm();
  const [text, setText] = useState(() => JSON.stringify(definition, null, 2));
  const [addType, setAddType] = useState<PanelType>('stat');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState<{ def: DashboardDefinition; run: DashboardRun } | null>(null);
  const parsed = useMemo(() => parse(text), [text]);
  // The title and description live in the JSON; these fields edit it, so there is one source of truth.
  const title = parsed.value?.title ?? '';
  const description = parsed.value?.description ?? '';
  const edit = (patch: Partial<DashboardDefinition>) => {
    if (parsed.value) setText(JSON.stringify({ ...parsed.value, ...patch }, null, 2));
  };

  const guard = async (fn: () => Promise<unknown> | void) => {
    setBusy(true);
    setError('');
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const save = () => {
    if (!parsed.value || parsed.problems.length) return;
    const def = parsed.value;
    void guard(() => onSave(def));
  };
  const runPreview = () => {
    const def = parsed.value;
    if (!def || parsed.problems.length || !onPreview) return;
    void guard(async () => setPreview({ def, run: await onPreview(def) }));
  };
  const addPanel = () => {
    if (!parsed.value) return;
    const stream = streams[0];
    if (!stream) {
      setError('There are no streams to read from yet');
      return;
    }
    setError('');
    const panels = [...(parsed.value.panels ?? []), newPanel(addType, stream, defaultMeasure, (parsed.value.panels?.length ?? 0) + 1)];
    setText(JSON.stringify({ ...parsed.value, panels }, null, 2));
  };
  const remove = async () => {
    const ok = await confirm({ title: 'Delete dashboard', body: `Delete ${title || 'this dashboard'}?${modified ? ' A shipped dashboard can be brought back by restoring the defaults.' : ''}`, confirmLabel: 'Delete', danger: true });
    if (ok && onDelete) void guard(() => onDelete());
  };

  const bad = parsed.problems.length > 0;
  return (
    <div className={['dash-editor', className].filter(Boolean).join(' ')}>
      {dialog}
      {help ? <p className="dash-desc">{help}</p> : null}
      <div className="dash-editor-names">
        <Field label="Name">
          <Input value={title} onChange={(e) => edit({ title: e.target.value })} disabled={!parsed.value} />
        </Field>
        <Field label="Description" optional>
          <Input value={description} onChange={(e) => edit({ description: e.target.value })} disabled={!parsed.value} />
        </Field>
      </div>
      <Field label="Definition (JSON)" hint={existing ? 'The key stays the same for a saved dashboard.' : 'The key is the address of the dashboard: lowercase letters, digits, dashes.'}>
        <Textarea className="dash-editor-json" rows={20} spellCheck={false} value={text} onChange={(e) => setText(e.target.value)} aria-invalid={bad || undefined} aria-describedby={bad ? 'dash-editor-problems' : undefined} />
      </Field>
      {bad ? (
        <div id="dash-editor-problems" role="alert">
          <ul className="dash-editor-problems">
            {parsed.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {error ? (
        <p className="dash-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="dash-editor-actions">
        <Button variant="primary" loading={busy} disabled={bad} onClick={save}>
          Save
        </Button>
        {onPreview ? (
          <Button disabled={bad || busy} onClick={runPreview}>
            Preview
          </Button>
        ) : null}
        <Select size="sm" aria-label="Panel type" value={addType} onChange={(e) => setAddType(e.target.value as PanelType)} options={PANEL_TYPES.map((t) => ({ value: t, label: PANEL_LABEL[t] }))} />
        <Button data-act="create" disabled={!parsed.value} onClick={addPanel}>
          Add panel
        </Button>
        <Button onClick={onClose}>Close</Button>
        {existing && modified && onReset ? (
          <Button disabled={busy} onClick={() => void guard(() => onReset())}>
            Reset to shipped
          </Button>
        ) : null}
        {existing && onDelete ? (
          <Button variant="danger-subtle" disabled={busy} onClick={() => void remove()}>
            Delete
          </Button>
        ) : null}
      </div>
      {preview ? <Dashboard definition={preview.def} run={preview.run} picks={{}} onPicks={() => undefined} className="dash-editor-preview" /> : null}
    </div>
  );
}
