// Overview tab: one health card per area, with the headline numbers on top.
import type { CategoricalHue } from '@kit'
import { Card, CardHead, HueTile, IconCheckCircle, IconInfo, IconPlay, IconRefresh, IconSparkle, Skeleton, StatTile } from '@kit'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import HermesEngineCard from '../../components/HermesEngineCard'
import { type Area, LEVEL_TONE, usd, useAreas, useGithub, useRunners, useSpend } from './data'
import { StatePill } from './parts'

const LEVEL_LABEL = { good: 'healthy', warn: 'watch', alert: 'action needed' } as const
const LEVEL_HUE: Record<Area['tone'], CategoricalHue | undefined> = { good: undefined, warn: 'amber', alert: 'red' }

/** Identity hue and glyph per area, so the cards are told apart at a glance. */
const AREA_MARK: Record<string, { hue: CategoricalHue; glyph: ReactNode }> = {
  spend: { hue: 'violet', glyph: <IconSparkle /> },
  accounts: { hue: 'blue', glyph: <IconInfo /> },
  jobs: { hue: 'teal', glyph: <IconRefresh /> },
  ci: { hue: 'green', glyph: <IconPlay /> },
  github: { hue: 'amber', glyph: <IconCheckCircle /> },
}

function AreaCard({ a }: { a: Area }) {
  const mark = AREA_MARK[a.key]
  return (
    <Card tone={LEVEL_HUE[a.tone]} className="infra-area">
      <CardHead
        title={a.label}
        subtitle={a.headline}
        icon={
          mark ? (
            <HueTile hue={mark.hue} size="md">
              {mark.glyph}
            </HueTile>
          ) : undefined
        }
        controls={<StatePill tone={LEVEL_TONE[a.tone]}>{LEVEL_LABEL[a.tone]}</StatePill>}
      />
      {a.detail.length > 0 ? (
        <ul className="infra-list infra-area-list">
          {a.detail.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      ) : (
        <p className="infra-muted infra-area-list">Nothing needs attention.</p>
      )}
      <div className="infra-area-foot">
        <Link to={a.to} className="btn" data-variant="ghost" data-size="sm">
          Open {a.label} &rarr;
        </Link>
      </div>
    </Card>
  )
}

export default function OverviewTab() {
  const { areas, loading } = useAreas()
  const spend = useSpend().data
  const fleet = useRunners().data
  const gh = useGithub().data
  const issues = areas.reduce((n, a) => n + a.issues, 0)
  const online = fleet ? fleet.runners.filter((r) => r.status === 'online').length : null
  return (
    <div className="infra-stack">
      <div className="stat-grid">
        <StatTile value={issues} label="items need attention" tone={issues ? 'danger' : 'success'} />
        <StatTile value={spend ? usd(spend.totals.billed_mtd) : '-'} label="Hermes billed to Enterprise, month" hue="violet" />
        <StatTile
          value={fleet ? `${online}/${fleet.runners.length}` : '-'}
          label="CI runners online"
          tone={fleet && online === fleet.runners.length && online ? 'success' : 'danger'}
        />
        <StatTile value={gh ? gh.prs.length : '-'} label="open PRs" hue="blue" />
      </div>
      <HermesEngineCard />
      <div className="infra-grid">
        {areas.map((a) => (
          <AreaCard key={a.key} a={a} />
        ))}
        {loading &&
          Array.from({ length: Math.max(1, 5 - areas.length) }, (_, i) => (
            <Card key={i}>
              <Skeleton variant="card" label={i === 0 ? 'Fetching remaining feeds' : 'Loading'} />
            </Card>
          ))}
      </div>
    </div>
  )
}
