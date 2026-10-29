/* shell-packages/console-modules: the manifest validator agrees with the JSON schema fixtures, and the
   registry checks a schema cannot make (declared groups, unique routes, permission source, peer ids) hold. */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  autoDescription, canOpen, ownsPermissions, peerModules, peerRef, permissionSourceId, validateManifest, validateRegistry,
} from '../../shell-packages/console-modules/index.js';

const FIX = resolve(__dirname, '../../tests/fixtures/console-module');
const load = (name: string) => JSON.parse(readFileSync(resolve(FIX, name), 'utf8'));
const all = () => ['console', 'alerts', 'fleet'].map((n) => load(`${n}.module.json`));

describe('validateManifest', () => {
  it('accepts every fixture and ignores unknown keys', () => {
    for (const m of all()) expect(validateManifest(m)).toEqual([]);
    const m = load('alerts.module.json');
    m['x-other'] = 1;
    m.api['x-api'] = true;
    expect(validateManifest(m)).toEqual([]);
  });

  const cases: Record<string, (m: any) => void> = {
    'bad id': (m) => { m.id = 'Alerts'; },
    'bad accent': (m) => { m.accent = 'pink'; },
    'bad icon': (m) => { m.icon = 'megaphone'; },
    'negative order': (m) => { m.order = -1; },
    'wrong client': (m) => { m.client = 'packages/x'; },
    'non ASCII name': (m) => { m.name = 'Caf' + String.fromCharCode(0xe9); },
    'angle bracket in description': (m) => { m.description = 'a <b> c'; },
    'empty requires': (m) => { m.pages[0].requires = []; },
    'bad hue': (m) => { m.pages[0].hue = 'pink'; },
    'bad permission id': (m) => { m.pages[0].requires = ['alerts']; },
    'undeclared group': (m) => { m.pages[0].group = 'nope'; },
    'duplicate route': (m) => { m.pages.push({ ...m.pages[0], key: 'second' }); },
    'duplicate item key': (m) => { m.links[0].key = m.pages[0].key; },
    'http link': (m) => { m.links[0].href = 'http://status.example.com/'; },
    'rail link without group': (m) => { m.links[0].slot = 'rail'; },
    'bad feed block': (m) => { m.home.feeds[0].block = 'side'; },
    'five home actions': (m) => { m.home.actions = Array.from({ length: 5 }, (_, i) => ({ ...m.home.actions[0], key: `a${i}` })); },
    'home action to an undeclared route': (m) => { m.home.actions[0].route = '/nowhere'; },
    'long action label': (m) => { m.home.actions[0].label = 'x'.repeat(41); },
    'double slash feed path': (m) => { m.home.feeds[0].path = '/a//b'; },
    'landing to an undeclared route': (m) => { m.landing = ['/nowhere']; },
    'peer id on a tile': (m) => { m.tiles = [{ key: 't', dashboard: 'home', label: 'T', permission: 'fleet/tab:x', order: 1 }]; },
    'permissionSource on another shape': (m) => { m.rbac.permissionSource = 'console'; },
    'missing groups': (m) => { delete m.groups; },
  };
  for (const [name, edit] of Object.entries(cases)) {
    it(`rejects: ${name}`, () => {
      const m = load('alerts.module.json');
      edit(m);
      expect(validateManifest(m).length).toBeGreaterThan(0);
    });
  }

  it('never throws on a non-object', () => {
    for (const v of [null, 1, 'x', [], undefined]) expect(validateManifest(v)).toEqual(['manifest must be an object']);
  });
});

describe('validateRegistry', () => {
  it('accepts the fixture set and needs the console module', () => {
    expect(validateRegistry(all())).toEqual([]);
    expect(validateRegistry(all().filter((m) => m.id !== 'console')).join('\n')).toMatch(/must contain the console module/);
  });

  it('rejects a duplicate id', () => {
    expect(validateRegistry([...all(), load('alerts.module.json')]).join('\n')).toMatch(/duplicate module id alerts/);
  });

  it('checks the permission source: it exists, owns its permissions and matches', () => {
    const fleet = load('fleet.module.json');
    expect(validateRegistry(all().filter((m) => m.id !== 'fleet').concat(fleet))).toEqual([]);
    expect(validateRegistry(all().filter((m) => m.id !== 'console')).join('\n')).toMatch(/permissionSource console is not a module/);
    const moved = all();
    moved[2].api.scopeEnv = 'OTHER';
    expect(validateRegistry(moved).join('\n')).toMatch(/api.scopeEnv must match console/);
    const chain = all();
    chain[0].rbac.permissionSource = 'alerts';
    expect(validateRegistry(chain).join('\n')).toMatch(/must own its permissions|cannot name/);
  });

  it('checks peer permissions: the module exists, owns its permissions and is not shape console', () => {
    expect(peerModules(load('fleet.module.json'))).toEqual(['alerts']);
    const missing = all().filter((m) => m.id !== 'alerts');
    expect(validateRegistry(missing).join('\n')).toMatch(/peer permission module alerts is not a module/);
    const toConsole = all();
    toConsole[2].pages[0].requires = ['console/tab:home'];
    expect(validateRegistry(toConsole).join('\n')).toMatch(/peer permission cannot name console/);
  });
});

describe('helpers', () => {
  it('splits a peer id and leaves an own id alone', () => {
    expect(peerRef('alerts/action:admin:mailbox')).toEqual({ module: 'alerts', permission: 'action:admin:mailbox' });
    expect(peerRef('tab:agent')).toBeNull();
  });

  it('routes permissions to the source and any-of opens', () => {
    const [c, , f] = all();
    expect(permissionSourceId(f)).toBe('console');
    expect(ownsPermissions(f)).toBe(false);
    expect(ownsPermissions(c)).toBe(true);
    expect(canOpen(['tab:a', 'tab:b'], (id) => id === 'tab:b')).toBe(true);
    expect(canOpen(['tab:a'], () => false)).toBe(false);
  });

  it('writes a launcher description that fits and is accepted by the validator', () => {
    const m = load('console.module.json');
    delete m.description;
    const text = autoDescription(m);
    expect(text).toMatch(/^Console: /);
    expect(text).toContain('Pages: Home and People.');
    expect(text.length).toBeLessThanOrEqual(400);
    m.pages = Array.from({ length: 80 }, (_, i) => ({ ...m.pages[0], key: `p${i}`, route: `/p${i}`, label: `Page number ${i}` }));
    const long = autoDescription(m);
    expect(long.length).toBeLessThanOrEqual(400);
    expect(long).toMatch(/and \d+ more\.$/);
  });
});
