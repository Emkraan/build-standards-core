import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { waitingGroups, waitingTotal } from '../src/lib/waitingOnMe.ts'

const platform = { needs_me_rows: [{ pr: 12, title: 'Plan page', what: 'Approve the plan' }, { pr: null, title: 'Not a PR', what: 'x' }] }
const team = { needs_me: [{ pr: 7, title: 'Fix', kind: 'escalated' }, { pr: 8, title: 'Mine', kind: 'direction' }, { pr: 9, title: 'Odd', why: 'Custom reason' }, { pr: 10, title: 'Bare' }] }
const other = { repos: [
  { slug: 'ops_center', repo: 'ops_center', needs_me: [{ pr: 3, title: 'Red', kind: 'checks' }] },
  { slug: 'build-standards-core', repo: 'Core', needs_me: [] },
  { slug: 'backup', repo: 'Backup', needs_me: [{ pr: 4, title: 'Old', kind: 'stale' }, { pr: 5, title: 'Clash', kind: 'conflict' }] },
] }

test('platform comes first, then team, then the other repos in the order given, and an empty repo has no group', () => {
  assert.deepEqual(waitingGroups(platform, team, other).map((g) => g.slug), ['platform', 'team', 'ops_center', 'backup'])
})

test('a platform row with no pull request number is not listed, since it has no card to link to', () => {
  const g = waitingGroups(platform, null, null)
  assert.equal(g.length, 1)
  assert.deepEqual(g[0].rows.map((r) => r.pr), [12])
})

test('each team kind is worded as the button on its card, a plain reason is used when there is no kind, and a bare row still says something', () => {
  const rows = waitingGroups(null, team, null)[0].rows
  assert.deepEqual(rows.map((r) => r.what), ['Approve as me', 'Give it direction', 'Custom reason', 'Needs my decision'])
})

test('other repo rows say what is wrong and link to that repo, not to the platform page', () => {
  const g = waitingGroups(null, null, other)
  assert.deepEqual(g.map((x) => x.rows.map((r) => `${r.pr} ${r.what} > ${r.to}`)), [
    ['3 Checks are failing > /reviews/ops_center'],
    ['4 Stale, needs a look > /reviews/backup', '5 Has a merge conflict > /reviews/backup'],
  ])
})

test('missing or empty lanes give no groups and a total of zero, never an error', () => {
  assert.deepEqual(waitingGroups(null, null, null), [])
  assert.deepEqual(waitingGroups({}, { needs_me: [] }, { repos: [] }), [])
  assert.equal(waitingTotal([]), 0)
})

test('the total counts every row across the groups', () => {
  assert.equal(waitingTotal(waitingGroups(platform, team, other)), 1 + 4 + 1 + 2)
})

// The panel does not write. It links to the Reviews card, where the one guarded Approve and merge flow lives, so a regression
// that imports a post function here would quietly create the second, faster path this design avoids.
test('the panel has no write path: neither the logic nor the component imports a post function', () => {
  for (const f of ['../src/lib/waitingOnMe.ts', '../src/components/WaitingOnMe.tsx']) {
    const src = readFileSync(new URL(f, import.meta.url), 'utf8')
    assert.equal(/\bpost[A-Z]\w*/.test(src.replace(/\/\/.*$/gm, '')), false, `${f} must not call a post function`)
    assert.equal(/fetch\(|method:\s*'POST'/.test(src.replace(/\/\/.*$/gm, '')), false, `${f} must not send a request`)
  }
})
