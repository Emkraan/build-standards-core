/* shell-packages/rbac: the grant ceiling, accessible tabs and the client access helpers. */
import { describe, expect, it } from 'vitest';
import {
  accessibleTabs, activeGrantable, annotateRoles, assignableRoleIds, canAssignRole, canGrantPermission, createAccess,
  filterRegistry, findPermissionLiterals, grantableIds, permissionsBeyond, stripRetiredPermissions, toPermissionList, viewAsPreview,
} from '../../shell-packages/rbac/index.js';

const registry = {
  tabs: [{ id: 'tab:home' }, { id: 'tab:people' }, { id: 'tab:audit' }],
  actions: [
    { id: 'action:people:edit', tab: 'tab:people' },
    { id: 'action:people:delete', tab: 'tab:people' },
    { id: 'action:audit:export', tab: 'tab:audit' },
  ],
};
const caller = (perms: string[], wildcard = false) => ({ callerPermissions: perms, callerIsWildcard: wildcard, registry });

describe('permission lists', () => {
  it('reads arrays and JSON text, and treats unparseable text as the wildcard so a ceiling check fails closed', () => {
    expect(toPermissionList(['tab:home'])).toEqual(['tab:home']);
    expect(toPermissionList('["tab:home"]')).toEqual(['tab:home']);
    expect(toPermissionList('not json')).toEqual(['*']);
    expect(toPermissionList(null)).toEqual([]);
  });
});

describe('accessibleTabs', () => {
  it('opens a tab for its own id or any of its actions, and the wildcard opens every tab', () => {
    expect(accessibleTabs(['action:people:edit'], registry)).toEqual(['tab:people']);
    expect(accessibleTabs(['tab:home'], registry)).toEqual(['tab:home']);
    expect(accessibleTabs(['*'], registry)).toEqual(['tab:home', 'tab:people', 'tab:audit']);
    expect(accessibleTabs([], registry)).toEqual([]);
  });
});

describe('the grant ceiling', () => {
  it('lets a caller confer only what they hold', () => {
    const c = caller(['tab:people', 'action:people:edit']);
    expect(permissionsBeyond({ requested: ['action:people:edit'], ...c })).toEqual([]);
    expect(permissionsBeyond({ requested: ['action:people:edit', 'tab:audit'], ...c })).toEqual(['tab:audit']);
  });

  it('confers the wildcard only from a genuine wildcard holder', () => {
    expect(permissionsBeyond({ requested: ['*'], ...caller(['tab:people']) })).toEqual(['*']);
    expect(permissionsBeyond({ requested: ['*'], ...caller([], true) })).toEqual([]);
  });

  it('keeps a stale id outside a delegate ceiling instead of dropping it', () => {
    expect(permissionsBeyond({ requested: ['tab:gone'], ...caller(['tab:people']) })).toEqual(['tab:gone']);
  });

  it('annotates roles with assignable and unknown permissions', () => {
    const roles = [
      { id: 1, permissions: ['tab:people'] },
      { id: 2, permissions: ['tab:audit', 'tab:gone'] },
    ];
    const out = annotateRoles(roles, caller(['tab:people']));
    expect(out.map((r) => r.assignable)).toEqual([true, false]);
    expect(out[1]?.unknownPermissions).toEqual(['tab:gone']);
    expect(assignableRoleIds(roles, caller(['tab:people']))).toEqual(['1']);
  });

  it('lists the ids a caller may grant', () => {
    expect(grantableIds(caller(['tab:home']))).toEqual(['tab:home']);
    expect(grantableIds(caller([], true))).toHaveLength(6);
  });
});

describe('view as', () => {
  it('refuses a subject beyond the caller and previews one inside it', () => {
    const inside = viewAsPreview({ subjectPermissions: ['tab:people'], subjectIsWildcard: false, caller: caller(['tab:people', 'tab:home']), registry, roles: [] });
    expect(inside.beyond).toEqual([]);
    expect(inside.tabs).toEqual(['tab:people']);
    const outside = viewAsPreview({ subjectPermissions: [], subjectIsWildcard: true, caller: caller(['tab:people']), registry, roles: [] });
    expect(outside.beyond).toEqual(['*']);
  });
});

describe('registry hygiene', () => {
  it('finds permission literals in source and strips only retired ids', () => {
    expect(findPermissionLiterals(`has("tab:home"); can('action:people:edit'); "tab:x y"`).sort()).toEqual(['action:people:edit', 'tab:home']);
    expect(stripRetiredPermissions(['tab:home', 'tab:old'], ['tab:old', 'tab:home'], registry)).toEqual(['tab:home']);
    expect(stripRetiredPermissions(['tab:home'], ['tab:old'], registry)).toBeNull();
    expect(stripRetiredPermissions(['*'], ['tab:old'], registry)).toBeNull();
  });
});

describe('client helpers', () => {
  it('createAccess uses the server tabs, falls back to the prefix rule, and the wildcard opens all', () => {
    const withTabs = createAccess({ permissions: ['action:people:edit'], tabs: ['tab:people'] });
    expect(withTabs.hasTab('tab:people')).toBe(true);
    expect(withTabs.hasTab('tab:home')).toBe(false);
    expect(createAccess({ permissions: ['action:people:edit'] }).hasTab('tab:people')).toBe(true);
    expect(createAccess({ permissions: ['*'] }).hasPermission('anything')).toBe(true);
    expect(createAccess(null).hasPermission('tab:home')).toBe(false);
  });

  it('narrows pickers by the grantable list, the view-as subject first', () => {
    const narrowed = filterRegistry(registry, ['action:people:edit']);
    expect(narrowed.tabs.map((t) => t.id)).toEqual(['tab:people']);
    expect(narrowed.actions.map((a) => a.id)).toEqual(['action:people:edit']);
    expect(filterRegistry(registry, null).tabs).toHaveLength(3);
    expect(activeGrantable({ grantable: ['a'] }, { grantable: ['b'] })).toEqual(['b']);
    expect(activeGrantable({ grantable: ['a'] }, null)).toEqual(['a']);
    expect(canGrantPermission('tab:home', { grantable: ['tab:home'] }, null)).toBe(true);
    expect(canGrantPermission('tab:x', { grantable: ['tab:home'] }, null)).toBe(false);
    expect(canGrantPermission('tab:x', null, null)).toBe(true);
    expect(canAssignRole({ id: 1, assignable: false }, null)).toBe(false);
    expect(canAssignRole({ id: 1, assignable: false }, { assignableRoleIds: ['1'] })).toBe(true);
    expect(canAssignRole({ id: 1 }, null)).toBe(true);
  });
});
