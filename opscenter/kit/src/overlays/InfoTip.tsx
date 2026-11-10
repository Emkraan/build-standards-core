/* InfoTip: a small info button beside a label or a field. Hover or focus shows the short text as the
   tip and a click opens a popover with the long text and an optional link, for the one thing too long
   for a tip. */

import { useCallback, useId, useRef, useState } from 'react';
import { IconInfo } from '../icons/icons';
import { cx, devWarn } from '../lib/env';
import { glossaryEntry, useGlossary } from '../primitives/Glossary';
import { HelpLink } from '../primitives/HelpLink';
import type { TipSide } from '../primitives/Tooltip';
import { Popover } from './Popover';
import type { Placement } from './Popover';

export interface InfoTipProps {
  /** A glossary id. Fills `short`, `long`, `href` and the name from the entry, and anything passed here wins. */
  id?: string | undefined;
  /** The tip: one or two short plain sentences. */
  short?: string | undefined;
  /** The longer text in the popover. Default: `short`. */
  long?: string | undefined;
  /** Documentation address shown as a link in the popover. */
  href?: string | undefined;
  hrefLabel?: string | undefined;
  /** The button's accessible name. Default: "About <term>" for a glossary entry, else "More information". */
  label?: string | undefined;
  tipSide?: TipSide | undefined;
  placement?: Placement | undefined;
  className?: string | undefined;
}

export function InfoTip({ id, short, long, href, hrefLabel = 'Learn more', label, tipSide, placement = 'bottom-start', className }: InfoTipProps) {
  const glossary = useGlossary();
  const entry = id === undefined ? undefined : glossaryEntry(glossary, id);
  const anchorRef = useRef<HTMLButtonElement | null>(null);
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);

  const shortText = short ?? entry?.short ?? '';
  const longText = long ?? entry?.long ?? shortText;
  const link = href ?? entry?.href;
  const name = label ?? (entry ? `About ${entry.term}` : 'More information');
  if (!shortText && !longText) {
    devWarn(`infotip:${id ?? ''}`, `<InfoTip${id ? ` id="${id}"` : ''}> has no text to show. Pass short or long, or a glossary id that is registered.`);
    return null;
  }
  return (
    <>
      <button
        ref={anchorRef}
        type="button"
        className={cx('info-tip', className)}
        aria-label={name}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        data-tip={shortText}
        data-tip-side={tipSide}
        onClick={() => setOpen((v) => !v)}
      >
        <IconInfo size={14} />
      </button>
      <Popover open={open} onClose={close} anchorRef={anchorRef} label={name} id={panelId} placement={placement} className="info-tip-panel">
        <div className="info-tip-body">
          <p className="info-tip-text">{longText}</p>
          {link ? (
            <p className="info-tip-more">
              <HelpLink href={link}>{hrefLabel}</HelpLink>
            </p>
          ) : null}
        </div>
      </Popover>
    </>
  );
}
