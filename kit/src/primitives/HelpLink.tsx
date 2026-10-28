/* HelpLink: a documentation link for help text. InfoTip uses it. */

import type { ReactNode } from 'react';
import { IconExternal } from '../icons/icons';
import { cx } from '../lib/env';
import { safeHref } from '../lib/url';

export interface HelpLinkProps {
  href: string;
  className?: string | undefined;
  children: ReactNode;
}

/**
 * A link to the full documentation. An address on another site opens in a new tab, shows an external
 * mark and says so to a screen reader. A path inside the app is a plain same-tab link and does a normal
 * page load. An unsafe scheme (see safeHref) renders without an href, like every kit link.
 */
export function HelpLink({ href, className, children }: HelpLinkProps) {
  const external = /^https?:\/\//i.test(href.trim());
  return (
    <a className={cx('help-link', className)} href={safeHref(href)} {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}>
      {children}
      {external ? (
        <>
          {/* A plain space keeps the name "<text> (opens in a new tab)" in every browser. */}
          {' '}
          <IconExternal size={11} />
          <span className="kit-sr-only">(opens in a new tab)</span>
        </>
      ) : null}
    </a>
  );
}
