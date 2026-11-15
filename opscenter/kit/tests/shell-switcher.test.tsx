/* The tool switcher carousel, the account menu and the bare / that opens search. */
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  AccountMenu,
  AppShell,
  CommandPalette,
  Header,
  NavGroup,
  NavItem,
  Rail,
  ShortcutLayer,
  ThemeProvider,
  ToolLauncher,
  ToolSwitchButton,
  accountDisplayName,
  isSlashOpen,
  openToYouLabel,
  slideOffset,
  useToolLauncher,
} from '../src';
import type { AccountMenuProps, LauncherTool, PaletteItem } from '../src';
import { media } from './helpers';

async function noAxe(el: Element) {
  const r = await axe.run(el, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
  expect(r.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([]);
}

const TOOLS: LauncherTool[] = [
  { id: 'reports', name: 'Reports', tagline: 'Numbers on demand', description: 'Scheduled and ad hoc reports.', hue: 'teal' },
  { id: 'devices', name: 'Devices', tagline: 'The fleet', description: 'Every enrolled device.' },
  { id: 'access', name: 'Access', tagline: 'Who can do what', hue: 'violet' },
  { id: 'docs', name: 'Docs', tagline: 'Reference', external: true },
];

function Launcher({ tools = TOOLS, activeId = 'reports', onOpen = () => undefined, ...rest }: Partial<React.ComponentProps<typeof ToolLauncher>> & { onOpen?: (t: LauncherTool) => void }) {
  const launcher = useToolLauncher();
  return (
    <>
      <ToolSwitchButton launcher={launcher} name="Reports" />
      <ToolLauncher open={launcher.open} onClose={launcher.close} origin={launcher.origin} tools={tools} activeId={activeId} onOpen={onOpen} {...rest} />
    </>
  );
}

function renderLauncher(props: Parameters<typeof Launcher>[0] = {}) {
  return render(
    <ShortcutLayer>
      <Launcher {...props} />
    </ShortcutLayer>,
  );
}

const centreName = () => document.querySelector('.tl-slide[data-slot="center"] .tl-tile-name')?.textContent;

beforeEach(() => {
  vi.useRealTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe('pure helpers', () => {
  it('slideOffset wraps three or more tools and does not wrap two', () => {
    expect([0, 1, 2, 3].map((i) => slideOffset(i, 0, 4))).toEqual([0, 1, -2, -1]);
    expect([0, 1, 2, 3, 4].map((i) => slideOffset(i, 4, 5))).toEqual([1, 2, -2, -1, 0]);
    expect(slideOffset(0, 1, 2)).toBe(-1);
    expect(slideOffset(1, 0, 2)).toBe(1);
    expect(slideOffset(0, 0, 1)).toBe(0);
  });
  it('openToYouLabel names one, two, three and many', () => {
    expect(openToYouLabel([])).toBe('');
    expect(openToYouLabel(['A'])).toBe('A is open to you');
    expect(openToYouLabel(['A', 'B'])).toBe('A and B are open to you');
    expect(openToYouLabel(['A', 'B', 'C'])).toBe('A, B and C are open to you');
    expect(openToYouLabel(['A', 'B', 'C', 'D', 'E'])).toBe('A, B and 3 more are open to you');
  });
  it('accountDisplayName prefers the name and falls back to the email local part', () => {
    expect(accountDisplayName({ name: 'Ada Lovelace', email: 'ada@example.com' })).toBe('Ada Lovelace');
    expect(accountDisplayName({ name: 'ada@example.com', email: 'ada@example.com' })).toBe('ada');
    expect(accountDisplayName({ email: 'ada@example.com' })).toBe('ada');
    expect(accountDisplayName({})).toBe('');
  });
});

describe('ToolSwitchButton and the opening shortcut', () => {
  it('is a named dialog button that opens the launcher and gets focus back on close', async () => {
    renderLauncher();
    const button = screen.getByRole('button', { name: 'Switch tool' });
    expect(button.getAttribute('aria-haspopup')).toBe('dialog');
    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(button.getAttribute('aria-keyshortcuts')).toBe('T');
    fireEvent.click(button);
    expect(button.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByRole('dialog', { name: 'Tools' })).toBeTruthy();
    fireEvent.keyDown(document.activeElement as Element, { key: 'Escape' });
    await vi.waitFor(() => expect(document.activeElement).toBe(button));
  });
  it('opens on t outside text fields, never in one and never with a modifier', () => {
    render(
      <ShortcutLayer>
        <Launcher />
        <input aria-label="Note" />
      </ShortcutLayer>,
    );
    fireEvent.keyDown(screen.getByLabelText('Note'), { key: 't' });
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.keyDown(document.body, { key: 't', ctrlKey: true });
    fireEvent.keyDown(document.body, { key: 't', metaKey: true });
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.keyDown(document.body, { key: 't' });
    expect(screen.getByRole('dialog', { name: 'Tools' })).toBeTruthy();
  });
  it('lists the shortcut in the help dialog', () => {
    renderLauncher();
    fireEvent.keyDown(document.body, { key: '?', shiftKey: true });
    const help = screen.getByRole('dialog', { name: 'Keyboard shortcuts' });
    expect(within(help).getByText('Switch tool')).toBeTruthy();
  });
});

describe('ToolLauncher carousel', () => {
  it('opens centred on the active tool, marks it current and lists every tool', () => {
    renderLauncher({ activeId: 'devices' });
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    expect(centreName()).toBe('Devices');
    const list = screen.getByRole('list', { name: 'Tools you can open' });
    expect(list.getAttribute('aria-roledescription')).toBe('carousel');
    expect(within(list).getAllByRole('listitem')).toHaveLength(4);
    expect(within(list).getByRole('button', { name: 'Devices' }).getAttribute('aria-current')).toBe('true');
    expect(screen.getByRole('button', { name: 'Current tool' }).hasAttribute('disabled')).toBe(true);
    // Only the centre tile is a tab stop.
    const stops = within(list).getAllByRole('button').filter((b) => b.tabIndex === 0);
    expect(stops.map((b) => b.getAttribute('aria-label'))).toEqual(['Devices']);
    expect(screen.getByText('2 of 4', { selector: '.tl-detail-eyebrow' })).toBeTruthy();
  });

  it('moves with the arrow buttons, the dots, and Left, Right, Home and End, wrapping around', () => {
    renderLauncher();
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    fireEvent.click(screen.getByRole('button', { name: 'Next tool' }));
    expect(centreName()).toBe('Devices');
    fireEvent.click(screen.getByRole('button', { name: 'Previous tool' }));
    fireEvent.click(screen.getByRole('button', { name: 'Previous tool' }));
    expect(centreName()).toBe('Docs');
    fireEvent.click(screen.getByRole('button', { name: 'Show Access' }));
    expect(centreName()).toBe('Access');
    const centre = () => document.querySelector('.tl-slide[data-slot="center"] .tl-tile') as HTMLElement;
    fireEvent.keyDown(centre(), { key: 'End' });
    expect(centreName()).toBe('Docs');
    fireEvent.keyDown(centre(), { key: 'ArrowRight' });
    expect(centreName()).toBe('Reports');
    fireEvent.keyDown(centre(), { key: 'ArrowLeft' });
    expect(centreName()).toBe('Docs');
    fireEvent.keyDown(centre(), { key: 'Home' });
    expect(centreName()).toBe('Reports');
    expect(screen.getByRole('button', { name: 'Show Reports' }).getAttribute('aria-current')).toBe('true');
  });

  it('shows the focused tool details and swaps them as the carousel moves', () => {
    renderLauncher();
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    const details = () => screen.getByRole('region', { name: 'Reports' });
    expect(within(details()).getByText('Numbers on demand')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Next tool' }));
    expect(screen.getByRole('region', { name: 'Devices' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Open Devices' })).toBeTruthy();
  });

  it('opens a tool with the Open button, Enter and a click on the centre tile, closing first', () => {
    const onOpen = vi.fn();
    renderLauncher({ onOpen });
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    fireEvent.click(screen.getByRole('button', { name: 'Next tool' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open Devices' }));
    expect(onOpen).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'devices' }));
    expect(screen.queryByRole('dialog')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    fireEvent.keyDown(document.querySelector('.tl-slide[data-slot="center"] .tl-tile') as HTMLElement, { key: 'ArrowRight' });
    fireEvent.keyDown(document.querySelector('.tl-slide[data-slot="center"] .tl-tile') as HTMLElement, { key: 'Enter' });
    expect(onOpen).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'devices' }));

    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    fireEvent.click(screen.getByRole('button', { name: 'Show Access' }));
    fireEvent.click(document.querySelector('.tl-slide[data-slot="center"] .tl-tile') as HTMLElement);
    expect(onOpen).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'access' }));
    expect(onOpen).toHaveBeenCalledTimes(3);
  });

  it('a click on a side tile moves it to the centre and the current tool never opens itself', () => {
    const onOpen = vi.fn();
    renderLauncher({ onOpen });
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    fireEvent.click(screen.getByRole('button', { name: 'Devices' }));
    expect(centreName()).toBe('Devices');
    expect(onOpen).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Show Reports' }));
    fireEvent.click(document.querySelector('.tl-slide[data-slot="center"] .tl-tile') as HTMLElement);
    fireEvent.keyDown(document.querySelector('.tl-slide[data-slot="center"] .tl-tile') as HTMLElement, { key: 'Enter' });
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('marks an external tool and says it opens in a new tab', () => {
    renderLauncher();
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    fireEvent.click(screen.getByRole('button', { name: 'Show Docs' }));
    expect(screen.getByText('External')).toBeTruthy();
    expect(screen.getByText('Opens in a new tab')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Open Docs' })).toBeTruthy();
  });

  it('Back and Escape close it', () => {
    renderLauncher();
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    fireEvent.keyDown(document.activeElement as Element, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('a swipe moves the carousel and a tap does not', () => {
    renderLauncher();
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    const track = screen.getByRole('list', { name: 'Tools you can open' });
    fireEvent.pointerDown(track, { button: 0, clientX: 300, pointerId: 1 });
    fireEvent.pointerMove(track, { clientX: 220, pointerId: 1 });
    fireEvent.pointerUp(track, { clientX: 220, pointerId: 1 });
    expect(centreName()).toBe('Devices');
    fireEvent.pointerDown(track, { button: 0, clientX: 100, pointerId: 2 });
    fireEvent.pointerMove(track, { clientX: 103, pointerId: 2 });
    fireEvent.pointerUp(track, { clientX: 103, pointerId: 2 });
    expect(centreName()).toBe('Devices');
  });

  it('one tool has no arrows and no dots, none shows the empty state, pending marks it busy', () => {
    const { unmount } = renderLauncher({ tools: [TOOLS[0] as LauncherTool] });
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    expect(screen.queryByRole('button', { name: 'Next tool' })).toBeNull();
    expect(screen.queryByRole('group', { name: 'Choose a tool' })).toBeNull();
    unmount();
    const none = renderLauncher({ tools: [] });
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    expect(screen.getByText('No other tools yet')).toBeTruthy();
    none.unmount();
    renderLauncher({ tools: [], pending: 2 });
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    expect(screen.queryByText('No other tools yet')).toBeNull();
    expect(screen.getByRole('list', { name: 'Tools you can open' }).getAttribute('aria-busy')).toBe('true');
  });
});

describe('ToolLauncher motion', () => {
  const advance = (ms: number) => act(() => void vi.advanceTimersByTime(ms));

  it('advances on its own, holds on hover, keyboard focus and interaction, and stops on request', () => {
    vi.useFakeTimers();
    renderLauncher({ autoAdvanceMs: 1000, idleMs: 5000 });
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    advance(1000);
    expect(centreName()).toBe('Devices');

    const stage = document.querySelector('.tl-stage') as HTMLElement;
    fireEvent.mouseEnter(stage);
    advance(3000);
    expect(centreName()).toBe('Devices');
    fireEvent.mouseLeave(stage);
    advance(1000);
    expect(centreName()).toBe('Access');

    fireEvent.click(screen.getByRole('button', { name: 'Next tool' }));
    expect(centreName()).toBe('Docs');
    advance(4000);
    expect(centreName()).toBe('Docs');
    advance(1100);
    // React re-renders when the idle hold ends, and only then arms the next advance.
    advance(1100);
    expect(centreName()).toBe('Reports');

    fireEvent.click(screen.getByRole('button', { name: 'Stop moving through the tools' }));
    advance(5000);
    expect(centreName()).toBe('Reports');
    expect(screen.getByRole('button', { name: 'Start moving through the tools' })).toBeTruthy();
  });

  it('holds while the keyboard is in the carousel', () => {
    vi.useFakeTimers();
    renderLauncher({ autoAdvanceMs: 1000 });
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    const tile = document.querySelector('.tl-slide[data-slot="center"] .tl-tile') as HTMLElement;
    tile.focus();
    fireEvent.keyDown(tile, { key: 'Shift' });
    advance(5000);
    expect(centreName()).toBe('Reports');
  });

  it('never moves on its own under reduced motion and offers no stop button', () => {
    media.reducedMotion = true;
    vi.useFakeTimers();
    renderLauncher({ autoAdvanceMs: 1000 });
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    expect(screen.getByRole('dialog').getAttribute('data-motion')).toBe('reduced');
    advance(10000);
    expect(centreName()).toBe('Reports');
    expect(screen.queryByRole('button', { name: /moving through the tools/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Next tool' }));
    expect(centreName()).toBe('Devices');
    expect(document.querySelector('.tl-detail.is-leaving')).toBeNull();
  });

  it('autoAdvanceMs 0 turns it off', () => {
    vi.useFakeTimers();
    renderLauncher({ autoAdvanceMs: 0 });
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    advance(20000);
    expect(centreName()).toBe('Reports');
  });
});

function CollapsedRail({ keep, collapsible }: { keep?: boolean; collapsible?: boolean }) {
  const launcher = useToolLauncher();
  return (
    <AppShell
      pathname="/"
      rail={
        <Rail
          brandMark="K"
          brandName="Test app"
          keepBrandSlotCollapsed={keep}
          brandSlot={<ToolSwitchButton launcher={launcher} name="Reports" collapsible={collapsible} />}
        >
          <NavGroup label="Main">
            <NavItem href="/" label="Home" hue="brand" icon={<span>H</span>} active />
          </NavGroup>
        </Rail>
      }
      header={<Header title="Home" home={{ href: '/' }} />}
    >
      <ToolLauncher open={launcher.open} onClose={launcher.close} origin={launcher.origin} tools={TOOLS} activeId="reports" onOpen={() => undefined} />
    </AppShell>
  );
}

const kitCss = readFileSync(resolve(process.cwd(), 'src/styles/kit.css'), 'utf8');

describe('collapsed rail switch control', () => {
  it('keeps the brand slot out of the collapsed rail by default and marks it only on request', () => {
    const { unmount } = render(<CollapsedRail />);
    expect(document.querySelector('.sidebar-brand-slot')?.hasAttribute('data-keep')).toBe(false);
    expect(document.querySelector('.tl-switch')?.hasAttribute('data-collapsible')).toBe(false);
    unmount();
    render(<CollapsedRail keep collapsible />);
    expect(document.querySelector('.shell')?.getAttribute('data-rail')).toBe('collapsed');
    expect(document.querySelector('.sidebar-brand-slot')?.hasAttribute('data-keep')).toBe(true);
    expect(document.querySelector('.tl-switch')?.hasAttribute('data-collapsible')).toBe(true);
  });

  it('keeps the same name, description, shortcut and popup state in every form', () => {
    for (const variant of ['rail', 'mark'] as const) {
      const launcher = { open: false, origin: null, openFrom: vi.fn(), close: vi.fn(), buttonRef: { current: null } };
      const { unmount } = render(<ToolSwitchButton launcher={launcher} name="Reports" variant={variant} />);
      const button = screen.getByRole('button', { name: 'Switch tool' });
      expect(button.getAttribute('data-variant')).toBe(variant);
      expect(button.getAttribute('aria-haspopup')).toBe('dialog');
      expect(button.getAttribute('aria-keyshortcuts')).toBe('T');
      expect(button.getAttribute('data-tip')).toBe('Switch tool');
      expect(document.getElementById(button.getAttribute('aria-describedby') as string)?.textContent).toBe('Reports');
      fireEvent.click(button);
      expect(launcher.openFrom).toHaveBeenCalledWith(button);
      unmount();
    }
  });

  it('collapsible applies to the rail form only', () => {
    const launcher = { open: false, origin: null, openFrom: vi.fn(), close: vi.fn(), buttonRef: { current: null } };
    const { rerender } = render(<ToolSwitchButton launcher={launcher} name="Reports" variant="prominent" collapsible />);
    expect(document.querySelector('.tl-switch')?.hasAttribute('data-collapsible')).toBe(false);
    rerender(<ToolSwitchButton launcher={launcher} name="Reports" variant="mark" collapsible />);
    expect(document.querySelector('.tl-switch')?.hasAttribute('data-collapsible')).toBe(false);
  });

  it('opens from the kept control in the collapsed rail, and Enter on the current tool stays a no op', () => {
    const onOpen = vi.fn();
    function Page() {
      const launcher = useToolLauncher();
      return (
        <AppShell pathname="/" rail={<Rail brandMark="K" brandName="Test app" keepBrandSlotCollapsed brandSlot={<ToolSwitchButton launcher={launcher} name="Reports" collapsible />} />} header={<Header title="Home" home={{ href: '/' }} />}>
          <ToolLauncher open={launcher.open} onClose={launcher.close} tools={TOOLS} activeId="reports" onOpen={onOpen} />
        </AppShell>
      );
    }
    render(<Page />);
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    expect(screen.getByRole('dialog', { name: 'Tools' })).toBeTruthy();
    fireEvent.keyDown(document.querySelector('.tl-slide[data-slot="center"] .tl-tile') as HTMLElement, { key: 'Enter' });
    expect(onOpen).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog', { name: 'Tools' })).toBeTruthy();
  });

  it('has the sheet rules that keep the slot and shrink the control to its mark', () => {
    expect(kitCss).toContain('.shell[data-rail="collapsed"] .sidebar-brand-slot[data-keep] { display: flex;');
    expect(kitCss).toContain('.shell[data-rail="collapsed"] .tl-switch[data-collapsible] .tl-switch-text { display: none; }');
    expect(kitCss).toContain('.tl-switch[data-variant="mark"] .tl-switch-text { display: none; }');
    expect(kitCss).toMatch(/\.shell\[data-rail="collapsed"\] \.sidebar-brand-slot \{ display: none; \}/);
  });

  it('has no axe violations with the control kept in the collapsed rail', async () => {
    const { container } = render(<CollapsedRail keep collapsible />);
    await noAxe(container);
    cleanup();
    const launcher = { open: false, origin: null, openFrom: () => undefined, close: () => undefined, buttonRef: { current: null } };
    const mark = render(<ToolSwitchButton launcher={launcher} name="Reports" variant="mark" />);
    await noAxe(mark.container);
  });
});

describe('ToolLauncher accessibility', () => {
  it('has no axe violations closed or open', async () => {
    const { container } = renderLauncher();
    await noAxe(container);
    fireEvent.click(screen.getByRole('button', { name: 'Switch tool' }));
    await noAxe(document.body);
  });
});

/* ---- account menu ---- */

const IDENTITY = { name: 'Ada Lovelace', email: 'ada@example.com', role: 'Engineer' };

function renderMenu(props: Partial<AccountMenuProps> = {}) {
  return render(
    <ThemeProvider>
      <AccountMenu identity={IDENTITY} {...props} />
    </ThemeProvider>,
  );
}

describe('AccountMenu', () => {
  it('renders nothing without an identity', () => {
    const { container, rerender } = render(<AccountMenu identity={null} />);
    expect(container.innerHTML).toBe('');
    rerender(<AccountMenu identity={{}} />);
    expect(container.innerHTML).toBe('');
  });

  it('shows the name and role in the trigger and the email when there is no role', () => {
    renderMenu();
    const trigger = screen.getByRole('button', { name: 'Account: Ada Lovelace' });
    expect(trigger.getAttribute('aria-haspopup')).toBe('dialog');
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(within(trigger).getByText('Engineer')).toBeTruthy();
  });

  it('falls back to the email local part and shows the email as the second line', () => {
    renderMenu({ identity: { email: 'grace@example.com' } });
    const trigger = screen.getByRole('button', { name: 'Account: grace' });
    expect(within(trigger).getByText('grace@example.com')).toBeTruthy();
  });

  it('opens a panel with the identity facts, extra facts and the theme choice', async () => {
    const user = userEvent.setup();
    renderMenu({ facts: [{ label: 'Access', value: 'Via Support group', title: 'group-7' }, { label: 'Last seen', value: 'Oct 22, 9:00 AM' }] });
    await user.click(screen.getByRole('button', { name: 'Account: Ada Lovelace' }));
    const panel = screen.getByRole('dialog', { name: 'Account' });
    expect(within(panel).getByText('ada@example.com')).toBeTruthy();
    expect(within(panel).getByText('Engineer')).toBeTruthy();
    expect(within(panel).getByText('Via Support group').getAttribute('title')).toBe('group-7');
    expect(within(panel).getByText('Last seen')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Account: Ada Lovelace' }).getAttribute('aria-expanded')).toBe('true');
  });

  it('changes the theme through the segmented choice and marks the pressed one', async () => {
    const user = userEvent.setup();
    renderMenu();
    await user.click(screen.getByRole('button', { name: 'Account: Ada Lovelace' }));
    const group = screen.getByRole('group', { name: 'Theme' });
    await user.click(within(group).getByRole('button', { name: 'Dark' }));
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(within(group).getByRole('button', { name: 'Dark' }).getAttribute('aria-pressed')).toBe('true');
    await user.click(within(group).getByRole('button', { name: 'Light' }));
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });

  it('works without a ThemeProvider when the theme choice is off', async () => {
    const user = userEvent.setup();
    render(<AccountMenu identity={IDENTITY} showTheme={false} />);
    await user.click(screen.getByRole('button', { name: 'Account: Ada Lovelace' }));
    expect(screen.queryByRole('group', { name: 'Theme' })).toBeNull();
  });

  it('lists links that open in a new tab and drops an unsafe href', async () => {
    const user = userEvent.setup();
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    renderMenu({ links: [{ key: 'a', label: 'My profile', href: 'https://example.com/me' }, { key: 'b', label: 'Bad', href: 'javascript:alert(1)' }] });
    await user.click(screen.getByRole('button', { name: 'Account: Ada Lovelace' }));
    const ok = screen.getByRole('link', { name: 'My profile' });
    expect(ok.getAttribute('href')).toBe('https://example.com/me');
    expect(ok.getAttribute('target')).toBe('_blank');
    expect(ok.getAttribute('rel')).toBe('noopener noreferrer');
    expect(screen.getByText('Bad').closest('a')?.getAttribute('href')).toBeNull();
  });

  it('signs out, closes the panel, and has no button without a handler', async () => {
    const user = userEvent.setup();
    const onSignOut = vi.fn().mockResolvedValue(undefined);
    const { unmount } = renderMenu({ onSignOut });
    await user.click(screen.getByRole('button', { name: 'Account: Ada Lovelace' }));
    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(onSignOut).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => expect(screen.queryByRole('dialog', { name: 'Account' })).toBeNull());
    unmount();
    renderMenu();
    await user.click(screen.getByRole('button', { name: 'Account: Ada Lovelace' }));
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull();
  });

  it('keeps the panel open and says so when sign out fails', async () => {
    const user = userEvent.setup();
    renderMenu({ onSignOut: () => Promise.reject(new Error('offline')) });
    await user.click(screen.getByRole('button', { name: 'Account: Ada Lovelace' }));
    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Could not sign out. Try again.');
    expect(screen.getByRole('dialog', { name: 'Account' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Sign out' }).hasAttribute('disabled')).toBe(false);
  });

  it('closes on Escape with focus back on the trigger, and on an outside press', async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <AccountMenu identity={IDENTITY} />
        <button type="button">Elsewhere</button>
      </ThemeProvider>,
    );
    const trigger = screen.getByRole('button', { name: 'Account: Ada Lovelace' });
    await user.click(trigger);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Account' })).toBeNull();
    await vi.waitFor(() => expect(document.activeElement).toBe(trigger));
    await user.click(trigger);
    await user.click(screen.getByRole('button', { name: 'Elsewhere' }));
    expect(screen.queryByRole('dialog', { name: 'Account' })).toBeNull();
  });

  it('has no axe violations closed or open', async () => {
    const user = userEvent.setup();
    const { container } = renderMenu({ facts: [{ label: 'Access', value: 'Via group' }], links: [{ key: 'a', label: 'Profile', href: '/me' }], onSignOut: () => undefined });
    await noAxe(container);
    await user.click(screen.getByRole('button', { name: 'Account: Ada Lovelace' }));
    await noAxe(document.body);
  });
});

/* ---- / opens search ---- */

const PAGES: PaletteItem[] = [{ id: 'a', label: 'Alpha', onSelect: () => undefined }];

function key(target: EventTarget, init: KeyboardEventInit = {}): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true, ...init });
  act(() => void target.dispatchEvent(event));
  return event;
}

describe('/ opens search', () => {
  it('opens the palette from the page and focuses its input without typing the slash', () => {
    render(<CommandPalette items={PAGES} />);
    const event = key(document.body);
    expect(event.defaultPrevented).toBe(true);
    expect(screen.getByRole('dialog', { name: 'Search' })).toBeTruthy();
    const input = screen.getByRole('combobox') as HTMLInputElement;
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe('');
  });

  it('does not fire inside an input, a textarea, a select or an editable region', () => {
    render(
      <>
        <CommandPalette items={PAGES} />
        <input aria-label="Name" />
        <input aria-label="Find" type="search" />
        <textarea aria-label="Notes" />
        <select aria-label="Kind">
          <option>One</option>
        </select>
        <div contentEditable suppressContentEditableWarning aria-label="Editor" role="textbox">
          <span>text</span>
        </div>
      </>,
    );
    const targets: Element[] = [
      screen.getByLabelText('Name'),
      screen.getByLabelText('Find'),
      screen.getByLabelText('Notes'),
      screen.getByLabelText('Kind'),
      screen.getByLabelText('Editor'),
      screen.getByText('text'),
    ];
    for (const target of targets) {
      const event = key(target);
      expect(event.defaultPrevented).toBe(false);
      expect(screen.queryByRole('dialog')).toBeNull();
    }
  });

  it('still fires on a button, a checkbox and a contenteditable=false island', () => {
    render(
      <>
        <CommandPalette items={PAGES} />
        <button type="button">Go</button>
        <input type="checkbox" aria-label="Tick" />
        <div contentEditable="false" data-testid="island" />
      </>,
    );
    for (const el of [screen.getByRole('button', { name: 'Go' }), screen.getByLabelText('Tick'), screen.getByTestId('island')]) {
      key(el);
      expect(screen.getByRole('dialog', { name: 'Search' })).toBeTruthy();
      key(document.activeElement as Element, { key: 'Escape' });
      expect(screen.queryByRole('dialog')).toBeNull();
    }
  });

  it('does not fire with Ctrl, Meta, Alt or Shift held', () => {
    render(<CommandPalette items={PAGES} />);
    for (const mod of ['ctrlKey', 'metaKey', 'altKey', 'shiftKey'] as const) {
      const event = key(document.body, { [mod]: true });
      expect(event.defaultPrevented).toBe(false);
      expect(screen.queryByRole('dialog')).toBeNull();
    }
  });

  it('ignores other keys, repeats, composition and an event something else handled', () => {
    render(<CommandPalette items={PAGES} />);
    key(document.body, { key: '?' });
    key(document.body, { key: '\\' });
    key(document.body, { repeat: true });
    key(document.body, { isComposing: true });
    const handled = new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true });
    const stop = (e: Event) => e.preventDefault();
    document.body.addEventListener('keydown', stop, { once: true });
    act(() => void document.body.dispatchEvent(handled));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('does not stack on another open dialog', () => {
    function Page() {
      const [open, setOpen] = useState(true);
      return (
        <>
          <CommandPalette items={PAGES} />
          <ToolLauncher open={open} onClose={() => setOpen(false)} tools={TOOLS} activeId="reports" onOpen={() => undefined} />
        </>
      );
    }
    render(<Page />);
    key(document.body);
    expect(screen.queryByRole('dialog', { name: 'Search' })).toBeNull();
    expect(screen.getByRole('dialog', { name: 'Tools' })).toBeTruthy();
  });

  it('typing / in the open palette types it, and slashOpens={false} turns the key off', () => {
    const { unmount } = render(<CommandPalette items={PAGES} />);
    key(document.body);
    const input = screen.getByRole('combobox') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'a/b' } });
    expect(input.value).toBe('a/b');
    expect(screen.getByRole('dialog', { name: 'Search' })).toBeTruthy();
    unmount();
    render(<CommandPalette items={PAGES} slashOpens={false} />);
    key(document.body);
    expect(screen.queryByRole('dialog')).toBeNull();
    key(document.body, { key: 'k', ctrlKey: true });
    expect(screen.getByRole('dialog', { name: 'Search' })).toBeTruthy();
  });

  it('is listed in the shortcut help next to Ctrl or Cmd and K', () => {
    render(
      <ShortcutLayer>
        <CommandPalette items={PAGES} />
      </ShortcutLayer>,
    );
    fireEvent.keyDown(document.body, { key: '?', shiftKey: true });
    const help = screen.getByRole('dialog', { name: 'Keyboard shortcuts' });
    expect(within(help).getAllByText('Open search')).toHaveLength(2);
  });

  it('isSlashOpen is the pure rule', () => {
    const base = { key: '/', ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, repeat: false, isComposing: false, defaultPrevented: false, target: document.body };
    expect(isSlashOpen(base)).toBe(true);
    expect(isSlashOpen({ ...base, key: 'a' })).toBe(false);
    expect(isSlashOpen({ ...base, ctrlKey: true })).toBe(false);
    expect(isSlashOpen({ ...base, target: document.createElement('textarea') })).toBe(false);
    expect(isSlashOpen({ ...base, target: null })).toBe(true);
  });
});
