/* Modal: every dialog in an app uses it (UI standard rule 7, section 7). Portal, focus moved in and
   trapped, focus restored on close, Escape closes the top dialog only, scroll lock, z tokens.
   Below 640px it becomes a bottom sheet. onClose says why it closed, and when the focused node
   inside the panel unmounts, focus returns to the panel instead of falling to the body. */

import { useEffect, useId, useRef, useState } from 'react';
import type { FormEvent, HTMLAttributes, KeyboardEvent, ReactNode, RefObject } from 'react';
import { createPortal } from 'react-dom';
import { IconClose } from '../icons/icons';
import { cx, isBrowser, isMacLike, prefersReducedMotion } from '../lib/env';
import type { MarkHue } from '../lib/hues';
import { useModalLayer } from '../lib/layers';
import { tokenDuration } from '../lib/timing';
import { Button } from '../primitives/Button';
import { Kbd } from '../primitives/marks';

export interface ModalAction {
  label: string;
  onClick?: (() => void) | undefined;
  /** Destructive: the danger button. */
  danger?: boolean | undefined;
  /** Leading icon on the button. */
  icon?: ReactNode;
  loading?: boolean | undefined;
  disabled?: boolean | undefined;
}

/** Why a modal asked to close: Escape, a backdrop press, or the close button and Cancel. */
export type ModalCloseReason = 'escape' | 'backdrop' | 'close';

/** Panel widths. `wide` is for tables and side by side forms, `full` fills the viewport less the
    gutter (a full-screen editor or preview). */
export type ModalSize = 'sm' | 'md' | 'lg' | 'xl' | 'wide' | 'full';

/** Attributes passed through to the dialog panel (data-*, id, aria-*, style hooks for tests). The
    props the modal owns are left out. */
type PanelAttributes = Omit<HTMLAttributes<HTMLDivElement>, 'title' | 'role' | 'onSubmit' | 'children' | 'className' | 'tabIndex'>;

export interface ModalProps extends PanelAttributes {
  open: boolean;
  /** Escape, the backdrop, the close button and Cancel call this (unless busy) with the reason.
      Handlers that take no argument keep working. */
  onClose: (reason: ModalCloseReason) => void;
  /** Always required: it names the dialog even when `hideHead` hides it. */
  title: ReactNode;
  /** Hides the head row (icon, title, subtitle, close button) for a dialog whose body brings its
      own heading or is a picture. The dialog keeps its accessible name: a string title becomes
      aria-label, any other title stays as a visually hidden heading. A close button floats in the
      corner unless `hideClose`. */
  hideHead?: boolean | undefined;
  subtitle?: ReactNode;
  /** Badges or a status beside the title, outside the accessible name (the dialog is named by
      the title alone, so a badge here is not read as part of it). */
  meta?: ReactNode;
  /** 40px icon tile in the head. */
  icon?: ReactNode;
  /** Hue of the icon tile. Never the accent. */
  hue?: MarkHue | undefined;
  children?: ReactNode;
  /** Replaces the default footer entirely. */
  footer?: ReactNode;
  /** Left side of the default footer. Keyboard hints show there when omitted. */
  footerStart?: ReactNode;
  /** The primary button of the default footer. With onSubmit it submits the form. */
  primaryAction?: ModalAction | undefined;
  /** Cancel label. Null hides the Cancel button. */
  cancelLabel?: string | null | undefined;
  size?: ModalSize | undefined;
  /** `sheet` docks a full-height panel on the right for long forms. */
  variant?: 'dialog' | 'sheet' | undefined;
  /** Blocks closing while saving. */
  busy?: boolean | undefined;
  /** Makes the body a form: Enter and Cmd or Ctrl and Enter submit. */
  onSubmit?: ((event: FormEvent<HTMLFormElement>) => void) | undefined;
  /** alertdialog for confirmations. */
  role?: 'dialog' | 'alertdialog' | undefined;
  /** Element to focus on open. Default: [data-autofocus], then the first field. */
  initialFocusRef?: RefObject<HTMLElement | null> | undefined;
  hideClose?: boolean | undefined;
  closeLabel?: string | undefined;
  className?: string | undefined;
}

