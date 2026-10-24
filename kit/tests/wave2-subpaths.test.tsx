/* Wave 2 subpath entries: charts (recharts), graph (React Flow) and api-reference (Scalar). Each is
   its own entry with an optional peer dependency; none of them is reachable from the kit root.
   Scalar is a whole Vue application that jsdom cannot host, so its React wrapper is replaced by a
   probe that records the configuration the kit hands it. */
import { act, render, screen, waitFor, within } from '@testing-library/react';
import axe from 'axe-core';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it, vi } from 'vitest';

const scalar = vi.hoisted(() => ({ configs: [] as Record<string, unknown>[] }));

vi.mock('@scalar/api-reference-react', () => ({
  ApiReferenceReact: ({ configuration }: { configuration: Record<string, unknown> }) => {
    scalar.configs.push(configuration);
    return (
      <div data-testid="scalar">
        <h1>Inventory API</h1>
      </div>
    );
  },
}));

import { ApiReference, demoteHeadings, nestMainLandmarks, scalarConfiguration } from '../src/api-reference';
import { AreaChart, BarChart, ChartTooltip, DonutChart, LineChart, Sparkline } from '../src/charts';
import { Graph, GraphNodeCard, graphEdge } from '../src/graph';
import { useColorScheme } from '../src/lib/media';

async function noAxe(el: Element) {
  const r = await axe.run(el, { rules: { region: { enabled: false } } });
  expect(r.violations.map((v) => v.id)).toEqual([]);
}

const traffic = [
  { day: 'Mon', reads: 120, writes: 40 },
  { day: 'Tue', reads: 180, writes: 55 },
  { day: 'Wed', reads: 150, writes: 70 },
];

const series = [
  { key: 'reads' as const, label: 'Reads' },
  { key: 'writes' as const, label: 'Writes' },
];

describe('charts entry', () => {
  it('names each chart and carries the numbers in a hidden table', async () => {
    const { container } = render(
      <LineChart data={traffic} x="day" series={series} label="Requests per day" formatValue={(v) => `${v} req`} />,
    );
    const figure = screen.getByRole('figure', { name: 'Requests per day' });
    const table = within(figure).getByRole('table', { name: 'Requests per day' });
    expect(within(table).getAllByRole('row').length).toBe(traffic.length + 1);
    expect(table.textContent).toContain('180 req');
    expect(figure.querySelector('.chart-plot')?.getAttribute('aria-hidden')).toBe('true');
    expect(figure.textContent).toContain('Writes');
    await noAxe(container);
  });

  it('area, stacked bar, sparkline and donut all render a named figure', () => {
    render(
      <>
        <AreaChart data={traffic} x="day" series={series} label="Area" />
        <BarChart data={traffic} x="day" series={series} label="Stacked" stacked />
        <BarChart data={traffic} x="day" series={series.slice(0, 1)} label="Ranked" layout="vertical" />
        <Sparkline data={[3, 5, 4, 8]} label="Trend" />
        <DonutChart
          data={[
            { label: 'Healthy', value: 7 },
            { label: 'Degraded', value: 2 },
          ]}
          label="Fleet health"
          center="9"
          centerLabel="hosts"
        />
      </>,
    );
    for (const name of ['Area', 'Stacked', 'Ranked', 'Trend', 'Fleet health']) {
      expect(screen.getByRole('figure', { name })).toBeTruthy();
    }
    expect(within(screen.getByRole('figure', { name: 'Trend' })).getAllByRole('row').length).toBe(5);
    expect(screen.getByRole('figure', { name: 'Fleet health' }).textContent).toContain('Degraded');
  });
});

describe('chart parts', () => {
  it('ChartTooltip lists each row with its swatch, and renders nothing without rows', () => {
    const { container, rerender } = render(
      <ChartTooltip
        title="Tue"
        rows={[
          { name: 'Reads', value: '180 req', color: 'rgb(1 2 3)' },
          { name: 'Writes', value: '55 req', color: 'rgb(4 5 6)' },
        ]}
      />,
    );
    expect(container.querySelector('.chart-tip-title')?.textContent).toBe('Tue');
    const rows = container.querySelectorAll('.chart-tip-row');
    expect(rows.length).toBe(2);
    expect(rows[0]?.textContent).toContain('Reads');
    expect(rows[0]?.textContent).toContain('180 req');
    expect(rows[0]?.querySelector('.chart-swatch')?.getAttribute('aria-hidden')).toBe('true');
    rerender(<ChartTooltip title="Tue" rows={[]} />);
    expect(container.querySelector('.chart-tip')).toBeNull();
  });

  it('the donut legend pushes each value to the row end so labels share one edge', () => {
    const css = readFileSync(join(__dirname, '../src/styles/kit.css'), 'utf8');
    expect(css).not.toMatch(/\.chart-donut \.chart-legend-item \{[^}]*space-between/);
    expect(css).toMatch(/\.chart-donut \.chart-legend-value \{[^}]*margin-inline-start: auto/);
  });
});

