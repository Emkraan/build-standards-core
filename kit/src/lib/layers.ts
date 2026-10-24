/* Overlay plumbing shared by Modal, the palette, popovers and the what's new dialog: a layer stack
   (only the top layer answers keys), a scroll lock, focus helpers and the focus trap. */

import { useEffect, useId, useLayoutEffect, useRef } from 'react';
import type { RefObject } from 'react';
import { isBrowser } from './env';

export const useIsoLayoutEffect = isBrowser ? useLayoutEffect : useEffect;

const stack: string[] = [];
let modalCount = 0;

export function pushLayer(id: string, modal: boolean): void {
  stack.push(id);
  if (modal) modalCount += 1;
}

export function removeLayer(id: string, modal: boolean): void {
  const i = stack.lastIndexOf(id);
  if (i >= 0) stack.splice(i, 1);
  if (modal && modalCount > 0) modalCount -= 1;
}

/**
 * The body-level element that anchored overlays (popovers, menus) portal into. A portal inside
 * <main> would inherit any transform or filter an app animates on it, which turns position:
 * fixed into position relative to <main> and misplaces the panel. It is a labelled region, so a
 * menu stays inside a landmark, and it is hidden while no overlay holds it (useLayerRoot), so an
 * empty landmark never shows up. Created on first use.
 */
export function layerRoot(): HTMLElement {
  const found = document.body.querySelector<HTMLElement>(':scope > [data-kit-layer-root]');
  if (found) return found;
  const el = document.createElement('div');
  el.setAttribute('data-kit-layer-root', '');
  el.setAttribute('role', 'region');
  el.setAttribute('aria-label', 'Menus and popovers');
  el.hidden = true;
  document.body.appendChild(el);
  return el;
}

let layerHolds = 0;

/** Shows the layer root while `active` (an open overlay portaled into it). */
export function useLayerRoot(active: boolean): void {
  useIsoLayoutEffect(() => {
    if (!active || !isBrowser) return undefined;
    layerHolds += 1;
    layerRoot().hidden = false;
    return () => {
      layerHolds = Math.max(0, layerHolds - 1);
      if (layerHolds === 0) layerRoot().hidden = true;
    };
  }, [active]);
}

export function isTopLayer(id: string): boolean {
  return stack[stack.length - 1] === id;
}

/** True while any modal dialog is open. Global shortcuts pause while it is. */
export function isDialogOpen(): boolean {
  return modalCount > 0;
}

let locks = 0;
let savedOverflow = '';

export function lockScroll(): void {
  if (!isBrowser) return;
  if (locks === 0) {
    savedOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
  }
  locks += 1;
}

export function unlockScroll(): void {
  if (!isBrowser || locks === 0) return;
  locks -= 1;
  if (locks === 0) document.body.style.overflow = savedOverflow;
}

const FOCUSABLE = [
  'a[href]', 'area[href]', 'button:not([disabled])', 'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])', 'textarea:not([disabled])', 'iframe', 'summary',
  '[contenteditable="true"]', '[tabindex]:not([tabindex="-1"])',
].join(',');

/** Keyboard-reachable elements inside a root, in document order. */
export function focusables(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => el.tabIndex >= 0 && !el.closest('[hidden], [inert], [aria-hidden="true"]'),
  );
}

/** Keeps Tab and Shift+Tab inside the panel. */
export function trapTab(event: KeyboardEvent, panel: HTMLElement): void {
  const items = focusables(panel);
  const active = document.activeElement;
  if (items.length === 0) {
    event.preventDefault();
    panel.focus();
    return;
  }
  const first = items[0] as HTMLElement;
  const last = items[items.length - 1] as HTMLElement;
  const inside = active instanceof Node && panel.contains(active);
  if (event.shiftKey && (active === first || active === panel || !inside)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (active === last || !inside)) {
    event.preventDefault();
    first.focus();
  }
}

export interface ModalLayerOptions {
  /** Escape on the top layer calls this. */
  onEscape?: (() => void) | undefined;
  /** Element to focus on open. Default: [data-autofocus], the first field, the first control, the panel. */
  initialFocus?: (() => HTMLElement | null | undefined) | undefined;
  /** Trap Tab inside the panel and lock page scroll (true for dialogs, false for menus). */
  modal?: boolean | undefined;
  /** Return focus to the element that had it before opening (default true). */
  restoreFocus?: boolean | undefined;
}

/**
 * Turns a panel into a layer while `open`: registers it on the stack, moves focus in, traps Tab,
 * answers Escape only when it is the top layer, locks scroll for modal layers, and restores focus
 * on close.
 */
export function useModalLayer(
  open: boolean,
  panelRef: RefObject<HTMLElement | null>,
  options: ModalLayerOptions = {},
): void {
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const id = useId();

  useIsoLayoutEffect(() => {
    if (!open || !isBrowser) return undefined;
    const modal = optionsRef.current.modal !== false;
    const restore = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    pushLayer(id, modal);
    if (modal) lockScroll();

    const panel = panelRef.current;
    if (panel) {
      const target =
        optionsRef.current.initialFocus?.() ??
        panel.querySelector<HTMLElement>('[data-autofocus]') ??
        panel.querySelector<HTMLElement>('input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled])') ??
        focusables(panel)[0] ??
        panel;
      target.focus({ preventScroll: true });
    }

    const onKey = (event: KeyboardEvent) => {
      if (!isTopLayer(id)) return;
      if (event.key === 'Escape') {
        const handler = optionsRef.current.onEscape;
        if (handler) {
          event.preventDefault();
          event.stopPropagation();
          handler();
        }
        return;
      }
      if (event.key === 'Tab' && modal && panelRef.current) trapTab(event, panelRef.current);
    };
    document.addEventListener('keydown', onKey, true);

    return () => {
      document.removeEventListener('keydown', onKey, true);
      removeLayer(id, modal);
      if (modal) unlockScroll();
      if (optionsRef.current.restoreFocus === false || !restore) return;
      // React puts focus back where it was after the commit that closes the layer, so the restore
      // waits for a microtask. It only moves focus that is still inside the closing panel or lost.
      queueMicrotask(() => {
        const active = document.activeElement;
        const lost = !active || active === document.body || Boolean(panel && panel.contains(active));
        if (lost && document.contains(restore)) restore.focus({ preventScroll: true });
      });
    };
  }, [open]);
}
