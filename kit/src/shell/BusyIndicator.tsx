/* BusyIndicator: the one processing indicator (UI standard, "One processing indicator"). A slim sweeping bar along
   the bottom edge of the window that reads the busy store (`useBusy`). It never covers the page or takes input
   (pointer-events none), it appears only after the work has lasted `showAfterMs` so a quick call never flashes,
   it says Loading or Saving to a screen reader, and it holds `holdMs` after the last request so chained calls do
   not blink it off. Under reduced motion the bar holds still. Mount it once in the app shell. */

import { useEffect, useState } from 'react';
import { useBusy } from '../lib/busy';

export interface BusyIndicatorProps {
  /** Work shorter than this never shows the bar. Default 350 ms. */
  showAfterMs?: number | undefined;
  /** The bar stays this long after the last request settles. Default 450 ms. */
  holdMs?: number | undefined;
  loadingLabel?: string | undefined;
  savingLabel?: string | undefined;
}

export function BusyIndicator({ showAfterMs = 350, holdMs = 450, loadingLabel = 'Loading', savingLabel = 'Saving' }: BusyIndicatorProps) {
  const { count, writing, since } = useBusy();
  const [visible, setVisible] = useState(false);
  const [label, setLabel] = useState(loadingLabel);

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

  if (!visible) return null;
  return (
    <div className="busy-dock" role="status" aria-live="polite" aria-label={label}>
      <div className="busy-track" aria-hidden="true">
        <span className="busy-sweep" />
      </div>
    </div>
  );
}
