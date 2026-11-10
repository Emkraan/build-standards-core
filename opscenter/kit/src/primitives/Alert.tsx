/* Inline alert: a status message that lives in the page flow (a banner inside a form, a card or a
   dialog). Toasts are for transient results, AnnouncementBanner is for the whole app, Alert is for
   a message that belongs to the content around it. Tone, never an edge bar (UI standard 0.1). */

import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from '../lib/env';
import { IconAlert, IconCheckCircle, IconInfo, IconWarning } from '../icons/icons';

export type AlertTone = 'info' | 'success' | 'warning' | 'danger';

export interface AlertProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  tone?: AlertTone | undefined;
  title?: ReactNode;
  /** A button or link placed on the right. */
  action?: ReactNode;
}

const ICON = { info: IconInfo, success: IconCheckCircle, warning: IconWarning, danger: IconAlert } as const;

export function Alert({ tone = 'info', title, action, className, children, ...rest }: AlertProps) {
  const Icon = ICON[tone];
  // Warnings and errors interrupt assistive technology, the rest are polite.
  const role = tone === 'danger' || tone === 'warning' ? 'alert' : 'status';
  return (
    <div role={role} {...rest} data-tone={tone} className={cx('alert', className)}>
      <span className="alert-icon" aria-hidden="true">
        <Icon size={16} />
      </span>
      <div className="alert-text">
        {title ? <p className="alert-title">{title}</p> : null}
        {children ? <div className="alert-body">{children}</div> : null}
      </div>
      {action ? <div className="alert-action">{action}</div> : null}
    </div>
  );
}
