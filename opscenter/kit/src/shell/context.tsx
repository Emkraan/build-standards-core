/* Shared state for the app shell: the rail (collapsed, open, pinned), the mobile drawer and the
   link component used for navigation, so the kit stays router-agnostic. */

import { createContext, useContext } from 'react';
import type { AnchorHTMLAttributes, ComponentType, FocusEvent, ReactNode, Ref } from 'react';
import { safeHref } from '../lib/url';

export type RailState = 'collapsed' | 'open' | 'pinned';

/** Props the kit passes to a link. Map `href` to your router's own prop in an adapter. */
export interface KitLinkProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  href: string;
  children?: ReactNode;
}

export type LinkComponent = ComponentType<KitLinkProps>;

/** A plain anchor. An unsafe href (see safeHref) renders an anchor without an href. */
export function DefaultLink({ href, ...rest }: KitLinkProps) {
  return <a {...rest} href={safeHref(href)} />;
}

/**
 * Renders a caller-supplied link through the app's link component. An unsafe href never reaches
 * the router adapter: the link renders as a plain anchor without an href instead.
 */
export function GuardedLink({ Link, href, ...rest }: KitLinkProps & { Link: LinkComponent }) {
  const safe = safeHref(href);
  if (safe === undefined) return <a {...rest} />;
  return <Link {...rest} href={safe} />;
}

export interface RailHandlers {
  onPointerEnter: () => void;
  onPointerLeave: () => void;
  onFocus: () => void;
  onBlur: (event: FocusEvent<HTMLElement>) => void;
}

export interface ShellContextValue {
  rail: RailState;
  pinned: boolean;
  togglePin: () => void;
  railHandlers: RailHandlers;
  mobileOpen: boolean;
  setMobileOpen: (open: boolean) => void;
  sidebarId: string;
  menuButtonRef: Ref<HTMLButtonElement>;
  Link: LinkComponent;
}

export const ShellContext = createContext<ShellContextValue | null>(null);

/** The shell context, or null outside an AppShell (components then fall back to plain links). */
export function useShell(): ShellContextValue | null {
  return useContext(ShellContext);
}
