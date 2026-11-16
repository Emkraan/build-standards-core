/* The notice tray (Ops Center Layout rule 18): every system notice that rides above a page (a fallback in use, a stuck automation
   window, a pending restart) is one fixed-height row here: a tone icon, a one-line title, at most one action and a chevron that opens
   the detail. The order is fixed (critical, warning, info, then input order), a notice has no dismiss control because it clears when
   its condition ends, and an empty tray takes no space. A page alert that carries its own long copy is not a notice: use an
   announcement banner for that. */

import { useId, useState } from 'react';
import type { ReactNode } from 'react';
import { IconAlert, IconChevronDown, IconInfo, IconWarning } from '../icons/icons';
import type { MarkHue } from '../lib/hues';

export type NoticeTone = 'critical' | 'warning' | 'info';

const TONE: Record<NoticeTone, { hue: MarkHue; icon: ReactNode; label: string }> = {
  critical: { hue: 'red', icon: <IconAlert />, label: 'Critical' },
  warning: { hue: 'amber', icon: <IconWarning />, label: 'Warning' },
  info: { hue: 'blue', icon: <IconInfo />, label: 'Information' },
};

const ORDER: Record<NoticeTone, number> = { critical: 0, warning: 1, info: 2 };

export interface NoticeItem {
  id: string;
  tone?: NoticeTone | undefined;
  /** One line. It is cut with an ellipsis on a wide screen and wraps on a phone. */
  title: ReactNode;
  /** What the chevron opens. Without it the row has no chevron. */
  detail?: ReactNode;
  /** The one control the row carries: a button or a link. */
  action?: ReactNode;
}

/** Most severe first, then input order. The input is not changed. */
export function sortNotices<T extends { tone?: NoticeTone | undefined }>(list: readonly T[]): T[] {
  return list
    .map((n, i) => ({ n, i }))
    .sort((a, b) => ORDER[a.n.tone ?? 'critical'] - ORDER[b.n.tone ?? 'critical'] || a.i - b.i)
    .map((x) => x.n);
}

/** One notice row. The tray renders these, a page may also use one on its own. */
export function Notice({ tone = 'critical', title, detail, action }: Omit<NoticeItem, 'id'>) {
  const t = TONE[tone];
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className={`notice hue-${t.hue}`} data-tone={tone} data-open={open || undefined} role={tone === 'info' ? 'status' : 'alert'}>
      <div className="notice-row">
        <span className={`notice-icon hue-tile hue-${t.hue}`} role="img" aria-label={t.label}>
          {t.icon}
        </span>
        <h2 className="notice-title">{title}</h2>
        {action ? <div className="notice-action">{action}</div> : null}
        {detail ? (
          <button
            type="button"
            className="btn notice-toggle"
            data-variant="ghost"
            data-size="sm"
            data-icon-only=""
            aria-expanded={open}
            aria-controls={id}
            aria-label={open ? 'Hide the detail' : 'Show the detail'}
            data-tip={open ? 'Hide the detail' : 'Show the detail'}
            onClick={() => setOpen(!open)}
          >
            <IconChevronDown />
          </button>
        ) : null}
      </div>
      {detail ? (
        <div className="notice-detail" id={id} hidden={!open}>
          {detail}
        </div>
      ) : null}
    </div>
  );
}

export interface NoticeTrayProps {
  notices: readonly NoticeItem[];
}

/** The tray. It renders no element at all while the list is empty, so it takes no space. */
export function NoticeTray({ notices }: NoticeTrayProps) {
  if (notices.length === 0) return null;
  return (
    <section className="notice-tray" aria-label="Notices">
      {sortNotices(notices).map((n) => (
        <Notice key={n.id} tone={n.tone} title={n.title} detail={n.detail} action={n.action} />
      ))}
    </section>
  );
}
