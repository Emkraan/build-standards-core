// Builds tab of the Operations hub (/operations/builds/<product>): live app_e release and endpoint agent build, release and rollout runs
// on platform. Each product card shows what is live right now (read from device management, the blob and GitHub,
// not assumed) and every pipeline's runs: a run in flight expands to its jobs and step bars, a
// waiting run names the environment it needs and links to the approval card, a failed run shows
// the error it stopped on. Approvals stay on the privileged lane in Reviews. The one write is
// a dev_tier deploy refused for being behind main shows the count, and on my own branches
// offers Update from main and redeploy (the server decides the phase and re-checks before it acts).
import { Button, Card, CardHead, EmptyState, IconAlert, IconChevronDown, IconChevronRight, Stat, StatRow } from '@kit'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { AgentLanded, BuildPipeline, BuildRefusal, BuildRun, Builds as BuildsData, app_eLanded } from '../../lib/data'
import { postBuildDispatch, postUpdateFromMain, relTime, useBuilds } from '../../lib/data'
import { dur, stateLabel, stateTone, useTick } from '../infra/data'
import { JobRow } from '../infra/LiveJobs'
import { FeedPending, StatePill } from '../infra/parts'
import '../Infrastructure.css'
import './Builds.css'
import { RunButton } from './RunButton'

const ACTIVE = new Set(['in_progress', 'queued', 'requested', 'pending', 'waiting'])

function runSpan(r: BuildRun): [string | null, string | null] {
  const starts = r.jobs
    .map((j) => j.started)
    .filter((x): x is string => !!x)
    .sort()
  const ends = r.jobs
    .map((j) => j.completed)
    .filter((x): x is string => !!x)
    .sort()
  const live = ACTIVE.has(r.status)
  return [r.started || starts[0] || r.created, live ? null : ends.pop() || r.updated]
}

