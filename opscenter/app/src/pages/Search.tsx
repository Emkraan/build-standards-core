// Global search: one box, every source. Local sources (action items open and
// completed, 1:1 topics, state/engineering/reference files, the
// Hermes chat history) come back in one call; Jira is queried
// live in parallel. Each hit links to where it lives.
// Kit build: kit Input, a Segmented source filter, result Cards with a CardHead per source,
// kit Pills and Badges on hits, and a kit Modal for the file viewer.
import type { SegmentedOption } from '@kit'
import { Badge, Card, CardHead, EmptyState, IconSearch, Input, Modal, Pill, Segmented, Skeleton } from '@kit'
import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { HubHeader } from '../components/HubHeader'
import { LivePill, LoadError } from '../components/StateBlocks'
import type { JiraHit, SearchHit, SearchResult } from '../lib/data'
import { fetchFileText, fetchJiraSearch, fetchSearch, hermesSessionUrl } from '../lib/data'
import './Search.css'

const GROUPS: { kind: SearchHit['kind']; label: string }[] = [
  { kind: 'action', label: 'Action items' },
  { kind: 'session', label: 'Hermes sessions' },
  { kind: 'one-on-one', label: '1:1 topics' },
  { kind: 'file', label: 'State and engineering files' },
]

function Mark({ text, terms }: { text: string; terms: string[] }) {
  if (!text || !terms.length) return <>{text}</>
  const esc = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')
  const parts = text.split(new RegExp(`(${esc})`, 'ig'))
  return <>{parts.map((p, i) => (i % 2 ? <mark key={i}>{p}</mark> : p))}</>
}

