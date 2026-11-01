/* Gate override pieces of an ops center (layout standard, rules 10 and 11): OverrideBar, OverrideButton,
   OverrideTag and PendingReason. An override lifts one gate for the owner's own work, for a limited time.
   The kit draws the controls and asks first; what the gate is, who may override, the expiry and the wording
   after the action come from the app and its server (`pending_line` of the core override store). Nothing is
   decided here: no gate name, no window, no clock. Every piece renders nothing, or the plain reason, when the
   app has not given it data yet. A confirm always comes first when an override is turned on, because lifting a
   gate can ship work. */

import type { ReactNode } from 'react';
import { useState } from 'react';
import { useConfirm } from '../overlays/dialogs';
import { Badge } from '../primitives/marks';
import { Button } from '../primitives/Button';
import { Switch } from '../primitives/Choice';
import { cx } from '../lib/env';

/** What the confirm says before an override is turned on. */
export interface OverrideConfirm {
  /** A question: "Bypass the change freeze for all my PRs?" */
  title: string;
  /** The consequence in plain words: what stops being held, what still applies, when it ends. */
  body?: ReactNode;
  /** The verb. Default "Turn on". */
  confirmLabel?: string | undefined;
}

/** How an override covers one item: `item` for this item only, `all` for every item, null for none. */
export type OverrideCover = 'item' | 'all' | null;

/** Tag for an item whose gate is lifted, so what happens next is never a surprise. */
export function OverrideTag({ cover, itemLabel = 'bypassed', allLabel = 'bypassed (all)', className }: { cover?: OverrideCover | undefined; itemLabel?: string; allLabel?: string; className?: string | undefined }) {
  if (!cover) return null;
  return (
    <Badge className={cx('pill', className)} tone="warning">
      {cover === 'item' ? itemLabel : allLabel}
    </Badge>
  );
}

export interface OverrideBarProps {
  /** The small title over the line, for example "Change freeze". The bar renders nothing without a `gate`. */
  title: string;
  /** The gate that is holding things now, in words: "Q4 freeze is on until Mon 11:59 PM." Absent: no bar. */
  gate?: ReactNode | undefined;
  /** What follows the gate line, which depends on the override: off, on for all, or on for some items. */
  detail?: ReactNode;
  /** The all-items override is on now. */
  on?: boolean | undefined;
  /** Label of the switch. */
  switchLabel: string;
  /** One line under the switch label, for example when it turns itself off. */
  switchHint?: ReactNode;
  /** Text of the tag shown while on. Default "override on". */
  onLabel?: string | undefined;
  /** Asked before turning the override on. Turning it off needs no confirm. */
  confirm: OverrideConfirm;
  /** Writes the new state; a rejection shows its message in the dialog and keeps the switch where it was. */
  onToggle: (next: boolean) => Promise<unknown> | void;
  className?: string | undefined;
}

export function OverrideBar({ title, gate, detail, on = false, switchLabel, switchHint, onLabel = 'override on', confirm, onToggle, className }: OverrideBarProps) {
  const { confirm: ask, dialog } = useConfirm();
  const [busy, setBusy] = useState(false);
  if (!gate) return null;
  const flip = async (next: boolean) => {
    if (!next) {
      setBusy(true);
      try {
        await onToggle(false);
      } finally {
        setBusy(false);
      }
      return;
    }
    await ask({
      title: confirm.title,
      body: confirm.body,
      confirmLabel: confirm.confirmLabel ?? 'Turn on',
      danger: true,
      action: () => onToggle(true),
    });
  };
  return (
    <section className={cx('override-bar', className)} aria-label={title} data-on={on || undefined}>
      {dialog}
      <div className="override-bar-text">
        <h2 className="override-bar-title">{title}</h2>
        <p className="override-bar-line">
          {gate}
          {detail ? <> {detail}</> : null}
        </p>
      </div>
      <div className="override-bar-actions">
        {on ? (
          <Badge className="pill" tone="warning">
            {onLabel}
          </Badge>
        ) : null}
        <Switch label={switchLabel} description={switchHint} checked={on} disabled={busy} onChange={(v) => void flip(v)} />
      </div>
    </section>
  );
}

export interface OverrideButtonProps {
  /** The gate holds this item now. */
  held?: boolean | undefined;
  /** How an override covers the item now. Nothing renders when the all-items override covers it (the bar turns that off). */
  cover?: OverrideCover | undefined;
  /** Label to turn it on, for example "Bypass freeze". */
  label: string;
  /** Label to take it back, for example "Undo freeze bypass". */
  undoLabel: string;
  /** Asked before turning it on. Taking it back needs no confirm. */
  confirm: OverrideConfirm;
  /** Writes the new state. */
  onSet: (next: boolean) => Promise<unknown> | void;
  size?: 'sm' | 'md' | undefined;
  className?: string | undefined;
}

export function OverrideButton({ held, cover, label, undoLabel, confirm, onSet, size = 'sm', className }: OverrideButtonProps) {
  const { confirm: ask, dialog } = useConfirm();
  const [busy, setBusy] = useState(false);
  if (cover === 'all' || (!held && cover !== 'item')) return null;
  const undo = cover === 'item';
  const go = async () => {
    if (undo) {
      setBusy(true);
      try {
        await onSet(false);
      } finally {
        setBusy(false);
      }
      return;
    }
    await ask({
      title: confirm.title,
      body: confirm.body,
      confirmLabel: confirm.confirmLabel ?? label,
      danger: true,
      action: () => onSet(true),
    });
  };
  return (
    <>
      {dialog}
      <Button className={className} size={size} variant={undo ? 'ghost' : 'secondary'} loading={busy} onClick={() => void go()}>
        {undo ? undoLabel : label}
      </Button>
    </>
  );
}

export interface PendingReasonProps {
  /** The server's line for the pending next step (`pending_line`): what was done and when it is re-checked. Present between the action and the next pass. */
  pending?: string | null | undefined;
  /** The reason the item is held. Shown only while there is no pending line. */
  reason?: ReactNode;
  className?: string | undefined;
}

/**
 * Rule 11: after an action a card never shows the reason the action just removed. With a `pending` line it
 * shows that line (and not the reason); without one it shows the reason; with neither it shows nothing.
 */
export function PendingReason({ pending, reason, className }: PendingReasonProps) {
  if (pending) {
    return (
      <p className={cx('override-pending', className)} role="status" data-state="pending">
        {pending}
      </p>
    );
  }
  if (!reason) return null;
  return (
    <p className={cx('override-reason', className)} data-state="held">
      {reason}
    </p>
  );
}
