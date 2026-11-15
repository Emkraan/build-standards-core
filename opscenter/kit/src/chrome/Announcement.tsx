/* Announcement banners (UI standard section 20): tone cards with a severity glyph and a dismiss
   control. Dismissal is per announcement id and persists in local storage. Banners belong on the
   home page only, so mount them there. A banner may carry one action (a link or a button), and
   `dismissible: false` hides the dismiss control for alerts that clear themselves. Every banner
   and stack on a page shares one dismissed list per storage key: a dismiss re-reads storage and
   merges, so dismissing one banner never brings another back. */

import { useCallback, useEffect, useId, useState } from 'react';
import type { ReactNode } from 'react';
import { IconAlert, IconCheckCircle, IconClose, IconInfo, IconWarning } from '../icons/icons';
import { isBrowser, readJson, writeJson } from '../lib/env';
import { useStorageKeys } from '../lib/scope';
import type { MarkHue } from '../lib/hues';

export type AnnouncementTone = 'info' | 'success' | 'warning' | 'critical';

const TONE: Record<AnnouncementTone, { hue: MarkHue; icon: ReactNode; label: string }> = {
  info: { hue: 'blue', icon: <IconInfo />, label: 'Information' },
  success: { hue: 'green', icon: <IconCheckCircle />, label: 'Good news' },
  warning: { hue: 'amber', icon: <IconWarning />, label: 'Warning' },
  critical: { hue: 'red', icon: <IconAlert />, label: 'Critical' },
};

const SEVERITY: Record<AnnouncementTone, number> = { critical: 0, warning: 1, info: 2, success: 3 };

export interface Announcement {
  id: string;
  tone: AnnouncementTone;
  title: string;
  body?: string | undefined;
  /** Small line under the body, for example "Posted today". */
  meta?: string | undefined;
  /** One action under the text: a link (class announce-link) or a small Button. */
  action?: ReactNode;
  /** Default true. False hides the dismiss control, for alerts that clear themselves. */
  dismissible?: boolean | undefined;
}

/** Most severe first, then input order, at most five (the section 20 contract). */
export function sortAnnouncements<T extends Pick<Announcement, 'tone'>>(list: readonly T[], cap = 5): T[] {
  return list
    .map((a, i) => ({ a, i }))
    .sort((x, y) => SEVERITY[x.a.tone] - SEVERITY[y.a.tone] || x.i - y.i)
    .slice(0, cap)
    .map((x) => x.a);
}

/** Most ids kept in the dismissed list. The oldest drop off first. */
export const DISMISSED_CAP = 200;

/** The dismissed ids stored under a key. Anything that is not a list of strings reads as empty. */
export function readDismissed(storageKey: string): string[] {
  const v = readJson<unknown>(storageKey, []);
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
}

/** Adds an id to the stored list, merged with what storage holds now, capped to the newest 200. */
export function addDismissed(storageKey: string, id: string): string[] {
  const current = readDismissed(storageKey);
  if (current.includes(id)) return current;
  const next = [...current, id].slice(-DISMISSED_CAP);
  writeJson(storageKey, next);
  notify(storageKey);
  return next;
}

// Hooks on the same page that watch the same key. Other tabs are covered by the storage event.
const listeners = new Map<string, Set<() => void>>();

function notify(storageKey: string): void {
  listeners.get(storageKey)?.forEach((fn) => fn());
}

