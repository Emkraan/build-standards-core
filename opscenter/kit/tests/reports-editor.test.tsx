/* Definitions are data (R2): validation, import and export, the client and the editor. */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import axe from 'axe-core';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DashboardEditor, blankDefinition, createDashboardsClient, exportDefinitions, importProblemText, newPanel, parseDefinitions, slugFor, validateDefinition } from '../src/reports';
import type { DashboardDefinition, DashboardRun } from '../src/reports';
import { installMatchMedia, resetMedia } from './helpers';

beforeEach(() => {
  resetMedia();
  installMatchMedia();
});

const good: DashboardDefinition = { key: 'ops', title: 'Operations', panels: [{ title: 'Total', type: 'stat', stream: 's', measure: 'rows' }] };

describe('validateDefinition', () => {
  it('accepts a good definition and keeps extra fields out of the way', () => {
    expect(validateDefinition(good)).toEqual([]);
    expect(validateDefinition({ ...good, extra: { anything: true } })).toEqual([]);
  });

  it('names each problem the way the server does', () => {
    expect(validateDefinition(null)).toEqual(['a definition must be a JSON object']);
    expect(validateDefinition([])).toEqual(['a definition must be a JSON object']);
    expect(validateDefinition({ key: 'Bad Key', title: ' ', panels: 'x' })).toEqual([
      'key must be a lowercase slug (letters, digits, dash, underscore)',
      'title must be a non-empty string',
      'panels must be a list',
    ]);
    expect(validateDefinition({ ...good, panels: [1, { title: 'a', stream: '', measure: 'm', type: 'pie' }] })).toEqual([
      'panel 1 must be an object',
      'panel 2: stream must be a non-empty string',
      'panel 2: type must be one of stat, line, area, bar, hbar, donut, table',
    ]);
    expect(validateDefinition({ ...good, panels: [{ title: 'a', stream: 's' }] })).toEqual(['panel 1: a measure (a name) or a spec (the report query) is required']);
    expect(validateDefinition({ ...good, panels: [{ title: 'a', stream: 's', type: 'table', spec: { groupBy: ['x'], metrics: ['rows'] } }] })).toEqual([]);
    expect(validateDefinition({ ...good, panels: Array.from({ length: 51 }, () => good.panels[0]) })).toContain('at most 50 panels');
  });
});

describe('parseDefinitions and exportDefinitions', () => {
  it('round trips an export, reads one definition or a wrapped list', () => {
    const text = exportDefinitions([good, { ...good, key: 'two' }]);
    expect(parseDefinitions(text)).toEqual({ definitions: [good, { ...good, key: 'two' }], problems: [] });
    expect(parseDefinitions(JSON.stringify(good)).definitions).toEqual([good]);
    expect(parseDefinitions(JSON.stringify({ dashboards: [good] })).definitions).toEqual([good]);
  });

  it('refuses a file with any problem, whole, and says which definition', () => {
    const out = parseDefinitions(JSON.stringify([good, { key: 'two', title: '', panels: [] }, good]));
    expect(out.definitions).toEqual([]);
    expect(out.problems).toEqual(['two: title must be a non-empty string', 'ops: key is used twice']);
    expect(parseDefinitions('{nope').problems[0]).toMatch(/^not valid JSON/);
  });
});

describe('definition helpers', () => {
  it('makes starting panels and slugs', () => {
    expect(newPanel('stat', 's', 'rows', 1)).toMatchObject({ id: 'panel-1', type: 'stat', w: 3, stream: 's', measure: 'rows' });
    expect(newPanel('table', 's', 'rows', 2).h).toBe(4);
    expect(newPanel('line', 's', 'rows', 3).w).toBe(8);
    expect(blankDefinition().panels).toEqual([]);
    expect(slugFor('Q4 Report / Final!')).toBe('q4-report-final');
    expect(slugFor('!!!')).toBe('dashboard');
    expect(validateDefinition({ ...blankDefinition(slugFor('My board'), 'My board') })).toEqual([]);
  });
});

