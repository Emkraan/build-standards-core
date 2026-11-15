import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AppShell, Header, NavGroup, NavItem, Rail, STORAGE_KEYS } from '../src/index';

function Shell({ pathname = '/' }: { pathname?: string }) {
  return (
    <AppShell
      pathname={pathname}
      rail={
        <Rail brandMark="K" brandName="Test app" version="2.3.1">
          <NavGroup label="Main">
            <NavItem href="/" label="Home" hue="brand" icon={<span>H</span>} active />
            <NavItem href="/devices" label="Devices" hue="blue" icon={<span>D</span>} />
          </NavGroup>
        </Rail>
      }
      header={<Header title="Home" home={{ href: '/' }} />}
    >
      <input aria-label="Search devices" />
    </AppShell>
  );
}

function shell(): HTMLElement {
  return document.querySelector('.shell') as HTMLElement;
}

describe('AppShell rail', () => {
  it('pins and unpins with [ and sets data-rail', () => {
    render(<Shell />);
    expect(shell().getAttribute('data-rail')).toBe('collapsed');
    fireEvent.keyDown(document.body, { key: '[' });
    expect(shell().getAttribute('data-rail')).toBe('pinned');
    expect(window.localStorage.getItem(STORAGE_KEYS.railPinned)).toBe('true');
    expect(screen.getByRole('button', { name: 'Pin sidebar' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.keyDown(document.body, { key: '[' });
    expect(shell().getAttribute('data-rail')).toBe('collapsed');
    expect(window.localStorage.getItem(STORAGE_KEYS.railPinned)).toBeNull();
  });

  it('ignores [ while typing in a field', () => {
    render(<Shell />);
    const input = screen.getByRole('textbox', { name: 'Search devices' });
    fireEvent.keyDown(input, { key: '[' });
    expect(shell().getAttribute('data-rail')).toBe('collapsed');
  });

  it('pins with the pin button and restores the stored pin', () => {
    window.localStorage.setItem(STORAGE_KEYS.railPinned, 'true');
    render(<Shell />);
    expect(shell().getAttribute('data-rail')).toBe('pinned');
    fireEvent.click(screen.getByRole('button', { name: 'Pin sidebar' }));
    expect(shell().getAttribute('data-rail')).toBe('collapsed');
  });

  it('opens on hover after the delay and on focus, then closes', () => {
    vi.useFakeTimers();
    try {
      render(<Shell />);
      const sidebar = screen.getByRole('complementary', { name: 'Sidebar' });
      fireEvent.pointerEnter(sidebar);
      expect(shell().getAttribute('data-rail')).toBe('collapsed');
      act(() => {
        vi.advanceTimersByTime(100);
      });
      expect(shell().getAttribute('data-rail')).toBe('open');
      fireEvent.pointerLeave(sidebar);
      act(() => {
        vi.advanceTimersByTime(300);
      });
      expect(shell().getAttribute('data-rail')).toBe('collapsed');
      fireEvent.focus(screen.getByRole('link', { name: 'Devices' }));
      expect(shell().getAttribute('data-rail')).toBe('open');
    } finally {
      vi.useRealTimers();
    }
  });

  it('marks the active link and gives nav icons their hue', () => {
    render(<Shell />);
    const home = screen.getAllByRole('link', { name: 'Home' }).find((a) => a.classList.contains('nav-item')) as HTMLElement;
    expect(home.getAttribute('aria-current')).toBe('page');
    expect(home.querySelector('.nav-icon')?.getAttribute('data-hue')).toBe('brand');
    expect(screen.getByRole('link', { name: 'Devices' }).querySelector('.nav-icon')?.getAttribute('data-hue')).toBe('blue');
    expect(document.querySelector('.nav-glider')).toBeTruthy();
  });

  it('opens the mobile drawer from the menu button and closes it on Escape and route change', () => {
    const { rerender } = render(<Shell />);
    const menu = screen.getByRole('button', { name: 'Open navigation' });
    fireEvent.click(menu);
    expect(shell().getAttribute('data-mobile-nav')).toBe('open');
    expect(menu.getAttribute('aria-expanded')).toBe('true');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(shell().getAttribute('data-mobile-nav')).toBe('closed');
    fireEvent.click(menu);
    rerender(<Shell pathname="/devices" />);
    expect(shell().getAttribute('data-mobile-nav')).toBe('closed');
  });

  it('keeps Tab inside the open mobile drawer and locks page scroll', () => {
    render(<Shell />);
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    expect(document.body.style.overflow).toBe('hidden');
    const sidebar = screen.getByRole('complementary', { name: 'Sidebar' });
    const items = Array.from(sidebar.querySelectorAll<HTMLElement>('a[href], button:not([disabled])'));
    const last = items[items.length - 1] as HTMLElement;
    last.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(sidebar.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).not.toBe(last);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(document.body.style.overflow).toBe('');
  });

  it('has one way home in the header and a plain-text brand', () => {
    render(<Shell />);
    const homeLinks = screen.getAllByRole('link', { name: 'Home' });
    expect(homeLinks.some((a) => a.classList.contains('hub-btn'))).toBe(true);
    expect(screen.getByText('Test app').closest('a')).toBeNull();
  });
});
