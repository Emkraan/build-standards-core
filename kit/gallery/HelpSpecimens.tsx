/* Gallery specimens for the tip layer: tips (disabled reasons, tipped marks, glossary terms and InfoTip)
   and When. They sit last on the page. Times are offsets from one moment, so a screenshot is the same on
   every run. */

import {
  Badge,
  Button,
  IconButton,
  IconRefresh,
  IconTrash,
  InfoTip,
  StatusDot,
  Term,
  When,
} from '../src/index';
import type { Glossary } from '../src/index';

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const MOMENT = Date.now();
const ago = (ms: number): number => MOMENT - ms;

/** The words the gallery registers once, for every Term and InfoTip. */
export const GALLERY_GLOSSARY: Glossary = {
  pool: {
    term: 'host pool',
    short: 'A group of machines that share one image and settings.',
    long: 'A host pool groups the machines people connect to. Every host in it is built from the same image, so a change to the image reaches all of them.',
    href: 'https://example.com/docs/pools',
  },
  drain: {
    term: 'drain mode',
    short: 'The host takes no new sessions and finishes the ones it has.',
    long: 'A host in drain mode keeps the sessions it has and refuses new ones. Use it before a restart or a removal.',
  },
  compliance: {
    term: 'compliance score',
    short: 'The share of checks a device passes, from 0 to 100 percent.',
  },
};

export function TipsSpecimen() {
  return (
    <div className="gallery-stack">
      <p className="gallery-note">Hover or focus each one. The shell tip layer is on here (AppShell tooltipLayer), so a data-tip attribute works anywhere on the page.</p>
      <div className="gallery-row">
        <Button variant="primary" disabledReason="Choose a host pool first. The size applies to that pool.">
          Scale pool
        </Button>
        <IconButton label="Remove host" icon={<IconTrash />} disabledReason="Drain the host first. A host with sessions cannot be removed." />
        <IconButton label="Refresh" icon={<IconRefresh />} />
      </div>
      <div className="gallery-row">
        <Badge tone="success" dot tip="Reported in the last minute. This is the normal state.">
          Healthy
        </Badge>
        <Badge tone="warning" dot tip="The host takes no new sessions. Normal during a restart.">
          Draining
        </Badge>
        <StatusDot tone="danger" tip="No report for ten minutes. Check the host network." />
        <StatusDot tone="success" label="Available" showLabel tip="Ready for new sessions." />
      </div>
      <p>
        Scale a <Term id="pool" /> by hand, or put it in <Term id="drain" /> before a restart. Each one shows a short meaning on hover or focus.
      </p>
      <div className="gallery-row">
        <span>Compliance</span>
        <InfoTip id="compliance" />
        <span>Pool size</span>
        <InfoTip id="pool" />
      </div>
    </div>
  );
}

export function WhenSpecimen() {
  const rows: Array<{ label: string; value: Date | string | number | null; zone?: string }> = [
    { label: 'A few minutes ago, in the viewer zone', value: ago(4 * MINUTE) },
    { label: 'Hours ago, shown in New York', value: ago(3 * HOUR), zone: 'America/New_York' },
    { label: 'Days ago, shown in UTC', value: ago(3 * DAY), zone: 'UTC' },
    { label: 'Ahead of now', value: MOMENT + 40 * MINUTE, zone: 'UTC' },
    { label: 'No value', value: null },
  ];
  return (
    <div className="gallery-stack">
      <p className="gallery-note">Hover or focus a time for the date, the time and the zone. Every time on a page ticks from one clock.</p>
      {rows.map((row) => (
        <div key={row.label} className="gallery-row">
          <span className="gallery-note">{row.label}:</span>
          <When value={row.value} tabIndex={0} {...(row.zone ? { timeZone: row.zone } : {})} />
        </div>
      ))}
    </div>
  );
}
