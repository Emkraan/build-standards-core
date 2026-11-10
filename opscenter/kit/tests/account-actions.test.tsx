import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { AccountMenu, ThemeProvider } from '../src/index';

const who = { name: 'Ada Example', email: 'ada@example.com', role: 'Operator' };

function open() {
  fireEvent.click(screen.getByRole('button', { name: /Account: Ada Example/ }));
}

describe('AccountMenu actions and status (D-004)', () => {
  it('without actions or status renders neither (default unchanged)', () => {
    const { container } = render(
      <ThemeProvider>
        <AccountMenu identity={who} onSignOut={() => undefined} />
      </ThemeProvider>,
    );
    open();
    expect(document.querySelector('.account-actions')).toBeNull();
    expect(document.querySelector('.account-status')).toBeNull();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeTruthy();
    expect(container).toBeTruthy();
  });

  it('runs an action, keeps the panel open and announces the status', () => {
    function Host() {
      const [status, setStatus] = useState('');
      return (
        <ThemeProvider>
          <AccountMenu
            identity={who}
            onSignOut={() => undefined}
            status={status}
            actions={[{ key: 'refresh', label: 'Refresh permissions', onSelect: () => setStatus('Permissions refreshed') }]}
          />
        </ThemeProvider>
      );
    }
    render(<Host />);
    open();
    const live = document.querySelector('.account-status') as HTMLElement;
    expect(live.getAttribute('aria-live')).toBe('polite');
    fireEvent.click(screen.getByRole('button', { name: 'Refresh permissions' }));
    expect(screen.getByText('Permissions refreshed')).toBeTruthy();
    // Still open: Sign out is still on screen.
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeTruthy();
  });

  it('a busy action does not run again', () => {
    const run = vi.fn();
    render(
      <ThemeProvider>
        <AccountMenu identity={who} actions={[{ key: 'r', label: 'Refresh permissions', onSelect: run, busy: true }]} />
      </ThemeProvider>,
    );
    open();
    fireEvent.click(screen.getByRole('button', { name: /Refresh permissions/ }));
    expect(run).not.toHaveBeenCalled();
  });
});
