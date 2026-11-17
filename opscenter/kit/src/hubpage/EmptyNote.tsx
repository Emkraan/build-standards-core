/* EmptyNote: the compact empty state, one line with a check icon, for the inside of a Section or a
   Panel. The large illustrated EmptyState is only for a page or tab that has nothing at all. */

import type { ReactNode } from 'react';
import { IconCheck } from '../icons/icons';

export interface EmptyNoteProps {
  title: string;
  body?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}

export function EmptyNote({ title, body, action, icon }: EmptyNoteProps) {
  return (
    <p className="hp-empty" role="status">
      <span className="hp-empty-icon" aria-hidden="true">
        {icon ?? <IconCheck size={14} />}
      </span>
      <span className="hp-empty-text">
        {title}
        {body ? <span className="hp-empty-body"> {body}</span> : null}
      </span>
      {action ? <span className="hp-empty-action">{action}</span> : null}
    </p>
  );
}
