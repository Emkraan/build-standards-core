/* ErrorState: the failure state of a data surface (UI standard section 7). A danger Alert that says the
   read failed, why, and offers Retry. It renders in place of the results, so the page chrome and the
   filters stay mounted and a retry re-runs the same query. */

import type { ReactNode } from 'react';
import { cx } from '../lib/env';
import { Alert } from './Alert';
import { Button } from './Button';

export interface ErrorStateProps {
  /** Heading. Default "Could not load." */
  title?: ReactNode;
  /** The failure. An Error's message, or a string, becomes the detail line. */
  error?: unknown;
  /** Explicit detail line, used instead of the error's message. */
  message?: ReactNode;
  /** Re-run the failed read. Without it no Retry button is shown. */
  onRetry?: (() => void) | undefined;
  /** The retry is in flight: the button shows a spinner and is disabled. */
  retrying?: boolean | undefined;
  /** Retry button label. Default "Retry". */
  retryLabel?: string | undefined;
  className?: string | undefined;
}

/** The detail line for an unknown failure: an Error's message, a string, or nothing. */
export function errorDetail(error: unknown): string | undefined {
  if (error instanceof Error) return error.message || undefined;
  if (typeof error === 'string') return error || undefined;
  return undefined;
}

export function ErrorState({
  title = 'Could not load.',
  error,
  message,
  onRetry,
  retrying = false,
  retryLabel = 'Retry',
  className,
}: ErrorStateProps) {
  const detail = message ?? errorDetail(error);
  return (
    <Alert
      tone="danger"
      title={title}
      className={cx('error-state', className)}
      action={
        onRetry ? (
          <Button size="sm" variant="secondary" onClick={onRetry} loading={retrying}>
            {retryLabel}
          </Button>
        ) : undefined
      }
    >
      {detail}
    </Alert>
  );
}
