/* Popover (an anchored, non-modal panel) and Menu (a button that opens a list of actions). Escape
   and an outside click close them, and focus returns to the trigger. */

import { cloneElement, isValidElement, useCallback, useEffect, useId, useRef, useState, version } from 'react';
import type { KeyboardEvent, MouseEvent, ReactElement, ReactNode, Ref, RefObject } from 'react';
import { createPortal } from 'react-dom';
import { cx, isBrowser } from '../lib/env';
import { focusables, layerRoot, useIsoLayoutEffect, useLayerRoot, useModalLayer } from '../lib/layers';

export type Placement = 'bottom-start' | 'bottom-end' | 'top-start' | 'top-end';

interface Position {
  top?: number | undefined;
  bottom?: number | undefined;
  left?: number | undefined;
  right?: number | undefined;
}

function place(anchor: HTMLElement, placement: Placement): Position {
  const r = anchor.getBoundingClientRect();
  const gap = 6;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const vertical = placement.startsWith('top') ? { bottom: vh - r.top + gap } : { top: r.bottom + gap };
  const horizontal = placement.endsWith('end') ? { right: Math.max(8, vw - r.right) } : { left: Math.max(8, r.left) };
  return { ...vertical, ...horizontal };
}

export interface PopoverProps {
  open: boolean;
  onClose: () => void;
  /** The element the panel attaches to. */
  anchorRef: RefObject<HTMLElement | null>;
  children?: ReactNode;
  placement?: Placement | undefined;
  /** Accessible name of the panel. */
  label: string;
  /** dialog for content, menu for a Menu list. */
  role?: 'dialog' | 'menu' | undefined;
  className?: string | undefined;
  id?: string | undefined;
  /**
   * Where the panel is portaled. Default: the kit layer root at <body> level, so an animated
   * transform on <main> cannot move a fixed panel away from its trigger.
   */
  container?: HTMLElement | null | undefined;
}

export function Popover({ open, onClose, anchorRef, children, placement = 'bottom-start', label, role = 'dialog', className, id, container }: PopoverProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<Position>({});
  useLayerRoot(open && !container);
  useModalLayer(open, panelRef, { onEscape: onClose, modal: false });

  useIsoLayoutEffect(() => {
    if (!open || !anchorRef.current) return undefined;
    const update = () => {
      if (anchorRef.current) setPos(place(anchorRef.current, placement));
    };
    update();
    window.addEventListener('resize', update);
    window.addEventListener('scroll', update, true);
    return () => {
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
    };
  }, [open, placement]);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (event: PointerEvent) => {
      const t = event.target;
      if (!(t instanceof Node)) return;
      if (panelRef.current?.contains(t) || anchorRef.current?.contains(t)) return;
      onClose();
    };
    document.addEventListener('pointerdown', onDown, true);
    return () => document.removeEventListener('pointerdown', onDown, true);
  }, [open, onClose, anchorRef]);

  if (!open || !isBrowser) return null;
  const host = container ?? layerRoot();
  return createPortal(
    <div
      ref={panelRef}
      id={id}
      className={cx('popover', className)}
      role={role}
      aria-label={label}
      tabIndex={-1}
      style={pos}
      onBlur={(event) => {
        const next = event.relatedTarget;
        if (next instanceof Node && (event.currentTarget.contains(next) || anchorRef.current?.contains(next))) return;
        if (role === 'menu' && next !== null) onClose();
      }}
    >
      {children}
    </div>,
    host,
  );
}

// React 19 moved ref into props and warns on element.ref. React 18 keeps it on the element.
const REF_IN_PROPS = Number.parseInt(version, 10) >= 19;

function assignRef<T>(ref: Ref<T> | undefined, value: T | null): void {
  if (typeof ref === 'function') ref(value);
  else if (ref && typeof ref === 'object') (ref as { current: T | null }).current = value;
}

export interface MenuItemDef {
  id: string;
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
  danger?: boolean | undefined;
  disabled?: boolean | undefined;
}

export interface MenuProps {
  /** The trigger, usually an IconButton. It receives aria-haspopup, aria-expanded and onClick. */
  trigger: ReactElement;
  items: readonly MenuItemDef[];
  /** Accessible name of the menu. */
  label: string;
  placement?: Placement | undefined;
}

