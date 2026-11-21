// The pieces of the platform reviews page that read the review gate and the policy file. A server with no review
// config answers without a `gate` or a `policy` object, and the page reads both as optional so that answer renders the
// empty page instead of throwing (issue 326, item 3). Free of React so tests/reviewsFoot.test.mjs can load it as it is.

export interface GateInfo {
  failures?: number
}
export interface PolicyInfo {
  path?: string
  version?: number
}

/** Failures in a row of the review gate; none when the server reported no gate. */
export function gateFailures(gate: GateInfo | null | undefined): number {
  return gate?.failures || 0
}

/** The footer text about the policy file, or null when the server named none (nothing to show, and nothing to throw on). */
export function policyFoot(policy: PolicyInfo | null | undefined): { version: string; path: string } | null {
  if (!policy || (!policy.path && policy.version == null)) return null
  return { version: policy.version == null ? '' : String(policy.version), path: (policy.path || '').replace(/^\/Users\/[^/]+/, '~') }
}
