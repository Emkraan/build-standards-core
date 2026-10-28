/* TooltipLayer: one layer serves every [data-tip] element on the page (UI standard section 7).
   AppShell mounts it. A second layer anywhere on the page stays idle, so a tip never shows twice.
   useTip: the props that give an element a tip plus the same words as its accessible description. */

import { useEffect, useId, useRef, useState, useSyncExternalStore } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { isBrowser } from '../lib/env';
import { TOOLTIP_DELAY, TOOLTIP_SKIP_DELAY, TOOLTIP_SKIP_WINDOW } from '../lib/timing';

export type TipSide = 'top' | 'bottom' | 'right' | 'left';

/** Attributes that make an element show `text` as its tip and describe itself with the same text. */
export interface TipAttributes {
  'data-tip'?: string | undefined;
  'data-tip-side'?: TipSide | undefined;
  'aria-describedby'?: string | undefined;
}

/**
 * The tooltip layer is hidden from assistive technology because a tip normally repeats an accessible
 * name. A tip that adds meaning (a term's definition, why a button is off, what a status means) needs a
 * second copy that is read: `props` goes on the element and `description` renders inside it. The
 * description is a hidden node, which `aria-describedby` still reads, so it takes no space and does not
 * become part of the element's name. Empty text gives no attributes and no node.
 */
export function useTip(
  text: string | null | undefined,
  side?: TipSide | undefined,
): { props: TipAttributes; description: ReactNode } {
  const id = useId();
  const clean = typeof text === 'string' ? text.trim() : '';
  if (!clean) return { props: {}, description: null };
  return {
    props: { 'data-tip': clean, 'data-tip-side': side, 'aria-describedby': id },
    description: (
      <span id={id} hidden>
        {clean}
      </span>
    ),
  };
}

/** Joins aria-describedby ids, skipping empty ones. Undefined when nothing is left. */
export function joinIds(...ids: Array<string | null | undefined>): string | undefined {
  const out = ids.filter((id): id is string => typeof id === 'string' && id.trim() !== '');
  return out.length ? out.join(' ') : undefined;
}

// One layer serves the page. Every mounted TooltipLayer registers here in mount order and the first
// one is active: it listens and draws, the others render nothing. When the active one unmounts the next
// takes over.
const layerOrder: string[] = [];
const layerListeners = new Set<() => void>();

function notifyLayers(): void {
  for (const listener of [...layerListeners]) listener();
}

function subscribeLayers(listener: () => void): () => void {
  layerListeners.add(listener);
  return () => {
    layerListeners.delete(listener);
  };
}

/** True while a TooltipLayer is mounted on the page. A control that adds a visible cue for a tip checks it,
    so a page without the layer keeps the previous markup. False on the server and on the first client pass. */
export function useTipLayerMounted(): boolean {
  return useSyncExternalStore(
    subscribeLayers,
    () => layerOrder.length > 0,
    () => false,
  );
}

interface TipState {
  text: string;
  kbd: string | null;
  side: TipSide;
  rect: { top: number; left: number; right: number; bottom: number; width: number; height: number };
}

/**
 * A native `title` becomes a [data-tip] the first time the pointer or keyboard reaches it, so the
 * browser's own slow, unstyled tooltip never shows and the page has one tooltip. The text moves to
 * `data-tip`. A control with no other accessible name (an icon button) keeps the text as its
 * `aria-label`, because removing `title` would otherwise remove its only name.
 */
function adoptTitle(el: HTMLElement): void {
  const title = el.getAttribute('title');
  if (title === null || el.hasAttribute('data-tip')) return;
  el.removeAttribute('title');
  if (!title.trim()) return;
  el.setAttribute('data-tip', title);
  el.setAttribute('data-tip-adopted', '');
  const named = el.hasAttribute('aria-label') || el.hasAttribute('aria-labelledby') || (el.textContent ?? '').trim() !== '';
  if (!named) el.setAttribute('aria-label', title);
}

function tipTarget(node: EventTarget | null): HTMLElement | null {
  if (!(node instanceof Element)) return null;
  const el = node.closest<HTMLElement>('[data-tip], .truncate, [title]');
  if (el && el.hasAttribute('title')) adoptTitle(el);
  return el;
}

