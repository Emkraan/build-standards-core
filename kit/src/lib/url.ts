/* Link URL guard. Every kit component that renders a caller-supplied href passes it through
   safeHref, so a script URL from data (a nav config, a feed item) can never run on click. */

// Bundlers replace process.env.NODE_ENV at build time. Where nothing replaced it, reading it
// throws and the code counts as development.
declare const process: { env: { NODE_ENV?: string | undefined } };

function isProduction(): boolean {
  try {
    return process.env.NODE_ENV === 'production';
  } catch {
    return false;
  }
}

const ALLOWED_SCHEMES = new Set(['http:', 'https:', 'mailto:', 'tel:']);
const SCHEME = /^([a-z][a-z0-9+.-]*):/i;
// C0 controls, DEL and C1 controls. Browsers drop tabs and newlines inside a URL, so
// "java\tscript:" would otherwise slip past a plain prefix test.
const CONTROL = /[\u0000-\u001f\u007f-\u009f]/g;

let warned = false;

/**
 * The URL to render as an href, or undefined when it is not safe. Relative paths, fragments
 * (`#id`), queries and http, https, mailto and tel URLs pass. Anything with another scheme
 * (javascript, data, vbscript, file and the rest) returns undefined, after control characters
 * are stripped, the value is trimmed and the scheme is compared without case. Render the link
 * without an href in that case. Development builds warn once in the console.
 */
export function safeHref(url: string | null | undefined): string | undefined {
  if (typeof url !== 'string') return undefined;
  const clean = url.replace(CONTROL, '').trim();
  if (clean === '') return undefined;
  const scheme = SCHEME.exec(clean);
  if (!scheme || ALLOWED_SCHEMES.has((scheme[1] ?? '').toLowerCase() + ':')) return clean;
  if (!warned && !isProduction() && typeof console !== 'undefined') {
    warned = true;
    console.warn(`kit: blocked a link with an unsafe URL scheme (${(scheme[1] ?? '').toLowerCase()}:). The link renders without an href.`);
  }
  return undefined;
}

/** Test hook: lets the next blocked URL warn again. */
export function resetSafeHrefWarning(): void {
  warned = false;
}
