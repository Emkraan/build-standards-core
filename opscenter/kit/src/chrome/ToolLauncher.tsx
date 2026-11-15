/* ToolLauncher: the tool switcher of a multi-tool shell. A button in the rail brand row (through
   the Rail brandSlot) opens a full-window carousel of every tool the person can enter. The focused
   tool sits large in the centre, the others smaller and dimmed, and its details show below with an
   Open button. Arrow keys, Home and End, the arrow buttons, the dots, a swipe and a tile click all
   move it. It advances slowly on its own and holds still on hover, keyboard focus and any
   interaction. Under reduced motion nothing moves on its own. The tools are plain data, so a host
   decides who can enter what and the launcher only displays it. */

import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { CSSProperties, KeyboardEvent, PointerEvent, ReactNode, Ref } from 'react';
import { IconArrowLeft, IconChevronLeft, IconChevronRight, IconExternal, IconGrid, IconPause, IconPlay } from '../icons/icons';
import { cx, prefersReducedMotion } from '../lib/env';
import { initialsOf } from '../lib/hues';
import type { MarkHue } from '../lib/hues';
import { useShortcut } from '../lib/shortcuts';
import { tokenDuration } from '../lib/timing';
import { Modal } from '../overlays/Modal';
import { Button, IconButton } from '../primitives/Button';
import { EmptyState, Skeleton } from '../primitives/EmptyState';
import { Badge } from '../primitives/marks';

/** One tool in the launcher. Plain data: the host decides which tools a person can enter. */
export interface LauncherTool {
  id: string;
  name: string;
  /** One short line under the name in the details. */
  tagline?: string | undefined;
  /** A sentence or two in the details. */
  description?: string | undefined;
  /** Tile tint. Absent or `brand` follows the app accent. */
  hue?: MarkHue | 'brand' | undefined;
  /** The tile face (a logo or an icon). Initials of the name show when omitted. */
  mark?: ReactNode;
  /** Opens outside the shell (a new tab). The tile shows an External badge and the details say so. */
  external?: boolean | undefined;
}

/** The key that opens the launcher from anywhere outside a text field. */
export const LAUNCHER_KEYS = 't';

/** Default carousel timing in milliseconds: how long a tool stays in the centre before the
    carousel moves on, and how long it stays still after the person interacts. */
export const LAUNCHER_TIMING = { autoMs: 4200, idleMs: 9000 } as const;

/** A drag of at least this many pixels moves the carousel. */
const SWIPE_PX = 40;

/**
 * Where tile `i` sits relative to the focused tile `at`: 0 in the centre, negative to the left.
 * Three or more tools wrap around (the carousel is a ring), two sit side by side.
 */
export function slideOffset(i: number, at: number, n: number): number {
  if (n < 3) return i - at;
  const half = Math.floor(n / 2);
  return ((((i - at + n + half) % n) + n) % n) - half;
}

function slotOf(off: number): 'center' | 'near' | 'far' | 'out' {
  const d = Math.abs(off);
  return d === 0 ? 'center' : d === 1 ? 'near' : d === 2 ? 'far' : 'out';
}

/** `A is open to you`, `A and B are open to you`, and past three names `A, B and 2 more are open to you`. */
export function openToYouLabel(names: readonly string[]): string {
  if (names.length === 0) return '';
  if (names.length === 1) return `${names[0]} is open to you`;
  const shown = names.length > 3 ? [...names.slice(0, 2), `${names.length - 2} more`] : [...names];
  return `${shown.slice(0, -1).join(', ')} and ${shown[shown.length - 1]} are open to you`;
}

/** A pointer that hovers (a mouse), so touch never pauses the carousel through an emulated hover. */
function canHover(): boolean {
  return typeof window.matchMedia === 'function' && !window.matchMedia('(hover: none)').matches;
}

const hueClass = (hue: LauncherTool['hue']): string | undefined => (hue && hue !== 'brand' ? `hue-${hue}` : undefined);

/* ---- state ---- */

export interface UseToolLauncherOptions {
  /** Keys that open the launcher (the shortcut grammar). Default `t`. */
  keys?: string | undefined;
  /** Turn the shortcut off, for example while the person has no other tool. Default true. */
  shortcut?: boolean | undefined;
  /** Shortcut description in the help dialog. */
  description?: string | undefined;
}

