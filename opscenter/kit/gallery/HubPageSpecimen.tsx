/* The hub page parts on sample data: the header with both tab levels, a stat row, Sections with
   Panels and Rows, status pills, a filter menu and the compact empty note, under two hub accents. */

import { useState } from 'react';
import {
  EmptyNote,
  FilterMenu,
  HubAccentStyle,
  HubPageHeader,
  HubSegmented,
  HubStatRow,
  HubStatTile,
  HubTabIntro,
  HubTabs,
  IconCheck,
  IconInfo,
  IconSearch,
  IconWarning,
  Panel,
  Row,
  Section,
  StatusPill,
} from '../src/index';
import type { HubAccentMap } from '../src/index';

const ACCENTS: HubAccentMap = {
  work: 'blue',
  reviews: 'teal',
  platform: 'violet',
  people: { mix: ['red', 'violet'], weight: 40 },
};

const LANES = [
  { value: 'all', label: 'All lanes', count: 7 },
  { value: 'build', label: 'Builds', count: 4 },
  { value: 'deploy', label: 'Deploys', count: 3 },
];

export function HubPageSpecimen() {
  const [tab, setTab] = useState('/work');
  const [view, setView] = useState('sprint');
  const [lane, setLane] = useState('all');
  return (
    <div className="gallery-stack">
      <HubAccentStyle map={ACCENTS} />
      <div data-hub="work">
        <HubPageHeader
          hub="work"
          icon={<IconCheck />}
          title="Work"
          subtitle="Tickets, sprints and changes in one place."
          meta={<StatusPill status="healthy" label="Updated 2 minutes ago" />}
          tabs={
            <HubTabs
              label="Work tabs"
              value={tab}
              onChange={setTab}
              items={[
                { id: '/work', label: 'Overview' },
                { id: '/work/sprint', label: 'Sprint', count: 12 },
                { id: '/work/changes', label: 'Changes', count: 2, tone: 'warning' },
                { id: '/work/backlog', label: 'Backlog', live: true },
              ]}
            />
          }
          switcher={
            <HubSegmented
              label="Sprint views"
              value={view}
              onChange={setView}
              options={[
                { value: 'sprint', label: 'Board' },
                { value: 'mine', label: 'Mine', count: 3 },
                { value: 'late', label: 'Late', count: 1, tone: 'danger' },
              ]}
            />
          }
        >
          <HubTabIntro>Updates write straight to the tracker.</HubTabIntro>
        </HubPageHeader>
        <HubStatRow>
          <HubStatTile label="In progress" value={12} icon={<IconInfo />} sub="3 more than last week" />
          <HubStatTile label="Blocked" value={2} tone="danger" icon={<IconWarning />} sub="Waiting on a vendor" />
          <HubStatTile label="Waiting on me" value={0} tone="warning" icon={<IconSearch />} hub="reviews" sub="Nothing to review" />
          <HubStatTile label="Done this week" value={41} tone="success" icon={<IconCheck />} to="#specimen-hub-page" sub="Open the list" />
        </HubStatRow>
        <Section
          title="Needs a decision"
          count={2}
          countTone="warning"
          description="Each row says what happens next."
          actions={<FilterMenu label="Lane" value={lane} allValue="all" onChange={setLane} options={LANES} />}
        >
          <Panel flush>
            <Row dot="warning" title="Roll the scheduler to the new runtime" meta="Change window opens Friday" right={<StatusPill status="needs me" />} onClick={() => {}} />
            <Row dot="danger" title="Nightly sync failed twice" meta="Last run 3 hours ago" right={<StatusPill status="failing" />} to="#specimen-hub-page" />
            <Row icon={<IconCheck />} title="Inventory export" meta="Finished today" right={<StatusPill status="done" />} detail="The export is on the shared drive and the report is attached to the ticket." />
          </Panel>
        </Section>
        <Section title="Parked" tone="info" collapsible open={false}>
          <EmptyNote title="Nothing is parked" body="Items you snooze land here." />
        </Section>
      </div>
      <div data-hub="platform">
        <Section title="Another hub, another accent">
          <div className="gallery-row">
            <Panel interactive selected>
              A selected panel wears the hub accent
            </Panel>
            <Panel tone="danger">A state tone is never an accent</Panel>
          </div>
        </Section>
      </div>
    </div>
  );
}
