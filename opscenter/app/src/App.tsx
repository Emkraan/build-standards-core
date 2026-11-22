// The Ops Center shell on the shared kit (the web-ui-standard doc): the hover rail
// with pin and the gliding active marker, the header on every page, the live feed strip, the build
// card with release notes, the command palette, the shortcut sheet, tooltips and toasts.
import type { KitLinkProps, ReleaseNote } from '@kit'
import {
  AppShell,
  BuildCard,
  FeedStrip,
  Header,
  NavGroup,
  NavItem,
  PageErrorBoundary,
  Rail,
  SearchTrigger,
  Skeleton,
  ThemeToggle,
  TooltipLayer,
  useShortcut,
} from '@kit'
import type { ReactNode } from 'react'
import { lazy, Suspense, useEffect } from 'react'
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom'
// Shared sheets first, so the page sheets imported by the pages below win ties.
import './App.css'
import './shell.css'
import { useActionCounts } from './lib/counts'
import { useApprovals, useData, useExtensions, useJiraNeedsMe, useNow, useOneOnOnes } from './lib/data'
import { extensionRoute, pagesAll } from './lib/extensions'
import { APP_SUBTITLE, NAV_LAYOUT } from './lib/config'
import { breadcrumb, groupOf } from './lib/navLayout'
import ActionHub from './pages/ActionHub'
import { movedTo, platformTarget } from './lib/legacyRoutes'
import { redirectOld } from './pages/operations/routes'
import { EntChip, NextOneOnOne, SyncChip, useFeed } from './shell/HeaderBits'
import type { BadgeKey, NavDef } from './shell/nav'
import { peopleRoute, peopleSlot } from './lib/peopleSlot'
import { trackerRoute, trackerSlot } from './lib/trackerSlot'
import { groupsFor, navFor } from './shell/nav'
import MobileTabBar from './components/MobileTabBar'
import SearchPalette from './shell/SearchPalette'

// Every page but the landing hub loads on demand (the charts library alone is about a third of the
// app and only the team and spend pages use it). After first paint the rest prefetch while idle, so
// switching pages stays instant.
const PAGES = {
  Plans: () => import('./pages/Plans'),
  EngBacklog: () => import('./pages/EngBacklog'),
  Operations: () => import('./pages/Operations'),
  JiraHub: () => import('./pages/JiraHub'),
  Knowledge: () => import('./pages/Knowledge'),
  Links: () => import('./pages/Links'),
  OneOnOnes: () => import('./pages/OneOnOnes'),
  Reviews: () => import('./pages/Reviews'),
  Search: () => import('./pages/Search'),
  TeamHub: () => import('./pages/TeamHub'),
}
const Plans = lazy(PAGES.Plans)
const ExtensionPage = lazy(() => import('./components/ExtensionPage'))
const EngBacklog = lazy(PAGES.EngBacklog)
const Operations = lazy(PAGES.Operations)
const JiraHub = lazy(PAGES.JiraHub)
const Knowledge = lazy(PAGES.Knowledge)
const Links = lazy(PAGES.Links)
const OneOnOnes = lazy(PAGES.OneOnOnes)
const Reviews = lazy(PAGES.Reviews)
const Search = lazy(PAGES.Search)
const TeamHub = lazy(PAGES.TeamHub)
// The banners show only while something is wrong (engine restart, fallback model, browser), so they load after first paint instead of with the shell.
const HermesRestartBanner = lazy(() => import('./components/HermesRestartBanner'))
const FallbackBanner = lazy(() => import('./components/FallbackBanner'))
const BrowserBanner = lazy(() => import('./components/BrowserBanner'))
const SlotNeeded = lazy(() => import('./components/SlotNeeded'))

function usePrefetchPages() {
  useEffect(() => {
    const go = () => {
      for (const load of Object.values(PAGES)) load().catch(() => {})
    }
    const w = window as Window & { requestIdleCallback?: (cb: () => void) => number }
    if (w.requestIdleCallback) w.requestIdleCallback(go)
    else window.setTimeout(go, 1500)
  }, [])
}

interface Manifest {
  generated_et: string
}

// What's new for the build card, written at build time by tools/gen-changelog.mjs from the app's
// git history. Missing file = an empty list and a disabled card (the build script fails first).
const generated = import.meta.glob<ReleaseNote[]>('./generated/changelog.json', { eager: true, import: 'default' })
const RELEASES: ReleaseNote[] = Object.values(generated)[0] ?? []

