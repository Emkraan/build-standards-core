/* A semicircular gauge for one value against a maximum. Hand-drawn SVG (no chart library), coloured
   by the status tokens and animated on the travel duration. The wrapper is a meter named by
   `label`, with the value as text, so a screen reader gets the number and the state. The drawing
   is hidden from assistive technology. Under reduced motion the arc does not animate. */

import type { ReactNode } from 'react';
import { cx } from '../lib/env';
import { useMediaQuery } from '../lib/media';
import { clampValue, fraction, meterText, thresholdTone } from './meter';
import type { MeterThresholds, MeterTone } from './meter';

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)';

export interface GaugeProps {
  value: number;
  /** The full-scale value. Default 100. A max of 0 or less draws an empty gauge. */
  max?: number | undefined;
  /** Accessible name of the gauge, also shown under the value. */
  label: string;
  /** Formats the value and the maximum for the centre text and the value text. Default: the number as is. */
  formatValue?: ((value: number) => string) | undefined;
  /** Fixed tone (`info` for a colour that is not a status). Wins over `thresholds`. Default: from `thresholds`, else the accent. */
  tone?: MeterTone | undefined;
  /** Where the tone turns warning and danger, in the units of `value` and `max`, higher worse unless `higherIsBetter`. */
  thresholds?: MeterThresholds | undefined;
  /** Flips the thresholds for values where lower is worse. Default false. */
  higherIsBetter?: boolean | undefined;
  /** Width in px. The height follows. Default 180. */
  width?: number | undefined;
  /** Stroke width in px. Default 12. */
  thickness?: number | undefined;
  className?: string | undefined;
}

/** One value on a half ring, with the value and its label in the opening. */
export function Gauge({
  value,
  max = 100,
  label,
  formatValue,
  tone,
  thresholds,
  higherIsBetter = false,
  width = 180,
  thickness = 12,
  className,
}: GaugeProps): ReactNode {
  const reduced = useMediaQuery(REDUCED_MOTION);
  const format = formatValue ?? String;
  const shown = clampValue(value, max);
  const share = fraction(value, max);
  const state = tone ?? thresholdTone(value, max, thresholds, higherIsBetter);
  const radius = (width - thickness) / 2;
  const mid = width / 2;
  const arc = `M ${thickness / 2} ${mid} A ${radius} ${radius} 0 0 1 ${width - thickness / 2} ${mid}`;
  return (
    <div
      className={cx('chart-meter', 'chart-gauge', className)}
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={Number.isFinite(max) && max > 0 ? max : 0}
      aria-valuenow={shown}
      aria-valuetext={meterText(value, max, format, state)}
      data-tone={state}
      data-motion={reduced ? 'reduced' : 'full'}
      style={{ width }}
    >
      <svg className="chart-meter-svg" width={width} height={mid + thickness / 2} viewBox={`0 0 ${width} ${mid + thickness / 2}`} aria-hidden="true" focusable="false">
        <path className="chart-meter-track" d={arc} fill="none" strokeWidth={thickness} strokeLinecap="round" />
        {share > 0 ? (
          <path
            className="chart-meter-fill"
            d={arc}
            fill="none"
            strokeWidth={thickness}
            strokeLinecap="round"
            pathLength={1}
            strokeDasharray={1}
            strokeDashoffset={1 - share}
          />
        ) : null}
      </svg>
      <div className="chart-meter-center">
        <span className="chart-meter-value">{format(shown)}</span>
        <span className="chart-meter-label">{label}</span>
      </div>
    </div>
  );
}