describe('useColorScheme', () => {
  function Probe() {
    return <span data-testid="scheme">{useColorScheme()}</span>;
  }

  it('follows the data-theme attribute without a ThemeProvider', async () => {
    const root = document.documentElement;
    const before = root.getAttribute('data-theme');
    root.setAttribute('data-theme', 'light');
    try {
      render(<Probe />);
      expect(screen.getByTestId('scheme').textContent).toBe('light');
      await act(async () => {
        root.setAttribute('data-theme', 'dark');
      });
      await waitFor(() => expect(screen.getByTestId('scheme').textContent).toBe('dark'));
    } finally {
      if (before === null) root.removeAttribute('data-theme');
      else root.setAttribute('data-theme', before);
    }
  });
});

describe('graph entry', () => {
  it('graphEdge builds a kit-styled edge', () => {
    const edge = graphEdge({ id: 'e1', source: 'a', target: 'b', hue: 'teal', twoWay: true, dashed: true, label: 'sync' });
    expect(edge.markerEnd).toBeTruthy();
    expect(edge.markerStart).toEqual(edge.markerEnd);
    expect((edge.style as Record<string, string>)['--xy-edge-stroke']).toBe('rgb(var(--hue-teal))');
    expect(edge.style?.strokeDasharray).toBe('5 4');
    expect(edge.label).toBe('sync');
    const plain = graphEdge({ id: 'e2', source: 'a', target: 'b' });
    expect(plain.markerStart).toBeUndefined();
    expect((plain.style as Record<string, string>)['--xy-edge-stroke']).toBe('var(--border-strong)');
  });

  it('GraphNodeCard renders on its own without handles', () => {
    const { container } = render(
      <GraphNodeCard label="Gateway" kind="Service" detail="2 replicas" meta={['a', 'b', 'c', 'd', 'e']} hue="violet" handles={false} />,
    );
    expect(container.querySelector('.flow-node')?.getAttribute('data-hue')).toBe('violet');
    expect(container.querySelectorAll('.flow-node-meta li').length).toBe(4);
    expect(container.textContent).toContain('Gateway');
  });

  it('Graph is a named group whose colour mode follows the theme', async () => {
    document.documentElement.setAttribute('data-theme', 'light');
    render(
      <Graph
        label="Service map"
        readOnly
        defaultNodes={[{ id: 'a', type: 'card', position: { x: 0, y: 0 }, data: { label: 'Gateway' } }]}
        defaultEdges={[]}
      />,
    );
    const group = screen.getByRole('group', { name: 'Service map' });
    await waitFor(() => expect(group.querySelector('.react-flow')).toBeTruthy());
    expect(group.querySelector('.react-flow')?.classList.contains('light')).toBe(true);
    act(() => document.documentElement.setAttribute('data-theme', 'dark'));
    await waitFor(() => expect(group.querySelector('.react-flow')?.classList.contains('dark')).toBe(true));
  });
});

