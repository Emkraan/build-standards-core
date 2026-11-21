// Date: 2026-11-21
// Purpose: the rail layout is a consumer parameter (issue 326 item 1): flat is the default, labels and order are
// parameters, grouped is a choice, and a bad value never empties the rail.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { arrange, DEFAULT_GROUPS, DEFAULT_NAV_LAYOUT, parseNavLayout } from '../src/lib/navLayout.ts'

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')
const ITEMS = ['/action', '/work', '/reviews', '/platform', '/debt', '/people', '/team', '/knowledge', '/plans', '/links'].map((to) => ({ to, label: to.slice(1) }))
const tos = (g) => g.flatMap((x) => x.items.map((i) => i.to))

test('unset, empty, malformed or non-object values give the default flat layout', () => {
  for (const raw of [undefined, null, '', '   ', '{', '[]', '"flat"', 'null', '7']) assert.deepEqual(parseNavLayout(raw), DEFAULT_NAV_LAYOUT, String(raw))
  assert.equal(DEFAULT_NAV_LAYOUT.layout, 'flat')
})

test('flat is one group with no heading, in core order, with every item', () => {
  const g = arrange(ITEMS, DEFAULT_NAV_LAYOUT)
  assert.equal(g.length, 1)
  assert.equal(g[0].label, '')
  assert.deepEqual(tos(g), ITEMS.map((i) => i.to))
})

test('labels replace the core label by route and leave the others', () => {
  const l = parseNavLayout(JSON.stringify({ labels: { '/work': 'Jira', '/platform': 'Operations', 'bad': 'x', '/plans': '  ' } }))
  const g = arrange(ITEMS, l)
  const by = Object.fromEntries(g[0].items.map((i) => [i.to, i.label]))
  assert.equal(by['/work'], 'Jira')
  assert.equal(by['/platform'], 'Operations')
  assert.equal(by['/plans'], 'plans')
  assert.equal(by['/action'], 'action')
})

test('order moves the named routes first, in that order, and the rest follow in core order', () => {
  const l = parseNavLayout(JSON.stringify({ order: ['/links', '/action', '/nowhere'] }))
  assert.deepEqual(tos(arrange(ITEMS, l)).slice(0, 4), ['/links', '/action', '/work', '/reviews'])
  assert.equal(tos(arrange(ITEMS, l)).length, ITEMS.length)
})

test('grouped uses the default five groups, or the consumer groups, and never drops a page', () => {
  const g = arrange(ITEMS, parseNavLayout('{"layout":"grouped"}'))
  assert.deepEqual(g.map((x) => x.label), ['Today', 'Deliver', 'Improve', 'People', 'Knowledge'])
  assert.equal(tos(g).length, ITEMS.length)
  const own = arrange(ITEMS, parseNavLayout(JSON.stringify({ layout: 'grouped', groups: [{ label: 'Operate', items: ['/action', '/work'] }, { label: 'Empty', items: ['/gone'] }] })))
  assert.deepEqual(own.map((x) => x.label), ['Operate', 'More'])
  assert.deepEqual(own[0].items.map((i) => i.to), ['/action', '/work'])
  assert.equal(tos(own).length, ITEMS.length)
})

test('a group that has no visible item (a slot is off) is left out', () => {
  const some = ITEMS.filter((i) => i.to !== '/people' && i.to !== '/team')
  const g = arrange(some, parseNavLayout('{"layout":"grouped","groups":[{"label":"People","items":["/people","/team"]}]}'))
  assert.equal(g.some((x) => x.label === 'People'), false)
})

test('the default groups list every core route once', () => {
  const all = DEFAULT_GROUPS.flatMap((g) => g.items)
  assert.equal(new Set(all).size, all.length)
})

test('the rail, the shortcuts and the palette read the layout through groupsFor, and a flat rail has no group heading', () => {
  const app = read('../src/App.tsx')
  assert.match(app, /g\.label \? \(/)
  assert.match(read('../src/lib/config.ts'), /parseNavLayout\(import\.meta\.env\.VITE_NAV\)/)
})

test('a hub page titles itself with the rail label, so a consumer label renames both (ops-center-layout rule 22)', () => {
  const nav = read('../src/shell/nav.tsx')
  for (const [page, route] of [['JiraHub', '/work'], ['OneOnOnes', '/people'], ['Operations', '/platform'], ['TeamHub', '/team'], ['EngBacklog', '/debt'], ['Reviews', '/reviews']]) {
    const src = read(`../src/pages/${page}.tsx`)
    const m = src.match(new RegExp(`title=\\{pageTitle\\('${route}', '([^']+)'\\)\\}`))
    assert.ok(m, `${page} uses pageTitle for ${route}`)
    assert.ok(nav.includes(`to: '${route}',\n    label: '${m[1]}'`) || nav.includes(`to: '${route}', label: '${m[1]}'`), `${page} default title equals the rail label`)
  }
})
