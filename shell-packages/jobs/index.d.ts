// Types for shell-packages/jobs.
export const ZONE: string;
export const TICK_MS: number;
export const FIRST_TICK_MS: number;
export const CATCH_UP_MS: number;

export interface Db { query(text: string, params?: unknown[]): Promise<{ rows: any[] }> }
export interface JobDef {
  id: string;
  name: string;
  description: string;
  /** HH:MM Eastern time, every day. */
  at: string;
  /** The repository path that sets the time. */
  source: string;
  /** false ships the job off until an admin turns it on (default true). */
  defaultEnabled?: boolean;
  /** Returns a small summary. A non-zero `failed` marks the run as a failure. Never return secrets. */
  run: () => Promise<Record<string, unknown>>;
}
export interface JobView {
  id: string; name: string; description: string; engine: "app"; schedule: string; at: string; zone: string;
  source: string; enabled: boolean; updatedBy: string | null; updatedAt: string | null; lastRunAt: string | null;
  lastStatus: string | null; lastResult: unknown; finishedAt: string | null; nextRunAt: string | null;
}
export interface Scheduler {
  tool: string;
  register(job: JobDef): void;
  list(): Promise<JobView[]>;
  setEnabled(id: string, enabled: boolean, by: string | null, now?: Date): Promise<boolean>;
  claim(job: JobDef, now: Date): Promise<boolean>;
  tick(now?: Date): Promise<string[]>;
  start(): void;
  stop(): void;
  has(id: string): boolean;
}
export interface SchedulerOptions {
  db: Db;
  /** The tool id (lowercase kebab-case). */
  tool: string;
  log?: (msg: string) => void;
  /** The environment variable that stops the runner on an instance when set to "off" (default JOBS). */
  offEnv?: string;
}
export function createScheduler(options: SchedulerOptions): Scheduler;

export interface JobRoutesOptions {
  scheduler: Scheduler;
  read: Function;
  manage: Function;
  canManage: (req: any) => boolean | Promise<boolean>;
  caller: (req: any) => { email: string | null };
  audit: (req: any, action: string, target: string, details: Record<string, unknown>) => Promise<unknown>;
  path?: string;
}
export function jobRoutes(router: { get: Function; put: Function }, options: JobRoutesOptions): void;

export interface AutomationSchedule {
  frequency: "Day" | "Hour" | "Week" | "Month";
  interval?: number;
  timezone: string;
  startTime: string;
  weekDays?: string[];
  monthDays?: number[];
}
export function occurrence(at: string, now: Date, addDays?: number): Date;
export function nextRun(at: string, now?: Date): Date;
export function describeDaily(at: string): string;
export function parseCron(expr: string): { minute: Set<number>; hour: Set<number>; dom: Set<number>; month: Set<number>; dow: Set<number>; domAny: boolean; dowAny: boolean };
export function nextCron(expr: string, now?: Date): Date | null;
export function describeCron(expr: string): string;
export function nextAutomation(schedule: AutomationSchedule, now?: Date): Date | null;
export function describeAutomation(schedule: AutomationSchedule): string;
export function nextScheduled(row: { engine: string; cron?: string[]; automation?: AutomationSchedule }, now?: Date): Date | null;