describe('api-reference entry', () => {
  it('configures Scalar with no third-party calls and the kit theme', () => {
    const cfg = scalarConfiguration({ openapi: '3.1.0' }, { title: 'Inventory API', servers: [{ url: 'https://api.test' }] }, 'light');
    expect(cfg).toMatchObject({
      theme: 'none',
      forceDarkModeState: 'light',
      darkMode: false,
      hideDarkModeToggle: true,
      withDefaultFonts: false,
      telemetry: false,
      showDeveloperTools: 'never',
      agent: { disabled: true },
      mcp: { disabled: true },
      content: { openapi: '3.1.0' },
      metaData: { title: 'Inventory API', ogTitle: 'Inventory API' },
      servers: [{ url: 'https://api.test' }],
    });
    expect(cfg).not.toHaveProperty('url');
    expect(scalarConfiguration(undefined, { url: '/openapi.json' }, 'dark')).toMatchObject({ url: '/openapi.json', darkMode: true });
  });

  it('fetches the spec through the app client, then mounts with it', async () => {
    scalar.configs.length = 0;
    const spec = { openapi: '3.1.0', info: { title: 'Inventory API', version: '1' } };
    let resolve!: (v: unknown) => void;
    const fetchSpec = vi.fn(() => new Promise<unknown>((r) => (resolve = r)));
    render(<ApiReference fetchSpec={fetchSpec} />);
    const loading = screen.getByRole('status', { name: 'Loading the API reference' });
    expect(loading.getAttribute('aria-busy')).toBe('true');
    await act(async () => resolve(spec));
    await screen.findByTestId('scalar');
    expect(fetchSpec).toHaveBeenCalledTimes(1);
    expect(scalar.configs.at(-1)?.['content']).toBe(spec);
  });

  it('shows ErrorState with Retry when the fetch fails', async () => {
    let calls = 0;
    const fetchSpec = vi.fn(() => {
      calls += 1;
      return calls === 1 ? Promise.reject(new Error('401 Unauthorized')) : Promise.resolve({ openapi: '3.1.0' });
    });
    const { container } = render(<ApiReference fetchSpec={fetchSpec} />);
    expect(await screen.findByText('401 Unauthorized')).toBeTruthy();
    await noAxe(container);
    await act(async () => screen.getByRole('button', { name: 'Retry' }).click());
    await screen.findByTestId('scalar');
    expect(fetchSpec).toHaveBeenCalledTimes(2);
  });

  it('shifts the Scalar heading outline under the page heading level', async () => {
    render(<ApiReference content={{ openapi: '3.1.0' }} />);
    await waitFor(() => expect(screen.getByRole('heading', { level: 2, name: 'Inventory API' })).toBeTruthy());
    const root = document.createElement('div');
    const [title, done, section, deep] = ['h1', 'h1', 'h2', 'h6'].map((t) => document.createElement(t));
    done?.setAttribute('aria-level', '3');
    root.append(...[title, done, section, deep].filter((h): h is HTMLElement => h !== undefined));
    expect(demoteHeadings(root, 3)).toBe(3);
    expect(title?.getAttribute('aria-level')).toBe('3');
    expect(section?.getAttribute('aria-level')).toBe('4');
    expect(deep?.getAttribute('aria-level')).toBe('6');
    expect(demoteHeadings(root, 3)).toBe(0);
  });

  it('turns a nested Scalar main into a named region, and only when nested', () => {
    const page = document.createElement('main');
    const frame = document.createElement('div');
    const inner = document.createElement('main');
    inner.setAttribute('aria-label', 'API documentation');
    frame.append(inner);
    page.append(frame);
    expect(nestMainLandmarks(frame)).toBe(1);
    expect(inner.getAttribute('role')).toBe('region');
    expect(nestMainLandmarks(frame)).toBe(0);
    const alone = document.createElement('div');
    const own = document.createElement('main');
    alone.append(own);
    document.body.append(alone);
    expect(nestMainLandmarks(alone)).toBe(0);
    expect(own.hasAttribute('role')).toBe(false);
    alone.remove();
  });

  it('follows the kit theme unless pinned', async () => {
    scalar.configs.length = 0;
    document.documentElement.setAttribute('data-theme', 'light');
    const { rerender } = render(<ApiReference content={{ openapi: '3.1.0' }} />);
    expect(scalar.configs.at(-1)?.['forceDarkModeState']).toBe('light');
    rerender(<ApiReference content={{ openapi: '3.1.0' }} colorScheme="dark" />);
    expect(scalar.configs.at(-1)?.['forceDarkModeState']).toBe('dark');
  });
});

describe('entry isolation', () => {
  it('the kit root never imports an optional peer', () => {
    const root = readFileSync(join(__dirname, '../src/index.ts'), 'utf8');
    expect(root).not.toMatch(/from '\.\/(graph|api-reference)/);
    expect(root).not.toMatch(/from '\.\/charts\/(Charts|index)'/);
    expect(root).not.toMatch(/recharts|@xyflow|@scalar/);
  });

  it('the consumer manifest exports each entry and marks its peer optional', () => {
    const pkg = JSON.parse(readFileSync(join(__dirname, '../consumer/package.json'), 'utf8')) as {
      exports: Record<string, string>;
      peerDependencies: Record<string, string>;
      peerDependenciesMeta: Record<string, { optional?: boolean }>;
    };
    expect(pkg.exports['./charts']).toBe('./charts/index.ts');
    expect(pkg.exports['./api-reference']).toBe('./api-reference/index.ts');
    expect(pkg.exports['./graph']).toBe('./graph/index.ts');
    for (const peer of ['recharts', '@xyflow/react', '@scalar/api-reference-react']) {
      expect(pkg.peerDependencies[peer]).toBeTruthy();
      expect(pkg.peerDependenciesMeta[peer]?.optional).toBe(true);
    }
  });
});
