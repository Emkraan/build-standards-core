/* TileReorderStatus: the two visually hidden elements a reorderable tile grid needs. The status
   region says what a move did (polite, so it never interrupts), and the hint is the instruction
   that every tile points at with aria-describedby. Render it once, next to the grid. */

import type { TileReorder } from './useTileReorder';

export interface TileReorderStatusProps {
  reorder: Pick<TileReorder, 'announcement' | 'hint' | 'hintId'>;
}

export function TileReorderStatus({ reorder }: TileReorderStatusProps) {
  return (
    <>
      <p id={reorder.hintId} className="kit-sr-only">
        {reorder.hint}
      </p>
      <div role="status" aria-live="polite" aria-atomic="true" className="kit-sr-only">
        {reorder.announcement}
      </div>
    </>
  );
}
