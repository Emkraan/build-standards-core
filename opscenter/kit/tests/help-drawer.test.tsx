/* InfoTip, HelpLink, page help (usePageHelp), the Help button and the help drawer, and the help
   topics in the command palette. Each part is also run through axe. */
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  AppShell,
  CommandPalette,
  GlossaryProvider,
  HelpButton,
  HelpDrawer,
  HelpLink,
  Header,
  HelpProvider,
  InfoTip,
  Rail,
  openCommandPalette,
  useHelp,
  useHelpPaletteItems,
  usePageHelp,
} from '../src';
import type { Glossary, PageHelp, PaletteItem } from '../src';
import { resetDevWarnings } from '../src/lib/env';

async function violations(root: Element): Promise<string[]> {
  const result = await axe.run(root, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } }, resultTypes: ['violations'] });
  return result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(' ')).join(', ')})`);
}

const glossary: Glossary = {
  pool: {
    term: 'host pool',
    short: 'A group of session hosts that share one image.',
    long: 'A host pool groups the machines users connect to. Every host in it shares the same image and settings.',
    href: 'https://docs.example.com/pool',
  },
  drain: { term: 'drain mode', short: 'The host takes no new sessions.' },
};

beforeEach(() => resetDevWarnings());
afterEach(() => vi.restoreAllMocks());

describe('HelpLink', () => {
  it('opens an address on another site in a new tab, safely, and says so', () => {
    render(<HelpLink href="https://docs.example.com/a">Read more</HelpLink>);
    const link = screen.getByRole('link', { name: 'Read more (opens in a new tab)' });
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
    expect(link.getAttribute('href')).toBe('https://docs.example.com/a');
  });

  it('keeps an in-app path in the same tab', () => {
    render(<HelpLink href="/docs/pools">Pools guide</HelpLink>);
    const link = screen.getByRole('link', { name: 'Pools guide' });
    expect(link.hasAttribute('target')).toBe(false);
    expect(link.getAttribute('href')).toBe('/docs/pools');
  });

  it('drops an unsafe scheme', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    render(<HelpLink href="javascript:alert(1)">Bad</HelpLink>);
    expect(screen.getByText('Bad').closest('a')?.hasAttribute('href')).toBe(false);
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <p>
        <HelpLink href="https://docs.example.com/a">Read more</HelpLink> or <HelpLink href="/docs">the guide</HelpLink>
      </p>,
    );
    expect(await violations(container)).toEqual([]);
  });
});

describe('InfoTip', () => {
  it('names itself from the glossary entry, shows the short text as the tip and opens the long text on click', async () => {
    const user = userEvent.setup();
    render(
      <GlossaryProvider glossary={glossary}>
        <InfoTip id="pool" />
      </GlossaryProvider>,
    );
    const button = screen.getByRole('button', { name: 'About host pool' });
    expect(button.getAttribute('data-tip')).toBe('A group of session hosts that share one image.');
    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(button.hasAttribute('aria-controls')).toBe(false);
    await user.click(button);
    const panel = screen.getByRole('dialog', { name: 'About host pool' });
    expect(within(panel).getByText(/Every host in it shares the same image/)).toBeTruthy();
    expect(button.getAttribute('aria-expanded')).toBe('true');
    expect(button.getAttribute('aria-controls')).toBe(panel.id);
    const link = within(panel).getByRole('link', { name: 'Learn more (opens in a new tab)' });
    expect(link.getAttribute('href')).toBe('https://docs.example.com/pool');
    expect(link.getAttribute('target')).toBe('_blank');
  });

  it('closes on a second click, on Escape and on a press outside', async () => {
    const user = userEvent.setup();
    render(
      <>
        <InfoTip short="Short text." long="The long text." />
        <button type="button">Elsewhere</button>
      </>,
    );
    const button = screen.getByRole('button', { name: 'More information' });
    await user.click(button);
    expect(screen.getByRole('dialog')).toBeTruthy();
    await user.click(button);
    expect(screen.queryByRole('dialog')).toBeNull();
    await user.click(button);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    await user.click(button);
    await user.click(screen.getByRole('button', { name: 'Elsewhere' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('works from the keyboard', async () => {
    const user = userEvent.setup();
    render(<InfoTip short="Short text." long="The long text." />);
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'More information' }));
    await user.keyboard('{Enter}');
    expect(screen.getByText('The long text.')).toBeTruthy();
  });

  it('lets an explicit prop win over the glossary entry, field by field', async () => {
    const user = userEvent.setup();
    render(
      <GlossaryProvider glossary={glossary}>
        <InfoTip id="pool" short="Overridden short." label="What is a pool" />
      </GlossaryProvider>,
    );
    const button = screen.getByRole('button', { name: 'What is a pool' });
    expect(button.getAttribute('data-tip')).toBe('Overridden short.');
    await user.click(button);
    // `long` was not passed, so the entry's long text still fills the popover.
    expect(screen.getByText(/Every host in it shares the same image/)).toBeTruthy();
  });

  it('uses the short text as the popover text when there is no long text', async () => {
    const user = userEvent.setup();
    render(<InfoTip short="Only a short text." />);
    await user.click(screen.getByRole('button', { name: 'More information' }));
    expect(within(screen.getByRole('dialog')).getByText('Only a short text.')).toBeTruthy();
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('shows a link only when there is an address, in the label it is given', async () => {
    const user = userEvent.setup();
    render(<InfoTip short="Text." href="/docs/pools" hrefLabel="Open the pools guide" />);
    await user.click(screen.getByRole('button', { name: 'More information' }));
    const link = screen.getByRole('link', { name: 'Open the pools guide' });
    expect(link.hasAttribute('target')).toBe(false);
  });

  it('renders nothing and warns once in development when there is no text', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const { container } = render(<InfoTip id="missing" />);
    expect(container.innerHTML).toBe('');
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0]?.[0])).toContain('missing');
  });

  it('has no axe violations closed or open', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <GlossaryProvider glossary={glossary}>
        <label htmlFor="pool-size">
          Pool size <InfoTip id="pool" />
        </label>
        <input id="pool-size" />
      </GlossaryProvider>,
    );
    expect(await violations(container)).toEqual([]);
    await user.click(screen.getByRole('button', { name: 'About host pool' }));
    expect(await violations(document.body)).toEqual([]);
  });
});

function Page({ help }: { help: PageHelp | null }) {
  usePageHelp(help);
  return <h1>Page</h1>;
}

const POOLS: PageHelp = {
  title: 'Host pools',
  summary: 'Create and scale the groups of machines users connect to.',
  steps: ['Pick a pool.', 'Choose a size.', 'Save.'],
  terms: ['pool', 'drain'],
  links: [{ label: 'Pool guide', href: 'https://docs.example.com/guide' }],
};

function Shell({ help, headerProps, shellProps, pathname }: { help: PageHelp | null; headerProps?: object; shellProps?: object; pathname?: string }) {
  return (
    <AppShell
      helpDrawer
      glossary={glossary}
      rail={<Rail brandName="Test" brandMark="T" version="1.0.0" />}
      header={<Header title="Console" {...headerProps} />}
      {...(pathname === undefined ? {} : { pathname })}
      {...shellProps}
    >
      <Page help={help} />
    </AppShell>
  );
}

describe('page help, the Help button and the drawer', () => {
  it('shows no Help button on a page that registered no help', () => {
    render(<Shell help={null} />);
    expect(screen.queryByRole('button', { name: 'Help' })).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('shows the Help button once a page registers help, and opens the drawer with the page help', async () => {
    const user = userEvent.setup();
    render(<Shell help={POOLS} />);
    const button = screen.getByRole('button', { name: 'Help' });
    expect(button.getAttribute('aria-expanded')).toBe('false');
    await user.click(button);
    const drawer = screen.getByRole('dialog', { name: 'Help: Host pools' });
    expect(within(drawer).getByText('Create and scale the groups of machines users connect to.')).toBeTruthy();
    const steps = within(drawer).getAllByRole('listitem').map((li) => li.textContent);
    expect(steps).toEqual(expect.arrayContaining(['Pick a pool.', 'Choose a size.', 'Save.']));
    expect(within(drawer).getByText('How to')).toBeTruthy();
    expect(within(drawer).getByText('host pool')).toBeTruthy();
    expect(within(drawer).getByText(/Every host in it shares the same image/)).toBeTruthy();
    // A term without a long text falls back to its short text.
    expect(within(drawer).getByText('The host takes no new sessions.')).toBeTruthy();
    expect(within(drawer).getByRole('link', { name: 'Pool guide (opens in a new tab)' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Help' }).getAttribute('aria-expanded')).toBe('true');
  });

  it('closes on Escape and on the close button, and gives focus back to the Help button', async () => {
    const user = userEvent.setup();
    render(<Shell help={POOLS} />);
    const button = screen.getByRole('button', { name: 'Help' });
    await user.click(button);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(button);
    await user.click(button);
    await user.click(screen.getByRole('button', { name: 'Close help' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('closes when the route changes, so help never stays open over the next page', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Shell help={POOLS} pathname="/pools" />);
    await user.click(screen.getByRole('button', { name: 'Help' }));
    expect(screen.getByRole('dialog')).toBeTruthy();
    rerender(<Shell help={POOLS} pathname="/hosts" />);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('removes the button and closes the drawer when the page stops having help', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Shell help={POOLS} />);
    await user.click(screen.getByRole('button', { name: 'Help' }));
    rerender(<Shell help={null} />);
    expect(screen.queryByRole('button', { name: 'Help' })).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('shows the new help when a page changes its words', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Shell help={POOLS} />);
    rerender(<Shell help={{ ...POOLS, title: 'Pools and hosts' }} />);
    await user.click(screen.getByRole('button', { name: 'Help' }));
    expect(screen.getByRole('dialog', { name: 'Help: Pools and hosts' })).toBeTruthy();
  });

  it('keeps one registration when a page builds the same object again on every render', () => {
    const seen: Array<PageHelp | null> = [];
    function Spy() {
      seen.push(useHelp()?.page ?? null);
      return null;
    }
    function Inline() {
      const [, setN] = useState(0);
      usePageHelp({ title: 'Inline', steps: ['One.'] });
      return (
        <button type="button" onClick={() => setN((n) => n + 1)}>
          Again
        </button>
      );
    }
    render(
      <HelpProvider>
        <Inline />
        <Spy />
      </HelpProvider>,
    );
    const first = seen.at(-1);
    expect(first?.title).toBe('Inline');
    fireEvent.click(screen.getByRole('button', { name: 'Again' }));
    fireEvent.click(screen.getByRole('button', { name: 'Again' }));
    expect(seen.at(-1)).toBe(first);
  });

  it('lets the latest page win and brings the earlier one back when it leaves', () => {
    function Two({ both }: { both: boolean }) {
      return (
        <HelpProvider>
          <Page help={{ title: 'Outer page' }} />
          {both ? <Page help={{ title: 'Inner panel' }} /> : null}
          <Title />
        </HelpProvider>
      );
    }
    function Title() {
      return <p data-testid="title">{useHelp()?.page?.title}</p>;
    }
    const { rerender } = render(<Two both />);
    expect(screen.getByTestId('title').textContent).toBe('Inner panel');
    rerender(<Two both={false} />);
    expect(screen.getByTestId('title').textContent).toBe('Outer page');
  });

  it('skips a listed word that is not in the glossary, and warns once in development', async () => {
    const user = userEvent.setup();
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    render(<Shell help={{ title: 'Hosts', terms: ['pool', 'ghost'] }} />);
    await user.click(screen.getByRole('button', { name: 'Help' }));
    const drawer = screen.getByRole('dialog', { name: 'Help: Hosts' });
    expect(within(drawer).getByText('host pool')).toBeTruthy();
    expect(within(drawer).queryByText('ghost')).toBeNull();
    expect(warn.mock.calls.filter((call) => String(call[0]).includes('ghost'))).toHaveLength(1);
  });

  it('leaves out the sections a page did not write', async () => {
    const user = userEvent.setup();
    render(<Shell help={{ title: 'Bare' }} />);
    await user.click(screen.getByRole('button', { name: 'Help' }));
    const drawer = screen.getByRole('dialog', { name: 'Help: Bare' });
    expect(within(drawer).queryByText('How to')).toBeNull();
    expect(within(drawer).queryByText('Words on this page')).toBeNull();
    expect(within(drawer).queryByText('Learn more')).toBeNull();
  });

  it('can be hidden from the Header and renamed', () => {
    const { rerender } = render(<Shell help={POOLS} headerProps={{ help: false }} />);
    expect(screen.queryByRole('button', { name: 'Help' })).toBeNull();
    rerender(<Shell help={POOLS} headerProps={{ helpLabel: 'How this works' }} />);
    expect(screen.getByRole('button', { name: 'How this works' })).toBeTruthy();
  });

  it('is off by default: no state, no Help button and no drawer, and the page renders as before', async () => {
    function Own() {
      const help = useHelp();
      return <p data-testid="own">{help ? 'state' : 'none'}</p>;
    }
    const { container } = render(
      <AppShell rail={<Rail brandName="Test" brandMark="T" version="1.0.0" />} header={<Header title="Console" />}>
        <Page help={POOLS} />
        <Own />
      </AppShell>,
    );
    expect(screen.queryByRole('button', { name: 'Help' })).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByTestId('own').textContent).toBe('none');
    expect(container.querySelector('.help-btn, .help-drawer')).toBeNull();
  });

  it('keeps an app\'s own provider and drawer when the shell does not mount one', async () => {
    const user = userEvent.setup();
    function Own() {
      const help = useHelp();
      return (
        <button type="button" onClick={() => help?.setOpen(true)}>
          {help?.page?.title ?? 'none'}
        </button>
      );
    }
    render(
      <HelpProvider>
        <AppShell rail={<Rail brandName="Test" brandMark="T" version="1.0.0" />} header={<Header title="Console" />}>
          <Page help={POOLS} />
          <Own />
        </AppShell>
      </HelpProvider>,
    );
    expect(screen.getByRole('button', { name: 'Host pools' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Host pools' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('HelpButton and HelpDrawer render nothing outside a provider', () => {
    const { container } = render(
      <>
        <HelpButton />
        <HelpDrawer />
      </>,
    );
    expect(container.innerHTML).toBe('');
  });

  it('usePageHelp is harmless outside a shell', () => {
    expect(() => render(<Page help={POOLS} />)).not.toThrow();
  });

  it('has no axe violations with the drawer closed and open', async () => {
    const user = userEvent.setup();
    const { container } = render(<Shell help={POOLS} />);
    expect(await violations(container)).toEqual([]);
    await user.click(screen.getByRole('button', { name: 'Help' }));
    expect(await violations(document.body)).toEqual([]);
  });
});

describe('help topics in the command palette', () => {
  // A palette that sits outside the shell needs the glossary and the help state above both.
  function Outer({ children }: { children: ReactNode }) {
    return (
      <GlossaryProvider glossary={glossary}>
        <HelpProvider>{children}</HelpProvider>
      </GlossaryProvider>
    );
  }

  function Palette({ extra = [] }: { extra?: PaletteItem[] }) {
    const help = useHelpPaletteItems();
    return <CommandPalette items={[...extra, ...help]} />;
  }

  it('lists the page and each of its words, and choosing one opens the drawer', async () => {
    const user = userEvent.setup();
    render(
      <Outer>
        <Shell help={POOLS} />
        <Palette />
      </Outer>,
    );
    act(() => openCommandPalette());
    const options = screen.getAllByRole('option').map((o) => o.textContent ?? '');
    expect(options).toHaveLength(3);
    expect(options.some((text) => text.startsWith('Help: Host pools') && text.endsWith('Help'))).toBe(true);
    expect(options.some((text) => text.startsWith('host pool') && text.endsWith('Term'))).toBe(true);
    expect(options.some((text) => text.startsWith('drain mode') && text.endsWith('Term'))).toBe(true);
    await user.click(screen.getByRole('option', { name: /Help: Host pools/ }));
    expect(screen.getByRole('dialog', { name: 'Help: Host pools' })).toBeTruthy();
  });

  it('finds a word by what a person would type', async () => {
    const user = userEvent.setup();
    render(
      <Outer>
        <Shell help={POOLS} />
        <Palette />
      </Outer>,
    );
    act(() => openCommandPalette());
    await user.type(screen.getByRole('combobox'), 'drain');
    const options = screen.getAllByRole('option').map((o) => o.textContent ?? '');
    expect(options).toHaveLength(1);
    expect(options[0]?.startsWith('drain mode')).toBe(true);
  });

  it('shares one provider with the shell, so a palette outside the shell sees the page on screen', () => {
    function Count() {
      return <p data-testid="count">{useHelpPaletteItems().length}</p>;
    }
    render(
      <Outer>
        <Shell help={POOLS} />
        <Count />
      </Outer>,
    );
    // The page and two words.
    expect(screen.getByTestId('count').textContent).toBe('3');
  });

  it('is empty while no page has help, and outside a provider', () => {
    function Count() {
      return <p data-testid="count">{useHelpPaletteItems().length}</p>;
    }
    const { rerender } = render(
      <Outer>
        <Shell help={null} />
        <Count />
      </Outer>,
    );
    expect(screen.getByTestId('count').textContent).toBe('0');
    rerender(<Count />);
    expect(screen.getByTestId('count').textContent).toBe('0');
  });

  it('puts the items in the group it is given and skips unknown words', () => {
    let seen: PaletteItem[] = [];
    function Grab() {
      const ref = useRef<PaletteItem[]>([]);
      ref.current = useHelpPaletteItems({ group: 'Guides' });
      seen = ref.current;
      return null;
    }
    render(
      <Outer>
        <Shell help={{ title: 'Hosts', terms: ['pool', 'ghost'] }} />
        <Grab />
      </Outer>,
    );
    expect(seen.map((item) => item.group)).toEqual(['Guides', 'Guides']);
    expect(seen.map((item) => item.id)).toEqual(['help:page', 'help:term:pool']);
  });
});

describe('HelpProvider', () => {
  it('keeps an outer provider as the only one', () => {
    const states: Array<unknown> = [];
    function Read() {
      states.push(useHelp());
      return null;
    }
    render(
      <HelpProvider>
        <Read />
        <HelpProvider>
          <Read />
        </HelpProvider>
      </HelpProvider>,
    );
    expect(states).toHaveLength(2);
    expect(states[1]).toBe(states[0]);
  });
});