/** Keeps a dialog mounted for its exit animation, then unmounts it. */
function usePresence(open: boolean): { mounted: boolean; closing: boolean } {
  const [mounted, setMounted] = useState(open);
  const [closing, setClosing] = useState(false);
  useEffect(() => {
    if (open) {
      setMounted(true);
      setClosing(false);
      return undefined;
    }
    if (!mounted) return undefined;
    const exit = prefersReducedMotion() ? 0 : tokenDuration('--dur-base');
    if (exit <= 0) {
      setMounted(false);
      setClosing(false);
      return undefined;
    }
    setClosing(true);
    const t = window.setTimeout(() => {
      setMounted(false);
      setClosing(false);
    }, exit);
    return () => window.clearTimeout(t);
  }, [open, mounted]);
  return { mounted: mounted || open, closing: !open && closing };
}

/** Watches the panel while open: when the element that had focus inside it leaves the DOM (a step
    swaps, a row is removed), focus moves to the panel so keyboard users stay in the dialog. */
function useFocusRescue(active: boolean, panelRef: RefObject<HTMLDivElement | null>): void {
  useEffect(() => {
    const panel = panelRef.current;
    if (!active || !panel || typeof MutationObserver !== 'function') return undefined;
    let last: Element | null = panel.contains(document.activeElement) ? document.activeElement : null;
    const onFocusIn = (event: FocusEvent) => {
      last = event.target instanceof Element ? event.target : null;
    };
    const rescue = () => {
      if (!last || last.isConnected) return;
      const now = document.activeElement;
      if (now === null || now === document.body || now === document.documentElement) {
        last = panel;
        panel.focus({ preventScroll: true });
      }
    };
    panel.addEventListener('focusin', onFocusIn);
    const mo = new MutationObserver(rescue);
    mo.observe(panel, { childList: true, subtree: true });
    return () => {
      panel.removeEventListener('focusin', onFocusIn);
      mo.disconnect();
    };
  }, [active, panelRef]);
}

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  meta,
  icon,
  hue = 'blue',
  children,
  footer,
  footerStart,
  primaryAction,
  cancelLabel = 'Cancel',
  size = 'md',
  variant = 'dialog',
  busy = false,
  onSubmit,
  role = 'dialog',
  initialFocusRef,
  hideClose = false,
  closeLabel = 'Close',
  className,
  hideHead = false,
  onKeyDown: onPanelKeyDown,
  ...panelProps
}: ModalProps) {
  const { mounted, closing } = usePresence(open);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const formRef = useRef<HTMLFormElement | null>(null);
  const titleId = `${useId()}-title`;
  const subId = `${titleId}-sub`;
  const requestClose = (reason: ModalCloseReason) => {
    if (!busy) onClose(reason);
  };
  useModalLayer(open, panelRef, {
    onEscape: () => requestClose('escape'),
    initialFocus: initialFocusRef ? () => initialFocusRef.current : undefined,
  });
  useFocusRescue(open && mounted, panelRef);

  if (!mounted || !isBrowser) return null;

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // Only the caller's own handler opts out: a child that already prevented the event (an
    // editor, a combobox) never switches off the modal's keys.
    const before = event.defaultPrevented;
    onPanelKeyDown?.(event);
    if (!before && event.defaultPrevented) return;
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && formRef.current) {
      event.preventDefault();
      formRef.current.requestSubmit();
    }
  };

  const hints = (
    <span className="modal-hints">
      <Kbd>Esc</Kbd> to close
      {onSubmit ? (
        <>
          {' | '}
          <Kbd>{isMacLike() ? 'Cmd' : 'Ctrl'}</Kbd>+<Kbd>Enter</Kbd> to save
        </>
      ) : null}
    </span>
  );

  const defaultFooter =
    primaryAction || cancelLabel !== null ? (
      <div className="modal-foot">
        <div className="modal-foot-start">{footerStart ?? hints}</div>
        {cancelLabel !== null ? (
          <Button variant="secondary" onClick={() => requestClose('close')} disabled={busy}>
            {cancelLabel}
          </Button>
        ) : null}
        {primaryAction ? (
          <Button
            variant={primaryAction.danger ? 'danger' : 'primary'}
            type={onSubmit ? 'submit' : 'button'}
            onClick={onSubmit ? undefined : primaryAction.onClick}
            loading={primaryAction.loading || busy}
            disabled={primaryAction.disabled}
            icon={primaryAction.icon}
          >
            {primaryAction.label}
          </Button>
        ) : null}
      </div>
    ) : null;

  const closeButton = hideClose ? null : (
    <button
      type="button"
      className={cx('btn modal-close', hideHead && 'modal-close-float')}
      data-variant="ghost"
      data-icon-only=""
      aria-label={closeLabel}
      onClick={() => requestClose('close')}
      disabled={busy}
    >
      <IconClose />
    </button>
  );
  const namedByLabel = hideHead && typeof title === 'string';
  // Caller ARIA wins over the generated name: an explicit aria-labelledby, then aria-label.
  const callerLabelledBy = panelProps['aria-labelledby'];
  const callerLabel = panelProps['aria-label'];
  const describedBy = [subtitle ? subId : null, panelProps['aria-describedby']].filter(Boolean).join(' ') || undefined;

  const head = hideHead ? (
    <>
      {namedByLabel ? null : (
        <h2 id={titleId} className="kit-sr-only">
          {title}
        </h2>
      )}
      {subtitle ? (
        <p id={subId} className="kit-sr-only">
          {subtitle}
        </p>
      ) : null}
      {closeButton}
    </>
  ) : (
      <div className="modal-head">
        {icon ? (
          <span className={cx('modal-icon', 'hue-tile', `hue-${hue}`)} aria-hidden="true">
            {icon}
          </span>
        ) : null}
        <div className="modal-titles">
          <div className="modal-title-row">
            <h2 id={titleId} className="modal-title">
              {title}
            </h2>
            {meta ? <span className="modal-meta">{meta}</span> : null}
          </div>
          {subtitle ? (
            <p id={subId} className="modal-sub">
              {subtitle}
            </p>
          ) : null}
        </div>
        {closeButton}
      </div>
  );

  const content = (
    <>
      {head}
      <div className="modal-body">{children}</div>
      {footer !== undefined ? footer : defaultFooter}
    </>
  );

  return createPortal(
    <div
      className="modal-backdrop"
      data-variant={variant}
      data-state={closing ? 'closing' : 'open'}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) requestClose('backdrop');
      }}
    >
      <div
        {...panelProps}
        ref={panelRef}
        className={cx('modal', className)}
        role={role}
        aria-modal="true"
        aria-label={callerLabelledBy ? undefined : callerLabel ?? (namedByLabel ? (title as string) : undefined)}
        aria-labelledby={callerLabelledBy ?? (callerLabel || namedByLabel ? undefined : titleId)}
        aria-describedby={describedBy}
        aria-busy={busy || undefined}
        data-size={size}
        data-variant={variant}
        data-state={closing ? 'closing' : 'open'}
        data-head={hideHead ? 'hidden' : undefined}
        tabIndex={-1}
        onKeyDown={onKeyDown}
      >
        {onSubmit ? (
          <form
            ref={formRef}
            className="modal-form"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              if (!busy) onSubmit(event);
            }}
          >
            {content}
          </form>
        ) : (
          content
        )}
      </div>
    </div>,
    document.body,
  );
}

export interface ModalSectionProps {
  title?: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
}

/** A titled section inside a modal body, separated by a hairline. */
export function ModalSection({ title, description, children }: ModalSectionProps) {
  return (
    <section className="modal-section">
      {title ? <h3 className="modal-section-title">{title}</h3> : null}
      {description ? <p className="modal-section-desc">{description}</p> : null}
      {children}
    </section>
  );
}
