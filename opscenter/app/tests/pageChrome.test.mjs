// Date: 2026-11-21
// Purpose: the page chrome of the parity spec (issue 327): the header trail, the mobile tab bar list, the stat row and the page chip.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { breadcrumb, DEFAULT_NAV_LAYOUT, groupOf, parseNavLayout } from '../src/lib/navLayout.ts'

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')

test('the trail joins group, page and tab and leaves out what a page does not have', () => {
  assert.equal(breadcrumb(['Today', 'Action Center', 'Needs me']), 'Today / Action Center / Needs me')
  assert.equal(breadcrumb(['Deliver', 'Platform', undefined]), 'Deliver / Platform')
  assert.equal(breadcrumb([undefined, 'Search', null]), 'Search')
})

test('the group of a route comes from the default five groups, or the consumer groups', () => {
  assert.equal(groupOf('/action', DEFAULT_NAV_LAYOUT), 'Today')
  assert.equal(groupOf('/work', DEFAULT_NAV_LAYOUT), 'Deliver')
  assert.equal(groupOf('/debt', DEFAULT_NAV_LAYOUT), 'Improve')
  assert.equal(groupOf('/nowhere', DEFAULT_NAV_LAYOUT), undefined)
  const own = parseNavLayout('{"groups":[{"label":"Operate","items":["/action"]}]}')
  assert.equal(groupOf('/action', own), 'Operate')
})

test('the mobile tab bar offers Action, Pull requests, Work and Platform in that order, only when the rail has them', async () => {
  const src = read('../src/components/MobileTabBar.tsx')
  assert.match(src, /TABBAR_ROUTES = \['\/action', '\/reviews', '\/work', '\/platform'\]/)
  assert.match(src, /, \{c\} need me/)
  assert.match(src, /aria-label="Menu"/)
})

test('a page header takes the rail icon as its chip, no page passes an eyebrow, and a notice is the kit row', () => {
  assert.match(read('../src/components/HubHeader.tsx'), /icon=\{icon\}/)
  for (const f of ['Operations', 'Plans', 'CoreConsumption', 'JiraHub', 'Knowledge', 'Links', 'OneOnOnes', 'Reviews', 'Search', 'TeamHub', 'EngBacklog', 'ActionHub']) assert.doesNotMatch(read(`../src/pages/${f}.tsx`), /eyebrow=/, f)
  assert.match(read('../src/components/AlertBanner.tsx'), /<Notice tone=/)
  assert.match(read('../src/App.tsx'), /<section className="notice-tray oc-alerts" aria-label="Notices">/)
})

test('a zero stat is muted and a stat with a handler is a button', () => {
  const src = read('../src/components/StatRow.tsx')
  assert.match(src, /data-zero=/)
  assert.match(src, /<button key=\{s\.key\} type="button" className="ds-stat" aria-pressed/)
})

test('the Work tracking tabs open with the reference stat rows and labels', () => {
  const want = {
    Sprint: ['My items', 'In progress', 'To do', 'Points done'],
    NeedsMe: ['Waiting on my call', 'Oldest wait', 'Closing now'],
    Backlog: ['Backlog items', 'High and highest', 'In progress outside the sprint', 'Active sprint'],
  }
  for (const [page, labels] of Object.entries(want)) {
    const src = read(`../src/pages/${page}.tsx`)
    assert.match(src, /<StatRow/, page)
    assert.doesNotMatch(src, /<StatTile/, page)
    for (const l of labels) assert.ok(src.includes(`'${l}'`), `${page}: ${l}`)
  }
})

test('the Alerts and Completed tabs open with the reference stat rows and labels', () => {
  const want = {
    Alerts: ['Need ack', 'Reports', 'Failing now', 'Jobs watched'],
    Completed: ['Completed', 'Last 7 days', 'Critical or high', 'Via Hermes'],
  }
  for (const [page, labels] of Object.entries(want)) {
    const src = read(`../src/pages/${page}.tsx`)
    assert.match(src, /<StatRow/, page)
    assert.doesNotMatch(src, /<StatTile/, page)
    for (const l of labels) assert.ok(src.includes(`'${l}'`), `${page}: ${l}`)
  }
})

test('the Team tabs open with the reference stat rows and labels', () => {
  const want = {
    TeamPerformance: ['Points delivered', 'High and highest', 'Open'],
    MemberReviews: ['Datapoints drawn on', 'Months on record', 'Trajectory'],
    YearlyReview: ['Work items completed', 'High priority closed', 'Median turnaround', 'Long-standing cleared', 'Open now'],
  }
  for (const [page, labels] of Object.entries(want)) {
    const src = read(`../src/pages/${page}.tsx`)
    assert.match(src, /<StatRow/, page)
    assert.doesNotMatch(src, /<StatTile/, page)
    for (const l of labels) assert.ok(src.includes(`'${l}'`), `${page}: ${l}`)
  }
})

test('the approval brief draws the why table with the reference column widths and upper case headers', () => {
  const src = read('../src/components/ApprovalBrief.tsx')
  assert.match(src, /rh-grants rh-grants-why/)
  for (const w of ['9%', '42%', '11%', '38%']) assert.ok(src.includes(`width: '${w}'`), w)
  assert.match(read('../src/pages/ReviewsHub.css'), /\.rh-grants-why th \{\s*text-transform: uppercase/)
})

test('the Jobs, Team ledger, throughput and Routing tables carry the reference column widths', () => {
  const want = {
    'infra/Jobs.tsx': [['Type', '117px'], ['Schedule', '133px'], ['Last run', '88px'], ['Next', '78px'], ['Logs 7d', '86px'], ['Health', '103px']],
    'TeamHistory.tsx': [['Period', '152px'], ['Sprints', '208px'], ['Engineer', '201px'], ['Completion', '153px'], ['Pts deliv.', '133px'], ['Done', '101px'], ['Carry', '103px'], ['Intake', '110px']],
    'TeamPerformance.tsx': [['Sprint', '223px'], ['Done', '188px'], ['Points', '216px']],
    'ActionRouting.tsx': [['Input', '42%'], ['What happened', '58%']],
  }
  for (const [file, cols] of Object.entries(want)) {
    const src = read(`../src/pages/${file}`)
    for (const [header, w] of cols) assert.match(src, new RegExp(`header: '${header.replace('.', '\\.')}',\\s*width: '${w}'`), `${file}: ${header}`)
  }
})

test('a document backed plan row opens the document in a new tab through the safe address and offers no Archive', () => {
  const src = read('../src/pages/Plans.tsx')
  assert.match(src, /d\.link \? \(\s*<a className="pl-row-main" href=\{safeHref\(d\.link\) \?\? undefined\} target="_blank" rel="noreferrer noopener">/)
  assert.match(src, /\{!d\.link && \(\s*<Button size="sm" variant="ghost" loading=\{busy\} onClick=\{onAction\}>/)
})
