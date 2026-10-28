/**
 * Aggregations behind the demo-mode Analytics dashboards (the real ones come from Superset, which can't
 * read the in-browser demo data). Computed from the same sensor model and alerts as the demo API.
 */
import type { Health } from '@/api/types';

import { firmwareItems, getDemoDb, sampleTime, serverHealth } from './server';
import { sensorValue, type DemoServer } from './seed';

const MIN = 60_000;
const HOUR = 3_600_000;
const DAY = 86_400_000;

export interface SitePoint {
  t: number;
  v: number | null;
}
export interface SiteSeries {
  siteId: number;
  code: string;
  name: string;
  points: SitePoint[];
}

const active = (s: DemoServer) => s.status !== 'decommissioned';

function siteSeries(
  metric: 'power_w' | 'inlet_temp_c',
  spanMs: number,
  stepMs: number,
  agg: 'sum' | 'avg',
  now = Date.now(),
): SiteSeries[] {
  const db = getDemoDb();
  const end = Math.floor(now / stepMs) * stepMs;
  return db.sites.map((site) => {
    const servers = db.servers.filter((s) => s.site_id === site.id && active(s));
    const points: SitePoint[] = [];
    for (let t = end - spanMs; t <= end; t += stepMs) {
      const vals = servers
        .map((s) => sensorValue(db, s, metric, '', t))
        .filter((v): v is number => v !== null);
      if (!vals.length) points.push({ t, v: null });
      else {
        const sum = vals.reduce((a, b) => a + b, 0);
        points.push({
          t,
          v: agg === 'sum' ? Math.round(sum / 100) / 10 : Math.round((sum / vals.length) * 10) / 10,
        });
      }
    }
    return { siteId: site.id, code: site.code, name: site.name, points };
  });
}

/** Total power per site in kW. */
export const powerBySite = (spanMs = DAY, stepMs = 15 * MIN, now = Date.now()) =>
  siteSeries('power_w', spanMs, stepMs, 'sum', now);
/** Average inlet temperature per site in °C. */
export const inletBySite = (spanMs = DAY, stepMs = 15 * MIN, now = Date.now()) =>
  siteSeries('inlet_temp_c', spanMs, stepMs, 'avg', now);

export interface ServerValueRow {
  id: number;
  name: string;
  site: string;
  rack: string;
  model: string;
  value: number;
}

function latestValue(s: DemoServer, metric: string, now: number): number | null {
  return sensorValue(getDemoDb(), s, metric, '', sampleTime(s, 60, now));
}

export function hottestServers(n = 10, now = Date.now()): ServerValueRow[] {
  const db = getDemoDb();
  return db.servers
    .filter(active)
    .map((s) => ({ s, v: latestValue(s, 'inlet_temp_c', now) }))
    .filter((x): x is { s: DemoServer; v: number } => x.v !== null)
    .sort((a, b) => b.v - a.v)
    .slice(0, n)
    .map(({ s, v }) => ({
      id: s.id,
      name: s.name,
      site: db.sites.find((x) => x.id === s.site_id)!.code,
      rack: db.racks.find((r) => r.id === s.rack_id)?.name ?? '—',
      model: `${s.vendor} ${s.model}`,
      value: v,
    }));
}

export interface RackUseRow {
  id: number;
  rack: string;
  site: string;
  powerKw: number;
  capacityKw: number;
  pct: number;
  servers: number;
}

export function rackUtilization(now = Date.now()): RackUseRow[] {
  const db = getDemoDb();
  return db.racks
    .map((r) => {
      const servers = db.servers.filter((s) => s.rack_id === r.id && active(s));
      const w = servers.reduce((sum, s) => sum + (latestValue(s, 'power_w', now) ?? 0), 0);
      const room = db.rooms.find((x) => x.id === r.room_id)!;
      const cap = r.power_capacity_w ?? 0;
      return {
        id: r.id,
        rack: r.name,
        site: db.sites.find((x) => x.id === room.site_id)!.code,
        powerKw: Math.round(w / 100) / 10,
        capacityKw: Math.round(cap / 100) / 10,
        pct: cap ? Math.round((w / cap) * 1000) / 10 : 0,
        servers: servers.length,
      };
    })
    .sort((a, b) => b.pct - a.pct);
}

export interface SiteHealthRow {
  code: string;
  name: string;
  counts: Record<Health, number>;
  total: number;
}

export function healthBySite(): SiteHealthRow[] {
  const db = getDemoDb();
  return db.sites.map((site) => {
    const counts: Record<Health, number> = { OK: 0, Warning: 0, Critical: 0, Unknown: 0 };
    const servers = db.servers.filter((s) => s.site_id === site.id && active(s));
    for (const s of servers) counts[serverHealth(s)]++;
    return { code: site.code, name: site.name, counts, total: servers.length };
  });
}

export interface PartRow {
  key: string;
  serverId: number;
  server: string;
  site: string;
  part: string;
  metric: string;
  health: 'Warning' | 'Critical';
  state: string;
  since: number;
}

const METRIC_LABEL: Record<string, string> = {
  psu_health: 'Power supply',
  psu_redundancy: 'PSU redundancy',
  fan_health: 'Fan',
  fan_redundancy: 'Fan redundancy',
  memory_health: 'Memory',
  drive_health: 'Drive',
  drive_life_pct: 'Drive wear',
  storage_health: 'RAID controller',
  volume_health: 'Volume',
  nic_link: 'NIC link',
  cpu_health: 'CPU',
  bmc_reachable: 'BMC',
  system_health: 'System',
  inlet_temp_c: 'Inlet temperature',
  power_state: 'Power state',
};

