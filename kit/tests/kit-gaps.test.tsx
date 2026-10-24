/* The optional props added for the first full adoptions: Spinner and live Pill, the urgent tone,
   Table row hooks and controlled sort, Segmented tone and badge, Modal close reasons and focus
   rescue, Input size, compact SearchTrigger, palette query callback, banner action, Rail status
   and the NavItem soft badge. Each default keeps the earlier output. */
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import {
  AnnouncementBanner,
  AnnouncementStack,
  AppShell,
  Badge,
  CommandPalette,
  Field,
  Header,
  Input,
  Modal,
  NavGroup,
  NavItem,
  Pill,
  Rail,
  SearchTrigger,
  Segmented,
  STORAGE_KEYS,
  Spinner,
  StatusDot,
  Table,
} from '../src/index';
import type { ModalCloseReason, SortState, TableColumn } from '../src/index';

const AXE: axe.RunOptions = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } }, resultTypes: ['violations'] };

async function violations(root: Element): Promise<string[]> {
  const result = await axe.run(root, AXE);
  return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`);
}

describe('Spinner and live Pill', () => {
  it('is hidden from screen readers by default and a status with a label', () => {
    const { container, rerender } = render(<Spinner />);
    const ring = container.querySelector('.spinner');
    expect(ring?.getAttribute('aria-hidden')).toBe('true');
    expect(ring?.getAttribute('data-size')).toBe('sm');
    expect(screen.queryByRole('status')).toBeNull();
    rerender(<Spinner size="lg" label="Syncing" />);
    expect(screen.getByRole('status').textContent).toBe('Syncing');
    expect(container.querySelector('.spinner')?.getAttribute('data-size')).toBe('lg');
  });

  it('renders the spinner before the label in a live Pill, in place of the dot', async () => {
    const { container } = render(
      <div>
        <Pill tone="info" live dot>
          Running
        </Pill>
        <Pill tone="success">Done</Pill>
      </div>,
    );
    const live = screen.getByText('Running');
    expect(live.getAttribute('data-live')).toBe('');
    expect(live.firstElementChild?.classList.contains('spinner')).toBe(true);
    expect(live.querySelector('.badge-dot')).toBeNull();
    expect(screen.getByText('Done').hasAttribute('data-live')).toBe(false);
    expect(screen.getByText('Done').querySelector('.spinner')).toBeNull();
    expect(await violations(container)).toEqual([]);
  });

  it('holds still under reduced motion and turns on the --dur-spin token', () => {
    const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');
    expect(css).toMatch(/\.spinner::after \{[^}]*animation: kit-spin var\(--dur-spin\) linear infinite/);
    const reduced = css.slice(css.lastIndexOf('@media (prefers-reduced-motion: reduce)'));
    expect(reduced).toMatch(/\.spinner::after/);
  });
});

describe('urgent tone', () => {
  it('reaches Badge, Pill and StatusDot', () => {
    render(
      <div>
        <Badge tone="urgent">High</Badge>
        <Pill tone="urgent" live>
          Escalating
        </Pill>
        <StatusDot tone="urgent" label="High priority" />
      </div>,
    );
    expect(screen.getByText('High').getAttribute('data-tone')).toBe('urgent');
    expect(screen.getByText('Escalating').getAttribute('data-tone')).toBe('urgent');
    expect(screen.getByRole('img', { name: 'High priority' }).getAttribute('data-tone')).toBe('urgent');
  });

  it('has a tone rule for every urgent mark and a certified token in both themes', () => {
    const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');
    for (const sel of ['.badge[data-tone="urgent"]', '.status-dot[data-tone="urgent"]', '.seg-dot[data-tone="urgent"]']) expect(css).toContain(sel);
    const tokens = readFileSync(resolve(__dirname, '../../tokens/tokens.css'), 'utf8');
    const dark = tokens.slice(0, tokens.indexOf('@media (prefers-color-scheme: light)'));
    const light = tokens.slice(tokens.indexOf('[data-theme="light"]'));
    for (const part of [dark, light]) {
      expect(part).toMatch(/--urgent: #[0-9a-f]{6};/);
      expect(part).toMatch(/--urgent-dim: #[0-9a-f]{6};/);
    }
  });
});

interface Row {
  id: string;
  name: string;
  level: 'critical' | 'ok';
}

const ROWS: Row[] = [
  { id: 'a', name: 'Beta', level: 'ok' },
  { id: 'b', name: 'Alpha', level: 'critical' },
];
const COLS: TableColumn<Row>[] = [
  { key: 'name', header: 'Name' },
  { key: 'level', header: 'Level' },
];

function names(): string[] {
  return screen
    .getAllByRole('row')
    .slice(1)
    .map((r) => within(r).getAllByRole('cell')[0]?.textContent ?? '');
}

describe('Table row hooks and controlled sort', () => {
  it('adds a class and attributes per row and still activates rows', () => {
    const activate = vi.fn();
    const own = vi.fn();
    render(
      <Table
        caption="Items"
        columns={COLS}
        rows={ROWS}
        rowKey={(r) => r.id}
        rowClassName={(r) => (r.level === 'critical' ? 'is-critical' : undefined)}
        rowProps={(r) => ({ 'data-level': r.level, title: r.name, onClick: own })}
        onRowActivate={activate}
      />,
    );
    const [first, second] = screen.getAllByRole('row').slice(1);
    expect(first?.className).toContain('table-row');
    expect(first?.className).toContain('is-critical');
    expect(first?.getAttribute('data-level')).toBe('critical');
    expect(second?.className).not.toContain('is-critical');
    expect(second?.getAttribute('title')).toBe('Beta');
    fireEvent.click(second as HTMLElement);
    expect(own).toHaveBeenCalledTimes(1);
    expect(activate).toHaveBeenCalledWith(ROWS[0]);
  });

  it('shows a controlled sort and reports clicks without changing it alone', () => {
    const onSortChange = vi.fn();
    const { rerender } = render(<Table caption="Items" columns={COLS} rows={ROWS} rowKey={(r) => r.id} sort={{ key: 'name', dir: 'desc' }} onSortChange={onSortChange} />);
    expect(names()).toEqual(['Beta', 'Alpha']);
    fireEvent.click(screen.getByRole('button', { name: 'Name' }));
    expect(onSortChange).toHaveBeenCalledWith({ key: 'name', dir: 'asc' });
    expect(names()).toEqual(['Beta', 'Alpha']);
    rerender(<Table caption="Items" columns={COLS} rows={ROWS} rowKey={(r) => r.id} sort={null} onSortChange={onSortChange} />);
    expect(names()).toEqual(['Beta', 'Alpha']);
    expect(screen.getAllByRole('columnheader')[0]?.getAttribute('aria-sort')).toBe('none');
  });

  it('persists through a parent that owns the sort', () => {
    const seen: SortState[] = [];
    function Host() {
      const [sort, setSort] = useState<SortState | null>({ key: 'name', dir: 'asc' });
      return (
        <Table
          caption="Items"
          columns={COLS}
          rows={ROWS}
          rowKey={(r) => r.id}
          sort={sort}
          onSortChange={(s) => {
            seen.push(s);
            setSort(s);
          }}
        />
      );
    }
    render(<Host />);
    expect(names()).toEqual(['Alpha', 'Beta']);
    fireEvent.click(screen.getByRole('button', { name: 'Name' }));
    expect(names()).toEqual(['Beta', 'Alpha']);
    expect(seen).toEqual([{ key: 'name', dir: 'desc' }]);
  });

  it('stays uncontrolled by default and still reports changes', () => {
    const onSortChange = vi.fn();
    render(<Table caption="Items" columns={COLS} rows={ROWS} rowKey={(r) => r.id} onSortChange={onSortChange} />);
    expect(names()).toEqual(['Alpha', 'Beta']);
    fireEvent.click(screen.getByRole('button', { name: 'Name' }));
    expect(names()).toEqual(['Beta', 'Alpha']);
    expect(onSortChange).toHaveBeenCalledWith({ key: 'name', dir: 'desc' });
  });
});

describe('Segmented tone and badge', () => {
  it('renders a tone dot and a count inside the option and passes axe', async () => {
    const { container } = render(
      <Segmented
        label="Queue"
        value="all"
        onChange={() => undefined}
        options={[
          { value: 'all', label: 'All', badge: 24 },
          { value: 'late', label: 'Late', tone: 'warning', badge: 3 },
          { value: 'plain', label: 'Plain' },
        ]}
      />,
    );
    const late = screen.getByRole('button', { name: 'Late 3' });
    expect(late.getAttribute('data-tone')).toBe('warning');
    expect(late.querySelector('.seg-dot')?.getAttribute('aria-hidden')).toBe('true');
    expect(late.querySelector('.seg-badge')?.textContent).toBe('3');
    const plain = screen.getByRole('button', { name: 'Plain' });
    expect(plain.hasAttribute('data-tone')).toBe(false);
    expect(plain.children.length).toBe(0);
    expect(await violations(container)).toEqual([]);
  });
});

describe('Modal close reason and focus rescue', () => {
  function Host({ onReason }: { onReason: (r: ModalCloseReason) => void }) {
    const [open, setOpen] = useState(true);
    return (
      <Modal
        open={open}
        title="Step"
        onClose={(reason) => {
          onReason(reason);
          setOpen(false);
        }}
      >
        <p>Body</p>
      </Modal>
    );
  }

  it('passes escape, backdrop and close', async () => {
    const user = userEvent.setup();
    const reasons: ModalCloseReason[] = [];
    const push = (r: ModalCloseReason) => reasons.push(r);
    const a = render(<Host onReason={push} />);
    await user.keyboard('{Escape}');
    a.unmount();
    const b = render(<Host onReason={push} />);
    fireEvent.mouseDown(document.querySelector('.modal-backdrop') as HTMLElement);
    b.unmount();
    const c = render(<Host onReason={push} />);
    await user.click(screen.getByRole('button', { name: 'Close' }));
    c.unmount();
    render(<Host onReason={push} />);
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(reasons).toEqual(['escape', 'backdrop', 'close', 'close']);
  });

  it('keeps working with a handler that takes no argument', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn(() => undefined);
    render(
      <Modal open title="Plain" onClose={onClose}>
        <p>Body</p>
      </Modal>,
    );
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('lets a nested step back out on Escape only', async () => {
    const user = userEvent.setup();
    function Wizard() {
      const [step, setStep] = useState(2);
      const [open, setOpen] = useState(true);
      return (
        <Modal open={open} title={`Step ${step}`} onClose={(reason) => (reason === 'escape' && step > 1 ? setStep(step - 1) : setOpen(false))}>
          <p>Body</p>
        </Modal>
      );
    }
    render(<Wizard />);
    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog', { name: 'Step 1' })).toBeTruthy();
  });

  it('moves focus to the panel when the focused node unmounts', async () => {
    function Swap() {
      const [first, setFirst] = useState(true);
      return (
        <Modal open title="Swap" onClose={() => undefined} cancelLabel={null} hideClose>
          {first ? (
            <button type="button" data-autofocus="" onClick={() => setFirst(false)}>
              Next step
            </button>
          ) : (
            <p>Second step</p>
          )}
        </Modal>
      );
    }
    render(<Swap />);
    const next = screen.getByRole('button', { name: 'Next step' });
    expect(document.activeElement).toBe(next);
    await act(async () => {
      next.click();
      await Promise.resolve();
    });
    expect(screen.getByText('Second step')).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole('dialog', { name: 'Swap' }));
  });
});

describe('Input size', () => {
  it('marks sm, leaves md as before and keeps a numeric native size', () => {
    render(
      <div>
        <Field label="Small">
          <Input size="sm" />
        </Field>
        <Field label="Default">
          <Input />
        </Field>
        <Field label="Native">
          <Input size={12} />
        </Field>
      </div>,
    );
    expect(screen.getByLabelText('Small').getAttribute('data-size')).toBe('sm');
    expect(screen.getByLabelText('Small').hasAttribute('size')).toBe(false);
    expect(screen.getByLabelText('Default').hasAttribute('data-size')).toBe(false);
    expect(screen.getByLabelText('Native').getAttribute('size')).toBe('12');
    expect(screen.getByLabelText('Native').hasAttribute('data-size')).toBe(false);
  });
});

describe('SearchTrigger compact', () => {
  it('keeps the label by default and puts the shortcut in the name when compact', async () => {
    const { container } = render(
      <div>
        <SearchTrigger />
        <SearchTrigger label="Find" compact />
        <SearchTrigger label="Look up" compact="auto" />
      </div>,
    );
    const plain = screen.getByRole('button', { name: 'Search' });
    expect(plain.hasAttribute('data-compact')).toBe(false);
    const icon = screen.getByRole('button', { name: 'Find (Ctrl+K)' });
    expect(icon.getAttribute('data-compact')).toBe('on');
    expect(icon.getAttribute('data-tip')).toBe('Find');
    expect(icon.getAttribute('aria-keyshortcuts')).toBe('Control+K');
    const auto = screen.getByRole('button', { name: 'Look up (Ctrl+K)' });
    expect(auto.getAttribute('data-compact')).toBe('auto');
    const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');
    expect(css).toMatch(/@media \(max-width: 640px\) \{\s*\.search-btn\[data-compact="auto"\]/);
    expect(await violations(container)).toEqual([]);
  });
});

describe('CommandPalette onQueryChange', () => {
  it('reports each query and the reset on reopen', async () => {
    const user = userEvent.setup();
    const queries: string[] = [];
    render(<CommandPalette items={[{ id: 'a', label: 'Alpha', onSelect: () => undefined }]} onQueryChange={(q) => queries.push(q)} />);
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
    await user.type(screen.getByRole('combobox'), 'al');
    expect(queries).toEqual(['a', 'al']);
    await user.keyboard('{Escape}');
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
    expect(queries).toEqual(['a', 'al', '']);
    expect((screen.getByRole('combobox') as HTMLInputElement).value).toBe('');
  });
});

describe('AnnouncementBanner action and dismiss', () => {
  it('renders an action and can hide dismiss', async () => {
    const { container } = render(
      <AnnouncementStack
        announcements={[
          { id: 'x1', tone: 'critical', title: 'Sync is failing', action: <a className="announce-link" href="#status">View status</a>, dismissible: false },
          { id: 'x2', tone: 'info', title: 'New reports' },
        ]}
      />,
    );
    expect(screen.getByRole('link', { name: 'View status' }).closest('.announce-action')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Dismiss announcement: Sync is failing' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Dismiss announcement: New reports' })).toBeTruthy();
    expect(await violations(container)).toEqual([]);
  });

  it('shows a non-dismissible banner even when its id was dismissed before', () => {
    window.localStorage.setItem(STORAGE_KEYS.announcementsDismissed, JSON.stringify(['y1']));
    render(<AnnouncementBanner id="y1" tone="warning" title="Still degraded" dismissible={false} />);
    expect(screen.getByText('Still degraded')).toBeTruthy();
  });
});

describe('Rail status and NavItem soft badge', () => {
  it('renders the status line under the footer and a soft badge with a working spinner', async () => {
    const { container } = render(
      <AppShell
        pathname="/"
        rail={
          <Rail brandMark="K" brandName="Test app" footer={<p>Build</p>} status="Data refreshed 2 min ago">
            <NavGroup label="Main">
              <NavItem href="/" label="Home" icon={<span>H</span>} active />
              <NavItem href="/queue" label="Queue" icon={<span>Q</span>} badge={12} softBadge={3} working />
              <NavItem href="/plain" label="Plain" icon={<span>P</span>} badge={2} />
            </NavGroup>
          </Rail>
        }
        header={<Header title="Home" />}
      >
        <p>Content</p>
      </AppShell>,
    );
    const status = screen.getByText('Data refreshed 2 min ago');
    expect(status.className).toBe('rail-status');
    expect(status.parentElement?.className).toBe('build-wrap');
    expect(status.previousElementSibling?.textContent).toBe('Build');
    const queue = screen.getByRole('link', { name: /Queue/ });
    const soft = queue.querySelector('.nav-badge-soft');
    expect(soft?.textContent).toBe('Working 3');
    expect(soft?.querySelector('.spinner')?.getAttribute('aria-hidden')).toBe('true');
    expect(queue.querySelectorAll('.nav-badge').length).toBe(2);
    expect(screen.getByRole('link', { name: /Plain/ }).querySelector('.nav-badge-soft')).toBeNull();
    expect(await violations(container)).toEqual([]);
  });
});

describe('cascade layer', () => {
  it('ships hub-layer.css and kit.css inside the one core layer', () => {
    for (const file of ['../src/styles/kit.css', '../../tokens/hub-layer.css']) {
      const css = readFileSync(resolve(__dirname, file), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
      const first = css.trim().split('\n')[0];
      expect(first).toBe('@layer core {');
      expect(css.trim().endsWith('}')).toBe(true);
      expect(css.match(/@layer/g)?.length).toBe(1);
    }
  });
});
