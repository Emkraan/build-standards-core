/* RunDialog: safe defaults, the plain-words note, "Run for real", refusals, double clicks and the form hook. */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import axe from 'axe-core';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RunDialog, RunRefusedError, runDefaults, runErrorFrom, runPublishes } from '../src';
import type { RunDialogProps, RunSpec } from '../src';
import { installMatchMedia, resetMedia } from './helpers';

beforeEach(() => {
  resetMedia();
  installMatchMedia();
});

const spec: RunSpec = {
  ref: 'branch',
  inputs: [
    { name: 'dry_run', type: 'boolean', default: true, help: 'Build only, publish nothing.' },
    { name: 'channel', type: 'choice', default: 'beta', options: ['beta', 'stable'] },
    { name: 'version', type: 'string', default: '', required: true, help: 'For example 4.2.0.' },
  ],
};
const modeSpec: RunSpec = { inputs: [{ name: 'mode', type: 'choice', default: 'dry-run', options: ['dry-run', 'apply'] }] };

function open(props: Partial<RunDialogProps> = {}) {
  const onRun = vi.fn().mockResolvedValue({});
  const onClose = vi.fn();
  const onDone = vi.fn();
  const view = render(<RunDialog open onClose={onClose} onDone={onDone} onRun={onRun} title="Run release" subtitle="release.yml" spec={spec} {...props} />);
  return { onRun, onClose, onDone, ...view };
}
const primary = (name: RegExp = /^Run( for real)?$/) => screen.getByRole('button', { name });
// The button's text is its label; a reason the button waits on follows it as hidden text.
const label = (name?: RegExp) => primary(name).firstChild?.textContent;

describe('defaults and wording', () => {
  it('opens with the dry-run settings, says nothing is published and offers Run', () => {
    open();
    expect((screen.getByRole('checkbox', { name: /Dry run/ }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText(/Defaults are the dry-run settings, nothing is published\./)).toBeTruthy();
    expect(label()).toBe('Run');
    expect(screen.getByRole('dialog', { name: 'Run release' })).toBeTruthy();
  });

  it('says plainly that the run publishes and the primary button becomes Run for real', () => {
    open();
    fireEvent.click(screen.getByRole('checkbox', { name: /Dry run/ }));
    expect(screen.getByText(/This run publishes or changes something\. Any job that writes still waits on its environment approval\./)).toBeTruthy();
    expect(screen.queryByText(/nothing is published/)).toBeNull();
    expect(label()).toBe('Run for real');
    fireEvent.click(screen.getByRole('checkbox', { name: /Dry run/ }));
    expect(label()).toBe('Run');
  });

  it('treats a mode other than dry-run as a write', () => {
    open({ spec: modeSpec });
    expect(label()).toBe('Run');
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'apply' } });
    expect(label()).toBe('Run for real');
  });

  it('takes its own rule for what publishes, and its own labels', () => {
    open({ spec: modeSpec, publishes: (v) => v['mode'] === 'dry-run', runLabel: 'Queue', realLabel: 'Queue for real' });
    expect(label(/^Queue/)).toBe('Queue for real');
  });

  it('shows the intro it is given and a branch field only for ref "branch"', () => {
    const { unmount } = open({ intro: 'Starts the workflow on the build host.', refHint: 'main, or a feature branch.' });
    expect(screen.getByText(/Starts the workflow on the build host\./)).toBeTruthy();
    expect(screen.getByRole('textbox', { name: /Branch/ })).toBeTruthy();
    unmount();
    open({ spec: modeSpec });
    expect(screen.queryByRole('textbox', { name: /Branch/ })).toBeNull();
  });
});

describe('runDefaults and runPublishes', () => {
  it('uses the spec defaults and a suggestion for an empty string input', () => {
    expect(runDefaults(spec)).toEqual({ dry_run: true, channel: 'beta', version: '' });
    expect(runDefaults(spec, { version: '4.2.0', channel: 'stable' })).toEqual({ dry_run: true, channel: 'beta', version: '4.2.0' });
  });
  it('is a write when dry_run is off or mode is not dry-run, and never for neither input', () => {
    expect(runPublishes(spec, { dry_run: false })).toBe(true);
    expect(runPublishes(spec, { dry_run: true })).toBe(false);
    expect(runPublishes(modeSpec, { mode: 'apply' })).toBe(true);
    expect(runPublishes({ inputs: [{ name: 'x', type: 'string', default: '' }] }, { x: 'y' })).toBe(false);
  });
});

