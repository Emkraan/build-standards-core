// Yearly review: the annual performance review I write once a year per person
// and hand to HR. Records are year-keyed on the server (state/team-performance/
// yearly-reviews.json) and never deleted.
//
// Drafting is analysis, not a data dump: "Draft full review" runs a server job
// that reads the whole year of evidence on each person (every Jira ticket, my
// Teams 1:1 chat, group chats, email both ways, meetings and transcripts, my
// engineer notes, the assessment history and the ledgers) and writes every
// section in my voice, HR-ready, with no sprint names. Each section can be
// rewritten on its own with my steer, undone, or edited by hand. Reset clears
// the review and keeps a snapshot I can restore. Sections come from the review
// template, which changes when HR sends the official format.
//
import {
  Badge,
  Button,
  Card,
  CardHead,
  EmptyState,
  Field,
  IconChevronDown,
  IconChevronRight,
  Segmented,
  Select,
  Skeleton,
  StatTile,
  Textarea,
  Tone,
  Toolbar,
  useConfirm,
} from '@kit'
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { confirmText } from '../components/confirmText'
import { Pill } from '../components/ui'
import type {
  HistoryMaster,
  ReviewJob,
  ReviewMetrics,
  ReviewTemplateSection,
  TeamPerformance,
  YearlyReviews,
  YearlyReview as YR,
} from '../lib/data'
import {
  fetchReviewEvidence,
  postReviewDraft,
  postYearlyReview,
  relTime,
  useData,
  useNow,
  useReviewJobs,
  useYearlyReviews,
  yearlyExportUrl,
} from '../lib/data'
import { Linked } from './MemberReviews'
import { ChartLegend, ChartTip, usePeopleChart } from './people/chart'
import { Meter, PersonCard, PersonRail } from './people/PersonCard'
import './MemberReviews.css'

const ACTIVE = new Set(['starting', 'queued', 'evidence', 'drafting', 'drafted'])
const CONF_TONE: Record<string, 'success' | 'warning' | 'danger' | 'neutral'> = { high: 'success', medium: 'warning', low: 'danger' }
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

type Save = { state: 'idle' | 'dirty' | 'saving' | 'error'; msg?: string }
const SAVE_TONE = { idle: 'neutral', dirty: 'warning', saving: 'info', error: 'danger' } as const

function monthLabel(ym: string) {
  const m = Number(ym.slice(5, 7))
  return MONTHS[m - 1] || ym
}

