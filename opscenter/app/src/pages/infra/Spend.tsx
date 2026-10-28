// LLM spend tab: the two Anthropic accounts (live from Anthropic), the Hermes spend split by the
// account that served each call, and the monthly history.
import type { TableColumn } from '@kit'
import { Badge, Card, CardHead, EmptyState, IconAlert, Pill, StatTile, Table, useChartTheme } from '@kit'
import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { relTime, useNow } from '../../lib/data'
import { enterpriseProjection, fmtTok, LEVEL_STAT, limitLevel, resetIn, usd, useAccounts, useSpend } from './data'
import { ChartLegend, ChartTip, FeedPending, Meter, Note } from './parts'
import type { LlmAccount, Month, SpendJob, TokenWindow } from './types'

const WINDOW_LABEL: Record<string, string> = {
  session: 'Current 5h session',
  week: 'Current week',
  today: 'Today',
  d7: 'Last 7 days',
  month: 'Billing month',
}

type TokenRow = TokenWindow & { key: string }

const TOKEN_COLUMNS: TableColumn<TokenRow>[] = [
  { key: 'key', header: 'Window', render: (r) => WINDOW_LABEL[r.key] || r.key },
  { key: 'calls', header: 'Calls', numeric: true, render: (r) => r.calls.toLocaleString() },
  { key: 'input', header: 'Input', numeric: true, render: (r) => fmtTok(r.input) },
  { key: 'output', header: 'Output', numeric: true, render: (r) => fmtTok(r.output) },
  { key: 'cache_read', header: 'Cache read', numeric: true, render: (r) => fmtTok(r.cache_read) },
  { key: 'cache_write', header: 'Cache write', numeric: true, render: (r) => fmtTok(r.cache_write) },
  { key: 'total', header: 'Total', numeric: true, render: (r) => <b>{fmtTok(r.total)}</b> },
]

function TokenTable({ a }: { a: LlmAccount }) {
  const t = a.tokens
  if (!t) return null
  const order = a.kind === 'claude_team' ? ['session', 'week', 'today'] : ['today', 'd7', 'month']
  const rows = order.filter((k) => t[k]).map((k) => ({ ...t[k], key: k }))
  if (!rows.length) return null
  return (
    <div className="infra-block">
      <div className="infra-eyebrow">Tokens served by this account (Hermes ledger)</div>
      <Table
        caption={`Tokens served by the ${a.kind_label} account`}
        columns={TOKEN_COLUMNS}
        rows={rows}
        rowKey={(r) => r.key}
        sortable={false}
      />
    </div>
  )
}

function AccountCard({ a, now }: { a: LlmAccount; now: number }) {
  const sub = [a.org, a.credential].filter(Boolean).join(' / ')
  const hue = a.kind === 'claude_enterprise' ? 'blue' : 'teal'
  return (
    <Card tone={hue} className="infra-account">
      <CardHead
        title={`${a.kind_label} account`}
        subtitle={sub}
        controls={
          <>
            {a.routing ? (
              <Badge tone="info" dot>
                Hermes routes here first
              </Badge>
            ) : (
              <Badge>fallback (priority {a.priority})</Badge>
            )}
            {a.cooling_down && (
              <Badge tone="warning" dot>
                {a.limits.some((l) => l.percent >= 100) ? 'limit reached' : 'exhausted'}
                {a.pool_reset_at ? `, ${resetIn(a.pool_reset_at, now).replace('resets in', 'back in')}` : ''}
              </Badge>
            )}
            {a.seat_tier && <Badge>{a.seat_tier.replace(/_/g, ' ')}</Badge>}
          </>
        }
      />
      {a.error ? (
        <EmptyState compact icon={<IconAlert />} hue="red" title="Usage unavailable" body={a.error} />
      ) : (
        <>
          {a.limits.map((l) => (
            <div key={l.kind + l.label} className="infra-limit">
              <div className="infra-limit-head">
                <span>
                  {l.label}
                  {l.group === 'session' && !l.is_active && <span className="infra-muted"> (no active session)</span>}
                </span>
                <b className="infra-num">{l.percent}% used</b>
              </div>
              <Meter pct={l.percent} level={limitLevel(l)} label={`${l.label} used`} />
              <div className="infra-muted">{resetIn(l.resets_at, now)}</div>
            </div>
          ))}
          {a.spend && (a.spend.enabled || a.spend.used_usd > 0) && (
            <div className="infra-limit">
              <div className="infra-limit-head">
                <span>{a.limits.length ? 'Extra usage credits, this billing month' : 'Usage spend, this billing month'}</span>
                <b className={a.limits.length ? 'infra-num' : 'infra-num infra-big'}>{usd(a.spend.used_usd)}</b>
              </div>
              {a.spend.limit_usd ? (
                <>
                  <Meter
                    pct={(a.spend.used_usd / a.spend.limit_usd) * 100}
                    level={a.spend.spend_limit_reached ? 'alert' : a.spend.percent >= 80 ? 'warn' : 'good'}
                    label="Spend cap used"
                  />
                  <div className="infra-muted">of {usd(a.spend.limit_usd)} cap</div>
                </>
              ) : (
                <div className="infra-muted">no per-user spend cap set, billed to the org contract</div>
              )}
            </div>
          )}
          {a.spend && !a.spend.enabled && a.limits.length > 0 && (
            <Note>Extra usage is off: hitting a limit blocks this account until the reset, then Hermes falls back.</Note>
          )}
          {!a.limits.length && !a.spend && <EmptyState compact title="No usage reported for this account." />}
          <TokenTable a={a} />
          <Note>
            {a.stale
              ? `Last live reading ${a.fetched_utc ? relTime(a.fetched_utc) : 'unknown'}. Live read paused: ${a.stale}.`
              : `Checked ${a.fetched_utc ? relTime(a.fetched_utc) : 'never'}.`}
          </Note>
        </>
      )}
    </Card>
  )
}

