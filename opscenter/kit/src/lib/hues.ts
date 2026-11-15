/* The six categorical hues (UI standard section 17), the two extra hues and the per-app accent
   names (section 12). Data takes a categorical hue, never the accent. The extra hues (yellow and
   ink, the solid neutral) are taken by name only: they never enter the series rotation, the
   avatar hash or the accent withholding. */

/** The series rotation, in order. */
export const CATEGORICAL_HUES = ['blue', 'green', 'amber', 'red', 'violet', 'teal'] as const;
/** One of the six series hues. Unchanged meaning: series, avatars and the withheld hue use it. */
export type CategoricalHue = (typeof CATEGORICAL_HUES)[number];
/** Another name for CategoricalHue. */
export type SeriesHue = CategoricalHue;

/** Hues for data that is yellow or black by name (a toner, a flag). Never in the rotation. */
export const EXTRA_HUES = ['yellow', 'ink'] as const;
export type ExtraHue = (typeof EXTRA_HUES)[number];

/** Every hue a mark, tile, card, badge or dialog icon can take: the six plus the extras. */
export type MarkHue = CategoricalHue | ExtraHue;

/** Nav icons may also take `brand`, which follows the app accent. */
export type NavHue = 'brand' | MarkHue;

/** True only for one of the six series hues (never an extra hue). */
export function isCategoricalHue(value: string): value is CategoricalHue {
  return (CATEGORICAL_HUES as readonly string[]).includes(value);
}

/** Another name for isCategoricalHue. */
export function isSeriesHue(value: string): value is SeriesHue {
  return isCategoricalHue(value);
}

/** True for a series hue or an extra hue, the set every `hue` prop accepts. */
export function isMarkHue(value: string): value is MarkHue {
  return isCategoricalHue(value) || (EXTRA_HUES as readonly string[]).includes(value);
}

/** A stable categorical hue for a name (avatars, people chips). Same name, same hue, every app. */
export function hueFor(name: string, hues: readonly CategoricalHue[] = CATEGORICAL_HUES): CategoricalHue {
  const list = hues.length > 0 ? hues : CATEGORICAL_HUES;
  let h = 0;
  for (const ch of name.trim().toLowerCase()) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return list[h % list.length] ?? 'blue';
}

/** Initials for an avatar: first letters of the first and last words. A trailing note in
    parentheses is ignored, and a directory name written "Last, First" reads as "First Last". */
export function initialsOf(name: string): string {
  const clean = name.replace(/\([^)]*\)/g, ' ').trim();
  const comma = clean.indexOf(',');
  const ordered = comma > 0 ? `${clean.slice(comma + 1)} ${clean.slice(0, comma)}` : clean;
  const words = ordered.split(/\s+/).filter(Boolean);
  if (words.length === 0) return '?';
  const first = words[0]?.[0] ?? '';
  const last = words.length > 1 ? words[words.length - 1]?.[0] ?? '' : '';
  return (first + last).toUpperCase();
}
