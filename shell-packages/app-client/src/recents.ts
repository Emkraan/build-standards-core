/* Recent pages, kept in this browser for this account. Client side only: nothing here reaches a server. A recent
   is a page the person opened in any hosted tool: { moduleId, route, label, at }. Newest first, one entry per
   page, at most `max`, and the key carries the account so two people on one browser never see each other's
   trail. Sign-out and an account change drop it. A page the shell no longer declares is filtered out when it is
   read (a stale entry never becomes a dead link). Display only: the target page still enforces its own access. */

export interface Recent {
  moduleId: string;
  route: string;
  label: string;
  at: number;
}

export interface RecentsOptions {
  /** The key prefix, one per app (for example "demo:recent:v1:"). The account id is appended. */
  keyPrefix: string;
  /** The signed-in account id, or null before sign-in (stored as "anon"). */
  accountId: () => string | null | undefined;
  /** Where to keep it. Default window.localStorage. */
  storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> | undefined;
  /** Most entries kept. Default 8. */
  max?: number;
  /** Pages that are never a recent (the Home page itself). */
  skip?: (page: { moduleId: string; route: string }) => boolean;
}

export interface Recents {
  /** Newest first. `declared` drops entries for pages the shell no longer declares. */
  read: (declared?: (page: { moduleId: string; route: string }) => boolean) => Recent[];
  record: (page: { moduleId: string; route: string; label: string }, at?: number) => void;
  clear: () => void;
}

const LABEL_MAX = 60;

export function createRecents(options: RecentsOptions): Recents {
  const max = options.max ?? 8;
  const key = () => `${options.keyPrefix}${options.accountId() || 'anon'}`;
  const store = () => {
    try {
      return options.storage ?? window.localStorage;
    } catch {
      return null;
    }
  };

  const read: Recents['read'] = (declared) => {
    try {
      const raw = store()?.getItem(key());
      const list: unknown = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(list)) return [];
      return list
        .filter(
          (r): r is Recent =>
            !!r &&
            typeof r.moduleId === 'string' &&
            typeof r.route === 'string' &&
            typeof r.label === 'string' &&
            Number.isFinite(r.at) &&
            (!declared || declared(r)),
        )
        .slice(0, max);
    } catch {
      return [];
    }
  };

  return {
    read,
    record(page, at = Date.now()) {
      if (!page.moduleId || !page.route || !page.label) return;
      if (options.skip?.(page)) return;
      const rest = read().filter((r) => !(r.moduleId === page.moduleId && r.route === page.route));
      const next = [{ moduleId: page.moduleId, route: page.route, label: page.label.slice(0, LABEL_MAX), at }, ...rest].slice(0, max);
      try {
        store()?.setItem(key(), JSON.stringify(next));
      } catch {
        /* storage full or off */
      }
    },
    clear() {
      try {
        store()?.removeItem(key());
      } catch {
        /* storage off */
      }
    },
  };
}
