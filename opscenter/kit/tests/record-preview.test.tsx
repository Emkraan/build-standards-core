import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ErrorBoundary, PageErrorBoundary, RecordChip, RecordPreviewProvider, createRecordRegistry, resetKeyChanged, useRecordPreview } from '../src/index';
import type { RecordRegistry, RecordTypeDef } from '../src/index';

interface Gadget {
  name: string;
  state: string;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

let errorSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
});
afterEach(() => errorSpy.mockRestore());

function gadgetRegistry(load: (id: string, signal: AbortSignal) => Promise<Gadget>, extra: Partial<RecordTypeDef<Gadget>> = {}): RecordRegistry {
  const registry = createRecordRegistry();
  registry.register<Gadget>('gadget', {
    label: 'Gadget',
    load,
    title: (data) => data.name,
    render: (data) => <p>State: {data.state}</p>,
    ...extra,
  });
  return registry;
}

function Page({ registry }: { registry: RecordRegistry }) {
  return (
    <RecordPreviewProvider registry={registry}>
      <p>
        See <RecordChip type="gadget" id="g-1">Gadget one</RecordChip> and <RecordChip type="widget" id="w-1" />
      </p>
    </RecordPreviewProvider>
  );
}

describe('createRecordRegistry', () => {
  it('registers, looks up, lists and unregisters a type', () => {
    const registry = createRecordRegistry();
    const off = registry.register('gadget', { label: 'Gadget', load: async () => 1, render: () => null });
    expect(registry.has('gadget')).toBe(true);
    expect(registry.types()).toEqual(['gadget']);
    expect(registry.get('gadget')?.label).toBe('Gadget');
    off();
    expect(registry.has('gadget')).toBe(false);
  });
  it('a stale unregister never removes a newer registration of the same type', () => {
    const registry = createRecordRegistry();
    const off = registry.register('gadget', { label: 'Old', load: async () => 1, render: () => null });
    registry.register('gadget', { label: 'New', load: async () => 1, render: () => null });
    off();
    expect(registry.get('gadget')?.label).toBe('New');
  });
});

