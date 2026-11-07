// Types for shell-packages/home-pins.
export const MAX_PINS: number;
export interface Pin { moduleId: string; route: string; label: string }
export interface DeclaringModule { id: string; pages?: ReadonlyArray<{ route: string }> }
export function declaredRoutes(modules: ReadonlyArray<DeclaringModule>): Map<string, Set<string>>;
export function validatePin(body: unknown, routes: Map<string, Set<string>>): { pin: Pin } | { error: string };
export interface HomePinRoutesOptions {
  db: { query: (text: string, params?: unknown[]) => Promise<{ rows: any[] }> };
  /** The gate for every route: the permission that shows the Home tab. */
  gate: Function;
  caller: (req: any) => { email?: string | null } | null | undefined;
  /** The manifests the shell loaded: a pin must name one of their declared pages. */
  modules: ReadonlyArray<DeclaringModule>;
  /** The most pins a person keeps (default 12). */
  max?: number;
}
export function homePinRoutes(router: { get: Function; put: Function; delete: Function }, options: HomePinRoutesOptions): void;