export interface ToolLauncherState {
  open: boolean;
  /** Screen point the dialog grows from, as a CSS `x y` pair, or null. */
  origin: string | null;
  /** Opens the launcher and remembers the control, so focus returns to it on close. */
  openFrom: (el: HTMLElement | null) => void;
  close: () => void;
  /** Attach to the rail switch button: the shortcut opens the launcher from it. */
  buttonRef: Ref<HTMLButtonElement>;
}

/** The launcher's open state, the opening control and the opening shortcut. */
export function useToolLauncher({ keys = LAUNCHER_KEYS, shortcut = true, description = 'Switch tool' }: UseToolLauncherOptions = {}): ToolLauncherState {
  const [open, setOpen] = useState(false);
  const [origin, setOrigin] = useState<string | null>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const wasOpen = useRef(false);

  const openFrom = useCallback((el: HTMLElement | null) => {
    openerRef.current = el;
    const rect = el?.getBoundingClientRect();
    setOrigin(rect && rect.width > 0 ? `${Math.round(rect.left + rect.width / 2)}px ${Math.round(rect.top + rect.height / 2)}px` : null);
    setOpen(true);
  }, []);
  const close = useCallback(() => setOpen(false), []);

  // Focus goes back to the control that opened the launcher. The modal restores focus to what had
  // it at open time in a microtask (the page, for the shortcut), so this runs after it and wins.
  useEffect(() => {
    if (open) {
      wasOpen.current = true;
      return undefined;
    }
    if (!wasOpen.current) return undefined;
    wasOpen.current = false;
    const t = window.setTimeout(() => {
      const el = openerRef.current;
      if (el && el.isConnected) el.focus({ preventScroll: true });
    }, 0);
    return () => window.clearTimeout(t);
  }, [open]);

  useShortcut(
    shortcut
      ? {
          id: 'kit.tools.launcher',
          keys,
          description,
          group: 'Navigation',
          handler: (event) => {
            event.preventDefault();
            openFrom(buttonRef.current);
          },
        }
      : null,
  );

  return { open, origin, openFrom, close, buttonRef };
}

/* ---- the buttons ---- */

export interface ToolSwitchButtonProps {
  launcher: ToolLauncherState;
  /** The active tool's name. */
  name: string;
  /** The active tool's mark. */
  mark?: ReactNode;
  hue?: LauncherTool['hue'];
  /** Accessible name of the control. Default `Switch tool`. */
  label?: string | undefined;
  /** `rail` is the compact control for the Rail brandSlot. `prominent` is the large button for a
      screen that has no rail (a no-access screen). `mark` is the collapsed form on its own: the
      tool's mark with a small corner glyph chip and no text. */
  variant?: 'rail' | 'prominent' | 'mark' | undefined;
  /** `rail` only: the control turns into the `mark` form while the rail is collapsed (desktop
      width), so it stays usable there. Pair it with `Rail` `keepBrandSlotCollapsed`. Default false. */
  collapsible?: boolean | undefined;
  /** `prominent` only: the small line over the name. */
  eyebrow?: string | undefined;
  className?: string | undefined;
}

/** The control that opens the launcher. It names the active tool and says what it does. */
export function ToolSwitchButton({ launcher, name, mark, hue, label = 'Switch tool', variant = 'rail', collapsible = false, eyebrow = 'Open your tool', className }: ToolSwitchButtonProps) {
  const nameId = useId();
  const prominent = variant === 'prominent';
  const keysLabel = LAUNCHER_KEYS.toUpperCase();
  return (
    <button
      ref={launcher.buttonRef}
      type="button"
      className={cx('tl-switch', hueClass(hue), className)}
      data-variant={variant}
      data-collapsible={collapsible && variant === 'rail' ? '' : undefined}
      aria-label={label}
      aria-describedby={nameId}
      aria-haspopup="dialog"
      aria-expanded={launcher.open}
      aria-keyshortcuts={keysLabel}
      data-tip={prominent ? undefined : label}
      data-tip-kbd={prominent ? undefined : keysLabel}
      onClick={(event) => launcher.openFrom(event.currentTarget)}
    >
      <span className="tl-switch-mark" aria-hidden="true">
        <span className="tl-ring" />
        <span className="tl-switch-tile">{mark ?? initialsOf(name)}</span>
      </span>
      <span className="tl-switch-text">
        {prominent ? <span className="tl-switch-eyebrow">{eyebrow}</span> : null}
        <span className="tl-switch-name" id={nameId}>
          {name}
        </span>
        {prominent ? null : (
          <span className="tl-switch-hint" aria-hidden="true">
            {label}
          </span>
        )}
      </span>
      <span className="tl-switch-glyph" aria-hidden="true">
        <IconGrid size={prominent ? 18 : 14} />
      </span>
    </button>
  );
}

