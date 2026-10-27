/* Stepper: the steps of a process, top to bottom, each with its state. Use it for a flow a person
   follows or waits on (enrol a host, approve a request, roll out a change). The state shows as the
   marker's shape and as hidden text, never as colour alone. A step can carry a "waiting on" line (who or
   what the process needs next) and its own actions. */

import type { ReactNode } from 'react';
import { IconCheck, IconClock, IconClose } from '../icons/icons';
import { cx } from '../lib/env';

export type StepState = 'done' | 'current' | 'upcoming' | 'failed' | 'waiting';

export interface StepItem {
  id: string;
  title: ReactNode;
  state: StepState;
  /** One line under the title: what happened, or what will. */
  detail?: ReactNode;
  /** Beside the title: a time (<When>), a duration or an owner. */
  meta?: ReactNode;
  /** Who or what the step needs next, shown as "Waiting on <waitingOn>". */
  waitingOn?: ReactNode;
  /** Buttons for this step (Retry, Approve, View log). Put them in a Button group, not a bare string. */
  actions?: ReactNode;
}

export const STEP_STATE_LABELS: Readonly<Record<StepState, string>> = {
  done: 'Done',
  current: 'In progress',
  upcoming: 'Not started',
  failed: 'Failed',
  waiting: 'Waiting',
};

export interface StepperProps {
  steps: readonly StepItem[];
  /** Accessible name of the list, for example "Enrolment progress". */
  label?: string | undefined;
  /** Hidden text read before each title. Override to translate, or to say it in the domain's words. */
  stateLabels?: Partial<Record<StepState, string>> | undefined;
  /** Text before the "waiting on" value. */
  waitingLabel?: string | undefined;
  className?: string | undefined;
}

function Marker({ state }: { state: StepState }) {
  if (state === 'done') return <IconCheck size={14} />;
  if (state === 'failed') return <IconClose size={14} />;
  if (state === 'waiting') return <IconClock size={14} />;
  if (state === 'current') return <span className="stepper-dot" />;
  return null;
}

export function Stepper({ steps, label, stateLabels, waitingLabel = 'Waiting on', className }: StepperProps) {
  const labels = { ...STEP_STATE_LABELS, ...stateLabels };
  return (
    <ol className={cx('stepper', className)} aria-label={label}>
      {steps.map((step) => (
        <li key={step.id} className="stepper-step" data-state={step.state} aria-current={step.state === 'current' ? 'step' : undefined}>
          <span className="stepper-marker" aria-hidden="true">
            <Marker state={step.state} />
          </span>
          <div className="stepper-body">
            <div className="stepper-head">
              <p className="stepper-title">
                <span className="kit-sr-only">{labels[step.state]}: </span>
                {step.title}
              </p>
              {step.meta ? <span className="stepper-meta">{step.meta}</span> : null}
            </div>
            {step.detail ? <p className="stepper-detail">{step.detail}</p> : null}
            {step.waitingOn ? (
              <p className="stepper-waiting">
                <IconClock size={14} />
                <span className="stepper-waiting-label">{waitingLabel}</span> {step.waitingOn}
              </p>
            ) : null}
            {step.actions ? <div className="stepper-actions">{step.actions}</div> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
