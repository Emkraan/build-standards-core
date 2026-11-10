/* The API reference: a themed mount of Scalar (@scalar/api-reference-react, an optional peer
   dependency). Scalar renders an OpenAPI document with ready-to-run request samples (curl, Python,
   JavaScript, Go and more) and a built-in try-it client.

   api-reference.css (import once: `kit-core/api-reference.css`) loads the Scalar sheet into the
   kit-vendor layer and maps its --scalar-* variables onto the kit tokens, so the reference follows
   the theme with no theme branch. Scalar also keeps a dark-mode or light-mode class on body for the
   few values it does not expose as variables; this component sets it from the kit theme and hides
   Scalar's own toggle, because the app owns the theme.

   Three ways to supply the document, in priority order:
     1. `content`   a pre-fetched OpenAPI object or string. Use it when the spec endpoint needs
                    auth: Scalar's own fetch sends no auth header, so a bare `url` against a gated
                    endpoint renders an EMPTY reference.
     2. `fetchSpec` an async fetcher (the app's authenticated client), called on mount. A sized
                    placeholder holds the space while it runs, so the tall reference never appears
                    late and shoves the page; a failure shows ErrorState with Retry.
     3. `url`       a spec URL Scalar fetches itself. Unauthenticated specs only.

   The mount makes no third-party request: Scalar's web fonts (the kit fonts are used), telemetry,
   developer toolbar and hosted agent and MCP features are all switched off. */

import { ApiReferenceReact } from '@scalar/api-reference-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ComponentProps } from 'react';
import { cx } from '../lib/env';
import { useColorScheme } from '../lib/media';
import type { ColorScheme } from '../lib/media';
import { ErrorState } from '../primitives/ErrorState';

type ScalarConfiguration = ComponentProps<typeof ApiReferenceReact>['configuration'];

/** A server the try-it client can call. */
export interface ApiReferenceServer {
  url: string;
  description?: string;
}

export interface ApiReferenceProps {
  /** A pre-fetched OpenAPI document (object or JSON or YAML string). */
  content?: unknown;
  /** A fetcher for the spec: the app's authenticated client. Called on mount and on Retry. */
  fetchSpec?: (() => Promise<unknown>) | undefined;
  /** A spec URL for Scalar to fetch itself. Unauthenticated specs only. */
  url?: string | undefined;
  /** The document title Scalar shows and sets in its metadata. */
  title?: string | undefined;
  /** Preselect a security scheme, so a gated API never reads as open. */
  preferredSecurityScheme?: string | undefined;
  /** Hide the download-the-spec button. Default false. */
  hideDownloadButton?: boolean | undefined;
  favicon?: string | undefined;
  /** Override the spec's `servers`, for example the API origin when the app and the API are on
   *  different hosts, so the try-it client calls the API. */
  servers?: ApiReferenceServer[] | undefined;
  /** The outline level the reference's own headings take. Default 2. Scalar renders the spec title
   *  as an h1; inside a page that already has its h1 that would be a second one, so each h1 in the
   *  reference is exposed as a heading of this level. Pass 1 where the reference IS the page. */
  headingLevel?: 1 | 2 | 3 | undefined;
  /** Pin the colour scheme. Default: follow the kit theme. */
  colorScheme?: ColorScheme | undefined;
  className?: string | undefined;
}

/** Shift the whole heading outline under `root` so its h1 sits at `level` and every deeper
 *  heading keeps its place below it (an h2 becomes `level + 1`, capped at 6), via role plus
 *  aria-level. An embedded document then never adds a second top-level heading, nor sections
 *  that outrank its own title. The level comes from the tag, so a repeat run is a no-op.
 *  Returns how many headings it changed. */
export function demoteHeadings(root: ParentNode, level: number): number {
  let changed = 0;
  for (const h of Array.from(root.querySelectorAll('h1, h2, h3, h4, h5, h6'))) {
    const target = String(Math.min(6, Number(h.tagName.slice(1)) + level - 1));
    if (h.getAttribute('aria-level') === target) continue;
    h.setAttribute('role', 'heading');
    h.setAttribute('aria-level', target);
    changed += 1;
  }
  return changed;
}

/** Scalar always renders its document as a main landmark. Inside a page that already has one,
 *  that is a second, nested main, which HTML forbids and which leaves a screen reader two
 *  "main content" stops. There it becomes a region named by Scalar's own label instead: one main
 *  per page, and the reference stays a named landmark. Vue never binds a role on that element, so
 *  the change survives its re-renders. Returns how many it changed. */
