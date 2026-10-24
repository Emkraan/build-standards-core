/* Wave 2 root parts: error and list states, Table selection, the selection and list bars, the
   removable Badge, the ProgressBar meter, FormSection, CardHead variants, typed confirmation and the
   media hooks. Each extends an existing part where one already covered the job (see MIGRATION.md). */
import { act, fireEvent, render, renderHook, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { useEffect } from 'react';
import { describe, expect, it, vi } from 'vitest';
import {
  Badge,
  CardHead,
  ErrorState,
  FormSection,
  Input,
  Field,
  ListFooter,
  ProgressBar,
  SelectionBar,
  Skeleton,
  Table,
  errorDetail,
  readColorScheme,
  useConfirm,
  useIsPhone,
  useMediaQuery,
  useRowSelection,
} from '../src';
import type { ConfirmApi, TableColumn } from '../src';
import { media } from './helpers';

async function noAxe(el: Element) {
  const r = await axe.run(el, { rules: { region: { enabled: false } } });
  expect(r.violations.map((v) => v.id)).toEqual([]);
}

describe('ErrorState', () => {
  it('names the failure, shows the message and retries', async () => {
    const onRetry = vi.fn();
    const { container } = render(<ErrorState error={new Error('Gateway timed out')} onRetry={onRetry} />);
    expect(screen.getByText('Could not load.')).toBeTruthy();
    expect(screen.getByText('Gateway timed out')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    await noAxe(container);
  });

  it('shows no Retry without a handler and prefers an explicit message', () => {
    render(<ErrorState error="raw" message="Try again in a minute." />);
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.getByText('Try again in a minute.')).toBeTruthy();
    expect(screen.queryByText('raw')).toBeNull();
  });

  it('errorDetail reads an Error or a string and ignores anything else', () => {
    expect(errorDetail(new Error('x'))).toBe('x');
    expect(errorDetail('y')).toBe('y');
    expect(errorDetail({ message: 'z' })).toBeUndefined();
    expect(errorDetail('')).toBeUndefined();
  });
});

describe('Skeleton variant list', () => {
  it('renders one row block per count', () => {
    const { container } = render(<Skeleton variant="list" count={4} />);
    expect(container.querySelectorAll('[data-shape="row"]').length).toBe(4);
  });
});

interface Row {
  id: string;
  name: string;
  locked?: boolean;
}

const rows: Row[] = [
  { id: 'a', name: 'alpha' },
  { id: 'b', name: 'bravo' },
  { id: 'c', name: 'charlie', locked: true },
];

const columns: TableColumn<Row>[] = [{ key: 'name', header: 'Name' }];

function SelectableTable({ onIds }: { onIds: (ids: string[]) => void }) {
  const selection = useRowSelection();
  useEffect(() => {
    onIds(selection.ids);
  });
  return (
    <Table<Row>
      caption="Hosts"
      rows={rows}
      columns={columns}
      rowKey={(r) => r.id}
      selection={selection}
      isRowSelectable={(r) => !r.locked}
    />
  );
}

describe('Table selection', () => {
  it('adds a labelled checkbox column, and select-all skips locked rows', async () => {
    let ids: string[] = [];
    const { container } = render(
      <SelectableTable
        onIds={(next) => {
          ids = next;
        }}
      />,
    );
    const alpha = screen.getByRole('checkbox', { name: 'Select alpha' });
    fireEvent.click(alpha);
    expect(ids).toEqual(['a']);
    const all = screen.getByRole('checkbox', { name: 'Select all visible rows' });
    expect((all as HTMLInputElement).indeterminate).toBe(true);
    fireEvent.click(all);
    expect([...ids].sort()).toEqual(['a', 'b']);
    expect((screen.getByRole('checkbox', { name: 'Select charlie' }) as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(all);
    expect(ids).toEqual([]);
    await noAxe(container);
  });

  it('gives a picked row the selected tint', () => {
    render(<SelectableTable onIds={() => undefined} />);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select bravo' }));
    const row = screen.getByRole('checkbox', { name: 'Select bravo' }).closest('tr');
    expect(row?.className).toContain('is-selected');
  });

  it('useRowSelection keeps ids that leave the page until cleared', () => {
    const { result, rerender } = renderHook(({ visible }) => useRowSelection(visible), {
      initialProps: { visible: ['a', 'b'] as readonly string[] },
    });
    act(() => result.current.toggleAll(true));
    expect(result.current.allSelected).toBe(true);
    rerender({ visible: ['c'] });
    expect(result.current.count).toBe(2);
    expect(result.current.someSelected).toBe(false);
    act(() => result.current.clear());
    expect(result.current.count).toBe(0);
  });
});

describe('SelectionBar and ListFooter', () => {
  it('renders nothing at zero, then the count, the actions and Clear', async () => {
    const onClear = vi.fn();
    const onDelete = vi.fn();
    const { container, rerender } = render(
      <SelectionBar count={0} onClear={onClear} actions={[{ label: 'Delete', onClick: onDelete, danger: true }]} />,
    );
    expect(container.firstChild).toBeNull();
    rerender(<SelectionBar count={3} onClear={onClear} actions={[{ label: 'Delete', onClick: onDelete, danger: true }]} />);
    const bar = screen.getByRole('region', { name: 'Selection' });
    expect(bar.textContent).toContain('3 selected');
    fireEvent.click(within(bar).getByRole('button', { name: 'Delete' }));
    fireEvent.click(within(bar).getByRole('button', { name: 'Clear selection' }));
    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(onClear).toHaveBeenCalledTimes(1);
    await noAxe(container);
  });

  it('ListFooter shows the counts, the freshness and the pager slot', () => {
    render(
      <ListFooter shown={25} total={140} updatedAt={new Date(Date.now() - 30_000)}>
        <button type="button">Next</button>
      </ListFooter>,
    );
    expect(screen.getByText(/Showing/).textContent).toBe('Showing 25 of 140');
    expect(screen.getByText(/Updated/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Next' })).toBeTruthy();
  });
});

describe('Badge onRemove (removable tag)', () => {
  it('adds a named remove button that is disabled while removing', async () => {
    const onRemove = vi.fn();
    const { container, rerender } = render(<Badge onRemove={onRemove}>prod</Badge>);
    fireEvent.click(screen.getByRole('button', { name: 'Remove prod' }));
    expect(onRemove).toHaveBeenCalledTimes(1);
    rerender(
      <Badge onRemove={onRemove} removing removeLabel="the prod tag">
        prod
      </Badge>,
    );
    expect((screen.getByRole('button', { name: 'Remove the prod tag' }) as HTMLButtonElement).disabled).toBe(true);
    expect(container.querySelector('.badge')?.getAttribute('aria-busy')).toBe('true');
    expect(container.querySelector('.badge-remove .spinner')).toBeTruthy();
    await noAxe(container);
  });
});

describe('ProgressBar meter', () => {
  it('is a labelled meter with its value', async () => {
    const { container } = render(<ProgressBar meter value={62} label="Disk used" tone="warning" />);
    const meter = screen.getByRole('meter', { name: 'Disk used' });
    expect(meter.getAttribute('aria-valuenow')).toBe('62');
    expect(meter.className).toContain('meter');
    await noAxe(container);
  });

  it('stays a progressbar without meter', () => {
    render(<ProgressBar value={10} label="Upload" />);
    expect(screen.getByRole('progressbar', { name: 'Upload' })).toBeTruthy();
  });
});

describe('FormSection', () => {
  it('groups fields in a named fieldset', async () => {
    const { container } = render(
      <FormSection title="Network" description="Where the host lives." columns={1}>
        <Field label="Hostname">
          <Input />
        </Field>
      </FormSection>,
    );
    const group = screen.getByRole('group', { name: 'Network' });
    expect(group.getAttribute('data-columns')).toBe('1');
    expect(within(group).getByLabelText('Hostname')).toBeTruthy();
    await noAxe(container);
  });
});

describe('CardHead variants (PanelHead, CardTitle, SectionLabel)', () => {
  it('panel and label keep a real heading and add the variant class', () => {
    const { container } = render(
      <>
        <CardHead variant="panel" title="Activity" subtitle="Last 24 hours" controls={<button type="button">Export</button>} />
        <CardHead variant="label" level={3} title="Pinned" count={4} />
      </>,
    );
    expect(screen.getByRole('heading', { level: 2, name: 'Activity' })).toBeTruthy();
    const label = screen.getByRole('heading', { level: 3 });
    expect(label.textContent).toBe('Pinned4');
    expect(container.querySelector('.card-head-panel')).toBeTruthy();
    expect(container.querySelector('.card-head-label .card-head-count')?.textContent).toBe('4');
  });

  it('the default variant adds no variant class', () => {
    const { container } = render(<CardHead title="Hosts" />);
    expect(container.querySelector('.card-head')?.className).toBe('card-head');
  });
});

function ConfirmHost({ onApi }: { onApi: (api: ConfirmApi) => void }) {
  const api = useConfirm();
  useEffect(() => {
    onApi(api);
  });
  return <>{api.dialog}</>;
}

describe('useConfirm requireText (typed confirmation)', () => {
  it('keeps the verb disabled until the text matches exactly', async () => {
    const user = userEvent.setup();
    const h: { api: ConfirmApi | null } = { api: null };
    render(<ConfirmHost onApi={(a) => (h.api = a)} />);
    let pending!: Promise<boolean>;
    act(() => {
      pending = h.api!.confirm({ title: 'Delete the vault?', confirmLabel: 'Delete', danger: true, requireText: 'vault-01' });
    });
    const dialog = await screen.findByRole('alertdialog', { name: 'Delete the vault?' });
    const verb = within(dialog).getByRole('button', { name: 'Delete' }) as HTMLButtonElement;
    expect(verb.disabled).toBe(true);
    const field = within(dialog).getByLabelText('Type vault-01 to confirm');
    await user.type(field, 'vault-0');
    expect(verb.disabled).toBe(true);
    await user.type(field, '1');
    expect(verb.disabled).toBe(false);
    await user.click(verb);
    await expect(pending).resolves.toBe(true);
  });
});

describe('media hooks', () => {
  it('useMediaQuery and useIsPhone read matchMedia', () => {
    media.desktop = true;
    expect(renderHook(() => useMediaQuery('(min-width: 901px)')).result.current).toBe(true);
    expect(renderHook(() => useIsPhone()).result.current).toBe(false);
  });

  it('readColorScheme follows data-theme, then the OS', () => {
    document.documentElement.setAttribute('data-theme', 'light');
    expect(readColorScheme()).toBe('light');
    document.documentElement.setAttribute('data-theme', 'dark');
    expect(readColorScheme()).toBe('dark');
    document.documentElement.removeAttribute('data-theme');
    media.light = true;
    expect(readColorScheme()).toBe('light');
  });
});
