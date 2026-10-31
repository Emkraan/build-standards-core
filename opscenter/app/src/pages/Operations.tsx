// Operations: everything we run, in sections with one tab per item (/operations/<section>/<item>, DESIGN.md 12.46). One hub for
// builds, scheduled jobs, CI, backup, spend and the core: the Overview is one card per item, grouped under the same section
// titles, and every number on the Overview, the tabs and the rail comes from the server's problem list (GET /api/badges,
// `problems`). The client applies no threshold of its own. Old /builds, /infra/* and /core links redirect here (App.tsx).
import { EmptyState, HubHeader, HubOverview, hubPath, resolveHubRoute, Skeleton } from '@kit'
import type { AreaCardData, AreaTone } from '@kit'
import type { ComponentType } from 'react'
import { Navigate, useLocation, useNavigate, useParams } from 'react-router-dom'
import HermesEngineCard from '../components/HermesEngineCard'
import { useBadges, useBuilds } from '../lib/data'
import type { ProblemItem, ProblemTone } from '../lib/data'
import CoreConsumption from './CoreConsumption'
import Ci from './infra/Ci'
import Github from './infra/Github'
import Jobs from './infra/Jobs'
import LiveJobs from './infra/LiveJobs'
import Spend from './infra/Spend'
import BuildTab from './operations/Builds'
import { OPERATIONS_BASE, operationsSections } from './operations/sections'
import './Infrastructure.css'

function CiAndGithub() {
  return (
    <div className="infra-stack">
      <LiveJobs />
      <Ci />
      <Github />
    </div>
  )
}

const BODY: Record<string, ComponentType> = {
  jobs: Jobs,
  ci: CiAndGithub,
  spend: Spend,
  core: CoreConsumption,
}

const TONE: Record<ProblemTone, AreaTone> = { needs_me: 'alert', worth_a_look: 'warn', healthy: 'good' }

function areaOf(i: ProblemItem, to: string): AreaCardData {
  return { key: i.item, label: i.label, to, tone: TONE[i.tone], live: i.running, headline: i.headline, detail: i.details }
}

export default function Operations() {
  const { section, item } = useParams()
  const { search, hash } = useLocation()
  const nav = useNavigate()
  const { data: badges } = useBadges()
  const { data: builds } = useBuilds()
  const problems = badges?.problems
  const sections = operationsSections(builds, problems)
  const route = resolveHubRoute(OPERATIONS_BASE, sections, section, item)
  // The build items exist once the pipelines feed has loaded: wait for it before sending a deep link to the Overview.
  if (route.kind === 'redirect' && section === 'builds' && !builds) return <Skeleton />
  if (route.kind === 'redirect') return <Navigate to={`${route.to}${search}${hash}`} replace />
  const needs = problems?.counts.needs_me ?? 0
  const areas = (problems?.items ?? []).map((i) => areaOf(i, hubPath(OPERATIONS_BASE, sections, i.item)))
  let body
  if (route.kind === 'overview') {
    body = (
      <div className="infra-stack">
        <HermesEngineCard />
        {problems && problems.items.length === 0 ? (
          <EmptyState compact pose="idle" title="Nothing is configured to run here yet." />
        ) : (
          <HubOverview
            sections={sections}
            areas={areas}
            summary={
              problems
                ? needs
                  ? `${needs} area${needs === 1 ? '' : 's'} need${needs === 1 ? 's' : ''} me. The counts are the same list as the Operations badge in the rail.`
                  : 'Nothing needs me. The counts are the same list as the Operations badge in the rail.'
                : 'Checking every area.'
            }
          />
        )}
      </div>
    )
  } else if (route.section.key === 'builds') {
    body = <BuildTab product={route.item.key} />
  } else {
    const Body = BODY[route.item.key]
    body = Body ? <Body /> : null
  }
  return (
    <div className="hub infra operations">
      <HubHeader
        eyebrow="Operate"
        title="Operations"
        subtitle="Builds, scheduled jobs, CI and backup, spend and the core: what we run and whether it is healthy."
        base={OPERATIONS_BASE}
        sections={sections}
        section={section}
        item={item}
        onNavigate={(path) => nav(path)}
      />
      <div className="hub-body">{body}</div>
    </div>
  )
}
