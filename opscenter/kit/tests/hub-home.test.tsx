/* The hub home: layout, feed, actions and pinned blocks, and the header pin control with its pins
   store contract. */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import axe from 'axe-core';
import { describe, expect, it, vi } from 'vitest';
import {
  ActionsBlock,
  FeedBlock,
  HubHome,
  HubLink,
  PinButton,
  PinnedBlock,
  Toaster,
  addRecent,
  createMemoryPinsStore,
  homeHref,
  pageAt,
  sanitizeRecents,
} from '../src';
import type { HomeTool, PinsStore } from '../src';

const reports: HomeTool = { id: 'reports', name: 'Reports', basePath: '/reports', hue: 'teal' };
const devices: HomeTool = { id: 'devices', name: 'Devices', basePath: '/devices/' };
const tools = [reports, devices];

async function noAxe(el: Element) {
  const r = await axe.run(el, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
  expect(r.violations.map((v) => v.id)).toEqual([]);
}

describe('homeHref', () => {
  it('joins the mount path and the route with one slash', () => {
    expect(homeHref(reports, '/runs')).toBe('/reports/runs');
    expect(homeHref(devices, 'fleet')).toBe('/devices/fleet');
    expect(homeHref(devices, '/')).toBe('/devices');
    expect(homeHref({ basePath: '' }, '/')).toBe('/');
  });
});

describe('HubLink', () => {
  it('opens in the shell on a plain click and leaves modified clicks to the browser', () => {
    const go = vi.fn();
    render(<HubLink href="/reports/runs" go={go}>Runs</HubLink>);
    const a = screen.getByRole('link', { name: 'Runs' });
    expect(a.getAttribute('href')).toBe('/reports/runs');
    fireEvent.click(a, { ctrlKey: true });
    fireEvent.click(a, { metaKey: true });
    fireEvent.click(a, { button: 1 });
    expect(go).not.toHaveBeenCalled();
    fireEvent.click(a);
    expect(go).toHaveBeenCalledWith('/reports/runs');
  });
  it('renders an unsafe href without an href and never calls go', () => {
    const go = vi.fn();
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    render(<HubLink href="javascript:alert(1)" go={go}>Bad</HubLink>);
    const a = screen.getByText('Bad');
    expect(a.getAttribute('href')).toBeNull();
    fireEvent.click(a);
    expect(go).not.toHaveBeenCalled();
  });
});

describe('FeedBlock', () => {
  const props = { id: 'waiting', title: 'Waiting on you', emptyTitle: 'Nothing waiting', emptyBody: 'All clear.', go: () => undefined };

  it('shows a skeleton while any source has not answered, and rows as they arrive', () => {
    const { rerender } = render(<FeedBlock {...props} sources={[{ tool: reports, status: 'loading' }]} />);
    expect(screen.getByText('Loading Waiting on you')).toBeTruthy();
    rerender(
      <FeedBlock
        {...props}
        sources={[
          { tool: reports, status: 'ready', items: [{ key: 'a', label: 'Approvals', value: 1200, tone: 'warning', route: '/approvals' }] },
          { tool: devices, status: 'loading' },
        ]}
      />,
    );
    expect(screen.getByText('Approvals')).toBeTruthy();
    expect(screen.getByText('1,200').getAttribute('data-tone')).toBe('warning');
    expect(screen.getByText('Loading more of Waiting on you')).toBeTruthy();
  });

  it('names a source that could not be read in one quiet line and still shows the rest', () => {
    render(
      <FeedBlock
        {...props}
        sources={[
          { tool: reports, status: 'error' },
          { tool: reports, status: 'error' },
          { tool: devices, status: 'ready', items: [{ key: 'd', label: 'Offline', value: null, route: '/offline' }] },
        ]}
      />,
    );
    expect(screen.getAllByRole('status').map((n) => n.textContent)).toEqual(['Reports could not be read right now.']);
    expect(screen.getByText('-').getAttribute('data-unknown')).toBe('');
    expect(screen.getByRole('link', { name: /Offline/ }).getAttribute('href')).toBe('/devices/offline');
  });

  it('says what empty means, and hides zero rows when asked', () => {
    const zero = [{ tool: reports, status: 'ready' as const, items: [{ key: 'z', label: 'Failed', value: 0, route: '/failed' }] }];
    const { rerender } = render(<FeedBlock {...props} sources={zero} />);
    expect(screen.getByText('Failed')).toBeTruthy();
    rerender(<FeedBlock {...props} sources={zero} hideZero />);
    expect(screen.queryByText('Failed')).toBeNull();
    expect(screen.getByText('Nothing waiting')).toBeTruthy();
  });

  it('opens a row through go and has no axe violations', async () => {
    const go = vi.fn();
    const { container } = render(
      <FeedBlock {...props} go={go} sources={[{ tool: reports, status: 'ready', items: [{ key: 'a', label: 'Approvals', detail: 'Need a decision', at: Date.now() - 60000, value: 3, route: '/approvals' }] }]} />,
    );
    expect(screen.getByRole('region', { name: 'Waiting on you' })).toBeTruthy();
    fireEvent.click(screen.getByRole('link', { name: /Approvals/ }));
    expect(go).toHaveBeenCalledWith('/reports/approvals');
    await noAxe(container);
  });
});

describe('ActionsBlock', () => {
  it('renders one button per action into its module page', async () => {
    const go = vi.fn();
    const { container } = render(<ActionsBlock go={go} actions={[{ key: 'new', tool: reports, label: 'New report', route: '/new' }, { key: 'scan', tool: devices, label: 'Scan', route: '/scan' }]} />);
    fireEvent.click(screen.getByRole('button', { name: 'New report' }));
    expect(go).toHaveBeenCalledWith('/reports/new');
    expect(screen.getByRole('button', { name: 'Scan' }).getAttribute('title')).toBe('Scan in Devices');
    await noAxe(container);
  });
});

describe('PinnedBlock', () => {
  const now = Date.now();
  const recents = [
    { moduleId: 'reports', route: '/runs', label: 'Runs', at: now - 5000 },
    { moduleId: 'devices', route: '/fleet', label: 'Fleet', at: now - 9000 },
    { moduleId: 'gone', route: '/x', label: 'Gone', at: now - 9000 },
  ];

  it('lists pins with an unpin button and does not repeat a pinned page under recent', async () => {
    const store = createMemoryPinsStore({ pins: [{ moduleId: 'reports', route: '/runs', label: 'Runs' }] });
    const { container } = render(<PinnedBlock store={store} tools={tools} recents={recents} go={() => undefined} />);
    const pinned = screen.getByRole('list', { name: 'Pinned pages' });
    expect(within(pinned).getByText('Runs')).toBeTruthy();
    const recent = screen.getByRole('list', { name: 'Recent pages' });
    expect(within(recent).queryByText('Runs')).toBeNull();
    expect(within(recent).getByText('Fleet')).toBeTruthy();
    expect(screen.queryByText('Gone')).toBeNull();
    await noAxe(container);
    fireEvent.click(screen.getByRole('button', { name: 'Unpin Runs' }));
    await waitFor(() => expect(screen.queryByRole('list', { name: 'Pinned pages' })).toBeNull());
    expect(within(screen.getByRole('list', { name: 'Recent pages' })).getByText('Runs')).toBeTruthy();
  });

  it('hides modules the person cannot enter', () => {
    const store = createMemoryPinsStore({ pins: [{ moduleId: 'devices', route: '/fleet', label: 'Fleet' }] });
    render(<PinnedBlock store={store} tools={tools} recents={recents} reachable={new Set(['reports'])} go={() => undefined} />);
    expect(screen.queryByText('Fleet')).toBeNull();
    expect(screen.getByText('Runs')).toBeTruthy();
  });

  it('keeps showing recents when the pins read is denied, and says what is empty', () => {
    const denied = createMemoryPinsStore({ denied: true });
    const { rerender } = render(<PinnedBlock store={denied} tools={tools} recents={recents} go={() => undefined} />);
    expect(screen.queryByRole('list', { name: 'Pinned pages' })).toBeNull();
    expect(screen.getByText('Runs')).toBeTruthy();
    rerender(<PinnedBlock store={denied} tools={tools} recents={[]} go={() => undefined} />);
    expect(screen.getByText('Nothing pinned yet')).toBeTruthy();
  });

  it('reports an unpin the store refused', async () => {
    const store: PinsStore = { ...createMemoryPinsStore({ pins: [{ moduleId: 'reports', route: '/runs', label: 'Runs' }] }), unpin: () => Promise.resolve('Offline.') };
    const onError = vi.fn();
    render(<PinnedBlock store={store} tools={tools} recents={[]} go={() => undefined} onError={onError} />);
    fireEvent.click(screen.getByRole('button', { name: 'Unpin Runs' }));
    await waitFor(() => expect(onError).toHaveBeenCalledWith('Offline.'));
  });
});

describe('HubHome', () => {
  const blocks = {
    waiting: <p>W</p>,
    actions: <p>A</p>,
    live: <p>L</p>,
    fleet: false,
    pinned: <p>P</p>,
  };
  it('puts blocks in the strip, main and side zones in reading order, leaving no gap for an empty one', () => {
    const { container } = render(<HubHome blocks={blocks} />);
    const zones = [...container.querySelectorAll('[data-zone]')].map((z) => `${z.getAttribute('data-zone')}:${z.getAttribute('data-count')}:${z.textContent}`);
    expect(zones).toEqual(['strip:2:WA', 'main:1:L', 'side:1:P']);
    expect(screen.getByRole('region', { name: 'Hub home' })).toBeTruthy();
  });
  it('follows tiles for what shows and in what order', () => {
    const { container } = render(<HubHome blocks={blocks} tiles={[{ key: 'actions' }, { key: 'waiting' }, { key: 'pinned' }]} />);
    expect(container.querySelector('[data-zone="strip"]')?.textContent).toBe('AW');
    expect(container.querySelector('[data-zone="main"]')).toBeNull();
    expect(container.querySelector('.home-layout')?.getAttribute('data-side')).toBe('');
  });
  it('drops the primary column when only the side has blocks', () => {
    const { container } = render(<HubHome blocks={{ pinned: <p>P</p> }} />);
    expect(container.querySelector('.home-primary')).toBeNull();
    expect(container.querySelector('.home-layout')?.hasAttribute('data-main')).toBe(false);
  });
});

describe('recents helpers', () => {
  it('moves a revisited page to the front, caps the list and never records home', () => {
    let list = addRecent([], { moduleId: 'a', route: '/1', label: 'One' }, 1, { max: 2 });
    list = addRecent(list, { moduleId: 'a', route: '/2', label: 'Two' }, 2, { max: 2 });
    list = addRecent(list, { moduleId: 'a', route: '/1', label: 'One' }, 3, { max: 2 });
    expect(list.map((r) => r.route)).toEqual(['/1', '/2']);
    list = addRecent(list, { moduleId: 'a', route: '/3', label: 'Three' }, 4, { max: 2 });
    expect(list.map((r) => r.route)).toEqual(['/3', '/1']);
    expect(addRecent(list, { moduleId: 'a', route: '/', label: 'Home' }, 5, { isHome: true })).toEqual(list);
    expect(addRecent([], { moduleId: 'a', route: '/x', label: 'x'.repeat(100) })[0]?.label.length).toBe(60);
  });
  it('drops incomplete entries read from storage', () => {
    expect(sanitizeRecents([{ moduleId: 'a', route: '/1', label: 'One', at: 1 }, { moduleId: 'a' }, null, 'x', { moduleId: 'a', route: '/2', label: 'Two', at: Number.NaN }])).toHaveLength(1);
    expect(sanitizeRecents('nope')).toEqual([]);
  });
});

describe('pageAt', () => {
  const pages = [{ route: '/', label: 'Overview' }, { route: '/runs', label: 'Runs' }, { route: '/runs/archive', label: 'Archive' }];
  it('picks the longest declared route that equals or prefixes the path', () => {
    expect(pageAt(pages, '/')?.label).toBe('Overview');
    expect(pageAt(pages, '/runs/42')?.label).toBe('Runs');
    expect(pageAt(pages, '/runs/archive/2024')?.label).toBe('Archive');
    expect(pageAt(pages, '/runsx')).toBeNull();
    expect(pageAt(pages, '/other')).toBeNull();
  });
});

describe('PinButton', () => {
  const ui = (store: PinsStore, over: Partial<{ route: string; hidden: boolean }> = {}) => (
    <Toaster>
      <PinButton store={store} moduleId="reports" route={over.route ?? '/runs'} label="Runs" hidden={over.hidden} />
    </Toaster>
  );

  it('pins and unpins the current page', async () => {
    const store = createMemoryPinsStore();
    const { container } = render(ui(store));
    const pin = screen.getByRole('button', { name: 'Pin Runs to the hub' });
    expect(pin.getAttribute('aria-pressed')).toBe('false');
    await act(async () => {
      fireEvent.click(pin);
    });
    expect(store.snapshot().pins).toEqual([{ moduleId: 'reports', route: '/runs', label: 'Runs' }]);
    const unpin = await screen.findByRole('button', { name: 'Unpin Runs from the hub' });
    expect(unpin.getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText('Pinned Runs to the hub')).toBeTruthy();
    await noAxe(container);
    await act(async () => {
      fireEvent.click(unpin);
    });
    expect(store.snapshot().pins).toEqual([]);
    expect(await screen.findByRole('button', { name: 'Pin Runs to the hub' })).toBeTruthy();
  });

  it('is absent when the pins read is denied or has not answered, and when hidden', () => {
    const { container, rerender } = render(ui(createMemoryPinsStore({ denied: true })));
    expect(container.querySelector('button')).toBeNull();
    const waiting = { status: 'loading', pins: [], max: 12 } as const;
    const loading: PinsStore = { ...createMemoryPinsStore(), snapshot: () => waiting };
    rerender(ui(loading));
    expect(container.querySelector('button')).toBeNull();
    rerender(ui(createMemoryPinsStore(), { hidden: true }));
    expect(container.querySelector('button')).toBeNull();
    rerender(ui(createMemoryPinsStore(), { route: '' }));
    expect(container.querySelector('button')).toBeNull();
  });

  it('starts the first read through the store load hook', () => {
    const load = vi.fn();
    render(ui({ ...createMemoryPinsStore(), load }));
    expect(load).toHaveBeenCalledOnce();
  });

  it('is disabled with the reason when the store is full, and still unpins a pinned page', () => {
    const full = createMemoryPinsStore({ max: 1, pins: [{ moduleId: 'devices', route: '/fleet', label: 'Fleet' }] });
    const { rerender } = render(ui(full));
    const btn = screen.getByRole('button', { name: 'The hub is full, unpin a page first (1 pins)' });
    expect(btn.hasAttribute('disabled')).toBe(true);
    rerender(ui(createMemoryPinsStore({ max: 1, pins: [{ moduleId: 'reports', route: '/runs', label: 'Runs' }] })));
    expect(screen.getByRole('button', { name: 'Unpin Runs from the hub' }).hasAttribute('disabled')).toBe(false);
  });

  it('shows the store reason in an error toast when a write fails', async () => {
    const store: PinsStore = { ...createMemoryPinsStore(), pin: () => Promise.resolve('Try again later.') };
    render(ui(store));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Pin Runs to the hub' }));
    });
    expect(await screen.findByText('Could not update your pins. Try again later.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Pin Runs to the hub' })).toBeTruthy();
  });

  it('keeps the header control and the pinned block in step through one store', async () => {
    const store = createMemoryPinsStore();
    render(
      <Toaster>
        <PinButton store={store} moduleId="reports" route="/runs" label="Runs" />
        <PinnedBlock store={store} tools={tools} recents={[]} go={() => undefined} />
      </Toaster>,
    );
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Pin Runs to the hub' }));
    });
    expect(within(screen.getByRole('list', { name: 'Pinned pages' })).getByText('Runs')).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Unpin Runs' }));
    });
    expect(screen.getByRole('button', { name: 'Pin Runs to the hub' })).toBeTruthy();
  });
});

