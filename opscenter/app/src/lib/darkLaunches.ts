// Which dark launches are acting. The live variable is the truth (dark_launches.py): a launch is acting while its switch reads
// on, and also while the switch cannot be read but the registry last recorded it as enabled, because an unreadable switch is
// never taken as off. An acting launch is listed under Operations > Automation > Live automation and leaves the Action Center;
// every other launch waits in the Action Center for its dry run and its Enable. Type imports only, so the node test in
// tests/darkLaunches.test.mjs can load this file without React or the data layer.
import type { DarkLaunch } from './data'

export const LIVE_AUTOMATION_PATH = '/operations/automation/live-automation'

export const isActing = (l: Pick<DarkLaunch, 'live' | 'status'>): boolean => l.live === 'on' || (l.live === 'unknown' && l.status === 'enabled')

export function splitLaunches<T extends Pick<DarkLaunch, 'live' | 'status'>>(launches: readonly T[]): { acting: T[]; dark: T[] } {
  return { acting: launches.filter(isActing), dark: launches.filter((l) => !isActing(l)) }
}
