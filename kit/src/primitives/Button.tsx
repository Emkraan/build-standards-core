/* Buttons (UI standard sections 7 and 24). Primary is the accent gradient with a spring press, and
   an icon-only button needs a label by shape (IconButton). Success, warning and danger come solid
   (a deep fill with white text) and subtle (the status tint, hairline and ink), so an app never
   paints a button with a hue class. A button that cannot be used right now says why through
   disabledReason: it stays focusable and the reason is its tip. */

import { forwardRef } from 'react';
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, MouseEvent, ReactNode } from 'react';
import { cx } from '../lib/env';
import { safeHref } from '../lib/url';
import { joinIds, useTip } from './Tooltip';

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
  /**
   * Why the button cannot be used now and how to enable it, one or two short sentences. While set the
   * button is aria-disabled instead of disabled: it stays in the tab order so a keyboard user reaches
   * the reason, which shows as its tip and is read as its description. A click does nothing, it does not
   * submit a form and it does not reach a parent. Use it instead of `disabled`. `loading` wins while both are set.
   */
  disabledReason?: string | undefined;
}

function ignoreClick(event: MouseEvent<HTMLButtonElement>): void {
  event.preventDefault();
  event.stopPropagation();
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'secondary',
    size = 'md',
    icon,
    iconEnd,
    loading = false,
    className,
    children,
    disabled,
    disabledReason,
    onClick,
    type = 'button',
    ...rest
  },
  ref,
) {
  const reasoned = Boolean(disabledReason?.trim()) && !loading;
  // An icon-only button keeps its label in the tip, so the reason follows it: "Remove host: Drain sessions first".
  const attrs = rest as Record<string, unknown>;
  const label = typeof attrs['aria-label'] === 'string' ? attrs['aria-label'] : '';
  const reasonTip = 'data-icon-only' in attrs && label ? `${label}: ${disabledReason ?? ''}` : disabledReason;
  const { props: tip, description } = useTip(reasoned ? reasonTip : undefined);
  const describedBy = joinIds(rest['aria-describedby'], tip['aria-describedby']);
  return (
    <button
      {...rest}
      {...(reasoned ? { 'data-tip': tip['data-tip'] } : {})}
      ref={ref}
      type={type}
      className={cx('btn', className)}
      data-variant={variant}
      data-size={size}
      disabled={(disabled && !reasoned) || loading}
      aria-disabled={reasoned ? true : rest['aria-disabled']}
      aria-describedby={describedBy}
      aria-busy={loading || undefined}
      onClick={reasoned ? ignoreClick : onClick}
    >
      {loading ? <span className="btn-spinner" aria-hidden="true" /> : icon ? <span className="btn-icon" aria-hidden="true">{icon}</span> : null}
      {children}
      {iconEnd ? (
        <span className="btn-icon" aria-hidden="true">
          {iconEnd}
        </span>
      ) : null}
      {reasoned ? description : null}
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