describe('createDashboardsClient', () => {
  const reply = (body: unknown, ok = true, status = 200) => vi.fn().mockResolvedValue({ ok, status, json: () => Promise.resolve(body) });

  it('calls the module routes with the envelope and the same-origin credentials', async () => {
    const f = reply({ success: true, data: [{ key: 'ops' }] });
    const api = createDashboardsClient({ base: '/api/reports/dashboards/', fetch: f as unknown as typeof fetch });
    expect(await api.list()).toEqual([{ key: 'ops' }]);
    expect(f).toHaveBeenCalledWith('/api/reports/dashboards', expect.objectContaining({ method: 'GET', credentials: 'same-origin' }));
    await api.save('a b', good);
    expect(f).toHaveBeenLastCalledWith('/api/reports/dashboards/a%20b', expect.objectContaining({ method: 'POST', body: JSON.stringify({ def: good }) }));
    await api.create(good);
    expect(f).toHaveBeenLastCalledWith('/api/reports/dashboards', expect.objectContaining({ method: 'POST', body: JSON.stringify({ def: good }) }));
    await api.reset('ops');
    await api.remove('ops');
    await api.importAll([good]);
    await api.run({ key: 'ops', range: '30', selections: { dept: 'IT' } });
    // The server registry has only GET and POST: nothing is a PUT or a DELETE.
    expect(f.mock.calls.map((c) => `${(c[1] as RequestInit).method} ${c[0]}`)).toEqual([
      'GET /api/reports/dashboards',
      'POST /api/reports/dashboards/a%20b',
      'POST /api/reports/dashboards',
      'POST /api/reports/dashboards/ops/reset',
      'POST /api/reports/dashboards/ops/delete',
      'POST /api/reports/dashboards/import',
      'POST /api/reports/dashboards/run',
    ]);
    expect(f).toHaveBeenCalledWith('/api/reports/dashboards/import', expect.objectContaining({ body: JSON.stringify({ dashboards: [good] }) }));
  });

  it('reads an export as a list or as { dashboards }, and an import problem as text', async () => {
    const list = createDashboardsClient({ base: '/x', fetch: reply({ success: true, data: [good] }) as unknown as typeof fetch });
    expect(await list.exportAll()).toEqual([good]);
    expect(importProblemText({ index: 1, key: 'two', message: 'title must be a non-empty string' })).toBe('two: title must be a non-empty string');
    expect(importProblemText({ index: 2, message: 'bad' })).toBe('#3: bad');
    expect(importProblemText({ message: 'bad' })).toBe('definition: bad');
    expect(importProblemText('plain')).toBe('plain');
  });

  it('unwraps the export envelope into a list of definitions', async () => {
    const f = reply({ success: true, data: { dashboards: [good] } });
    const api = createDashboardsClient({ base: '/api/dashboards', fetch: f as unknown as typeof fetch });
    expect(await api.exportAll()).toEqual([good]);
    expect(f).toHaveBeenCalledWith('/api/dashboards/export', expect.objectContaining({ method: 'GET' }));
  });

  it('turns a failure into an Error with the server message, or a plain one', async () => {
    const api = createDashboardsClient({ base: '/x', fetch: reply({ success: false, message: 'not yours' }, false, 403) as unknown as typeof fetch });
    await expect(api.list()).rejects.toThrow('not yours');
    const api2 = createDashboardsClient({ base: '/x', fetch: vi.fn().mockResolvedValue({ ok: false, status: 500, json: () => Promise.reject(new Error('x')) }) as unknown as typeof fetch });
    await expect(api2.list()).rejects.toThrow('Request failed (500)');
  });
});

describe('DashboardEditor', () => {
  const run: DashboardRun = { generatedAt: '2026-11-07T10:00:00Z', range: '30', options: {}, panels: { '0': { columns: [], rows: [], stat: { value: 5 } } } };
  const setup = (props: Partial<Parameters<typeof DashboardEditor>[0]> = {}) => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    const view = render(<DashboardEditor definition={good} streams={['events']} onSave={onSave} onClose={onClose} {...props} />);
    return { onSave, onClose, ...view };
  };
  const json = () => screen.getByLabelText('Definition (JSON)') as HTMLTextAreaElement;

  it('edits the name through the definition and saves what the JSON says', async () => {
    const { onSave } = setup();
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Ops board' } });
    expect(JSON.parse(json().value).title).toBe('Ops board');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ key: 'ops', title: 'Ops board' })));
  });

  it('names the problems and will not save or preview while there are any', () => {
    const { onSave } = setup({ onPreview: vi.fn() });
    fireEvent.change(json(), { target: { value: '{"key":"Bad","title":"","panels":[]}' } });
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain('key must be a lowercase slug');
    expect(alert.textContent).toContain('title must be a non-empty string');
    expect((screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Preview' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(onSave).not.toHaveBeenCalled();
    fireEvent.change(json(), { target: { value: '{oops' } });
    expect(screen.getByRole('alert').textContent).toMatch(/not valid JSON/);
  });

  it('adds a panel of the chosen type on the first stream, and says when there is no stream', () => {
    const { unmount } = setup();
    fireEvent.change(screen.getByLabelText('Panel type'), { target: { value: 'donut' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add panel' }));
    const added = JSON.parse(json().value).panels[1];
    expect(added).toMatchObject({ type: 'donut', stream: 'events', measure: 'rows' });
    unmount();
    setup({ streams: [] });
    fireEvent.click(screen.getByRole('button', { name: 'Add panel' }));
    expect(screen.getByRole('alert').textContent).toBe('There are no streams to read from yet');
  });

  it('shows the server message when a save fails and keeps the editor', async () => {
    setup({ onSave: vi.fn().mockRejectedValue(new Error('key already exists')) });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('key already exists'));
  });

  it('previews the definition with the run the app returns', async () => {
    const onPreview = vi.fn().mockResolvedValue(run);
    setup({ onPreview });
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(screen.getByText('5')).toBeTruthy());
    expect(onPreview).toHaveBeenCalledWith(expect.objectContaining({ key: 'ops' }));
  });

  it('offers reset only for an edited shipped dashboard, and delete only after a confirm', async () => {
    const onReset = vi.fn().mockResolvedValue(undefined);
    const onDelete = vi.fn().mockResolvedValue(undefined);
    const { unmount } = setup({ existing: false, onReset, onDelete });
    expect(screen.queryByRole('button', { name: 'Reset to shipped' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull();
    unmount();
    setup({ existing: true, modified: true, onReset, onDelete });
    fireEvent.click(screen.getByRole('button', { name: 'Reset to shipped' }));
    await waitFor(() => expect(onReset).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(onDelete).not.toHaveBeenCalled();
    const dialogButtons = screen.getAllByRole('button', { name: 'Delete' });
    fireEvent.click(dialogButtons[dialogButtons.length - 1] as HTMLElement);
    await waitFor(() => expect(onDelete).toHaveBeenCalled());
  });

  it('has no axe violations, with and without problems', async () => {
    const { container } = setup({ onPreview: vi.fn() });
    let r = await axe.run(container, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
    expect(r.violations.map((v) => v.id)).toEqual([]);
    fireEvent.change(json(), { target: { value: '{"key":"x"}' } });
    r = await axe.run(container, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } });
    expect(r.violations.map((v) => v.id)).toEqual([]);
  });
});