describe('RecordPreview', () => {
  it('opens a labelled dialog with a loading state, then the registered body', async () => {
    const user = userEvent.setup();
    const gate = deferred<Gadget>();
    render(<Page registry={gadgetRegistry(() => gate.promise)} />);
    const chip = screen.getByRole('button', { name: 'Gadget one' });
    expect(chip.getAttribute('aria-haspopup')).toBe('dialog');
    await user.click(chip);
    const dialog = screen.getByRole('dialog', { name: 'Gadget g-1' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(screen.getByText('Loading Gadget').closest('[role="status"]')).toBeTruthy();
    await act(async () => gate.resolve({ name: 'Front desk kiosk', state: 'ready' }));
    expect(screen.getByRole('dialog', { name: 'Front desk kiosk' })).toBeTruthy();
    expect(screen.getByText('State: ready')).toBeTruthy();
    expect(screen.queryByText('Loading Gadget')).toBeNull();
  });

  it('shows the error state inside the dialog and Retry loads again', async () => {
    const user = userEvent.setup();
    const load = vi.fn<(id: string) => Promise<Gadget>>().mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ name: 'Back', state: 'up' });
    render(<Page registry={gadgetRegistry(load)} />);
    await user.click(screen.getByRole('button', { name: 'Gadget one' }));
    expect(await screen.findByText('offline')).toBeTruthy();
    expect(screen.getByRole('dialog')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('State: up')).toBeTruthy();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it('closes on Escape and restores focus to the chip', async () => {
    const user = userEvent.setup();
    render(<Page registry={gadgetRegistry(async () => ({ name: 'G', state: 's' }))} />);
    const chip = screen.getByRole('button', { name: 'Gadget one' });
    await user.click(chip);
    await screen.findByText('State: s');
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(document.activeElement).toBe(chip);
  });

  it('opens from a keyboard press on the chip', async () => {
    const user = userEvent.setup();
    render(<Page registry={gadgetRegistry(async () => ({ name: 'G', state: 's' }))} />);
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Gadget one' }));
    await user.keyboard('{Enter}');
    expect(await screen.findByRole('dialog')).toBeTruthy();
  });

  it('renders a chip for an unregistered type as plain text', () => {
    render(<Page registry={gadgetRegistry(async () => ({ name: 'G', state: 's' }))} />);
    expect(screen.getByText('w-1').tagName).toBe('SPAN');
    expect(screen.queryByRole('button', { name: 'w-1' })).toBeNull();
  });

  it('renders a chip with no provider as plain text', () => {
    render(<RecordChip type="gadget" id="g-9" />);
    expect(screen.getByText('g-9').tagName).toBe('SPAN');
  });

  it('open() from a hook returns false for an unknown type and true for a known one', async () => {
    const user = userEvent.setup();
    let result: boolean[] = [];
    function Palette() {
      const preview = useRecordPreview();
      return (
        <button
          type="button"
          onClick={() => {
            result = [preview.open({ type: 'nope', id: '1' }), preview.open({ type: 'gadget', id: 'g-2' })];
          }}
        >
          Go
        </button>
      );
    }
    render(
      <RecordPreviewProvider registry={gadgetRegistry(async (id) => ({ name: `Gadget ${id}`, state: 's' }))}>
        <Palette />
      </RecordPreviewProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'Go' }));
    expect(result).toEqual([false, true]);
    expect(await screen.findByRole('dialog', { name: 'Gadget g-2' })).toBeTruthy();
  });

  it('useRecordPreview outside a provider throws a clear error', () => {
    function Bad() {
      useRecordPreview();
      return null;
    }
    expect(() => render(<Bad />)).toThrow(/RecordPreviewProvider/);
  });

  it('aborts the previous load and ignores its late result when another record opens', async () => {
    const user = userEvent.setup();
    const first = deferred<Gadget>();
    const signals: AbortSignal[] = [];
    const registry = gadgetRegistry((id, signal) => {
      signals.push(signal);
      return id === 'g-1' ? first.promise : Promise.resolve({ name: 'Second', state: 'two' });
    });
    function Two() {
      const preview = useRecordPreview();
      return (
        <>
          <button type="button" onClick={() => preview.open({ type: 'gadget', id: 'g-1' })}>One</button>
          <button type="button" onClick={() => preview.open({ type: 'gadget', id: 'g-2' })}>Two</button>
        </>
      );
    }
    render(
      <RecordPreviewProvider registry={registry}>
        <Two />
      </RecordPreviewProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'One' }));
    act(() => {
      screen.getByRole('button', { name: 'Two', hidden: true }).click();
    });
    expect(await screen.findByText('State: two')).toBeTruthy();
    expect(signals[0]?.aborted).toBe(true);
    await act(async () => first.resolve({ name: 'First', state: 'one' }));
    expect(screen.queryByText('State: one')).toBeNull();
    expect(screen.getByText('State: two')).toBeTruthy();
  });

  it('offers Open full page for a registered href and hands a plain click to navigate', async () => {
    const user = userEvent.setup();
    const navigate = vi.fn();
    const registry = gadgetRegistry(async () => ({ name: 'G', state: 's' }), { href: (id) => `/gadgets/${id}` });
    render(
      <RecordPreviewProvider registry={registry} navigate={navigate}>
        <RecordChip type="gadget" id="g-1" />
      </RecordPreviewProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'g-1' }));
    const link = await screen.findByRole('link', { name: 'Open full page' });
    expect(link.getAttribute('href')).toBe('/gadgets/g-1');
    await user.click(link);
    expect(navigate).toHaveBeenCalledWith('/gadgets/g-1');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('drops an unsafe href instead of rendering a script link', async () => {
    const user = userEvent.setup();
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const registry = gadgetRegistry(async () => ({ name: 'G', state: 's' }), { href: () => 'javascript:alert(1)' });
    render(<Page registry={registry} />);
    await user.click(screen.getByRole('button', { name: 'Gadget one' }));
    await screen.findByText('State: s');
    expect(screen.queryByRole('link')).toBeNull();
    warn.mockRestore();
  });

  it('keeps a body that throws inside the dialog', async () => {
    const user = userEvent.setup();
    const registry = gadgetRegistry(async () => ({ name: 'G', state: 's' }), {
      render: () => {
        throw new Error('bad body');
      },
    });
    render(<Page registry={registry} />);
    await user.click(screen.getByRole('button', { name: 'Gadget one' }));
    expect(await screen.findByText('This page hit an error')).toBeTruthy();
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Gadget one', hidden: true })).toBeTruthy();
  });

  it('has no axe violations while loaded and in the error state', async () => {
    const user = userEvent.setup();
    const load = vi.fn<(id: string) => Promise<Gadget>>().mockResolvedValueOnce({ name: 'G', state: 's' }).mockRejectedValue(new Error('down'));
    render(<Page registry={gadgetRegistry(load)} />);
    await user.click(screen.getByRole('button', { name: 'Gadget one' }));
    await screen.findByText('State: s');
    const opts = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
    expect((await axe.run(document.body, opts)).violations.map((v) => v.id)).toEqual([]);
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await user.click(screen.getByRole('button', { name: 'Gadget one' }));
    await screen.findByText('down');
    expect((await axe.run(document.body, opts)).violations.map((v) => v.id)).toEqual([]);
  });
});

