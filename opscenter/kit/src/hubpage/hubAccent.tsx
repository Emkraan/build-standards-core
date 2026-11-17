/* The hub accent: the identity colour a hub wears. A page root (or any element) carries
   data-hub="<key>", and the kit styles read --hub, --hub-soft, --hub-line and --hub-ink from it.
   The key to colour table is the consumer's own configurable map, never a fixed list in the kit.
   Accent is identity and never state: red, amber and green stay the state tones, so a map entry
   names a categorical hue or a mix of two, and the kit refuses a key that is not a plain token. */

import type { MarkHue } from '../lib/hues';

/** A hue token, or the app accent. */
export type HubAccentStop = MarkHue | 'accent';

/** One hub colour: a single stop, or a mix of two stops with the weight (0 to 100) of the first. */
export type HubAccentSpec = HubAccentStop | { mix: readonly [HubAccentStop, HubAccentStop]; weight: number };

export type HubAccentMap = Readonly<Record<string, HubAccentSpec>>;

const KEY = /^[a-z][a-z0-9-]*$/;

function stop(value: HubAccentStop): string {
  return value === 'accent' ? 'rgb(var(--accent-rgb))' : `rgb(var(--hue-${value}))`;
}

function colour(spec: HubAccentSpec): string {
  if (typeof spec === 'string') return stop(spec);
  const weight = Math.round(spec.weight);
  if (!Number.isFinite(weight) || weight < 1 || weight > 99) throw new Error('hub accent: a mix weight is 1 to 99');
  return `color-mix(in srgb, ${stop(spec.mix[0])} ${weight}%, ${stop(spec.mix[1])} ${100 - weight}%)`;
}

/** The CSS rules for a hub accent map, one rule per key. Throws on a key that is not a plain token. */
export function hubAccentRules(map: HubAccentMap): string {
  return Object.entries(map)
    .map(([key, spec]) => {
      if (!KEY.test(key)) throw new Error(`hub accent: "${key}" is not a lower case token`);
      return `[data-hub="${key}"] { --hub: ${colour(spec)}; }`;
    })
    .join('\n');
}

/** Injects the rules of a hub accent map. Render once near the root. */
export function HubAccentStyle({ map, nonce }: { map: HubAccentMap; nonce?: string | undefined }) {
  return <style nonce={nonce}>{hubAccentRules(map)}</style>;
}
