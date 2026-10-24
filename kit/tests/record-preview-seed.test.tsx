import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RecordChip, RecordPreviewProvider, createRecordRegistry, useRecordPreview } from '../src/index';
import type { RecordBodyContext, RecordRegistry, RecordTypeDef } from '../src/index';

interface Gadget {
  name: string;
  state: string;
  note?: string;
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

function registryWith(def: Partial<RecordTypeDef<Gadget>> & Pick<RecordTypeDef<Gadget>, 'load'>): RecordRegistry {
  const registry = createRecordRegistry();
  registry.register<Gadget>('gadget', {
    label: 'Gadget',
    title: (data) => data.name,
    render: (data) => (
      <p>
        State: {data.state}
        {data.note ? ` Note: ${data.note}` : ''}
      </p>
    ),
    ...def,
  });
  return registry;
}

function Page({ registry, context }: { registry: RecordRegistry; context?: Record<string, unknown> }) {
  return (
    <RecordPreviewProvider registry={registry}>
      <RecordChip type="gadget" id="g-1" context={context}>
        Gadget one
      </RecordChip>
    </RecordPreviewProvider>
  );
}

describe('RecordPreview seed', () => {
  it('paints the seed at once, marks the body busy, then shows the live data', async () => {
    const user = userEvent.setup();
    const gate = deferred<Gadget>();
    render(<Page registry={registryWith({ load: () => gate.promise, seed: (ref) => ({ name: `Seed ${ref.id}`, state: 'cached' }) })} />);
    await user.click(screen.getByRole('button', { name: 'Gadget one' }));
    expect(screen.getByRole('dialog', { name: 'Seed g-1' })).toBeTruthy();
    expect(screen.getByText('State: cached')).toBeTruthy();
    expect(screen.queryByText('Loading Gadget')).toBeNull();
    const body = document.querySelector('.record-preview-body') as HTMLElement;
    expect(body.getAttribute('aria-busy')).toBe('true');
    expect(body.hasAttribute('data-pending')).toBe(true);
    await act(async () => gate.resolve({ name: 'Live name', state: 'ready' }));
    expect(screen.getByRole('dialog', { name: 'Live name' })).toBeTruthy();
    expect(screen.getByText('State: ready')).toBeTruthy();
    expect(body.hasAttribute('aria-busy')).toBe(false);
    expect(body.hasAttribute('data-pending')).toBe(false);
  });

  it('merges the live result over the seed so seed only fields survive', async () => {
    const user = userEvent.setup();
    const gate = deferred<Gadget>();
    const merge = vi.fn((seed: Gadget, live: Gadget) => ({ ...seed, ...live }));
    render(<Page registry={registryWith({ load: () => gate.promise, seed: () => ({ name: 'Seed', state: 'cached', note: 'from cache' }), merge })} />);
    await user.click(screen.getByRole('button', { name: 'Gadget one' }));
    await act(async () => gate.resolve({ name: 'Live', state: 'ready' }));
    expect(screen.getByText('State: ready Note: from cache')).toBeTruthy();
    expect(merge).toHaveBeenCalledTimes(1);
  });

  it('without merge the live result replaces the seed', async () => {
    const user = userEvent.setup();
    const gate = deferred<Gadget>();
    render(<Page registry={registryWith({ load: () => gate.promise, seed: () => ({ name: 'Seed', state: 'cached', note: 'from cache' }) })} />);
    await user.click(screen.getByRole('button', { name: 'Gadget one' }));
    await act(async () => gate.resolve({ name: 'Live', state: 'ready' }));
    expect(screen.getByText('State: ready')).toBeTruthy();
  });

  it('a seed that returns nothing or throws keeps the skeleton, and merge is not called', async () => {
    const user = userEvent.setup();
    for (const seed of [() => undefined, () => { throw new Error('cache broke'); }]) {
      const gate = deferred<Gadget>();
      const merge = vi.fn();
      const { unmount } = render(<Page registry={registryWith({ load: () => gate.promise, seed, merge })} />);
      await user.click(screen.getByRole('button', { name: 'Gadget one' }));
      expect(screen.getByText('Loading Gadget')).toBeTruthy();
      await act(async () => gate.resolve({ name: 'Live', state: 'ready' }));
      expect(screen.getByText('State: ready')).toBeTruthy();
      expect(merge).not.toHaveBeenCalled();
      unmount();
    }
  });

  it('a failing live load still shows the error with Retry, and Retry paints the seed again', async () => {
    const user = userEvent.setup();
    const load = vi.fn<(id: string) => Promise<Gadget>>().mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ name: 'Live', state: 'ready' });
    const seed = vi.fn(() => ({ name: 'Seed', state: 'cached' }));
    render(<Page registry={registryWith({ load, seed })} />);
    await user.click(screen.getByRole('button', { name: 'Gadget one' }));
    expect(await screen.findByRole('button', { name: 'Retry' })).toBeTruthy();
    expect(screen.queryByText('State: cached')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('State: ready')).toBeTruthy();
    expect(seed).toHaveBeenCalledTimes(2);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it('a merge that throws shows the error state', async () => {
    const user = userEvent.setup();
    render(
      <Page
        registry={registryWith({
          load: async () => ({ name: 'Live', state: 'ready' }),
          seed: () => ({ name: 'Seed', state: 'cached' }),
          merge: () => {
            throw new Error('bad merge');
          },
        })}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Gadget one' }));
    expect(await screen.findByRole('button', { name: 'Retry' })).toBeTruthy();
  });

  it('a type without a seed behaves as before', async () => {
    const user = userEvent.setup();
    const gate = deferred<Gadget>();
    render(<Page registry={registryWith({ load: () => gate.promise })} />);
    await user.click(screen.getByRole('button', { name: 'Gadget one' }));
    expect(screen.getByText('Loading Gadget')).toBeTruthy();
    const body = document.querySelector('.record-preview-body') as HTMLElement;
    expect(body.hasAttribute('aria-busy')).toBe(false);
  });

  it('has no axe violations while the seed is shown', async () => {
    const user = userEvent.setup();
    const gate = deferred<Gadget>();
    render(<Page registry={registryWith({ load: () => gate.promise, seed: () => ({ name: 'Seed', state: 'cached' }) })} />);
    await user.click(screen.getByRole('button', { name: 'Gadget one' }));
    const opts = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
    expect((await axe.run(document.body, opts)).violations.map((v) => v.id)).toEqual([]);
  });
});

describe('RecordPreview open context', () => {
  it('reaches the seed and the body from a chip', async () => {
    const user = userEvent.setup();
    const seed = vi.fn((_ref: unknown, context?: Record<string, unknown>) => ({ name: 'Seed', state: String(context?.['hint']) }));
    let seen: RecordBodyContext | undefined;
    render(
      <Page
        context={{ hint: 'from-row' }}
        registry={registryWith({
          load: async () => ({ name: 'Live', state: 'ready' }),
          seed,
          render: (data, ctx) => {
            seen = ctx;
            return <p>State: {data.state}</p>;
          },
        })}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Gadget one' }));
    expect(seed.mock.calls[0]?.[1]).toEqual({ hint: 'from-row' });
    expect(seen?.context).toEqual({ hint: 'from-row' });
  });

  it('open() from the hook passes the bag and a later open without one clears it', async () => {
    const user = userEvent.setup();
    let seen: RecordBodyContext | undefined;
    function Openers() {
      const api = useRecordPreview();
      return (
        <>
          <button type="button" onClick={() => api.open({ type: 'gadget', id: 'a' }, { tab: 'history' })}>
            with bag
          </button>
          <button type="button" onClick={() => api.open({ type: 'gadget', id: 'a' })}>
            without bag
          </button>
        </>
      );
    }
    const registry = registryWith({
      load: async () => ({ name: 'Live', state: 'ready' }),
      render: (data, ctx) => {
        seen = ctx;
        return <p>State: {data.state}</p>;
      },
    });
    render(
      <RecordPreviewProvider registry={registry}>
        <Openers />
      </RecordPreviewProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'with bag' }));
    expect(await screen.findByText('State: ready')).toBeTruthy();
    expect(seen?.context).toEqual({ tab: 'history' });
    await user.keyboard('{Escape}');
    await user.click(screen.getByRole('button', { name: 'without bag' }));
    expect(await screen.findByText('State: ready')).toBeTruthy();
    expect(seen?.context).toBeUndefined();
  });
});

describe('RecordPreview reload', () => {
  it('reload keeps the body on screen, loads again and shows the fresh data', async () => {
    const user = userEvent.setup();
    const second = deferred<Gadget>();
    const load = vi.fn<(id: string) => Promise<Gadget>>().mockResolvedValueOnce({ name: 'One', state: 'before' }).mockReturnValueOnce(second.promise);
    render(
      <Page
        registry={registryWith({
          load,
          render: (data, ctx) => (
            <div>
              <p>State: {data.state}</p>
              <button type="button" onClick={ctx.reload}>
                Save edit
              </button>
            </div>
          ),
        })}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Gadget one' }));
    expect(await screen.findByText('State: before')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Save edit' }));
    expect(screen.getByText('State: before')).toBeTruthy();
    expect(screen.queryByText('Loading Gadget')).toBeNull();
    expect((document.querySelector('.record-preview-body') as HTMLElement).getAttribute('aria-busy')).toBe('true');
    await act(async () => second.resolve({ name: 'One', state: 'after' }));
    expect(screen.getByText('State: after')).toBeTruthy();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it('a failed reload shows the error state and Retry recovers', async () => {
    const user = userEvent.setup();
    const load = vi
      .fn<(id: string) => Promise<Gadget>>()
      .mockResolvedValueOnce({ name: 'One', state: 'before' })
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue({ name: 'One', state: 'after' });
    render(
      <Page
        registry={registryWith({
          load,
          render: (data, ctx) => (
            <button type="button" onClick={ctx.reload}>
              Reload {data.state}
            </button>
          ),
        })}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Gadget one' }));
    await user.click(await screen.findByRole('button', { name: 'Reload before' }));
    await user.click(await screen.findByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('button', { name: 'Reload after' })).toBeTruthy();
  });
});