describe('resetKeyChanged', () => {
  it('compares with Object.is and arrays element by element', () => {
    expect(resetKeyChanged('/a', '/a')).toBe(false);
    expect(resetKeyChanged('/a', '/b')).toBe(true);
    expect(resetKeyChanged(NaN, NaN)).toBe(false);
    expect(resetKeyChanged(['/a', 1], ['/a', 1])).toBe(false);
    expect(resetKeyChanged(['/a', 1], ['/a', 2])).toBe(true);
    expect(resetKeyChanged(['/a'], ['/a', 'x'])).toBe(true);
    expect(resetKeyChanged(undefined, undefined)).toBe(false);
  });
});

function Boom({ when }: { when: boolean }) {
  if (when) throw new Error('page exploded');
  return <p>page fine</p>;
}

describe('ErrorBoundary resetKey and page variant', () => {
  it('clears the crash when the reset key changes and shows the new page', () => {
    const { rerender } = render(
      <PageErrorBoundary resetKey="/a">
        <Boom when />
      </PageErrorBoundary>,
    );
    expect(screen.getByRole('alert', { name: 'Page error' })).toBeTruthy();
    rerender(
      <PageErrorBoundary resetKey="/b">
        <Boom when={false} />
      </PageErrorBoundary>,
    );
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByText('page fine')).toBeTruthy();
  });

  it('keeps the crash while the key is unchanged, even when the children rerender', () => {
    const { rerender } = render(
      <PageErrorBoundary resetKey="/a">
        <Boom when />
      </PageErrorBoundary>,
    );
    rerender(
      <PageErrorBoundary resetKey="/a">
        <Boom when={false} />
      </PageErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.queryByText('page fine')).toBeNull();
  });

  it('a page that crashes under a new key shows its own crash and reports once', () => {
    const onError = vi.fn();
    const { rerender } = render(
      <PageErrorBoundary resetKey="/a" onError={onError}>
        <Boom when />
      </PageErrorBoundary>,
    );
    rerender(
      <PageErrorBoundary resetKey="/b" onError={onError}>
        <Boom when />
      </PageErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(onError).toHaveBeenCalledTimes(2);
    rerender(
      <PageErrorBoundary resetKey="/b" onError={onError}>
        <Boom when />
      </PageErrorBoundary>,
    );
    expect(onError).toHaveBeenCalledTimes(2);
  });

  it('navigating in a host recovers a crashed page', async () => {
    const user = userEvent.setup();
    function Host() {
      const [path, setPath] = useState('/broken');
      return (
        <>
          <nav>
            <button type="button" onClick={() => setPath('/broken')}>Broken</button>
            <button type="button" onClick={() => setPath('/home')}>Home</button>
          </nav>
          <PageErrorBoundary resetKey={path}>
            <Boom when={path === '/broken'} />
          </PageErrorBoundary>
        </>
      );
    }
    render(<Host />);
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.getByRole('navigation')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Home' }));
    expect(screen.getByText('page fine')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Broken' }));
    expect(screen.getByRole('alert')).toBeTruthy();
  });

  it('Try again retries the render without a key change', async () => {
    const user = userEvent.setup();
    let fail = true;
    const Flaky = () => {
      if (fail) throw new Error('once');
      return <p>recovered</p>;
    };
    render(
      <PageErrorBoundary resetKey="/a">
        <Flaky />
      </PageErrorBoundary>,
    );
    fail = false;
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(screen.getByText('recovered')).toBeTruthy();
  });

  it('keeps the stack in a closed disclosure and names the page scope', () => {
    render(
      <PageErrorBoundary resetKey="/a">
        <Boom when />
      </PageErrorBoundary>,
    );
    const details = screen.getByText('Technical details').closest('details');
    expect(details?.open).toBe(false);
    expect(details?.textContent).toContain('page exploded');
    expect(screen.getByText(/rest of the app is unaffected/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Reset session' })).toBeNull();
  });

  it('an array key resets when one element changes', () => {
    const { rerender } = render(
      <ErrorBoundary variant="page" resetKey={['/a', 1]}>
        <Boom when />
      </ErrorBoundary>,
    );
    rerender(
      <ErrorBoundary variant="page" resetKey={['/a', 1]}>
        <Boom when={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toBeTruthy();
    rerender(
      <ErrorBoundary variant="page" resetKey={['/a', 2]}>
        <Boom when={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('page fine')).toBeTruthy();
  });

  it('the app variant keeps the full screen crash and also resets on a key change', () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="/a">
        <Boom when />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('button', { name: 'Reset session' })).toBeTruthy();
    rerender(
      <ErrorBoundary resetKey="/b">
        <Boom when={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('page fine')).toBeTruthy();
  });

  it('page crash has no axe violations', async () => {
    const { container } = render(
      <PageErrorBoundary resetKey="/a">
        <Boom when />
      </PageErrorBoundary>,
    );
    const r = await axe.run(container, { rules: { region: { enabled: false }, 'color-contrast': { enabled: false } } });
    expect(r.violations.map((v) => v.id)).toEqual([]);
  });
});
