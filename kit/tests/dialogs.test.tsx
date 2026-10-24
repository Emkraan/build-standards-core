import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect } from 'react';
import { describe, expect, it } from 'vitest';
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