function fmtDay(iso: string | null | undefined) {
  if (!iso) return '-'
  const d = new Date(iso.length <= 10 ? `${iso}T12:00:00` : iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function elapsed(from: string | null | undefined, now: number) {
  if (!from) return ''
  const s = Math.max(0, Math.round((now - new Date(from).getTime()) / 1000))
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
}

function metaLabel(m: YR['meta'][string] | undefined) {
  if (!m) return ''
  const when = relTime(m.at)
  switch (m.source) {
    case 'draft':
      return `Drafted ${when}${m.steered ? ' with my steer' : ''}`
    case 'refine':
      return `Rewritten ${when}${m.steered ? ' with my steer' : ''}`
    case 'manual':
      return `Edited by me ${when}`
    case 'undo':
      return `Earlier version restored ${when}`
    default:
      return ''
  }
}

const isActive = (j: ReviewJob) => ACTIVE.has(j.state) && !j.applied_utc

export default function YearlyReview() {
  const { data: hist } = useData<HistoryMaster>('history-master.json')
  const { data: tp } = useData<TeamPerformance>('team-performance.json')
  const { data: yr, error: yErr, mutate, reload } = useYearlyReviews()
  const { data: jobData } = useReviewJobs()
  const now = useNow(1000)
  const [params, setParams] = useSearchParams()
  const thisYear = String(new Date().getFullYear())

  const years = useMemo(() => {
    const s = new Set<string>([thisYear])
    hist?.runs.forEach((r) => {
      if (r.year) s.add(r.year)
    })
    Object.keys(yr?.reviews || {}).forEach((y) => {
      s.add(y)
    })
    return [...s].sort().reverse()
  }, [hist, yr, thisYear])
  const qYear = params.get('year') || ''
  const year = years.includes(qYear) ? qYear : thisYear

  const people = useMemo(() => {
    const s = new Set<string>()
    hist?.runs
      .filter((r) => r.year === year)
      .forEach((r) => {
        r.engineers.forEach((e) => {
          s.add(e.name)
        })
      })
    Object.keys(yr?.reviews?.[year] || {}).forEach((n) => {
      s.add(n)
    })
    if (year === thisYear) {
      ;(tp?.engineers || []).forEach((n) => {
        s.add(n)
      })
      ;(yr?.people || []).forEach((n) => {
        s.add(n)
      })
    }
    return [...s].sort()
  }, [hist, yr, tp, year, thisYear])
  const want = (params.get('p') || '').toLowerCase()
  const name = people.find((n) => n.toLowerCase() === want || n.split(' ')[0].toLowerCase() === want) || people[0] || ''
  const first = name.split(' ')[0]
  const key = `${year}|${name}`
  const server: YR | undefined = yr?.reviews?.[year]?.[name]
  const tplSections: ReviewTemplateSection[] = yr?.template?.sections || []

  // Jobs: the live poller wins over the copy embedded in the reviews payload.
  const jobs = useMemo(() => jobData?.jobs || yr?.jobs || [], [jobData, yr])
  const myJob = jobs.find((j) => j.year === year && j.person === name && isActive(j))
  const lastJob = jobs.find((j) => j.year === year && j.person === name)
  const busyKeys = new Set<string>(myJob ? (myJob.mode === 'full' ? tplSections.map((s) => s.key) : myJob.sections) : [])

  // When a job for anyone finishes, pull the reviews again.
  const activeIds = useRef<Set<string>>(new Set())
  useEffect(() => {
    const nowActive = new Set(jobs.filter(isActive).map((j) => j.id))
    let finished = false
    activeIds.current.forEach((id) => {
      if (!nowActive.has(id)) finished = true
    })
    activeIds.current = nowActive
    if (finished) reload()
  }, [jobs, reload])

  // ---------------- edit buffer: only keys I touched are sent, so a draft that
  // lands while I type never gets overwritten by stale text.
  const [buf, setBuf] = useState<Record<string, string>>({})
  const [rating, setRating] = useState('')
  const [save, setSave] = useState<Save>({ state: 'idle' })
  type Pending = { y: string; n: string; sections: Record<string, string> }
  const pending = useRef<Pending | null>(null)
  // Read through a function so TypeScript does not narrow the ref across awaits.
  const peek = () => pending.current
  const loadedKey = useRef('')
  // biome-ignore lint/correctness/useExhaustiveDependencies: reload the edit buffer only when the review key or the server version changes, never on every server object identity
  useEffect(() => {
    const mine = pending.current && loadedKey.current === key ? pending.current.sections : {}
    loadedKey.current = key
    setBuf({ ...(server?.sections || {}), ...mine })
    setRating(server?.rating || '')
  }, [key, server?.updated_utc])

  const store = useCallback(
    (rec: YR, y: string, n: string) =>
      mutate((d: YearlyReviews) => ({ ...d, reviews: { ...d.reviews, [y]: { ...(d.reviews[y] || {}), [n]: rec } } })),
    [mutate],
  )

  // biome-ignore lint/correctness/useExhaustiveDependencies: peek only reads the pending ref, so it never needs to rebuild flush
  const flush = useCallback(async () => {
    const p = pending.current
    if (!p) return true
    pending.current = null
    setSave({ state: 'saving' })
    try {
      const r = await postYearlyReview({ year: p.y, person: p.n, sections: p.sections })
      store(r.review, p.y, p.n)
      setSave(peek() ? { state: 'dirty' } : { state: 'idle' })
      return true
    } catch (e) {
      const later = peek()
      pending.current = { ...p, sections: { ...p.sections, ...(later?.sections || {}) } }
      setSave({ state: 'error', msg: String((e as Error).message || e) })
      return false
    }
  }, [store])

  // biome-ignore lint/correctness/useExhaustiveDependencies: buf restarts the autosave debounce on every keystroke
  useEffect(() => {
    if (save.state !== 'dirty') return
    const id = window.setTimeout(() => void flush(), 1200)
    return () => window.clearTimeout(id)
  }, [save, buf, flush])

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (pending.current) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [])

  const final = server?.status === 'final'
  const editSection = (k: string, v: string) => {
    if (final || busyKeys.has(k)) return
    setBuf((b) => ({ ...b, [k]: v }))
    const base = pending.current && pending.current.y === year && pending.current.n === name ? pending.current.sections : {}
    pending.current = { y: year, n: name, sections: { ...base, [k]: v } }
    setSave({ state: 'dirty' })
  }

  const run = async (fn: () => Promise<{ review: YR }>) => {
    if (!(await flush())) return false
    try {
      const r = await fn()
      store(r.review, year, name)
      setSave({ state: 'idle' })
      return true
    } catch (e) {
      setSave({ state: 'error', msg: String((e as Error).message || e) })
      return false
    }
  }

  const setRatingNow = (v: string) => {
    setRating(v)
    void run(() => postYearlyReview({ year, person: name, rating: v }))
  }

  const go = async (patch: { year?: string; p?: string }) => {
    await flush()
    setParams((q) => {
      const n = new URLSearchParams(q)
      if (patch.year) n.set('year', patch.year)
      if (patch.p) n.set('p', patch.p)
      return n
    })
  }

  const [jobErr, setJobErr] = useState('')
  const { confirm: ask, dialog: confirmDialog } = useConfirm()
  const [dismissed, setDismissed] = useState('')
  const startJob = async (mode: 'full' | 'refine' | 'evidence', sections?: string[], guidance?: Record<string, string>) => {
    if (!(await flush())) return false
    setJobErr('')
    try {
      await postReviewDraft({ year, person: name, mode, sections, guidance })
      reload()
      return true
    } catch (e) {
      setJobErr(String((e as Error).message || e))
      return false
    }
  }

  const hasContent = tplSections.some((s) => (server?.sections?.[s.key] || '').trim())
  const ratedSections = tplSections.filter((s) => s.rated)
  const competencyMode = ratedSections.length > 0
  const sRatings = server?.section_ratings || {}
  // HR returns a review where any rating lacks its comment, so final needs both everywhere.
  const missingForFinal = competencyMode
    ? tplSections
        .filter((s) => s.export && !s.private)
        .flatMap((s) => [
          ...((buf[s.key] || '').trim() ? [] : [`${s.title} comment`]),
          ...(s.rated && !sRatings[s.key] ? [`${s.title} rating`] : []),
        ])
    : (buf.summary || '').trim()
      ? []
      : ['Overall summary']
  const setSectionRating = (k: string, v: string) => {
    void run(() => postYearlyReview({ year, person: name, section_ratings: { [k]: v } }))
  }
  const draftAll = async () => {
    if (
      hasContent &&
      !(await ask({
        ...confirmText(
          `Redraft every section of ${first}'s ${year} review from a fresh pull of the full-year evidence? Each section's current text is kept as an earlier version I can restore with Undo, and my steering is applied.`,
        ),
        confirmLabel: 'Redraft all',
      }))
    )
      return
    void startJob('full')
  }
  const resetReview = async () => {
    if (
      !(await ask({
        ...confirmText(
          `Reset ${first}'s ${year} review? This clears every section, the rating, the analysis and my steering. A snapshot is kept so I can restore it.`,
        ),
        confirmLabel: 'Reset',
        danger: true,
      }))
    )
      return
    pending.current = null
    void run(() => postYearlyReview({ year, person: name, op: 'reset' }))
  }
  const restore = async () => {
    if (
      !(await ask({
        ...confirmText(`Restore ${first}'s review to how it was before the last reset? What is on screen now is replaced.`),
        confirmLabel: 'Restore',
        danger: true,
      }))
    )
      return
    pending.current = null
    void run(() => postYearlyReview({ year, person: name, op: 'restore' }))
  }
  const setStatus = async (status: 'draft' | 'final') => {
    if (
      status === 'final' &&
      !(await ask({
        ...confirmText(`Mark the ${year} review for ${name} final? Editing locks until I reopen it.`),
        confirmLabel: 'Mark final',
      }))
    )
      return
    await run(() => postYearlyReview({ year, person: name, status }))
  }
  const exportDocx = async () => {
    if (!(await flush())) return
    window.location.href = yearlyExportUrl(year, name)
  }

  // ---------------- evidence metrics for the side panel
  const [metrics, setMetrics] = useState<ReviewMetrics | null>(null)
  const evStamp = server?.draft?.evidence_utc || ''
  // biome-ignore lint/correctness/useExhaustiveDependencies: evStamp refetches the metrics when the evidence is regenerated
  useEffect(() => {
    let live = true
    setMetrics(null)
    if (!name) return
    fetchReviewEvidence(year, name)
      .then((r) => {
        if (live) setMetrics(r.metrics)
      })
      .catch(() => {
        if (live) setMetrics(null)
      })
    return () => {
      live = false
    }
  }, [year, name, evStamp])

  if (yErr && !yr) return <EmptyState title="Could not load yearly reviews." body={yErr} />
  if (!yr) return <Skeleton variant="card" count={3} label="Loading yearly reviews" />

  const yearRecs = yr.reviews?.[year] || {}
  const finals = people.filter((n) => yearRecs[n]?.status === 'final').length
  const priorYears = years.filter((y) => y < year && yr.reviews?.[y]?.[name])
  const saveLabel =
    save.state === 'saving'
      ? 'Saving...'
      : save.state === 'dirty'
        ? 'Unsaved changes'
        : save.state === 'error'
          ? `Not saved: ${save.msg}`
          : server?.updated_utc
            ? `Saved ${relTime(server.updated_utc)}`
            : 'Not started'
  const sug = server?.rating_suggestion
  const filled = tplSections.filter((s) => (buf[s.key] || '').trim()).length
  const subtitle = [
    metrics?.title || '',
    metrics?.period
      ? `${fmtDay(metrics.period.start)} to ${fmtDay(metrics.period.end)}${metrics.period.partial ? ' (partial year)' : ''}`
      : '',
  ]
    .filter(Boolean)
    .join(' \u00b7 ')

  return (
    <div className="rv yr">
      {confirmDialog}
      <p className="pp-lede">
        One review per person per year, written from the whole year of evidence: Jira, Teams, email, meetings, my notes and the ledgers.
        Draft it, steer any section in my own words, then mark it final for HR.
      </p>

      <Toolbar label="Review year">
        <Segmented
          label="Review year"
          options={years.map((y) => ({ value: y, label: y }))}
          value={year}
          onChange={(y) => void go({ year: y })}
        />
        <span className="yr-progress">
          <span>
            <b>{finals}</b> of {people.length} final for {year}
          </span>
          <Meter pct={people.length ? (100 * finals) / people.length : 0} tone="success" label={`${finals} of ${people.length} final`} />
        </span>
        <Badge data-tip="Sections come from the review template. It changes when HR sends the official format.">
          Format: {yr.template?.name}
        </Badge>
      </Toolbar>

      {!people.length ? (
        <Card>
          <EmptyState title={`No one was assessed in ${year} yet.`} />
        </Card>
      ) : (
        <>
          <PersonRail label="Pick a person">
            {people.map((n) => {
              const r = yearRecs[n]
              const j = jobs.find((x) => x.year === year && x.person === n && isActive(x))
              const st = j
                ? 'Drafting'
                : r
                  ? r.status === 'final'
                    ? 'Final'
                    : Object.values(r.sections || {}).some((v) => v.trim())
                      ? 'Draft'
                      : 'Empty'
                  : 'Not started'
              return (
                <PersonCard
                  key={n}
                  name={n}
                  selected={n === name}
                  onPick={() => void go({ p: n.split(' ')[0].toLowerCase() })}
                  sub={
                    <>
                      <Pill live={!!j} tone={j ? 'info' : r?.status === 'final' ? 'good' : r && st === 'Draft' ? 'warn' : 'neutral'}>
                        {st}
                      </Pill>
                      {r?.rating ? yr.ratings[r.rating] : 'No rating yet'}
                    </>
                  }
                />
              )
            })}
          </PersonRail>

          <YearStats metrics={metrics} first={first} />

          <div className="yr-layout">
            <Card className="yr-main">
              <div className="yr-main-head">
                <div className="yr-main-titles">
                  <div className="page-eyebrow">{year} annual review</div>
                  <h2 className="mr-name">{name}</h2>
                  {subtitle && <div className="mr-role">{subtitle}</div>}
                </div>
                <div className="yr-actions">
                  <Badge tone={SAVE_TONE[save.state]} dot={save.state !== 'idle'} className="yr-save">
                    {saveLabel}
                  </Badge>
                  {!final && (
                    <Button size="sm" variant={hasContent ? 'secondary' : 'primary'} onClick={draftAll} disabled={!!myJob}>
                      {hasContent ? 'Redraft all' : 'Draft full review'}
                    </Button>
                  )}
                  {!final && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="yr-danger"
                      onClick={resetReview}
                      disabled={!!myJob || (!hasContent && !server?.rating)}
                    >
                      Reset
                    </Button>
                  )}
                  <Button size="sm" variant="secondary" onClick={() => void exportDocx()} disabled={!hasContent}>
                    Export .docx
                  </Button>
                  {final ? (
                    <Button size="sm" variant="ghost" onClick={() => void setStatus('draft')}>
                      Reopen
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant={hasContent ? 'primary' : 'secondary'}
                      onClick={() => void setStatus('final')}
                      disabled={missingForFinal.length > 0 || !!myJob}
                      data-tip={missingForFinal.length ? `Still needed: ${missingForFinal.join(', ')}` : undefined}
                    >
                      Mark final
                    </Button>
                  )}
                </div>
              </div>

              {final && (
                <Tone hue="green" className="pp-note">
                  Final {server?.finalized_utc ? `since ${new Date(server.finalized_utc).toLocaleDateString()}` : ''}. Reopen to edit.
                </Tone>
              )}
              {!final && !hasContent && !myJob && (server?.snapshots?.length || 0) > 0 && (
                <Tone hue="amber" className="pp-note">
                  This review was reset {relTime(server?.snapshots?.[server.snapshots.length - 1]?.at)}.
                  <Button size="sm" variant="ghost" onClick={restore}>
                    Restore what was there before
                  </Button>
                </Tone>
              )}
              {jobErr && (
                <Tone hue="red" className="pp-note" role="alert">
                  {jobErr}
                </Tone>
              )}
              {myJob ? (
                <JobBanner job={myJob} now={now} first={first} titles={yr.sections} />
              ) : (
                lastJob?.state === 'failed' &&
                dismissed !== lastJob.id && (
                  <Tone hue="red" className="pp-note" role="alert">
                    The last {lastJob.mode === 'full' ? 'draft' : lastJob.mode === 'evidence' ? 'evidence refresh' : 'rewrite'} did not
                    finish {relTime(lastJob.finished_utc)}: {lastJob.error}
                    <Button size="sm" variant="ghost" onClick={() => setDismissed(lastJob.id)}>
                      Dismiss
                    </Button>
                  </Tone>
                )
              )}
              {!hasContent && !myJob && !final && (
                <EmptyState
                  compact
                  className="yr-empty"
                  title="Nothing drafted yet."
                  body={`Draft full review pulls everything on record for ${first} this year and writes every section in my voice, with the evidence behind each one. Takes a few minutes. I can steer the whole review first below.`}
                />
              )}

              <OverallSteer
                key={`steer-${key}`}
                value={server?.guidance?._all || ''}
                disabled={final}
                onSave={(v) => run(() => postYearlyReview({ year, person: name, op: 'guidance', guidance: { _all: v } }))}
              />

              {competencyMode ? (
                <OverallScore score={server?.score || null} ratings={yr.ratings} sections={ratedSections} values={sRatings} />
              ) : (
                <RatingField
                  ratings={yr.ratings}
                  value={rating}
                  disabled={final}
                  onChange={setRatingNow}
                  suggested={server?.rating_source === 'draft'}
                  suggestion={server?.rating_source === 'manager' && sug && sug.value !== rating ? yr.ratings[sug.value] || sug.value : ''}
                  rationale={sug?.rationale && server?.rating_source === 'draft' ? sug.rationale : ''}
                />
              )}

              <div className="yr-count">
                {filled} of {tplSections.length} sections written
                {competencyMode ? ` \u00b7 ${ratedSections.filter((s) => sRatings[s.key]).length} of ${ratedSections.length} rated` : ''}
                {server?.draft?.generated_utc ? ` \u00b7 full draft ${relTime(server.draft.generated_utc)}` : ''}
                {server?.draft?.datapoints ? ` from ${server.draft.datapoints.toLocaleString()} datapoints` : ''}
              </div>

              {tplSections.map((s, i) => (
                <SectionCard
                  key={`${key}|${s.key}`}
                  s={s}
                  index={competencyMode ? i + 1 : 0}
                  text={buf[s.key] || ''}
                  rec={server}
                  ratings={yr.ratings}
                  onRate={(v) => setSectionRating(s.key, v)}
                  final={final}
                  busy={busyKeys.has(s.key)}
                  jobRunning={!!myJob}
                  onEdit={(v) => editSection(s.key, v)}
                  onBlur={() => void flush()}
                  onUndo={() => {
                    pending.current = null
                    void run(() => postYearlyReview({ year, person: name, op: 'undo', section: s.key }))
                  }}
                  onSaveSteer={(v) => run(() => postYearlyReview({ year, person: name, op: 'guidance', guidance: { [s.key]: v } }))}
                  onRewrite={(v) => startJob('refine', [s.key], { [s.key]: v })}
                />
              ))}
              <p className="pp-foot">
                Export writes a .docx for Confluence and HR and archives a copy under state/team-performance/yearly-reviews/{year}/. Private
                notes, my analysis and the evidence lists stay on this dashboard.
              </p>
            </Card>

            <div className="yr-side">
              <YearData metrics={metrics} first={first} />
              {server?.analysis && <AnalysisCard a={server.analysis} first={first} />}
              <SourcesCard rec={server} metrics={metrics} busy={!!myJob} onRefresh={() => void startJob('evidence')} />
              <Card>
                <CardHead title="Prior years" level={3} />
                {priorYears.length ? (
                  <div className="yr-prior-list">
                    {priorYears.map((y) => {
                      const r = yr.reviews[y][name]
                      return (
                        <button key={y} type="button" className="yr-prior" onClick={() => void go({ year: y })}>
                          <b>{y}</b>
                          <span>{r.rating ? yr.ratings[r.rating] : 'No rating'}</span>
                          <Badge tone={r.status === 'final' ? 'success' : 'warning'} dot>
                            {r.status === 'final' ? 'Final' : 'Draft'}
                          </Badge>
                        </button>
                      )
                    })}
                  </div>
                ) : (
                  <p className="yr-muted">
                    This is the first year on file for {first}. Next year starts its own record and this one stays readable.
                  </p>
                )}
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function OverallScore({
  score,
  ratings,
  sections,
  values,
}: {
  score: YR['score']
  ratings: Record<string, string>
  sections: ReviewTemplateSection[]
  values: Record<string, string>
}) {
  const label = score?.complete && score.rating ? ratings[score.rating] : 'Not set yet'
  const open = sections.filter((s) => !values[s.key]).map((s) => s.title)
  return (
    <div className="yr-rating field">
      <div className="yr-rating-top">
        <span className="field-label">Overall rating</span>
        <Badge tone="neutral" data-tip="Weighted average of the competency ratings, as on the HR form, rounded to the nearest point.">
          Weighted from {sections.length} competencies
        </Badge>
      </div>
      <div className="yr-score">
        <b>{label}</b>
        {score?.value != null && <span>Weighted score {score.value.toFixed(2)} of 5</span>}
      </div>
      {open.length > 0 && <p className="field-hint">Not rated yet: {open.join(', ')}.</p>}
    </div>
  )
}

function RatingField({
  ratings,
  value,
  disabled,
  onChange,
  suggested,
  suggestion,
  rationale,
}: {
  ratings: Record<string, string>
  value: string
  disabled: boolean
  onChange: (v: string) => void
  suggested: boolean
  suggestion: string
  rationale: string
}) {
  const id = useId()
  return (
    <div className="yr-rating field">
      <div className="yr-rating-top">
        <label className="field-label" htmlFor={id}>
          Overall rating
        </label>
        {suggested && <Badge tone="info">Suggested by the draft</Badge>}
        {suggestion && <small>The draft suggested {suggestion}</small>}
      </div>
      <Select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        options={Object.entries(ratings).map(([k, v]) => ({ value: k, label: v }))}
      />
      {rationale && <p className="field-hint">{rationale}</p>}
    </div>
  )
}

function JobBanner({ job, now, first, titles }: { job: ReviewJob; now: number; first: string; titles: Record<string, string> }) {
  const what =
    job.mode === 'full'
      ? `Drafting ${first}'s full review`
      : job.mode === 'evidence'
        ? `Refreshing ${first}'s evidence`
        : `Rewriting ${job.sections.map((k) => titles[k] || k).join(', ')}`
  const phase =
    job.state === 'queued'
      ? 'Waiting for another draft to finish'
      : job.state === 'evidence'
        ? 'Collecting evidence'
        : job.state === 'drafting'
          ? 'Analyzing and writing'
          : 'Starting'
  return (
    <Tone hue="blue" className="pp-note yr-job" role="status">
      <div className="yr-job-head">
        <Pill live tone="info">
          {phase}
        </Pill>
        <b>{what}</b>
        <span className="yr-job-time">{elapsed(job.started_utc || job.created_utc, now)}</span>
      </div>
      <div className="yr-job-stage">{job.stage}</div>
      {job.mode !== 'evidence' && (
        <div className="yr-job-hint">
          A full draft usually takes four to eight minutes. I can keep working on other people meanwhile. The sections update when it lands.
        </div>
      )}
    </Tone>
  )
}

function OverallSteer({ value, disabled, onSave }: { value: string; disabled: boolean; onSave: (v: string) => Promise<boolean> }) {
  const [open, setOpen] = useState(!!value)
  const [v, setV] = useState(value)
  const [saved, setSaved] = useState(false)
  useEffect(() => setV(value), [value])
  return (
    <div className={`yr-steer-all${open ? ' is-open' : ''}`}>
      <Button
        variant="ghost"
        size="sm"
        className="yr-steer-toggle"
        icon={open ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        Overall steer for this review
        {value && !open && <Badge tone="accent">Set</Badge>}
      </Button>
      {open && (
        <div className="yr-steer-body">
          <Field
            label="Overall steer"
            hint="Anything I want the whole review to reflect: context the data cannot show, what I want emphasized or softened, facts in my own words. Used by every draft and every section rewrite."
          >
            <Textarea
              rows={3}
              value={v}
              disabled={disabled}
              placeholder="Example: He carried the vendor_a SMS cutover mostly alone through the spring. Give that real weight. The escalation issue was early in the year and has improved since July."
              onChange={(e) => {
                setV(e.target.value)
                setSaved(false)
              }}
            />
          </Field>
          <div className="yr-btns">
            <Button
              size="sm"
              variant="secondary"
              disabled={disabled || v === value}
              onClick={async () => {
                if (await onSave(v)) setSaved(true)
              }}
            >
              Save steer
            </Button>
            {saved && <span className="yr-ok">Saved. The next draft or rewrite uses it.</span>}
          </div>
        </div>
      )}
    </div>
  )
}

function SectionCard({
  s,
  index,
  text,
  rec,
  ratings,
  onRate,
  final,
  busy,
  jobRunning,
  onEdit,
  onBlur,
  onUndo,
  onSaveSteer,
  onRewrite,
}: {
  s: ReviewTemplateSection
  index: number
  text: string
  rec: YR | undefined
  ratings: Record<string, string>
  onRate: (v: string) => void
  final: boolean
  busy: boolean
  jobRunning: boolean
  onEdit: (v: string) => void
  onBlur: () => void
  onUndo: () => void
  onSaveSteer: (v: string) => Promise<boolean>
  onRewrite: (v: string) => Promise<boolean>
}) {
  const saved = rec?.guidance?.[s.key] || ''
  const [refine, setRefine] = useState(false)
  const [steer, setSteer] = useState(saved)
  const [showEv, setShowEv] = useState(false)
  const { confirm: ask, dialog: confirmDialog } = useConfirm()
  const textId = useId()
  const rateId = useId()
  useEffect(() => setSteer(saved), [saved])
  const sRating = rec?.section_ratings?.[s.key] || ''
  const sMeta = rec?.section_rating_meta?.[s.key]
  const versions = rec?.versions?.[s.key] || []
  const ev = rec?.evidence?.[s.key] || []
  const meta = rec?.meta?.[s.key]
  const rows = Math.max(s.rows || 5, Math.min(22, Math.ceil(text.length / 95) + text.split('\n').length))
  const evButton =
    ev.length > 0 ? (
      <Button size="sm" variant="ghost" onClick={() => setShowEv(!showEv)} aria-expanded={showEv}>
        {showEv ? 'Hide evidence' : `Evidence (${ev.length})`}
      </Button>
    ) : null
  return (
    <section className={`yr-sec${s.private ? ' is-private' : ''}${busy ? ' is-busy' : ''}`} aria-labelledby={`${textId}-t`}>
      {confirmDialog}
      <div className="yr-sec-head">
        <div className="yr-sec-title">
          <h3 id={`${textId}-t`}>
            <label htmlFor={textId}>
              {index ? `${index}. ` : ''}
              {s.title}
            </label>
          </h3>
          {s.rated && s.weight != null && <Badge>Weight {s.weight}%</Badge>}
          {s.private && <Badge>Private, never exported</Badge>}
          {saved && (
            <Badge tone="accent" data-tip={saved}>
              Steered
            </Badge>
          )}
        </div>
        {busy ? (
          <Pill live tone="info">
            Rewriting...
          </Pill>
        ) : (
          <span className="yr-sec-meta">{metaLabel(meta)}</span>
        )}
      </div>
      <div className="yr-sec-hint">{s.hint}</div>
      {s.rated && (
        <div className="yr-sec-rating">
          <label className="field-label" htmlFor={rateId}>
            Manager rating
          </label>
          <Select
            id={rateId}
            value={sRating}
            disabled={final || busy}
            onChange={(e) => onRate(e.target.value)}
            options={Object.entries(ratings).map(([k, v]) => ({ value: k, label: v }))}
          />
          {sMeta?.source === 'draft' && sRating && <Badge tone="info">Suggested by the draft</Badge>}
          {sMeta?.source === 'manager' && sMeta.suggested && sMeta.suggested !== sRating && (
            <small>The draft suggested {ratings[sMeta.suggested] || sMeta.suggested}</small>
          )}
        </div>
      )}
      <Textarea
        id={textId}
        rows={rows}
        value={text}
        readOnly={final || busy}
        placeholder={
          busy
            ? 'Writing this section from the evidence...'
            : 'Not written yet. Draft the full review or use Refine to write just this section.'
        }
        onChange={(e) => onEdit(e.target.value)}
        onBlur={onBlur}
      />
      {!final && (
        <div className="yr-btns">
          <Button
            size="sm"
            variant={refine ? 'primary' : 'secondary'}
            onClick={() => setRefine(!refine)}
            disabled={busy}
            aria-expanded={refine}
          >
            {text.trim() ? 'Refine' : 'Write this section'}
          </Button>
          {versions.length > 0 && (
            <Button
              size="sm"
              variant="ghost"
              disabled={busy || jobRunning}
              data-tip={`Restore the version from ${relTime(versions[versions.length - 1].at)}`}
              onClick={async () => {
                const ok = await ask({
                  ...confirmText(`Replace this section with the earlier version from ${relTime(versions[versions.length - 1].at)}?`),
                  confirmLabel: 'Replace',
                  danger: true,
                })
                if (ok) onUndo()
              }}
            >
              Undo ({versions.length})
            </Button>
          )}
          {evButton}
        </div>
      )}
      {final && evButton && <div className="yr-btns">{evButton}</div>}
      {refine && !final && (
        <div className="yr-refine">
          <Field label="Steer this section in my words" hint="Saved with the review and applied every time this section is drafted.">
            <Textarea
              rows={3}
              value={steer}
              placeholder="Tell me what to change, add or drop, or paste wording I want kept. Leave it empty to just get a stronger rewrite from the evidence."
              onChange={(e) => setSteer(e.target.value)}
            />
          </Field>
          <div className="yr-btns">
            <Button
              size="sm"
              variant="primary"
              disabled={busy || jobRunning}
              onClick={async () => {
                if (await onRewrite(steer.trim())) setRefine(false)
              }}
            >
              {text.trim() ? 'Rewrite section' : 'Write section'}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={steer.trim() === saved}
              onClick={async () => {
                if (await onSaveSteer(steer.trim())) setRefine(false)
              }}
            >
              Save steer only
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setSteer(saved)
                setRefine(false)
              }}
            >
              Cancel
            </Button>
            {jobRunning && !busy && <span className="yr-sec-meta">Another draft is running for this person.</span>}
          </div>
        </div>
      )}
      {showEv && ev.length > 0 && (
        <ul className="yr-evidence">
          {ev.map((x, i) => (
            <li key={i}>
              <Linked text={x} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

// The year's hero numbers for the picked person, as kit StatTiles (rule 4: the only KPI primitive).
function YearStats({ metrics, first }: { metrics: ReviewMetrics | null; first: string }) {
  if (!metrics) return null
  const j = metrics.jira
  const highPct = j.high_touched ? Math.round((100 * j.high_closed) / j.high_touched) : 0
  return (
    <div className="stat-grid kpi-strip pp-stats yr-stats">
      <StatTile label="Work items completed" value={j.closed} tone="success" />
      <StatTile label="High priority closed" value={`${j.high_closed}/${j.high_touched}`} tone="accent" hint={`${highPct}%`} />
      <StatTile label="Median turnaround" value={`${j.median_days_new_work ?? '-'}d`} tone="info" hint="new work" />
      <StatTile label="Long-standing cleared" value={j.aged_cleared} tone="success" />
      <StatTile label="Open now" value={j.open_now} tone={j.open_over_90d ? 'warning' : 'info'} hint={`${j.open_over_90d} over 90 days`} />
      <StatTile label={`Items ${first} raised`} value={j.reported_by_them} tone="info" />
    </div>
  )
}

function YearData({ metrics, first }: { metrics: ReviewMetrics | null; first: string }) {
  const chart = usePeopleChart()
  if (!metrics) {
    return (
      <Card>
        <CardHead title="The year in data" level={3} />
        <EmptyState compact title={`No evidence pulled for ${first} yet.`} body="The first draft collects it." />
      </Card>
    )
  }
  const j = metrics.jira
  const c = metrics.comms
  const series = metrics.series.map((s) => ({ ...s, label: monthLabel(s.month) }))
  const col = {
    closed: chart.t.status.completed,
    opened: chart.hue('blue'),
    teams: chart.hue('blue'),
    mail: chart.hue('teal'),
    meetings: chart.hue('amber'),
  }
  const tick = { ...chart.axisTick, fontSize: 10.5 }
  return (
    <Card>
      <CardHead title="The year in data" level={3} subtitle={`${fmtDay(metrics.period.start)} to ${fmtDay(metrics.period.end)}`} />
      <div className="pp-chart-title">Work completed and opened by month</div>
      <ResponsiveContainer width="100%" height={150}>
        <BarChart data={series} margin={{ top: 6, right: 4, left: -26, bottom: 0 }}>
          <CartesianGrid stroke={chart.t.grid} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" tick={tick} axisLine={{ stroke: chart.t.grid }} tickLine={false} interval={0} />
          <YAxis tick={tick} axisLine={false} tickLine={false} allowDecimals={false} />
          <Tooltip content={<ChartTip />} cursor={{ fill: chart.t.grid, fillOpacity: 0.35 }} />
          <Bar dataKey="closed" name="Completed" fill={col.closed} radius={[4, 4, 0, 0]} />
          <Bar dataKey="opened" name="Opened" fill={col.opened} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
      <ChartLegend
        items={[
          { label: 'Completed', color: col.closed },
          { label: 'Opened', color: col.opened },
        ]}
      />
      <div className="pp-chart-title">How much we talked, by month</div>
      <ResponsiveContainer width="100%" height={150}>
        <BarChart data={series} margin={{ top: 6, right: 4, left: -26, bottom: 0 }}>
          <CartesianGrid stroke={chart.t.grid} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" tick={tick} axisLine={{ stroke: chart.t.grid }} tickLine={false} interval={0} />
          <YAxis tick={tick} axisLine={false} tickLine={false} allowDecimals={false} />
          <Tooltip content={<ChartTip />} cursor={{ fill: chart.t.grid, fillOpacity: 0.35 }} />
          <Bar dataKey="teams" name="Teams" stackId="c" fill={col.teams} />
          <Bar dataKey="mail" name="Email" stackId="c" fill={col.mail} />
          <Bar dataKey="meetings" name="Meetings" stackId="c" fill={col.meetings} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
      <ChartLegend
        items={[
          { label: 'Teams', color: col.teams },
          { label: 'Email', color: col.mail },
          { label: 'Meetings', color: col.meetings },
        ]}
      />
      <div className="yr-comms">
        <span>
          <b>{c.teams_1on1}</b> 1:1 Teams messages ({c.teams_1on1_them} from {first})
        </span>
        <span>
          <b>{c.group_by_them}</b> group chat posts by {first}
        </span>
        <span>
          <b>{c.mail_from + c.mail_to}</b> emails ({c.mail_from} from {first})
        </span>
        <span>
          <b>{c.meetings}</b> meetings together, {c.one_on_ones} one-on-one
        </span>
      </div>
      {j.top_epics.length > 0 && (
        <>
          <div className="pp-chart-title">Where the work went</div>
          <div className="yr-themes">
            {j.top_epics.slice(0, 7).map((e) => (
              <div key={e.epic} className="yr-theme-row">
                <span>{e.epic}</span>
                <b>{e.closed}</b>
                <small>{e.open ? `${e.open} open` : ''}</small>
              </div>
            ))}
          </div>
        </>
      )}
    </Card>
  )
}

function AnalysisCard({ a, first }: { a: NonNullable<YR['analysis']>; first: string }) {
  const [open, setOpen] = useState(false)
  const conf = (a.confidence || '').toLowerCase().split(/\W/)[0]
  return (
    <Card className="yr-analysis">
      <CardHead
        title={`My read of ${first}'s year`}
        level={3}
        controls={conf ? <Badge tone={CONF_TONE[conf] || 'neutral'} dot>{`${conf} confidence`}</Badge> : undefined}
      />
      <div className={`yr-an-body${open ? ' is-open' : ''}`}>
        {(a.overview || '').split(/\n+/).map((p, i) => (
          <p key={i}>
            <Linked text={p} />
          </p>
        ))}
        {open && (
          <>
            {a.by_period.length > 0 && (
              <>
                <div className="pp-chart-title">Across the year</div>
                {a.by_period.map((p) => (
                  <div key={p.period} className="yr-an-item">
                    <b>{p.period}</b>
                    <p>
                      <Linked text={p.read} />
                    </p>
                  </div>
                ))}
              </>
            )}
            {a.themes.length > 0 && (
              <>
                <div className="pp-chart-title">Patterns</div>
                {a.themes.map((t) => (
                  <div key={t.title} className="yr-an-item">
                    <b>{t.title}</b>
                    <p>
                      <Linked text={t.read} />
                    </p>
                    <div className="yr-an-src">
                      {t.sources.map((s) => (
                        <Badge key={s}>{s}</Badge>
                      ))}
                    </div>
                  </div>
                ))}
              </>
            )}
            {a.on_me.length > 0 && (
              <>
                <div className="pp-chart-title">What is on me</div>
                <ul className="pp-list">
                  {a.on_me.map((x, i) => (
                    <li key={i}>
                      <Linked text={x} />
                    </li>
                  ))}
                </ul>
              </>
            )}
            {a.gaps.length > 0 && (
              <>
                <div className="pp-chart-title">Check before I submit</div>
                <ul className="pp-list">
                  {a.gaps.map((x, i) => (
                    <li key={i}>
                      <Linked text={x} />
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </div>
      <Button size="sm" variant="ghost" className="yr-an-more" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? 'Show less' : 'Quarter by quarter, patterns, what is on me'}
      </Button>
    </Card>
  )
}

function SourcesCard({
  rec,
  metrics,
  busy,
  onRefresh,
}: {
  rec: YR | undefined
  metrics: ReviewMetrics | null
  busy: boolean
  onRefresh: () => void
}) {
  const sources = metrics?.sources || rec?.draft?.sources || []
  const warnings = [...new Set([...(metrics?.warnings || []), ...(rec?.draft?.warnings || [])])]
  return (
    <Card>
      <CardHead
        title="Evidence behind the draft"
        level={3}
        subtitle={metrics ? `${metrics.datapoints.toLocaleString()} datapoints` : undefined}
      />
      {sources.length ? (
        <div className="yr-sources">
          {sources.map((s) => (
            <div key={s.key} className={`yr-src${s.count ? '' : ' is-zero'}`}>
              <b>{s.count.toLocaleString()}</b>
              <span>
                {s.label}
                <small>{s.detail}</small>
              </span>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState compact title="Nothing collected yet." />
      )}
      {warnings.length > 0 && (
        <Tone hue="amber" className="pp-note yr-warn">
          <ul>
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Tone>
      )}
      <div className="yr-src-foot">
        <span>{metrics ? `Collected ${relTime(metrics.generated_utc)}` : ''}</span>
        <Button size="sm" variant="secondary" onClick={onRefresh} disabled={busy}>
          Refresh evidence
        </Button>
      </div>
    </Card>
  )
}
