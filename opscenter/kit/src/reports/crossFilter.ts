/* Click to cross-filter. The picks are one value per filter id; a click on a mark sets its filter, a second click on the
   same value clears it. Pure functions: the app keeps the picks in its address (see viewState) and the run follows. */

export type Picks = Readonly<Record<string, string>>;

/** The picks after a click on `value` for filter `id`: set it, or clear it when it was already the pick. */
export function togglePick(picks: Picks, id: string, value: string): Picks {
  const next = { ...picks };
  if (!value || next[id] === value) delete next[id];
  else next[id] = value;
  return next;
}

/** One filter set to a value (an empty value clears it). */
export function setPick(picks: Picks, id: string, value: string): Picks {
  const next = { ...picks };
  if (value) next[id] = value;
  else delete next[id];
  return next;
}

/** The picks that are on, as [id, value]. */
export function activePicks(picks: Picks): [string, string][] {
  return Object.entries(picks).filter(([, v]) => !!v);
}
