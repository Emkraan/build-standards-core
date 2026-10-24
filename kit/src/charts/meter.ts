/* Shared maths for the single-value charts (Gauge and RingProgress): clamping, the threshold tone
   and the text a screen reader gets. Pure functions, no chart library. */

/** The colour state of a single-value chart. `accent` is the neutral default. `info` is a fixed colour
   for a ring or gauge that is not a status (a share, a category): thresholds never produce it and its
   value text carries no state word. */
export type MeterTone = 'accent' | 'info' | 'success' | 'warning' | 'danger';

/** Where a value turns warning and danger, in the same units as `value` and `max` (not a 0 to 1 share:
   for a max of 200, a warning at 150 is `warning: 150`). Higher is worse unless `higherIsBetter` is set. */
export interface MeterThresholds {
  /** The value at which the tone becomes warning. */
  warning?: number | undefined;
  /** The value at which the tone becomes danger. */
  danger?: number | undefined;
}

/** The value limited to 0 through `max`. A non-finite value or a `max` of 0 or less gives 0. */
export function clampValue(value: number, max: number): number {
  if (!Number.isFinite(value) || !Number.isFinite(max) || max <= 0) return 0;
  return Math.min(Math.max(value, 0), max);
}

/** The filled share of the track, 0 through 1. */
export function fraction(value: number, max: number): number {
  const limit = Number.isFinite(max) && max > 0 ? max : 0;
  return limit === 0 ? 0 : clampValue(value, limit) / limit;
}

/**
 * The tone for a value. With no thresholds the tone is `accent`. By default a higher value is worse
 * (load, usage): at or past `danger` is danger, at or past `warning` is warning, else success. With
 * `higherIsBetter` it flips (health, remaining): at or under `danger` is danger, at or under
 * `warning` is warning, else success. The clamped value is compared, never the raw one.
 */
export function thresholdTone(value: number, max: number, thresholds?: MeterThresholds, higherIsBetter = false): MeterTone {
  if (!thresholds || (thresholds.warning === undefined && thresholds.danger === undefined)) return 'accent';
  const v = clampValue(value, max);
  const { warning, danger } = thresholds;
  if (higherIsBetter) {
    if (danger !== undefined && v <= danger) return 'danger';
    if (warning !== undefined && v <= warning) return 'warning';
    return 'success';
  }
  if (danger !== undefined && v >= danger) return 'danger';
  if (warning !== undefined && v >= warning) return 'warning';
  return 'success';
}

const TONE_WORD: Record<MeterTone, string> = { accent: '', info: '', success: 'healthy', warning: 'warning', danger: 'critical' };

/** The value text for aria-valuetext: "42 of 100", plus the state word when thresholds colour it. */
export function meterText(value: number, max: number, format: (n: number) => string, tone: MeterTone): string {
  const base = `${format(clampValue(value, max))} of ${format(Number.isFinite(max) && max > 0 ? max : 0)}`;
  const word = TONE_WORD[tone];
  return word ? `${base}, ${word}` : base;
}
