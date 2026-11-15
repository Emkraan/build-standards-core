/* KeepRedirect: a redirect for a moved route that keeps the query string and hash (layout standard rule 9, "old
   links never break"), so a tab filter or an anchor on a bookmarked link survives the move. Router free: the app
   passes the place it is at (its router's location) and goes to the target in `onRedirect`. `redirectTarget` is
   the same rule as a plain function for an app that redirects in a route loader. Only a path on the same site
   is a target: a scheme, a protocol relative `//host` or a backslash form is refused and the redirect does
   nothing, so a redirect built from data can never leave the site. */

import { useEffect } from 'react';
import { isBrowser } from '../lib/env';

/** The part of a location that survives a redirect. */
export interface RedirectCarry {
  search?: string | undefined;
  hash?: string | undefined;
}

const SAFE_PATH = /^\/(?![/\\])[^\u0000-\u001f\u007f-\u009f]*$/;

/**
 * `to` with the query string and hash of the old location added. A parameter `to` already has wins over the same
 * parameter in the old query; a hash on `to` wins over the old one. Returns null when `to` is not a path on this site.
 */
export function redirectTarget(to: string, carry: RedirectCarry = {}): string | null {
  if (!SAFE_PATH.test(to)) return null;
  const hashAt = to.indexOf('#');
  const noHash = hashAt >= 0 ? to.slice(0, hashAt) : to;
  const ownHash = hashAt >= 0 ? to.slice(hashAt) : '';
  const qAt = noHash.indexOf('?');
  const path = qAt >= 0 ? noHash.slice(0, qAt) : noHash;
  const own = new URLSearchParams(qAt >= 0 ? noHash.slice(qAt + 1) : '');
  const old = new URLSearchParams((carry.search ?? '').replace(/^\?/, ''));
  for (const [k, v] of old) if (!own.has(k)) own.append(k, v);
  const q = own.toString();
  const hash = ownHash || (carry.hash && carry.hash !== '#' ? (carry.hash.startsWith('#') ? carry.hash : `#${carry.hash}`) : '');
  return `${path}${q ? `?${q}` : ''}${hash}`;
}

export interface KeepRedirectProps {
  /** The new home of the route, a path on this site. */
  to: string;
  /** The location being left. Default the browser's own `location`. */
  location?: RedirectCarry | undefined;
  /** Goes to the target with the app's router, replacing the old entry in the history. */
  onRedirect: (target: string) => void;
}

/** Renders nothing and redirects once when it mounts. */
export function KeepRedirect({ to, location, onRedirect }: KeepRedirectProps) {
  useEffect(() => {
    const carry = location ?? (isBrowser ? { search: window.location.search, hash: window.location.hash } : {});
    const target = redirectTarget(to, carry);
    if (target) onRedirect(target);
    // A redirect happens once for the place it was mounted at.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}
