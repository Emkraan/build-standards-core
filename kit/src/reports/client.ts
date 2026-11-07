/* A small typed client for the reports module routes, so an app does not write the same fetch code again. Opt in: an app
   that has its own client does not use it. It speaks the module's envelope `{ success, data, message }`, sends the
   same-origin credentials, and turns any failure into an Error with the server's message. The base path is the app's. */

import type { DashboardDefinition, DashboardRow, DashboardRun } from './types';

interface Envelope<T> {
  success?: boolean;
  data?: T;
  message?: string;
  error?: string;
}

export interface RunRequest {
  /** A saved dashboard by key, or a definition to preview. */
  key?: string | undefined;
  def?: DashboardDefinition | undefined;
  range: string;
  /** Filter picks by filter id. */
  selections: Readonly<Record<string, string>>;
}

export interface ImportResult {
  created: number;
  updated: number;
  errors: string[];
}

export interface ReportsClientOptions {
  /** Where the module's routes live, for example `/api/reports/dashboards`. */
  base: string;
  fetch?: typeof fetch | undefined;
}

export function createDashboardsClient({ base, fetch: f }: ReportsClientOptions) {
  const root = base.replace(/\/+$/, '');
  async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await (f ?? fetch)(`${root}${path}`, {
      method,
      credentials: 'same-origin',
      ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
    });
    const json = (await res.json().catch(() => ({}))) as Envelope<T>;
    if (!res.ok || json.success === false) throw new Error(json.message ?? json.error ?? `Request failed (${res.status})`);
    return json.data as T;
  }
  const seg = encodeURIComponent;
  return {
    list: () => call<DashboardRow[]>('GET', ''),
    create: (def: DashboardDefinition) => call<DashboardRow>('POST', '', def),
    save: (key: string, def: DashboardDefinition) => call<DashboardRow>('PUT', `/${seg(key)}`, def),
    remove: (key: string) => call<void>('DELETE', `/${seg(key)}`),
    reset: (key: string) => call<DashboardRow>('POST', `/${seg(key)}/reset`, {}),
    exportAll: () => call<DashboardDefinition[]>('GET', '/export'),
    importAll: (dashboards: readonly DashboardDefinition[]) => call<ImportResult>('POST', '/import', { dashboards }),
    run: (req: RunRequest) => call<DashboardRun>('POST', '/run', req),
  };
}

export type DashboardsClient = ReturnType<typeof createDashboardsClient>;
