/* Pagination for an unknown total: the count line, Next from hasMore or a full page, onPage,
   usePagination with a null total, and that a known total behaves as before. */
import { fireEvent, render, renderHook, screen, act } from '@testing-library/react';
import axe from 'axe-core';
import { describe, expect, it, vi } from 'vitest';
import { Pagination, usePagination } from '../src';

async function noAxe(container: HTMLElement) {
  const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } });
  expect(result.violations.map((v) => v.id)).toEqual([]);
}

const next = () => screen.getByRole('button', { name: 'Next' });
const prev = () => screen.getByRole('button', { name: 'Previous' });

describe('Pagination with an unknown total', () => {
  it('reads Page N with the rows on this page', () => {
    render(<Pagination page={3} pageSize={25} itemCount={25} />);
    expect(screen.getByText('Page 3, 25 on this page')).toBeTruthy();
  });
  it('reads Page N alone without an itemCount, and treats null as unknown', () => {
    render(<Pagination page={2} pageSize={25} total={null} />);
    expect(screen.getByText('Page 2')).toBeTruthy();
  });
  it('says so when the first page is empty', () => {
    render(<Pagination page={1} pageSize={25} itemCount={0} unit="runs" />);
    expect(screen.getByText('No runs')).toBeTruthy();
    expect(next().hasAttribute('disabled')).toBe(true);
  });
  it('enables Next on a full page and disables it on a short one', () => {
    const { rerender } = render(<Pagination page={1} pageSize={25} itemCount={25} />);
    expect(next().hasAttribute('disabled')).toBe(false);
    rerender(<Pagination page={1} pageSize={25} itemCount={9} />);
    expect(next().hasAttribute('disabled')).toBe(true);
  });
  it('leaves Next on when nothing says otherwise', () => {
    render(<Pagination page={1} pageSize={25} />);
    expect(next().hasAttribute('disabled')).toBe(false);
  });
  it('lets hasMore decide Next over the page fill', () => {
    const { rerender } = render(<Pagination page={1} pageSize={25} itemCount={25} hasMore={false} />);
    expect(next().hasAttribute('disabled')).toBe(true);
    rerender(<Pagination page={1} pageSize={25} itemCount={3} hasMore />);
    expect(next().hasAttribute('disabled')).toBe(false);
  });
  it('lets hasMore decide Next with a known total too', () => {
    render(<Pagination page={1} pageSize={25} total={500} hasMore={false} />);
    expect(screen.getByText('1 to 25 of 500 entries')).toBeTruthy();
    expect(next().hasAttribute('disabled')).toBe(true);
  });
  it('disables Previous on page 1 and everything while loading', () => {
    const { rerender } = render(<Pagination page={1} pageSize={25} itemCount={25} />);
    expect(prev().hasAttribute('disabled')).toBe(true);
    rerender(<Pagination page={2} pageSize={25} itemCount={25} loading />);
    expect(prev().hasAttribute('disabled')).toBe(true);
    expect(next().hasAttribute('disabled')).toBe(true);
  });
  it('has no axe violations', async () => {
    const { container } = render(<Pagination page={2} pageSize={25} itemCount={25} onPage={() => undefined} onPageSizeChange={() => undefined} />);
    await noAxe(container);
  });
});

describe('Pagination onPage', () => {
  it('gets the target page from Previous and Next', () => {
    const onPage = vi.fn();
    render(<Pagination page={4} pageSize={25} itemCount={25} onPage={onPage} />);
    fireEvent.click(prev());
    fireEvent.click(next());
    expect(onPage.mock.calls).toEqual([[3], [5]]);
  });
  it('works with a known total', () => {
    const onPage = vi.fn();
    render(<Pagination page={2} pageSize={25} total={80} onPage={onPage} />);
    fireEvent.click(next());
    expect(onPage).toHaveBeenCalledWith(3);
  });
  it('yields to onPrev and onNext when they are given', () => {
    const onPage = vi.fn();
    const onNext = vi.fn();
    render(<Pagination page={2} pageSize={25} total={80} onPage={onPage} onNext={onNext} />);
    fireEvent.click(next());
    fireEvent.click(prev());
    expect(onNext).toHaveBeenCalledOnce();
    expect(onPage.mock.calls).toEqual([[1]]);
  });
});

describe('known total is unchanged', () => {
  it('keeps the count line and the last page end', () => {
    render(<Pagination page={4} pageSize={25} total={80} unit="rows" />);
    expect(screen.getByText('76 to 80 of 80 rows')).toBeTruthy();
    expect(next().hasAttribute('disabled')).toBe(true);
  });
});

describe('usePagination with an unknown total', () => {
  it('does not clamp to a last page and leaves total out of its props', () => {
    const { result } = renderHook(() => usePagination(null, 25));
    expect(result.current.props.total).toBeUndefined();
    act(() => result.current.props.onNext?.());
    act(() => result.current.props.onNext?.());
    expect(result.current.page).toBe(3);
    act(() => result.current.setPage(1));
    expect(result.current.page).toBe(1);
  });
  it('feeds Pagination', () => {
    const Probe = () => {
      const pager = usePagination(undefined, 10);
      return <Pagination {...pager.props} itemCount={10} />;
    };
    render(<Probe />);
    fireEvent.click(next());
    expect(screen.getByText('Page 2, 10 on this page')).toBeTruthy();
  });
});
