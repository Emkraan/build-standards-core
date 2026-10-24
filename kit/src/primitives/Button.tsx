/* Buttons (UI standard sections 7 and 24). Primary is the accent gradient with a spring press, and
   an icon-only button needs a label by shape (IconButton). Success, warning and danger come solid
   (a deep fill with white text) and subtle (the status tint, hairline and ink), so an app never
   paints a button with a hue class. */

import { forwardRef } from 'react';
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from 'react';
import { cx } from '../lib/env';
import { safeHref } from '../lib/url';

export type ButtonVariant =
  | 'primary'
  | 'secondary'
  | 'ghost'
  | 'danger'
  | 'danger-subtle'
  | 'success'
  | 'success-subtle'
  | 'warning'
  | 'warning-subtle';
export type ButtonSize = 'sm' | 'md';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant | undefined;
  size?: ButtonSize | undefined;
  /** Leading icon. */
  icon?: ReactNode;
  /** Trailing icon. */
  iconEnd?: ReactNode;
  /** Shows a spinner, disables the button and sets aria-busy. */
  loading?: boolean | undefined;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', icon, iconEnd, loading = false, className, children, disabled, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      className={cx('btn', className)}
      data-variant={variant}
      data-size={size}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
    >
      {loading ? <span className="btn-spinner" aria-hidden="true" /> : icon ? <span className="btn-icon" aria-hidden="true">{icon}</span> : null}
      {children}
      {iconEnd ? (
        <span className="btn-icon" aria-hidden="true">
          {iconEnd}
        </span>
      ) : null}
    </button>
  );
});

export interface ButtonLinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> {
  /** Destination. Goes through `safeHref`: an unsafe scheme (javascript:, data:) renders no href. */
  href: string | null | undefined;
  variant?: ButtonVariant | undefined;
  size?: ButtonSize | undefined;
  icon?: ReactNode;
  iconEnd?: ReactNode;
}

/** The link form of Button: an anchor that looks like a button, for navigation rather than action. */
export const ButtonLink = forwardRef<HTMLAnchorElement, ButtonLinkProps>(function ButtonLink(
  { href, variant = 'secondary', size = 'md', icon, iconEnd, className, children, ...rest },
  ref,
) {
  const safe = safeHref(href);
  return (
    <a {...rest} ref={ref} href={safe} className={cx('btn', className)} data-variant={variant} data-size={size}>
      {icon ? <span className="btn-icon" aria-hidden="true">{icon}</span> : null}
      {children}
      {iconEnd ? <span className="btn-icon" aria-hidden="true">{iconEnd}</span> : null}
    </a>
  );
});

export interface IconButtonProps extends Omit<ButtonProps, 'children' | 'icon' | 'iconEnd' | 'aria-label'> {
  /** Required accessible name, also shown as the tooltip. */
  label: string;
  icon: ReactNode;
  /** Shortcut chip in the tooltip, for example `[`. */
  kbd?: string | undefined;
  tipSide?: 'top' | 'bottom' | 'right' | undefined;
}

/** An icon-only button. The label is required, so it always has a name and a tooltip. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, icon, kbd, tipSide, variant = 'ghost', ...rest },
  ref,
) {
  return (
    <Button
      {...rest}
      ref={ref}
      variant={variant}
      aria-label={label}
      data-tip={label}
      data-tip-kbd={kbd}
      data-tip-side={tipSide}
      data-icon-only=""
      icon={icon}
    />
  );
});
