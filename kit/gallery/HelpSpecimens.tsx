/* Gallery specimens for the help layer: tips (disabled reasons, tipped marks, glossary terms and
   InfoTip), When, page help with the Help button and drawer, Stepper and Timeline. They sit last on the
   page. Times are offsets from one moment, so a screenshot is the same on every run. */

import { useState } from 'react';
import type { ComponentProps, ReactNode } from 'react';
import {
  Badge,
  Button,
  CommandPalette,
  GlossaryProvider,
  HelpProvider,
  IconButton,
  IconRefresh,
  IconTrash,
  InfoTip,
  Segmented,
  StatusDot,
  Stepper,
  Term,
  Timeline,
  When,
  useHelp,
  useHelpPaletteItems,
  usePageHelp,
} from '../src/index';
import type { Glossary, PageHelp, StepItem, TimelineEntry } from '../src/index';

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const MOMENT = Date.now();
const ago = (ms: number): number => MOMENT - ms;

/** The words the gallery registers once, for every Term, InfoTip and the help drawer. */
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

/** The providers the gallery mounts above the shell and the palette, so the palette can list help topics. */
export function GalleryHelpProviders({ children }: { children: ReactNode }) {
  return (
    <GlossaryProvider glossary={GALLERY_GLOSSARY}>
      <HelpProvider pathname="#gallery">{children}</HelpProvider>
    </GlossaryProvider>
  );
}

/** The command palette with the help of the page on screen merged in. */
export function GalleryPalette({ items, ...rest }: ComponentProps<typeof CommandPalette>) {
  const help = useHelpPaletteItems();
  return <CommandPalette {...rest} items={[...items, ...help]} />;
}

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

const GALLERY_HELP: PageHelp = {
  title: 'Kit gallery',
  summary: 'Every shared component on one page, in both themes.',
  steps: ['Pick a theme and an accent at the top.', 'Scroll to a specimen and try it with the keyboard.', 'Open search to jump to a section.'],
  terms: ['pool', 'drain'],
  links: [{ label: 'Kit documentation', href: 'https://example.com/docs/kit' }],
};

export function PageHelpSpecimen() {
  usePageHelp(GALLERY_HELP);
  const help = useHelp();
  return (
    <div className="gallery-stack">
      <p className="gallery-note">
        This page registers its help with usePageHelp, so the Header shows a Help button and search lists the page and its words. The drawer holds the
        summary, the steps, the words and the links.
      </p>
      <div className="gallery-row">
        <Button onClick={() => help?.setOpen(true)}>Show help for this page</Button>
      </div>
    </div>
  );
}

const STEPS: StepItem[] = [
  { id: 'request', title: 'Request filed', state: 'done', detail: 'Submitted by the service desk.', meta: <When value={ago(5 * HOUR)} /> },
  {
    id: 'approval',
    title: 'Approval',
    state: 'waiting',
    waitingOn: 'the host pool owner',
    detail: 'The owner was asked to approve the new size.',
    actions: <Button size="sm">Send a reminder</Button>,
  },
  { id: 'build', title: 'Build the hosts', state: 'current', detail: 'Imaging 3 of 6 hosts.', meta: <When value={ago(20 * MINUTE)} /> },
  {
    id: 'verify',
    title: 'Verify the hosts',
    state: 'failed',
    detail: 'The health check did not pass on 2 hosts.',
    actions: (
      <>
        <Button size="sm" variant="primary">
          Retry the check
        </Button>
        <Button size="sm" variant="ghost">
          View the log
        </Button>
      </>
    ),
  },
  { id: 'handoff', title: 'Hand over to the pool', state: 'upcoming' },
];

export function StepperSpecimen() {
  return (
    <div className="gallery-stack">
      <p className="gallery-note">The five states: done, waiting, in progress, failed and not started. Each says its state in words as well as in its mark.</p>
      <Stepper label="Scale-out progress" steps={STEPS} />
    </div>
  );
}

const ENTRIES: TimelineEntry[] = [
  {
    id: 'approved',
    time: ago(35 * MINUTE),
    actor: 'Ada Lovelace',
    actorTip: 'ada@example.com',
    text: 'approved the request to scale the pool',
    source: 'Audit log',
    href: 'https://example.com/records/approved',
    hrefLabel: 'Open the record',
    tone: 'success',
  },
  { id: 'check', time: ago(3 * HOUR), text: 'The health check failed on 2 hosts.', source: 'Monitor', tone: 'danger' },
  {
    id: 'resize',
    time: ago(DAY + 2 * HOUR),
    actor: 'Grace Hopper',
    actorTip: 'grace@example.com',
    text: 'changed the pool size from 4 to 6',
    source: 'Console',
  },
  { id: 'created', time: ago(9 * DAY), text: 'The pool was created.', source: 'Console' },
];

export function TimelineSpecimen() {
  const [zone, setZone] = useState('UTC');
  return (
    <div className="gallery-stack">
      <p className="gallery-note">One sentence per entry. A person is shown by name with the address in the tip, and the zone is a prop.</p>
      <Segmented
        label="Time zone"
        value={zone}
        onChange={setZone}
        options={[
          { value: 'UTC', label: 'UTC' },
          { value: 'America/New_York', label: 'New York' },
        ]}
      />
      <Timeline label="Pool activity" entries={ENTRIES} timeZone={zone} />
    </div>
  );
}
