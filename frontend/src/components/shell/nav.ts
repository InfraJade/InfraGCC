import type { Role } from '@/auth/roles';

import type { IconName } from '../Icon';

export interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  /** Lowest role that sees the item (hierarchy viewer < noc_operator < dc_engineer < platform_admin). */
  minRole: Role;
  end?: boolean;
}

/** Main navigation. Items the user's role can't open are not shown (routes are guarded too). */
export const NAV_ITEMS: readonly NavItem[] = [
  { to: '/', label: 'Overview', icon: 'dashboard', minRole: 'viewer', end: true },
  { to: '/alerts', label: 'Alerts', icon: 'bell', minRole: 'viewer' },
  { to: '/inventory', label: 'Inventory', icon: 'server', minRole: 'viewer' },
  { to: '/firmware', label: 'Firmware', icon: 'chip', minRole: 'viewer' },
  { to: '/analytics', label: 'Analytics', icon: 'chart', minRole: 'viewer' },
  { to: '/admin', label: 'Admin', icon: 'sliders', minRole: 'dc_engineer' },
  { to: '/audit', label: 'Audit log', icon: 'file-text', minRole: 'platform_admin' },
  { to: '/settings', label: 'Settings', icon: 'settings', minRole: 'viewer' },
];

export function visibleNav(hasRole: (r: Role) => boolean, items: readonly NavItem[] = NAV_ITEMS): NavItem[] {
  return items.filter((i) => hasRole(i.minRole));
}
