// The active builds panel: agent work that is running, stuck, failed or finished, read from the consumer's own feed (GET api/active-builds).
// The feed is a provider slot, so a 404 means the consumer has none and the panel is hidden. The decisions are here so a test can load them
// without the browser (issue 308, items 7 and 26). Read only on purpose: a Stop action is a separate decision with its own confirmation.

export type BuildState = 'running' | 'stuck' | 'failed' | 'finished'

export interface ActiveBuild {
  id: string
  title: string
  state: string
  started: number | null
  finished: number | null
  activity: string | null
  activity_at: number | null
  outcome: string | null
  url: string | null
  kind: string | null
}

export interface ActiveBuildsFeed {
  fetched_utc: string
  counts: { running: number; stuck: number; failed: number; finished: number; total: number }
  builds: ActiveBuild[]
  truncated: number
  error: string | null
}

export type ActiveBuildsState = { configured: false } | ({ configured: true } & ActiveBuildsFeed)

/** What the panel does: stay hidden (no provider), say the source failed, or list what it has. */
export type PanelMode = 'hidden' | 'error' | 'list' | 'quiet'

export function panelMode(s: ActiveBuildsState | null | undefined): PanelMode {
  if (!s || !s.configured) return 'hidden'
  if (s.error) return 'error'
  // Nothing running, stuck or failed is a real answer worth one calm line, but finished history alone is not worth a panel.
  const live = s.counts.running + s.counts.stuck + s.counts.failed
  return live > 0 ? 'list' : 'quiet'
}

const STATE_WORD: Record<string, string> = { running: 'Running', stuck: 'Stuck', failed: 'Failed', finished: 'Finished' }

/** A state as a word. An unknown state is shown as the provider sent it, capitalised, never hidden and never called running. */
export function stateWord(state: string): string {
  return STATE_WORD[state] ?? (state ? state[0].toUpperCase() + state.slice(1) : 'Unknown')
}

/** Rows to draw: what needs a look first (stuck, then failed), then running, then finished, each keeping the feed's newest first order. */
export function orderedBuilds(builds: ActiveBuild[]): ActiveBuild[] {
  const rank = (s: string) => ({ stuck: 0, failed: 1, running: 2, finished: 3 })[s] ?? 4
  return builds.map((b, i) => ({ b, i })).sort((x, y) => rank(x.b.state) - rank(y.b.state) || x.i - y.i).map((x) => x.b)
}

/** How long ago, from epoch seconds. A missing time is an empty string and never a made up age. */
export function ageText(thenSeconds: number | null, nowSeconds: number): string {
  if (thenSeconds === null) return ''
  const s = Math.max(0, Math.round(nowSeconds - thenSeconds))
  if (s < 60) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 48) return `${h} h ago`
  return `${Math.round(h / 24)} d ago`
}

/** The age that matters for a row: a running or stuck build is judged by its last output, a finished one by when it ended. */
export function rowAge(b: ActiveBuild, nowSeconds: number): string {
  const at = b.state === 'finished' || b.state === 'failed' ? (b.finished ?? b.activity_at ?? b.started) : (b.activity_at ?? b.started)
  return ageText(at, nowSeconds)
}

/** The heading's summary, for example "1 stuck, 2 running". A zero is left out, so a calm board is an empty string. */
export function summaryLine(c: ActiveBuildsFeed['counts']): string {
  return (['stuck', 'failed', 'running'] as const)
    .filter((k) => c[k] > 0)
    .map((k) => `${c[k]} ${k}`)
    .join(', ')
}

/** A link is drawn only when it is an http or https address. The server already filters, and this keeps a bad row from ever becoming a link. */
export function safeLink(url: string | null): string | null {
  return url !== null && /^https?:\/\//.test(url) ? url : null
}
