/* Stepper and Timeline: the states and what they say to a screen reader, the per-step actions and the
   "waiting on" line, and the entries of a timeline with their time, actor, source and link. */
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Button, STEP_STATE_LABELS, Stepper, Timeline, When } from '../src';
import type { StepItem, StepState, TimelineEntry } from '../src';

async function violations(root: Element): Promise<string[]> {
  const result = await axe.run(root, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } }, resultTypes: ['violations'] });
  return result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(' ')).join(', ')})`);
}

const flat = (text: string | null | undefined): string => (text ?? '').replace(/\s/g, ' ');
// What a reader sees of an element: its text without the hidden description nodes that tips add.
const shown = (el: Element): string => {
  const copy = el.cloneNode(true) as Element;
  for (const node of copy.querySelectorAll('[hidden]')) node.remove();
  return flat(copy.textContent);
};

const STEPS: StepItem[] = [
  { id: 'req', title: 'Request submitted', state: 'done', detail: 'Filed by the service desk.', meta: <When value="2026-10-26T10:00:00Z" /> },
  { id: 'approve', title: 'Approval', state: 'waiting', waitingOn: 'the pool owner', actions: <Button size="sm">Remind</Button> },
  { id: 'build', title: 'Build the host', state: 'current', detail: 'Imaging in progress.' },
  { id: 'verify', title: 'Verify', state: 'failed', detail: 'The health check did not pass.', actions: <Button size="sm">Retry</Button> },
  { id: 'handoff', title: 'Hand over', state: 'upcoming' },
];

describe('Stepper', () => {
  it('is an ordered list with a name, one item per step in the order given', () => {
    render(<Stepper label="Enrolment progress" steps={STEPS} />);
    const list = screen.getByRole('list', { name: 'Enrolment progress' });
    expect(list.tagName).toBe('OL');
    expect(within(list).getAllByRole('listitem')).toHaveLength(5);
    const titles = within(list)
      .getAllByRole('listitem')
      .map((li) => li.querySelector('.stepper-title')?.textContent);
    expect(titles).toEqual([
      'Done: Request submitted',
      'Waiting: Approval',
      'In progress: Build the host',
      'Failed: Verify',
      'Not started: Hand over',
    ]);
  });

  it('says every state in words, so colour is never the only signal', () => {
    for (const state of Object.keys(STEP_STATE_LABELS) as StepState[]) {
      const { container, unmount } = render(<Stepper steps={[{ id: 's', title: 'Step', state }]} />);
      expect(container.querySelector('.stepper-title')?.textContent).toBe(`${STEP_STATE_LABELS[state]}: Step`);
      expect(container.querySelector('.stepper-step')?.getAttribute('data-state')).toBe(state);
      unmount();
    }
  });

  it('marks each state with its own shape and hides the marker from assistive technology', () => {
    const { container } = render(<Stepper steps={STEPS} />);
    const marker = (id: string): Element => (container.querySelectorAll('.stepper-step')[STEPS.findIndex((s) => s.id === id)] as Element).querySelector('.stepper-marker') as Element;
    expect(marker('req').querySelector('[data-icon="check"]')).not.toBeNull();
    expect(marker('approve').querySelector('[data-icon="clock"]')).not.toBeNull();
    expect(marker('build').querySelector('.stepper-dot')).not.toBeNull();
    expect(marker('verify').querySelector('[data-icon="close"]')).not.toBeNull();
    expect(marker('handoff').children).toHaveLength(0);
    for (const el of container.querySelectorAll('.stepper-marker')) expect(el.getAttribute('aria-hidden')).toBe('true');
  });

  it('marks the current step with aria-current and no other', () => {
    const { container } = render(<Stepper steps={STEPS} />);
    const current = container.querySelectorAll('[aria-current="step"]');
    expect(current).toHaveLength(1);
    expect(current[0]?.querySelector('.stepper-title')?.textContent).toContain('Build the host');
  });

  it('shows the detail and the meta of a step, and leaves them out when absent', () => {
    const { container } = render(<Stepper steps={STEPS} />);
    expect(screen.getByText('Filed by the service desk.')).toBeTruthy();
    expect(container.querySelectorAll('.stepper-meta')).toHaveLength(1);
    expect(container.querySelectorAll('.stepper-detail')).toHaveLength(3);
  });

  it('writes a "waiting on" line only for a step that has one, and lets the words be changed', () => {
    const { container, rerender } = render(<Stepper steps={STEPS} />);
    const lines = container.querySelectorAll('.stepper-waiting');
    expect(lines).toHaveLength(1);
    expect(flat(lines[0]?.textContent)).toBe('Waiting on the pool owner');
    rerender(<Stepper steps={STEPS} waitingLabel="Needs" />);
    expect(flat(container.querySelector('.stepper-waiting')?.textContent)).toBe('Needs the pool owner');
  });

  it('puts an actions slot on each step and the buttons work', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(
      <Stepper
        steps={[
          { id: 'a', title: 'Verify', state: 'failed', actions: <Button onClick={onRetry}>Retry</Button> },
          { id: 'b', title: 'Hand over', state: 'upcoming' },
        ]}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(document.querySelectorAll('.stepper-actions')).toHaveLength(1);
  });

  it('lets the state words be replaced, per state', () => {
    const { container } = render(<Stepper steps={STEPS} stateLabels={{ current: 'Running', failed: 'Did not pass' }} />);
    const titles = [...container.querySelectorAll('.stepper-title')].map((el) => el.textContent);
    expect(titles).toContain('Running: Build the host');
    expect(titles).toContain('Did not pass: Verify');
    expect(titles).toContain('Done: Request submitted');
  });

  it('takes a class and renders an empty list for no steps', () => {
    const { container } = render(<Stepper steps={[]} className="mine" />);
    const list = container.querySelector('ol');
    expect(list?.className).toContain('stepper');
    expect(list?.className).toContain('mine');
    expect(list?.children).toHaveLength(0);
  });

  it('has no axe violations with every state', async () => {
    const { container } = render(<Stepper label="Enrolment progress" steps={STEPS} />);
    expect(await violations(container)).toEqual([]);
  });
});

const ENTRIES: TimelineEntry[] = [
  {
    id: 'e1',
    time: '2026-10-26T18:00:00Z',
    actor: 'Dana Whitfield',
    actorTip: 'dana.whitfield@example.com',
    text: 'approved the request',
    source: 'Audit log',
    href: 'https://records.example.com/e1',
    hrefLabel: 'Open the record',
    tone: 'success',
  },
  { id: 'e2', time: '2026-10-26T16:00:00Z', text: 'The nightly sync ran.', source: 'Scheduler' },
  { id: 'e3', time: null, actor: 'Ravi Chandra', text: 'changed the pool size from 4 to 6', href: '/records/e3', tone: 'neutral' },
  { id: 'e4', time: '2026-10-26T15:00:00Z', text: 'The health check failed.', tone: 'danger' },
];

describe('Timeline', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-26T19:04:12Z'));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('is an ordered list with a name, one item per entry in the order given', () => {
    render(<Timeline label="Activity" entries={ENTRIES} />);
    const list = screen.getByRole('list', { name: 'Activity' });
    expect(list.tagName).toBe('OL');
    expect(within(list).getAllByRole('listitem')).toHaveLength(4);
    expect([...list.querySelectorAll('.timeline-line')].map((el) => shown(el))).toEqual([
      'Dana Whitfield approved the request',
      'The nightly sync ran.',
      'Ravi Chandra changed the pool size from 4 to 6',
      'The health check failed.',
    ]);
  });

  it('shows the actor by name and the login as the actor tip, reachable by keyboard and read as the description', () => {
    render(<Timeline entries={ENTRIES} />);
    const actor = screen.getByText('Dana Whitfield');
    expect(actor.getAttribute('data-tip')).toBe('dana.whitfield@example.com');
    expect(actor.getAttribute('tabindex')).toBe('0');
    expect(document.getElementById(actor.getAttribute('aria-describedby') ?? '')?.textContent).toBe('dana.whitfield@example.com');
    // No tip, no tab stop.
    const plain = screen.getByText('Ravi Chandra');
    expect(plain.hasAttribute('data-tip')).toBe(false);
    expect(plain.hasAttribute('tabindex')).toBe(false);
  });

  it('shows the time as a relative time with the absolute time in the tip, in the zone given', () => {
    const { container } = render(<Timeline entries={ENTRIES} timeZone="America/New_York" />);
    const first = container.querySelectorAll('.timeline-item')[0] as Element;
    const when = first.querySelector('time') as Element;
    expect(when.textContent?.startsWith('64 min ago')).toBe(true);
    expect(flat(when.getAttribute('data-tip'))).toContain('EDT');
  });

  it('says "undated" for an entry with no time', () => {
    const { container } = render(<Timeline entries={ENTRIES} />);
    expect((container.querySelectorAll('.timeline-item')[2] as Element).querySelector('.when')?.textContent).toBe('undated');
  });

  it('shows the source as a chip and leaves it out when there is none', () => {
    const { container } = render(<Timeline entries={ENTRIES} />);
    expect([...container.querySelectorAll('.timeline-source')].map((el) => el.textContent)).toEqual(['Audit log', 'Scheduler']);
  });

  it('links to the record with a label, a default label, and the right tab behaviour', () => {
    render(<Timeline entries={ENTRIES} />);
    const external = screen.getByRole('link', { name: 'Open the record (opens in a new tab)' });
    expect(external.getAttribute('href')).toBe('https://records.example.com/e1');
    expect(external.getAttribute('target')).toBe('_blank');
    const inApp = screen.getByRole('link', { name: 'View' });
    expect(inApp.getAttribute('href')).toBe('/records/e3');
    expect(inApp.hasAttribute('target')).toBe(false);
  });

  it('carries the tone on the item for a status and leaves neutral and unset alone', () => {
    const { container } = render(<Timeline entries={ENTRIES} />);
    const tones = [...container.querySelectorAll('.timeline-item')].map((el) => el.getAttribute('data-tone'));
    expect(tones).toEqual(['success', null, null, 'danger']);
  });

  it('hides the marker from assistive technology', () => {
    const { container } = render(<Timeline entries={ENTRIES} />);
    for (const el of container.querySelectorAll('.timeline-marker')) expect(el.getAttribute('aria-hidden')).toBe('true');
  });

  it('shows the empty text for no entries, and nothing when there is none to show', () => {
    const { container, rerender } = render(<Timeline entries={[]} empty="Nothing has happened yet." />);
    expect(screen.getByText('Nothing has happened yet.')).toBeTruthy();
    expect(container.querySelector('ol')).toBeNull();
    rerender(<Timeline entries={[]} />);
    expect(container.innerHTML).toBe('');
  });

  it('takes a class', () => {
    const { container } = render(<Timeline entries={ENTRIES} className="mine" />);
    expect(container.querySelector('ol')?.className).toContain('mine');
  });

  it('has no axe violations', async () => {
    vi.useRealTimers();
    const { container } = render(<Timeline label="Activity" entries={ENTRIES} timeZone="UTC" />);
    expect(await violations(container)).toEqual([]);
  });
});

describe('Stepper and Timeline motion', () => {
  it('has no transition or animation of its own, so nothing ignores prefers-reduced-motion', () => {
    const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../src/styles/kit.css'), 'utf8');
    const rules = css.split('}').filter((rule) => /(^|[\s,{])\.(stepper|timeline)[\w-]*/.test(rule.split('{')[0] ?? ''));
    expect(rules.length).toBeGreaterThan(10);
    for (const rule of rules) expect(rule, rule.trim().slice(0, 60)).not.toMatch(/transition|animation/);
  });
});