describe('createMemoryPinsStore', () => {
  it('refuses a duplicate silently, refuses past max and refuses everything when denied', async () => {
    const store = createMemoryPinsStore({ max: 1 });
    const pin = { moduleId: 'a', route: '/1', label: 'One' };
    expect(await store.pin(pin)).toBeNull();
    expect(await store.pin(pin)).toBeNull();
    expect(store.snapshot().pins).toHaveLength(1);
    expect(await store.pin({ moduleId: 'a', route: '/2', label: 'Two' })).toMatch(/Only 1/);
    const denied = createMemoryPinsStore({ denied: true });
    expect(await denied.pin(pin)).toMatch(/not available/);
    expect(await denied.unpin(pin)).toMatch(/not available/);
  });
  it('keeps one snapshot object until something changes and drops a listener on unsubscribe', async () => {
    const store = createMemoryPinsStore();
    const a = store.snapshot();
    expect(store.snapshot()).toBe(a);
    const l = vi.fn();
    const off = store.subscribe(l);
    await store.pin({ moduleId: 'a', route: '/1', label: 'One' });
    expect(l).toHaveBeenCalledOnce();
    off();
    await store.unpin({ moduleId: 'a', route: '/1', label: 'One' });
    expect(l).toHaveBeenCalledOnce();
    expect(store.snapshot()).not.toBe(a);
  });
});
