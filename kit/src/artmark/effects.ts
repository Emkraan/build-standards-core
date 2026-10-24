/* The effect recipes of the art mark, named by what they do and never by what they decorate. Each
   recipe lists the effect layers it draws and the anchors it reads. The CSS for each recipe is in
   styles/kit.css under [data-effect="<name>"]. Adding a recipe is a new entry here, its layer
   classes and its keyframes in that sheet. */

export interface ArtEffectDef {
  /** Layer counts. A layer is a span with the class am-<name>, its index in --i and in data-n. */
  readonly layers: Readonly<Record<string, number>>;
  /** Which anchors the recipe reads, for the consumer that measures them. */
  readonly anchors: readonly string[];
}

export const ART_EFFECTS = Object.freeze({
  /** A turning light sweep from the focus point plus pulses of waves that spread to both sides. */
  beacon: Object.freeze({ layers: Object.freeze({ beam: 1, wave: 2 }), anchors: ['focus', 'reach'] }),
  /** A point of light that breathes at the focus, a sheen that crosses the picture, an occasional spark. */
  glint: Object.freeze({ layers: Object.freeze({ eye: 1, sweep: 1, spark: 2 }), anchors: ['focus', 'spark'] }),
  /** Arcs around the focus that light one after another, then a soft ring that spreads out. */
  signal: Object.freeze({ layers: Object.freeze({ arc: 4, ping: 1 }), anchors: ['focus', 'arcs'] }),
  /** The picture shakes now and then around a pivot while arcs around the focus light up in turn. */
  ring: Object.freeze({ layers: Object.freeze({ arc: 3 }), anchors: ['focus', 'arcs', 'pivot'] }),
  /** A light bar crosses a window and a part of the picture slides out along a line and back. */
  scan: Object.freeze({ layers: Object.freeze({ bar: 1, feed: 1 }), anchors: ['box', 'feed'] }),
  /** An electric flicker: a charged glow, a brightness flash, thin jagged arcs and sparks that crackle. */
  lightning: Object.freeze({ layers: Object.freeze({ bolt: 1, zap: 3 }), anchors: [] }),
  /** A flame glow that breathes unevenly, a flickering picture and embers rising off it. */
  fire: Object.freeze({ layers: Object.freeze({ ember: 5 }), anchors: [] }),
}) satisfies Readonly<Record<string, ArtEffectDef>>;

export type ArtEffectName = keyof typeof ART_EFFECTS;

/** The recipe name when it is a known one, otherwise undefined (a still picture). */
export function artEffectFor(name: string | undefined): ArtEffectName | undefined {
  return name && Object.prototype.hasOwnProperty.call(ART_EFFECTS, name) ? (name as ArtEffectName) : undefined;
}
