// The header chip that says Enterprise is billing Hermes while Team has headroom, and how long until the incident clears by itself (the server
// sends `closes_utc`, one quiet period after the last leak call, so the client holds no threshold). Free of React so tests/entChip.test.mjs
// can load it as it is.

export interface EntChipInput {
  active: { closes_utc?: string | null } | null | undefined
}

export interface EntChip {
  /** The full text, "Enterprise on, 0 h 41 min left". */
  text: string
  /** The short text for a narrow header. */
  short: string
}

/** The chip while an incident is open, none otherwise. A missing or past close time leaves out the time left and never invents one. */
export function entChip(fb: EntChipInput | null | undefined, nowMs: number): EntChip | null {
  if (!fb || !fb.active) return null
  const end = fb.active.closes_utc ? Date.parse(fb.active.closes_utc) : NaN
  const left = Number.isNaN(end) ? 0 : Math.floor((end - nowMs) / 60000)
  if (left <= 0) return { text: 'Enterprise on', short: 'Ent on' }
  return { text: `Enterprise on, ${Math.floor(left / 60)} h ${left % 60} min left`, short: 'Ent on' }
}
