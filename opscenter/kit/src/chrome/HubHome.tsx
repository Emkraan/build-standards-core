/* The hub home layout (UI standard, shell section 9): three zones, the strip (what needs the person and
   what they can do), the main pair (live and snapshot) and the side (their own shortcuts). Blocks
   are keyed; `tiles` says which show and in what order, so a host hides or reorders them with the
   mechanism it already has. A hidden or empty block leaves no gap. DOM order is reading order: strip,
   main, side. The grid answers to the width of the page area (a container query), not the window. */

import { Fragment } from 'react';
import type { ReactNode } from 'react';

export interface HubZones {
  strip: readonly string[];
  main: readonly string[];
  side: readonly string[];
}

/** The default zones. Pass your own to name other blocks. */
export const DEFAULT_HUB_ZONES: HubZones = {
  strip: ['waiting', 'actions'],
  main: ['live', 'fleet'],
  side: ['pinned'],
};

export interface HubHomeProps {
  /** The blocks by key. A falsy entry (a block with nothing to show) is left out. */
  blocks: Readonly<Record<string, ReactNode>>;
  /** Visible blocks in order. Default: every block, in the order of the zones. */
  tiles?: readonly { key: string }[] | undefined;
  zones?: HubZones | undefined;
  label?: string | undefined;
}

export function HubHome({ blocks, tiles, zones = DEFAULT_HUB_ZONES, label = 'Hub home' }: HubHomeProps) {
  const order = tiles ?? [...zones.strip, ...zones.main, ...zones.side].map((key) => ({ key }));
  const zone = (keys: readonly string[]): ReactNode[] =>
    order.filter((t) => keys.includes(t.key)).flatMap((t) => (blocks[t.key] ? [<Fragment key={t.key}>{blocks[t.key]}</Fragment>] : []));
  const strip = zone(zones.strip);
  const main = zone(zones.main);
  const side = zone(zones.side);
  const hasMain = strip.length > 0 || main.length > 0;
  return (
    <div className="home-fit" role="region" aria-label={label}>
      <div className="home-layout" data-side={side.length > 0 ? '' : undefined} data-main={hasMain ? '' : undefined}>
        {hasMain ? (
          <div className="home-primary">
            {strip.length > 0 ? (
              <div className="home-zone home-strip" data-zone="strip" data-count={strip.length}>
                {strip}
              </div>
            ) : null}
            {main.length > 0 ? (
              <div className="home-zone home-pair" data-zone="main" data-count={main.length}>
                {main}
              </div>
            ) : null}
          </div>
        ) : null}
        {side.length > 0 ? (
          <div className="home-zone home-side" data-zone="side" data-count={side.length}>
            {side}
          </div>
        ) : null}
      </div>
    </div>
  );
}
