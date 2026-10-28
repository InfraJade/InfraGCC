import type { User } from 'oidc-client-ts';

import { decodeJwtPayload } from '@/auth/jwt';
import { toAuthUser } from '@/auth/oidc';
import { hasRole, highestRank, primaryRole, rolesFromGroups, sitesFromGroups, type Role } from '@/auth/roles';
import { visibleNav } from '@/components/shell/nav';

function b64url(obj: unknown): string {
  const bin = String.fromCharCode(...new TextEncoder().encode(JSON.stringify(obj)));
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
const jwt = (claims: Record<string, unknown>) => `${b64url({ alg: 'RS256' })}.${b64url(claims)}.sig`;

describe('role mapping (D20)', () => {
  it('maps SSO groups to roles, tolerating full-path groups', () => {
    expect(rolesFromGroups(['gcc-viewer'])).toEqual(['viewer']);
    expect(rolesFromGroups(['/gcc-noc-operator', 'gcc-site-PNQ1'])).toEqual(['noc_operator']);
    expect(rolesFromGroups(['gcc-analyst', 'gcc-dc-engineer', 'other'])).toEqual(['dc_engineer', 'analyst']);
    expect(rolesFromGroups([])).toEqual([]);
  });

  it('reads site limits from gcc-site-<CODE> groups (none = all sites)', () => {
    expect(sitesFromGroups(['gcc-site-PNQ1', '/gcc-site-hyd1', 'gcc-viewer'])).toEqual(['HYD1', 'PNQ1']);
    expect(sitesFromGroups(['gcc-viewer'])).toEqual([]);
  });
});

describe('role hierarchy viewer < noc_operator < dc_engineer < platform_admin', () => {
  const cases: [Role[], Role, boolean][] = [
    [['viewer'], 'viewer', true],
    [['viewer'], 'noc_operator', false],
    [['noc_operator'], 'viewer', true],
    [['noc_operator'], 'dc_engineer', false],
    [['dc_engineer'], 'noc_operator', true],
    [['dc_engineer'], 'platform_admin', false],
    [['platform_admin'], 'dc_engineer', true],
    [['platform_admin'], 'viewer', true],
    // analyst = viewer in the app
    [['analyst'], 'viewer', true],
    [['analyst'], 'noc_operator', false],
    // analyst as a requirement is membership (or admin)
    [['analyst'], 'analyst', true],
    [['dc_engineer'], 'analyst', false],
    [['platform_admin'], 'analyst', true],
    // no roles at all
    [[], 'viewer', false],
  ];
  it.each(cases)('%j has %s → %s', (roles, required, expected) => {
    expect(hasRole(roles, required)).toBe(expected);
  });

  it('picks the highest rank and a display role', () => {
    expect(highestRank(['viewer', 'dc_engineer'])).toBe(2);
    expect(highestRank([])).toBe(-1);
    expect(primaryRole(['analyst'])).toBe('analyst');
    expect(primaryRole(['noc_operator', 'analyst'])).toBe('noc_operator');
    expect(primaryRole([])).toBeNull();
  });

  it('filters navigation by role', () => {
    const forViewer = visibleNav((r) => hasRole(['viewer'], r)).map((i) => i.to);
    const forEngineer = visibleNav((r) => hasRole(['dc_engineer'], r)).map((i) => i.to);
    const forAdmin = visibleNav((r) => hasRole(['platform_admin'], r)).map((i) => i.to);
    expect(forViewer).not.toContain('/admin');
    expect(forEngineer).toContain('/admin');
    expect(forEngineer).not.toContain('/audit');
    expect(forAdmin).toContain('/audit');
  });
});

describe('access token claims', () => {
  it('decodes base64url JWT payloads (incl. UTF-8) and rejects garbage', () => {
    expect(decodeJwtPayload(jwt({ name: 'Aïsha', groups: ['gcc-viewer'] }))).toEqual({
      name: 'Aïsha',
      groups: ['gcc-viewer'],
    });
    expect(decodeJwtPayload('nope')).toBeNull();
    expect(decodeJwtPayload('a.###.c')).toBeNull();
  });

  it('builds the app user from the ACCESS token groups', () => {
    const user = {
      access_token: jwt({ sub: 'u1', groups: ['gcc-noc-operator', 'gcc-site-PNQ1'] }),
      expires_at: 1_900_000_000,
      expired: false,
      profile: { sub: 'u1', preferred_username: 'noc-pune', name: 'NOC Pune', email: 'noc-pune@gcc.example' },
    } as unknown as User;
    const au = toAuthUser(user);
    expect(au.roles).toEqual(['noc_operator']);
    expect(au.sites).toEqual(['PNQ1']);
    expect(au.username).toBe('noc-pune');
    expect(au.name).toBe('NOC Pune');
    expect(au.accessToken).toBe(user.access_token);
  });
});