export function nestMainLandmarks(root: Element): number {
  if (!root.parentElement?.closest('main, [role="main"]')) return 0;
  let changed = 0;
  for (const m of Array.from(root.querySelectorAll('main:not([role])'))) {
    m.setAttribute('role', 'region');
    changed += 1;
  }
  return changed;
}

/** The Scalar configuration for a resolved document. Exported for tests. */
export function scalarConfiguration(
  spec: unknown,
  props: Pick<
    ApiReferenceProps,
    'url' | 'title' | 'preferredSecurityScheme' | 'hideDownloadButton' | 'favicon' | 'servers'
  >,
  scheme: ColorScheme,
): Record<string, unknown> {
  return {
    theme: 'none',
    darkMode: scheme === 'dark',
    forceDarkModeState: scheme,
    hideDarkModeToggle: true,
    hideDownloadButton: props.hideDownloadButton ?? false,
    withDefaultFonts: false,
    telemetry: false,
    showDeveloperTools: 'never',
    agent: { disabled: true },
    mcp: { disabled: true },
    ...(spec !== undefined ? { content: spec } : props.url ? { url: props.url } : {}),
    ...(props.preferredSecurityScheme
      ? { authentication: { preferredSecurityScheme: props.preferredSecurityScheme } }
      : {}),
    ...(props.title ? { metaData: { title: props.title, ogTitle: props.title } } : {}),
    ...(props.favicon ? { favicon: props.favicon } : {}),
    ...(props.servers?.length ? { servers: props.servers } : {}),
  };
}

export function ApiReference({
  content,
  fetchSpec,
  url,
  title,
  preferredSecurityScheme,
  hideDownloadButton,
  favicon,
  servers,
  headingLevel = 2,
  colorScheme,
  className,
}: ApiReferenceProps) {
  const themeScheme = useColorScheme();
  const scheme = colorScheme ?? themeScheme;
  const [fetched, setFetched] = useState<unknown>(undefined);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const frameRef = useRef<HTMLDivElement | null>(null);

  // Scalar renders client-side and re-renders as the reader navigates, so keep shifting any
  // heading it adds for as long as it is mounted.
  useEffect(() => {
    const root = frameRef.current;
    if (!root) return undefined;
    const settle = () => {
      if (headingLevel !== 1) demoteHeadings(root, headingLevel);
      nestMainLandmarks(root);
    };
    settle();
    if (typeof MutationObserver === 'undefined') return undefined;
    // Only child changes are observed, so the attributes set here never re-trigger it.
    const observer = new MutationObserver(settle);
    observer.observe(root, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [headingLevel, fetched, error]);

  useEffect(() => {
    // Nothing to fetch when the document was supplied, or Scalar fetches the url itself.
    if (content !== undefined || !fetchSpec) return undefined;
    let alive = true;
    setError(null);
    fetchSpec()
      .then((doc) => {
        if (alive) setFetched(doc);
      })
      .catch((e: unknown) => {
        if (alive) setError(e ?? new Error('The API reference could not be loaded.'));
      });
    return () => {
      alive = false;
    };
  }, [content, fetchSpec, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const spec = content !== undefined ? content : fetched;

  // ApiReferenceReact pushes a new configuration into Scalar whenever the object changes, so build
  // it only when an input does.
  const configuration = useMemo(
    () =>
      scalarConfiguration(
        spec,
        { url, title, preferredSecurityScheme, hideDownloadButton, favicon, servers },
        scheme,
      ) as ScalarConfiguration,
    [spec, url, title, preferredSecurityScheme, hideDownloadButton, favicon, servers, scheme],
  );

  if (error) {
    return (
      <div className={cx('kit-api-ref', 'kit-api-ref-error', className)}>
        <ErrorState title="The API reference could not be loaded." error={error} onRetry={retry} />
      </div>
    );
  }

  // Waiting for a fetched document: a sized placeholder, not a spinner. The reference is page-tall,
  // so collapsing to a spinner and then expanding would shift the page.
  if (content === undefined && fetchSpec && fetched === undefined) {
    return (
      <div
        className={cx('kit-api-ref', 'kit-api-ref-loading', className)}
        role="status"
        aria-busy="true"
        aria-label="Loading the API reference"
      />
    );
  }

  return (
    <div ref={frameRef} className={cx('kit-api-ref', className)}>
      <ApiReferenceReact configuration={configuration} />
    </div>
  );
}
