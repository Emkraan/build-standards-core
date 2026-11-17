/* Section: every content block that has a heading. One title case heading (one size, one weight), a
   small accent marker, an optional count Badge, an optional one line description, optional right
   actions and an optional collapse. Never an upper case eyebrow on a page: the rail keeps its group
   labels. The marker wears the hub accent unless a state tone is given. */

import { useId, useState } from 'react';
import type { ReactNode } from 'react';
import { IconChevronDown } from '../icons/icons';
import { cx } from '../lib/env';
import { Badge } from '../primitives/marks';
import type { StatusTone } from '../primitives/marks';

export interface SectionProps {
  /** Text, or a node when the heading itself links. */
  title: ReactNode;
  count?: number | undefined;
  countTone?: StatusTone | undefined;
  description?: ReactNode;
  actions?: ReactNode;
  /** Makes the heading a disclosure. `open` is the starting state. */
  collapsible?: boolean | undefined;
  open?: boolean | undefined;
  /** A state tone for the marker (strengths, watch, blocked). The default marker is the hub accent. */
  tone?: StatusTone | undefined;
  id?: string | undefined;
  className?: string | undefined;
  children?: ReactNode;
}

export function Section({ title, count, countTone, description, actions, collapsible, open = true, tone, id, className, children }: SectionProps) {
  const [shown, setShown] = useState(open);
  const body = useId();
  const head = (
    <>
      <span className="hp-section-mark" data-tone={tone} aria-hidden="true" />
      <h2 className="hp-section-title">{title}</h2>
      {count !== undefined ? <Badge tone={countTone ?? 'neutral'}>{count}</Badge> : null}
    </>
  );
  return (
    <section className={cx('hp-section', className)} id={id} aria-label={typeof title === 'string' ? title : undefined}>
      <div className="hp-section-head">
        {collapsible ? (
          <button type="button" className="hp-section-toggle" aria-expanded={shown} aria-controls={body} onClick={() => setShown((s) => !s)}>
            {head}
            <span className="hp-section-chev" data-open={shown ? '' : undefined} aria-hidden="true">
              <IconChevronDown size={14} />
            </span>
          </button>
        ) : (
          <div className="hp-section-lead">{head}</div>
        )}
        {actions ? <div className="hp-section-actions">{actions}</div> : null}
      </div>
      {description ? <p className="hp-section-desc">{description}</p> : null}
      {!collapsible || shown ? (
        <div className="hp-section-body" id={body}>
          {children}
        </div>
      ) : null}
    </section>
  );
}