function RefusalNote({ run: r, refusal: f }: { run: BuildRun; refusal: BuildRefusal }) {
  const { refresh } = useBuilds()
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const n = f.behind_live ?? f.behind
  const plural = (k: number) => `${k} commit${k === 1 ? '' : 's'}`
  const headline =
    f.behind_live === 0
      ? `Refused: ${f.branch} was ${plural(f.behind)} behind main, up to date now`
      : `Refused: ${f.branch} is ${plural(n)} behind main`
  const go = () => {
    setBusy(true)
    setErr(null)
    postUpdateFromMain({ run: r.id, branch: f.branch, sha: f.head })
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => {
        setBusy(false)
        refresh()
      })
  }
  const working = busy || f.phase === 'working'
  const error = err || f.error
  return (
    <div className="tone hue-red bld-note bld-refusal">
      <IconAlert />
      <div className="bld-refusal-body">
        <p>
          <strong>{headline}</strong>
        </p>
        {f.phase === 'conflict' && (
          <p>
            Conflict with main, needs a manual merge.
            {f.files && f.files.length > 0 ? ` Files changed on both sides: ${f.files.join(', ')}.` : ''}
          </p>
        )}
        {f.phase === 'working' && <p>Waiting for the new run to show.</p>}
        {error && <p role="alert">{error}</p>}
        {f.own === null && f.phase === 'info' && (
          <p className="infra-muted">Could not confirm who wrote this branch, so no update is offered.</p>
        )}
        {(f.phase === 'needs_action' || working) && (
          <div className="bld-refusal-actions">
            <Button size="sm" variant="primary" loading={working} disabled={working} onClick={go}>
              Update from main and redeploy
            </Button>
            {working && (
              <StatePill tone="info" live>
                updating
              </StatePill>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function RunRow({ run: r, now }: { run: BuildRun; now: number }) {
  const live = ACTIVE.has(r.status)
  const [open, setOpen] = useState(false)
  const show = live || open
  const [start, end] = runSpan(r)
  const current = r.jobs.flatMap((j) => j.steps.filter((s) => s.status === 'in_progress').map((s) => `${j.name}: ${s.name}`))[0]
  const tone = stateTone(r.status, r.conclusion)
  const dry = !!r.summary && /dryRun=true/.test(r.summary)
  return (
    <div className="bld-run" data-tone={tone} data-live={live ? '' : undefined}>
      <div className="bld-run-head">
        {!live && (
          <button
            type="button"
            className="btn infra-run-toggle"
            data-variant="ghost"
            data-size="sm"
            data-icon-only=""
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            aria-label={open ? 'Hide jobs' : 'Show jobs'}
            data-tip={open ? 'Hide jobs' : 'Show jobs'}
          >
            {open ? <IconChevronDown /> : <IconChevronRight />}
          </button>
        )}
        <StatePill tone={tone} live={r.status === 'in_progress'}>
          {stateLabel(r.status, r.conclusion)}
        </StatePill>
        <a href={r.url} target="_blank" rel="noreferrer" className="infra-run-name">
          Run {r.id}
          {r.attempt && r.attempt > 1 ? ` (attempt ${r.attempt})` : ''}
        </a>
        <span className="infra-muted">
          {r.branch} &middot; {r.sha}
          {r.actor ? ` \u00b7 ${r.actor}` : ''}
        </span>
        <span className="infra-muted infra-push">{live ? `started ${relTime(start || r.created)}` : relTime(r.updated)}</span>
        <span className="infra-muted infra-mono">{dur(start, end, now)}</span>
      </div>
      {live && current && <p className="bld-now">Now: {current}</p>}
      {r.waiting_on.length > 0 && (
        <p className="tone hue-amber bld-note" role="status">
          <IconAlert />
          <span>
            Waiting on <strong>{r.waiting_on.join(', ')}</strong> approval.{' '}
            {r.approve_here.length > 0 ? (
              <Link to="/reviews/platform">Approve it in Reviews &rarr;</Link>
            ) : (
              <a href={r.url} target="_blank" rel="noreferrer">
                Review it on GitHub &rarr;
              </a>
            )}
          </span>
        </p>
      )}
      {r.refusal && <RefusalNote run={r} refusal={r.refusal} />}
      {r.reason && !r.refusal && (
        <p className="tone hue-red bld-note">
          <IconAlert />
          <span>
            <strong>{r.reason.where}</strong>
            {r.reason.message ? `: ${r.reason.message}` : ''}
          </span>
        </p>
      )}
      {r.summary && (
        <p className={`bld-summary${dry ? ' tone hue-amber' : ''}`}>
          {dry ? 'Dry run only, nothing published: ' : 'Rolled out: '}
          {r.summary}
        </p>
      )}
      {r.error && <p className="infra-muted">Jobs unavailable: {r.error}</p>}
      {show && r.jobs.length > 0 && (
        <div className="bld-jobs">
          {r.jobs.map((j) => (
            <JobRow key={j.id} job={j} now={now} liveLog={false} />
          ))}
        </div>
      )}
    </div>
  )
}

function PipelineBlock({ p, now, refresh }: { p: BuildPipeline; now: number; refresh: () => void }) {
  const [all, setAll] = useState(false)
  // Current state vs history (layout rule 5): the server says whether the pipeline is failed now; the runs of its history
  // stay folded under "older runs" so a fixed failure never reads as current. Runs are newest first.
  const history = new Set(p.state?.history ?? [])
  const active = p.runs.filter((r) => ACTIVE.has(r.status))
  const finished = p.runs.filter((r) => !ACTIVE.has(r.status))
  const recent = finished.filter((r) => !history.has(r.id))
  const older = finished.filter((r) => history.has(r.id))
  const shown = all ? finished : recent.slice(0, 3)
  const hidden = all ? 0 : finished.length - shown.length
  const refusal = p.paused ? { kind: 'paused', reason: 'This pipeline is paused.' } : undefined
  return (
    <section className="bld-pipe" aria-label={p.label}>
      <div className="bld-pipe-head">
        <a href={p.url} target="_blank" rel="noreferrer" className="bld-pipe-name">
          {p.label}
        </a>
        <span className="infra-muted infra-mono">{p.workflow}</span>
        {p.state?.failed ? <StatePill tone="danger">failed on main</StatePill> : null}
        {p.paused ? <StatePill tone="neutral">paused</StatePill> : null}
        <span className="infra-push">
          <RunButton
            label="Run workflow"
            title={`Run ${p.label}`}
            subtitle={p.workflow}
            inputs={p.inputs}
            ref_={p.ref}
            refusal={refusal}
            start={(req) => postBuildDispatch(p.key, req.ref, req.inputs)}
            onStarted={refresh}
          />
        </span>
      </div>
      {p.runs.length === 0 && <p className="infra-muted">No runs yet.</p>}
      <div className="infra-stack">
        {active.map((r) => (
          <RunRow key={r.id} run={r} now={now} />
        ))}
        {shown.map((r) => (
          <RunRow key={r.id} run={r} now={now} />
        ))}
      </div>
      {(hidden > 0 || (all && older.length > 0)) && (
        <button type="button" className="btn bld-more" data-variant="ghost" data-size="sm" onClick={() => setAll(!all)}>
          {all ? 'Show fewer' : `History: ${hidden} older run${hidden === 1 ? '' : 's'}`}
        </button>
      )}
    </section>
  )
}

function Problems({ items }: { items: string[] }) {
  if (!items.length) return null
  return (
    <p className="tone hue-red infra-alert" role="alert">
      <IconAlert />
      <span>{items.join(' | ')}</span>
    </p>
  )
}

function App_eLive({ l }: { l: app_eLanded }) {
  const rec = l.recorded
  const health = l.live?.health
  return (
    <>
      <StatRow label="What is live for app_e" min="sm">
        <Stat label="Payload" value={rec?.payload || 'unknown'} hint={rec?.released ? `recorded ${rec.released}` : undefined} />
        <Stat
          label="device management content version"
          value={rec?.content_version || 'unknown'}
          hint="from release.json (my Graph token cannot read the app)"
        />
        <Stat
          label="Health script version"
          value={health?.version || 'unknown'}
          hint={health?.modified ? `changed ${relTime(health.modified)}, live` : 'live read failed'}
          tone={l.drift.length ? 'warning' : undefined}
        />
        <Stat
          label="Staging package"
          value={l.blob?.bytes ? `${(l.blob.bytes / 1e9).toFixed(2)} GB` : 'unknown'}
          hint={l.blob?.modified ? `published ${relTime(l.blob.modified)}` : undefined}
        />
      </StatRow>
      {l.drift.length > 0 && (
        <p className="tone hue-amber bld-note" role="status">
          <IconAlert />
          <span>
            <strong>Release not recorded yet.</strong> {l.drift.map((d) => d.charAt(0).toUpperCase() + d.slice(1)).join('. ')}. The record
            PR (release.json from the run's artifact) closes this.
          </span>
        </p>
      )}
      <Problems items={l.errors} />
    </>
  )
}

function AgentLive({ l, rollout }: { l: AgentLanded; rollout: BuildRun | undefined }) {
  const dry = !!rollout?.summary && /dryRun=true/.test(rollout.summary)
  return (
    <>
      <StatRow label="What is live for the endpoint agent" min="sm">
        <Stat
          label="Newest release"
          value={l.latest?.version || 'none'}
          hint={l.latest?.published ? `published ${relTime(l.latest.published)}` : undefined}
        />
        <Stat
          label="Version on main"
          value={l.main_version || 'unknown'}
          tone={l.pending ? 'warning' : undefined}
          hint={l.pending ? 'not released yet' : 'released'}
        />
        <Stat
          label="Last workflow rollout"
          value={rollout?.summary ? rollout.summary.replace(/^version (\S+):.*ring (\S+?),?\s.*$/, '$1 to $2') : 'none'}
          hint={
            rollout
              ? `${dry ? 'dry run only, ' : ''}${relTime(rollout.updated)}. Console rollouts do not show here.`
              : 'Console rollouts do not show here.'
          }
          tone={dry ? 'warning' : undefined}
        />
      </StatRow>
      {l.pending && (
        <p className="tone hue-amber bld-note" role="status">
          <IconAlert />
          <span>{l.pending}.</span>
        </p>
      )}
      <Problems items={l.errors} />
    </>
  )
}

function ProductCard({
  title,
  subtitle,
  pipes,
  now,
  refresh,
  children,
}: {
  title: string
  subtitle: string
  pipes: BuildPipeline[]
  now: number
  refresh: () => void
  children: React.ReactNode
}) {
  const live = pipes.some((p) => p.runs.some((r) => ACTIVE.has(r.status)))
  return (
    <Card>
      <CardHead
        title={title}
        subtitle={subtitle}
        controls={
          live ? (
            <StatePill tone="info" live>
              running
            </StatePill>
          ) : (
            <StatePill tone="neutral">idle</StatePill>
          )
        }
      />
      <div className="infra-stack">
        {children}
        {pipes.map((p) => (
          <PipelineBlock key={p.key} p={p} now={now} refresh={refresh} />
        ))}
      </div>
    </Card>
  )
}

/** One build item of the hub: the pipelines of a product, what is live for it and a start button per workflow. */
export default function BuildTab({ product }: { product: string }) {
  const { data, error, refresh } = useBuilds()
  const now = useTick(!!data?.active)
  if (!data) return <FeedPending title="Builds" error={error} what="Build feed" tiles />
  return <BuildsBody data={data} now={now} product={product} refresh={refresh} />
}

function BuildsBody({ data, now, product, refresh }: { data: BuildsData; now: number; product: string; refresh: () => void }) {
  const pipes = data.pipelines.filter((p) => p.product === product)
  // The newest real rollout by workflow, else the newest dry run (flagged as such).
  const rolls = pipes.find((p) => p.key === 'agent-rollout')?.runs.filter((r) => r.conclusion === 'success' && r.summary) || []
  const rollout = rolls.find((r) => !/dryRun=true/.test(r.summary || '')) || rolls[0]
  const title = product === 'agent' ? 'Endpoint agent' : product
  return (
    <div className="infra-stack">
      <Problems items={data.errors} />
      <ProductCard title={title} subtitle={data.active ? `${data.running} running, ${data.waiting} waiting on approval` : `idle, checked ${relTime(data.generated_utc)}`} pipes={pipes} now={now} refresh={refresh}>
        {product === 'app_e' && data.landed.app_e ? <App_eLive l={data.landed.app_e} /> : null}
        {product === 'agent' && data.landed.agent ? <AgentLive l={data.landed.agent} rollout={rollout} /> : null}
      </ProductCard>
      {pipes.length === 0 && <EmptyState compact pose="idle" title="No pipelines configured." />}
    </div>
  )
}
