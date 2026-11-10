/* Gauge and RingProgress: clamping, thresholds, labels, meter semantics, reduced motion and axe. */
import { render, screen } from '@testing-library/react';
import axe from 'axe-core';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { Gauge, RingProgress, clampValue, fraction, meterText, thresholdTone } from '../src/charts';
import { installMatchMedia, media, resetMedia } from './helpers';

beforeEach(() => {
  resetMedia();
  installMatchMedia();
});
afterEach(() => resetMedia());

const fillOffset = (el: HTMLElement): number | null => {
  const fill = el.querySelector('.chart-meter-fill');
  return fill ? Number(fill.getAttribute('stroke-dashoffset')) : null;
};

describe('meter maths', () => {
  it('clamps below 0, above max and non-finite input', () => {
    expect(clampValue(-5, 100)).toBe(0);
    expect(clampValue(150, 100)).toBe(100);
    expect(clampValue(40, 100)).toBe(40);
    expect(clampValue(Number.NaN, 100)).toBe(0);
    expect(clampValue(10, 0)).toBe(0);
    expect(clampValue(10, -3)).toBe(0);
    expect(fraction(50, 200)).toBe(0.25);
    expect(fraction(500, 200)).toBe(1);
    expect(fraction(5, 0)).toBe(0);
  });

  it('picks the tone from the thresholds, higher worse by default', () => {
    const t = { warning: 60, danger: 90 };
    expect(thresholdTone(10, 100)).toBe('accent');
    expect(thresholdTone(10, 100, {})).toBe('accent');
    expect(thresholdTone(59, 100, t)).toBe('success');
    expect(thresholdTone(60, 100, t)).toBe('warning');
    expect(thresholdTone(89, 100, t)).toBe('warning');
    expect(thresholdTone(90, 100, t)).toBe('danger');
    expect(thresholdTone(400, 100, t)).toBe('danger');
    expect(thresholdTone(-4, 100, t)).toBe('success');
  });

  it('reads thresholds in value units, not as a 0 to 1 share', () => {
    const t = { warning: 150, danger: 180 };
    expect(thresholdTone(149, 200, t)).toBe('success');
    expect(thresholdTone(150, 200, t)).toBe('warning');
    expect(thresholdTone(180, 200, t)).toBe('danger');
    expect(thresholdTone(0.9, 1, { warning: 0.7, danger: 0.9 })).toBe('danger');
  });

  it('never produces info from thresholds', () => {
    for (const v of [0, 30, 60, 95]) expect(thresholdTone(v, 100, { warning: 50, danger: 90 })).not.toBe('info');
  });

  it('flips the thresholds when higher is better', () => {
    const t = { warning: 50, danger: 20 };
    expect(thresholdTone(80, 100, t, true)).toBe('success');
    expect(thresholdTone(50, 100, t, true)).toBe('warning');
    expect(thresholdTone(20, 100, t, true)).toBe('danger');
    expect(thresholdTone(-10, 100, t, true)).toBe('danger');
  });

  it('words the value text, with the state only when a tone colours it', () => {
    const f = (n: number) => `${n}%`;
    expect(meterText(42, 100, f, 'accent')).toBe('42% of 100%');
    expect(meterText(150, 100, f, 'danger')).toBe('100% of 100%, critical');
    expect(meterText(5, 100, f, 'warning')).toBe('5% of 100%, warning');
    expect(meterText(5, 100, f, 'success')).toBe('5% of 100%, healthy');
    expect(meterText(5, 100, f, 'info')).toBe('5% of 100%');
  });
});

