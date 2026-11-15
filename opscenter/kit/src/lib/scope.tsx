/* App scope for the kit's per-app storage keys. Apps that share an origin wrap the tree in
   <StorageScope appId="..."> (AppShell does it when it gets an appId), and the build card and the
   announcements then read and write keys of their own. */

import { createContext, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';
import { storageKeys } from './env';
import type { StorageKeys } from './env';

const StorageScopeContext = createContext<string | null>(null);

export interface StorageScopeProps {
  /** Short stable id of the app, for example its route segment. Empty keeps the shared keys. */
  appId?: string | null | undefined;
  children?: ReactNode;
}

export function StorageScope({ appId, children }: StorageScopeProps) {
  return <StorageScopeContext.Provider value={appId ?? null}>{children}</StorageScopeContext.Provider>;
}

/** The app id of the nearest StorageScope, or null. */
export function useStorageScope(): string | null {
  return useContext(StorageScopeContext);
}

/** The kit storage keys for the current app scope. */
export function useStorageKeys(): StorageKeys {
  const appId = useStorageScope();
  return useMemo(() => storageKeys(appId), [appId]);
}
