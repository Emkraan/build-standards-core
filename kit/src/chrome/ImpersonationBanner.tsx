/* ImpersonationBanner: the persistent strip shown while an administrator views the app as another
   role or user. It says the current view is not their own authority and offers the one control to
   leave it. Presentational: the app maps its own permission state to these props and renders the
   banner only while impersonation is active. */

import type { ReactNode } from 'react';
import { IconShield } from '../icons/icons';
import { cx } from '../lib/env';

export interface ImpersonationBannerProps {
  /** The role being impersonated, for example "Reader". */
  roleName: string;
  /** Leave impersonation and return to the administrator's own authority. */
  onExit: () => void;
  /** When impersonating a specific person rather than a bare role. */
  asUser?: string | undefined;
  /** The sign-in source the impersonated identity came through. */
  via?: string | undefined;
  /** The exit button text. */
  exitLabel?: string | undefined;
  className?: string | undefined;
  /** Replaces the default "Viewing as" sentence. */
  children?: ReactNode;
}

export function ImpersonationBanner({ roleName, onExit, asUser, via, exitLabel = 'Exit', className, children }: ImpersonationBannerProps) {
  return (
    <div className={cx('impersonation-banner', className)} role="status">
      <span className="impersonation-icon" aria-hidden="true">
        <IconShield size={14} />
      </span>
      <span className="impersonation-body">
        {children ?? (
          <>
            Viewing as <strong>{asUser || roleName}</strong>
            {asUser ? <> ({roleName})</> : null}
            {via ? <span className="impersonation-via"> - {via}</span> : null}
          </>
        )}
      </span>
      <button type="button" className="impersonation-exit" onClick={onExit}>
        {exitLabel}
      </button>
    </div>
  );
}
