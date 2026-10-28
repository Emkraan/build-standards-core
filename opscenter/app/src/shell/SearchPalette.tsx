// Global search on the kit command palette (web-ui.md sections 13 and 25). Cmd or Ctrl and K, or
// /, opens it from anywhere. It lists the pages, tabs, open Action Center items, the 1:1 people and
// the theme commands, and as I type it asks the same /api/search the Search page uses. The first
// row always runs the full search on /search (which adds Jira and the file viewer).
import type { PaletteItem } from '@kit'
import { CommandPalette, IconSearch, openCommandPalette, useShell, useShortcut, useTheme } from '@kit'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { IconFile, IconLink, IconPalette, IconUser, IconZap } from '../components/icons'
import type { SearchHit } from '../lib/data'
import { fetchSearch, hermesSessionUrl, useData, useOneOnOnes } from '../lib/data'
import { hostOf, LINK_GROUPS } from '../pages/links/catalog'
import { NAV } from './nav'

const KIND_LABEL: Record<SearchHit['kind'], string> = {
  action: 'Action item',
  draft: 'Draft',
  plan: 'Plan',
  'one-on-one': '1:1 topic',
  file: 'File',
  session: 'Hermes session',
}

// The kit palette filters a fixed list and does not report the query, so the shell reads it from
// the palette's input to fetch live results (kit gap, see the shell notes in the report).
function usePaletteQuery(): [string, (v: string) => void] {
  const [q, setQ] = useState('')
  useEffect(() => {
    const onInput = (e: Event) => {
      const t = e.target
      if (t instanceof HTMLInputElement && t.classList.contains('palette-input')) setQ(t.value)
    }
    document.addEventListener('input', onInput, true)
    return () => document.removeEventListener('input', onInput, true)
  }, [])
  return [q, setQ]
}

export default function SearchPalette() {
  const nav = useNavigate()
  const shell = useShell()
  const { setChoice } = useTheme()
  const { data: ac } = useData<{ items?: { fp: string; title: string; priority?: string }[] }>('action-center.json')
  const { data: oo } = useOneOnOnes()
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = usePaletteQuery()
  const q = open ? typed.trim() : ''
  const [hits, setHits] = useState<{ q: string; items: SearchHit[] }>({ q: '', items: [] })

  useShortcut({ id: 'oc.search.slash', keys: '/', description: 'Open search', group: 'General', handler: () => openCommandPalette() })

  // Live results from the shared search API, debounced while typing.
  useEffect(() => {
    if (q.length < 2) return undefined
    const ac2 = new AbortController()
    const t = window.setTimeout(() => {
      fetchSearch(q, ac2.signal)
        .then((r) => {
          const all = Object.values(r.groups).flatMap((g) => g || [])
          all.sort((a, b) => b.score - a.score)
          setHits({ q, items: all.slice(0, 8) })
        })
        .catch(() => undefined)
    }, 220)
    return () => {
      window.clearTimeout(t)
      ac2.abort()
    }
  }, [q])

  const items = useMemo<PaletteItem[]>(() => {
    const out: PaletteItem[] = []
    if (q) {
      out.push({
        id: 'search-all',
        label: `Search everything for "${q}"`,
        kind: 'Search',
        keywords: [q],
        icon: <IconSearch />,
        onSelect: () => nav(`/search?q=${encodeURIComponent(q)}`),
      })
      if (hits.q === q) {
        hits.items.forEach((h, i) => {
          const sid = h.session_id
          out.push({
            id: `hit-${i}-${h.kind}-${h.title}`,
            label: h.title || sid || h.path || 'Result',
            kind: KIND_LABEL[h.kind] || 'Result',
            keywords: [q],
            icon: h.kind === 'action' ? <IconZap /> : h.kind === 'one-on-one' ? <IconUser /> : <IconFile />,
            onSelect: () => {
              if (h.kind === 'session' && sid) window.location.href = hermesSessionUrl(sid)
              else if (h.route) nav(h.route)
              else nav(`/search?q=${encodeURIComponent(q)}`)
            },
          })
        })
      }
    }
    for (const n of NAV) {
      out.push({ id: `nav-${n.to}`, label: n.label, kind: 'Page', icon: n.icon, keywords: [n.to], onSelect: () => nav(n.to) })
      for (const p of n.pages || []) {
        out.push({ id: `nav-${p.to}`, label: p.label, kind: 'Page', icon: n.icon, keywords: [p.to], onSelect: () => nav(p.to) })
      }
    }
    out.push({ id: 'nav-/search', label: 'Search page', kind: 'Page', icon: <IconSearch />, onSelect: () => nav('/search') })
    // The Links page catalog: picking one opens the console in a new tab.
    for (const g of LINK_GROUPS) {
      for (const l of g.links) {
        out.push({
          id: `link-${l.url}`,
          label: l.name,
          kind: 'Link',
          keywords: [hostOf(l.url), g.title],
          icon: <IconLink />,
          onSelect: () => window.open(l.url, '_blank', 'noopener,noreferrer'),
        })
      }
    }
    for (const p of oo?.people || []) {
      out.push({
        id: `person-${p.first}`,
        label: `1:1 with ${p.first}`,
        kind: 'Person',
        keywords: [p.name],
        icon: <IconUser />,
        onSelect: () => nav(`/people?p=${p.first.toLowerCase()}`),
      })
    }
    for (const it of ac?.items || []) {
      out.push({
        id: `ac-${it.fp}`,
        label: it.title,
        kind: 'Action item',
        keywords: it.priority ? [it.priority] : undefined,
        icon: <IconZap />,
        onSelect: () => nav(`/action?item=${encodeURIComponent(it.fp)}`),
      })
    }
    out.push(
      { id: 'theme-light', label: 'Theme: light', kind: 'Command', icon: <IconPalette />, onSelect: () => setChoice('light') },
      { id: 'theme-dark', label: 'Theme: dark', kind: 'Command', icon: <IconPalette />, onSelect: () => setChoice('dark') },
      {
        id: 'theme-system',
        label: 'Theme: follow the system',
        kind: 'Command',
        icon: <IconPalette />,
        onSelect: () => setChoice('system'),
      },
    )
    if (shell) {
      out.push({
        id: 'rail-pin',
        label: shell.pinned ? 'Unpin the sidebar' : 'Pin the sidebar open',
        kind: 'Command',
        keywords: ['rail', 'sidebar'],
        onSelect: shell.togglePin,
      })
    }
    return out
  }, [q, hits, ac, oo, nav, setChoice, shell])

  return (
    <CommandPalette
      items={items}
      onOpenChange={(v) => {
        setTyped('')
        setOpen(v)
      }}
      label="Search everything"
      placeholder="Search pages, links, action items, people, files and sessions"
      emptyText="No matches"
    />
  )
}