function AccountsSection() {
  const { data, error } = useAccounts()
  const now = useNow(30_000)
  if (!data) return <FeedPending title="Anthropic accounts" error={error} what="Account usage" tiles />
  const ent = data.accounts.find((a) => a.kind === 'claude_enterprise')
  const team = data.accounts.find((a) => a.kind === 'claude_team')
  const sess = team?.limits.find((l) => l.kind === 'session')
  const week = team?.limits.find((l) => l.kind === 'weekly_all')
  return (
    <section className="infra-stack" aria-label="Anthropic accounts">
      <div className="stat-grid">
        <StatTile value={ent?.spend ? usd(ent.spend.used_usd) : '-'} label="Enterprise spend, billing month" hue="blue" />
        <StatTile value={sess ? `${sess.percent}%` : '-'} label="Team session used" tone={sess ? LEVEL_STAT[limitLevel(sess)] : 'accent'} />
        <StatTile value={week ? `${week.percent}%` : '-'} label="Team weekly used" tone={week ? LEVEL_STAT[limitLevel(week)] : 'accent'} />
        {(() => {
          // While the weekly cap is hit, the weekly reset is what brings Team back, not the session.
          const gate = week && week.percent >= 100 && week.resets_at ? week : sess
          const isWeek = gate === week && gate !== sess
          return (
            <StatTile
              value={gate?.resets_at ? resetIn(gate.resets_at, now).replace('resets in ', '').split(' (')[0] : '-'}
              label={isWeek ? 'until Team weekly reset' : 'until Team session reset'}
              hue="teal"
              hint={gate && !gate.resets_at ? 'no active session' : isWeek ? 'weekly cap reached, Enterprise serves until then' : undefined}
            />
          )
        })()}
      </div>
      <div className="infra-grid">
        {data.accounts.map((a) => (
          <AccountCard key={a.credential} a={a} now={now} />
        ))}
      </div>
      <Note>
        Dollars and percents are live from Anthropic per account, refreshed every minute. Token counts come from the anthropic_ledger Hermes
        plugin, which records the pool entry that served every API call
        {data.ledger?.since_utc ? ` (recording since ${new Date(data.ledger.since_utc).toLocaleString()})` : ' (no calls recorded yet)'}.
        {data.ledger && data.ledger.unattributed_d7.calls > 0 && (
          <>
            {' '}
            {data.ledger.unattributed_d7.calls} calls ({fmtTok(data.ledger.unattributed_d7.total)} tokens) in the last 7 days have no
            account attached: auxiliary calls ({data.ledger.unattributed_d7.aux_calls}) plus processes started before the plugin loaded.
          </>
        )}{' '}
        Tokens and dollars only cover Hermes. claude.ai, Cowork, and Claude Code on the Enterprise seat add to the Anthropic figure but not
        the ledger. The spend section below splits every Hermes call by the account that served it: Enterprise calls are billed, Team calls
        are covered by the seat.
      </Note>
    </section>
  )
}

