// Own-PR card rules shared by the Reviews tabs and the badge counts. Type imports only, so the
// node test in tests/ownPrs.test.mjs can load this file without React or the data layer.
// The server applies the same rule when it counts (platform_reviews._mine_needs_me).

import type { AresPr, OlyMyPr } from './data'

// A PR of mine is "working" when something is moving on it without me: checks or the PR
// review running, the auto-merge lane waiting on its next pass, or auto-fix on a problem.
export function olyPrWorking(p: OlyMyPr): boolean {
  const h = p.hold
  // Running checks always lock the row: the hold (even a policy or direction one) can change when they finish.
  if (p.pending.length > 0) return true
  // A live session on the PR (a delegated fix, a Discuss session) locks it on any hold.
  if (p.autofix?.session) return true
  if (h?.kind === 'policy' || h?.kind === 'direction') return false
  // Parked on purpose: main's own unapplied change or a draft's gate the lane re-checks on
  // its own. Nothing runs on the PR meanwhile, so no spinner and nothing for me to click.
  if (h?.parked === 'main' || h?.parked === 'gate') return false
  if (!p.verdict && !p.ai_result) return true
  // Checks parked on my terraform-plan approval are not running work. The action is on Needs me.
  if (h?.kind === 'waiting') return !((p.waiting?.length ?? 0) > 0)
  return h?.kind === 'problem' && (h.autofix?.state === 'running' || h.autofix?.state === 'deferred')
}
export function aresPrWorking(p: AresPr): boolean {
  if (p.working || p.checks.pending.length > 0) return true
  if (p.autofix?.session) return true
  if (p.kind === 'signoff' || p.kind === 'direction') return false
  return p.autofix?.state === 'running' || p.autofix?.state === 'deferred'
}

// one of my own platform PRs that has an action for me right now, so it shows under Needs me
// (same card, same buttons) and counts in the badges. A policy hold (Approve and merge), a direction
// or decision card, a blocked review my triage already covers (Accept the risk), and a do-not-merge
// hold with nothing else behind it (Remove hold label). Locked rows stay out: checks running, a live
// session on the PR, auto-fix running, waiting on another PR (those list apart, not counted).
export function olyMineNeedsMe(p: OlyMyPr): boolean {
  const h = p.hold
  if (!h || p.deps || olyPrWorking(p)) return false
  if (h.kind === 'policy' || h.kind === 'direction') return true
  return h.kind === 'problem' && (!!p.can_accept_risk || !!h.label_hold?.clear)
}

// One answer to "where is this PR at", the first thing every card shows. needs_you = a click or a decision
// only I can give, in_progress = something runs on it right now, waiting = parked on a named event with
// the time or trigger that moves it, stuck = nothing will move it on its own, ready = green, the lane
// merges it on its next pass. why names the cause, next names what moves it. Never guessed: every
// branch reads a field the server set.
export type PrState = 'needs_you' | 'in_progress' | 'waiting' | 'stuck' | 'ready'
export interface PrStateView {
  state: PrState
  why: string
  next: string
}
export const PR_STATE_LABEL: Record<PrState, string> = {
  needs_you: 'Needs you',
  in_progress: 'In progress',
  waiting: 'Waiting',
  stuck: 'Stuck',
  ready: 'Ready',
}
const LANE_PASS = 'the own-PR lane (every 3 minutes)'

export function olyPrState(p: OlyMyPr): PrStateView {
  const h = p.hold
  const af = h?.autofix ?? p.autofix ?? undefined
  const unmet = (h?.gate || []).find((g) => !g.ok)
  if (p.autofix?.session || af?.state === 'deferred')
    return {
      state: 'in_progress',
      why: `A live session is working this PR (${p.autofix?.session || af?.session || 'session'}).`,
      next: 'Automation waits for that session to go quiet, then carries on by itself.',
    }
  if (p.pending.length > 0)
    return {
      state: 'in_progress',
      why: `${p.pending.length} check(s) running: ${p.pending.slice(0, 3).join(', ')}${p.pending.length > 3 ? ', ...' : ''}.`,
      next: `When they finish, ${LANE_PASS} re-reads the result.`,
    }
  if (h?.kind === 'problem' && af?.state === 'running')
    return {
      state: 'in_progress',
      why: `Auto-fix is working on it: ${h.summary}`,
      next: 'The fix pushes to the branch, then the checks run again.',
    }
  if (h?.parked === 'gate')
    return {
      state: 'waiting',
      why: unmet ? `Its gate: ${unmet.label} (${unmet.detail}).` : h.summary,
      next: h.next || 'The lane re-checks the gate every 10 minutes.',
    }
  if (h?.parked === 'main') return { state: 'waiting', why: h.summary, next: h.next || 'It moves once main applies.' }
  if (h?.parked === 'nogate') return { state: 'stuck', why: h.summary, next: h.next || 'Mark it ready for review by hand.' }
  if (p.deps)
    return {
      state: 'waiting',
      why: p.deps.first_line || p.deps.lines[0] || `It waits on ${p.deps.chain.map((n) => `#${n}`).join(', ')}.`,
      next: 'The lane rebases it and carries on once that lands.',
    }
  if (af?.state === 'waiting_on') return { state: 'waiting', why: af.text, next: 'The lane rebases it by itself once those merge.' }
  if (olyMineNeedsMe(p))
    return {
      state: 'needs_you',
      why: h?.summary || 'A policy rule reserves this one for me.',
      next:
        h?.kind === 'policy'
          ? 'Approve and merge on this card.'
          : p.can_accept_risk
            ? 'Accept the risk on this card.'
            : h?.label_hold?.clear
              ? 'Remove hold label on this card.'
              : 'Answer the decision on this card.',
    }
  if (h?.kind === 'problem')
    return af?.state === 'gave_up'
      ? { state: 'stuck', why: af.text, next: 'Discuss with the assistant to give it a direction.' }
      : { state: 'waiting', why: h.summary, next: h.next || `Auto-fix starts on the next pass of ${LANE_PASS}.` }
  if (!p.verdict && !p.ai_result)
    return {
      state: 'in_progress',
      why: 'The PR review has not reported on this head yet.',
      next: 'The review job runs on its schedule (Watcher line).',
    }
  if ((p.waiting?.length ?? 0) > 0)
    return {
      state: 'waiting',
      why: `${p.waiting?.length} terraform check(s) wait on the terraform-plan approval.`,
      next: h?.plan_line || 'The plan gate takes them within 2 minutes, or they show under Needs me.',
    }
  if (h?.kind === 'waiting') return { state: 'waiting', why: h.summary, next: h.next || `The next pass of ${LANE_PASS}.` }
  return { state: 'ready', why: 'Everything is green.', next: `The next pass of ${LANE_PASS} merges it.` }
}
