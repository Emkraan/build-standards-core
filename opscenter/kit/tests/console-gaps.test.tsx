/* Gaps found while moving five consoles onto the kit: success and warning buttons, the extra
   hues, Checkbox, Radio, RadioGroup and Switch, Modal hideHead, sizes and pass-through, Segmented
   icons, Select labelledBy, Stat and StatRow, an app theme default that keeps a stored System
   pick, the Rail status line, and toasts deduped by id. */
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { useState } from 'react';
import type { ReactElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { categoricalHues, extraHues, tokens } from '../../tokens/tokens';
import {
  AppShell,
  Button,
  CATEGORICAL_HUES,
  Checkbox,
  EXTRA_HUES,
  Header,
  Modal,
  NavGroup,
  NavItem,
  Radio,
  RadioGroup,
  Rail,
  Segmented,
  Select,
  Stat,
  StatRow,
  STORAGE_KEYS,
  Switch,
  ThemeProvider,
  Toaster,
  hueFor,
  isCategoricalHue,
  isMarkHue,
  isSeriesHue,
  themeInitScript,
  useTheme,
  useToast,
} from '../src/index';
import type { ToastApi } from '../src/index';

const AXE: axe.RunOptions = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } }, resultTypes: ['violations'] };

async function violations(root: Element): Promise<string[]> {
  const result = await axe.run(root, AXE);
  return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`);
}

const css = readFileSync(resolve(__dirname, '../src/styles/kit.css'), 'utf8');
const hub = readFileSync(resolve(__dirname, '../../tokens/hub-layer.css'), 'utf8');

function hex(c: string): number[] {
  const m = /^#([0-9a-f]{6})$/i.exec(c);
  if (!m || !m[1]) throw new Error(`not a hex colour: ${c}`);
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function lum(c: number[]): number {
  const [r = 0, g = 0, b = 0] = c.map((v) => {
    const s = v / 255;
    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

describe('light surface ladder', () => {
  it('puts white cards on a light grey canvas and leaves dark stepping up', () => {
    expect(tokens.light['surface-1']).toBe('#ffffff');
    expect(lum(hex(tokens.light['bg-canvas']))).toBeLessThan(lum(hex(tokens.light['surface-1'])));
    // Dark keeps the raised ladder: each step lighter than the canvas.
    expect(lum(hex(tokens.dark['surface-1']))).toBeGreaterThan(lum(hex(tokens.dark['bg-canvas'])));
    expect(tokens.dark['surface-1']).toBe('#121a2d');
    expect(tokens.light['surface-1-rgb']).toBe('255 255 255');
  });

  it('keeps hover (surface-3) visible on the canvas and on a card in light', () => {
    const ratio = (a: string, b: string) => {
      const [x, y] = [lum(hex(a)), lum(hex(b))].sort((m, n) => n - m) as [number, number];
      return (x + 0.05) / (y + 0.05);
    };
    expect(ratio(tokens.light['surface-3'], tokens.light['bg-canvas'])).toBeGreaterThan(1.05);
    expect(ratio(tokens.light['surface-3'], tokens.light['surface-1'])).toBeGreaterThan(1.15);
    expect(ratio(tokens.light['surface-2'], tokens.light['surface-1'])).toBeGreaterThan(1.05);
  });

  it('keeps the interaction steps above surface-1 darker than the card in light', () => {
    const card = lum(hex(tokens.light['surface-1']));
    for (const step of ['surface-2', 'surface-3', 'surface-4', 'surface-5'] as const) {
      expect(lum(hex(tokens.light[step]))).toBeLessThan(card);
    }
  });
});

describe('extra hues', () => {
  it('match the token source and stay out of the series rotation', () => {
    expect([...EXTRA_HUES]).toEqual([...extraHues]);
    expect([...CATEGORICAL_HUES]).toEqual([...categoricalHues]);
    // CategoricalHue keeps its meaning (the six), MarkHue is the wider set every hue prop takes.
    expect(isCategoricalHue('yellow')).toBe(false);
    expect(isCategoricalHue('teal')).toBe(true);
    expect(isSeriesHue('yellow')).toBe(false);
    expect(isMarkHue('yellow')).toBe(true);
    expect(isMarkHue('ink')).toBe(true);
    expect(isMarkHue('pink')).toBe(false);
    for (const name of ['Ada Lovelace', 'Grace Hopper', 'Alan Turing', 'x', 'yy', 'zzz']) {
      expect(CATEGORICAL_HUES as readonly string[]).toContain(hueFor(name));
    }
  });

  it('have a class recipe and a nav icon colour', () => {
    for (const h of EXTRA_HUES) {
      expect(hub).toContain(`.hue-${h}`);
      expect(hub).toContain(`[data-hue="${h}"]`);
      expect(tokens.dark[`hue-${h}`]).toMatch(/^\d+ \d+ \d+$/);
      expect(tokens.light[`hue-${h}-d`]).toMatch(/^\d+ \d+ \d+$/);
    }
  });
});

describe('success and warning buttons', () => {
  it('render solid and subtle variants with token styles', async () => {
    const { container } = render(
      <div>
        <Button variant="success">Approve</Button>
        <Button variant="success-subtle">Mark done</Button>
        <Button variant="warning">Pause</Button>
        <Button variant="warning-subtle">Snooze</Button>
        <Button variant="danger-subtle">Remove</Button>
      </div>,
    );
    expect(screen.getByRole('button', { name: 'Approve' }).getAttribute('data-variant')).toBe('success');
    expect(screen.getByRole('button', { name: 'Snooze' }).getAttribute('data-variant')).toBe('warning-subtle');
    for (const v of ['success', 'warning', 'success-subtle', 'warning-subtle', 'danger-subtle']) {
      expect(css).toContain(`.btn[data-variant="${v}"]`);
    }
    expect(await violations(container)).toEqual([]);
  });
});

describe('Checkbox', () => {
  it('is a labelled native checkbox with a description, sizes and the mixed state', async () => {
    const onCheckedChange = vi.fn();
    const { container } = render(
      <div>
        <Checkbox label="Email me" description="Once a day at most" onCheckedChange={onCheckedChange} />
        <Checkbox label="Select all" indeterminate size="sm" />
        <Checkbox label="Locked" disabled defaultChecked />
        <Checkbox label="Hidden label" hideLabel />
      </div>,
    );
    const box = screen.getByRole('checkbox', { name: 'Email me' });
    expect(box.getAttribute('aria-describedby')).toBeTruthy();
    expect(document.getElementById(box.getAttribute('aria-describedby') ?? '')?.textContent).toBe('Once a day at most');
    await userEvent.click(box);
    expect(onCheckedChange).toHaveBeenLastCalledWith(true);
    box.focus();
    await userEvent.keyboard(' ');
    expect(onCheckedChange).toHaveBeenLastCalledWith(false);
    await userEvent.click(screen.getByText('Email me'));
    expect(onCheckedChange).toHaveBeenLastCalledWith(true);
    const all = screen.getByRole('checkbox', { name: 'Select all' }) as HTMLInputElement;
    expect(all.indeterminate).toBe(true);
    // A click clears the native flag. The prop stays the truth on the next render.
    await userEvent.click(all);
    expect(all.indeterminate).toBe(false);
    expect(all.closest('.choice')?.getAttribute('data-size')).toBe('sm');
    expect((screen.getByRole('checkbox', { name: 'Locked' }) as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByRole('checkbox', { name: 'Hidden label' })).toBeTruthy();
    expect(await violations(container)).toEqual([]);
  });
});

describe('RadioGroup and Radio', () => {
  it('names the group, moves with the keyboard and reports the value', async () => {
    const onChange = vi.fn();
    function Demo() {
      const [value, setValue] = useState('daily');
      return (
        <RadioGroup
          label="Frequency"
          value={value}
          onChange={(v) => {
            setValue(v);
            onChange(v);
          }}
          options={[
            { value: 'daily', label: 'Daily' },
            { value: 'weekly', label: 'Weekly', description: 'Mondays' },
            { value: 'never', label: 'Never', disabled: true },
          ]}
          hint="Applies to every channel"
        />
      );
    }
    const { container } = render(<Demo />);
    const group = screen.getByRole('group', { name: 'Frequency' });
    expect(group).toBeTruthy();
    const daily = screen.getByRole('radio', { name: 'Daily' }) as HTMLInputElement;
    const weekly = screen.getByRole('radio', { name: 'Weekly' }) as HTMLInputElement;
    expect(daily.checked).toBe(true);
    expect(daily.name).toBe(weekly.name);
    expect(daily.getAttribute('aria-describedby')).toBeTruthy();
    await userEvent.click(weekly);
    expect(onChange).toHaveBeenLastCalledWith('weekly');
    expect(weekly.checked).toBe(true);
    expect((screen.getByRole('radio', { name: 'Never' }) as HTMLInputElement).disabled).toBe(true);
    expect(await violations(container)).toEqual([]);
  });

  it('works uncontrolled with Radio children and a group size and disabled state', () => {
    render(
      <RadioGroup label="Size" defaultValue="m" size="sm" disabled orientation="horizontal">
        <Radio value="s" label="Small" />
        <Radio value="m" label="Medium" />
      </RadioGroup>,
    );
    const m = screen.getByRole('radio', { name: 'Medium' }) as HTMLInputElement;
    expect(m.checked).toBe(true);
    expect(m.disabled).toBe(true);
    expect(m.closest('.choice')?.getAttribute('data-size')).toBe('sm');
    expect(screen.getByRole('group', { name: 'Size' }).getAttribute('data-orientation')).toBe('horizontal');
  });
});

describe('Switch', () => {
  it('is a labelled switch that toggles with click, Space and its label', async () => {
    const onChange = vi.fn();
    const { container } = render(
      <form data-testid="form">
        <Switch label="Auto refresh" description="Every 30 seconds" onChange={onChange} name="auto" />
        <Switch label="Locked" disabled checked size="sm" />
      </form>,
    );
    const sw = screen.getByRole('switch', { name: 'Auto refresh' });
    expect(sw.getAttribute('aria-checked')).toBe('false');
    await userEvent.click(sw);
    expect(sw.getAttribute('aria-checked')).toBe('true');
    expect(onChange).toHaveBeenLastCalledWith(true);
    expect((container.querySelector('input[name="auto"]') as HTMLInputElement | null)?.value).toBe('on');
    sw.focus();
    await userEvent.keyboard(' ');
    expect(sw.getAttribute('aria-checked')).toBe('false');
    expect(container.querySelector('input[name="auto"]')).toBeNull();
    await userEvent.click(screen.getByText('Auto refresh'));
    expect(sw.getAttribute('aria-checked')).toBe('true');
    const locked = screen.getByRole('switch', { name: 'Locked' }) as HTMLButtonElement;
    expect(locked.disabled).toBe(true);
    await userEvent.click(locked);
    expect(locked.getAttribute('aria-checked')).toBe('true');
    expect(await violations(container)).toEqual([]);
  });

  it('never submits a disabled switch and keeps a caller aria-labelledby', () => {
    const { container } = render(
      <form>
        <span id="ext-label">External name</span>
        <Switch label="Visible" name="off" defaultChecked disabled aria-labelledby="ext-label" />
      </form>,
    );
    expect(container.querySelector('input[name="off"]')).toBeNull();
    expect(screen.getByRole('switch', { name: 'External name' })).toBeTruthy();
  });
});

describe('Modal hideHead, sizes and pass-through', () => {
  it('hides the head but keeps the name from a string title, and passes data attributes', async () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="Preview" hideHead size="full" data-testid="preview-modal" id="pm" cancelLabel={null}>
        <p>Body</p>
      </Modal>,
    );
    const dialog = screen.getByRole('dialog', { name: 'Preview' });
    expect(dialog.getAttribute('aria-label')).toBe('Preview');
    expect(dialog.getAttribute('aria-labelledby')).toBeNull();
    expect(dialog.getAttribute('data-testid')).toBe('preview-modal');
    expect(dialog.id).toBe('pm');
    expect(dialog.getAttribute('data-size')).toBe('full');
    expect(dialog.querySelector('.modal-head')).toBeNull();
    const close = screen.getByRole('button', { name: 'Close' });
    expect(close.className).toContain('modal-close-float');
    await userEvent.click(close);
    expect(onClose).toHaveBeenCalledWith('close');
    expect(await violations(document.body)).toEqual([]);
  });

  it('names the dialog from a JSX title with a hidden heading, and offers the wide size', () => {
    render(
      <Modal open onClose={() => undefined} title={<span>Job <b>42</b></span>} hideHead hideClose size="wide">
        <p>Body</p>
      </Modal>,
    );
    const dialog = screen.getByRole('dialog', { name: 'Job 42' });
    expect(dialog.getAttribute('data-size')).toBe('wide');
    expect(screen.queryByRole('button', { name: 'Close' })).toBeNull();
    expect(css).toContain('.modal[data-size="wide"]');
    expect(css).toContain('.modal[data-size="full"]');
  });

  it('keeps a caller aria-labelledby and merges aria-describedby', () => {
    render(
      <Modal open onClose={() => undefined} title="Ignored" subtitle="Sub" hideHead aria-labelledby="body-h" aria-describedby="body-d">
        <h3 id="body-h">From the body</h3>
        <p id="body-d">More detail</p>
      </Modal>,
    );
    const dialog = screen.getByRole('dialog', { name: 'From the body' });
    expect(dialog.getAttribute('aria-label')).toBeNull();
    expect(dialog.getAttribute('aria-describedby')?.split(' ')).toContain('body-d');
    expect(dialog.getAttribute('aria-describedby')?.split(' ').length).toBe(2);
  });

  it('still submits on Cmd or Ctrl and Enter after a child prevented the key', () => {
    const onSubmit = vi.fn();
    render(
      <Modal open onClose={() => undefined} title="Form" onSubmit={onSubmit} primaryAction={{ label: 'Save' }}>
        <input aria-label="Editor" onKeyDown={(e) => e.preventDefault()} />
      </Modal>,
    );
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Editor' }), { key: 'Enter', ctrlKey: true });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('calls a passed onKeyDown before its own keys', () => {
    const onKeyDown = vi.fn();
    render(
      <Modal open onClose={() => undefined} title="Keys" onKeyDown={onKeyDown}>
        <p>Body</p>
      </Modal>,
    );
    fireEvent.keyDown(screen.getByRole('dialog', { name: 'Keys' }), { key: 'a' });
    expect(onKeyDown).toHaveBeenCalledTimes(1);
  });
});

describe('Segmented icons and Select labelledBy', () => {
  it('renders an icon per option, and an icon-only option keeps its label as the name', async () => {
    const { container } = render(
      <Segmented
        label="View"
        value="list"
        onChange={() => undefined}
        options={[
          { value: 'list', label: 'List', icon: <svg data-testid="i-list" /> },
          { value: 'grid', label: 'Grid', icon: <svg data-testid="i-grid" />, iconOnly: true },
          { value: 'map', label: 'Map' },
        ]}
      />,
    );
    const list = screen.getByRole('button', { name: 'List' });
    expect(list.querySelector('.seg-icon')?.getAttribute('aria-hidden')).toBe('true');
    const grid = screen.getByRole('button', { name: 'Grid' });
    expect(grid.textContent).toBe('');
    expect(grid.getAttribute('data-tip')).toBe('Grid');
    expect(screen.getByRole('button', { name: 'Map' }).querySelector('.seg-icon')).toBeNull();
    expect(await violations(container)).toEqual([]);
  });

  it('labels a select by another element', () => {
    render(
      <div>
        <h3 id="owner-h">Owner</h3>
        <Select labelledBy="owner-h" options={[{ value: 'a', label: 'Anyone' }]} />
      </div>,
    );
    expect(screen.getByRole('combobox', { name: 'Owner' })).toBeTruthy();
  });
});

describe('Stat and StatRow', () => {
  it('renders a light card stat with an icon tile, a toned value and a labelled row', async () => {
    const onClick = vi.fn();
    const { container } = render(
      <StatRow label="Fleet summary">
        <Stat label="Devices" value={1234} hint="All sites" icon={<svg />} hue="teal" />
        <Stat label="Offline" value="12" tone="danger" onClick={onClick} selected={false} />
        <Stat label="Toner" value="8%" hue="ink" icon={<svg />} />
      </StatRow>,
    );
    const row = screen.getByRole('group', { name: 'Fleet summary' });
    expect(row.className).toBe('stat-row');
    expect(screen.getByText('1,234').className).toBe('stat-value');
    expect(container.querySelector('.stat-icon.hue-teal')).toBeTruthy();
    expect(container.querySelector('.stat-icon.hue-ink')).toBeTruthy();
    const offline = screen.getByRole('button', { name: /Offline/ });
    expect(offline.getAttribute('aria-pressed')).toBe('false');
    expect(offline.querySelector('.stat-value')?.getAttribute('data-tone')).toBe('danger');
    offline.focus();
    await userEvent.keyboard('{Enter}');
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(container.querySelector('.kpi-tile')).toBeNull();
    expect(await violations(container)).toEqual([]);
  });
});

describe('theme default other than system', () => {
  afterEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  function Picker() {
    const { choice, setChoice } = useTheme();
    return (
      <div>
        <span data-testid="choice">{choice}</span>
        <button type="button" onClick={() => setChoice('system')}>
          System
        </button>
      </div>
    );
  }

  it('applies the app default when nothing is stored, and keeps a stored System pick', async () => {
    const first = render(
      <ThemeProvider defaultChoice="dark">
        <Picker />
      </ThemeProvider>,
    );
    expect(screen.getByTestId('choice').textContent).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    await userEvent.click(screen.getByRole('button', { name: 'System' }));
    expect(window.localStorage.getItem(STORAGE_KEYS.theme)).toBe('system');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    first.unmount();
    render(
      <ThemeProvider defaultChoice="dark">
        <Picker />
      </ThemeProvider>,
    );
    expect(screen.getByTestId('choice').textContent).toBe('system');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('gives the init script the same default and lets a stored system follow the OS', () => {
    // The script is the kit's own output for constant test inputs, run the way a browser would.
    const run = (script: string) => new Function(script)() as void;
    run(themeInitScript(STORAGE_KEYS.theme, 'dark'));
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    document.documentElement.removeAttribute('data-theme');
    window.localStorage.setItem(STORAGE_KEYS.theme, 'system');
    run(themeInitScript(STORAGE_KEYS.theme, 'dark'));
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    window.localStorage.setItem(STORAGE_KEYS.theme, 'light');
    run(themeInitScript(STORAGE_KEYS.theme, 'dark'));
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    document.documentElement.removeAttribute('data-theme');
    window.localStorage.clear();
    run(themeInitScript());
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });
});

describe('Rail status line', () => {
  function shell(rail: ReactElement) {
    return render(
      <AppShell pathname="/" rail={rail} header={<Header title="Home" />}>
        <p>Content</p>
      </AppShell>,
    );
  }
  const nav = (
    <NavGroup label="Main">
      <NavItem href="/" label="Home" icon={<span>H</span>} active />
    </NavGroup>
  );

  it('composes environment, version and app text once', () => {
    const { container } = shell(
      <Rail brandMark="K" brandName="Test app" version="2.4.1" environment="Production" statusText="Example Org">
        {nav}
      </Rail>,
    );
    const line = container.querySelector('.rail-status-line');
    expect(line?.querySelector('.badge')?.textContent).toBe('Production');
    expect(line?.querySelector('.rail-status-text')?.textContent).toBe('v2.4.1 . Example Org');
    expect(container.querySelector('.rail-ver')?.textContent).toBe('v2');
    expect((container.querySelector('.rail-status')?.textContent?.match(/2\.4\.1/g) ?? []).length).toBe(1);
  });

  it('adds nothing to an app status, and can leave the version out', () => {
    const own = shell(
      <Rail brandMark="K" brandName="Test app" version="v3.0.0" status="v3.0.0 . Own text" environment="Ignored">
        {nav}
      </Rail>,
    );
    expect(own.container.querySelector('.rail-status')?.textContent).toBe('v3.0.0 . Own text');
    expect(own.container.querySelector('.rail-status-line')).toBeNull();
    own.unmount();
    const noVer = shell(
      <Rail brandMark="K" brandName="Test app" version="3.0.0" statusText="Example Org" showVersion={false}>
        {nav}
      </Rail>,
    );
    expect(noVer.container.querySelector('.rail-status-text')?.textContent).toBe('Example Org');
  });
});

describe('Toaster dedupes by id, not by text', () => {
  function Capture({ onApi }: { onApi: (api: ToastApi) => void }) {
    const api = useToast();
    onApi(api);
    return null;
  }

  it('shows the same text twice and JSX messages, and replaces a toast that reuses an id', () => {
    let api: ToastApi | null = null;
    render(
      <Toaster>
        <Capture
          onApi={(a) => {
            api = a;
          }}
        />
      </Toaster>,
    );
    const t = () => api as unknown as ToastApi;
    act(() => {
      t().toast('success', 'Saved');
      t().toast('success', 'Saved');
      t().toast('info', <span>Job <b>7</b> queued</span>);
    });
    expect(screen.getAllByText('Saved')).toHaveLength(2);
    expect(screen.getByText('7')).toBeTruthy();
    let id = '';
    act(() => {
      id = t().toast('info', 'Uploading 1 of 3', { id: 'upload', persistent: true });
    });
    expect(id).toBe('upload');
    act(() => {
      t().toast('success', 'Uploaded 3 of 3', { id: 'upload', persistent: true });
    });
    expect(screen.queryByText('Uploading 1 of 3')).toBeNull();
    expect(screen.getAllByText('Uploaded 3 of 3')).toHaveLength(1);
    expect(document.querySelectorAll('.toast')).toHaveLength(4);
  });

  it('never lets a generated id replace a caller toast that uses the same text id', () => {
    let api: ToastApi | null = null;
    render(
      <Toaster>
        <Capture
          onApi={(a) => {
            api = a;
          }}
        />
      </Toaster>,
    );
    const t = () => api as unknown as ToastApi;
    let next = '';
    act(() => {
      next = t().toast('info', 'Probe');
    });
    const n = Number(next.replace('toast-', ''));
    act(() => {
      t().toast('info', 'Caller owned', { id: `toast-${n + 2}`, persistent: true });
      t().toast('info', 'Auto after');
    });
    expect(screen.getByText('Caller owned')).toBeTruthy();
    expect(screen.getByText('Auto after')).toBeTruthy();
  });

  it('restarts the timer when a toast is updated in place', () => {
    vi.useFakeTimers();
    try {
      let api: ToastApi | null = null;
      render(
        <Toaster>
          <Capture
            onApi={(a) => {
              api = a;
            }}
          />
        </Toaster>,
      );
      const t = () => api as unknown as ToastApi;
      act(() => {
        t().toast('info', 'First', { id: 'sync', duration: 1000 });
      });
      act(() => {
        vi.advanceTimersByTime(800);
      });
      act(() => {
        t().toast('info', 'Second', { id: 'sync', duration: 1000 });
      });
      act(() => {
        vi.advanceTimersByTime(800);
      });
      expect(screen.getByText('Second')).toBeTruthy();
      act(() => {
        vi.advanceTimersByTime(300);
      });
      expect(screen.queryByText('Second')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
