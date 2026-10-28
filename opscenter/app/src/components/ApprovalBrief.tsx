// The approval brief on every Reviews card that asks me to act: three short paragraphs of plain
// prose, written from the card's own data (approval_brief.py, card_brief.py). PR cards say what the
// change does, what I am approving and what the review raised. Owner applies, privileged deployments
// and runbook delete releases say what the card is, what my click does and the risks with a
// recommendation. A Terraform apply card also carries a deterministic warning when an open PR changes
// the same root. The raw data (rules, plan lines, resource lists, ids) moves into a collapsed
// Details disclosure under it, nothing is dropped. owner 2026-10-15: all data is explained.
// owner 2026-10-20: a non-PR card answers four questions in order, as labelled facts and a table
// before any prose: what is asked, who asked, what exactly I grant, why it needs me and not auto.
import type { ReactNode } from 'react'
import { useState } from 'react'
import type { ApprovalBrief, BriefGrant, BriefLanding, BriefLandingRow, BriefPool, BriefPoolHost } from '../lib/data'
import { postReviewBrief, relTime, useVisibleInterval } from '../lib/data'
import { ErrorLine } from '../pages/reviews/parts'

type Key = 'does' | 'approving' | 'review'
const PR_LABELS: Record<Key, string> = {
  does: 'What this change does',
  approving: 'What you are approving',
  review: 'What the review raised and what I recommend',
}
const CARD_LABELS: Record<Key, string> = {
  does: 'What this is',
  approving: 'What your click does',
  review: 'Risks and what I recommend',
}
const SOURCES: Record<string, string> = {
  owner: 'the saved plan, the root code on main, the open PRs on this root and Entra',
  priv: 'the run, its plan, the gate assessment and the open PRs on its roots',
  release: 'the approved deletes, the main deploy run and the open PRs on the runbooks root',
}

// a PR card (mine to sign off, or an engineer PR) answers the same questions as the non-PR cards.
const isPrKind = (k?: string) => k === 'pr_signoff' || k === 'pr_engineer'