const short = (iso?: string | number) => {
  if (!iso) return ''
  const d = typeof iso === 'number' ? new Date(iso * 1000) : new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function Search() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') || ''
  const [input, setInput] = useState(q)
  const [res, setRes] = useState<SearchResult | null>(null)
  const [jira, setJira] = useState<JiraHit[] | null>(null)
  const [jiraErr, setJiraErr] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [only, setOnly] = useState<string>('all')
  const [viewer, setViewer] = useState<{ path: string; text: string } | null>(null)
  const box = useRef<HTMLInputElement>(null)

  useEffect(() => setInput(q), [q])
  useEffect(() => {
    box.current?.focus()
  }, [])

  useEffect(() => {
    if (q.trim().length < 2) {
      setRes(null)
      setJira(null)
      return
    }
    const ac = new AbortController()
    setBusy(true)
    setErr(null)
    setJira(null)
    setJiraErr(null)
    fetchSearch(q, ac.signal)
      .then(setRes)
      .catch((e) => {
        if (!ac.signal.aborted) setErr(String(e))
      })
      .finally(() => {
        if (!ac.signal.aborted) setBusy(false)
      })
    fetchJiraSearch(q, ac.signal)
      .then(setJira)
      .catch((e) => {
        if (!ac.signal.aborted) setJiraErr(String(e.message || e))
      })
    return () => ac.abort()
  }, [q])

  // Debounced live search as I type.
  useEffect(() => {
    if (input === q) return
    const id = window.setTimeout(() => setParams(input.trim() ? { q: input } : {}, { replace: true }), 350)
    return () => window.clearTimeout(id)
  }, [input, q, setParams])

  const terms = res?.terms || []
  const count = (k: string) => (k === 'jira' ? jira?.length || 0 : res?.groups[k as SearchHit['kind']]?.length || 0)
  const total = (res?.total || 0) + (jira?.length || 0)

  const openFile = (path: string) => {
    fetchFileText(path)
      .then((text) => setViewer({ path, text }))
      .catch((e) => setViewer({ path, text: String(e) }))
  }

  const filterOptions: SegmentedOption<string>[] = [
    { value: 'all', label: `All ${total ? total : ''}`.trim() },
    ...[...GROUPS, { kind: 'jira', label: 'Jira' }]
      .filter((g) => count(g.kind) > 0)
      .map((g) => ({ value: g.kind, label: `${g.label} ${count(g.kind)}` })),
  ]

  const renderHit = (h: SearchHit, i: number) => {
    let title: React.ReactNode = <Mark text={h.title || h.session_id || ''} terms={terms} />
    if (h.kind === 'session' && h.session_id) {
      title = (
        <a href={hermesSessionUrl(h.session_id)} data-tip="Open thread in Hermes">
          {title}
        </a>
      )
    } else if (h.route) {
      title = <Link to={h.route}>{title}</Link>
    } else if (h.path) {
      title = (
        <button type="button" className="srch-link" onClick={() => openFile(h.path ?? '')}>
          {title}
        </button>
      )
    }
    return (
      <li key={`${h.kind}-${i}`} className="srch-hit">
        <div className="srch-hit-row">
          <span className="srch-title">{title}</span>
          {h.status && (
            <Pill tone={h.status === 'resolved' ? 'success' : h.status === 'open' ? 'info' : 'neutral'} dot>
              {h.status === 'resolved' ? 'completed' : h.status}
            </Pill>
          )}
          {h.archived && <Pill>archived</Pill>}
          {h.group && <span className="srch-meta">{h.group}</span>}
          {h.person && <span className="srch-meta">{h.person}</span>}
          {h.matches ? (
            <span className="srch-meta">
              {h.matches} mention{h.matches === 1 ? '' : 's'}
            </span>
          ) : null}
          {h.at && <span className="srch-meta">{short(h.at)}</span>}
          {h.kind === 'action' && h.session_id && (
            <a className="srch-meta srch-meta-link" href={hermesSessionUrl(h.session_id)}>
              Hermes thread
            </a>
          )}
        </div>
        {h.snippet && h.snippet !== 'Title match' && (
          <div className="srch-snip">
            <Mark text={h.snippet} terms={terms} />
          </div>
        )}
        {h.path && <div className="srch-path">{h.path.replace(/^\/Users\/[^/]+/, '~')}</div>}
      </li>
    )
  }

  const searching = q.trim().length >= 2

  return (
    <div className="hub">
      <HubHeader eyebrow="Find" title="Search" subtitle="One box across action items, Hermes sessions, 1:1 topics, state files and Jira." />
      <div className="hub-body">
        <form
          className="srch-form"
          role="search"
          onSubmit={(e) => {
            e.preventDefault()
            setParams(input.trim() ? { q: input } : {})
          }}
        >
          <span className="srch-icon" aria-hidden="true">
            <IconSearch size={18} />
          </span>
          <Input
            ref={box}
            type="search"
            className="srch-input"
            aria-label="Search everything"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder='Search everything: tickets (a key like PROJ-123), people, systems, phrases ("change freeze")...'
          />
        </form>
        {searching && (
          <div className="srch-filters">
            <Segmented label="Filter by source" options={filterOptions} value={only} onChange={setOnly} />
            {busy && <LivePill>searching...</LivePill>}
          </div>
        )}
        {err && (
          <Card>
            <LoadError title="Search failed" error={err} />
          </Card>
        )}
        {!searching && (
          <Card>
            <EmptyState
              icon={<IconSearch />}
              hue="blue"
              title="Type at least two characters."
              body="Quotes keep a phrase together; every word must match."
            />
          </Card>
        )}
        {searching && busy && !res && !err && (
          <div className="srch-results">
            <Skeleton variant="card" label="Searching" />
            <Skeleton variant="card" />
          </div>
        )}
        {res && total === 0 && !busy && jira !== null && (
          <Card>
            <EmptyState pose="shrug" title={`No matches for "${q}".`} />
          </Card>
        )}

        <div className="srch-results">
          {(only === 'all' || only === 'jira') && (jira?.length || jiraErr) ? (
            <Card>
              <CardHead
                title="Jira"
                subtitle={jiraErr ? 'live search unavailable' : `${jira?.length} issue(s), live`}
                controls={jira?.length ? <Badge>{jira.length}</Badge> : undefined}
              />
              {jiraErr && <p className="srch-note">{jiraErr}</p>}
              <ul className="srch-list">
                {(jira || []).map((j) => (
                  <li key={j.key} className="srch-hit">
                    <div className="srch-hit-row">
                      <a className="srch-title" href={j.url} target="_blank" rel="noreferrer">
                        <span className="tkt">{j.key}</span> <Mark text={j.summary} terms={terms} />
                      </a>
                      <Pill>{j.status}</Pill>
                      <span className="srch-meta">
                        {j.type}
                        {j.assignee ? ` \u00b7 ${j.assignee}` : ''}
                      </span>
                      <span className="srch-meta">{short(j.updated)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
          {GROUPS.filter((g) => (only === 'all' || only === g.kind) && count(g.kind) > 0).map((g) => (
            <Card key={g.kind}>
              <CardHead title={g.label} subtitle={`${count(g.kind)} result(s)`} controls={<Badge>{count(g.kind)}</Badge>} />
              <ul className="srch-list">{(res?.groups[g.kind] || []).map(renderHit)}</ul>
            </Card>
          ))}
        </div>
      </div>

      <Modal
        open={!!viewer}
        onClose={() => setViewer(null)}
        size="xl"
        hue="teal"
        title={viewer?.path.split('/').pop() ?? ''}
        subtitle={viewer?.path.replace(/^\/Users\/[^/]+/, '~')}
        cancelLabel="Close"
        className="srch-viewer"
      >
        {viewer && (
          <pre className="srch-pre">
            {viewer.text.split('\n').map((ln, i) => (
              <div key={i} className={terms.some((t) => ln.toLowerCase().includes(t)) ? 'hit' : ''}>
                <Mark text={ln} terms={terms} />
                {'\n'}
              </div>
            ))}
          </pre>
        )}
      </Modal>
    </div>
  )
}
