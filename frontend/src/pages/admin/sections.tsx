import { lazy, type ComponentType, type LazyExoticComponent } from 'react';
import { Navigate } from 'react-router-dom';

import { useAuth } from '@/auth/AuthProvider';
import type { Role } from '@/auth/roles';

export interface AdminSection {
  path: string;
  label: string;
  /** Who may open the section (mirrors the API's read rule inside the DC-engineer-only admin area). */
  minRole: Role;
  description: string;
  /** The screen; edit buttons inside follow `useCan()` so view-only users see it read-only. */
  component: LazyExoticComponent<ComponentType>;
}

/**
 * Admin sub-pages. The whole area is DC engineer and up. Read rules come from the API routers:
 * sites, racks, servers, maintenance, collectors, thresholds, alert rules and baselines are readable by every
 * role (so DC engineers see the admin-only ones read-only); alert routes and users are platform admin only.
 * Write rules: sites/rooms, collectors, thresholds, rules, routes → platform admin; racks, servers,
 * maintenance, firmware baselines → DC engineer.
 */
export const ADMIN_SECTIONS: readonly AdminSection[] = [
  {
    path: 'sites',
    label: 'Sites & rooms',
    minRole: 'dc_engineer',
    description: 'Create and edit sites and rooms.',
    component: lazy(() => import('./SitesSection')),
  },
  {
    path: 'racks',
    label: 'Racks',
    minRole: 'dc_engineer',
    description: 'Racks, rows and heights; server positions.',
    component: lazy(() => import('./RacksSection')),
  },
  {
    path: 'servers',
    label: 'Server onboarding',
    minRole: 'dc_engineer',
    description: 'Onboard a server: BMC address, rack, position and collector.',
    component: lazy(() => import('./ServersSection')),
  },
  {
    path: 'maintenance',
    label: 'Maintenance windows',
    minRole: 'dc_engineer',
    description: 'Planned work that mutes alerts for servers, racks or sites.',
    component: lazy(() => import('./MaintenanceSection')),
  },
  {
    path: 'collectors',
    label: 'Collectors',
    minRole: 'dc_engineer',
    description: 'On-prem collectors, heartbeats and assignments.',
    component: lazy(() => import('./CollectorsSection')),
  },
  {
    path: 'thresholds',
    label: 'Thresholds',
    minRole: 'dc_engineer',
    description: 'Alert limits per metric: global, model, site, server.',
    component: lazy(() => import('./ThresholdsSection')),
  },
  {
    path: 'alert-rules',
    label: 'Alert rules',
    minRole: 'dc_engineer',
    description: 'What raises an alert: condition, duration, severity.',
    component: lazy(() => import('./AlertRulesSection')),
  },
  {
    path: 'routing',
    label: 'Routing',
    minRole: 'platform_admin',
    description: 'Email and Teams routes per site and severity, escalation.',
    component: lazy(() => import('./RoutingSection')),
  },
  {
    path: 'baselines',
    label: 'Firmware baselines',
    minRole: 'dc_engineer',
    description: 'Approved firmware versions per model.',
    component: lazy(() => import('./BaselinesSection')),
  },
  {
    path: 'users',
    label: 'Users',
    minRole: 'platform_admin',
    description: 'Who has signed in, with roles and sites (managed in SSO).',
    component: lazy(() => import('./UsersSection')),
  },
];

/** /admin → first section the user may open. */
export function AdminIndex() {
  const { hasRole } = useAuth();
  const first = ADMIN_SECTIONS.find((s) => hasRole(s.minRole));
  return <Navigate to={first ? `/admin/${first.path}` : '/'} replace />;
}