export function ApprovalBriefView({
  repo,
  pr,
  card,
  brief,
  reload,
  detailsLabel = 'Details: rules, plan counts and findings',
  children,
}: {
  repo: 'platform' | 'team'
  pr?: number
  card?: string
  brief?: ApprovalBrief
  reload: () => void
  detailsLabel?: string
  children?: ReactNode
}) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  // While the written brief is on its way, look again every 20 s (paused on a hidden tab).
  useVisibleInterval(reload, brief?.pending || busy ? 20_000 : null)
  const target = card ?? pr
  const rewrite = async () => {
    if (target === undefined) return
    setBusy(true)
    setErr('')
    try {
      await postReviewBrief(repo, target)
      setTimeout(reload, 1500)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  const details = children ? (
    <details className="rh-details">
      <summary>{detailsLabel}</summary>
      <div className="rh-details-body">{children}</div>
    </details>
  ) : null
  if (!brief) return details
  const pr_ = isPrKind(brief.kind)
  const card_ = !!brief.kind && !pr_
  const labels = card_ ? CARD_LABELS : PR_LABELS
  const head = brief.head.slice(0, 8)
  const from = card_ && brief.kind ? SOURCES[brief.kind] : `the PR description, the diff, the Terraform plan and the review for ${head}`
  const status =
    brief.source === 'model'
      ? `Written from ${from}${brief.generated_at ? `, ${relTime(brief.generated_at)}` : ''}.`
      : brief.pending || busy
        ? `Short version from the card data. The full brief is being written from ${from}.`
        : `Short version from the card data.${brief.error ? ` The full brief could not be written (${brief.error}).` : ''}`
  const checked =
    brief.overlap_status === 'ok' && brief.overlap_checked_at ? ` Open PRs on this root checked ${relTime(brief.overlap_checked_at)}.` : ''
  // Only a card that can be acted on gets a written brief, so only it offers a rewrite.
  const canRewrite = !brief.pending && !busy && target !== undefined && (!card_ || brief.source === 'model' || !!brief.error)
  return (
    <>
      <section className="rh-brief" aria-label={card_ ? 'Approval brief' : `Approval brief for PR ${pr}`}>
        {brief.warning && (
          <div className="rh-brief-warn" role="alert">
            <h4 className="rh-h">{brief.wait_for?.length ? 'Do not apply yet' : 'Open PR check'}</h4>
            <p>{brief.warning}</p>
            {(brief.wait_for || []).map((w) => (
              <p key={w.number} className="rh-brief-wait">
                <a href={w.url} target="_blank" rel="noreferrer">
                  Wait for #{w.number}
                </a>{' '}
                <span className="rh-muted">{w.title}</span>
              </p>
            ))}
          </div>
        )}
        {pr_ && brief.ask && brief.landing ? (
          <PrStructuredAsk brief={brief} />
        ) : card_ && brief.ask ? (
          <StructuredAsk brief={brief} />
        ) : (
          (Object.keys(labels) as Key[]).map((k) => (
            <div key={k}>
              <h4 className="rh-h">{labels[k]}</h4>
              <p>{brief[k]}</p>
            </div>
          ))
        )}
        <p className="rh-brief-meta">
          {(brief.pending || busy) && <span className="rh-spin" aria-hidden="true" />}
          <span>
            {status}
            {checked}
          </span>
          {canRewrite && (
            <button type="button" className="rh-textbtn" onClick={rewrite}>
              Rewrite brief
            </button>
          )}
        </p>
        {err && <ErrorLine>{err}</ErrorLine>}
      </section>
      {details}
    </>
  )
}

// The four questions, in order. Everything but the title, origin, notes and review comes from the
// data, so a card is clear before the model has written anything.
function StructuredAsk({ brief }: { brief: ApprovalBrief }) {
  const model = brief.source === 'model'
  const grants = brief.grants || []
  const changes = brief.changes || []
  return (
    <>
      {model && brief.title && <p className="rh-brief-title">{brief.title}</p>}
      <h4 className="rh-h">1. What is being asked</h4>
      <p>{brief.ask}</p>
      <h4 className="rh-h">2. Who is asking</h4>
      <dl className="rh-brief-facts">
        {(brief.asked_by || []).map((r) => (
          <div key={r.label}>
            <dt>{r.label}</dt>
            <dd>{r.value}</dd>
          </div>
        ))}
        <div>
          <dt>Real source</dt>
          <dd>{model && brief.origin ? brief.origin : <span className="rh-muted">{brief.origin || 'Being identified.'}</span>}</dd>
        </div>
      </dl>
      <h4 className="rh-h">3. What exactly you are granting</h4>
      {grants.length > 0 ? <GrantTable grants={grants} /> : !changes.length && <p>No access changes.</p>}
      {changes.length > 0 && (
        <p>
          {grants.length ? 'Also: ' : ''}
          {changes.map((c) => `${c.change} ${c.count} ${c.what}${c.names.length ? ` (${c.names.join(', ')})` : ''}`).join('. ')}.
        </p>
      )}
      {brief.pool && <PoolEvidence pool={brief.pool} />}
      {model && brief.notes && !/^nothing else to know/i.test(brief.notes) && <p className="rh-brief-note">{brief.notes}</p>}
      <h4 className="rh-h">4. Why this needs you and is not auto-approved</h4>
      <p>{brief.why_you}</p>
      {brief.auto && <p className={brief.auto.fits ? 'rh-brief-auto fits' : 'rh-brief-auto'}>{brief.auto.text}</p>}
      <h4 className="rh-h">Risks and what I recommend</h4>
      <p>{brief.review}</p>
      {brief.click && (
        <details className="rh-brief-click">
          <summary>What the buttons do</summary>
          <p>{brief.click}</p>
        </details>
      )}
    </>
  )
}

const num = (n: number | null) => (n === null ? 'n/a' : String(n))

// The PR card, in order: what I am asked to approve, who, what lands at the merge per Terraform root
// (from the PR files, the plan run and the roots file, never the model), why it needs me, the risks
// and what the buttons do. The model writes only what the change does and the recommendation.
function PrStructuredAsk({ brief }: { brief: ApprovalBrief }) {
  const model = brief.source === 'model'
  const land = brief.landing as BriefLanding
  const why = brief.why_rows || []
  const risks = brief.risks || []
  return (
    <>
      <h4 className="rh-h">1. What you are asked to approve</h4>
      <p>{brief.ask}</p>
      <h4 className="rh-h">2. Who is asking</h4>
      <dl className="rh-brief-facts">
        {(brief.asked_by || []).map((r) => (
          <div key={r.label}>
            <dt>{r.label}</dt>
            <dd>{r.value}</dd>
          </div>
        ))}
        <div>
          <dt>What it does</dt>
          <dd>{model ? brief.does : <span className="rh-muted">{brief.pending ? 'Being written.' : brief.does}</span>}</dd>
        </div>
      </dl>
      <h4 className="rh-h">3. What lands at the merge</h4>
      <LandingTable land={land} />
      {land.not_applied.length > 0 && (
        <>
          <h4 className="rh-h">Planned but not applied by this merge</h4>
          <NotApplied rows={land.not_applied} />
        </>
      )}
      <h4 className="rh-h">4. Why this needs you</h4>
      <p>{brief.why_you}</p>
      {why.length > 0 && (
        <div className="rh-grants-wrap">
          <table className="rh-grants">
            <thead>
              <tr>
                <th>Kind</th>
                <th>What</th>
                <th>Severity</th>
                <th>Where</th>
              </tr>
            </thead>
            <tbody>
              {why.map((w, i) => (
                <tr key={`${w.kind}|${w.id}|${w.where}|${i}`}>
                  <td>{w.kind === 'rule' ? 'Rule' : 'Finding'}</td>
                  <td>{w.label}</td>
                  <td>{w.severity}</td>
                  <td className="rh-mono">{w.where || <span className="rh-muted">not located</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h4 className="rh-h">Risks</h4>
      {risks.length > 0 ? (
        <ul>
          {risks.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      ) : (
        <p>No destroy, access grant or open finding on the roots this merge applies.</p>
      )}
      <h4 className="rh-h">What I recommend</h4>
      <p>{brief.review}</p>
      {brief.confirm && (
        <p className="rh-brief-note">
          {brief.confirm.why} The name is <span className="rh-mono">{brief.confirm.name}</span>.
        </p>
      )}
      {brief.click && (
        <details className="rh-brief-click">
          <summary>What the buttons do</summary>
          <p>{brief.click}</p>
        </details>
      )}
    </>
  )
}

function LandingTable({ land }: { land: BriefLanding }) {
  if (land.status === 'no_plan') return <p>No Terraform plan ran for this commit, so the merge applies no planned root.</p>
  if (land.status === 'plan_unread')
    return <p>I could not read the Terraform plan for this commit here. Its result is on the PR's terraform plan checks.</p>
  if (land.status === 'unknown') return <p>I could not read the PR file list, so which roots the merge applies is not known.</p>
  if (land.roots.length === 0) return <p>The merge applies no Terraform root.</p>
  return (
    <div className="rh-grants-wrap">
      <table className="rh-grants">
        <thead>
          <tr>
            <th>Root</th>
            <th>Tier</th>
            <th>Adds</th>
            <th>Changes</th>
            <th>Destroys</th>
            <th>Grants</th>
            <th>Gate that follows</th>
          </tr>
        </thead>
        <tbody>
          {land.roots.map((r) => (
            <tr key={`${r.root}|${r.tier}`}>
              <td>
                {r.root}
                <div className="rh-muted">{r.reason}</div>
              </td>
              <td>{r.tier}</td>
              <td>{num(r.add)}</td>
              <td>{num(r.change)}</td>
              <td>
                {num(r.destroy)}
                {r.destroys_named.map((d) => (
                  <div key={d} className="rh-muted rh-mono">
                    {d}
                  </div>
                ))}
              </td>
              <td>
                {r.grants}
                {r.entra > 0 && <div className="rh-muted">{r.entra} Entra</div>}
              </td>
              <td>{r.gate}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function NotApplied({ rows }: { rows: BriefLandingRow[] }) {
  return (
    <ul>
      {rows.map((r) => (
        <li key={`${r.root}|${r.tier}`}>
          <b>
            {r.root} ({r.tier}):
          </b>{' '}
          {num(r.add)} to add, {num(r.change)} to change, {num(r.destroy)} to destroy. Not applied because {r.reason}.
        </li>
      ))}
    </ul>
  )
}

// The desktop pool roll's host pool read: who is retiring, who is serving, and whether the data says
// the delete is safe. Deterministic, read-only, and a failed read says so.
function PoolEvidence({ pool }: { pool: BriefPool }) {
  const stateOf = (h: BriefPoolHost) => `${h.status ?? 'unknown'}`
  return (
    <>
      <h4 className="rh-h">Host pool right now</h4>
      <p className={pool.status === 'ok' ? 'rh-brief-auto fits' : 'rh-brief-auto'}>{pool.text}</p>
      {pool.pools.map((p) => (
        <div className="rh-grants-wrap" key={p.pool}>
          <table className="rh-grants">
            <caption>{p.pool_name}</caption>
            <thead>
              <tr>
                <th>Host</th>
                <th>Role</th>
                <th>Status</th>
                <th>Drain mode</th>
                <th>Sessions</th>
              </tr>
            </thead>
            <tbody>
              {p.retiring.map((h) => (
                <tr key={h.name}>
                  <td>{h.name}</td>
                  <td>Retiring</td>
                  <td>{stateOf(h)}</td>
                  <td>{h.drained ? 'On' : 'Off'}</td>
                  <td>{h.sessions ?? 'unknown'}</td>
                </tr>
              ))}
              {p.new.map((h) => (
                <tr key={h.name}>
                  <td>{h.name}</td>
                  <td>New</td>
                  <td>{stateOf(h)}</td>
                  <td>{h.allow_new_session ? 'Off (accepting)' : 'On'}</td>
                  <td>{h.sessions ?? 'unknown'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {pool.checked_at && <p className="rh-muted">Read from Azure at {pool.checked_at}.</p>}
    </>
  )
}

function GrantTable({ grants }: { grants: BriefGrant[] }) {
  return (
    <div className="rh-grants-wrap">
      <table className="rh-grants">
        <thead>
          <tr>
            <th>Change</th>
            <th>Who</th>
            <th>Role and what it allows</th>
            <th>Where</th>
          </tr>
        </thead>
        <tbody>
          {grants.map((g, i) => (
            <tr key={`${g.change}|${g.principal_id || g.who}|${g.role}|${i}`}>
              <td>
                <span className={`rh-grant-chg ${g.change}`}>{g.change === 'add' ? 'Adds' : 'Removes'}</span>
                {g.move && <div className="rh-muted">moves, not new</div>}
              </td>
              <td>
                {g.who}
                {g.who_kind && <div className="rh-muted">{g.who_kind.toLowerCase()}</div>}
              </td>
              <td>
                {g.role}
                {g.means && <div className="rh-muted">{g.means}</div>}
              </td>
              <td>{g.on.length ? g.on.map((o) => <div key={o}>{o}</div>) : <span className="rh-muted">not shown in the plan</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
