// helpers for cards whose PR waits on another PR (pr_deps.py on the server).
import type { DepView } from './data'

/** The confirm question for Approve anyway (title up to the question mark, then the body). */
export function depConfirm(what: string, v: DepView): string {
  const names = v.waiting.map((w) => `#${w.pr} (${w.kind_text})`).join(', ')
  const first = v.first.map((n) => `#${n}`).join(', ')
  return (
    `${what} anyway?\n\nIt waits on ${names}. Its plan will likely fail or be redone once that lands, ` +
    `and the new runs then need another approval. Do ${first} first unless you know this can pass now.`
  )
}

/** The open PRs that wait on this one (it is first in their chain), for a "do this first" line. */
export function unblocks(deps: Record<string, DepView> | undefined, pr: number | null): number[] {
  if (!deps || pr === null) return []
  return Object.entries(deps)
    .filter(([, v]) => v.chain.includes(pr))
    .map(([k]) => Number(k))
    .sort((a, b) => a - b)
}
