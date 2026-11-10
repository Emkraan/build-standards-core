import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import {
  AnnouncementBanner,
  AnnouncementStack,
  AppShell,
  BuildCard,
  CommandPalette,
  Menu,
  Modal,
  STORAGE_KEYS,
  StorageScope,
  Table,
  addDismissed,
  isFromInteractiveDescendant,
  onMediaChange,
  readDismissed,
  storageKeys,
  themeInitScript,
  useStorageKeys,
  visibleAnnouncements,
} from '../src/index';
import type { Announcement, TableColumn } from '../src/index';

const KEY = STORAGE_KEYS.announcementsDismissed;

function stored(key: string = KEY): unknown {
  return JSON.parse(window.localStorage.getItem(key) ?? 'null');
}

describe('announcement dismissals share one list', () => {
  it('dismissing one standalone banner keeps the other dismissal (H1)', () => {
    render(
      <>
        <AnnouncementBanner id="a" tone="info" title="Alpha" />
        <AnnouncementBanner id="b" tone="info" title="Bravo" />
      </>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss announcement: Alpha' }));
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss announcement: Bravo' }));
    expect(stored()).toEqual(['a', 'b']);
    expect(screen.queryByText('Alpha')).toBeNull();
    expect(screen.queryByText('Bravo')).toBeNull();
  });

  it('merges with ids another tab wrote since mount and follows the storage event', () => {
    render(<AnnouncementBanner id="a" tone="info" title="Alpha" />);
    window.localStorage.setItem(KEY, JSON.stringify(['other']));
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss announcement: Alpha' }));
    expect(stored()).toEqual(['other', 'a']);
  });

  it('hides a banner another tab dismissed (storage event)', () => {
    render(<AnnouncementBanner id="c" tone="info" title="Charlie" />);
    expect(screen.getByText('Charlie')).toBeTruthy();
    act(() => {
      window.localStorage.setItem(KEY, JSON.stringify(['c']));
      window.dispatchEvent(new StorageEvent('storage', { key: KEY }));
    });
    expect(screen.queryByText('Charlie')).toBeNull();
  });

  it('caps the stored list to the newest 200 ids and ignores junk', () => {
    window.localStorage.setItem(KEY, JSON.stringify(Array.from({ length: 200 }, (_, i) => `x${i}`)));
    const next = addDismissed(KEY, 'new');
    expect(next).toHaveLength(200);
    expect(next[0]).toBe('x1');
    expect(next[199]).toBe('new');
    window.localStorage.setItem(KEY, JSON.stringify([1, 'ok', null]));
    expect(readDismissed(KEY)).toEqual(['ok']);
    window.localStorage.setItem(KEY, '{broken');
    expect(readDismissed(KEY)).toEqual([]);
  });
});

describe('announcement stack (M3)', () => {
  const six: Announcement[] = ['a', 'b', 'c', 'd', 'e', 'f'].map((id) => ({ id, tone: 'info', title: `Note ${id}` }));

  it('hides dismissed ones before the cap of five', () => {
    expect(visibleAnnouncements(six, ['b']).map((a) => a.id)).toEqual(['a', 'c', 'd', 'e', 'f']);
    const kept = [{ id: 'k', tone: 'critical' as const, dismissible: false }];
    expect(visibleAnnouncements(kept, ['k']).map((a) => a.id)).toEqual(['k']);
  });

  it('shows the sixth after one of the first five is dismissed', () => {
    const onDismiss = vi.fn();
    render(<AnnouncementStack announcements={six} onDismiss={onDismiss} />);
    expect(screen.queryByText('Note f')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss announcement: Note b' }));
    expect(onDismiss).toHaveBeenCalledWith('b');
    expect(screen.getByText('Note f')).toBeTruthy();
    expect(screen.getAllByRole('heading')).toHaveLength(5);
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss announcement: Note a' }));
    expect(stored()).toEqual(['b', 'a']);
  });
});

describe('per-app storage keys (H2)', () => {
  it('keeps the shared keys without an app id', () => {
    expect(storageKeys()).toEqual(STORAGE_KEYS);
    expect(storageKeys('  ')).toEqual(STORAGE_KEYS);
  });

  it('scopes build seen and dismissals, never theme or rail pin', () => {
    expect(storageKeys('reports')).toEqual({
      theme: 'shell.theme',
      railPinned: 'shell.sidebar.pinned',
      buildSeen: 'shell.reports.build.seen',
      announcementsDismissed: 'shell.reports.announce.dismissed',
    });
  });

  it('applies through StorageScope and AppShell appId', () => {
    let seen = '';
    function Probe() {
      seen = useStorageKeys().buildSeen;
      return null;
    }
    render(
      <StorageScope appId="one">
        <Probe />
      </StorageScope>,
    );
    expect(seen).toBe('shell.one.build.seen');

    render(
      <AppShell appId="two" rail={<BuildCard version="1.2.0" releases={[{ version: '1.2.0', date: '2026-10-01', title: 'First', items: ['First'] }]} />}>
        <AnnouncementBanner id="n" tone="info" title="Scoped" />
      </AppShell>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss announcement: Scoped' }));
    expect(stored('shell.two.announce.dismissed')).toEqual(['n']);
    expect(window.localStorage.getItem(KEY)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Version 1\.2\.0/ }));
    expect(window.localStorage.getItem('shell.two.build.seen')).toBe('1.2.0');
    expect(window.localStorage.getItem(STORAGE_KEYS.buildSeen)).toBeNull();
  });
});

interface Row {
  id: string;
  name: string;
}

describe('table row activation (H3)', () => {
  const rows: Row[] = [{ id: 'r1', name: 'First' }];
  function setup(onAction = vi.fn()) {
    const onRowActivate = vi.fn();
    const columns: TableColumn<Row>[] = [
      { key: 'name', header: 'Name' },
      {
        key: 'act',
        header: 'Actions',
        sortable: false,
        render: () => (
          <>
            <button type="button" onClick={onAction}>
              Delete
            </button>
            <input aria-label="Pick" type="checkbox" />
            <a href="#x">Open</a>
            <span data-no-row-activate="">
              <span>Inert zone</span>
            </span>
          </>
        ),
      },
    ];
    render(<Table caption="Rows" columns={columns} rows={rows} rowKey={(r) => r.id} onRowActivate={onRowActivate} />);
    return { onRowActivate, row: screen.getByText('First').closest('tr') as HTMLTableRowElement };
  }

  it('ignores clicks on controls inside a cell', () => {
    const onAction = vi.fn();
    const { onRowActivate } = setup(onAction);
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Pick' }));
    fireEvent.click(screen.getByRole('link', { name: 'Open' }));
    fireEvent.click(screen.getByText('Inert zone'));
    expect(onAction).toHaveBeenCalledTimes(1);
    expect(onRowActivate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('First'));
    expect(onRowActivate).toHaveBeenCalledTimes(1);
  });

  it('ignores Enter on a focused inner control and keeps it on the row', () => {
    const { onRowActivate, row } = setup();
    fireEvent.keyDown(screen.getByRole('button', { name: 'Delete' }), { key: 'Enter' });
    fireEvent.keyDown(screen.getByRole('checkbox', { name: 'Pick' }), { key: ' ' });
    expect(onRowActivate).not.toHaveBeenCalled();
    fireEvent.keyDown(row, { key: 'Enter' });
    expect(onRowActivate).toHaveBeenCalledTimes(1);
  });

  it('skips a click a handler already prevented', () => {
    const onRowActivate = vi.fn();
    const columns: TableColumn<Row>[] = [{ key: 'name', header: 'Name' }];
    render(
      <Table
        caption="Rows"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        onRowActivate={onRowActivate}
        rowProps={() => ({ onClick: (event) => event.preventDefault() })}
      />,
    );
    fireEvent.click(screen.getByText('First'));
    expect(onRowActivate).not.toHaveBeenCalled();
  });

  it('isFromInteractiveDescendant only counts elements inside the row', () => {
    const row = document.createElement('tr');
    row.setAttribute('role', 'button');
    const cell = document.createElement('td');
    const text = document.createElement('span');
    cell.appendChild(text);
    row.appendChild(cell);
    expect(isFromInteractiveDescendant(text, row)).toBe(false);
    expect(isFromInteractiveDescendant(row, row)).toBe(false);
    const btn = document.createElement('button');
    cell.appendChild(btn);
    expect(isFromInteractiveDescendant(btn, row)).toBe(true);
  });

  it('keeps row focus while the filter changes (tbody is not remounted)', () => {
    const many: Row[] = [
      { id: 'a', name: 'alpha one' },
      { id: 'b', name: 'alpha two' },
    ];
    const columns: TableColumn<Row>[] = [{ key: 'name', header: 'Name' }];
    const { rerender } = render(<Table caption="Rows" columns={columns} rows={many} rowKey={(r) => r.id} onRowActivate={() => undefined} filter="" />);
    const first = screen.getByText('alpha one').closest('tr') as HTMLElement;
    first.focus();
    rerender(<Table caption="Rows" columns={columns} rows={many} rowKey={(r) => r.id} onRowActivate={() => undefined} filter="alpha" />);
    expect(document.activeElement).toBe(first);
  });
});

describe('menu keyboard open (M1)', () => {
  const items = [
    { id: 'off', label: 'Unavailable', onSelect: () => undefined, disabled: true },
    { id: 'edit', label: 'Edit', onSelect: () => undefined },
    { id: 'drop', label: 'Remove', onSelect: () => undefined },
  ];
  function setup() {
    render(
      <main>
        <Menu label="Row actions" items={items} trigger={<button type="button">More</button>} />
      </main>,
    );
    return screen.getByRole('button', { name: 'More' });
  }

  it.each(['ArrowDown', 'Enter', ' '])('focuses the first enabled item after %s', async (key) => {
    const trigger = setup();
    trigger.focus();
    fireEvent.keyDown(trigger, { key });
    await act(async () => undefined);
    expect(document.activeElement?.textContent).toBe('Edit');
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'ArrowDown' });
    expect(document.activeElement?.textContent).toBe('Remove');
  });

  it('focuses the last item after ArrowUp and the first after a click', async () => {
    const trigger = setup();
    fireEvent.keyDown(trigger, { key: 'ArrowUp' });
    await act(async () => undefined);
    expect(document.activeElement?.textContent).toBe('Remove');
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'Escape' });
    await act(async () => undefined);
    await userEvent.click(trigger);
    expect(document.activeElement?.textContent).toBe('Edit');
  });
});

describe('smaller review items', () => {
  it('Cmd+K does not open the palette over another dialog (L1)', () => {
    const onOpenChange = vi.fn();
    render(
      <>
        <Modal open onClose={() => undefined} title="Confirm">
          <p>Body</p>
        </Modal>
        <CommandPalette items={[]} onOpenChange={onOpenChange} />
      </>,
    );
    fireEvent.keyDown(document, { key: 'k', metaKey: true });
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it('themeInitScript escapes < in the key (L7)', () => {
    const script = themeInitScript('x</script><b>');
    expect(script).not.toContain('</script>');
    expect(script).toContain('\\u003c/script>');
  });

  it('onMediaChange falls back to addListener (L8)', () => {
    const add = vi.fn();
    const remove = vi.fn();
    const legacy = { matches: false, addListener: add, removeListener: remove } as unknown as MediaQueryList;
    const listener = () => undefined;
    const off = onMediaChange(legacy, listener);
    expect(add).toHaveBeenCalledWith(listener);
    off();
    expect(remove).toHaveBeenCalledWith(listener);
  });
});
