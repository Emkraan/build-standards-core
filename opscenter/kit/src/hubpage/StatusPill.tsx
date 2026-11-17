/* StatusPill: one pill for every status vocabulary, mapped centrally to a tone so no page decides a
   colour by itself. The shipped words cover the common work states. An app adds its own words with
   the `words` prop or statusTone's second argument, and an unknown word is neutral, never a guess. */

import { Pill } from '../primitives/marks';
import type { StatusTone } from '../primitives/marks';

type PillTone = Extract<StatusTone, 'success' | 'info' | 'warning' | 'danger' | 'neutral'>;

const TONES: Readonly<Record<string, PillTone>> = {
  // done and well
  healthy: 'success', ok: 'success', passing: 'success', ready: 'success', approved: 'success', done: 'success',
  closed: 'success', merged: 'success', shipped: 'success', resolved: 'success', current: 'success', clear: 'success',
  // in motion
  active: 'info', 'in progress': 'info', running: 'info', working: 'info', suggested: 'info', proposed: 'info',
  open: 'info', draft: 'info', 'to do': 'info', todo: 'info', new: 'info',
  // waiting on a person
  'needs me': 'warning', 'needs decision': 'warning', 'worth a look': 'warning', waiting: 'warning', pending: 'warning',
  stale: 'warning', review: 'warning', 'in review': 'warning', 'at risk': 'warning',
  // broken
  failing: 'danger', failed: 'danger', stuck: 'danger', blocked: 'danger', error: 'danger', overdue: 'danger', down: 'danger',
  // set aside
  parked: 'neutral', snoozed: 'neutral', declined: 'neutral', rejected: 'neutral', retired: 'neutral', archived: 'neutral',
  unknown: 'neutral', skipped: 'neutral', paused: 'neutral', idle: 'neutral',
};

/** Every status word the kit knows, for a conformance test. */
export const STATUS_WORDS: readonly string[] = Object.keys(TONES);

/** The tone of a status word, neutral for a word nobody mapped. `extra` words win over the shipped ones. */
export function statusTone(status: string, extra?: Readonly<Record<string, StatusTone>>): StatusTone {
  const word = status.trim().toLowerCase();
  return extra?.[word] ?? TONES[word] ?? 'neutral';
}

export interface StatusPillProps {
  status: string;
  /** The text shown. Default is the status word with a capital. */
  label?: string | undefined;
  /** An app's own words and their tones. */
  words?: Readonly<Record<string, StatusTone>> | undefined;
}

export function StatusPill({ status, label, words }: StatusPillProps) {
  return (
    <Pill tone={statusTone(status, words)} dot>
      {label ?? status.charAt(0).toUpperCase() + status.slice(1)}
    </Pill>
  );
}