describe('starting a run', () => {
  it('waits for a required input, with the reason, then sends ref and inputs and closes', async () => {
    const { onRun, onClose, onDone } = open({ suggest: {} });
    fireEvent.click(primary());
    expect(onRun).not.toHaveBeenCalled();
    expect(primary().getAttribute('aria-disabled')).toBe('true');
    expect(primary().getAttribute('data-tip')).toBe('Fill in Version');
    fireEvent.change(screen.getByRole('textbox', { name: /Version/ }), { target: { value: '4.2.0' } });
    fireEvent.change(screen.getByRole('combobox', { name: /Channel/ }), { target: { value: 'stable' } });
    fireEvent.click(primary());
    await waitFor(() => expect(onRun).toHaveBeenCalledTimes(1));
    expect(onRun).toHaveBeenCalledWith({ ref: 'main', inputs: { dry_run: true, channel: 'stable', version: '4.2.0' } });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onDone).toHaveBeenCalledWith({});
  });

  it('sends the branch typed, trimmed, and main when it is blank', async () => {
    const { onRun } = open({ suggest: { version: '1.0.0' } });
    fireEvent.change(screen.getByRole('textbox', { name: /Branch/ }), { target: { value: '  feature/x ' } });
    fireEvent.click(primary());
    await waitFor(() => expect(onRun).toHaveBeenCalledWith(expect.objectContaining({ ref: 'feature/x' })));
  });

  it('passes the server answer "already" to onDone', async () => {
    const { onDone } = open({ suggest: { version: '1' }, onRun: vi.fn().mockResolvedValue({ already: true }) });
    fireEvent.click(primary());
    await waitFor(() => expect(onDone).toHaveBeenCalledWith({ already: true }));
  });

  it('ignores a second click while the first is in flight', async () => {
    let finish: () => void = () => undefined;
    const onRun = vi.fn(() => new Promise<void>((resolveRun) => { finish = resolveRun; }));
    open({ suggest: { version: '1' }, onRun });
    fireEvent.click(primary());
    fireEvent.click(primary());
    fireEvent.click(primary());
    expect(onRun).toHaveBeenCalledTimes(1);
    await act(async () => { finish(); });
  });
});

describe('refusals and errors', () => {
  it('shows a paused item with its reason before any click, and does not run', () => {
    const { onRun } = open({ suggest: { version: '1' }, refusal: { kind: 'paused', reason: 'Paused until the freeze ends on Monday.' } });
    const note = screen.getByRole('status');
    expect(note.textContent).toContain('Paused:');
    expect(note.textContent).toContain('Paused until the freeze ends on Monday.');
    fireEvent.click(primary());
    expect(onRun).not.toHaveBeenCalled();
    expect(primary().getAttribute('data-tip')).toBe('Paused until the freeze ends on Monday.');
  });

  it('shows a running item as already running', () => {
    open({ refusal: { kind: 'running', reason: 'Run 812 is still going.' } });
    expect(screen.getByRole('status').textContent).toContain('Already running:');
  });

  it('shows a refusal thrown by the run, keeps the dialog open and keeps the reason on the button', async () => {
    const onRun = vi.fn().mockRejectedValue(new RunRefusedError('Another run of this workflow is in progress.', 'running'));
    const { onClose } = open({ suggest: { version: '1' }, onRun });
    fireEvent.click(primary());
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Another run of this workflow is in progress.'));
    expect(screen.getByRole('status').textContent).toContain('Already running:');
    expect(onClose).not.toHaveBeenCalled();
    expect(primary().getAttribute('data-tip')).toBe('Another run of this workflow is in progress.');
  });

  it('shows any other failure as an alert and allows another try', async () => {
    const onRun = vi.fn().mockRejectedValueOnce(new Error('input channel is not allowed')).mockResolvedValueOnce({});
    const { onClose } = open({ suggest: { version: '1' }, onRun });
    fireEvent.click(primary());
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('input channel is not allowed'));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(primary());
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it('maps a failed response: 409 or a kind is a refusal, else a plain error', () => {
    const a = runErrorFrom(409, { error: 'paused' });
    expect(a).toBeInstanceOf(RunRefusedError);
    expect((a as RunRefusedError).kind).toBe('refused');
    const b = runErrorFrom(400, { error: 'busy', kind: 'running' });
    expect(b).toBeInstanceOf(RunRefusedError);
    expect((b as RunRefusedError).kind).toBe('running');
    const c = runErrorFrom(400, { error: 'unknown input: foo' });
    expect(c).not.toBeInstanceOf(RunRefusedError);
    expect(c.message).toBe('unknown input: foo');
    expect(runErrorFrom(502).message).toBe('run -> 502');
  });
});

describe('reopening', () => {
  it('starts from the safe defaults again after the dialog was closed', async () => {
    const props = { onClose: vi.fn(), onRun: vi.fn(), title: 'Run release', spec, suggest: { version: '1' } };
    const { rerender } = render(<RunDialog open {...props} />);
    fireEvent.click(screen.getByRole('checkbox', { name: /Dry run/ }));
    expect(label()).toBe('Run for real');
    rerender(<RunDialog open={false} {...props} />);
    rerender(<RunDialog open {...props} />);
    await waitFor(() => expect(label()).toBe('Run'));
    expect((screen.getByRole('checkbox', { name: /Dry run/ }) as HTMLInputElement).checked).toBe(true);
  });
});

describe('accessibility and styling', () => {
  it('has no axe violations open, writing, or refused', async () => {
    const { baseElement } = open({ suggest: { version: '1' }, refusal: { kind: 'paused', reason: 'Paused.' } });
    fireEvent.click(screen.getByRole('checkbox', { name: /Dry run/ }));
    const result = await axe.run(baseElement, { rules: { 'color-contrast': { enabled: false } } });
    expect(result.violations).toEqual([]);
  });

  it('keeps the field stack and the alert box in the stylesheet', () => {
    const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');
    expect(css).toMatch(/\.run-fields \{[^}]*flex-direction: column/);
    expect(css).toMatch(/\.run-alert \{[^}]*padding:/);
  });
});
