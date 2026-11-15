import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { Toaster, useToast } from '../src/index';
import type { ToastApi } from '../src/index';

function Host({ onApi }: { onApi: (api: ToastApi) => void }) {
  const api = useToast();
  useEffect(() => {
    onApi(api);
  });
  return null;
}

describe('Toaster', () => {
  it('runs Undo once and closes the toast', async () => {
    const user = userEvent.setup();
    const undo = vi.fn();
    const h: { api: ToastApi | null } = { api: null };
    render(
      <Toaster>
        <Host onApi={(a) => (h.api = a)} />
      </Toaster>,
    );
    act(() => {
      h.api!.toast('success', 'Device archived', { action: { label: 'Undo', onClick: undo } });
    });
    expect(screen.getByRole('status').textContent).toContain('Device archived');
    await user.click(screen.getByRole('button', { name: 'Undo' }));
    expect(undo).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Device archived')).toBeNull();
  });

  it('keeps at most four, newest last, and expires on its timer', () => {
    vi.useFakeTimers();
    try {
      const h: { api: ToastApi | null } = { api: null };
      render(
        <Toaster>
          <Host onApi={(a) => (h.api = a)} />
        </Toaster>,
      );
      act(() => {
        for (let i = 1; i <= 5; i += 1) h.api!.toast('info', `Message ${i}`);
      });
      const shown = screen.getAllByRole('status').map((t) => t.querySelector('.toast-message')?.textContent);
      expect(shown).toEqual(['Message 2', 'Message 3', 'Message 4', 'Message 5']);
      act(() => {
        vi.advanceTimersByTime(5100);
      });
      expect(screen.queryAllByRole('status')).toHaveLength(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it('uses role alert for errors', () => {
    const h: { api: ToastApi | null } = { api: null };
    render(
      <Toaster>
        <Host onApi={(a) => (h.api = a)} />
      </Toaster>,
    );
    act(() => {
      h.api!.toast('error', 'Save failed', { persistent: true });
    });
    expect(screen.getByRole('alert').textContent).toContain('Save failed');
  });
});