/* ---- the dialog ---- */

interface DetailProps {
  tool: LauncherTool;
  current: boolean;
  position: string;
  dir: 'next' | 'prev';
  reduced: boolean;
  leaving?: boolean;
  onOpen?: (tool: LauncherTool) => void;
  headingId?: string;
  currentLabel: string;
  externalHint: string;
  openLabel: (tool: LauncherTool) => string;
}

function ToolDetail({ tool, current, position, dir, reduced, leaving = false, onOpen, headingId, currentLabel, externalHint, openLabel }: DetailProps) {
  const step = (i: number): CSSProperties | undefined => (reduced ? undefined : ({ '--tl-i': i } as CSSProperties));
  return (
    <div
      className={cx('tl-detail', hueClass(tool.hue), leaving && 'is-leaving')}
      data-external={tool.external ? '' : undefined}
      data-dir={dir}
      data-detail={tool.id}
      aria-hidden={leaving ? 'true' : undefined}
    >
      <p className="tl-detail-eyebrow" style={step(0)}>
        {position}
      </p>
      <h3 className="tl-detail-name" id={leaving ? undefined : headingId} style={step(1)}>
        {tool.name}
      </h3>
      {tool.tagline ? (
        <p className="tl-detail-tag" id={leaving || !headingId ? undefined : `${headingId}-tag`} style={step(2)}>
          {tool.tagline}
        </p>
      ) : null}
      {tool.description ? (
        <p className="tl-detail-desc" style={step(3)}>
          {tool.description}
        </p>
      ) : null}
      {tool.external ? (
        <p className="tl-detail-newtab" style={step(3)}>
          {externalHint}
        </p>
      ) : null}
      {leaving ? null : (
        <div className="tl-detail-actions" style={step(4)}>
          {current ? (
            <Button variant="primary" disabled>
              {currentLabel}
            </Button>
          ) : (
            <Button variant="primary" iconEnd={tool.external ? <IconExternal size={16} /> : <IconChevronRight size={16} />} onClick={() => onOpen?.(tool)}>
              {openLabel(tool)}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

export interface ToolLauncherProps {
  open: boolean;
  onClose: () => void;
  /** Every tool the person can enter, in display order. */
  tools: readonly LauncherTool[];
  /** The tool the person is in. The carousel opens centred on it and marks it Current. */
  activeId: string;
  /** Runs on Open, Enter and a click on the centre tile. The launcher closes first. */
  onOpen: (tool: LauncherTool) => void;
  /** Screen point the dialog grows from (`ToolLauncherState.origin`). */
  origin?: string | null | undefined;
  /** How many access reads are still out: shows a quiet loading line and marks the list busy. */
  pending?: number | undefined;
  title?: string | undefined;
  subtitle?: string | undefined;
  backLabel?: string | undefined;
  currentLabel?: string | undefined;
  externalLabel?: string | undefined;
  externalHint?: string | undefined;
  emptyTitle?: string | undefined;
  emptyBody?: string | undefined;
  /** Milliseconds a tool stays centred before the carousel moves on. 0 turns auto-advance off. */
  autoAdvanceMs?: number | undefined;
  /** Milliseconds the carousel stays still after the person interacts. */
  idleMs?: number | undefined;
}

type Way = 'next' | 'prev';
interface MoveOptions {
  user?: boolean;
  focusTile?: boolean;
}

export function ToolLauncher({
  open,
  onClose,
  tools,
  activeId,
  onOpen,
  origin,
  pending = 0,
  title = 'Tools',
  subtitle = 'Every tool your access opens.',
  backLabel = 'Back',
  currentLabel = 'Current tool',
  externalLabel = 'External',
  externalHint = 'Opens in a new tab',
  emptyTitle = 'No other tools yet',
  emptyBody = 'Your access does not open any other tool.',
  autoAdvanceMs = LAUNCHER_TIMING.autoMs,
  idleMs = LAUNCHER_TIMING.idleMs,
}: ToolLauncherProps) {
  const titleId = useId();
  const detailId = useId();
  const keysId = useId();
  const reduced = open ? prefersReducedMotion() : false;
  const n = tools.length;

  const [focusId, setFocusId] = useState<string | null>(null);
  const [dir, setDir] = useState<Way>('next');
  const [leaving, setLeaving] = useState<{ tool: LauncherTool; dir: Way; key: number } | null>(null);
  const [hovered, setHovered] = useState(false);
  const [keyFocus, setKeyFocus] = useState(false);
  const [interacting, setInteracting] = useState(false);
  const [stopped, setStopped] = useState(false);
  const keyed = useRef(false);
  const idleTimer = useRef<number | undefined>(undefined);
  const trackRef = useRef<HTMLUListElement | null>(null);
  const prevOffsets = useRef<Map<string, number>>(new Map());
  const drag = useRef<{ x: number; id: number; moved: boolean } | null>(null);
  const swallowClick = useRef(false);
  const leaveSeq = useRef(0);

  // Every open starts centred on the active tool, still and unpaused.
  useEffect(() => {
    if (!open) return;
    setFocusId(activeId);
    setLeaving(null);
    setHovered(false);
    setKeyFocus(false);
    setInteracting(false);
    setStopped(false);
    keyed.current = false;
    prevOffsets.current = new Map();
  }, [open, activeId]);
  useEffect(() => () => window.clearTimeout(idleTimer.current), []);

  const found = tools.findIndex((t) => t.id === focusId);
  const index = found >= 0 ? found : Math.max(0, tools.findIndex((t) => t.id === activeId));
  const focused: LauncherTool | undefined = n ? tools[index] : undefined;

  /** Any interaction keeps the carousel still for a while. */
  const interacted = useCallback(() => {
    setInteracting(true);
    window.clearTimeout(idleTimer.current);
    idleTimer.current = window.setTimeout(() => setInteracting(false), idleMs);
  }, [idleMs]);

  /** Moves the centre to tile `to`. `user` pauses auto-advance, `focusTile` moves keyboard focus with it. */
  const moveTo = useCallback(
    (to: number, way: Way, o: MoveOptions = {}) => {
      if (!n) return;
      const target = tools[((to % n) + n) % n];
      if (o.user) interacted();
      if (target && focused && target.id !== focused.id) {
        setDir(way);
        if (!reduced) {
          leaveSeq.current += 1;
          setLeaving({ tool: focused, dir: way, key: leaveSeq.current });
        }
        setFocusId(target.id);
      }
      if (o.focusTile && target) {
        window.requestAnimationFrame(() => {
          const el = trackRef.current?.querySelector(`[data-tool-card="${CSS.escape(target.id)}"]`);
          if (el instanceof HTMLElement) el.focus({ preventScroll: true });
        });
      }
    },
    [n, tools, focused, reduced, interacted],
  );
  const step = (delta: number, o: MoveOptions = {}) => moveTo(index + delta, delta >= 0 ? 'next' : 'prev', o);

  // The leaving copy of the details goes once its crossfade has run.
  useEffect(() => {
    if (!leaving) return undefined;
    const ms = (tokenDuration('--dur-travel') || 400) + 60;
    const t = window.setTimeout(() => setLeaving((l) => (l && l.key === leaving.key ? null : l)), ms);
    return () => window.clearTimeout(t);
  }, [leaving]);

  // Remember where each tile sat, so a tile that wraps around the ring jumps instead of sliding
  // across the stage behind the others.
  useEffect(() => {
    prevOffsets.current = new Map(tools.map((t, i) => [t.id, slideOffset(i, index, n)]));
  });

  const autoRunning = open && !reduced && !stopped && n > 1 && autoAdvanceMs > 0;
  const paused = hovered || keyFocus || interacting;
  useEffect(() => {
    if (!autoRunning || paused) return undefined;
    const t = window.setTimeout(() => step(1), autoAdvanceMs);
    return () => window.clearTimeout(t);
  });

  const choose = (tool: LauncherTool) => {
    onClose();
    onOpen(tool);
  };

  const onTrackKey = (e: KeyboardEvent) => {
    if (!n || e.altKey || e.ctrlKey || e.metaKey) return;
    const run: Record<string, () => void> = {
      ArrowRight: () => step(1, { user: true, focusTile: true }),
      ArrowLeft: () => step(-1, { user: true, focusTile: true }),
      Home: () => moveTo(0, 'prev', { user: true, focusTile: true }),
      End: () => moveTo(n - 1, 'next', { user: true, focusTile: true }),
      Enter: () => {
        if (focused && focused.id !== activeId) choose(focused);
      },
    };
    const fn = run[e.key];
    if (!fn) return;
    e.preventDefault();
    fn();
  };

  const onPointerDown = (e: PointerEvent) => {
    if (e.button !== 0 || n < 2) return;
    drag.current = { x: e.clientX, id: e.pointerId, moved: false };
  };
  const onPointerMove = (e: PointerEvent) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    const dx = e.clientX - d.x;
    if (!d.moved && Math.abs(dx) > 6) {
      d.moved = true;
      trackRef.current?.setAttribute('data-dragging', '');
    }
    if (d.moved && !reduced) trackRef.current?.style.setProperty('--tl-drag', `${Math.round(dx)}px`);
  };
  const onPointerUp = (e: PointerEvent) => {
    const d = drag.current;
    drag.current = null;
    const track = trackRef.current;
    track?.removeAttribute('data-dragging');
    track?.style.removeProperty('--tl-drag');
    if (!d || d.id !== e.pointerId || !d.moved) return;
    swallowClick.current = true;
    window.setTimeout(() => {
      swallowClick.current = false;
    }, 0);
    const dx = e.clientX - d.x;
    if (Math.abs(dx) < SWIPE_PX) return;
    const stepPx = track ? parseFloat(getComputedStyle(track).getPropertyValue('--tl-step')) || 200 : 200;
    const moves = Math.max(1, Math.min(n - 1, Math.round(Math.abs(dx) / stepPx)));
    step(dx < 0 ? moves : -moves, { user: true });
  };

  const style = origin ? ({ '--tl-origin': origin } as CSSProperties) : undefined;
  const empty = n === 0 && pending === 0;
  const position = (i: number) => `${i + 1} of ${n}`;
  const openLabel = (tool: LauncherTool) => `Open ${tool.name}`;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      hideHead
      hideClose
      footer={null}
      size="full"
      className="tl-panel"
      aria-labelledby={titleId}
      data-motion={reduced ? 'reduced' : 'full'}
      style={style}
    >
      <div
        className="tl-frame"
        onKeyDownCapture={(e) => {
          keyed.current = true;
          // Focus can already sit in the carousel before the first key (the dialog's autofocus, or
          // a pointer focus), so no focus event follows: hold here as well.
          if (e.currentTarget.querySelector('.tl-stage')?.contains(document.activeElement)) setKeyFocus(true);
        }}
      >
        <div className="tl-head">
          <Button variant="ghost" icon={<IconArrowLeft size={16} />} onClick={onClose}>
            {backLabel}
          </Button>
          <div className="tl-titles">
            <h2 className="tl-title" id={titleId}>
              {title}
            </h2>
            <p className="tl-sub">{subtitle}</p>
          </div>
        </div>

        <div
          className="tl-stage"
          data-paused={paused || !autoRunning ? '' : undefined}
          onMouseEnter={() => {
            if (canHover()) setHovered(true);
          }}
          onMouseLeave={() => setHovered(false)}
          onFocus={() => {
            if (keyed.current) setKeyFocus(true);
          }}
          onBlur={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setKeyFocus(false);
          }}
        >
          {n > 1 ? (
            <span className="tl-arrow-slot" data-side="prev">
              <IconButton label="Previous tool" variant="secondary" icon={<IconChevronLeft size={20} />} onClick={() => step(-1, { user: true })} />
            </span>
          ) : null}
          <ul
            ref={trackRef}
            className="tl-track"
            aria-label="Tools you can open"
            aria-roledescription="carousel"
            aria-describedby={keysId}
            aria-busy={pending > 0 || undefined}
            onKeyDown={onTrackKey}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
          >
            {tools.map((tool, i) => {
              const off = slideOffset(i, index, n);
              const was = prevOffsets.current.get(tool.id);
              const jump = was !== undefined && Math.abs(was - off) > 1;
              const centre = off === 0;
              const current = tool.id === activeId;
              return (
                <li
                  key={tool.id}
                  className="tl-slide"
                  data-slot={slotOf(off)}
                  data-jump={jump ? '' : undefined}
                  style={{ '--tl-off': off } as CSSProperties}
                  aria-roledescription="slide"
                  aria-label={position(i)}
                >
                  <button
                    type="button"
                    className={cx('tl-tile', hueClass(tool.hue), centre && 'is-focused', current && 'is-current')}
                    data-tool-card={tool.id}
                    data-autofocus={centre ? '' : undefined}
                    tabIndex={centre ? 0 : -1}
                    aria-label={tool.name}
                    aria-describedby={centre && tool.tagline ? `${detailId}-name-tag` : undefined}
                    aria-current={current ? 'true' : undefined}
                    onClick={() => {
                      if (swallowClick.current) return;
                      if (centre) {
                        if (!current) choose(tool);
                      } else moveTo(i, off > 0 ? 'next' : 'prev', { user: true });
                    }}
                  >
                    <span className="tl-tile-mark" aria-hidden="true">
                      <span className="tl-ring" />
                      <span className="tl-tile-face">{tool.mark ?? initialsOf(tool.name)}</span>
                    </span>
                    <span className="tl-tile-name">{tool.name}</span>
                    {current ? <Badge tone="accent">Current</Badge> : null}
                    {tool.external ? (
                      <Badge tone="info" className="tl-tile-external">
                        <IconExternal size={11} /> {externalLabel}
                      </Badge>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
          {n > 1 ? (
            <span className="tl-arrow-slot" data-side="next">
              <IconButton label="Next tool" variant="secondary" icon={<IconChevronRight size={20} />} onClick={() => step(1, { user: true })} />
            </span>
          ) : null}
        </div>

        {n > 1 ? (
          <div className="tl-controls">
            <div className="tl-dots" role="group" aria-label="Choose a tool">
              {tools.map((tool, i) => (
                <button
                  key={tool.id}
                  type="button"
                  className={cx('tl-dot', hueClass(tool.hue))}
                  aria-label={`Show ${tool.name}`}
                  aria-current={i === index ? 'true' : undefined}
                  onClick={() => moveTo(i, i > index ? 'next' : 'prev', { user: true })}
                />
              ))}
            </div>
            {!reduced && autoAdvanceMs > 0 ? (
              <IconButton
                size="sm"
                label={stopped ? 'Start moving through the tools' : 'Stop moving through the tools'}
                icon={stopped ? <IconPlay size={14} /> : <IconPause size={14} />}
                onClick={() => setStopped((s) => !s)}
              />
            ) : null}
          </div>
        ) : null}

        <p className="kit-sr-only" id={keysId}>
          Left and Right arrow keys move between tools, Enter opens the focused tool, Escape goes back.
        </p>
        <p className="kit-sr-only" aria-live={autoRunning && !paused ? 'off' : 'polite'} aria-atomic="true">
          {focused ? `${focused.name}${focused.external ? `, external tool, ${externalHint.toLowerCase()}` : ''}, ${position(index)}` : ''}
        </p>

        <section className="tl-details" aria-labelledby={focused ? `${detailId}-name` : undefined}>
          <div className="tl-details-stack" id={detailId}>
            {leaving && leaving.tool.id !== focused?.id ? (
              <ToolDetail
                key={`leave-${leaving.key}`}
                tool={leaving.tool}
                current={leaving.tool.id === activeId}
                position={position(Math.max(0, tools.findIndex((t) => t.id === leaving.tool.id)))}
                dir={leaving.dir}
                reduced={reduced}
                leaving
                currentLabel={currentLabel}
                externalHint={externalHint}
                openLabel={openLabel}
              />
            ) : null}
            {focused ? (
              <ToolDetail
                key={focused.id}
                tool={focused}
                current={focused.id === activeId}
                position={position(index)}
                dir={dir}
                reduced={reduced}
                onOpen={choose}
                headingId={`${detailId}-name`}
                currentLabel={currentLabel}
                externalHint={externalHint}
                openLabel={openLabel}
              />
            ) : null}
          </div>
          {pending > 0 ? (
            <div className="tl-pending">
              <Skeleton variant="lines" count={1} label="Checking which tools you can open" />
            </div>
          ) : null}
          {empty ? (
            <div className="tl-empty">
              <EmptyState compact title={emptyTitle} body={emptyBody} />
            </div>
          ) : null}
        </section>
      </div>
    </Modal>
  );
}
