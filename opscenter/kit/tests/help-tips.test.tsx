/* The tip parts of the help layer: Button disabledReason, Badge and StatusDot tips, Term and the
   glossary, useTip, and the development warning. Each part is also run through axe. */
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  AppShell,
  Badge,
  Button,
  GlossaryProvider,
  IconButton,
  IconTrash,
  Modal,
  Rail,
  StatusDot,
  Term,
  TooltipLayer,
  glossaryEntry,
  useGlossary,
  useTip,
} from '../src';
import type { Glossary } from '../src';
import { devWarn, isProduction, resetDevWarnings } from '../src/lib/env';
import { joinIds } from '../src/primitives/Tooltip';

async function violations(root: Element): Promise<string[]> {
  const result = await axe.run(root, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } }, resultTypes: ['violations'] });
  return result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(' ')).join(', ')})`);
}

const describedBy = (el: Element): string => {
  const id = el.getAttribute('aria-describedby') ?? '';
  return id
    .split(' ')
    .map((one) => document.getElementById(one)?.textContent ?? '')
    .join(' ')
    .trim();
};

describe('useTip and joinIds', () => {
  function Probe({ text }: { text: string | null | undefined }) {
    const { props, description } = useTip(text, 'bottom');
    return (
      <p data-testid="probe" {...props}>
        x{description}
      </p>
    );
  }

  it('gives the tip attributes and a hidden description with the same words', () => {
    render(<Probe text="  Why this is off.  " />);
    const el = screen.getByTestId('probe');
    expect(el.getAttribute('data-tip')).toBe('Why this is off.');
    expect(el.getAttribute('data-tip-side')).toBe('bottom');
    expect(describedBy(el)).toBe('Why this is off.');
    expect(el.querySelector('[hidden]')).not.toBeNull();
  });

  it.each([[undefined], [null], [''], ['   ']])('gives nothing for %j', (text) => {
    render(<Probe text={text} />);
    const el = screen.getByTestId('probe');
    expect(el.hasAttribute('data-tip')).toBe(false);
    expect(el.hasAttribute('aria-describedby')).toBe(false);
    expect(el.querySelector('span')).toBeNull();
  });

  it('joins ids and skips the empty ones', () => {
    expect(joinIds('a', undefined, '', 'b')).toBe('a b');
    expect(joinIds(undefined, null, '  ')).toBeUndefined();
  });
});

describe('Button disabledReason', () => {
  it('is aria-disabled and still focusable, with the reason as its tip and description', async () => {
    const user = userEvent.setup();
    render(<Button disabledReason="Fill in the name first.">Save</Button>);
    const button = screen.getByRole('button', { name: 'Save' });
    expect(button.getAttribute('aria-disabled')).toBe('true');
    expect(button.hasAttribute('disabled')).toBe(false);
    expect(button.getAttribute('data-tip')).toBe('Fill in the name first.');
    expect(describedBy(button)).toBe('Fill in the name first.');
    await user.tab();
    expect(document.activeElement).toBe(button);
  });

  it('ignores a click: no handler, no form submit, no parent handler', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const onParent = vi.fn();
    const onSubmit = vi.fn((event: { preventDefault: () => void }) => event.preventDefault());
    render(
      <div onClick={onParent}>
        <form onSubmit={onSubmit}>
          <Button type="submit" onClick={onClick} disabledReason="Fill in the name first.">
            Save
          </Button>
        </form>
      </div>,
    );
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(onClick).not.toHaveBeenCalled();
    expect(onParent).not.toHaveBeenCalled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('does not run on Enter or Space either', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <Button onClick={onClick} disabledReason="Not yet.">
        Go
      </Button>,
    );
    await user.tab();
    await user.keyboard('{Enter}');
    await user.keyboard(' ');
    expect(onClick).not.toHaveBeenCalled();
  });

  it('is a normal button again when the reason goes away', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const { rerender } = render(
      <Button onClick={onClick} disabledReason="Not yet.">
        Go
      </Button>,
    );
    rerender(
      <Button onClick={onClick} disabledReason={undefined}>
        Go
      </Button>,
    );
    const button = screen.getByRole('button', { name: 'Go' });
    expect(button.hasAttribute('aria-disabled')).toBe(false);
    expect(button.hasAttribute('data-tip')).toBe(false);
    expect(button.hasAttribute('aria-describedby')).toBe(false);
    await user.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('treats a blank reason as no reason', () => {
    render(<Button disabledReason="   ">Go</Button>);
    expect(screen.getByRole('button', { name: 'Go' }).hasAttribute('aria-disabled')).toBe(false);
  });

  it('lets loading win: a real disabled spinner, no reason', () => {
    render(
      <Button loading disabledReason="Not yet.">
        Saving
      </Button>,
    );
    const button = screen.getByRole('button', { name: 'Saving' });
    expect(button.hasAttribute('disabled')).toBe(true);
    expect(button.getAttribute('aria-busy')).toBe('true');
    expect(button.hasAttribute('aria-disabled')).toBe(false);
    expect(button.hasAttribute('data-tip')).toBe(false);
  });

  it('keeps a plain disabled button as it was', () => {
    render(<Button disabled>Off</Button>);
    const button = screen.getByRole('button', { name: 'Off' });
    expect(button.hasAttribute('disabled')).toBe(true);
    expect(button.hasAttribute('aria-disabled')).toBe(false);
  });

  it('keeps the caller aria-describedby and adds the reason', () => {
    render(
      <>
        <span id="hint">Hint text</span>
        <Button aria-describedby="hint" disabledReason="Not yet.">
          Go
        </Button>
      </>,
    );
    const ids = (screen.getByRole('button', { name: 'Go' }).getAttribute('aria-describedby') ?? '').split(' ');
    expect(ids[0]).toBe('hint');
    expect(ids).toHaveLength(2);
  });

  it('writes the label into the tip of an icon-only button, so the verb stays visible', () => {
    render(<IconButton label="Remove host" icon={<IconTrash />} disabledReason="Drain the sessions first." />);
    const button = screen.getByRole('button', { name: 'Remove host' });
    expect(button.getAttribute('data-tip')).toBe('Remove host: Drain the sessions first.');
    expect(button.getAttribute('aria-disabled')).toBe('true');
  });

  it('shows the reason in the tip layer on hover and on keyboard focus', () => {
    vi.useFakeTimers();
    try {
      render(
        <>
          <Button disabledReason="You need the Operator role.">Remove</Button>
          <TooltipLayer />
        </>,
      );
      const button = screen.getByRole('button', { name: 'Remove' });
      fireEvent.pointerOver(button);
      act(() => {
        vi.advanceTimersByTime(2000);
      });
      expect(document.querySelector('.tooltip')?.textContent).toContain('You need the Operator role.');
    } finally {
      vi.useRealTimers();
    }
  });

  it('has no axe violations, alone or inside a form', async () => {
    const { container } = render(
      <form aria-label="Edit">
        <Button disabledReason="Fill in the name first.">Save</Button>
        <IconButton label="Remove host" icon={<IconTrash />} disabledReason="Drain the sessions first." />
      </form>,
    );
    expect(await violations(container)).toEqual([]);
  });
});

describe('Modal primary action disabledReason', () => {
  it('passes the reason to the button and holds back Cmd or Ctrl and Enter', async () => {
    const onSubmit = vi.fn((event: { preventDefault: () => void }) => event.preventDefault());
    const { rerender } = render(
      <Modal
        open
        onClose={() => undefined}
        title="Edit pool"
        onSubmit={onSubmit}
        primaryAction={{ label: 'Save', disabledReason: 'Name the pool first.' }}
      >
        <input aria-label="Name" />
      </Modal>,
    );
    const save = screen.getByRole('button', { name: 'Save' });
    expect(save.getAttribute('aria-disabled')).toBe('true');
    expect(save.getAttribute('data-tip')).toBe('Name the pool first.');
    fireEvent.keyDown(screen.getByLabelText('Name'), { key: 'Enter', ctrlKey: true });
    expect(onSubmit).not.toHaveBeenCalled();

    rerender(
      <Modal open onClose={() => undefined} title="Edit pool" onSubmit={onSubmit} primaryAction={{ label: 'Save' }}>
        <input aria-label="Name" />
      </Modal>,
    );
    fireEvent.keyDown(screen.getByLabelText('Name'), { key: 'Enter', ctrlKey: true });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});

describe('Badge and StatusDot tips', () => {
  it('Badge with a tip is focusable, shows it and describes itself with it', () => {
    render(<Badge tone="warning" tip="Normal for a new host. It clears in a few minutes.">Draining</Badge>);
    const badge = screen.getByText('Draining');
    expect(badge.getAttribute('data-tip')).toBe('Normal for a new host. It clears in a few minutes.');
    expect(badge.getAttribute('tabindex')).toBe('0');
    expect(describedBy(badge)).toBe('Normal for a new host. It clears in a few minutes.');
  });

  it('Badge without a tip is unchanged: no tip, no tab stop', () => {
    render(<Badge>Plain</Badge>);
    const badge = screen.getByText('Plain');
    expect(badge.hasAttribute('data-tip')).toBe(false);
    expect(badge.hasAttribute('tabindex')).toBe(false);
    expect(badge.hasAttribute('aria-describedby')).toBe(false);
  });

  it('Badge honours tabIndex={-1} for a badge inside a focusable row, and the side', () => {
    render(
      <Badge tip="Tip" tipSide="right" tabIndex={-1}>
        Row
      </Badge>,
    );
    const badge = screen.getByText('Row');
    expect(badge.getAttribute('tabindex')).toBe('-1');
    expect(badge.getAttribute('data-tip-side')).toBe('right');
  });

  it('Badge keeps its remove button and its name', () => {
    render(
      <Badge tip="A tag." onRemove={() => undefined}>
        prod
      </Badge>,
    );
    expect(screen.getByRole('button', { name: 'Remove prod' })).toBeTruthy();
  });

  it('StatusDot with a label takes the tip as its description', () => {
    render(<StatusDot tone="success" label="Healthy" showLabel tip="The agent reported in the last minute." />);
    const wrap = screen.getByText('Healthy').parentElement as HTMLElement;
    expect(wrap.getAttribute('data-tip')).toBe('The agent reported in the last minute.');
    expect(describedBy(wrap)).toBe('The agent reported in the last minute.');
    expect(wrap.getAttribute('tabindex')).toBe('0');
  });

  it('a bare StatusDot with a tip is a named, focusable image whose name is the tip', () => {
    render(<StatusDot tone="danger" tip="No heartbeat for ten minutes. Check the host." />);
    const dot = screen.getByRole('img', { name: 'No heartbeat for ten minutes. Check the host.' });
    expect(dot.getAttribute('tabindex')).toBe('0');
    expect(dot.getAttribute('data-tip')).toBe('No heartbeat for ten minutes. Check the host.');
  });

  it('a bare StatusDot with a label and a tip keeps the label as the name and the tip as the description', () => {
    render(<StatusDot tone="warning" label="Degraded" tip="Slower than usual. It is not an outage." />);
    const dot = screen.getByRole('img', { name: 'Degraded' });
    expect(describedBy(dot)).toBe('Slower than usual. It is not an outage.');
  });

  it('StatusDot without a tip is unchanged', () => {
    const { container } = render(<StatusDot tone="success" />);
    const dot = container.querySelector('.status-dot') as HTMLElement;
    expect(dot.getAttribute('aria-hidden')).toBe('true');
    expect(dot.hasAttribute('tabindex')).toBe(false);
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <div>
        <Badge tone="success" tip="Running and healthy. This is the normal state.">Available</Badge>
        <StatusDot tone="danger" tip="No heartbeat for ten minutes." />
        <StatusDot tone="success" label="Healthy" showLabel tip="Reported in the last minute." />
      </div>,
    );
    expect(await violations(container)).toEqual([]);
  });
});

describe('Term and the glossary', () => {
  const glossary: Glossary = {
    pool: { term: 'host pool', short: 'A group of session hosts that share one image.', long: 'A host pool groups the machines users connect to.', href: 'https://docs.example.com/pool' },
    drain: { term: 'drain mode', short: 'The host takes no new sessions.' },
  };

  beforeEach(() => {
    resetDevWarnings();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  it('renders the entry term with its short text as the tip and the description, and is focusable', async () => {
    const user = userEvent.setup();
    render(
      <GlossaryProvider glossary={glossary}>
        <p>
          Scale a <Term id="pool" /> by hand.
        </p>
      </GlossaryProvider>,
    );
    const term = screen.getByText('host pool');
    expect(term.classList.contains('term')).toBe(true);
    expect(term.getAttribute('data-tip')).toBe('A group of session hosts that share one image.');
    expect(describedBy(term)).toBe('A group of session hosts that share one image.');
    expect(term.getAttribute('tabindex')).toBe('0');
    await user.tab();
    expect(document.activeElement).toBe(term);
  });

  it('shows the words it is given instead of the term, for a plural or a sentence start', () => {
    render(
      <GlossaryProvider glossary={glossary}>
        <Term id="pool">Host pools</Term>
      </GlossaryProvider>,
    );
    expect(screen.getByText('Host pools').getAttribute('data-tip')).toBe('A group of session hosts that share one image.');
  });

  it('renders plain text for an unknown id and warns once in development', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const { container } = render(
      <GlossaryProvider glossary={glossary}>
        <p>
          A <Term id="nope">mystery</Term> and another <Term id="nope">mystery</Term>.
        </p>
      </GlossaryProvider>,
    );
    expect(container.querySelector('.term')).toBeNull();
    expect(container.querySelector('[data-tip]')).toBeNull();
    expect(container.textContent).toBe('A mystery and another mystery.');
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0]?.[0])).toContain('nope');
  });

  it('shows the id when an unknown Term has no children', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const { container } = render(<Term id="lonely" />);
    expect(container.textContent).toBe('lonely');
  });

  it('stays silent in production', () => {
    vi.stubEnv('NODE_ENV', 'production');
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const { container } = render(<Term id="nope">mystery</Term>);
    expect(container.textContent).toBe('mystery');
    expect(warn).not.toHaveBeenCalled();
  });

  it('renders plain text outside any provider', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const { container } = render(<Term id="pool">host pool</Term>);
    expect(container.querySelector('.term')).toBeNull();
  });

  it('does not take Object.prototype names as ids', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const { container } = render(
      <GlossaryProvider glossary={glossary}>
        <Term id="constructor">constructor</Term>
        <Term id="toString">toString</Term>
      </GlossaryProvider>,
    );
    expect(container.querySelector('.term')).toBeNull();
  });

  it('merges nested providers and lets the inner one win on a shared id', () => {
    function Read() {
      const g = useGlossary();
      return (
        <p data-testid="read">
          {glossaryEntry(g, 'pool')?.term}|{glossaryEntry(g, 'drain')?.term}|{glossaryEntry(g, 'extra')?.term}
        </p>
      );
    }
    render(
      <GlossaryProvider glossary={glossary}>
        <GlossaryProvider glossary={{ pool: { term: 'pool (inner)', short: 'Inner.' }, extra: { term: 'extra', short: 'Extra.' } }}>
          <Read />
        </GlossaryProvider>
      </GlossaryProvider>,
    );
    expect(screen.getByTestId('read').textContent).toBe('pool (inner)|drain mode|extra');
  });

  it('is registered once through AppShell glossary and reaches every page', () => {
    render(
      <AppShell glossary={glossary} rail={<Rail brandName="Test" brandMark="T" version="1.0.0" />}>
        <Term id="drain" />
      </AppShell>,
    );
    expect(screen.getByText('drain mode').getAttribute('data-tip')).toBe('The host takes no new sessions.');
  });

  it('passes extra attributes and a class through', () => {
    render(
      <GlossaryProvider glossary={glossary}>
        <Term id="pool" className="mine" data-x="1" />
      </GlossaryProvider>,
    );
    const term = screen.getByText('host pool');
    expect(term.className).toContain('term');
    expect(term.className).toContain('mine');
    expect(term.getAttribute('data-x')).toBe('1');
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <GlossaryProvider glossary={glossary}>
        <p>
          Each <Term id="pool" /> can be put in <Term id="drain" /> before a restart.
        </p>
      </GlossaryProvider>,
    );
    expect(await violations(container)).toEqual([]);
  });
});

describe('development warnings', () => {
  beforeEach(() => {
    resetDevWarnings();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  it('warns once per key and again after a reset', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    devWarn('k', 'first');
    devWarn('k', 'again');
    devWarn('other', 'second');
    expect(warn).toHaveBeenCalledTimes(2);
    resetDevWarnings();
    devWarn('k', 'after reset');
    expect(warn).toHaveBeenCalledTimes(3);
  });

  it('prefixes the message so it is easy to find', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    devWarn('p', 'something is off');
    expect(warn).toHaveBeenCalledWith('kit: something is off');
  });

  it('is silent in production and says so through isProduction', () => {
    vi.stubEnv('NODE_ENV', 'production');
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    expect(isProduction()).toBe(true);
    devWarn('p', 'quiet');
    expect(warn).not.toHaveBeenCalled();
  });

  it('counts a test build as development', () => {
    expect(isProduction()).toBe(false);
  });
});
