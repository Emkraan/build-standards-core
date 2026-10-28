/* Same-origin return targets. A module bounces a signed-out caller to the shell with
   ?returnTo=<path>, and an interactive sign-in carries the page it started from. Both come back
   through the browser, so every target is validated here before anything navigates to it. */

// C0 controls, DEL and C1 controls. Browsers drop tabs and newlines inside a URL, so "/\t/evil"
// would otherwise read as a protocol-relative URL after the browser cleans it.
const CONTROL = /[\u0000-\u001f\u007f-\u009f]/;

/**
 * The same-origin path (pathname, search and hash) a caller may be sent to, or null.
 *
 * Accepts a path ("/example/users?q=1") or an absolute URL on the same origin (the form MSAL
 * records as the start page). Rejects protocol-relative ("//evil.com") and backslash
 * ("/\\evil.com") targets, any control character, anything that resolves to another origin, and
 * the bare shell root unless `allowRoot` is set (forwarding to "/" from "/" would only reload).
 */
export function safeReturnTo(
  value: string | null | undefined,
  origin: string,
  { allowRoot = false }: { allowRoot?: boolean } = {},
): string | null {
  if (typeof value !== 'string') return null;
  const raw = value.trim();
  if (raw === '' || raw.length > 2048 || CONTROL.test(raw)) return null;

  let path = raw;
  if (!raw.startsWith('/')) {
    // An absolute URL is only allowed when it is on this origin.
    let parsed: URL;
    try {
      parsed = new URL(raw);
    } catch {
      return null;
    }
    if (parsed.origin !== origin) return null;
    path = parsed.pathname + parsed.search + parsed.hash;
  }

  if (!path.startsWith('/') || path.startsWith('//') || path.startsWith('/\\')) return null;

  let resolved: URL;
  try {
    resolved = new URL(path, origin);
  } catch {
    return null;
  }
  if (resolved.origin !== origin) return null;
  const out = resolved.pathname + resolved.search + resolved.hash;
  // Dot segments resolve away after the raw check ("/.//evil.com" becomes "//evil.com"), so the
  // resolved path gets the same protocol-relative, backslash and control checks.
  if (!out.startsWith('/') || out.startsWith('//') || out.startsWith('/\\') || CONTROL.test(out)) return null;
  if (!allowRoot && out === '/') return null;
  return out;
}