/** Colours of the three spend buckets plus the real Anthropic line, from the live chart theme. */
function useBucketColors() {
  const t = useChartTheme()
  return { t, billed: t.status.overdue, included: t.status.completed, unattributed: t.status.notStarted, actual: t.status.warning }
}

const axisProps = (axis: string, grid: string) => ({
  tick: { fontSize: 11, fill: axis },
  axisLine: { stroke: grid },
  tickLine: false as const,
})

function DailyChart({ chart, hasReal }: { chart: Record<string, unknown>[]; hasReal: boolean }) {
  const c = useBucketColors()
  return (
    <>
      <div className="infra-chart" role="img" aria-label="Daily Hermes spend by account, last 21 days">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chart} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={c.t.grid} vertical={false} />
            <XAxis dataKey="label" {...axisProps(c.t.axis, c.t.grid)} />
            <YAxis {...axisProps(c.t.axis, c.t.grid)} axisLine={false} width={48} tickFormatter={(v) => `$${v}`} />
            <Tooltip cursor={{ fill: c.t.grid, opacity: 0.4 }} content={<ChartTip format={usd} />} />
            <Bar dataKey="billed" stackId="a" fill={c.billed} name="billed (Enterprise)" isAnimationActive={false} />
            <Bar dataKey="included" stackId="a" fill={c.included} name="covered by Team" isAnimationActive={false} />
            <Bar
              dataKey="unattributed"
              stackId="a"
              fill={c.unattributed}
              name="unattributed"
              radius={[4, 4, 0, 0]}
              isAnimationActive={false}
            />
            {hasReal && (
              <Line
                dataKey="anthropic"
                name="Enterprise actual (Anthropic)"
                stroke={c.actual}
                strokeWidth={2}
                dot={{ r: 3, fill: c.actual }}
                connectNulls
                isAnimationActive={false}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <ChartLegend
        items={[
          ...(hasReal ? [{ label: 'Enterprise actual (Anthropic)', color: c.actual, line: true }] : []),
          { label: 'billed (Enterprise)', color: c.billed },
          { label: 'covered by Team', color: c.included },
          { label: 'unattributed', color: c.unattributed },
        ]}
      />
    </>
  )
}

const JOB_COLUMNS: TableColumn<SpendJob>[] = [
  {
    key: 'name',
    header: 'Job',
    render: (j) => (
      <span className="infra-inline">
        {j.name}
        {!j.active && <Pill>retired</Pill>}
      </span>
    ),
  },
  { key: 'runs_d7', header: 'Runs', numeric: true },
  {
    key: 'fallback_runs_d7',
    header: 'Fell back',
    numeric: true,
    render: (j) => <span className={j.fallback_runs_d7 ? 'infra-billed' : undefined}>{j.fallback_runs_d7}</span>,
  },
  {
    key: 'billed_today',
    header: 'Billed today',
    numeric: true,
    render: (j) => <span className={j.billed_today > 0 ? 'infra-billed' : undefined}>{usd(j.billed_today)}</span>,
  },
  { key: 'billed_d7', header: 'Billed 7d', numeric: true, render: (j) => <b>{usd(j.billed_d7)}</b> },
  { key: 'included_d7', header: 'Team 7d', numeric: true, render: (j) => <span className="infra-muted">{usd(j.included_d7)}</span> },
]

function SpendSection() {
  const { data, error } = useSpend()
  const accts = useAccounts().data
  if (!data) return <FeedPending title="LLM spend" error={error} what="Spend" tiles />
  const t = data.totals
  const ent = accts?.accounts.find((a) => a.kind === 'claude_enterprise')
  const proj = enterpriseProjection(data, ent)
  const realDaily = new Map((ent?.spend_history?.daily ?? []).map((d) => [d.date, d]))
  const chart = data.daily.slice(-21).map((d) => {
    const r = realDaily.get(d.date)
    return { ...d, label: d.date.slice(5), anthropic: r && !r.partial ? r.usd : undefined }
  })
  const hasReal = chart.some((d) => d.anthropic !== undefined)
  const outside = ent?.spend ? Math.max(0, ent.spend.used_usd - t.billed_mtd) : null
  const since = data.ledger_since_utc
    ? new Date(data.ledger_since_utc).toLocaleString('en-US', { month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit' })
    : null
  const jobs = data.jobs.filter((j) => j.cost_d7 > 0)
  return (
    <section className="infra-stack" aria-label="Hermes spend">
      <div className="stat-grid">
        <StatTile
          value={usd(t.billed_today)}
          label="billed to Enterprise today (Hermes)"
          tone={t.billed_today > 0 ? 'warning' : 'success'}
        />
        <StatTile value={usd(t.billed_d7)} label="billed to Enterprise, 7 days (Hermes)" hue="blue" />
        <StatTile
          value={proj ? usd(proj.value) : '-'}
          label={proj?.real ? 'projected Enterprise bill, month' : 'projected Hermes Enterprise, month'}
          tone={proj && proj.value > 3000 ? 'danger' : proj && proj.value > 1500 ? 'warning' : 'accent'}
        />
        <StatTile value={usd(t.included_d7)} label="covered by Team, 7 days ($0 billed)" tone="success" />
        {outside !== null && <StatTile value={usd(outside)} label="Enterprise outside Hermes, month (est.)" hue="violet" />}
        {t.unattributed_d7 > 0 && <StatTile value={usd(t.unattributed_d7)} label="unattributed, 7 days" tone="warning" />}
      </div>
      <Note>
        Billed means calls the Enterprise account served (usage billed to the org). Team calls are list-price value covered by the seat, so
        they cost nothing extra. Hermes ran on Enterprise until the ledger started{since ? ` (${since})` : ''}, so earlier days count as
        billed.{' '}
        {proj &&
          `Projection: ${usd(ent?.spend ? ent.spend.used_usd : t.billed_mtd)} so far plus ${usd(proj.rate)}/day (${proj.basis}) for the rest of the month.`}{' '}
        Hermes list-price total, both accounts: {usd(t.today)} today, {usd(t.d7)} last 7 days.
      </Note>
      <div className="infra-grid">
        <Card>
          <CardHead title="Daily Hermes spend by account" subtitle="last 21 days, billed vs covered by Team" />
          <DailyChart chart={chart} hasReal={hasReal} />
          <Note>
            {hasReal
              ? 'The amber line is the real Enterprise charge per day from Anthropic (all usage on the seat, not just Hermes).'
              : `Real per-day Enterprise charges from Anthropic start plotting after a full day of samples${
                  ent?.spend_history?.since_utc ? ` (sampling since ${relTime(ent.spend_history.since_utc)})` : ''
                }.`}
          </Note>
        </Card>
        <MonthlyChartCard />
      </div>
      <Card>
        <CardHead title="Spend by cron job" subtitle="last 7 days, billed first" />
        <Table
          caption="Spend by cron job, last 7 days"
          columns={JOB_COLUMNS}
          rows={jobs}
          rowKey={(j) => j.id}
          defaultSort={{ key: 'billed_d7', dir: 'desc' }}
          empty={<EmptyState compact title="No cron spend in the last 7 days." />}
        />
        <dl className="infra-totals" aria-label="Cron total">
          <div>
            <dt>Cron total</dt>
            <dd>{jobs.reduce((n, j) => n + j.runs_d7, 0)} runs</dd>
          </div>
          <div>
            <dt>Fell back</dt>
            <dd>{jobs.reduce((n, j) => n + j.fallback_runs_d7, 0)}</dd>
          </div>
          <div>
            <dt>Billed today</dt>
            <dd>{usd(jobs.reduce((n, j) => n + j.billed_today, 0))}</dd>
          </div>
          <div>
            <dt>Billed 7d</dt>
            <dd>
              <b>{usd(t.cron_billed_d7)}</b>
            </dd>
          </div>
          <div>
            <dt>Team 7d</dt>
            <dd>{usd(t.cron_included_d7)}</dd>
          </div>
        </dl>
        <Note>
          Fell back counts runs where at least one call fell back to Enterprise after the switch. Billed 7d includes days before the Team
          switch. {data.sessions} sessions in 30 days, {data.estimated_sessions} priced from token counts at list price. Refreshed{' '}
          {relTime(data.generated_utc)}.
        </Note>
      </Card>
    </section>
  )
}

function monthLabel(m: string): string {
  const [y, mo] = m.split('-').map(Number)
  return new Date(y, mo - 1, 1).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
}

type MonthJob = Month['jobs'][number]

const MONTH_JOB_COLUMNS: TableColumn<MonthJob>[] = [
  { key: 'name', header: 'Cron job' },
  { key: 'billed', header: 'Billed', numeric: true, render: (j) => usd(j.billed) },
  {
    key: 'team',
    header: 'Team',
    numeric: true,
    value: (j) => Math.max(0, j.cost - j.billed),
    render: (j) => usd(Math.max(0, j.cost - j.billed)),
  },
  { key: 'cost', header: 'List total', numeric: true, render: (j) => <span className="infra-muted">{usd(j.cost)}</span> },
]

function MonthlyChartCard() {
  const { data } = useSpend()
  const c = useBucketColors()
  if (!data?.months) return null
  const cur = data.months[data.months.length - 1]
  const chart = data.months.map((m) => ({ ...m, label: monthLabel(m.month) }))
  return (
    <Card>
      <CardHead title="Monthly spend" subtitle="calendar months, billed to Enterprise vs covered by Team" />
      <div className="infra-chart" role="img" aria-label="Monthly spend by account">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chart} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={c.t.grid} vertical={false} />
            <XAxis dataKey="label" {...axisProps(c.t.axis, c.t.grid)} />
            <YAxis {...axisProps(c.t.axis, c.t.grid)} axisLine={false} width={56} tickFormatter={(v) => `$${v}`} />
            <Tooltip cursor={{ fill: c.t.grid, opacity: 0.4 }} content={<ChartTip format={usd} />} />
            <Bar dataKey="billed" stackId="m" fill={c.billed} name="billed (Enterprise)" isAnimationActive={false} />
            <Bar dataKey="included" stackId="m" fill={c.included} name="covered by Team" isAnimationActive={false} />
            <Bar
              dataKey="unattributed"
              stackId="m"
              fill={c.unattributed}
              name="unattributed"
              radius={[4, 4, 0, 0]}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ChartLegend
        items={[
          { label: 'billed (Enterprise)', color: c.billed },
          { label: 'covered by Team', color: c.included },
          { label: 'unattributed', color: c.unattributed },
        ]}
      />
      {cur && (
        <Note>
          {monthLabel(cur.month)} so far: {usd(cur.billed)} billed to Enterprise by Hermes, {usd(cur.included)} covered by Team. Projected
          Hermes Enterprise bill {usd(data.totals.billed_projected_month)} at the current fallback rate.
        </Note>
      )}
    </Card>
  )
}

function MonthlySection() {
  const { data } = useSpend()
  const [open, setOpen] = useState<string | null>(null)
  if (!data?.months) return null
  const months = [...data.months].reverse()
  const cur = months[0]
  const sel = months.find((m) => m.month === open)
  const columns: TableColumn<Month>[] = [
    {
      key: 'month',
      header: 'Month',
      render: (m) => (
        <span className="infra-inline">
          {monthLabel(m.month)}
          {m === cur && (
            <Badge tone="info" dot>
              in progress
            </Badge>
          )}
        </span>
      ),
    },
    { key: 'billed', header: 'Billed', numeric: true, render: (m) => <b>{usd(m.billed)}</b> },
    { key: 'included', header: 'Team', numeric: true, render: (m) => usd(m.included) },
    { key: 'unattributed', header: 'Unattrib.', numeric: true, render: (m) => usd(m.unattributed) },
    { key: 'total', header: 'List total', numeric: true, render: (m) => <span className="infra-muted">{usd(m.total)}</span> },
  ]
  return (
    <Card>
      <CardHead title="Cost by month" subtitle="click a month for its cron jobs" />
      <div className={sel ? 'infra-split' : undefined}>
        <Table
          caption="Cost by month"
          columns={columns}
          rows={months}
          rowKey={(m) => m.month}
          defaultSort={{ key: 'month', dir: 'desc' }}
          onRowActivate={(m) => setOpen(open === m.month ? null : m.month)}
          isRowSelected={(m) => m.month === open}
        />
        {sel && (
          <div>
            <div className="infra-eyebrow infra-split-title">Cron jobs in {monthLabel(sel.month)}</div>
            <Table
              caption={`Cron jobs in ${monthLabel(sel.month)}`}
              columns={MONTH_JOB_COLUMNS}
              rows={sel.jobs.slice(0, 12)}
              rowKey={(j) => sel.month + j.id}
              defaultSort={{ key: 'cost', dir: 'desc' }}
              empty={<EmptyState compact title="No cron spend recorded this month." />}
            />
          </div>
        )}
      </div>
      <Note>
        History starts {monthLabel(data.months[0]?.month || '')} (first session on record). Months before the Team switch are all billed.
        Team column on job rows includes unattributed calls.
      </Note>
    </Card>
  )
}

export default function SpendTab() {
  return (
    <div className="infra-stack infra-stack-lg">
      <AccountsSection />
      <SpendSection />
      <MonthlySection />
    </div>
  )
}
