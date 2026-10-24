/* BuildCard and the What's new dialog (UI standard sections 22 and 25). A live or offline dot, the
   version rolling in one character at a time, a New pill until that version's notes are opened,
   and the notes themselves, generated from git history by scripts/gen-changelog.mjs. */

import { useEffect, useId, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { IconClose, IconSparkle } from '../icons/icons';
import { isBrowser, readStorage, writeStorage } from '../lib/env';
import { useStorageKeys } from '../lib/scope';
import { useModalLayer } from '../lib/layers';

export type ReleaseItemType = 'new' | 'improved' | 'fixed';

export interface ReleaseItem {
  type?: ReleaseItemType | undefined;
  title: string;
  detail?: string | undefined;
}

/** One release as written by gen-changelog.mjs. Items may be plain strings. */
export interface ReleaseNote {
  version: string;
  /** ISO calendar day, YYYY-MM-DD. Optional: notes summarised by an API may carry no date. */
  date?: string | undefined;
  title: string;
  items: readonly (string | ReleaseItem)[];
  /** A link beside this release, for example the full changelog of the tool it belongs to, when
      one dialog lists releases from several tools (http or https only). */
  link?: ReleaseNotesLink | undefined;
}

const TYPE_META: Record<ReleaseItemType, { label: string; hue: string; mark: string }> = {
  new: { label: 'New', hue: 'violet', mark: 'N' },
  improved: { label: 'Improved', hue: 'blue', mark: 'I' },
  fixed: { label: 'Fixed', hue: 'green', mark: 'F' },
};

function normalise(item: string | ReleaseItem): ReleaseItem {
  return typeof item === 'string' ? { title: item } : item;
}

/** "1.4.0" and "v1.4.0" read as v1.4.0. A label such as "next" stays as it is. */
export function versionLabel(version: string): string {
  const v = version.replace(/^v(?=\d)/i, '');
  return /^\d/.test(v) ? `v${v}` : v;
}

/** Splits text into per-character spans that roll in one after another (.ver-ch, --i). */
export function RollingText({ text }: { text: string }) {
  return (
    <span className="ver-roll" aria-hidden="true">
      {Array.from(text).map((ch, i) => (
        <span key={`${i}-${ch}`} className="ver-ch" style={{ '--i': i } as CSSProperties}>
          {ch}
        </span>
      ))}
    </span>
  );
}

export interface BuildCardProps {
  /** The running version, for example 1.4.0. */
  version: string;
  /** Newest first. The card is disabled only when this is empty, which CI prevents. */
  releases: readonly ReleaseNote[];
  /** Backend reachable. False shows the offline dot. */
  live?: boolean | undefined;
  /** Short line under the version, for example "Deployed 2h ago". */
  subtitle?: string | undefined;
  /** Default `shell.build.seen`, or `shell.<appId>.build.seen` inside a StorageScope. */
  storageKey?: string | undefined;
  /** A link in the dialog foot to the full changelog in the docs home (http or https only). */
  link?: ReleaseNotesLink | undefined;
  /** What the New pill compares with the last opened notes. Default `version`. Set it when the
      notes change without the version changing, for example a console that lists the releases
      of several tools, so a new release in any of them shows the pill. */
  seenKey?: string | undefined;
}

/** The full changelog link in the What's new foot. */
export interface ReleaseNotesLink {
  href: string;
  label: string;
}

/** Only an absolute http or https link is rendered, so data from an API can never inject a script URL. */
export function safeReleaseLink(link: ReleaseNotesLink | undefined): ReleaseNotesLink | undefined {
  if (!link || typeof link.href !== 'string' || typeof link.label !== 'string' || !link.label.trim()) return undefined;
  try {
    const url = new URL(link.href);
    return url.protocol === 'https:' || url.protocol === 'http:' ? { href: url.href, label: link.label.trim() } : undefined;
  } catch {
    return undefined;
  }
}

export function BuildCard({ version, releases, live = true, subtitle, storageKey: storageKeyProp, link, seenKey }: BuildCardProps) {
  const keys = useStorageKeys();
  const storageKey = storageKeyProp ?? keys.buildSeen;
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState(() => readStorage(storageKey));
  const cardRef = useRef<HTMLButtonElement | null>(null);
  const marker = seenKey ?? version;
  const isNew = releases.length > 0 && seen !== marker;
  const v = version.replace(/^v/i, '');

  const openNotes = () => {
    setOpen(true);
    writeStorage(storageKey, marker);
    setSeen(marker);
  };

  return (
    <>
      <button
        ref={cardRef}
        type="button"
        className="build-card"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Version ${v}${live ? '' : ', offline'}${isNew ? ', new release notes' : ''}. Show what's new`}
        disabled={releases.length === 0}
        onClick={openNotes}
      >
        <span className="build-row">
          <span className="build-ver">
            <span aria-hidden="true">v</span>
            <RollingText text={v} />
          </span>
          {isNew ? (
            <span className="build-new" aria-hidden="true">
              <IconSparkle size={10} className="build-spark" />
              New
            </span>
          ) : null}
        </span>
        <span className="build-row">
          <span className="build-line" aria-hidden="true">
            <span className="live-dot" data-off={live ? undefined : ''} /> <b>{live ? 'Live' : 'Offline'}</b>
          </span>
          {subtitle ? (
            <span className="build-sub" aria-hidden="true">
              {subtitle}
            </span>
          ) : null}
        </span>
      </button>
      <ReleaseNotesDialog open={open} onClose={() => setOpen(false)} releases={releases} version={v} anchorRef={cardRef} link={link} />
    </>
  );
}

export interface ReleaseNotesDialogProps {
  open: boolean;
  onClose: () => void;
  releases: readonly ReleaseNote[];
  version?: string | undefined;
  anchorRef?: { current: HTMLElement | null } | undefined;
  /** Most releases to list. Default 5. */
  limit?: number | undefined;
  /** A link in the foot to the full changelog in the docs home. */
  link?: ReleaseNotesLink | undefined;
}

/** The What's new dialog. Anchored beside its card when there is room, centred otherwise. */
export function ReleaseNotesDialog({ open, onClose, releases, version, anchorRef, limit = 5, link }: ReleaseNotesDialogProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const titleId = `${useId()}-title`;
  const [pos, setPos] = useState<CSSProperties>({});
  useModalLayer(open, panelRef, { onEscape: onClose });

  useEffect(() => {
    if (!open) return;
    const a = anchorRef?.current?.getBoundingClientRect();
    const width = Math.min(360, window.innerWidth - 24);
    if (a && a.width > 0 && window.innerWidth > 640) {
      setPos({ left: Math.min(a.right + 10, window.innerWidth - width - 12), bottom: Math.max(12, window.innerHeight - a.bottom), width });
    } else {
      setPos({ left: (window.innerWidth - width) / 2, top: 64, width });
    }
  }, [open, anchorRef]);

  if (!open || !isBrowser) return null;
  const shown = releases.slice(0, limit);
  const more = safeReleaseLink(link);
  return createPortal(
    <>
      <div className="release-scrim" aria-hidden="true" onMouseDown={onClose} />
      <div ref={panelRef} className="release-pop" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} style={pos}>
        <div className="release-head">
          <span className="release-mark hue-tile hue-violet" aria-hidden="true">
            <IconSparkle size={16} />
          </span>
          <div>
            <p className="release-eyebrow">Release notes</p>
            <h2 id={titleId} className="release-title">
              What's new
              {version ? <span className="release-tag">{versionLabel(version)}</span> : null}
            </h2>
          </div>
          <button type="button" className="release-close" aria-label="Close release notes" onClick={onClose}>
            <IconClose size={14} />
          </button>
        </div>
        <div className="release-body">
          {shown.map((release) => {
            const releaseLink = safeReleaseLink(release.link);
            return (
            <section key={`${release.title}-${release.version}-${release.date ?? ''}`} className="release-group" aria-label={`Version ${release.version}`}>
              <h3 className="release-group-title">
                <span>{release.title}</span>
                <span className="release-group-meta">
                  {versionLabel(release.version)}
                  {release.date ? ` | ${release.date}` : null}
                </span>
              </h3>
              <ul className="release-list">
                {release.items.map((raw, i) => {
                  const item = normalise(raw);
                  const meta = item.type ? TYPE_META[item.type] : undefined;
                  return (
                    <li key={`${i}-${item.title}`} className="release-item" style={{ '--i': i } as CSSProperties}>
                      {meta ? (
                        <span className={`release-icon hue-tile hue-${meta.hue}`} aria-hidden="true">
                          {meta.mark}
                        </span>
                      ) : null}
                      <span>
                        <span className="release-item-title">
                          {meta ? <span className="kit-sr-only">{meta.label}: </span> : null}
                          {item.title}
                        </span>
                        {item.detail ? <span className="release-item-detail">{item.detail}</span> : null}
                      </span>
                    </li>
                  );
                })}
              </ul>
              {releaseLink ? (
                <a className="release-link release-group-link" href={releaseLink.href} target="_blank" rel="noopener noreferrer">
                  {releaseLink.label}
                </a>
              ) : null}
            </section>
            );
          })}
        </div>
        <div className="release-foot">
          <span>Generated from the change history</span>
          {more ? (
            <a className="release-link" href={more.href} target="_blank" rel="noopener noreferrer">
              {more.label}
            </a>
          ) : (
            <span>
              {releases.length} release{releases.length === 1 ? '' : 's'}
            </span>
          )}
        </div>
      </div>
    </>,
    document.body,
  );
}
