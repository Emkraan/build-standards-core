import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AccentProvider, STORAGE_KEYS, ThemeProvider, ThemeToggle, getAppAccent, setAppAccent, themeInitScript } from '../src/index';
import { media } from './helpers';

afterEach(() => {
  Reflect.deleteProperty(document, 'startViewTransition');
});

describe('ThemeToggle withSystem (D-001)', () => {
  it('without withSystem stays the single flip button', () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.queryByRole('group', { name: 'Theme' })).toBeNull();
  });

  it('offers Light, System and Dark, and returns to following the OS', () => {
    render(
      <ThemeProvider>
        <ThemeToggle withSystem />
      </ThemeProvider>,
    );
    expect(screen.getByRole('group', { name: 'Theme' })).toBeTruthy();
    const system = screen.getByRole('button', { name: 'System' });
    expect(system.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'Dark' }));
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(window.localStorage.getItem(STORAGE_KEYS.theme)).toBe('dark');
    expect(screen.getByRole('button', { name: 'Dark' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'System' }));
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    expect(window.localStorage.getItem(STORAGE_KEYS.theme)).toBe('system');
    expect(screen.getByRole('button', { name: 'System' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('takes its own labels', () => {
    render(
      <ThemeProvider>
        <ThemeToggle withSystem groupLabel="Appearance" lightLabel="Day" systemLabel="Auto" darkLabel="Night" />
      </ThemeProvider>,
    );
    expect(screen.getByRole('group', { name: 'Appearance' })).toBeTruthy();
    for (const name of ['Day', 'Auto', 'Night']) expect(screen.getByRole('button', { name })).toBeTruthy();
  });
});

describe('ThemeToggle', () => {
  it('sets data-theme on html and persists the choice', () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Switch to light theme' }));
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    expect(window.localStorage.getItem(STORAGE_KEYS.theme)).toBe('light');
    fireEvent.click(screen.getByRole('button', { name: 'Switch to dark theme' }));
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(window.localStorage.getItem(STORAGE_KEYS.theme)).toBe('dark');
  });

  it('restores the stored choice and follows the OS when nothing is stored', () => {
    window.localStorage.setItem(STORAGE_KEYS.theme, 'light');
    const { unmount } = render(<ThemeProvider />);
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    unmount();
    window.localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
    media.light = true;
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    expect(screen.getByRole('button', { name: 'Switch to dark theme' })).toBeTruthy();
  });

  it('reveals through a view transition, and swaps instantly under reduced motion', () => {
    const start = vi.fn((cb: () => void) => {
      cb();
      return { ready: Promise.resolve() };
    });
    Object.defineProperty(document, 'startViewTransition', { configurable: true, writable: true, value: start });
    document.documentElement.animate = vi.fn() as unknown as typeof document.documentElement.animate;
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Switch to light theme' }));
    expect(start).toHaveBeenCalledTimes(1);
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    media.reducedMotion = true;
    fireEvent.click(screen.getByRole('button', { name: 'Switch to dark theme' }));
    expect(start).toHaveBeenCalledTimes(1);
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });

  it('ships a pre-paint init script for the stored theme', () => {
    expect(themeInitScript()).toContain(JSON.stringify(STORAGE_KEYS.theme));
  });
});

describe('accent', () => {
  it('sets data-app-accent once on the root, and cobalt removes it', () => {
    const { rerender } = render(<AccentProvider accent="teal" />);
    expect(document.documentElement.getAttribute('data-app-accent')).toBe('teal');
    expect(getAppAccent()).toBe('teal');
    rerender(<AccentProvider accent="cobalt" />);
    expect(document.documentElement.hasAttribute('data-app-accent')).toBe(false);
    setAppAccent('gold');
    expect(getAppAccent()).toBe('gold');
  });
});