// The kit renders nav links through this adapter so they stay HashRouter routes.
function RouterLink({ href, ...rest }: KitLinkProps) {
  return <Link to={href} {...rest} />
}

function badgeTip(key: BadgeKey, n: number): string {
  switch (key) {
    case 'action':
      return `${n} Action Center items need me`
    case 'reviews':
      return `${n} need me`
    case 'jira':
      return `${n} Jira items need me (approvals and sprint tickets)`
    case 'knowledge':
      return `${n} Knowledge items need me (proposals to approve and documentation gaps)`
    case 'debt':
      return `${n} improvements waiting on my decision`
    case 'oneonone':
      return `${n} open 1:1 topics`
    case 'operations':
      return `${n} operations problems`
    case 'links':
      return `${n} links on the Links page no longer work (swap or remove them there)`
  }
}

// Old /builds, /core and /infra/<tab> links land on their item in Operations with the query string kept.
function OldRoute() {
  const { pathname, search, hash } = useLocation()
  return <Navigate to={redirectOld(pathname, search, hash) ?? '/platform'} replace />
}

// The people pages sit behind the people slot (opscenter/DESIGN.md 12.14): while it is off the page says it needs the slot (12.72),
// before the first answer it waits, and an unreachable server still shows the page, which reports its own failure.
function PeopleGate({ children }: { children: ReactNode }) {
  const { data, error } = useOneOnOnes()
  const { pathname } = useLocation()
  const act = peopleRoute(peopleSlot(data), !!error)
  if (act === 'off') return <SlotNeeded slot="people" page={pathname.startsWith('/team') ? 'Team' : '1:1s'} />
  if (act === 'wait') return <Skeleton variant="lines" count={6} label="Loading page" />
  return <>{children}</>
}

// /jira and /operations moved to /work and /platform (12.73): the old address lands on the same tab, query and hash kept.
function MovedRoute() {
  const { pathname, search, hash } = useLocation()
  return <Navigate to={movedTo(pathname, search, hash) ?? '/action'} replace />
}

// /platform is the Platform hub. Its old meaning, a redirect into the platform review lane, survives for the three lane tabs.
function PlatformEntry() {
  const { section } = useParams()
  const t = platformTarget(section)
  return t.kind === 'lane' ? <Navigate to={t.to} replace /> : <Operations />
}

// The work tracking pages sit behind the tracker slot (opscenter/DESIGN.md 12.67), the same way: off, the page says it needs the slot.
function TrackerGate({ children }: { children: ReactNode }) {
  const { data, error } = useJiraNeedsMe()
  const act = trackerRoute(trackerSlot(data), !!error)
  if (act === 'off') return <SlotNeeded slot="tracker" page="Work tracking" />
  if (act === 'wait') return <Skeleton variant="lines" count={6} label="Loading page" />
  return <>{children}</>
}

// A page a consumer added: the route waits for the manifest, and leaves for the home route when the manifest does not name the page, so a
// removed page or a typed address never shows a broken one. The key remounts the page when the address changes to another extension.
function ExtensionRoute() {
  const { id = '' } = useParams()
  const { data, error } = useExtensions()
  const act = extensionRoute(data, id, !!error)
  if (act === 'leave') return <Navigate to="/action" replace />
  if (act === 'wait') return <Skeleton variant="lines" count={6} label="Loading page" />
  return <ExtensionPage key={id} id={id} />
}

function GoShortcut({ id, keys, label, to }: { id: string; keys: string; label: string; to: string }) {
  const nav = useNavigate()
  useShortcut({ id, keys, description: `Go to ${label}`, group: 'Navigation', handler: () => nav(to) })
  return null
}

// G then a letter jumps to a page (the ? sheet lists them).
function Shortcuts({ people, tracker }: { people: boolean; tracker: boolean }) {
  return (
    <>
      {groupsFor(people, tracker).flatMap((g) => g.items).filter((n) => n.key).map((n) => (
        <GoShortcut key={n.key} id={`oc.go.${n.key}`} keys={`g ${n.key}`} label={n.label} to={n.to} />
      ))}
      <GoShortcut id="oc.go.search" keys="g s" label="the Search page" to="/search" />
    </>
  )
}

