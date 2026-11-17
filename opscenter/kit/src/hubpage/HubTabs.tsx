/* The two tab levels of a hub page. HubTabs is level one: underline style, the selected tab carries
   the hub accent underline, a count is a Badge (neutral for a plain count, warning or danger for work
   waiting) and live work is a small spinner. HubSegmented is level two: the one segmented switch for
   an in page view, a count is always a Badge, a long label truncates with a tip and the row scrolls
   when it cannot fit. A third level is never a tab row: it becomes a FilterMenu or a select. */

import { Segmented } from '../primitives/Tabs';
import { Tabs } from '../primitives/Tabs';
import { Badge } from '../primitives/marks';
import type { StatusTone } from '../primitives/marks';
import { Spinner } from '../primitives/Spinner';

export interface HubTabItem {
  /** The route or key the tab selects. */
  id: string;
  label: string;
  count?: number | undefined;
  /** Tone of the count Badge. neutral for a plain number, warning or danger for work waiting. */
  tone?: StatusTone | undefined;
  /** Work in progress under this tab. */
  live?: boolean | undefined;
}

export interface HubTabsProps {
  /** Accessible name of the tab list. */
  label: string;
  items: readonly HubTabItem[];
  value: string;
  onChange: (id: string) => void;
}

export function HubTabs({ label, items, value, onChange }: HubTabsProps) {
  return (
    <Tabs
      label={label}
      className="hp-tabs"
      value={value}
      onChange={onChange}
      items={items.map((t) => ({
        id: t.id,
        label: t.label,
        badge:
          t.live || (t.count !== undefined && t.count > 0) ? (
            <>
              {t.live ? (
                <>
                  <Spinner size="xs" arc />
                  <span className="kit-sr-only">working</span>
                </>
              ) : null}
              {t.count !== undefined && t.count > 0 ? <Badge tone={t.tone ?? 'neutral'}>{t.count}</Badge> : null}
            </>
          ) : undefined,
      }))}
    />
  );
}

export interface HubSegOption<T extends string> {
  value: T;
  label: string;
  count?: number | undefined;
  tone?: StatusTone | undefined;
  tip?: string | undefined;
  live?: boolean | undefined;
}

export interface HubSegmentedProps<T extends string> {
  label: string;
  options: readonly HubSegOption<T>[];
  value: T;
  onChange: (value: T) => void;
  full?: boolean | undefined;
}

/** Labels longer than this get their full text as the tip. */
const LONG_LABEL = 24;

export function HubSegmented<T extends string>({ label, options, value, onChange, full }: HubSegmentedProps<T>) {
  return (
    <div className="hp-seg">
      <Segmented
        label={label}
        value={value}
        onChange={onChange}
        full={full}
        options={options.map((o) => ({
          value: o.value,
          label: o.label,
          tone: o.tone,
          tip: o.tip ?? (o.label.length > LONG_LABEL ? o.label : undefined),
          badge: o.count !== undefined && o.count > 0 ? o.count : o.live ? 'live' : undefined,
        }))}
      />
    </div>
  );
}
