import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
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
  Panel,
  Row,
  STATUS_WORDS,
  Section,
  StatusPill,
  hubAccentRules,
  hubPageViolations,
  statusTone,
} from '../src';

function page(title = 'Work', extra: React.ReactNode = null) {
  return render(
    <main>
      <HubPageHeader
        hub="work"
        icon={<svg />}
        title={title}
        subtitle="Tickets and sprints in one place."
        tabs={<HubTabs label="Work tabs" items={[{ id: 'a', label: 'Board', count: 3 }, { id: 'b', label: 'Backlog' }]} value="a" onChange={() => {}} />}
        switcher={<HubSegmented label="Board items" options={[{ value: 'x', label: 'Sprint' }, { value: 'y', label: 'Mine', count: 2 }]} value="x" onChange={() => {}} />}
      >
        <HubTabIntro>Updates write straight to the tracker.</HubTabIntro>
      </HubPageHeader>
      {extra}
    </main>,
  );
}

describe('hub accent map', () => {
  it('writes one rule per key, from hue tokens only', () => {
    const css = hubAccentRules({ work: 'blue', people: { mix: ['red', 'violet'], weight: 40 }, home: 'accent' });
    expect(css).toContain('[data-hub="work"] { --hub: rgb(var(--hue-blue)); }');
    expect(css).toContain('[data-hub="people"] { --hub: color-mix(in srgb, rgb(var(--hue-red)) 40%, rgb(var(--hue-violet)) 60%); }');
    expect(css).toContain('[data-hub="home"] { --hub: rgb(var(--accent-rgb)); }');
  });
  it('refuses a key that is not a plain token and a weight out of range', () => {
    expect(() => hubAccentRules({ 'a"]{x:y}': 'blue' })).toThrow();
    expect(() => hubAccentRules({ a: { mix: ['red', 'blue'], weight: 100 } })).toThrow();
  });
  it('renders a style element', () => {
    const { container } = render(<HubAccentStyle map={{ work: 'teal' }} />);
    expect(container.querySelector('style')?.textContent).toContain('--hue-teal');
  });
});

describe('hub page header', () => {
  it('conforms when the title is the rail label', () => {
    page('Work');
    expect(hubPageViolations(document.body, { railLabel: 'Work' })).toEqual([]);
  });
  it('reports a title that is not the rail label', () => {
    page('Tickets');
    expect(hubPageViolations(document.body, { railLabel: 'Work' })).toEqual(['title "Tickets" is not the rail label "Work"']);
  });
  it('reports a second h1, an upper case section and a second switch', () => {
    page(
      'Work',
      <>
        <h1>Again</h1>
        <Section title="STRENGTHS AND WATCH">x</Section>
      </>,
    );
    const found = hubPageViolations(document.body, { railLabel: 'Work' });
    expect(found.some((f) => f.includes('one h1'))).toBe(true);
    expect(found.some((f) => f.includes('upper case'))).toBe(true);
  });
  it('shows the count as a badge and keeps the tab names', () => {
    page();
    expect(screen.getByRole('tab', { name: /Board/ }).textContent).toContain('3');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Work');
  });
  it('tips a long segmented label', () => {
    render(<HubSegmented label="Items" options={[{ value: 'a', label: 'A very long label that will not fit in one line' }]} value="a" onChange={() => {}} />);
    expect(document.querySelector('[data-tip="A very long label that will not fit in one line"]')).not.toBeNull();
  });
});

describe('Section', () => {
  it('toggles when collapsible', () => {
    render(
      <Section title="Details" count={2} collapsible>
        <p>body text</p>
      </Section>,
    );
    expect(screen.getByText('body text')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Details/ }));
    expect(screen.queryByText('body text')).toBeNull();
  });
});

describe('Panel and Row', () => {
  it('a Row with onClick is one button and fires it', () => {
    const fn = vi.fn();
    render(<Row title="Job one" meta="3 min ago" dot="success" onClick={fn} />);
    fireEvent.click(screen.getByRole('button', { name: /Job one/ }));
    expect(fn).toHaveBeenCalledOnce();
  });
  it('a Row with to renders a link through the default link', () => {
    render(<Row title="Open it" to="/platform" />);
    expect(screen.getByRole('link', { name: /Open it/ }).getAttribute('href')).toBe('/platform');
  });
  it('never renders an unsafe href as a link target', () => {
    render(<Row title="Bad" to="javascript:alert(1)" />);
    expect(screen.getByText('Bad').closest('a')?.getAttribute('href')).toBeNull();
  });
  it('a Panel carries its tone and flush marks', () => {
    const { container } = render(<Panel tone="danger" flush>x</Panel>);
    const el = container.firstElementChild as HTMLElement;
    expect(el.getAttribute('data-tone')).toBe('danger');
    expect(el.hasAttribute('data-flush')).toBe(true);
  });
});

describe('HubStatTile', () => {
  it('mutes a zero and drops its tone', () => {
    const { container } = render(<HubStatRow><HubStatTile label="Failing" value={0} tone="danger" /></HubStatRow>);
    const v = container.querySelector('.hp-stat-value') as HTMLElement;
    expect(v.hasAttribute('data-zero')).toBe(true);
    expect(v.getAttribute('data-tone')).toBeNull();
  });
  it('groups a number and borrows another hub accent', () => {
    const { container } = render(<HubStatTile label="Open" value={12400} hub="reviews" to="/reviews" />);
    expect(container.querySelector('.hp-stat-value')?.textContent).toBe('12,400');
    expect(container.querySelector('a')?.getAttribute('data-hub')).toBe('reviews');
  });
});

describe('StatusPill', () => {
  it('maps every shipped word to a tone and an unknown word to neutral', () => {
    for (const w of STATUS_WORDS) expect(['success', 'info', 'warning', 'danger', 'neutral']).toContain(statusTone(w));
    expect(statusTone('Needs Me')).toBe('warning');
    expect(statusTone('no such word')).toBe('neutral');
  });
  it('lets an app word win', () => {
    expect(statusTone('open', { open: 'danger' })).toBe('danger');
    render(<StatusPill status="quarantined" words={{ quarantined: 'warning' }} />);
    expect(screen.getByText('Quarantined')).toBeTruthy();
  });
});

describe('EmptyNote and FilterMenu', () => {
  it('an EmptyNote is a status line', () => {
    render(<EmptyNote title="Nothing waiting" />);
    expect(screen.getByRole('status').textContent).toContain('Nothing waiting');
  });
  it('a FilterMenu picks one option and shows it on the button', () => {
    const fn = vi.fn();
    render(<FilterMenu label="Lane" allValue="all" value="all" onChange={fn} options={[{ value: 'all', label: 'All lanes', count: 5 }, { value: 'pr', label: 'Pull requests', count: 2 }]} />);
    fireEvent.click(screen.getByRole('button', { name: 'Lane' }));
    fireEvent.click(screen.getByRole('button', { name: /Pull requests/ }));
    expect(fn).toHaveBeenCalledWith('pr');
  });
});