export default function App() {
  const { pathname } = useLocation()
  const { data: manifest } = useData<Manifest>('manifest.json')
  const counts = useActionCounts()
  usePrefetchPages()
  const { data: oo, error: ooErr } = useOneOnOnes()
  const people = peopleSlot(oo) === 'on'
  const { data: approvals } = useApprovals()
  const { data: needsMe } = useJiraNeedsMe()
  const tracker = trackerSlot(needsMe) !== 'off'
  // Pages a consumer added through the extension manifest. Only a working source adds any, and a failed one adds none (the rail never guesses).
  const { data: extensions } = useExtensions()
  const extraPages = pagesAll(extensions)
  const now = useNow(30_000)
  const feed = useFeed(manifest?.generated_et)
  const badges: Record<BadgeKey, number> = {
    action: counts.actions,
    reviews: counts.reviews,
    oneonone: oo ? oo.people.reduce((n, p) => n + p.counts.open, 0) : 0,
    // Changes waiting on my approval plus sprint tickets the close-out needs my call on.
    jira: (approvals?.pending.length || 0) + (needsMe?.count || 0),
    // Knowledge proposals waiting on my approval plus documentation gaps, server counted.
    knowledge: counts.knowledge,
    debt: counts.debt,
    // The server's problem list: failed pipelines, failing or overdue jobs, CI and backup, spend, core approvals.
    operations: counts.operations,
    // Dead links on the Links page nobody has swapped or removed yet.
    links: counts.links,
  }
  const today = new Date(now).toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })
  const active = navFor(pathname)

  const badgeFor = (n: NavDef): ReactNode => {
    const count = n.badge ? badges[n.badge] : (n.count ?? 0)
    if (n.extension) {
      return count > 0 ? (
        <span className="nb-count" data-tip={`${count} need me`}>
          {count}
        </span>
      ) : undefined
    }
    // Reviews carries a second, soft count: my open PRs, with a spinner while any has work running.
    const mine = n.badge === 'reviews' && counts.myPrs > 0
    if (!count && !mine) return undefined
    return (
      <>
        {count > 0 && n.badge && (
          <span className="nb-count" data-tip={n.badge === 'operations' ? counts.operationsItems.join('\n') : badgeTip(n.badge, count)}>
            {count}
          </span>
        )}
        {mine && (
          <span
            className={`nb-soft${counts.myPrsWorking ? ' working' : ''}`}
            data-tip={`${counts.myPrs} open PRs of mine, ${counts.myPrsWorking} with something running`}
          >
            {counts.myPrsWorking > 0 && <span className="spin" aria-hidden="true" />}
            {counts.myPrs}
          </span>
        )}
      </>
    )
  }

  const rail = (
    <Rail
      brandMark="M"
      brandName="Ops Center"
      version={__APP_VERSION__}
      footer={
        <div className="rail-foot">
          <BuildCard version={__APP_VERSION__} releases={RELEASES} live={!ooErr} subtitle={APP_SUBTITLE} />
          <p className="rail-foot-line">{manifest ? `Data refreshed ${manifest.generated_et}` : 'Data refresh time unknown'}</p>
        </div>
      }
    >
      {groupsFor(people, tracker, extraPages).map((g) => {
        const items = g.items.map((n) => {
            const badge = badgeFor(n)
            const count = n.badge ? badges[n.badge] : (n.count ?? 0)
            // The collapsed rail hides the kit badge, so the count rides on the icon itself.
            const icon = count ? (
              <span className="nav-ic">
                {n.icon}
                <span className="nav-ic-count" aria-hidden="true">
                  {count > 99 ? '99+' : count}
                </span>
              </span>
            ) : (
              n.icon
            )
            return (
              <NavItem
                key={n.to}
                href={n.to}
                label={n.label}
                icon={icon}
                hue={n.hue}
                active={active?.to === n.to}
                badge={badge}
                className={badge ? 'has-count' : undefined}
              />
            )
        })
        // The flat rail has no heading: one labelled group of items (the kit group needs a visible label, so it is not used).
        return g.label ? (
          <NavGroup key={g.label} label={g.label}>
            {items}
          </NavGroup>
        ) : (
          <div key="flat" className="nav-section" role="group" aria-label="Pages">
            {items}
          </div>
        )
      })}
    </Rail>
  )

  // The header names where I am as a trail: group, page and, when the address is one of the page's tabs, that tab.
  const tab = active?.pages?.find((p) => p.to === pathname)?.label.replace(`${active.label}: `, '')
  const crumb = active
    ? breadcrumb([groupOf(active.to, NAV_LAYOUT), active.label, tab])
    : pathname.startsWith('/search')
      ? 'Search'
      : 'Ops Center'
  const header = (
    <Header
      title={crumb}
      subtitle={today}
      actions={
        <>
          <NextOneOnOne />
          <SyncChip />
          <EntChip />
          <ThemeToggle />
        </>
      }
    >
      <SearchTrigger label="Search everything" compact="auto" />
    </Header>
  )

  return (
    <>
      <AppShell
        pathname={pathname}
        linkComponent={RouterLink}
        rail={rail}
        header={header}
        strip={<FeedStrip health={feed.health} items={feed.items} search={false} greeting="Nothing is waiting on me right now." />}
      >
        <div className="oc-page">
          <section className="notice-tray oc-alerts" aria-label="Notices">
            <Suspense fallback={null}>
              <FallbackBanner />
              <BrowserBanner />
              <HermesRestartBanner />
            </Suspense>
          </section>
          <Suspense fallback={<Skeleton variant="lines" count={6} label="Loading page" />}>
            {/* A page that throws while it renders shows its own crash panel; the rail and header stay usable and another page clears it. */}
            <PageErrorBoundary resetKey={pathname}>
            <Routes>
              <Route path="/" element={<Navigate to="/action" replace />} />
              <Route path="/action" element={<ActionHub />} />
              <Route path="/action/drafts" element={<ActionHub />} />
              <Route path="/action/plans" element={<Navigate to="/action" replace />} />
              <Route path="/action/:tab" element={<ActionHub />} />
              <Route path="/people" element={<PeopleGate><OneOnOnes /></PeopleGate>} />
              <Route path="/team" element={<PeopleGate><TeamHub /></PeopleGate>} />
              <Route path="/team/:tab" element={<PeopleGate><TeamHub /></PeopleGate>} />
              <Route path="/reviews" element={<Reviews />} />
              <Route path="/reviews/:repo" element={<Reviews />} />
              <Route path="/reviews/:repo/:tab" element={<Reviews />} />
              <Route path="/work" element={<TrackerGate><JiraHub /></TrackerGate>} />
              <Route path="/work/:tab" element={<TrackerGate><JiraHub /></TrackerGate>} />
              <Route path="/work/:tab/:sprintId" element={<TrackerGate><JiraHub /></TrackerGate>} />
              <Route path="/debt" element={<EngBacklog />} />
              <Route path="/debt/:tab" element={<EngBacklog />} />
              <Route path="/knowledge" element={<Knowledge />} />
              <Route path="/knowledge/:tab" element={<Knowledge />} />
              <Route path="/plans" element={<Plans />} />
              <Route path="/links" element={<Links />} />
              <Route path="/drafts" element={<Navigate to="/plans" replace />} />
              <Route path="/search" element={<Search />} />
              <Route path="/platform" element={<PlatformEntry />} />
              <Route path="/platform/:section" element={<PlatformEntry />} />
              <Route path="/platform/:section/:item" element={<Operations />} />
              {/* Builds, CI, spend and the core moved into Operations; old links keep their place (layout rule 9). */}
              <Route path="/jira" element={<MovedRoute />} />
              <Route path="/jira/:tab" element={<MovedRoute />} />
              <Route path="/jira/:tab/:sprintId" element={<MovedRoute />} />
              <Route path="/operations" element={<MovedRoute />} />
              <Route path="/operations/:section" element={<MovedRoute />} />
              <Route path="/operations/:section/:item" element={<MovedRoute />} />
              <Route path="/builds" element={<OldRoute />} />
              <Route path="/core" element={<OldRoute />} />
              <Route path="/infra" element={<OldRoute />} />
              <Route path="/infra/:tab" element={<OldRoute />} />
              {/* old bookmarks */}
              <Route path="/planning" element={<Navigate to="/action" replace />} />
              <Route path="/history" element={<Navigate to="/team/history" replace />} />
              <Route path="/backlog" element={<Navigate to="/work/backlog" replace />} />
              <Route path="/extensions/:id" element={<ExtensionRoute />} />
              <Route path="*" element={<Navigate to="/action" replace />} />
            </Routes>
            </PageErrorBoundary>
          </Suspense>
        </div>
        <SearchPalette />
        <MobileTabBar items={groupsFor(people, tracker).flatMap((g) => g.items)} count={(n) => (n.badge ? badges[n.badge] : 0)} />
        <Shortcuts people={people} tracker={tracker} />
      </AppShell>
      <TooltipLayer />
    </>
  )
}
