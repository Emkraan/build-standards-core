/* Breadcrumb and Pagination. The last crumb is the current page: it carries aria-current and is
   never a link. Pagination always states the count, because a list capped at 40 that reports 300
   results and offers no way to reach them is a correctness problem. Figures are tabular. */

import { useCallback, useState } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { IconChevronLeft, IconChevronRight } from '../icons/icons';
import { cx } from '../lib/env';
import { Button } from './Button';
import { Select } from './Field';

export interface BreadcrumbItem {
  label: ReactNode;
  href?: string | undefined;
  onClick?: (() => void) | undefined;
}

export interface BreadcrumbLinkRenderProps {
  item: BreadcrumbItem;
  /** Always "breadcrumb-link": apply it so a routed crumb matches the default. */
  className: string;
  children: ReactNode;
}

export interface BreadcrumbProps extends HTMLAttributes<HTMLElement> {
  items: BreadcrumbItem[];
  label?: string | undefined;
  /** Render an href crumb through the app's router instead of a plain anchor, so a crumb never
      reloads a single page app. Same contract as the shell's renderLink. */
  renderLink?: ((props: BreadcrumbLinkRenderProps) => ReactNode) | undefined;
}

export function Breadcrumb({ items, label = 'Breadcrumb', renderLink, className, ...rest }: BreadcrumbProps) {
  return (
    <nav {...rest} className={cx('breadcrumb', className)} aria-label={label}>
      <ol className="breadcrumb-list">
        {items.map((item, i) => {
          const last = i === items.length - 1;
          let crumb: ReactNode;
          if (last || (!item.href && !item.onClick)) {
            crumb = (
              <span className="breadcrumb-link" aria-current={last ? 'page' : undefined}>
                {item.label}
              </span>
            );
          } else if (item.href) {
            crumb = renderLink ? (
              renderLink({ item, className: 'breadcrumb-link', children: item.label })
            ) : (
              <a className="breadcrumb-link" href={item.href}>
                {item.label}
              </a>
            );
          } else {
            crumb = (
              <button type="button" className="breadcrumb-link" onClick={item.onClick}>
                {item.label}
              </button>
            );
          }
          return (
            <li key={item.href ?? String(i)}>
              {i > 0 ? (
                <span className="breadcrumb-sep" aria-hidden="true">
                  /
                </span>
              ) : null}
              {crumb}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export interface PaginationProps extends HTMLAttributes<HTMLDivElement> {
  /** One based. */
  page?: number | undefined;
  pageSize: number;
  /** The row count behind the list. Leave it out (or null) when the server cannot say: the footer then
      reads "Page N" with the rows on the page, and Next follows hasMore or a full page. */
  total?: number | null | undefined;
  /** Rows on the current page. With an unknown total it is the "N on this page" figure, and a page
      that holds fewer rows than pageSize is taken as the last one. */
  itemCount?: number | undefined;
  /** Whether a page after this one exists. When given it decides Next, with or without a total. */
  hasMore?: boolean | undefined;
  onPrev?: (() => void) | undefined;
  onNext?: (() => void) | undefined;
  /** Gets the target page number (one based) for Previous and Next. Used for a button whose
      onPrev or onNext is not given. */
  onPage?: ((page: number) => void) | undefined;
  /** The plural noun in the count line, for example "runs". */
  unit?: string | undefined;
  /** Page sizes to offer. With onPageSizeChange it adds a "Rows per page" select. */
  pageSizeOptions?: readonly number[] | undefined;
  onPageSizeChange?: ((size: number) => void) | undefined;
  /** A page is loading: the buttons and the size select are disabled. */
  loading?: boolean | undefined;
}

export function Pagination({
  page = 1,
  pageSize,
  total,
  itemCount,
  hasMore,
  onPrev,
  onNext,
  onPage,
  unit = 'entries',
  pageSizeOptions = [25, 50, 100, 200],
  onPageSizeChange,
  loading = false,
  className,
  ...rest
}: PaginationProps) {
  const known = typeof total === 'number';
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = known ? Math.min(page * pageSize, total) : page * pageSize;
  const onThisPage = itemCount === undefined ? null : Math.max(0, Math.floor(itemCount));
  const nextDisabled =
    hasMore !== undefined ? !hasMore : known ? last >= total : onThisPage !== null && onThisPage < pageSize;
  const countText = known
    ? total === 0
      ? `No ${unit}`
      : `${first} to ${last} of ${total} ${unit}`
    : onThisPage === 0 && page <= 1
      ? `No ${unit}`
      : onThisPage === null
        ? `Page ${page}`
        : `Page ${page}, ${onThisPage} on this page`;
  return (
    <div {...rest} className={cx('pagination', className)}>
      <span className="pagination-count">{countText}</span>
      <div className="pagination-actions">
        {onPageSizeChange ? (
          <Select
            size="sm"
            aria-label="Rows per page"
            className="pagination-size"
            value={String(pageSize)}
            disabled={loading}
            onChange={(e) => onPageSizeChange(Number(e.target.value))}
            options={(pageSizeOptions.includes(pageSize) ? pageSizeOptions : [...pageSizeOptions, pageSize].sort((a, b) => a - b)).map((n) => ({ value: String(n), label: `${n} per page` }))}
          />
        ) : null}
        <Button variant="ghost" size="sm" onClick={onPrev ?? (onPage ? () => onPage(page - 1) : undefined)} disabled={loading || page <= 1} icon={<IconChevronLeft size={12} />}>
          Previous
        </Button>
        <Button variant="ghost" size="sm" onClick={onNext ?? (onPage ? () => onPage(page + 1) : undefined)} disabled={loading || nextDisabled} iconEnd={<IconChevronRight size={12} />}>
          Next
        </Button>
      </div>
    </div>
  );
}

export interface PaginationState {
  /** One based, always inside 1 to pageCount. */
  page: number;
  pageSize: number;
  pageCount: number;
  /** Props to spread on Pagination: page, pageSize, total and the handlers. */
  props: Pick<PaginationProps, 'page' | 'pageSize' | 'total' | 'onPrev' | 'onNext' | 'onPageSizeChange'>;
  setPage: (page: number) => void;
  setPageSize: (size: number) => void;
  /** The rows of the current page. */
  slice: <T>(rows: readonly T[]) => T[];
}

/** Page and page size state for a client-paged list. Pass null for a total the server cannot give
    and spread props with hasMore and itemCount from the response. A page size change keeps the first row on
    screen where it can, and a total that shrinks (a filter) pulls the page back inside range. */
export function usePagination(total: number | null | undefined, initialPageSize = 25): PaginationState {
  const [pageSize, setSize] = useState(Math.max(1, Math.floor(initialPageSize)));
  const [rawPage, setRawPage] = useState(1);
  const known = typeof total === 'number';
  // An unknown total (a server paged list) has no last page to clamp to, so the page is the count.
  const pageCount = known ? Math.max(1, Math.ceil(total / pageSize)) : Math.max(1, rawPage);
  const page = Math.min(Math.max(1, rawPage), pageCount);
  const setPage = useCallback((next: number) => setRawPage(Math.max(1, Math.floor(next))), []);
  const setPageSize = useCallback(
    (size: number) => {
      const next = Math.max(1, Math.floor(size));
      const firstRow = (page - 1) * pageSize;
      setSize(next);
      setRawPage(Math.floor(firstRow / next) + 1);
    },
    [page, pageSize],
  );
  return {
    page,
    pageSize,
    pageCount,
    setPage,
    setPageSize,
    slice: (rows) => rows.slice((page - 1) * pageSize, page * pageSize),
    props: {
      page,
      pageSize,
      total: known ? total : undefined,
      onPrev: () => setPage(page - 1),
      onNext: () => setPage(page + 1),
      onPageSizeChange: setPageSize,
    },
  };
}
