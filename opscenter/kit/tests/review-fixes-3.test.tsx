import { act, fireEvent, render, renderHook, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  AppShell,
  CommandPalette,
  DefaultLink,
  Header,
  Menu,
  NavGroup,
  NavItem,
  Rail,
  isDialogOpen,
  openCommandPalette,
  safeHref,
  useNow,
} from '../src/index';
import type { KitLinkProps } from '../src/index';
import { resetSafeHrefWarning } from '../src/lib/url';

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  resetSafeHrefWarning();
});

describe('safeHref', () => {
  it.each(['/', '/devices?id=3', 'devices', '../up', '#main', '?q=1', 'https://example.com/a', 'HTTP://example.com', 'mailto:a@example.com', 'tel:+15550100'])(
    'keeps %s',
    (url) => {
      expect(safeHref(url)).toBe(url);
    },
  );

  it.each([
    'javascript:alert(1)',
    'JavaScript:alert(1)',
    '  javascript:alert(1)',
    'java\tscript:alert(1)',
    'java\nscript:alert(1)',
    '\u0001javascript:alert(1)',
    'data:text/html,<p>x</p>',
    'vbscript:msgbox(1)',
    'file:///etc/hosts',
  ])('blocks %j', (url) => {
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    expect(safeHref(url)).toBeUndefined();
  });

  it('returns undefined for empty input and warns only once', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    expect(safeHref('')).toBeUndefined();
    expect(safeHref(undefined)).toBeUndefined();
    expect(warn).not.toHaveBeenCalled();
    safeHref('javascript:void(0)');
    safeHref('data:,x');
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it('trims and strips control characters from a safe URL', () => {
    expect(safeHref('  /devices\n')).toBe('/devices');
  });
});

describe('kit links never render an unsafe href', () => {
  function Shell({ link }: { link?: (props: KitLinkProps) => ReactNode }) {
    return (
      <AppShell
        linkComponent={link}
        rail={
          <Rail brandMark="K" brandName="Test app" version="1.0.0">
            <NavGroup label="Main">
              <NavItem href="javascript:alert(1)" label="Bad" />
              <NavItem href="/good" label="Good" />
            </NavGroup>
          </Rail>
        }
        header={<Header title="Home" home={{ href: ' JAVASCRIPT:alert(1)', label: 'Hub' }} />}
      >
        <p>Content</p>
      </AppShell>
    );
  }

  it('drops the href with the default link', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    render(<Shell />);
    const bad = screen.getByText('Bad').closest('a') as HTMLAnchorElement;
    expect(bad.hasAttribute('href')).toBe(false);
    const hub = screen.getByText('Hub').closest('a') as HTMLAnchorElement;
    expect(hub.hasAttribute('href')).toBe(false);
    expect((screen.getByText('Good').closest('a') as HTMLAnchorElement).getAttribute('href')).toBe('/good');
  });

  it('never hands an unsafe href to a router adapter', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const seen: string[] = [];
    const RouterLink = ({ href, ...rest }: KitLinkProps) => {
      seen.push(href);
      return <a {...rest} href={href} data-router="" />;
    };
    render(<Shell link={RouterLink} />);
    expect(seen).toEqual(['/good']);
    expect(document.querySelectorAll('a[href^="javascript" i], a[href*="script:" i]').length).toBe(0);
  });

  it('guards DefaultLink used on its own', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    render(<DefaultLink href="data:text/html,x">Raw</DefaultLink>);
    expect(screen.getByText('Raw').hasAttribute('href')).toBe(false);
  });
});

describe('palette open event and the dialog guard', () => {
  it('does not stack on another open dialog', () => {
    const onOpenChange = vi.fn();
    render(
      <>
        <AppShell rail={<Rail brandMark="K" brandName="Test app" version="1.0.0" />} header={<Header title="Home" />}>
          <p>Content</p>
        </AppShell>
        <CommandPalette items={[]} onOpenChange={onOpenChange} />
      </>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    expect(isDialogOpen()).toBe(true);
    act(() => openCommandPalette());
    expect(onOpenChange).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(isDialogOpen()).toBe(false);
    act(() => openCommandPalette());
    expect(onOpenChange).toHaveBeenCalledWith(true);
  });
});

describe('useNow interval', () => {
  it.each([0, -5, 10, Number.NaN, Number.POSITIVE_INFINITY])('never ticks faster than once a second for %s', (interval) => {
    vi.useFakeTimers();
    const spy = vi.spyOn(window, 'setInterval');
    renderHook(() => useNow(true, interval));
    const delays = spy.mock.calls.map((call) => call[1] as number);
    expect(delays.length).toBeGreaterThan(0);
    for (const d of delays) {
      expect(Number.isFinite(d)).toBe(true);
      expect(d).toBeGreaterThanOrEqual(1000);
    }
  });

  it('keeps a valid interval', () => {
    vi.useFakeTimers();
    const spy = vi.spyOn(window, 'setInterval');
    renderHook(() => useNow(true, 5000));
    expect(spy.mock.calls.map((call) => call[1])).toContain(5000);
  });
});

describe('menus portal to the body layer root', () => {
  it('renders the menu outside <main> and returns focus to the trigger', async () => {
    render(
      <main>
        <Menu label="Row actions" items={[{ id: 'edit', label: 'Edit', onSelect: () => undefined }]} trigger={<button type="button">More</button>} />
      </main>,
    );
    const trigger = screen.getByRole('button', { name: 'More' });
    trigger.focus();
    fireEvent.click(trigger);
    await act(async () => undefined);
    const menu = screen.getByRole('menu');
    expect(menu.closest('main')).toBeNull();
    const root = menu.parentElement as HTMLElement;
    expect(root.hasAttribute('data-kit-layer-root')).toBe(true);
    expect(root.parentElement).toBe(document.body);
    expect(menu.classList.contains('popover')).toBe(true);
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'Escape' });
    await act(async () => undefined);
    expect(screen.queryByRole('menu')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});
