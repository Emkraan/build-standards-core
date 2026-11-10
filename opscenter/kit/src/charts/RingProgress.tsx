/* A progress ring for one value against a maximum, with a label and a sub label beside it. Hand-drawn
   SVG (no chart library), coloured by the status tokens and animated on the travel duration. The
   wrapper is a meter named by `label`, with the value as text. The drawing is hidden from
   assistive technology. Under reduced motion the ring does not animate. */

import type { ReactNode } from 'react';
import { cx } from '../lib/env';
import { useMediaQuery } from '../lib/media';
import { clampValue, fraction, meterText, thresholdTone } from './meter';
import type { MeterThresholds, MeterTone } from './meter';

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)';

export interface RingProgressProps {
  value: number;
  /** The full-scale value. Default 100. A max of 0 or less draws an empty ring. */
  max?: number | undefined;
  /** Accessible name of the ring, also shown beside it. */
  label: string;
  /** A smaller line under the label. */
  subLabel?: ReactNode;
  /** Formats the value and the maximum for the value text. Default: the number as is. */
  formatValue?: ((value: number) => string) | undefined;
  /** Text in the ring. Default: the filled share as a whole percent. */
  center?: ReactNode;
  /** Fixed tone (`info` for a colour that is not a status). Wins over `thresholds`. Default: from `thresholds`, else the accent. */
  tone?: MeterTone | undefined;
  /** Where the tone turns warning and danger, in the units of `value` and `max`, higher worse unless `higherIsBetter`. */
  thresholds?: MeterThresholds | undefined;
  /** Flips the thresholds for values where lower is worse. Default false. */
  higherIsBetter?: boolean | undefined;
  /** Diameter in px. Default 72. */
  size?: number | undefined;
  /** Stroke width in px. Default 6. */
  thickness?: number | undefined;
  className?: string | undefined;
}

/** One value on a full ring, with the share in the hole and a label beside it. */
export function RingProgress({
  value,
  max = 100,
  label,
  subLabel,
  formatValue,
  center,
  tone,
  thresholds,
  higherIsBetter = false,
  size = 72,
  thickness = 6,
  className,
}: RingProgressProps): ReactNode {
  const reduced = useMediaQuery(REDUCED_MOTION);
  const format = formatValue ?? String;
  const shown = clampValue(value, max);
  const share = fraction(value, max);
  const state = tone ?? thresholdTone(value, max, thresholds, higherIsBetter);
  const radius = (size - thickness) / 2;
  const mid = size / 2;
  return (
    <div
      className={cx('chart-meter', 'chart-ring', className)}
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={Number.isFinite(max) && max > 0 ? max : 0}
      aria-valuenow={shown}
      aria-valuetext={meterText(value, max, format, state)}
      data-tone={state}
      data-motion={reduced ? 'reduced' : 'full'}
    >
      <div className="chart-ring-dial" style={{ width: size, height: size }}>
        <svg className="chart-meter-svg chart-ring-svg" width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true" focusable="false">
          <circle className="chart-meter-track" cx={mid} cy={mid} r={radius} fill="none" strokeWidth={thickness} />
          {share > 0 ? (
            <circle
              className="chart-meter-fill"
              cx={mid}
              cy={mid}
              r={radius}
              fill="none"
              strokeWidth={thickness}
              strokeLinecap="round"
              pathLength={1}
              strokeDasharray={1}
              strokeDashoffset={1 - share}
            />
          ) : null}
        </svg>
        <span className="chart-ring-center">{center ?? `${Math.round(share * 100)}%`}</span>
      </div>
      <div className="chart-ring-text">
        <span className="chart-ring-label">{label}</span>
        {subLabel !== undefined && subLabel !== null && subLabel !== false ? <span className="chart-ring-sub">{subLabel}</span> : null}
      </div>
    </div>
  );
}