export function Menu({ trigger, items, label, placement = 'bottom-end' }: MenuProps) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLElement | null>(null);
  const menuId = `${useId()}-menu`;
  const close = useCallback(() => setOpen(false), []);
  // Which item takes focus when the menu opens: the first, or the last after ArrowUp.
  const focusOnOpen = useRef<'first' | 'last'>('first');

  // Opening, by click or by key, moves focus to the first enabled item (ArrowUp: the last), so
  // the arrow keys work at once. useModalLayer focuses the panel first, and this runs after it.
  useEffect(() => {
    if (!open) return undefined;
    const panel = document.getElementById(menuId);
    if (!panel) return undefined;
    const enabled = Array.from(panel.querySelectorAll<HTMLElement>('[role="menuitem"]')).filter(
      (el) => !(el as HTMLButtonElement).disabled && el.getAttribute('aria-disabled') !== 'true',
    );
    const target = focusOnOpen.current === 'last' ? enabled[enabled.length - 1] : enabled[0];
    focusOnOpen.current = 'first';
    target?.focus({ preventScroll: true });
    return undefined;
  }, [open, menuId]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const list = focusables(event.currentTarget).filter((el) => el.getAttribute('role') === 'menuitem');
    const i = list.indexOf(document.activeElement as HTMLElement);
    let next: HTMLElement | undefined;
    if (event.key === 'ArrowDown') next = list[(i + 1) % list.length];
    else if (event.key === 'ArrowUp') next = list[(i - 1 + list.length) % list.length];
    else if (event.key === 'Home') next = list[0];
    else if (event.key === 'End') next = list[list.length - 1];
    else if (event.key === 'Tab') {
      setOpen(false);
      return;
    }
    if (!next) return;
    event.preventDefault();
    next.focus();
  };

  if (!isValidElement(trigger)) return null;
  const t = trigger as ReactElement<Record<string, unknown>>;
  // The trigger's own ref and handlers keep working: they run first, and a handler that calls
  // preventDefault stops the menu behaviour. React 19 keeps ref in props, React 18 on the element.
  const ownRef = (REF_IN_PROPS ? t.props['ref'] : (t as unknown as { ref?: unknown }).ref) as Ref<HTMLElement> | undefined;
  const ownClick = t.props['onClick'] as ((event: MouseEvent<HTMLElement>) => void) | undefined;
  const ownKeyDown = t.props['onKeyDown'] as ((event: KeyboardEvent<HTMLElement>) => void) | undefined;
  const triggerEl = cloneElement(t, {
    ref: (node: HTMLElement | null) => {
      anchorRef.current = node;
      assignRef(ownRef, node);
    },
    'aria-haspopup': 'menu',
    'aria-expanded': open,
    'aria-controls': open ? menuId : undefined,
    onClick: (event: MouseEvent<HTMLElement>) => {
      ownClick?.(event);
      if (event.defaultPrevented) return;
      setOpen((v) => !v);
    },
    onKeyDown: (event: KeyboardEvent<HTMLElement>) => {
      ownKeyDown?.(event);
      if (open || event.defaultPrevented) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Enter' || event.key === ' ') {
        // preventDefault keeps Enter and Space from also firing a click that would toggle it shut.
        event.preventDefault();
        focusOnOpen.current = event.key === 'ArrowUp' ? 'last' : 'first';
        setOpen(true);
      }
    },
  });

  return (
    <>
      {triggerEl}
      <Popover open={open} onClose={close} anchorRef={anchorRef} placement={placement} label={label} role="menu" id={menuId} className="menu">
        <div className="menu-list" onKeyDown={onKeyDown}>
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              role="menuitem"
              className="menu-item"
              data-danger={item.danger ? '' : undefined}
              disabled={item.disabled}
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
            >
              {item.icon ? (
                <span className="menu-icon" aria-hidden="true">
                  {item.icon}
                </span>
              ) : null}
              <span>{item.label}</span>
            </button>
          ))}
        </div>
      </Popover>
    </>
  );
}
