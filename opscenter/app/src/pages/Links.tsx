// Links: the firm admin consoles and references we use, as a launcher. One compact panel per area
// (mark, name, host per row, the whole row is the link and opens a new tab), flowed into balanced
// CSS columns so no area leaves a hole. Area chips and a text filter narrow it. The weekly reachability check (
// link_health.py) marks a dead link on its tile, and the Link health card lists it with Swap and Remove.
// The list lives in links/catalog.json and the Cmd K palette lists the same links.
import type { ChipOption } from '@kit'
import { ChipGroup, EmptyState, HueTile, IconSearch, Pill, SearchInput, Toolbar } from '@kit'
import { useMemo, useState } from 'react'
import { HubHeader } from '../components/HubHeader'
import type { LinkEdit, LinkHealthRow } from '../lib/data'
import { useLinkHealth, useLocalStore } from '../lib/data'
import type { LinkGroup, LinkItem } from './links/catalog'
import { hostOf, LINK_GROUPS, monogram } from './links/catalog'
import { LinkHealth } from './links/LinkHealth'
import './Links.css'

function matches(l: LinkItem, g: LinkGroup, words: string[]): boolean {
  const hay = `${l.name} ${hostOf(l.url)} ${g.title} ${l.note || ''}`.toLowerCase()
  return words.every((w) => hay.includes(w))
}

function LinkTile({ link, group, health, edit }: { link: LinkItem; group: LinkGroup; health?: LinkHealthRow; edit?: LinkEdit }) {
  const dead = health?.state === 'dead' && !edit
  const retired = !!link.note && /retired/i.test(link.note)
  return (
    <li>
      <a
        className={`lk-tile${dead ? ' tone hue-red' : ''}`}
        href={link.url}
        target="_blank"
        rel="noopener noreferrer"
        data-tip={dead ? `Not reachable: ${health?.reason}. ${link.url}` : link.url}
      >
        <HueTile hue={group.hue} size="sm">
          {monogram(link.name)}
        </HueTile>
        <span className="lk-text">
          <span className="lk-name">{link.name}</span>
          <span className="lk-host">{hostOf(link.url)}</span>
        </span>
        {edit ? (
          <Pill tone="info">PR #{edit.pr} open</Pill>
        ) : dead ? (
          <Pill tone="danger">Not reachable</Pill>
        ) : link.note ? (
          <Pill tone={retired ? 'warning' : 'neutral'}>{retired ? 'Retired' : link.note}</Pill>
        ) : null}
      </a>
    </li>
  )
}

export default function Links() {
  const [q, setQ] = useState('')
  const [areas, setAreas] = useLocalStore<string[]>('links-areas-v1', [])
  const { data: health } = useLinkHealth()
  const key = q.toLowerCase().trim()

  const groups = useMemo(() => {
    const words = key.split(/\s+/).filter(Boolean)
    return LINK_GROUPS.filter((g) => areas.length === 0 || areas.includes(g.id))
      .map((g) => ({ ...g, links: g.links.filter((l) => matches(l, g, words)) }))
      .filter((g) => g.links.length > 0)
  }, [areas, key])
  const options: ChipOption<string>[] = LINK_GROUPS.map((g) => ({ value: g.id, label: g.title, badge: g.links.length }))
  const total = LINK_GROUPS.reduce((n, g) => n + g.links.length, 0)
  const shown = groups.reduce((n, g) => n + g.links.length, 0)
  const deadN = (health?.dead || []).filter((d) => !d.edit).length
  const checked = health?.checked_utc ? new Date(health.checked_utc).toLocaleDateString() : null

  return (
    <div className="lk-page">
      <HubHeader eyebrow="Knowledge" title="Links" subtitle="The admin consoles and references we use. Every link opens in a new tab." />
      <Toolbar label="Filter links">
        <SearchInput value={q} onChange={setQ} placeholder="Filter by name or host" aria-label="Filter links" focusHotkey="f" />
        <span className="lk-count">
          {shown === total ? `${total} links` : `${shown} of ${total} links`}
          {checked && (deadN ? `, ${deadN} not reachable (checked ${checked})` : `, all reachable (checked ${checked})`)}
        </span>
      </Toolbar>
      <LinkHealth />
      <ChipGroup className="lk-areas" label="Areas" options={options} value={areas} onChange={setAreas} />
      {groups.length === 0 ? (
        <EmptyState icon={<IconSearch />} title="No links match" body="Clear the filter or turn an area back on." pose="shrug" />
      ) : (
        <div className="lk-columns">
          {groups.map((g) => (
            <section key={g.id} className="lk-section" aria-labelledby={`lk-h-${g.id}`}>
              <h2 id={`lk-h-${g.id}`} className="lk-heading">
                <span className={`lk-dot hue-${g.hue}`} aria-hidden="true" />
                {g.title}
                <span className="lk-heading-n">{g.links.length}</span>
              </h2>
              <ul className="lk-grid">
                {g.links.map((l) => (
                  <LinkTile key={l.url} link={l} group={g} health={health?.links?.[l.url]} edit={health?.edits?.[l.url]} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