function tipFor(el: HTMLElement): TipState | null {
  let text = el.getAttribute('data-tip') ?? '';
  if (!text && el.classList.contains('truncate')) {
    if (el.scrollWidth <= el.clientWidth) return null;
    text = el.textContent?.trim() ?? '';
  }
  if (!text) return null;
  const sideAttr = el.getAttribute('data-tip-side');
  const side: TipSide = sideAttr === 'bottom' || sideAttr === 'right' || sideAttr === 'left' ? sideAttr : 'top';
  const r = el.getBoundingClientRect();
  return {
    text,
    kbd: el.getAttribute('data-tip-kbd'),
    side,
    rect: { top: r.top, left: r.left, right: r.right, bottom: r.bottom, width: r.width, height: r.height },
  };
}

function isKeyboardFocus(el: Element): boolean {
  try {
    return el.matches(':focus-visible');
  } catch {
    return true;
  }
}

/**
 * AppShell mounts it, so an app does not. An app that mounts its own keeps working: only the first layer
 * on the page is active, a later one renders nothing. Shows [data-tip] text (with an optional [data-tip-kbd] key chip and
 * [data-tip-side] of top, bottom, right or left), the full text of cut-off .truncate elements and any
 * native `title` (adopted on first hover or focus, see adoptTitle). It
 * appears after a hover delay or at once on keyboard focus, never on touch, and hides on scroll,
 * pointer down and Escape. The tooltip repeats an accessible name, so it is not announced again.
 */
export function TooltipLayer() {
  const layerId = useId();
  const [tip, setTip] = useState<TipState | null>(null);
  const timer = useRef<number | null>(null);
  const current = useRef<HTMLElement | null>(null);
  const lastHide = useRef(0);

  useEffect(() => {
    layerOrder.push(layerId);
    notifyLayers();
    return () => {
      const at = layerOrder.indexOf(layerId);
      if (at >= 0) layerOrder.splice(at, 1);
      notifyLayers();
    };
  }, [layerId]);
  const active = useSyncExternalStore(
    subscribeLayers,
    () => layerOrder[0] === layerId,
    () => false,
  );

  useEffect(() => {
    if (!isBrowser || !active) return undefined;
    const clear = () => {
      if (timer.current !== null) {
        window.clearTimeout(timer.current);
        timer.current = null;
      }
    };
    const hide = () => {
      clear();
      if (current.current) lastHide.current = Date.now();
      current.current = null;
      setTip(null);
    };
    const show = (el: HTMLElement) => {
      current.current = el;
      setTip(tipFor(el));
    };
    const onOver = (event: PointerEvent) => {
      if (event.pointerType === 'touch') return;
      const el = tipTarget(event.target);
      if (!el || el === current.current) return;
      clear();
      current.current = el;
      const delay = Date.now() - lastHide.current < TOOLTIP_SKIP_WINDOW ? TOOLTIP_SKIP_DELAY : TOOLTIP_DELAY;
      timer.current = window.setTimeout(() => show(el), delay);
    };
    const onOut = (event: PointerEvent) => {
      const el = tipTarget(event.target);
      if (!el) return;
      const to = event.relatedTarget;
      if (to instanceof Node && el.contains(to)) return;
      hide();
    };
    const onFocusIn = (event: FocusEvent) => {
      const el = tipTarget(event.target);
      if (el && event.target instanceof Element && isKeyboardFocus(event.target)) show(el);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') hide();
    };
    document.addEventListener('pointerover', onOver);
    document.addEventListener('pointerout', onOut);
    document.addEventListener('focusin', onFocusIn);
    document.addEventListener('focusout', hide);
    document.addEventListener('pointerdown', hide, true);
    document.addEventListener('keydown', onKey);
    window.addEventListener('scroll', hide, true);
    return () => {
      clear();
      document.removeEventListener('pointerover', onOver);
      document.removeEventListener('pointerout', onOut);
      document.removeEventListener('focusin', onFocusIn);
      document.removeEventListener('focusout', hide);
      document.removeEventListener('pointerdown', hide, true);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', hide, true);
      setTip(null);
    };
  }, [active]);

  if (!active || !tip || !isBrowser) return null;
  const gap = 8;
  const { rect, side } = tip;
  const style =
    side === 'right'
      ? { left: rect.right + gap, top: rect.top + rect.height / 2 }
      : side === 'left'
        ? { left: rect.left - gap, top: rect.top + rect.height / 2 }
        : side === 'bottom'
        ? { left: rect.left + rect.width / 2, top: rect.bottom + gap }
        : { left: rect.left + rect.width / 2, top: rect.top - gap };
  return createPortal(
    <div className="tooltip" data-side={side} style={style} aria-hidden="true">
      <span>{tip.text}</span>
      {tip.kbd ? <kbd className="kbd tooltip-kbd">{tip.kbd}</kbd> : null}
    </div>,
    document.body,
  );
}
