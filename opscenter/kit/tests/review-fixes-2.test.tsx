import { act, fireEvent, render, screen } from '@testing-library/react';
import { createRef } from 'react';
import type { MouseEvent } from 'react';
import { describe, expect, it, vi } from 'vitest';
import {
  AccentProvider,
  AppShell,
  CommandPalette,
  FeedStrip,
  Header,
  Menu,
  NavGroup,
  NavItem,
  Rail,
  ShortcutLayer,
  isDialogOpen,
  storageKeys,
  useShortcut,
} from '../src/index';

function Shell({ onNav }: { onNav?: (event: MouseEvent<HTMLAnchorElement>) => void }) {
  return (
    <AppShell
      rail={
        <Rail brandMark="K" brandName="Test app" version="1.0.0">
          <NavGroup label="Main">
            <NavItem href="/" label="Home" hue="brand" icon={<span>H</span>} active onClick={onNav} />
          </NavGroup>
        </Rail>
      }
      header={<Header title="Home" home={{ href: '/' }} />}
    >
      <p>Content</p>
    </AppShell>
  );
}

describe('mobile drawer is a modal layer', () => {
  it('pauses global shortcuts and the palette while open', () => {
    const onOpenChange = vi.fn();
    render(
      <>
        <Shell />
        <CommandPalette items={[]} onOpenChange={onOpenChange} />
      </>,
    );
    expect(isDialogOpen()).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    expect(isDialogOpen()).toBe(true);
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
    expect(onOpenChange).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(isDialogOpen()).toBe(false);
  });

  it('keeps the drawer open when a nav click is prevented', () => {
    render(<Shell onNav={(event) => event.preventDefault()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    const home = screen.getAllByRole('link', { name: 'Home' }).find((a) => a.classList.contains('nav-item')) as HTMLElement;
    fireEvent.click(home);
    expect(document.querySelector('.shell')?.getAttribute('data-mobile-nav')).toBe('open');
  });
});

describe('menu trigger composition', () => {
  it('keeps the trigger ref and handlers, and honours preventDefault', () => {
    const ref = createRef<HTMLButtonElement>();
    const onClick = vi.fn();
    render(
      <main>
        <Menu
          label="Actions"
          items={[{ id: 'a', label: 'Edit', onSelect: () => undefined }]}
          trigger={
            <button type="button" ref={ref} onClick={onClick}>
              More
            </button>
          }
        />
      </main>,
    );
    expect(ref.current?.textContent).toBe('More');
    fireEvent.click(screen.getByRole('button', { name: 'More' }));
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('menu')).toBeTruthy();
  });

  it('does not open when the trigger handler prevents it', () => {
    render(
      <main>
        <Menu
          label="Actions"
          items={[{ id: 'a', label: 'Edit', onSelect: () => undefined }]}
          trigger={
            <button type="button" onClick={(event) => event.preventDefault()}>
              More
            </button>
          }
        />
      </main>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'More' }));
    expect(screen.queryByRole('menu')).toBeNull();
  });
});

describe('app id grammar', () => {
  it('accepts plain ids and rejects separators', () => {
    expect(storageKeys('reports-2').buildSeen).toBe('shell.reports-2.build.seen');
    expect(() => storageKeys('a.build')).toThrow(/Invalid appId/);
    expect(() => storageKeys('a b')).toThrow(/Invalid appId/);
    expect(() => storageKeys('x'.repeat(65))).toThrow(/Invalid appId/);
  });
});

describe('accent provider', () => {
  it('restores the previous root accent on unmount', () => {
    document.documentElement.setAttribute('data-app-accent', 'teal');
    const { unmount } = render(<AccentProvider accent="violet">x</AccentProvider>);
    expect(document.documentElement.getAttribute('data-app-accent')).toBe('violet');
    unmount();
    expect(document.documentElement.getAttribute('data-app-accent')).toBe('teal');
    document.documentElement.removeAttribute('data-app-accent');
    const second = render(<AccentProvider accent="violet">x</AccentProvider>);
    second.unmount();
    expect(document.documentElement.hasAttribute('data-app-accent')).toBe(false);
  });
});

describe('feed strip interval', () => {
  it('falls back to the default for a zero interval', () => {
    vi.useFakeTimers();
    try {
      const spy = vi.spyOn(window, 'setInterval');
      render(
        <FeedStrip
          health={{ status: 'ok', label: 'All good' }}
          items={[
            { id: '1', tone: 'info', title: 'One' },
            { id: '2', tone: 'info', title: 'Two' },
          ]}
          interval={0}
          search={false}
        />,
      );
      const delays = spy.mock.calls.map((c) => c[1]);
      expect(delays.length).toBeGreaterThan(0);
      expect(delays.every((d) => typeof d === 'number' && d >= 1000)).toBe(true);
      spy.mockRestore();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('feed strip stepping', () => {
  it('steps forward and back, wraps, keeps rotating and restarts the timer on a step', () => {
    vi.useFakeTimers();
    try {
      render(
        <FeedStrip
          health={{ status: 'ok', label: 'All good' }}
          items={[
            { id: '1', tone: 'info', title: 'One' },
            { id: '2', tone: 'info', title: 'Two' },
            { id: '3', tone: 'info', title: 'Three' },
          ]}
          interval={5000}
          search={false}
        />,
      );
      const next = screen.getByRole('button', { name: 'Next item' });
      const prev = screen.getByRole('button', { name: 'Previous item' });
      expect(screen.getByText('One')).toBeTruthy();
      act(() => {
        vi.advanceTimersByTime(4000);
      });
      fireEvent.click(next);
      expect(screen.getByText('Two')).toBeTruthy();
      // The step restarted the timer: 4 seconds later the stepped item is still on screen.
      act(() => {
        vi.advanceTimersByTime(4000);
      });
      expect(screen.getByText('Two')).toBeTruthy();
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(screen.getByText('Three')).toBeTruthy();
      fireEvent.click(next);
      expect(screen.getByText('One')).toBeTruthy();
      fireEvent.click(prev);
      expect(screen.getByText('Three')).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows no step controls for a single item', () => {
    render(<FeedStrip health={{ status: 'ok', label: 'All good' }} items={[{ id: '1', tone: 'info', title: 'One' }]} search={false} />);
    expect(screen.queryByRole('button', { name: 'Next item' })).toBeNull();
  });
});

describe('shortcut sequences', () => {
  it('does not finish a sequence from inside a text field', () => {
    const handler = vi.fn();
    function Probe() {
      useShortcut({ id: 'go-home', keys: 'g h', description: 'Go home', handler });
      return <input aria-label="Field" />;
    }
    render(
      <ShortcutLayer>
        <Probe />
      </ShortcutLayer>,
    );
    fireEvent.keyDown(document.body, { key: 'g' });
    act(() => {
      screen.getByRole('textbox', { name: 'Field' }).focus();
    });
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Field' }), { key: 'h' });
    expect(handler).not.toHaveBeenCalled();
    fireEvent.keyDown(document.body, { key: 'g' });
    fireEvent.keyDown(document.body, { key: 'h' });
    expect(handler).toHaveBeenCalledTimes(1);
  });
});
