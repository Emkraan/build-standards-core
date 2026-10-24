/* ErrorBoundary: the crash screen the UI standard requires. A render-time crash anywhere below it would
   otherwise leave a blank page; this catches it, logs it (never swallowed) and shows a recoverable
   screen. The default `app` variant is the full screen crash with Reload and a Reset session escape
   that clears local and session storage: mount it once at the app root. The `page` variant keeps the
   crash inside the page (the shell and navigation stay usable) and clears itself when `resetKey`
   changes, so a host keys it by the route and moving to another page recovers. Pass `fallback` to
   render your own screen, or `onError` to report the crash. */

import { Component, type ErrorInfo, type ReactNode } from 'react';
import { IconAlert } from '../icons/icons';
import { Button } from '../primitives/Button';

export interface ErrorBoundaryProps {
  children: ReactNode;
  /** Replaces the default crash screen. Receives the error and a reset that retries the render. */
  fallback?: ((error: Error, reset: () => void) => ReactNode) | undefined;
  /** Called once per caught crash, for error reporting. */
  onError?: ((error: Error, info: ErrorInfo) => void) | undefined;
  /** Where Reset session sends the user after clearing storage. Defaults to "/". */
  homeHref?: string | undefined;
  /** `app` (default) is the full screen crash with Reload and Reset session. `page` is an inline
      panel that keeps the shell usable, with Try again and the stack in a closed disclosure. */
  variant?: 'app' | 'page' | undefined;
  /** When this value changes (compared with Object.is, an array element by element) a shown crash
      clears and the children render again. Key it by the route: moving to another page recovers. */
  resetKey?: unknown;
}

/** Marks a crash whose render has not yet reported the resetKey it failed under. */
const UNSET = Symbol('unset');

interface ErrorBoundaryState {
  error: Error | null;
  /** The resetKey in force when the crash was caught. */
  errorKey: unknown;
}

/** True when two reset keys differ: Object.is, or element by element for two arrays. */
export function resetKeyChanged(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) && Array.isArray(b)) return a.length !== b.length || a.some((item, i) => !Object.is(item, b[i]));
  return !Object.is(a, b);
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null, errorKey: UNSET };

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { error, errorKey: UNSET };
  }

  static getDerivedStateFromProps(props: ErrorBoundaryProps, state: ErrorBoundaryState): Partial<ErrorBoundaryState> | null {
    // Clear in the same render the key changes in, so the new page never paints the old crash.
    if (state.error && state.errorKey !== UNSET && resetKeyChanged(state.errorKey, props.resetKey)) {
      return { error: null, errorKey: UNSET };
    }
    return null;
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[ErrorBoundary] render crash:', error, info.componentStack);
    // Remember which key the crash happened under: a crash caused by a new key must not clear itself.
    this.setState({ errorKey: this.props.resetKey });
    this.props.onError?.(error, info);
  }

  reset = (): void => {
    this.setState({ error: null, errorKey: UNSET });
  };

  resetSession = (): void => {
    try {
      localStorage.clear();
      sessionStorage.clear();
    } catch {
      /* storage can be unavailable (private mode, blocked): the navigation below still helps */
    }
    window.location.href = this.props.homeHref ?? '/';
  };

  override render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    if (this.props.fallback) return this.props.fallback(error, this.reset);
    if (this.props.variant === 'page') {
      return (
        <section className="page-crash" role="alert" aria-label="Page error">
          <div className="page-crash-head">
            <span className="empty-icon crash-icon" aria-hidden="true">
              <IconAlert size={18} />
            </span>
            <div className="page-crash-text">
              <h2 className="page-crash-title">
                This page hit an error
              </h2>
              <p className="page-crash-body">The rest of the app is unaffected. Try again, or move to another page.</p>
            </div>
            <Button variant="secondary" size="sm" onClick={this.reset}>
              Try again
            </Button>
          </div>
          <details className="page-crash-details">
            <summary>Technical details</summary>
            <pre className="page-crash-stack">{error.stack || error.message}</pre>
          </details>
        </section>
      );
    }
    return (
      <main className="crash-screen" role="alert">
        <div className="empty-icon crash-icon" aria-hidden="true">
          <IconAlert size={22} />
        </div>
        <h1 className="crash-title">Something went wrong</h1>
        <p className="crash-body">
          The app hit an unexpected error. Reloading usually fixes it. If it persists, reset the session and sign in again.
        </p>
        <div className="crash-actions">
          <button type="button" className="btn" data-variant="primary" data-size="md" onClick={() => window.location.reload()}>
            Reload
          </button>
          <button type="button" className="btn" data-variant="secondary" data-size="md" onClick={this.resetSession}>
            Reset session
          </button>
        </div>
      </main>
    );
  }
}

export interface PageErrorBoundaryProps extends Omit<ErrorBoundaryProps, 'variant' | 'resetKey' | 'homeHref'> {
  /** Required: key it by the current route, so moving to another page clears the crash. */
  resetKey: unknown;
}

/** The page scoped boundary: an ErrorBoundary with the `page` variant and a required resetKey.
    Mount it around the routed page, inside the shell, never around the shell. */
export function PageErrorBoundary(props: PageErrorBoundaryProps) {
  return <ErrorBoundary {...props} variant="page" />;
}
