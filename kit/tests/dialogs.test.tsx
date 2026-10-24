import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { useConfirm, usePrompt } from '../src/index';
import type { ConfirmApi, PromptApi } from '../src/index';

function ConfirmHost({ onApi }: { onApi: (api: ConfirmApi) => void }) {
  const api = useConfirm();
  useEffect(() => {
    onApi(api);
  });
  return <>{api.dialog}</>;
}

function PromptHost({ onApi }: { onApi: (api: PromptApi) => void }) {
  const api = usePrompt();
  useEffect(() => {
    onApi(api);
  });
  return <>{api.dialog}</>;
}

describe('useConfirm', () => {
  it('resolves true on the verb and false on Cancel or Escape', async () => {
    const user = userEvent.setup();
    const h: { api: ConfirmApi | null } = { api: null };
    render(<ConfirmHost onApi={(a) => (h.api = a)} />);
    let pending!: Promise<boolean>;
    act(() => {
      pending = h.api!.confirm({ title: 'Delete this schedule?', body: 'This cannot be undone.', confirmLabel: 'Delete', danger: true });
    });
    const dialog = await screen.findByRole('alertdialog', { name: 'Delete this schedule?' });
    expect(dialog.textContent).toContain('This cannot be undone.');
    expect(document.activeElement?.textContent).toBe('Cancel');
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    await expect(pending).resolves.toBe(true);

    act(() => {
      pending = h.api!.confirm({ title: 'Remove the rule?', confirmLabel: 'Remove' });
    });
    await user.click(await screen.findByRole('button', { name: 'Cancel' }));
    await expect(pending).resolves.toBe(false);

    act(() => {
      pending = h.api!.confirm({ title: 'Archive it?', confirmLabel: 'Archive' });
    });
    await screen.findByRole('alertdialog');
    await user.keyboard('{Escape}');
    await expect(pending).resolves.toBe(false);
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
  });
});

describe('useConfirm action and validate (D-005)', () => {
  it('runs the action inside the dialog, shows busy, and resolves true only after it succeeds', async () => {
    const user = userEvent.setup();
    const h: { api: ConfirmApi | null } = { api: null };
    render(<ConfirmHost onApi={(a) => (h.api = a)} />);
    let finish!: () => void;
    const action = vi.fn(() => new Promise<void>((resolve) => (finish = resolve)));
    let pending!: Promise<boolean>;
    let settled = false;
    act(() => {
      pending = h.api!.confirm({ title: 'Delete the schedule?', confirmLabel: 'Delete', danger: true, action });
      void pending.then(() => (settled = true));
    });
    await user.click(await screen.findByRole('button', { name: 'Delete' }));
    expect(action).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('alertdialog')).toBeTruthy();
    expect((screen.getByRole('button', { name: /Delete/ }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Cancel' }) as HTMLButtonElement).disabled).toBe(true);
    expect(settled).toBe(false);
    await act(async () => finish());
    await expect(pending).resolves.toBe(true);
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
  });

  it('a failed action keeps the dialog open with the error inline, and a retry can succeed', async () => {
    const user = userEvent.setup();
    const h: { api: ConfirmApi | null } = { api: null };
    render(<ConfirmHost onApi={(a) => (h.api = a)} />);
    let calls = 0;
    const action = () => {
      calls += 1;
      return calls === 1 ? Promise.reject(new Error('The server refused the delete.')) : Promise.resolve();
    };
    let pending!: Promise<boolean>;
    act(() => {
      pending = h.api!.confirm({ title: 'Delete the schedule?', confirmLabel: 'Delete', action });
    });
    await user.click(await screen.findByRole('button', { name: 'Delete' }));
    expect((await screen.findByRole('alert')).textContent).toBe('The server refused the delete.');
    expect(screen.getByRole('alertdialog')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    await expect(pending).resolves.toBe(true);
  });

  it('validate keeps the dialog open on an error and never runs the action', async () => {
    const user = userEvent.setup();
    const h: { api: ConfirmApi | null } = { api: null };
    render(<ConfirmHost onApi={(a) => (h.api = a)} />);
    const action = vi.fn();
    act(() => {
      void h.api!.confirm({ title: 'Save the rule?', confirmLabel: 'Save', validate: () => 'Pick a schedule first.', action });
    });
    await user.click(await screen.findByRole('button', { name: 'Save' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Pick a schedule first.');
    expect(action).not.toHaveBeenCalled();
    expect(screen.getByRole('alertdialog')).toBeTruthy();
  });

  it('without action or validate it still resolves true at once (default unchanged)', async () => {
    const user = userEvent.setup();
    const h: { api: ConfirmApi | null } = { api: null };
    render(<ConfirmHost onApi={(a) => (h.api = a)} />);
    let pending!: Promise<boolean>;
    act(() => {
      pending = h.api!.confirm({ title: 'Archive it?', confirmLabel: 'Archive' });
    });
    await user.click(await screen.findByRole('button', { name: 'Archive' }));
    await expect(pending).resolves.toBe(true);
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('usePrompt', () => {
  it('resolves the trimmed value, null on cancel, and blocks invalid input', async () => {
    const user = userEvent.setup();
    const h: { api: PromptApi | null } = { api: null };
    render(<PromptHost onApi={(a) => (h.api = a)} />);
    let pending!: Promise<string | null>;
    act(() => {
      pending = h.api!.prompt({ title: 'Rename group', label: 'Group name', validate: (v) => (v.length < 3 ? 'Use at least 3 characters.' : null) });
    });
    const input = await screen.findByLabelText('Group name');
    expect(document.activeElement).toBe(input);
    await user.type(input, 'ab{Enter}');
    expect(screen.getByText('Use at least 3 characters.')).toBeTruthy();
    expect(input.getAttribute('aria-invalid')).toBe('true');
    await user.clear(input);
    await user.type(input, '  Kiosk fleet  {Enter}');
    await expect(pending).resolves.toBe('Kiosk fleet');

    act(() => {
      pending = h.api!.prompt({ title: 'Rename again', label: 'Name', initialValue: 'Lab' });
    });
    await user.click(await screen.findByRole('button', { name: 'Cancel' }));
    await expect(pending).resolves.toBeNull();
  });
});