/** Dismissed announcement ids, persisted per browser (per app inside a StorageScope). */
export function useDismissed(storageKey?: string) {
  const keys = useStorageKeys();
  const key = storageKey ?? keys.announcementsDismissed;
  const [ids, setIds] = useState<string[]>(() => readDismissed(key));

  useEffect(() => {
    const sync = () => {
      const next = readDismissed(key);
      setIds((prev) => (prev.length === next.length && prev.every((x, i) => x === next[i]) ? prev : next));
    };
    sync();
    let set = listeners.get(key);
    if (!set) {
      set = new Set();
      listeners.set(key, set);
    }
    set.add(sync);
    const onStorage = (event: StorageEvent) => {
      if (event.key === null || event.key === key) sync();
    };
    if (isBrowser) window.addEventListener('storage', onStorage);
    return () => {
      set?.delete(sync);
      if (set && set.size === 0) listeners.delete(key);
      if (isBrowser) window.removeEventListener('storage', onStorage);
    };
  }, [key]);

  const dismiss = useCallback(
    (id: string) => {
      setIds(addDismissed(key, id));
    },
    [key],
  );
  return { dismissed: ids, isDismissed: (id: string) => ids.includes(id), dismiss };
}

export interface AnnouncementBannerProps extends Announcement {
  /** Called after the banner is dismissed and the id persisted. */
  onDismiss?: ((id: string) => void) | undefined;
  storageKey?: string | undefined;
}

interface BannerViewProps extends Announcement {
  onClose: () => void;
}

function BannerView({ tone, title, body, meta, action, dismissible = true, onClose }: BannerViewProps) {
  const titleId = `${useId()}-title`;
  const t = TONE[tone];
  return (
    <section
      className={`announce hue-${t.hue}`}
      aria-labelledby={titleId}
      data-tone={tone}
      role={tone === 'critical' ? 'alert' : undefined}
    >
      <span className={`announce-icon hue-tile hue-${t.hue}`} role="img" aria-label={t.label}>
        {t.icon}
      </span>
      <div>
        <h2 id={titleId} className="announce-title">
          {title}
        </h2>
        {body ? <p className="announce-body">{body}</p> : null}
        {meta ? <p className="announce-meta">{meta}</p> : null}
        {action !== undefined && action !== null && action !== false ? <div className="announce-action">{action}</div> : null}
      </div>
      {dismissible ? (
        <button type="button" className="announce-close" aria-label={`Dismiss announcement: ${title}`} data-tip="Dismiss" onClick={onClose}>
          <IconClose size={14} />
        </button>
      ) : null}
    </section>
  );
}

/** One banner on its own. Inside a list, prefer AnnouncementStack (it orders, caps and dismisses). */
export function AnnouncementBanner({ onDismiss, storageKey, ...announcement }: AnnouncementBannerProps) {
  const { isDismissed, dismiss } = useDismissed(storageKey);
  const dismissible = announcement.dismissible !== false;
  if (dismissible && isDismissed(announcement.id)) return null;
  return (
    <BannerView
      {...announcement}
      onClose={() => {
        dismiss(announcement.id);
        onDismiss?.(announcement.id);
      }}
    />
  );
}

/** What the stack shows: dismissed ones removed first, then most severe first, at most `cap`. */
export function visibleAnnouncements<T extends Pick<Announcement, 'id' | 'tone' | 'dismissible'>>(
  list: readonly T[],
  dismissed: readonly string[],
  cap = 5,
): T[] {
  const hidden = new Set(dismissed);
  return sortAnnouncements(
    list.filter((a) => a.dismissible === false || !hidden.has(a.id)),
    cap,
  );
}

export interface AnnouncementStackProps {
  announcements: readonly Announcement[];
  storageKey?: string | undefined;
  /** Called after an announcement is dismissed and the id persisted. */
  onDismiss?: ((id: string) => void) | undefined;
}

/** The home page banner list: dismissed ones hidden, then most severe first, at most five. */
export function AnnouncementStack({ announcements, storageKey, onDismiss }: AnnouncementStackProps) {
  const { dismissed, dismiss } = useDismissed(storageKey);
  const list = visibleAnnouncements(announcements, dismissed);
  if (list.length === 0) return null;
  return (
    <div className="announce-stack">
      {list.map((a) => (
        <BannerView
          key={a.id}
          {...a}
          onClose={() => {
            dismiss(a.id);
            onDismiss?.(a.id);
          }}
        />
      ))}
    </div>
  );
}
