/* BusyIndicator: the one processing indicator (UI standard, "One processing indicator"). A slim sweeping bar along
   the bottom edge of the window that reads the busy store (`useBusy`). It never covers the page or takes input
   (pointer-events none), it appears only after the work has lasted `showAfterMs` so a quick call never flashes,
   it says Loading or Saving to a screen reader, and it holds `holdMs` after the last request so chained calls do
   not blink it off. Under reduced motion the bar holds still. When the app lets reads be stopped
   (`installBusyTracking({ cancel: true })`), a chip with the elapsed seconds appears after `cancelAfterMs`, with Cancel
   request for the reads that can be stopped; the bar itself stays out of the way, only the chip takes a click.
   Pass the current `route` and a read that outlived its page is stopped when the route changes. Mount it once in the
   app shell. */

import { useEffect, useState } from 'react';
import { abortStaleReads, cancelBusyReads, useBusy } from '../lib/busy';

export interface BusyIndicatorProps {
  /** Work shorter than this never shows the bar. Default 350 ms. */
  showAfterMs?: number | undefined;
  /** The bar stays this long after the last request settles. Default 450 ms. */
  holdMs?: number | undefined;
  loadingLabel?: string | undefined;
  savingLabel?: string | undefined;
  /** Seconds of work before the chip with the elapsed time (and Cancel request) shows. Default 5000 ms. */
  cancelAfterMs?: number | undefined;
  cancelLabel?: string | undefined;
  /** The current route (the path). When it changes, reads that belong to the page left behind are stopped. Needs `cancel` on `installBusyTracking`. */
  route?: string | undefined;
  /** Stops the reads. Default `cancelBusyReads`. */
  onCancel?: (() => void) | undefined;
}

export function BusyIndicator({ showAfterMs = 350, holdMs = 450, loadingLabel = 'Loading', savingLabel = 'Saving', cancelAfterMs = 5000, cancelLabel = 'Cancel request', route, onCancel = cancelBusyReads }: BusyIndicatorProps) {
  const { count, writing, since, cancellable } = useBusy();
  const [visible, setVisible] = useState(false);
  const [label, setLabel] = useState(loadingLabel);
  const [secs, setSecs] = useState(0);

  // Leaving a page stops the slow reads it started.
  useEffect(() => {
    if (route !== undefined) abortStaleReads(route);
  }, [route]);

  useEffect(() => {
    if (writing) setLabel(savingLabel);
    else if (count > 0) setLabel(loadingLabel);
  }, [count, writing, loadingLabel, savingLabel]);

  useEffect(() => {
    if (count > 0) {
      const t = window.setTimeout(() => setVisible(true), Math.max(0, showAfterMs - (Date.now() - since)));
      return () => window.clearTimeout(t);
    }
    const t = window.setTimeout(() => setVisible(false), holdMs);
    return () => window.clearTimeout(t);
  }, [count, since, showAfterMs, holdMs]);

  useEffect(() => {
    if (!visible || !since) {
      setSecs(0);
      return;
    }
    const tick = () => setSecs(Math.floor((Date.now() - since) / 1000));
    tick();
    const t = window.setInterval(tick, 500);
    return () => window.clearInterval(t);
  }, [visible, since]);

  if (!visible) return null;
  const long = secs * 1000 >= cancelAfterMs;
  return (
    <div className="busy-dock" role="status" aria-live="polite" aria-label={label}>
      {long ? (
        <div className="busy-chip">
          <span>
            {label}, {secs}s
          </span>
          {cancellable > 0 ? (
            <button type="button" className="busy-cancel" onClick={onCancel}>
              {cancelLabel}
            </button>
          ) : null}
        </div>
      ) : null}
      <div className="busy-track" aria-hidden="true">
        <span className="busy-sweep" />
      </div>
    </div>
  );
}
