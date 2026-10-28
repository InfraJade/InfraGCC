/**
 * Roles and site scope from SSO groups (DECISIONS D20/D21).
 *
 * Groups come from the access token's `groups` claim: gcc-viewer → viewer, gcc-noc-operator → noc_operator,
 * gcc-dc-engineer → dc_engineer, gcc-platform-admin → platform_admin, gcc-analyst → analyst;
 * `gcc-site-<CODE>` limits the user to that site (no site group = all sites).
 *
 * In the app the hierarchy is viewer < noc_operator < dc_engineer < platform_admin, and analyst counts as
 * viewer (analysts' extra rights live in Superset).
 */

export type Role = 'viewer' | 'noc_operator' | 'dc_engineer' | 'platform_admin' | 'analyst';
export type AppRole = Exclude<Role, 'analyst'>;

export const ROLE_ORDER: readonly AppRole[] = ['viewer', 'noc_operator', 'dc_engineer', 'platform_admin'];

export const ROLE_LABELS: Record<Role, string> = {
  viewer: 'Viewer',
  noc_operator: 'NOC operator',
  dc_engineer: 'DC engineer',
  platform_admin: 'Platform admin',
  analyst: 'Analyst',
};

export const GROUP_ROLE_MAP: Readonly<Record<string, Role>> = {
  'gcc-viewer': 'viewer',
  'gcc-noc-operator': 'noc_operator',
  'gcc-dc-engineer': 'dc_engineer',
  'gcc-platform-admin': 'platform_admin',
  'gcc-analyst': 'analyst',
};

const SITE_PREFIX = 'gcc-site-';

/** "/gcc-viewer" (full-path groups) and "gcc-viewer" both normalize to "gcc-viewer". */
export function normalizeGroup(group: string): string {
  const parts = group.split('/').filter(Boolean);
  return (parts[parts.length - 1] ?? '').trim();
}

export function rolesFromGroups(
  groups: readonly string[],
  map: Readonly<Record<string, Role>> = GROUP_ROLE_MAP,
): Role[] {
  const out = new Set<Role>();
  for (const g of groups) {
    const role = map[normalizeGroup(g).toLowerCase()];
    if (role) out.add(role);
  }
  const ordered: Role[] = ROLE_ORDER.filter((r) => out.has(r));
  if (out.has('analyst')) ordered.push('analyst');
  return ordered;
}

/** Site codes the user is limited to; an empty list means all sites. */
export function sitesFromGroups(groups: readonly string[]): string[] {
  const out = new Set<string>();
  for (const g of groups) {
    const name = normalizeGroup(g);
    if (name.toLowerCase().startsWith(SITE_PREFIX)) {
      const code = name.slice(SITE_PREFIX.length).trim().toUpperCase();
      if (code) out.add(code);
    }
  }
  return [...out].sort();
}

/** Rank in the app hierarchy; analyst = viewer; -1 = no app role at all. */
export function roleRank(role: Role): number {
  return role === 'analyst' ? 0 : ROLE_ORDER.indexOf(role);
}

export function highestRank(roles: readonly Role[]): number {
  return roles.reduce((max, r) => Math.max(max, roleRank(r)), -1);
}

/**
 * Does a user with `roles` have at least `required`?
 * `hasRole(roles, 'analyst')` is a membership check (analyst or platform admin), not a rank check.
 */
export function hasRole(roles: readonly Role[], required: Role): boolean {
  if (required === 'analyst') return roles.includes('analyst') || roles.includes('platform_admin');
  return highestRank(roles) >= roleRank(required);
}

/** The single role to show for a user (highest app role, or analyst when that's all they have). */
export function primaryRole(roles: readonly Role[]): Role | null {
  const rank = highestRank(roles);
  if (rank < 0) return null;
  if (rank === 0 && roles.includes('analyst') && !roles.includes('viewer')) return 'analyst';
  return ROLE_ORDER[rank] ?? null;
}
