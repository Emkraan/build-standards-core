// Payload shapes of the read-only /api/infra/* feeds (infra.py, llm_accounts.py).

export interface SpendJob {
  id: string
  name: string
  runs_d7: number
  cost_d7: number
  per_run_d7: number
  cost_today: number
  cost_d30: number
  active: boolean
  billed_d7: number
  billed_today: number
  included_d7: number
  unattributed_d7: number
  fallback_runs_d7: number
}
export interface Month {
  month: string
  cron: number
  interactive: number
  total: number
  billed: number
  included: number
  unattributed: number
  sessions: number
  jobs: { id: string; name: string; cost: number; billed: number }[]
}
type Bucket = 'billed' | 'included' | 'unattributed'
type BucketTotals = { [K in `${Bucket}_${'today' | 'd7' | 'mtd'}` | `${'cron' | 'interactive'}_${Bucket}_d7`]: number }
export interface Spend {
  generated_utc: string
  months: Month[]
  totals: {
    today: number
    d7: number
    d30: number
    mtd: number
    cron_d7: number
    interactive_d7: number
    projected_month: number
    billed_rate_per_day: number
    billed_projected_month: number
  } & BucketTotals
  daily: { date: string; cron: number; interactive: number; billed: number; included: number; unattributed: number }[]
  jobs: SpendJob[]
  sessions: number
  estimated_sessions: number
  ledger_since_utc: string | null
  rate_basis_days: number
}
export interface CronJob {
  id: string
  name: string
  schedule: string
  kind: string
  model: string
  last_run_at: string | null
  next_run_at: string | null
  last_status: string | null
  last_error: string
  failure_streak: number
  delivery_error: string
  deliver: string
  runs_total: number | null
  outputs_d7: number
  health: string
  description: string
  category: string
  script: string
  skills: string[]
  workdir: string
  created_at: string | null
  enabled: boolean
  paused_reason: string
  last_failure: unknown
  recent_outputs: { file: string; at: string; bytes: number }[]
}
export interface Cron {
  generated_utc: string
  scheduler_heartbeat_age_s: number | null
  jobs: CronJob[]
}
export interface PR {
  repo: string
  number: number
  title: string
  url: string
  author: string
  draft: boolean
  review: string
  merge_state: string
  branch: string
  updated: string
  checks: { pass: number; fail: number; pending: number; failing: string[] }
}
export interface Run {
  repo: string
  id: number
  workflow: string
  title: string
  status: string
  conclusion: string
  event: string
  branch: string
  created: string
  updated: string
  url: string
}
export interface Github {
  generated_utc: string
  repos: string[]
  errors: Record<string, string>
  prs: PR[]
  runs: Run[]
  red_on_main: Run[]
  in_progress: Run[]
}

export interface FleetJob {
  id: number
  name: string
  workflow: string
  branch: string
  created: string
  url: string
}
export interface Snapshot {
  id: string
  time: string
  files: number
  bytes: number
}
export interface RunnerFleet {
  generated_utc: string
  repo: string
  vm: { name: string; status: string; cpus: number; memory_gib: number; disk_gib: number } | null
  runners: { name: string; status: string; busy: boolean; labels: string[] }[]
  queued: FleetJob[]
  running: FleetJob[]
  minutes: { hosted_used: number; included: number } | null
  backup: {
    status: string
    message: string
    checked_utc: string
    latest: Snapshot | Record<string, never>
    drill?: { result: string; detail: string; ran_utc: string }
  } | null
  errors: string[]
  links: { actions: string; runners: string; pulls: string }
}

export interface AccountLimit {
  kind: string
  group: string
  label: string
  percent: number
  severity: string
  resets_at: string | null
  is_active: boolean
}
export interface TokenWindow {
  calls: number
  input: number
  output: number
  cache_read: number
  cache_write: number
  total: number
}
export interface LlmAccount {
  credential: string
  priority: number
  kind: string | null
  kind_label: string
  org: string | null
  seat_tier: string | null
  rate_limit_tier: string | null
  limits: AccountLimit[]
  spend: {
    enabled: boolean
    used_usd: number
    limit_usd: number | null
    percent: number
    severity: string
    spend_limit_reached: boolean
  } | null
  pool_status: string | null
  pool_error: string | null
  pool_reset_at: string | null
  cooling_down: boolean
  routing: boolean
  fetched_utc: string | null
  error: string | null
  stale?: string | null
  tokens?: Record<string, TokenWindow>
  spend_history?: {
    since_utc: string | null
    daily: { date: string; usd: number; partial: boolean; total: number }[]
    rate_per_day: number | null
    rate_basis_days: number
  }
}
export interface LlmAccounts {
  generated_utc: string
  accounts: LlmAccount[]
  ledger?: { since_utc: string | null; rows: number; unattributed_d7: { calls: number; total: number; aux_calls: number } }
}

export interface LiveStep {
  n: number
  name: string
  status: string
  conclusion: string | null
  started: string | null
  completed: string | null
}
export interface LiveJob {
  id: number
  name: string
  status: string
  conclusion: string | null
  runner: string | null
  started: string | null
  completed: string | null
  url: string
  steps: LiveStep[]
}
export interface LiveRun {
  id: number
  title: string
  workflow: string
  branch: string
  event: string
  status: string
  conclusion: string | null
  created: string
  updated: string
  url: string
  jobs: LiveJob[]
}
export interface LiveJobs {
  generated_utc: string
  repo: string
  runs: LiveRun[]
  active: boolean
  errors: string[]
}
export interface JobLog {
  runner: string
  live: boolean
  lines: string[]
}
