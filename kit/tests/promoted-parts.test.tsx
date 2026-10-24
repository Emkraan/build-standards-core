/* Parts promoted from a consumer's local library into the kit: breadcrumb, pagination, text helpers,
   page states, search input, progress bar, text diff, impersonation banner and the error boundary. */
import { act, fireEvent, render, screen } from '@testing-library/react';
import axe from 'axe-core';
import { describe, expect, it, vi } from 'vitest';
import {
  Breadcrumb,
  CopyButton,
  ErrorBoundary,
  Forbidden,
  ImpersonationBanner,
  Mono,
  NotFound,
  Pagination,
  ProgressBar,
  RelativeTime,
  SearchInput,
  TextDiff,
  diffLines,
  formatRelative,
  freshness,
} from '../src';

async function noAxe(el: Element) {
  const r = await axe.run(el, { rules: { region: { enabled: false } } });
  expect(r.violations.map((v) => v.id)).toEqual([]);
}

describe('Breadcrumb', () => {
  it('marks the last crumb as the page and never links it', async () => {
    const { container } = render(<Breadcrumb items={[{ label: 'Home', href: '/' }, { label: 'Runs', href: '/runs' }, { label: 'Run 7' }]} />);
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toBeTruthy();
    expect(screen.getByText('Run 7').getAttribute('aria-current')).toBe('page');
    expect(screen.getByText('Run 7').tagName).toBe('SPAN');
    expect(screen.getByText('Runs').getAttribute('href')).toBe('/runs');
    await noAxe(container);
  });
  it('routes href crumbs through renderLink and onClick crumbs through a button', () => {
    const go = vi.fn();
    render(
      <Breadcrumb
        items={[{ label: 'Home', href: '/' }, { label: 'Back', onClick: go }, { label: 'Here' }]}
        renderLink={({ className, children, item }) => <a className={className} data-routed={item.href} href={item.href}>{children}</a>}
      />,
    );
    expect(screen.getByText('Home').getAttribute('data-routed')).toBe('/');
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(go).toHaveBeenCalledOnce();
  });
});

describe('Pagination', () => {
  it('states the count and disables the ends', () => {
    const next = vi.fn();
    render(<Pagination page={1} pageSize={40} total={300} unit="runs" onNext={next} />);
    expect(screen.getByText('1 to 40 of 300 runs')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Previous' }).hasAttribute('disabled')).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(next).toHaveBeenCalledOnce();
  });
  it('says so when empty', () => {
    render(<Pagination pageSize={10} total={0} />);
    expect(screen.getByText('No entries')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Next' }).hasAttribute('disabled')).toBe(true);
  });
});

describe('text helpers', () => {
  it('formats ages', () => {
    expect(formatRelative(5)).toBe('just now');
    expect(formatRelative(300)).toBe('5m ago');
    expect(formatRelative(7200)).toBe('2h ago');
    expect(formatRelative(86400 * 3)).toBe('3d ago');
  });
  it('RelativeTime carries the absolute time and handles a missing value', () => {
    const { rerender } = render(<RelativeTime value={new Date(Date.now() - 120000)} />);
    const t = screen.getByText('2m ago');
    expect(t.tagName).toBe('TIME');
    expect(t.getAttribute('dateTime')).toMatch(/T/);
    rerender(<RelativeTime value={null} />);
    expect(screen.getByText('undated')).toBeTruthy();
  });
  it('freshness maps age to a tone', () => {
    expect(freshness(new Date().toISOString()).tone).toBe('success');
    expect(freshness(new Date(Date.now() - 60 * 86400000).toISOString()).tone).toBe('warning');
    expect(freshness(new Date(Date.now() - 200 * 86400000).toISOString()).tone).toBe('danger');
    expect(freshness(null).label).toBe('undated');
  });
  it('Mono marks dim runs', () => {
    render(<Mono dim>-</Mono>);
    expect(screen.getByText('-').hasAttribute('data-dim')).toBe(true);
  });
  it('CopyButton copies and announces the result', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<CopyButton value="abc123" />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy: abc123' }));
    });
    expect(writeText).toHaveBeenCalledWith('abc123');
    expect(screen.getByRole('status').textContent).toBe('Copied');
    expect(screen.getByRole('button').getAttribute('data-state')).toBe('copied');
  });
});

describe('page states', () => {
  it('Forbidden and NotFound render an h1, the detail and a way home', async () => {
    const { container, rerender } = render(<Forbidden permission="runs.write" />);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toContain('do not have access');
    expect(screen.getByText('runs.write')).toBeTruthy();
    expect(screen.getByRole('link').getAttribute('href')).toBe('/');
    await noAxe(container);
    rerender(<NotFound path="/nope" action={<button type="button">Back</button>} />);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Page not found');
    expect(screen.getByRole('button', { name: 'Back' })).toBeTruthy();
  });
});

