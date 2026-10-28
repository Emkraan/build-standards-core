// Counting rules for my own PR cards. Run: node --test tests/ownPrs.test.mjs
// vitest is not a dependency of this app, so this uses the built-in node test runner and loads
// src/lib/ownPrs.ts directly (it has type imports only).
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { aresPrWorking, olyMineNeedsMe, olyPrState, olyPrWorking } from '../src/lib/ownPrs.ts'

const pr = (hold, extra = {}) => ({
  pr: 448,
  head_sha: 'a'.repeat(40),
  verdict: 'blocked',
  ai_result: 'FAILURE',
  pending: [],
  waiting: [],
  hold,
  ...extra,
})

test('a policy hold and a direction card need me', () => {
  assert.equal(olyMineNeedsMe(pr({ kind: 'policy' })), true)
  assert.equal(olyMineNeedsMe(pr({ kind: 'direction' })), true)
})

test('a problem needs me only with Accept the risk or a clear label hold', () => {
  assert.equal(olyMineNeedsMe(pr({ kind: 'problem' })), false)
  assert.equal(olyMineNeedsMe(pr({ kind: 'problem' }, { can_accept_risk: true })), true)
  assert.equal(olyMineNeedsMe(pr({ kind: 'problem', label_hold: { clear: true } })), true)
  assert.equal(olyMineNeedsMe(pr({ kind: 'problem', label_hold: { clear: false } })), false)
})

test('waiting, in-flight and session-locked holds stay out', () => {
  assert.equal(olyMineNeedsMe(pr({ kind: 'waiting' }, { can_accept_risk: true })), false)
  assert.equal(olyMineNeedsMe(pr({ kind: 'policy' }, { pending: ['ci'] })), false)
  assert.equal(olyMineNeedsMe(pr({ kind: 'policy' }, { deps: { first: [1], chain: [1] } })), false)
  const session = { autofix: { state: 'deferred', session: 'Discuss', text: 'x' } }
  for (const kind of ['policy', 'direction', 'problem']) {
    assert.equal(olyMineNeedsMe(pr({ kind }, { can_accept_risk: true, ...session })), false, kind)
  }
  assert.equal(olyMineNeedsMe(pr({ kind: 'problem', autofix: { state: 'running' } }, { can_accept_risk: true })), false)
  assert.equal(olyMineNeedsMe(pr(undefined)), false)
})

test('a PR with no review yet is still working', () => {
  assert.equal(olyPrWorking(pr({ kind: 'problem' }, { verdict: undefined, ai_result: undefined })), true)
  assert.equal(olyMineNeedsMe(pr({ kind: 'problem' }, { verdict: undefined, ai_result: undefined, can_accept_risk: true })), false)
})

test('the list rule and the working rule never disagree on a locked card', () => {
  const locked = pr({ kind: 'policy' }, { autofix: { state: 'deferred', session: 'Discuss', text: 'x' } })
  assert.equal(olyPrWorking(locked), true)
  assert.equal(olyMineNeedsMe(locked), false)
})

test('team: a session or running checks lock a my-PR row', () => {
  const row = { working: false, checks: { pending: [] }, kind: 'signoff' }
  assert.equal(aresPrWorking(row), false)
  assert.equal(aresPrWorking({ ...row, autofix: { state: 'deferred', session: 'Discuss' } }), true)
  assert.equal(aresPrWorking({ ...row, checks: { pending: ['ci'] } }), true)
})

test('a PR parked on main apply is neither working nor needs me', () => {
  const parked = pr({ kind: 'waiting', parked: 'main' })
  assert.equal(olyPrWorking(parked), false)
  assert.equal(olyMineNeedsMe(parked), false)
  assert.equal(olyPrWorking(pr({ kind: 'waiting' })), true)
})

test('a draft parked on its gate is neither working nor needs me, even before a review ran', () => {
  const parked = { ...pr({ kind: 'waiting', parked: 'gate', gate: [] }), verdict: undefined, ai_result: undefined }
  assert.equal(olyPrWorking(parked), false)
  assert.equal(olyMineNeedsMe(parked), false)
})

test('state: a parked draft is Waiting and names the unmet check', () => {
  const p = pr({ kind: 'waiting', parked: 'gate', summary: 's', next: 'next about 10:22 PM', gate: [
    { label: 'a', ok: true, detail: 'x' }, { label: 'prod refusals', ok: false, detail: '93, needs <= 0' }] })
  const s = olyPrState(p)
  assert.equal(s.state, 'waiting')
  assert.match(s.why, /prod refusals \(93, needs <= 0\)/)
  assert.match(s.next, /10:22/)
})
test('state: running checks are In progress, a live session wins over everything', () => {
  assert.equal(olyPrState({ ...pr({ kind: 'policy' }), pending: ['plan'] }).state, 'in_progress')
  assert.equal(olyPrState({ ...pr({ kind: 'waiting', parked: 'gate', gate: [] }), autofix: { state: 'deferred', text: '', session: 'Fix 466' } }).state, 'in_progress')
})
test('state: a policy hold Needs you, a fixer that gave up is Stuck, a draft without a gate is Stuck', () => {
  assert.equal(olyPrState(pr({ kind: 'policy', summary: 'sign off' })).state, 'needs_you')
  assert.equal(olyPrState(pr({ kind: 'problem', summary: 'x', autofix: { state: 'gave_up', text: 'two sessions failed' } })).state, 'stuck')
  assert.equal(olyPrState(pr({ kind: 'problem', parked: 'nogate', summary: 'x' })).state, 'stuck')
})
test('state: all green with no hold is Ready', () => {
  assert.equal(olyPrState({ ...pr(undefined), verdict: 'success' }).state, 'ready')
})