/** Parts unhealthy at `now`. */
export function unhealthyParts(now = Date.now()): PartRow[] {
  const db = getDemoDb();
  const rows: PartRow[] = [];
  for (const s of db.servers.filter(active)) {
    for (const [key, f] of Object.entries(s.faults)) {
      const [metric = '', component = ''] = key.split('|');
      if (metric === 'system_health' || f.since > now) continue;
      rows.push({
        key: `${s.id}|${key}`,
        serverId: s.id,
        server: s.name,
        site: db.sites.find((x) => x.id === s.site_id)!.code,
        part: component || '—',
        metric: METRIC_LABEL[metric] ?? metric,
        health: f.health,
        state: f.state,
        since: f.since,
      });
    }
  }
  return rows.sort((a, b) => (a.health === b.health ? b.since - a.since : a.health === 'Critical' ? -1 : 1));
}

/** Unhealthy parts per kind (bar chart). */
export function partsByKind(rows: PartRow[]): { kind: string; count: number }[] {
  const m = new Map<string, number>();
  for (const r of rows) m.set(r.metric, (m.get(r.metric) ?? 0) + 1);
  return [...m.entries()].map(([kind, count]) => ({ kind, count })).sort((a, b) => b.count - a.count);
}

export interface AlertDay {
  day: number;
  critical: number;
  warning: number;
  info: number;
}

export function alertsPerDay(days = 30, now = Date.now()): AlertDay[] {
  const db = getDemoDb();
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  const first = start.getTime() - (days - 1) * DAY;
  const out: AlertDay[] = Array.from({ length: days }, (_, i) => ({
    day: first + i * DAY,
    critical: 0,
    warning: 0,
    info: 0,
  }));
  for (const a of db.alerts) {
    const i = Math.floor((Date.parse(a.opened_at) - first) / DAY);
    const d = out[i];
    if (!d) continue;
    if (a.severity === 'Critical') d.critical++;
    else if (a.severity === 'Warning') d.warning++;
    else d.info++;
  }
  return out;
}

export interface AlertStats {
  open: number;
  acknowledged: number;
  resolved30d: number;
  medianResolveMin: number | null;
  medianAckMin: number | null;
  topRules: { rule: string; count: number; critical: number }[];
}

const median = (xs: number[]) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m]! : (s[m - 1]! + s[m]!) / 2;
};

export function alertStats(now = Date.now()): AlertStats {
  const db = getDemoDb();
  const recent = db.alerts.filter((a) => now - Date.parse(a.opened_at) <= 30 * DAY);
  const resolved = recent.filter((a) => a.resolved_at);
  const byRule = new Map<string, { count: number; critical: number }>();
  for (const a of recent) {
    const r = byRule.get(a.rule.name) ?? { count: 0, critical: 0 };
    r.count++;
    if (a.severity === 'Critical') r.critical++;
    byRule.set(a.rule.name, r);
  }
  return {
    open: db.alerts.filter((a) => a.state === 'open' && !a.muted).length,
    acknowledged: db.alerts.filter((a) => a.state === 'acknowledged').length,
    resolved30d: resolved.length,
    medianResolveMin: median(
      resolved.map((a) => (Date.parse(a.resolved_at!) - Date.parse(a.opened_at)) / MIN),
    ),
    medianAckMin: median(
      recent.filter((a) => a.acked_at).map((a) => (Date.parse(a.acked_at!) - Date.parse(a.opened_at)) / MIN),
    ),
    topRules: [...byRule.entries()]
      .map(([rule, v]) => ({ rule, ...v }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 8),
  };
}

export interface ModelRow {
  key: string;
  vendor: string;
  model: string;
  servers: number;
  compliant: number;
  offBaseline: number;
  noBaseline: boolean;
}

export function fleetByModel(now = Date.now()): ModelRow[] {
  const db = getDemoDb();
  const m = new Map<string, ModelRow>();
  for (const s of db.servers.filter(active)) {
    const key = `${s.vendor}|${s.model}`;
    const row = m.get(key) ?? {
      key,
      vendor: s.vendor,
      model: s.model,
      servers: 0,
      compliant: 0,
      offBaseline: 0,
      noBaseline: true,
    };
    row.servers++;
    const fw = firmwareItems(db, s, now).filter((f) => f.compliant !== null);
    if (fw.length) {
      row.noBaseline = false;
      if (fw.every((f) => f.compliant)) row.compliant++;
      else row.offBaseline++;
    }
    m.set(key, row);
  }
  return [...m.values()].sort((a, b) => b.servers - a.servers);
}

export function fleetTotals(now = Date.now()) {
  const db = getDemoDb();
  const servers = db.servers.filter(active);
  const watts = servers.reduce((sum, s) => sum + (latestValue(s, 'power_w', now) ?? 0), 0);
  const capacity = db.racks.reduce((sum, r) => sum + (r.power_capacity_w ?? 0), 0);
  const health = servers.map(serverHealth);
  return {
    servers: servers.length,
    healthyPct:
      Math.round((health.filter((h) => h === 'OK').length / Math.max(1, servers.length)) * 1000) / 10,
    powerKw: Math.round(watts / 100) / 10,
    capacityKw: Math.round(capacity / 100) / 10,
    racks: db.racks.length,
    sites: db.sites.length,
  };
}

export const HOURS = HOUR;