describe('SearchInput', () => {
  it('is controlled, clears, and focuses on its hotkey but not while typing elsewhere', () => {
    const change = vi.fn();
    const { rerender } = render(
      <>
        <input aria-label="other" />
        <SearchInput value="" onChange={change} focusHotkey="/" placeholder="Filter runs" />
      </>,
    );
    const box = screen.getByRole('searchbox', { name: 'Filter runs' });
    fireEvent.keyDown(window, { key: '/' });
    expect(document.activeElement).toBe(box);
    const other = screen.getByRole('textbox', { name: 'other' });
    other.focus();
    fireEvent.keyDown(other, { key: '/' });
    expect(document.activeElement).toBe(other);
    fireEvent.change(box, { target: { value: 'abc' } });
    expect(change).toHaveBeenLastCalledWith('abc');
    rerender(
      <>
        <input aria-label="other" />
        <SearchInput value="abc" onChange={change} focusHotkey="/" placeholder="Filter runs" />
      </>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Clear search' }));
    expect(change).toHaveBeenLastCalledWith('');
  });
});

describe('ProgressBar', () => {
  it('is a labelled progressbar, clamped, and indeterminate without a value', async () => {
    const { container, rerender } = render(<ProgressBar value={150} label="Upload" />);
    const bar = screen.getByRole('progressbar', { name: 'Upload' });
    expect(bar.getAttribute('aria-valuenow')).toBe('150');
    expect(bar.style.getPropertyValue('--progress')).toBe('100');
    await noAxe(container);
    rerender(<ProgressBar label="Scanning" tone="warning" />);
    expect(screen.getByRole('progressbar').getAttribute('data-state')).toBe('indeterminate');
    expect(screen.getByRole('progressbar').hasAttribute('aria-valuenow')).toBe(false);
  });
});

describe('TextDiff', () => {
  it('diffs by line with real markers', () => {
    expect(diffLines('a\nb\nc', 'a\nc\nd').map((l) => `${l.kind}:${l.text}`)).toEqual(['same:a', 'del:b', 'same:c', 'add:d']);
    expect(diffLines('', '')).toEqual([]);
    const { container, rerender } = render(<TextDiff before="x" after="y" />);
    expect(container.querySelector('[data-kind="del"].text-diff-line')?.textContent).toContain('-x');
    rerender(<TextDiff before="same" after="same" />);
    expect(screen.getByText('No differences.')).toBeTruthy();
  });
  it('numbers each line against the before and the after text', () => {
    expect(diffLines('a\nb\nc', 'a\nc\nd').map((l) => [l.oldNumber, l.newNumber])).toEqual([
      [1, 1],
      [2, null],
      [3, 2],
      [null, 3],
    ]);
    expect(diffLines('a', 'a\nb\nc').map((l) => [l.oldNumber, l.newNumber])).toEqual([
      [1, 1],
      [null, 2],
      [null, 3],
    ]);
    expect(diffLines('a\nb\nc', 'a').map((l) => [l.oldNumber, l.newNumber])).toEqual([
      [1, 1],
      [2, null],
      [3, null],
    ]);
  });
  it('shows no gutter unless lineNumbers is set', () => {
    const { container } = render(<TextDiff before={'a\nb'} after={'a\nc'} />);
    expect(container.querySelector('.text-diff-num')).toBeNull();
    expect(container.querySelector('.text-diff-body')?.getAttribute('data-line-numbers')).toBeNull();
  });
  it('renders old and new gutters, hidden from assistive technology, and keeps the text readable', async () => {
    const { container } = render(<TextDiff lineNumbers before={'a\nb\nc'} after={'a\nc\nd'} />);
    const rows = Array.from(container.querySelectorAll('.text-diff-line'));
    const nums = rows.map((r) => Array.from(r.querySelectorAll('.text-diff-num')).map((n) => n.textContent));
    expect(nums).toEqual([
      ['1', '1'],
      ['2', ''],
      ['3', '2'],
      ['', '3'],
    ]);
    for (const n of Array.from(container.querySelectorAll('.text-diff-num'))) expect(n.getAttribute('aria-hidden')).toBe('true');
    expect(container.querySelector('[data-kind="del"].text-diff-line')?.textContent).toContain('-b');
    expect(container.querySelector('[data-kind="add"].text-diff-line')?.textContent).toContain('+d');
    await noAxe(container);
  });
  it('sizes the gutter to the widest number', () => {
    const many = Array.from({ length: 120 }, (_, i) => `l${i}`).join('\n');
    const { container } = render(<TextDiff lineNumbers before={many} after={`${many}\nend`} />);
    expect((container.querySelector('.text-diff-body') as HTMLElement).style.getPropertyValue('--diff-gutter-digits')).toBe('3');
  });
});

describe('ImpersonationBanner', () => {
  it('names who is being viewed and exits', () => {
    const exit = vi.fn();
    render(<ImpersonationBanner roleName="Reader" asUser="ada" via="sso" onExit={exit} />);
    expect(screen.getByRole('status').textContent).toContain('Viewing as ada (Reader) - sso');
    fireEvent.click(screen.getByRole('button', { name: 'Exit' }));
    expect(exit).toHaveBeenCalledOnce();
  });
});

describe('ErrorBoundary', () => {
  it('catches a render crash, reports it and shows the recovery screen', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const onError = vi.fn();
    const Boom = () => {
      throw new Error('kaboom');
    };
    render(
      <ErrorBoundary onError={onError}>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('alert').textContent).toContain('Something went wrong');
    expect(screen.getByRole('button', { name: 'Reload' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reset session' })).toBeTruthy();
    expect(onError).toHaveBeenCalledOnce();
    spy.mockRestore();
  });
  it('uses a custom fallback with a working reset', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    let fail = true;
    const Maybe = () => {
      if (fail) throw new Error('once');
      return <p>recovered</p>;
    };
    render(
      <ErrorBoundary fallback={(e, reset) => <button type="button" onClick={reset}>{e.message}</button>}>
        <Maybe />
      </ErrorBoundary>,
    );
    fail = false;
    fireEvent.click(screen.getByRole('button', { name: 'once' }));
    expect(screen.getByText('recovered')).toBeTruthy();
    spy.mockRestore();
  });
});
