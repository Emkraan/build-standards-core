/* AccountMenu: the signed-in account at the foot of the rail (the Rail footer). A trigger with the
   avatar, the name and the role or email opens a panel with who the person is, the facts the host
   supplies (how access was granted, when they were last seen), the theme choice, the host's account
   links and Sign out. Everything is plain data. The kit never reads an identity from anywhere. */

import { useId, useRef, useState } from 'react';
import type { ReactElement, ReactNode } from 'react';
import { IconChevronDown, IconExternal, IconLogOut } from '../icons/icons';
import { cx } from '../lib/env';
import { safeHref } from '../lib/url';
import { Popover } from '../overlays/Popover';
import type { Placement } from '../overlays/Popover';
import { Button } from '../primitives/Button';
import { Avatar } from '../primitives/Avatar';
import { Segmented } from '../primitives/Tabs';
import { useTheme } from '../theme/theme';
import type { ThemeChoice } from '../theme/theme';

/** The person the menu is about. Every field is optional except that a name or an email is needed. */
export interface AccountIdentity {
  name?: string | undefined;
  email?: string | undefined;
  /** Shown under the name in the trigger. The email shows when there is no role. */
  role?: string | undefined;
  /** Photo URL. Initials show when omitted. */
  photo?: string | undefined;
}

/** One labelled line in the panel, for example `Access` and `Via a group`. Plain text, never markup. */
export interface AccountFact {
  label: string;
  value: string;
  /** Tooltip with more detail. */
  title?: string | undefined;
  /** Render the value in the monospace face (an email address, an id). */
  mono?: boolean | undefined;
}

/** A link in the panel. It opens in a new tab and passes through `safeHref`. */
export interface AccountLink {
  key: string;
  label: string;
  href: string;
}

/** An action button in the panel, above Sign out (for example "Refresh permissions"). */
export interface AccountAction {
  key: string;
  label: string;
  /** Runs on click. The panel stays open, so the host can report the result through `status`. */
  onSelect: () => Promise<unknown> | void;
  /** Shows the button as working and blocks a second click. */
  busy?: boolean | undefined;
  /** `danger` for a destructive action. Default neutral. */
  tone?: 'neutral' | 'danger' | undefined;
  /** Leading icon, decorative. */
  icon?: ReactNode;
}

const THEME_OPTIONS: readonly { value: ThemeChoice; label: string }[] = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'System' },
];

/** The name to show: the name when it is not just the email, else the part of the email before @. */
export function accountDisplayName({ name, email }: AccountIdentity): string {
  const n = (name ?? '').trim();
  const e = (email ?? '').trim();
  if (n && n !== e) return n;
  if (e) return e.split('@')[0] ?? e;
  return n;
}

export interface AccountMenuProps {
  identity: AccountIdentity | null | undefined;
  /** Extra lines under the email and role (access, last seen). */
  facts?: readonly AccountFact[] | undefined;
  links?: readonly AccountLink[] | undefined;
  /** Action buttons shown above Sign out. Default none. */
  actions?: readonly AccountAction[] | undefined;
  /** A status line for the actions (for example "Permissions refreshed"), announced politely. Pass
      it whenever the panel has actions, even as an empty string, so the live region exists before
      its text changes. Default none. */
  status?: ReactNode;
  /** Runs on Sign out. Leave it out to show no Sign out button. A rejected promise shows an inline
      error and keeps the panel open. */
  onSignOut?: (() => Promise<unknown> | void) | undefined;
  /** Shows the Light, Dark and System choice. Needs a ThemeProvider above. Default true. */
  showTheme?: boolean | undefined;
  placement?: Placement | undefined;
  label?: string | undefined;
  themeLabel?: string | undefined;
  signOutLabel?: string | undefined;
  signOutFailedText?: string | undefined;
  className?: string | undefined;
}

function ThemeChoiceRow({ label }: { label: string }) {
  const { choice, setChoice } = useTheme();
  return (
    <div className="account-theme">
      <span className="account-eyebrow">{label}</span>
      <Segmented label={label} options={THEME_OPTIONS} value={choice} onChange={(v) => setChoice(v)} full />
    </div>
  );
}

export function AccountMenu({
  identity,
  facts = [],
  links = [],
  actions = [],
  status,
  onSignOut,
  showTheme = true,
  placement = 'top-start',
  label = 'Account',
  themeLabel = 'Theme',
  signOutLabel = 'Sign out',
  signOutFailedText = 'Could not sign out. Try again.',
  className,
}: AccountMenuProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const anchorRef = useRef<HTMLButtonElement | null>(null);
  const panelId = useId();
  if (!identity || (!identity.name && !identity.email)) return null;
  const displayName = accountDisplayName(identity);
  const sub = identity.role || identity.email;
  const lines: AccountFact[] = [
    ...(identity.email ? [{ label: 'Email', value: identity.email, mono: true }] : []),
    ...(identity.role ? [{ label: 'Role', value: identity.role }] : []),
    ...facts,
  ];

  const signOut = async () => {
    if (!onSignOut || busy) return;
    setBusy(true);
    setFailed(false);
    try {
      await onSignOut();
      setOpen(false);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={cx('account', className)}>
      <button
        ref={anchorRef}
        type="button"
        className="account-trigger"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        aria-label={`${label}: ${displayName}`}
        onClick={() => setOpen((v) => !v)}
      >
        <Avatar name={displayName || identity.email || '?'} src={identity.photo || undefined} size="sm" />
        <span className="account-label">
          <span className="account-name">{displayName}</span>
          {sub ? <span className="account-sub">{sub}</span> : null}
        </span>
        <IconChevronDown size={14} className="account-chevron" />
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchorRef={anchorRef} placement={placement} label={label} className="account-pop" id={panelId}>
        <dl className="account-facts">
          {lines.map((fact) => (
            <FactRow key={fact.label} fact={fact} />
          ))}
        </dl>
        {showTheme ? <ThemeChoiceRow label={themeLabel} /> : null}
        {links.length > 0 ? (
          <ul className="account-links">
            {links.map((link) => {
              const href = safeHref(link.href);
              return (
                <li key={link.key}>
                  <a href={href} target="_blank" rel="noopener noreferrer" className="account-link">
                    <IconExternal size={14} /> {link.label}
                  </a>
                </li>
              );
            })}
          </ul>
        ) : null}
        {actions.length > 0 || status !== undefined ? (
          <div className="account-actions">
            {actions.map((action) => (
              <Button
                key={action.key}
                variant={action.tone === 'danger' ? 'danger-subtle' : 'ghost'}
                size="sm"
                icon={action.icon}
                loading={action.busy}
                onClick={() => {
                  if (!action.busy) void action.onSelect();
                }}
              >
                {action.label}
              </Button>
            ))}
            {status !== undefined ? (
              <p className="account-status" aria-live="polite">
                {status}
              </p>
            ) : null}
          </div>
        ) : null}
        {onSignOut ? (
          <div className="account-foot">
            {failed ? (
              <p className="account-error" role="alert">
                {signOutFailedText}
              </p>
            ) : null}
            <Button variant="ghost" size="sm" icon={<IconLogOut size={14} />} loading={busy} onClick={signOut}>
              {signOutLabel}
            </Button>
          </div>
        ) : null}
      </Popover>
    </div>
  );
}

function FactRow({ fact }: { fact: AccountFact }): ReactElement {
  return (
    <>
      <dt>{fact.label}</dt>
      <dd className={fact.mono ? 'account-mono' : undefined} title={fact.title}>
        {fact.value}
      </dd>
    </>
  );
}