describe('Gauge', () => {
  it('is a named meter with a value and value text, and hides the drawing', () => {
    const { container } = render(<Gauge value={42} label="Disk used" formatValue={(n) => `${n}%`} />);
    const meter = screen.getByRole('meter', { name: 'Disk used' });
    expect(meter.getAttribute('aria-valuemin')).toBe('0');
    expect(meter.getAttribute('aria-valuemax')).toBe('100');
    expect(meter.getAttribute('aria-valuenow')).toBe('42');
    expect(meter.getAttribute('aria-valuetext')).toBe('42% of 100%');
    expect(container.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true');
    expect(meter.textContent).toContain('42%');
    expect(meter.textContent).toContain('Disk used');
  });

  it('clamps a value below 0 and above max', () => {
    const { rerender } = render(<Gauge value={-20} label="Load" />);
    let meter = screen.getByRole('meter', { name: 'Load' });
    expect(meter.getAttribute('aria-valuenow')).toBe('0');
    expect(fillOffset(meter)).toBeNull();
    rerender(<Gauge value={250} max={200} label="Load" />);
    meter = screen.getByRole('meter', { name: 'Load' });
    expect(meter.getAttribute('aria-valuenow')).toBe('200');
    expect(meter.getAttribute('aria-valuemax')).toBe('200');
    expect(fillOffset(meter)).toBe(0);
    expect(meter.textContent).toContain('200');
    rerender(<Gauge value={50} max={200} label="Load" />);
    expect(fillOffset(screen.getByRole('meter', { name: 'Load' }))).toBe(0.75);
  });

  it('draws an empty gauge for a max of 0', () => {
    render(<Gauge value={5} max={0} label="Empty" />);
    const meter = screen.getByRole('meter', { name: 'Empty' });
    expect(meter.getAttribute('aria-valuenow')).toBe('0');
    expect(fillOffset(meter)).toBeNull();
  });

  it('colours by threshold, and a fixed tone wins', () => {
    const t = { warning: 60, danger: 90 };
    const { rerender } = render(<Gauge value={30} label="Use" thresholds={t} />);
    expect(screen.getByRole('meter').getAttribute('data-tone')).toBe('success');
    rerender(<Gauge value={70} label="Use" thresholds={t} />);
    expect(screen.getByRole('meter').getAttribute('data-tone')).toBe('warning');
    rerender(<Gauge value={95} label="Use" thresholds={t} />);
    const meter = screen.getByRole('meter');
    expect(meter.getAttribute('data-tone')).toBe('danger');
    expect(meter.getAttribute('aria-valuetext')).toBe('95 of 100, critical');
    rerender(<Gauge value={95} label="Use" thresholds={t} tone="accent" />);
    expect(screen.getByRole('meter').getAttribute('data-tone')).toBe('accent');
    rerender(<Gauge value={95} label="Use" />);
    expect(screen.getByRole('meter').getAttribute('data-tone')).toBe('accent');
  });

  it('marks reduced motion on the chart', () => {
    const { unmount } = render(<Gauge value={10} label="Motion" />);
    expect(screen.getByRole('meter').getAttribute('data-motion')).toBe('full');
    unmount();
    media.reducedMotion = true;
    render(<Gauge value={10} label="Motion" />);
    expect(screen.getByRole('meter').getAttribute('data-motion')).toBe('reduced');
  });

  it('has no axe violations', async () => {
    const { container } = render(<Gauge value={72} label="Memory" thresholds={{ warning: 60, danger: 90 }} />);
    const r = await axe.run(container, { rules: { region: { enabled: false } } });
    expect(r.violations.map((v) => v.id)).toEqual([]);
  });
});

describe('RingProgress', () => {
  it('is a named meter with value text, a percent in the ring and both labels', () => {
    const { container } = render(<RingProgress value={30} max={120} label="Backups" subLabel="30 of 120 hosts" formatValue={(n) => `${n} hosts`} />);
    const meter = screen.getByRole('meter', { name: 'Backups' });
    expect(meter.getAttribute('aria-valuenow')).toBe('30');
    expect(meter.getAttribute('aria-valuemax')).toBe('120');
    expect(meter.getAttribute('aria-valuetext')).toBe('30 hosts of 120 hosts');
    expect(container.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true');
    expect(meter.textContent).toContain('25%');
    expect(meter.textContent).toContain('Backups');
    expect(meter.textContent).toContain('30 of 120 hosts');
    expect(fillOffset(meter)).toBe(0.75);
  });

  it('clamps a value below 0 and above max', () => {
    const { rerender } = render(<RingProgress value={-1} label="Ring" />);
    let meter = screen.getByRole('meter', { name: 'Ring' });
    expect(meter.getAttribute('aria-valuenow')).toBe('0');
    expect(meter.textContent).toContain('0%');
    expect(fillOffset(meter)).toBeNull();
    rerender(<RingProgress value={900} label="Ring" />);
    meter = screen.getByRole('meter', { name: 'Ring' });
    expect(meter.getAttribute('aria-valuenow')).toBe('100');
    expect(meter.textContent).toContain('100%');
    expect(fillOffset(meter)).toBe(0);
  });

  it('shows custom centre text and omits an absent sub label', () => {
    const { container } = render(<RingProgress value={5} label="Ring" center="5/100" />);
    expect(screen.getByRole('meter').textContent).toContain('5/100');
    expect(container.querySelector('.chart-ring-sub')).toBeNull();
  });

  it('colours by threshold with the flip for higher is better', () => {
    const { rerender } = render(<RingProgress value={95} label="Ring" thresholds={{ warning: 60, danger: 90 }} />);
    expect(screen.getByRole('meter').getAttribute('data-tone')).toBe('danger');
    rerender(<RingProgress value={95} label="Ring" thresholds={{ warning: 50, danger: 20 }} higherIsBetter />);
    expect(screen.getByRole('meter').getAttribute('data-tone')).toBe('success');
    rerender(<RingProgress value={10} label="Ring" thresholds={{ warning: 50, danger: 20 }} higherIsBetter />);
    expect(screen.getByRole('meter').getAttribute('data-tone')).toBe('danger');
  });

  it('marks reduced motion on the chart', () => {
    media.reducedMotion = true;
    render(<RingProgress value={10} label="Motion" />);
    expect(screen.getByRole('meter').getAttribute('data-motion')).toBe('reduced');
  });

  it('has no axe violations', async () => {
    const { container } = render(<RingProgress value={72} label="Memory" subLabel="of quota" tone="warning" />);
    const r = await axe.run(container, { rules: { region: { enabled: false } } });
    expect(r.violations.map((v) => v.id)).toEqual([]);
  });
});

describe('meter chart styles', () => {
  it('colours only from tokens and animates on the travel duration', async () => {
    const { readFileSync } = await import('node:fs');
    const { join } = await import('node:path');
    const css = readFileSync(join(__dirname, '../src/styles/kit.css'), 'utf8');
    expect(css).toMatch(/\.chart-meter-fill \{[^}]*var\(--dur-travel\)/);
    expect(css).toMatch(/\.chart-meter\[data-tone="info"\] \{ --meter-color: var\(--info\)/);
    expect(css).toMatch(/\.chart-meter\[data-tone="danger"\] \{ --meter-color: var\(--danger\)/);
    const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce) {\n  .modal[data-state="closing"]'));
    expect(reduced).toMatch(/\.chart-meter-fill, [^{]*\{ transition: none !important/);
  });
});
