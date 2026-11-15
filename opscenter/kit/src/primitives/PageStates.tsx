/* The whole-screen states the UI standard requires next to the crash screen: 403 Forbidden and 404
   NotFound. They share EmptyState's anatomy (icon tile, title, one line of copy, one action) but
   render as a centred page panel with a real h1, because they are the page. Router agnostic: pass
   `action` (for example a router Link), otherwise a plain anchor to `homeHref` renders. */

import type { HTMLAttributes, ReactNode } from 'react';
import { IconSearch, IconShield } from '../icons/icons';
import { cx } from '../lib/env';

interface PageStateBase extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  title?: ReactNode;
  message?: ReactNode;
  /** Replaces the default home link, for example a router Link. */
  action?: ReactNode;
  homeHref?: string | undefined;
  homeLabel?: ReactNode;
}

function PageState({
  kind,
  icon,
  title,
  message,
  detail,
  action,
  homeHref,
  homeLabel,
  className,
  ...rest
}: PageStateBase & { kind: 'forbidden' | 'not-found'; icon: ReactNode; detail?: ReactNode }) {
  return (
    <section {...rest} className={cx('page-state', className)} data-kind={kind}>
      <div className="page-state-panel empty-state">
        <div className="empty-icon page-state-icon" aria-hidden="true">
          {icon}
        </div>
        <h1 className="empty-title page-state-title">{title}</h1>
        {message ? <p className="empty-body">{message}</p> : null}
        {detail ? <code className="page-state-detail">{detail}</code> : null}
        <div className="empty-action">
          {action ?? (
            <a className="btn" data-variant="primary" data-size="md" href={homeHref}>
              {homeLabel}
            </a>
          )}
        </div>
      </div>
    </section>
  );
}

export interface ForbiddenProps extends PageStateBase {
  /** The permission the page requires, shown in mono. */
  permission?: string | undefined;
}

/** 403: signed in but without the permission. Never a login redirect. */
export function Forbidden({
  title = 'You do not have access to this page',
  message = 'Ask an administrator for access, or head back to a page you can use.',
  permission,
  homeHref = '/',
  homeLabel = 'Go to an accessible page',
  ...rest
}: ForbiddenProps) {
  return (
    <PageState
      {...rest}
      kind="forbidden"
      icon={<IconShield size={22} />}
      title={title}
      message={message}
      detail={permission}
      homeHref={homeHref}
      homeLabel={homeLabel}
    />
  );
}

export interface NotFoundProps extends PageStateBase {
  /** The attempted path, shown in mono. */
  path?: string | undefined;
}

/** 404: an unknown route. */
export function NotFound({
  title = 'Page not found',
  message = 'The page you asked for does not exist or has moved.',
  path,
  homeHref = '/',
  homeLabel = 'Go home',
  ...rest
}: NotFoundProps) {
  return (
    <PageState
      {...rest}
      kind="not-found"
      icon={<IconSearch size={22} />}
      title={title}
      message={message}
      detail={path}
      homeHref={homeHref}
      homeLabel={homeLabel}
    />
  );
}
