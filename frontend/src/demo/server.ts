/**
 * The demo backend: answers every `/api/v1/*` call the app makes from the in-memory demo data set, with the
 * same shapes, filters, cursor pagination, site limits and role checks as the real API. Writes (acknowledge,
 * comment, edit a threshold, onboard a server, ...) change the in-memory data, so the app behaves normally
 * until the page is reloaded (or "Reset demo data" is used), which restores the original data set.
 */
import type {
  AlertCounts,
  AlertDetail,
  AlertRoute,
  AlertRule,
  AuditEntry,
  Baseline,
  Collector,
  Compliance,
  ComplianceServer,
  ComponentListItem,
  EffectiveLimit,
  FirmwareItem,
  Freshness,
  Health,
  HealthCounts,
  HealthPart,
  LatestReading,
  Maintenance,
  Me,
  OverviewTotals,
  Rack,
  RackDetail,
  RackServer,
  RackSummary,
  ReadingValue,
  Readings,
  Room,
  RoomWithRacks,
  SearchOut,
  ServerDetail,
  ServerListItem,
  SiteDetail,
  SiteOut,
  SiteSummary,
  Threshold,
  ThresholdPage,
} from '@/api/types';
import type { Role } from '@/auth/roles';

import {
  buildDemoDb,
  DIMMS_PER_CPU,
  hash01,
  sensorStatus,
  sensorValue,
  strHash,
  type DemoDb,
  type DemoMaintenance,
  type DemoRack,
  type DemoServer,
  type DemoSite,
} from './seed';

// ---------------------------------------------------------------------------------------------- state

let current: DemoDb | null = null;

export function getDemoDb(): DemoDb {
  current ??= buildDemoDb();
  return current;
}

/** Throw away every change and rebuild the data set (timestamps relative to now again). */
export function resetDemoDb(): void {
  current = buildDemoDb();
}

export interface DemoUser {
  sub: string;
  username: string;
  name: string;
  email: string | null;
  roles: Role[];
  /** Site codes the user is limited to; empty = all sites. */
  sites: string[];
  expiresAt: number | null;
}

// ---------------------------------------------------------------------------------------------- http plumbing

export class DemoHttpError extends Error {
  constructor(
    readonly status: number,
    readonly title: string,
    readonly detail?: string,
    readonly errors?: { loc: string[]; msg: string; type: string }[],
  ) {
    super(detail ?? title);
  }
}

const TITLES: Record<number, string> = {
  400: 'Bad Request',
  403: 'Forbidden',
  404: 'Not Found',
  409: 'Conflict',
  422: 'Unprocessable Content',
};
const fail = (status: number, detail: string): never => {
  throw new DemoHttpError(status, TITLES[status] ?? 'Error', detail);
};
const invalid = (field: string, msg: string): never => {
  throw new DemoHttpError(422, 'Unprocessable Content', 'The request did not pass validation.', [
    { loc: ['body', field], msg, type: 'value_error' },
  ]);
};

export interface DemoResult {
  status: number;
  body?: unknown;
  contentType?: string;
  headers?: Record<string, string>;
}

interface Ctx {
  method: string;
  params: Record<string, string>;
  query: URLSearchParams;
  body: Record<string, unknown>;
  user: DemoUser | null;
  now: number;
  db: DemoDb;
}

type Handler = (ctx: Ctx) => unknown;

interface RouteDef {
  method: string;
  re: RegExp;
  keys: string[];
  handler: Handler;
}

const routes: RouteDef[] = [];
function route(method: string, pattern: string, handler: Handler) {
  const keys: string[] = [];
  const re = new RegExp(
    `^${pattern.replace(/:(\w+)/g, (_, k: string) => {
      keys.push(k);
      return '([^/]+)';
    })}$`,
  );
  for (const m of method.split('|')) routes.push({ method: m, re, keys, handler });
}

/** Run one demo API request. `path` is the part after `/api/v1`. */
export function handleDemoRequest(
  method: string,
  path: string,
  query: URLSearchParams,
  body: unknown,
  user: DemoUser | null,
): DemoResult {
  const db = getDemoDb();
  for (const r of routes) {
    if (r.method !== method) continue;
    const m = r.re.exec(path);
    if (!m) continue;
    const params: Record<string, string> = {};
    r.keys.forEach((k, i) => (params[k] = decodeURIComponent(m[i + 1] ?? '')));
    const ctx: Ctx = {
      method,
      params,
      query,
      body: body && typeof body === 'object' ? (body as Record<string, unknown>) : {},
      user,
      now: Date.now(),
      db,
    };
    const out = r.handler(ctx);
    if (out && typeof out === 'object' && '__demoResult' in out)
      return (out as unknown as { result: DemoResult }).result;
    if (out === undefined) return { status: method === 'DELETE' ? 204 : 200 };
    return {
      status:
        method === 'POST' &&
        !path.includes('/ack') &&
        !path.includes('/resolve') &&
        !path.includes('/comments') &&
        !path.includes('guest-token')
          ? 201
          : 200,
      body: out,
    };
  }
  return fail(404, `No demo data for ${method} /api/v1${path}.`);
}

const raw = (result: DemoResult) => ({ __demoResult: true, result });

// ---------------------------------------------------------------------------------------------- helpers

const iso = (ms: number) => new Date(Math.round(ms / 1000) * 1000).toISOString().replace('.000Z', 'Z');
const MIN = 60_000;

const ROLE_RANK: Record<Role, number> = {
  viewer: 0,
  analyst: 0,
  noc_operator: 1,
  dc_engineer: 2,
  platform_admin: 3,
};
function hasRole(user: DemoUser | null, role: Role): boolean {
  if (!user) return false;
  if (role === 'analyst') return user.roles.includes('analyst') || user.roles.includes('platform_admin');
  return user.roles.some((r) => ROLE_RANK[r] >= ROLE_RANK[role]);
}
function requireRole(ctx: Ctx, role: Role, what = 'This action') {
  if (!hasRole(ctx.user, role)) fail(403, `${what} needs the ${role.replace('_', ' ')} role.`);
}
function unrestricted(ctx: Ctx, what: string) {
  if ((ctx.user?.sites.length ?? 0) > 0)
    fail(403, `${what} applies to every site; users limited to some sites can't change it.`);
}

function visibleSiteIds(ctx: Ctx): Set<number> {
  const codes = ctx.user?.sites ?? [];
  return new Set(ctx.db.sites.filter((s) => codes.length === 0 || codes.includes(s.code)).map((s) => s.id));
}
function canSee(ctx: Ctx, siteId: number | null | undefined): boolean {
  return siteId === null || siteId === undefined
    ? (ctx.user?.sites.length ?? 0) === 0
    : visibleSiteIds(ctx).has(siteId);
}

const qInt = (ctx: Ctx, key: string): number | undefined => {
  const v = ctx.query.get(key);
  if (v === null || v === '') return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
};
const qStr = (ctx: Ctx, key: string): string | undefined => {
  const v = ctx.query.get(key);
  return v === null || v === '' ? undefined : v;
};
const qBool = (ctx: Ctx, key: string): boolean | undefined => {
  const v = ctx.query.get(key);
  return v === null || v === '' ? undefined : v === 'true' || v === '1';
};
const qList = (ctx: Ctx, key: string) => ctx.query.getAll(key).filter(Boolean);
const like = (hay: (string | null | undefined)[], q: string) => {
  const needle = q.trim().toLowerCase();
  return hay.some((h) => (h ?? '').toLowerCase().includes(needle));
};
const pid = (ctx: Ctx, key = 'id') => {
  const n = Number(ctx.params[key]);
  if (!Number.isInteger(n)) fail(404, 'Not found.');
  return n;
};
const str = (ctx: Ctx, key: string): string | undefined => {
  const v = ctx.body[key];
  return typeof v === 'string' ? v : undefined;
};
const num = (ctx: Ctx, key: string): number | null | undefined => {
  const v = ctx.body[key];
  if (v === null) return null;
  return typeof v === 'number' ? v : undefined;
};
const bodyStr = (body: Record<string, unknown>, key: string, fallback: string): string => {
  const v = body[key];
  return typeof v === 'string' ? v : fallback;
};
const has = (ctx: Ctx, key: string) => Object.prototype.hasOwnProperty.call(ctx.body, key);

/** Offset cursor pagination, like the API's `{items, next_cursor}`. */
function page<T>(ctx: Ctx, items: T[], extra: Record<string, unknown> = {}) {
  const limit = Math.min(500, Math.max(1, qInt(ctx, 'limit') ?? 50));
  const cursor = qStr(ctx, 'cursor');
  const offset = cursor ? Number(atob(cursor).replace('o:', '')) || 0 : 0;
  const slice = items.slice(offset, offset + limit);
  const next = offset + limit < items.length ? btoa(`o:${offset + limit}`) : null;
  return { items: slice, next_cursor: next, ...extra };
}

function audit(
  ctx: Ctx,
  action: string,
  objectType: string,
  objectId: string | number | null,
  before: Record<string, unknown> | null,
  after: Record<string, unknown> | null,
) {
  const db = ctx.db;
  const entry: AuditEntry = {
    id: (db.audit[0]?.id ?? 0) + 1,
    time: iso(ctx.now),
    user_sub: ctx.user?.sub ?? null,
    user_name: ctx.user?.name ?? 'demo user',
    action,
    object_type: objectType,
    object_id: objectId === null ? null : String(objectId),
    before,
    after,
    ip: '127.0.0.1',
    request_id: (strHash(`${action}${ctx.now}`) >>> 0).toString(16).padStart(8, '0') + 'demo0000demo0000',
  };
  db.audit.unshift(entry);
}

// ---------------------------------------------------------------------------------------------- derived values

const HEALTH_RANK: Record<Health, number> = { OK: 0, Unknown: 1, Warning: 2, Critical: 3 };
const worst = (hs: Health[]): Health =>
  hs.reduce<Health>((w, h) => (HEALTH_RANK[h] > HEALTH_RANK[w] ? h : w), 'OK');

const site = (db: DemoDb, id: number) => db.sites.find((s) => s.id === id)!;
const siteRef = (s: DemoSite) => ({ id: s.id, code: s.code, name: s.name });
const rackOf = (db: DemoDb, id: number | null) => db.racks.find((r) => r.id === id) ?? null;
const roomOf = (db: DemoDb, id: number | null) => db.rooms.find((r) => r.id === id) ?? null;
const metricDef = (db: DemoDb, code: string) => db.metrics.find((m) => m.code === code)!;
const listed = (db: DemoDb) => db.servers.filter((s) => s.status !== 'decommissioned');

/** (metric, component) pairs a server reports, in the order of the server page. */
function readingKeys(s: DemoServer): [string, string][] {
  const of = (type: string) => s.components.filter((c) => c.type === type).map((c) => c.name);
  const dimms = of('dimm');
  const keys: [string, string][] = [
    ['inlet_temp_c', ''],
    ['exhaust_temp_c', ''],
  ];
  for (const c of of('cpu')) keys.push(['cpu_temp_c', c]);
  keys.push(['dimm_temp_c', dimms[0]!], ['dimm_temp_c', dimms[DIMMS_PER_CPU]!]);
  for (const f of of('fan')) keys.push(['fan_rpm', f]);
  for (const f of of('fan')) keys.push(['fan_health', f]);
  keys.push(['fan_redundancy', ''], ['power_w', ''], ['power_capacity_w', '']);
  for (const p of of('psu')) keys.push(['psu_health', p]);
  for (const p of of('psu')) keys.push(['psu_input_v', p]);
  keys.push(['psu_redundancy', ''], ['power_state', ''], ['system_health', '']);
  for (const c of of('cpu')) keys.push(['cpu_health', c]);
  for (const d of dimms) keys.push(['memory_health', d]);
  for (const d of of('drive')) keys.push(['drive_health', d]);
  for (const d of of('drive')) keys.push(['drive_life_pct', d]);
  for (const c of of('storage_controller')) keys.push(['storage_health', c]);
  for (const v of of('volume')) keys.push(['volume_health', v]);
  for (const n of of('nic')) keys.push(['nic_link', n]);
  keys.push(['bmc_health', ''], ['bmc_reachable', '']);
  return keys;
}

/** Time of the latest sample of a metric (polled every interval, offset per server). */
export function sampleTime(s: DemoServer, intervalS: number, now: number): number {
  const offset = (s.seed % 40) * 1000;
  const step = intervalS * 1000;
  let t = Math.floor((now - offset) / step) * step + offset;
  if (s.unreachableSince !== null) t = Math.min(t, s.unreachableSince - 1000);
  return t;
}

function latestReadings(db: DemoDb, s: DemoServer, now: number): LatestReading[] {
  const out: LatestReading[] = [];
  for (const [metric, component] of readingKeys(s)) {
    const def = metricDef(db, metric);
    const interval = metric === 'bmc_reachable' ? 60 : Math.min(def.interval_s, 300);
    let t = sampleTime(s, interval, now);
    if (metric === 'bmc_reachable') t = Math.floor(now / 60_000) * 60_000 - (s.seed % 40) * 1000;
    const value = sensorValue(db, s, metric, component, t);
    if (value === null && metric !== 'bmc_reachable') continue;
    out.push({
      metric,
      metric_name: def.name,
      unit: def.unit,
      type: def.type,
      category: def.category,
      component,
      value,
      status: sensorStatus(s, metric, component, value),
      time: iso(t),
      age_s: Math.max(0, Math.round((now - t) / 1000)),
    });
  }
  return out;
}

function lastSeen(s: DemoServer, now: number): number {
  return sampleTime(s, 60, now);
}

function healthParts(db: DemoDb, s: DemoServer, now: number): HealthPart[] {
  const out: HealthPart[] = [];
  for (const [metric, component] of readingKeys(s)) {
    const def = metricDef(db, metric);
    const f = s.faults[`${metric}|${component}`];
    if (def.type !== 'state' && !f) continue;
    const t = sampleTime(s, 60, now);
    const value = sensorValue(db, s, metric, component, t);
    out.push({
      metric,
      metric_name: def.name,
      category: def.category,
      component,
      health: f ? f.health : 'OK',
      state: f ? f.state : sensorStatus(s, metric, component, value ?? 0),
      since: iso(f ? f.since : Date.parse(s.discovered_at)),
      updated_at: iso(t),
    });
  }
  return out;
}

export function serverHealth(s: DemoServer): Health {
  if (s.status === 'decommissioned') return 'Unknown';
  return worst(Object.values(s.faults).map((f) => f.health));
}

const unresolved = (a: AlertDetail) => a.state !== 'resolved';
const openAlerts = (db: DemoDb, s: DemoServer) =>
  db.alerts.filter((a) => unresolved(a) && a.server?.id === s.id).length;

function readingValue(db: DemoDb, s: DemoServer, metric: string, now: number): ReadingValue | null {
  const t = sampleTime(s, 60, now);
  const v = sensorValue(db, s, metric, '', t);
  if (v === null) return null;
  return {
    value: v,
    unit: metricDef(db, metric).unit,
    status: sensorStatus(s, metric, '', v),
    time: iso(t),
    age_s: Math.round((now - t) / 1000),
  };
}

function serverListItem(db: DemoDb, s: DemoServer, now: number): ServerListItem {
  const rack = rackOf(db, s.rack_id);
  const room = roomOf(db, s.room_id);
  const collector = db.collectors.find((c) => c.id === s.collector_id) ?? null;
  return {
    id: s.id,
    name: s.name,
    hostname: s.hostname,
    bmc_host: s.bmc_host,
    vendor: s.vendor,
    model: s.model,
    serial: s.serial,
    asset_tag: s.asset_tag,
    status: s.status,
    health: serverHealth(s),
    site: siteRef(site(db, s.site_id)),
    room: room ? { id: room.id, name: room.name } : null,
    rack: rack ? { id: rack.id, name: rack.name } : null,
    position_u: s.position_u,
    height_u: s.height_u,
    collector_id: s.collector_id,
    collector_name: collector?.name ?? null,
    last_seen_at: iso(lastSeen(s, now)),
    open_alerts: openAlerts(db, s),
  };
}

function baselineFor(db: DemoDb, s: DemoServer, key: string) {
  return (
    db.baselines.find((b) => b.vendor === s.vendor && b.model === s.model && b.component === key) ?? null
  );
}

export function firmwareItems(db: DemoDb, s: DemoServer, now: number): FirmwareItem[] {
  const collected = iso(
    Math.floor(now / 86_400_000) * 86_400_000 +
      2 * 3_600_000 -
      (now % 86_400_000 < 2 * 3_600_000 ? 86_400_000 : 0),
  );
  return s.firmware.map((f) => {
    const b = baselineFor(db, s, f.component_key);
    return {
      ...f,
      approved_version: b?.version ?? null,
      compliant: b ? b.version === f.version : null,
      collected_at: collected,
    };
  });
}

const stripActivity = (a: AlertDetail) => {
  const { activity: _activity, ...rest } = a;
  void _activity;
  return rest;
};

function serverDetail(db: DemoDb, s: DemoServer, now: number): ServerDetail {
  const collector = db.collectors.find((c) => c.id === s.collector_id) ?? null;
  return {
    ...serverListItem(db, s, now),
    bmc_mac: s.bmc_mac,
    bmc_model: s.bmc_model,
    host_ips: s.host_ips,
    system_path: s.system_path,
    notes: s.notes,
    discovered_at: s.discovered_at,
    created_at: s.created_at,
    updated_at: s.updated_at,
    collector: collector
      ? { id: collector.id, name: collector.name, online: collectorOnline(collector) }
      : null,
    rack_height_u: rackOf(db, s.rack_id)?.height_u ?? null,
    health_parts: healthParts(db, s, now),
    latest_readings: latestReadings(db, s, now),
    components: s.components,
    firmware: firmwareItems(db, s, now),
    recent_events: s.events.slice(0, 20),
    active_alerts: db.alerts.filter((a) => unresolved(a) && a.server?.id === s.id).map(stripActivity),
  };
}

function healthCounts(servers: DemoServer[]): HealthCounts {
  const c = { ok: 0, warning: 0, critical: 0, unknown: 0 };
  for (const s of servers) {
    const h = serverHealth(s);
    if (h === 'OK') c.ok++;
    else if (h === 'Warning') c.warning++;
    else if (h === 'Critical') c.critical++;
    else c.unknown++;
  }
  return c;
}

function alertCounts(alerts: AlertDetail[]): AlertCounts {
  const c = { critical: 0, warning: 0, info: 0, acknowledged: 0, muted: 0 };
  for (const a of alerts) {
    if (!unresolved(a)) continue;
    if (a.muted) {
      c.muted++;
      continue;
    }
    if (a.state === 'acknowledged') c.acknowledged++;
    if (a.severity === 'Critical') c.critical++;
    else if (a.severity === 'Warning') c.warning++;
    else c.info++;
  }
  return c;
}

function freshness(servers: DemoServer[], now: number): Freshness {
  const active = servers.filter((s) => s.status !== 'decommissioned');
  const seen = active.map((s) => lastSeen(s, now));
  const stale = seen.filter((t) => now - t > 5 * MIN).length;
  return {
    latest_reading_at: seen.length ? iso(Math.max(...seen)) : null,
    oldest_server_reading_at: seen.length ? iso(Math.min(...seen)) : null,
    servers_reporting: active.length - stale,
    servers_stale: stale,
  };
}

const powerOf = (db: DemoDb, servers: DemoServer[], now: number) =>
  servers.reduce((sum, s) => sum + (sensorValue(db, s, 'power_w', '', sampleTime(s, 60, now)) ?? 0), 0);

function inletStats(db: DemoDb, servers: DemoServer[], now: number) {
  const vals = servers
    .map((s) => sensorValue(db, s, 'inlet_temp_c', '', sampleTime(s, 60, now)))
    .filter((v): v is number => v !== null);
  if (!vals.length) return { avg: null, max: null };
  return {
    avg: Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10,
    max: Math.max(...vals),
  };
}

export const collectorOnline = (c: { enabled: boolean; heartbeatAgeS: number | null }) =>
  c.enabled && c.heartbeatAgeS !== null && c.heartbeatAgeS <= 120;

function siteSummary(db: DemoDb, s: DemoSite, now: number): SiteSummary {
  const rooms = db.rooms.filter((r) => r.site_id === s.id);
  const racks = db.racks.filter((r) => rooms.some((room) => room.id === r.room_id));
  const servers = listed(db).filter((x) => x.site_id === s.id);
  const collectors = db.collectors.filter((c) => c.site_id === s.id);
  const inlet = inletStats(db, servers, now);
  return {
    id: s.id,
    code: s.code,
    name: s.name,
    city: s.city,
    country: s.country,
    timezone: s.timezone,
    room_count: rooms.length,
    rack_count: racks.length,
    server_count: servers.length,
    servers_in_maintenance: servers.filter((x) => x.status === 'maintenance').length,
    health: healthCounts(servers),
    worst_health: worst(servers.map(serverHealth)),
    alerts: alertCounts(db.alerts.filter((a) => a.site?.id === s.id)),
    power_w: Math.round(powerOf(db, servers, now)),
    rack_power_capacity_w: racks.reduce((sum, r) => sum + (r.power_capacity_w ?? 0), 0),
    inlet_avg_c: inlet.avg,
    inlet_max_c: inlet.max,
    freshness: freshness(servers, now),
    collectors_online: collectors.filter(collectorOnline).length,
    collectors_total: collectors.length,
  };
}

function rackServers(db: DemoDb, r: DemoRack) {
  return listed(db).filter((s) => s.rack_id === r.id);
}

function rackSummary(db: DemoDb, r: DemoRack, now: number): RackSummary {
  const servers = rackServers(db, r);
  const inlet = inletStats(db, servers, now);
  return {
    id: r.id,
    name: r.name,
    row: r.row,
    height_u: r.height_u,
    power_capacity_w: r.power_capacity_w,
    server_count: servers.length,
    used_u: servers.reduce((u, s) => u + s.height_u, 0),
    health: healthCounts(servers),
    worst_health: worst(servers.map(serverHealth)),
    open_alerts: db.alerts.filter((a) => unresolved(a) && servers.some((s) => s.id === a.server?.id)).length,
    power_w: Math.round(powerOf(db, servers, now)),
    inlet_max_c: inlet.max,
  };
}

function rackOut(db: DemoDb, r: DemoRack): Rack {
  const room = roomOf(db, r.room_id)!;
  const s = site(db, room.site_id);
  const servers = rackServers(db, r);
  return {
    id: r.id,
    room_id: room.id,
    room_name: room.name,
    site_id: s.id,
    site_code: s.code,
    name: r.name,
    row: r.row,
    height_u: r.height_u,
    power_capacity_w: r.power_capacity_w,
    server_count: servers.length,
    used_u: servers.reduce((u, x) => u + x.height_u, 0),
  };
}

function roomOut(db: DemoDb, r: (typeof db.rooms)[number]): Room {
  return {
    id: r.id,
    site_id: r.site_id,
    site_code: site(db, r.site_id).code,
    name: r.name,
    floor: r.floor,
    rack_count: db.racks.filter((x) => x.room_id === r.id).length,
  };
}

function collectorOut(db: DemoDb, c: (typeof db.collectors)[number], now: number): Collector {
  const assigned = listed(db).filter(
    (s) =>
      s.collector_id === c.id ||
      (s.site_id === c.site_id &&
        !collectorOnline(
          db.collectors.find((x) => x.id === s.collector_id) ?? { enabled: false, heartbeatAgeS: null },
        ) &&
        collectorOnline(c)),
  );
  const online = collectorOnline(c);
  const hb = c.heartbeatAgeS === null ? null : now - c.heartbeatAgeS * 1000 - (now % 30_000);
  return {
    id: c.id,
    site_id: c.site_id,
    site_code: site(db, c.site_id).code,
    name: c.name,
    version: c.version,
    hostname: c.hostname,
    enabled: c.enabled,
    online,
    last_heartbeat: hb === null ? null : iso(hb),
    heartbeat_age_s: hb === null ? null : Math.round((now - hb) / 1000),
    cert_fingerprint: c.cert_fingerprint,
    servers_preferred: listed(db).filter((s) => s.collector_id === c.id).length,
    stats: online
      ? {
          servers_assigned: assigned.length,
          servers_ok: assigned.filter((s) => s.unreachableSince === null).length,
          polls_ok_1m: assigned.length,
          polls_failed_1m: assigned.filter((s) => s.unreachableSince !== null).length,
          cycles_skipped_1m: 0,
          buffer_batches: 0,
          buffer_bytes: 0,
          last_batch_at: iso(now - 7000),
          config_version: (strHash(c.name) >>> 0).toString(16).slice(0, 12),
        }
      : { buffer_batches: 212, buffer_bytes: 1843200, last_batch_at: hb === null ? null : iso(hb) },
    created_at: c.created_at,
  };
}

function maintTargetSite(db: DemoDb, m: DemoMaintenance): number {
  if (m.scope === 'site') return m.site_id!;
  if (m.scope === 'rack') return roomOf(db, rackOf(db, m.rack_id)!.room_id)!.site_id;
  return db.servers.find((s) => s.id === m.server_id)!.site_id;
}

function maintOut(db: DemoDb, m: DemoMaintenance, now: number): Maintenance {
  const name =
    m.scope === 'site'
      ? `${site(db, m.site_id!).code} · ${site(db, m.site_id!).name}`
      : m.scope === 'rack'
        ? `Rack ${rackOf(db, m.rack_id)!.name} (${site(db, maintTargetSite(db, m)).code})`
        : db.servers.find((s) => s.id === m.server_id)!.name;
  return {
    ...m,
    target_site_id: maintTargetSite(db, m),
    target_name: name,
    active: Date.parse(m.starts_at) <= now && now < Date.parse(m.ends_at),
  };
}

// ---------------------------------------------------------------------------------------------- me, metrics, overview, search

function capabilities(user: DemoUser | null): Record<string, boolean> {
  const viewer = Boolean(user && user.roles.length);
  const operator = hasRole(user, 'noc_operator');
  const engineer = hasRole(user, 'dc_engineer');
  const admin = hasRole(user, 'platform_admin');
  return {
    view: viewer,
    ack_alerts: operator,
    comment_alerts: operator,
    resolve_alerts: operator,
    onboard_servers: engineer,
    edit_racks: engineer,
    edit_maintenance: engineer,
    edit_baselines: engineer,
    edit_sites: admin,
    edit_collectors: admin,
    edit_thresholds: admin,
    edit_alert_rules: admin,
    edit_alert_routes: admin,
    view_users: admin,
    view_audit: admin && (user?.sites.length ?? 0) === 0,
    superset_editor: Boolean(user?.roles.includes('analyst')) || admin,
  };
}

route('GET', '/me', (ctx): Me => {
  const u = ctx.user;
  if (!u) return fail(403, 'Not signed in.');
  const order: Role[] = ['platform_admin', 'dc_engineer', 'noc_operator', 'analyst', 'viewer'];
  return {
    sub: u.sub,
    username: u.username,
    name: u.name,
    email: u.email,
    roles: u.roles,
    primary_role: order.find((r) => u.roles.includes(r)) ?? null,
    site_limited: u.sites.length > 0,
    sites: u.sites.length ? ctx.db.sites.filter((s) => u.sites.includes(s.code)).map(siteRef) : null,
    capabilities: capabilities(u),
    token_expires_at: iso(u.expiresAt ? u.expiresAt * 1000 : ctx.now + 15 * MIN),
  };
});

route('GET', '/metrics', (ctx) => ctx.db.metrics);

route('GET', '/overview', (ctx) => {
  const ids = qList(ctx, 'site_id').map(Number);
  const sites = ctx.db.sites.filter((s) => canSee(ctx, s.id) && (ids.length === 0 || ids.includes(s.id)));
  const summaries = sites.map((s) => siteSummary(ctx.db, s, ctx.now));
  const servers = listed(ctx.db).filter((s) => sites.some((x) => x.id === s.site_id));
  const collectors = ctx.db.collectors.filter((c) => sites.some((x) => x.id === c.site_id));
  const totals: OverviewTotals = {
    sites: sites.length,
    server_count: servers.length,
    health: healthCounts(servers),
    worst_health: worst(servers.map(serverHealth)),
    alerts: alertCounts(
      ctx.db.alerts.filter((a) => a.site !== null && sites.some((x) => x.id === a.site!.id)),
    ),
    power_w: Math.round(powerOf(ctx.db, servers, ctx.now)),
    freshness: freshness(servers, ctx.now),
    collectors_online: collectors.filter(collectorOnline).length,
    collectors_total: collectors.length,
  };
  return { generated_at: iso(ctx.now), totals, sites: summaries };
});

route('GET', '/search', (ctx): SearchOut => {
  const q = qStr(ctx, 'q') ?? '';
  const limit = qInt(ctx, 'limit') ?? 10;
  const db = ctx.db;
  return {
    query: q,
    servers: listed(db)
      .filter((s) => canSee(ctx, s.site_id) && like([s.name, s.serial, s.bmc_host, s.asset_tag, s.model], q))
      .slice(0, limit)
      .map((s) => ({
        id: s.id,
        name: s.name,
        bmc_host: s.bmc_host,
        serial: s.serial,
        asset_tag: s.asset_tag,
        model: s.model,
        site_code: site(db, s.site_id).code,
        rack_name: rackOf(db, s.rack_id)?.name ?? null,
        position_u: s.position_u,
        health: serverHealth(s),
      })),
    racks: db.racks
      .filter((r) => like([r.name], q))
      .map((r) => rackOut(db, r))
      .filter((r) => canSee(ctx, r.site_id))
      .slice(0, limit)
      .map((r) => ({
        id: r.id,
        name: r.name,
        room_name: r.room_name,
        site_id: r.site_id,
        site_code: r.site_code,
      })),
    sites: db.sites
      .filter((s) => canSee(ctx, s.id) && like([s.code, s.name, s.city], q))
      .slice(0, limit)
      .map((s) => ({ id: s.id, code: s.code, name: s.name, city: s.city })),
  };
});

// ---------------------------------------------------------------------------------------------- sites, rooms, racks

const siteOut = (s: DemoSite): SiteOut => ({
  id: s.id,
  code: s.code,
  name: s.name,
  city: s.city,
  country: s.country,
  timezone: s.timezone,
  created_at: s.created_at,
  updated_at: s.updated_at,
});

route('GET', '/sites', (ctx) =>
  page(
    ctx,
    ctx.db.sites.filter((s) => canSee(ctx, s.id)).map((s) => siteSummary(ctx.db, s, ctx.now)),
  ),
);

route('GET', '/sites/:id', (ctx): SiteDetail => {
  const db = ctx.db;
  const s = db.sites.find((x) => x.id === pid(ctx));
  if (!s || !canSee(ctx, s.id)) return fail(404, 'Site not found.');
  const roomId = qInt(ctx, 'room_id');
  const rooms: RoomWithRacks[] = db.rooms
    .filter((r) => r.site_id === s.id && (roomId === undefined || r.id === roomId))
    .map((r) => {
      const racks = db.racks.filter((x) => x.room_id === r.id).map((x) => rackSummary(db, x, ctx.now));
      return {
        id: r.id,
        name: r.name,
        floor: r.floor,
        worst_health: worst(racks.map((x) => x.worst_health)),
        racks,
      };
    });
  return {
    ...siteSummary(db, s, ctx.now),
    rooms,
    collectors: db.collectors
      .filter((c) => c.site_id === s.id)
      .map((c) => ({ id: c.id, name: c.name, online: collectorOnline(c) })),
  };
});

route('POST', '/sites', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Creating a site');
  const code = (str(ctx, 'code') ?? '').trim().toUpperCase();
  if (!code) invalid('code', 'Enter a site code.');
  if (ctx.db.sites.some((s) => s.code === code)) fail(409, `A site with code ${code} already exists.`);
  const s: DemoSite = {
    id: ctx.db.nextId(),
    code,
    name: str(ctx, 'name') ?? code,
    city: str(ctx, 'city') ?? '',
    country: str(ctx, 'country') ?? '',
    timezone: str(ctx, 'timezone') ?? 'UTC',
    phase: 0,
    created_at: iso(ctx.now),
    updated_at: iso(ctx.now),
  };
  ctx.db.sites.push(s);
  audit(ctx, 'site.create', 'site', s.id, null, { code: s.code, name: s.name });
  return siteOut(s);
});

route('PUT|PATCH', '/sites/:id', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Changing a site');
  const s = ctx.db.sites.find((x) => x.id === pid(ctx)) ?? fail(404, 'Site not found.');
  for (const k of ['name', 'city', 'country', 'timezone'] as const)
    if (typeof ctx.body[k] === 'string') s[k] = ctx.body[k];
  s.updated_at = iso(ctx.now);
  audit(ctx, 'site.update', 'site', s.id, null, ctx.body);
  return siteOut(s);
});

route('DELETE', '/sites/:id', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Deleting a site');
  const id = pid(ctx);
  if (ctx.db.rooms.some((r) => r.site_id === id)) fail(409, 'The site still has rooms. Remove them first.');
  ctx.db.sites = ctx.db.sites.filter((s) => s.id !== id);
  audit(ctx, 'site.delete', 'site', id, null, null);
});

route('GET', '/rooms', (ctx) => {
  const siteId = qInt(ctx, 'site_id');
  return page(
    ctx,
    ctx.db.rooms
      .filter((r) => canSee(ctx, r.site_id) && (siteId === undefined || r.site_id === siteId))
      .map((r) => roomOut(ctx.db, r)),
  );
});
route('GET', '/rooms/:id', (ctx) =>
  roomOut(ctx.db, ctx.db.rooms.find((r) => r.id === pid(ctx)) ?? fail(404, 'Room not found.')),
);
route('POST', '/rooms', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Creating a room');
  const siteId = num(ctx, 'site_id');
  if (!siteId || !ctx.db.sites.some((s) => s.id === siteId)) invalid('site_id', 'Unknown site.');
  const r = {
    id: ctx.db.nextId(),
    site_id: siteId!,
    name: (str(ctx, 'name') ?? '').trim() || 'New room',
    floor: str(ctx, 'floor') ?? null,
  };
  ctx.db.rooms.push(r);
  audit(ctx, 'room.create', 'room', r.id, null, { name: r.name });
  return roomOut(ctx.db, r);
});
route('PUT|PATCH', '/rooms/:id', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Changing a room');
  const r = ctx.db.rooms.find((x) => x.id === pid(ctx)) ?? fail(404, 'Room not found.');
  if (typeof ctx.body.name === 'string') r.name = ctx.body.name;
  if (has(ctx, 'floor')) r.floor = (ctx.body.floor as string | null) ?? null;
  audit(ctx, 'room.update', 'room', r.id, null, ctx.body);
  return roomOut(ctx.db, r);
});
route('DELETE', '/rooms/:id', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Deleting a room');
  const id = pid(ctx);
  if (ctx.db.racks.some((r) => r.room_id === id)) fail(409, 'The room still has racks. Remove them first.');
  ctx.db.rooms = ctx.db.rooms.filter((r) => r.id !== id);
  audit(ctx, 'room.delete', 'room', id, null, null);
});

route('GET', '/racks', (ctx) => {
  const siteId = qInt(ctx, 'site_id');
  const roomId = qInt(ctx, 'room_id');
  return page(
    ctx,
    ctx.db.racks
      .map((r) => rackOut(ctx.db, r))
      .filter(
        (r) =>
          canSee(ctx, r.site_id) &&
          (siteId === undefined || r.site_id === siteId) &&
          (roomId === undefined || r.room_id === roomId),
      ),
  );
});

route('GET', '/racks/:id', (ctx): RackDetail => {
  const db = ctx.db;
  const r = db.racks.find((x) => x.id === pid(ctx));
  if (!r) return fail(404, 'Rack not found.');
  const room = roomOf(db, r.room_id)!;
  const s = site(db, room.site_id);
  if (!canSee(ctx, s.id)) return fail(404, 'Rack not found.');
  const servers = rackServers(db, r);
  const summary = rackSummary(db, r, ctx.now);
  const rs: RackServer[] = servers
    .sort((a, b) => b.position_u - a.position_u)
    .map((x) => {
      const alerts = db.alerts.filter((a) => unresolved(a) && a.server?.id === x.id);
      return {
        id: x.id,
        name: x.name,
        bmc_host: x.bmc_host,
        vendor: x.vendor,
        model: x.model,
        position_u: x.position_u,
        height_u: x.height_u,
        status: x.status,
        health: serverHealth(x),
        inlet_temp: readingValue(db, x, 'inlet_temp_c', ctx.now),
        power: readingValue(db, x, 'power_w', ctx.now),
        open_alerts: alerts.length,
        worst_alert_severity: alerts.some((a) => a.severity === 'Critical')
          ? 'Critical'
          : alerts.some((a) => a.severity === 'Warning')
            ? 'Warning'
            : alerts.length
              ? 'Info'
              : null,
      };
    });
  return {
    id: r.id,
    name: r.name,
    row: r.row,
    height_u: r.height_u,
    power_capacity_w: r.power_capacity_w,
    site: siteRef(s),
    room: { id: room.id, name: room.name },
    used_u: summary.used_u,
    free_u: r.height_u - summary.used_u,
    power_w: summary.power_w ?? null,
    worst_health: summary.worst_health,
    servers: rs,
  };
});

route('POST', '/racks', (ctx) => {
  requireRole(ctx, 'dc_engineer', 'Creating a rack');
  const roomId = num(ctx, 'room_id');
  if (!roomId || !roomOf(ctx.db, roomId)) invalid('room_id', 'Unknown room.');
  const r: DemoRack = {
    id: ctx.db.nextId(),
    room_id: roomId!,
    name: (str(ctx, 'name') ?? '').trim() || 'R-new',
    row: str(ctx, 'row') ?? null,
    height_u: num(ctx, 'height_u') ?? 42,
    power_capacity_w: num(ctx, 'power_capacity_w') ?? null,
    inletOffset: 0,
  };
  ctx.db.racks.push(r);
  audit(ctx, 'rack.create', 'rack', r.id, null, { name: r.name });
  return rackOut(ctx.db, r);
});
route('PUT|PATCH', '/racks/:id', (ctx) => {
  requireRole(ctx, 'dc_engineer', 'Changing a rack');
  const r = ctx.db.racks.find((x) => x.id === pid(ctx)) ?? fail(404, 'Rack not found.');
  if (typeof ctx.body.name === 'string') r.name = ctx.body.name;
  if (has(ctx, 'row')) r.row = (ctx.body.row as string | null) ?? null;
  if (typeof ctx.body.height_u === 'number') r.height_u = ctx.body.height_u;
  if (has(ctx, 'power_capacity_w')) r.power_capacity_w = (ctx.body.power_capacity_w as number | null) ?? null;
  if (typeof ctx.body.room_id === 'number') r.room_id = ctx.body.room_id;
  audit(ctx, 'rack.update', 'rack', r.id, null, ctx.body);
  return rackOut(ctx.db, r);
});
route('DELETE', '/racks/:id', (ctx) => {
  requireRole(ctx, 'dc_engineer', 'Deleting a rack');
  const id = pid(ctx);
  if (listed(ctx.db).some((s) => s.rack_id === id))
    fail(409, 'The rack still has servers. Move or decommission them first.');
  ctx.db.racks = ctx.db.racks.filter((r) => r.id !== id);
  audit(ctx, 'rack.delete', 'rack', id, null, null);
});

// ---------------------------------------------------------------------------------------------- servers

function serverFilter(ctx: Ctx) {
  const f = {
    site_id: qInt(ctx, 'site_id'),
    room_id: qInt(ctx, 'room_id'),
    rack_id: qInt(ctx, 'rack_id'),
    collector_id: qInt(ctx, 'collector_id'),
    vendor: qStr(ctx, 'vendor'),
    model: qStr(ctx, 'model'),
    health: qStr(ctx, 'health'),
    status: qStr(ctx, 'status'),
    q: qStr(ctx, 'q'),
  };
  const ids = qList(ctx, 'site_id').map(Number);
  return ctx.db.servers.filter(
    (s) =>
      canSee(ctx, s.site_id) &&
      (f.status ? s.status === f.status : s.status !== 'decommissioned') &&
      (ids.length <= 1 ? f.site_id === undefined || s.site_id === f.site_id : ids.includes(s.site_id)) &&
      (f.room_id === undefined || s.room_id === f.room_id) &&
      (f.rack_id === undefined || s.rack_id === f.rack_id) &&
      (f.collector_id === undefined || s.collector_id === f.collector_id) &&
      (!f.vendor || s.vendor === f.vendor) &&
      (!f.model || s.model === f.model) &&
      (!f.health || serverHealth(s) === f.health) &&
      (!f.q || like([s.name, s.serial, s.bmc_host, s.asset_tag, s.hostname], f.q)),
  );
}

function sortServers(db: DemoDb, list: ServerListItem[], sort: string | undefined): ServerListItem[] {
  const desc = sort?.startsWith('-') ?? false;
  const key = sort?.replace(/^-/, '') ?? 'name';
  const val = (s: ServerListItem): string | number => {
    switch (key) {
      case 'health':
        return HEALTH_RANK[s.health];
      case 'site':
        return `${s.site.code}|${s.rack?.name ?? ''}|${String(99 - (s.position_u ?? 0)).padStart(2, '0')}`;
      case 'rack':
        return `${s.rack?.name ?? ''}|${String(99 - (s.position_u ?? 0)).padStart(2, '0')}`;
      case 'vendor':
        return `${s.vendor ?? ''}|${s.name}`;
      case 'model':
        return `${s.model ?? ''}|${s.name}`;
      case 'last_seen':
        return s.last_seen_at ?? '';
      case 'id':
        return s.id;
      default:
        return s.name;
    }
  };
  void db;
  return [...list].sort((a, b) => {
    const x = val(a);
    const y = val(b);
    const c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y));
    return desc ? -c : c;
  });
}

route('GET', '/servers', (ctx) =>
  page(
    ctx,
    sortServers(
      ctx.db,
      serverFilter(ctx).map((s) => serverListItem(ctx.db, s, ctx.now)),
      qStr(ctx, 'sort'),
    ),
  ),
);

const csvCell = (v: unknown) => {
  const s =
    typeof v === 'string'
      ? v
      : typeof v === 'number' || typeof v === 'boolean'
        ? String(v)
        : v === null || v === undefined
          ? ''
          : JSON.stringify(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};
const csv = (header: string[], rows: unknown[][], filename: string) =>
  raw({
    status: 200,
    contentType: 'text/csv; charset=utf-8',
    headers: { 'Content-Disposition': `attachment; filename="${filename}"` },
    body: [header, ...rows].map((r) => r.map(csvCell).join(',')).join('\n') + '\n',
  });

route('GET', '/servers/export.csv', (ctx) => {
  const rows = sortServers(
    ctx.db,
    serverFilter(ctx).map((s) => serverListItem(ctx.db, s, ctx.now)),
    qStr(ctx, 'sort'),
  );
  return csv(
    [
      'id',
      'name',
      'site',
      'room',
      'rack',
      'position_u',
      'height_u',
      'vendor',
      'model',
      'serial',
      'asset_tag',
      'bmc_host',
      'status',
      'health',
      'open_alerts',
      'last_seen_at',
    ],
    rows.map((s) => [
      s.id,
      s.name,
      s.site.code,
      s.room?.name,
      s.rack?.name,
      s.position_u,
      s.height_u,
      s.vendor,
      s.model,
      s.serial,
      s.asset_tag,
      s.bmc_host,
      s.status,
      s.health,
      s.open_alerts,
      s.last_seen_at,
    ]),
    'servers-demo.csv',
  );
});

function serverById(ctx: Ctx, key = 'id'): DemoServer {
  const s = ctx.db.servers.find((x) => x.id === pid(ctx, key));
  if (!s || !canSee(ctx, s.site_id)) return fail(404, 'Server not found.');
  return s;
}

route('GET', '/servers/:id', (ctx) => serverDetail(ctx.db, serverById(ctx), ctx.now));

route('GET', '/servers/:id/readings', (ctx): Readings => {
  const db = ctx.db;
  const s = serverById(ctx);
  const metric = qStr(ctx, 'metric') ?? fail(422, 'metric is required.');
  const def = db.metrics.find((m) => m.code === metric) ?? fail(422, `Unknown metric ${metric}.`);
  const end = qStr(ctx, 'to') ? Date.parse(qStr(ctx, 'to')!) : ctx.now;
  const start = qStr(ctx, 'from') ? Date.parse(qStr(ctx, 'from')!) : end - 86_400_000;
  const span = end - start;
  const resolution: Readings['resolution'] =
    span <= 6 * 3_600_000 ? 'raw' : span <= 8 * 86_400_000 ? '5m' : '1h';
  let step = resolution === 'raw' ? Math.max(60, def.interval_s) : resolution === '5m' ? 300 : 3600;
  step = Math.max(step, qInt(ctx, 'step') ?? 0);
  while (span / (step * 1000) > 1500) step *= 2;
  const component = qStr(ctx, 'component');
  const comps = [
    ...new Set(
      readingKeys(s)
        .filter(([m, c]) => m === metric && (component === undefined || c === component))
        .map(([, c]) => c),
    ),
  ];
  const from = Math.max(start, Date.parse(s.discovered_at));
  const first = Math.ceil(from / (step * 1000)) * step * 1000;
  const series = comps.map((c) => {
    const points: Readings['series'][number]['points'] = [];
    for (let t = first; t <= end; t += step * 1000) {
      if (resolution === 'raw') {
        const v = sensorValue(db, s, metric, c, t);
        if (v !== null) points.push({ t: iso(t), v });
      } else {
        const samples = [0, 0.25, 0.5, 0.75]
          .map((f) => sensorValue(db, s, metric, c, t + f * step * 1000))
          .filter((v): v is number => v !== null);
        if (!samples.length) continue;
        const avg = samples.reduce((a, b) => a + b, 0) / samples.length;
        points.push({
          t: iso(t),
          v: Math.round(avg * 10) / 10,
          min: Math.min(...samples),
          max: Math.max(...samples),
        });
      }
    }
    return { component: c, points };
  });
  return {
    server_id: s.id,
    metric,
    metric_name: def.name,
    unit: def.unit,
    type: def.type,
    start: iso(start),
    end: iso(end),
    resolution,
    step_s: step,
    series,
  };
});

route('GET', '/servers/:id/events', (ctx) => {
  const s = serverById(ctx);
  const severity = qStr(ctx, 'severity');
  const q = qStr(ctx, 'q');
  return page(
    ctx,
    s.events.filter(
      (e) => (!severity || e.severity === severity) && (!q || like([e.message, e.message_id], q)),
    ),
  );
});

const VENDOR_BY_HASH = [
  ['Dell', 'PowerEdge R750', 'iDRAC9'],
  ['HPE', 'ProLiant DL380 Gen10', 'iLO 5'],
  ['Lenovo', 'ThinkSystem SR650', 'XClarity Controller'],
] as const;

route('POST', '/servers', (ctx) => {
  requireRole(ctx, 'dc_engineer', 'Onboarding a server');
  const db = ctx.db;
  const bmc = (str(ctx, 'bmc_host') ?? '').trim();
  if (!bmc) invalid('bmc_host', 'Enter the BMC address.');
  if (db.servers.some((s) => s.bmc_host === bmc && s.status !== 'decommissioned'))
    fail(409, 'A server with that BMC address is already onboarded.');
  const rack = rackOf(db, num(ctx, 'rack_id') ?? null) ?? invalid('rack_id', 'Choose a rack.');
  const room = roomOf(db, rack.room_id)!;
  const position = num(ctx, 'position_u') ?? invalid('position_u', 'Enter the position.');
  const height = num(ctx, 'height_u') ?? 2;
  const clash = rackServers(db, rack).find(
    (s) => position < s.position_u + s.height_u && s.position_u < position + height,
  );
  if (clash) invalid('position_u', `U${position} overlaps ${clash.name} (U${clash.position_u}).`);
  // "Discovery": the template server of the same vendor provides parts and firmware.
  const [vendor, model, bmcModel] = VENDOR_BY_HASH[Math.abs(strHash(bmc)) % VENDOR_BY_HASH.length]!;
  const template = db.servers.find((s) => s.model === model) ?? db.servers[0]!;
  const id = Math.max(...db.servers.map((s) => s.id)) + 1;
  const name =
    (str(ctx, 'name') ?? '').trim() ||
    `${site(db, room.site_id).code.toLowerCase()}-new${String(id).padStart(3, '0')}.demo.local`;
  const s: DemoServer = {
    ...template,
    id,
    name,
    hostname: name,
    bmc_host: bmc,
    vendor,
    model,
    bmc_model: bmcModel,
    serial: `DEMO${String(id).padStart(4, '0')}`,
    asset_tag: str(ctx, 'asset_tag') ?? null,
    status: (str(ctx, 'status') as DemoServer['status'] | undefined) ?? 'active',
    site_id: room.site_id,
    room_id: room.id,
    rack_id: rack.id,
    position_u: position,
    height_u: height,
    collector_id:
      num(ctx, 'collector_id') ?? db.collectors.find((c) => c.site_id === room.site_id)?.id ?? null,
    notes: str(ctx, 'notes') ?? null,
    discovered_at: iso(ctx.now - 30_000),
    created_at: iso(ctx.now - 60_000),
    updated_at: iso(ctx.now),
    seed: Math.floor(hash01(id, 7) * 1e6),
    components: template.components.map((c) => ({
      ...c,
      id: db.nextId(),
      server_id: id,
      first_seen_at: iso(ctx.now - 30_000),
      last_seen_at: iso(ctx.now),
    })),
    firmware: template.firmware.map((f) => ({ ...f })),
    faults: {},
    inletBoost: 0,
    slowFan: null,
    failedPsu: null,
    unreachableSince: null,
    poweredOff: false,
    events: [
      {
        id: db.nextId(),
        server_id: id,
        time: iso(ctx.now - 20_000),
        severity: 'OK',
        message: 'The system inventory was updated successfully.',
        message_id: 'SYS1003',
        entry_id: 'Sel/1',
      },
    ],
  };
  db.servers.push(s);
  audit(ctx, 'server.create', 'server', s.id, null, {
    name: s.name,
    bmc_host: s.bmc_host,
    rack_id: rack.id,
    position_u: position,
  });
  return serverDetail(db, s, ctx.now);
});

route('PUT|PATCH', '/servers/:id', (ctx) => {
  requireRole(ctx, 'dc_engineer', 'Changing a server');
  const s = serverById(ctx);
  const before = { rack_id: s.rack_id, position_u: s.position_u, status: s.status, name: s.name };
  if (typeof ctx.body.rack_id === 'number') {
    const rack = rackOf(ctx.db, ctx.body.rack_id) ?? invalid('rack_id', 'Unknown rack.');
    s.rack_id = rack.id;
    s.room_id = rack.room_id;
    s.site_id = roomOf(ctx.db, rack.room_id)!.site_id;
  }
  if (typeof ctx.body.position_u === 'number') s.position_u = ctx.body.position_u;
  if (typeof ctx.body.height_u === 'number') s.height_u = ctx.body.height_u;
  if (typeof ctx.body.status === 'string') s.status = ctx.body.status as DemoServer['status'];
  if (typeof ctx.body.name === 'string' && ctx.body.name.trim()) s.name = ctx.body.name.trim();
  if (has(ctx, 'asset_tag')) s.asset_tag = (ctx.body.asset_tag as string | null) ?? null;
  if (has(ctx, 'collector_id')) s.collector_id = (ctx.body.collector_id as number | null) ?? null;
  if (has(ctx, 'notes')) s.notes = (ctx.body.notes as string | null) ?? null;
  s.updated_at = iso(ctx.now);
  audit(ctx, 'server.update', 'server', s.id, before, ctx.body);
  return serverDetail(ctx.db, s, ctx.now);
});

route('DELETE', '/servers/:id', (ctx) => {
  requireRole(ctx, 'dc_engineer', 'Decommissioning a server');
  const s = serverById(ctx);
  s.status = 'decommissioned';
  for (const a of ctx.db.alerts.filter((x) => unresolved(x) && x.server?.id === s.id)) {
    a.state = 'resolved';
    a.resolved_at = iso(ctx.now);
    a.resolved_by = 'system';
  }
  audit(ctx, 'server.decommission', 'server', s.id, { status: 'active' }, { status: 'decommissioned' });
});

// ---------------------------------------------------------------------------------------------- components

function componentFilter(ctx: Ctx): ComponentListItem[] {
  const db = ctx.db;
  const siteId = qInt(ctx, 'site_id');
  const serverId = qInt(ctx, 'server_id');
  const type = qStr(ctx, 'type');
  const model = qStr(ctx, 'model');
  const manufacturer = qStr(ctx, 'manufacturer');
  const q = qStr(ctx, 'q');
  const out: ComponentListItem[] = [];
  for (const s of listed(db)) {
    if (
      !canSee(ctx, s.site_id) ||
      (siteId !== undefined && s.site_id !== siteId) ||
      (serverId !== undefined && s.id !== serverId)
    )
      continue;
    const st = site(db, s.site_id);
    for (const c of s.components) {
      if (
        (type && c.type !== type) ||
        (model && c.model !== model) ||
        (manufacturer && c.manufacturer !== manufacturer)
      )
        continue;
      if (q && !like([c.name, c.model, c.serial, c.manufacturer, s.name], q)) continue;
      out.push({ ...c, server_name: s.name, site_id: st.id, site_code: st.code });
    }
  }
  return out;
}

route('GET', '/components', (ctx) => page(ctx, componentFilter(ctx)));
route('GET', '/components/export.csv', (ctx) =>
  csv(
    [
      'id',
      'server',
      'site',
      'type',
      'name',
      'model',
      'manufacturer',
      'serial',
      'capacity',
      'capacity_unit',
      'firmware_version',
      'location',
    ],
    componentFilter(ctx).map((c) => [
      c.id,
      c.server_name,
      c.site_code,
      c.type,
      c.name,
      c.model,
      c.manufacturer,
      c.serial,
      c.capacity,
      c.capacity_unit,
      c.firmware_version,
      c.location,
    ]),
    'components-demo.csv',
  ),
);

// ---------------------------------------------------------------------------------------------- alerts

function alertFilter(ctx: Ctx): AlertDetail[] {
  const states = qList(ctx, 'state');
  const severities = qList(ctx, 'severity');
  const siteIds = qList(ctx, 'site_id').map(Number);
  const serverId = qInt(ctx, 'server_id');
  const ruleId = qInt(ctx, 'rule_id');
  const muted = qBool(ctx, 'muted');
  const from = qStr(ctx, 'from');
  const to = qStr(ctx, 'to');
  const q = qStr(ctx, 'q');
  return ctx.db.alerts.filter(
    (a) =>
      canSee(ctx, a.site?.id ?? null) &&
      (!states.length || states.includes(a.state)) &&
      (!severities.length || severities.includes(a.severity)) &&
      (!siteIds.length || (a.site !== null && siteIds.includes(a.site.id))) &&
      (serverId === undefined || a.server?.id === serverId) &&
      (ruleId === undefined || a.rule.id === ruleId) &&
      (muted === undefined || a.muted === muted) &&
      (!from || Date.parse(a.opened_at) >= Date.parse(from)) &&
      (!to || Date.parse(a.opened_at) < Date.parse(to)) &&
      (!q || like([a.title, a.message, a.server?.name, a.component], q)),
  );
}

route('GET', '/alerts', (ctx) => page(ctx, alertFilter(ctx).map(stripActivity)));

function alertById(ctx: Ctx): AlertDetail {
  const a = ctx.db.alerts.find((x) => x.id === pid(ctx));
  if (!a || !canSee(ctx, a.site?.id ?? null)) return fail(404, 'Alert not found.');
  return a;
}

route('GET', '/alerts/:id', (ctx) => alertById(ctx));

function activity(
  ctx: Ctx,
  a: AlertDetail,
  action: string,
  from: string | null,
  to: string | null,
  note: string | null,
) {
  a.activity.unshift({
    id: ctx.db.nextId(),
    time: iso(ctx.now),
    actor: ctx.user?.name ?? 'demo user',
    action,
    from_state: from,
    to_state: to,
    note,
    details: {},
  });
}

route('POST', '/alerts/:id/ack', (ctx) => {
  requireRole(ctx, 'noc_operator', 'Acknowledging alerts');
  const a = alertById(ctx);
  if (a.state !== 'open') fail(409, `The alert is ${a.state}.`);
  const note = str(ctx, 'note')?.trim() || null;
  a.state = 'acknowledged';
  a.acked_at = iso(ctx.now);
  a.acked_by = ctx.user?.name ?? 'demo user';
  activity(ctx, a, 'acknowledged', 'open', 'acknowledged', note);
  audit(ctx, 'alert.ack', 'alert', a.id, { state: 'open' }, { state: 'acknowledged', note });
  return a;
});

route('POST', '/alerts/:id/comments', (ctx) => {
  requireRole(ctx, 'noc_operator', 'Commenting on alerts');
  const a = alertById(ctx);
  const note = str(ctx, 'note')?.trim();
  if (!note) invalid('note', 'Write a comment.');
  activity(ctx, a, 'commented', null, null, note!);
  audit(ctx, 'alert.comment', 'alert', a.id, null, { note });
  return a;
});

route('POST', '/alerts/:id/resolve', (ctx) => {
  requireRole(ctx, 'noc_operator', 'Resolving alerts');
  const a = alertById(ctx);
  if (!a.manually_resolvable) fail(409, 'This alert resolves on its own when the reading is back to normal.');
  if (a.state === 'resolved') fail(409, 'The alert is already resolved.');
  const note = str(ctx, 'note')?.trim() || null;
  const from = a.state;
  a.state = 'resolved';
  a.resolved_at = iso(ctx.now);
  a.resolved_by = ctx.user?.name ?? 'demo user';
  activity(ctx, a, 'resolved', from, 'resolved', note);
  audit(ctx, 'alert.resolve', 'alert', a.id, { state: from }, { state: 'resolved', note });
  return a;
});

// ---------------------------------------------------------------------------------------------- rules, thresholds, routes

route('GET', '/alert-rules', (ctx) => {
  const type = qStr(ctx, 'rule_type');
  const metric = qStr(ctx, 'metric');
  const enabled = qBool(ctx, 'enabled');
  return page(
    ctx,
    ctx.db.rules.filter(
      (r) =>
        (!type || r.rule_type === type) &&
        (!metric || r.metric === metric) &&
        (enabled === undefined || r.enabled === enabled),
    ),
  );
});
route(
  'GET',
  '/alert-rules/:id',
  (ctx) => ctx.db.rules.find((r) => r.id === pid(ctx)) ?? fail(404, 'Rule not found.'),
);

function applyRule(ctx: Ctx, r: AlertRule, body: Record<string, unknown>) {
  for (const k of ['name', 'description', 'severity', 'route'] as const)
    if (typeof body[k] === 'string') r[k] = body[k];
  if (typeof body.duration_s === 'number') r.duration_s = body.duration_s;
  if (typeof body.enabled === 'boolean') r.enabled = body.enabled;
  if (body.condition && typeof body.condition === 'object')
    r.condition = body.condition as Record<string, unknown>;
  r.updated_by = ctx.user?.name ?? 'demo user';
  r.updated_at = iso(ctx.now);
}

route('POST', '/alert-rules', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Adding alert rules');
  const name = (str(ctx, 'name') ?? '').trim();
  if (!name) invalid('name', 'Give the rule a name.');
  const r: AlertRule = {
    id: ctx.db.nextId(),
    name,
    description: str(ctx, 'description') ?? '',
    rule_type: str(ctx, 'rule_type') ?? 'threshold',
    metric: (ctx.body.metric as string | null) ?? null,
    condition: {},
    duration_s: 0,
    severity: 'Warning',
    route: 'hardware',
    enabled: true,
    builtin: false,
    updated_by: null,
    updated_at: iso(ctx.now),
  };
  applyRule(ctx, r, ctx.body);
  ctx.db.rules.push(r);
  audit(ctx, 'alert_rule.create', 'alert_rule', r.id, null, { name: r.name });
  return r;
});
route('PUT', '/alert-rules', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Changing alert rules');
  const items = Array.isArray(ctx.body.items) ? (ctx.body.items as Record<string, unknown>[]) : [];
  const changed = items.map((it) => {
    const r = ctx.db.rules.find((x) => x.id === it.id) ?? fail(404, `Rule ${String(it.id)} not found.`);
    applyRule(ctx, r, it);
    return r;
  });
  audit(ctx, 'alert_rule.bulk_update', 'alert_rule', null, null, { count: changed.length });
  return { items: changed, next_cursor: null };
});
route('PUT|PATCH', '/alert-rules/:id', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Changing alert rules');
  const r = ctx.db.rules.find((x) => x.id === pid(ctx)) ?? fail(404, 'Rule not found.');
  const before = { enabled: r.enabled, severity: r.severity, duration_s: r.duration_s };
  applyRule(ctx, r, ctx.body);
  audit(ctx, 'alert_rule.update', 'alert_rule', r.id, before, ctx.body);
  return r;
});
route('DELETE', '/alert-rules/:id', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Deleting alert rules');
  const r = ctx.db.rules.find((x) => x.id === pid(ctx)) ?? fail(404, 'Rule not found.');
  if (r.builtin) fail(409, 'Built-in rules can be disabled but not deleted.');
  ctx.db.rules = ctx.db.rules.filter((x) => x.id !== r.id);
  audit(ctx, 'alert_rule.delete', 'alert_rule', r.id, { name: r.name }, null);
});

const BMC_LIMITS: Record<string, [number | null, number | null, number | null, number | null]> = {
  exhaust_temp_c: [null, null, 70, 75],
  cpu_temp_c: [null, null, 90, 95],
  dimm_temp_c: [null, null, 85, 90],
  fan_rpm: [1500, 2500, null, null],
};

function thresholdsFor(db: DemoDb, s: DemoServer) {
  return db.thresholds.filter(
    (t) =>
      t.scope === 'global' ||
      (t.scope === 'site' && t.site_id === s.site_id) ||
      (t.scope === 'model' && t.model === s.model && (!t.vendor || t.vendor === s.vendor)) ||
      (t.scope === 'server' && t.server_id === s.id),
  );
}

function effectiveLimits(
  db: DemoDb,
  s: DemoServer,
  now: number,
): { effective: EffectiveLimit[]; bmc: NonNullable<ThresholdPage['bmc_limits']> } {
  const order = ['server', 'site', 'model', 'global'] as const;
  const applicable = thresholdsFor(db, s);
  const effective: EffectiveLimit[] = [];
  const bmc: NonNullable<ThresholdPage['bmc_limits']> = [];
  const keys = readingKeys(s).filter(([m]) =>
    [
      'inlet_temp_c',
      'exhaust_temp_c',
      'cpu_temp_c',
      'dimm_temp_c',
      'fan_rpm',
      'power_w',
      'psu_input_v',
      'drive_life_pct',
    ].includes(m),
  );
  for (const [metric, component] of keys) {
    const limits = BMC_LIMITS[metric];
    if (limits)
      bmc.push({
        metric,
        component,
        lower_critical: limits[0],
        lower_warning: limits[1],
        upper_warning: limits[2],
        upper_critical: limits[3],
        updated_at: s.discovered_at,
      });
    const t = order.map((sc) => applicable.find((x) => x.metric === metric && x.scope === sc)).find(Boolean);
    if (t)
      effective.push({
        metric,
        component,
        source: t.scope as EffectiveLimit['source'],
        threshold_id: t.id,
        direction: t.direction,
        warning: t.warning,
        critical: t.critical,
        nominal: t.nominal,
      });
    else if (limits)
      effective.push(
        limits[2] !== null
          ? {
              metric,
              component,
              source: 'bmc',
              threshold_id: null,
              direction: 'above',
              warning: limits[2],
              critical: limits[3],
            }
          : {
              metric,
              component,
              source: 'bmc',
              threshold_id: null,
              direction: 'below',
              warning: limits[1],
              critical: limits[0],
              lower_warning: limits[1],
              lower_critical: limits[0],
            },
      );
  }
  void now;
  return { effective, bmc };
}

route('GET', '/thresholds', (ctx): ThresholdPage => {
  const db = ctx.db;
  const metric = qStr(ctx, 'metric');
  const scope = qStr(ctx, 'scope');
  const siteId = qInt(ctx, 'site_id');
  const serverId = qInt(ctx, 'server_id');
  const model = qStr(ctx, 'model');
  if (serverId !== undefined) {
    const s = db.servers.find((x) => x.id === serverId) ?? fail(404, 'Server not found.');
    const items = thresholdsFor(db, s).filter((t) => !metric || t.metric === metric);
    const { effective, bmc } = effectiveLimits(db, s, ctx.now);
    return {
      items,
      next_cursor: null,
      bmc_limits: bmc.filter((b) => !metric || b.metric === metric),
      effective: effective.filter((e) => !metric || e.metric === metric),
    };
  }
  return page(
    ctx,
    db.thresholds.filter(
      (t) =>
        (!metric || t.metric === metric) &&
        (!scope || t.scope === scope) &&
        (siteId === undefined || t.site_id === siteId) &&
        (!model || t.model === model),
    ),
  );
});

function thresholdFromBody(ctx: Ctx, body: Record<string, unknown>): Threshold {
  const metric = bodyStr(body, 'metric', '');
  const def = ctx.db.metrics.find((m) => m.code === metric) ?? invalid('metric', 'Unknown metric.');
  const scope = bodyStr(body, 'scope', 'global');
  if (scope === 'global') unrestricted(ctx, 'A global threshold');
  return {
    id: ctx.db.nextId(),
    metric,
    metric_name: def.name,
    unit: def.unit,
    scope,
    site_id: (body.site_id as number | null) ?? null,
    server_id: (body.server_id as number | null) ?? null,
    vendor: (body.vendor as string | null) ?? null,
    model: (body.model as string | null) ?? null,
    direction: bodyStr(body, 'direction', 'above'),
    warning: (body.warning as number | null) ?? null,
    critical: (body.critical as number | null) ?? null,
    nominal: (body.nominal as number | null) ?? null,
    updated_by: ctx.user?.name ?? 'demo user',
    updated_at: iso(ctx.now),
  };
}

route('POST', '/thresholds', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Adding thresholds');
  const t = thresholdFromBody(ctx, ctx.body);
  if (
    ctx.db.thresholds.some(
      (x) =>
        x.metric === t.metric &&
        x.scope === t.scope &&
        x.site_id === t.site_id &&
        x.server_id === t.server_id &&
        x.model === t.model,
    )
  )
    fail(409, 'An override for that metric and scope already exists.');
  ctx.db.thresholds.push(t);
  audit(ctx, 'threshold.create', 'threshold', t.id, null, {
    metric: t.metric,
    scope: t.scope,
    warning: t.warning,
    critical: t.critical,
  });
  return t;
});
route('PUT', '/thresholds', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Changing thresholds');
  const items = Array.isArray(ctx.body.items) ? (ctx.body.items as Record<string, unknown>[]) : [];
  const out = items.map((it) => {
    const t = thresholdFromBody(ctx, it);
    const existing = ctx.db.thresholds.find(
      (x) =>
        x.metric === t.metric &&
        x.scope === t.scope &&
        x.site_id === t.site_id &&
        x.server_id === t.server_id &&
        x.model === t.model,
    );
    if (existing)
      return Object.assign(existing, {
        direction: t.direction,
        warning: t.warning,
        critical: t.critical,
        nominal: t.nominal,
        updated_by: t.updated_by,
        updated_at: t.updated_at,
      });
    ctx.db.thresholds.push(t);
    return t;
  });
  audit(ctx, 'threshold.bulk_update', 'threshold', null, null, { count: out.length });
  return { items: out, next_cursor: null };
});
route('PUT|PATCH', '/thresholds/:id', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Changing thresholds');
  const t = ctx.db.thresholds.find((x) => x.id === pid(ctx)) ?? fail(404, 'Threshold not found.');
  if (t.scope === 'global') unrestricted(ctx, 'A global threshold');
  const before = { warning: t.warning, critical: t.critical, direction: t.direction };
  if (typeof ctx.body.direction === 'string') t.direction = ctx.body.direction;
  for (const k of ['warning', 'critical', 'nominal'] as const)
    if (has(ctx, k)) t[k] = (ctx.body[k] as number | null) ?? null;
  t.updated_by = ctx.user?.name ?? 'demo user';
  t.updated_at = iso(ctx.now);
  audit(ctx, 'threshold.update', 'threshold', t.id, before, {
    warning: t.warning,
    critical: t.critical,
    direction: t.direction,
  });
  return t;
});
route('DELETE', '/thresholds/:id', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Removing thresholds');
  const t = ctx.db.thresholds.find((x) => x.id === pid(ctx)) ?? fail(404, 'Threshold not found.');
  if (t.scope === 'global') fail(409, 'Global defaults can be changed but not removed.');
  ctx.db.thresholds = ctx.db.thresholds.filter((x) => x.id !== t.id);
  audit(ctx, 'threshold.delete', 'threshold', t.id, { metric: t.metric, scope: t.scope }, null);
});

function maskTarget(channel: string, target: string): string {
  if (channel === 'teams') return target.replace(/^(https:\/\/[^/]+\/).*(\/[^/]+)$/, '$1…$2');
  const list = target
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  const first = list[0] ?? '';
  const [u, d] = first.split('@');
  return `${(u ?? '').slice(0, 1)}***@${d ?? ''}${list.length > 1 ? ` +${list.length - 1}` : ''}`;
}

route('GET', '/alert-routes', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Viewing alert routes');
  const siteId = qInt(ctx, 'site_id');
  const channel = qStr(ctx, 'channel');
  return page(
    ctx,
    ctx.db.routes
      .filter(
        (r) =>
          canSee(ctx, r.site_id) &&
          (siteId === undefined || r.site_id === siteId) &&
          (!channel || r.channel === channel),
      )
      .sort((a, b) => a.name.localeCompare(b.name)),
  );
});
route(
  'GET',
  '/alert-routes/:id',
  (ctx) => ctx.db.routes.find((r) => r.id === pid(ctx)) ?? fail(404, 'Route not found.'),
);
route('POST', '/alert-routes', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Adding alert routes');
  const siteId = (ctx.body.site_id as number | null) ?? null;
  if (siteId === null) unrestricted(ctx, 'A route for all sites');
  const channel = str(ctx, 'channel') ?? 'email';
  const target = (str(ctx, 'target') ?? '').trim();
  if (target.length < 3) invalid('target', 'Enter a target.');
  const r: AlertRoute = {
    id: ctx.db.nextId(),
    name: str(ctx, 'name') ?? 'Route',
    route: str(ctx, 'route') ?? '*',
    site_id: siteId,
    min_severity: str(ctx, 'min_severity') ?? 'Critical',
    escalation_level: num(ctx, 'escalation_level') ?? 0,
    channel,
    target_hint: maskTarget(channel, target),
    enabled: ctx.body.enabled !== false,
    created_at: iso(ctx.now),
    updated_at: iso(ctx.now),
  };
  ctx.db.routes.push(r);
  ctx.db.routeTargets[r.id] = target;
  audit(ctx, 'alert_route.create', 'alert_route', r.id, null, { name: r.name, channel, site_id: siteId });
  return r;
});
route('PATCH|PUT', '/alert-routes/:id', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Changing alert routes');
  const r = ctx.db.routes.find((x) => x.id === pid(ctx)) ?? fail(404, 'Route not found.');
  const before = { name: r.name, enabled: r.enabled, min_severity: r.min_severity, channel: r.channel };
  const channel = str(ctx, 'channel') ?? r.channel;
  if (channel !== r.channel && !str(ctx, 'target')) fail(422, 'Changing the channel needs a new target.');
  for (const k of ['name', 'route', 'min_severity'] as const)
    if (typeof ctx.body[k] === 'string') r[k] = ctx.body[k];
  if (has(ctx, 'site_id')) r.site_id = (ctx.body.site_id as number | null) ?? null;
  if (typeof ctx.body.escalation_level === 'number') r.escalation_level = ctx.body.escalation_level;
  if (typeof ctx.body.enabled === 'boolean') r.enabled = ctx.body.enabled;
  r.channel = channel;
  const target = str(ctx, 'target')?.trim();
  if (target) {
    ctx.db.routeTargets[r.id] = target;
    r.target_hint = maskTarget(channel, target);
  }
  r.updated_at = iso(ctx.now);
  audit(ctx, 'alert_route.update', 'alert_route', r.id, before, {
    ...ctx.body,
    target: target ? '(changed)' : undefined,
  });
  return r;
});
route('DELETE', '/alert-routes/:id', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Removing alert routes');
  const id = pid(ctx);
  ctx.db.routes = ctx.db.routes.filter((r) => r.id !== id);
  audit(ctx, 'alert_route.delete', 'alert_route', id, null, null);
});

// ---------------------------------------------------------------------------------------------- maintenance, collectors

route('GET', '/maintenance-windows', (ctx) => {
  const db = ctx.db;
  const when = qStr(ctx, 'when') ?? 'current_and_upcoming';
  const siteId = qInt(ctx, 'site_id');
  const scope = qStr(ctx, 'scope');
  const serverId = qInt(ctx, 'server_id');
  const items = db.maintenance
    .map((m) => maintOut(db, m, ctx.now))
    .filter((m) => {
      const start = Date.parse(m.starts_at);
      const end = Date.parse(m.ends_at);
      const ok =
        when === 'active'
          ? m.active
          : when === 'upcoming'
            ? start > ctx.now
            : when === 'past'
              ? end <= ctx.now
              : end > ctx.now;
      return (
        ok &&
        canSee(ctx, m.target_site_id) &&
        (siteId === undefined || m.target_site_id === siteId) &&
        (!scope || m.scope === scope) &&
        (serverId === undefined || m.server_id === serverId)
      );
    })
    .sort((a, b) =>
      when === 'past'
        ? Date.parse(b.starts_at) - Date.parse(a.starts_at)
        : Date.parse(a.starts_at) - Date.parse(b.starts_at),
    );
  return page(ctx, items);
});
route('GET', '/maintenance-windows/:id', (ctx) =>
  maintOut(
    ctx.db,
    ctx.db.maintenance.find((m) => m.id === pid(ctx)) ?? fail(404, 'Window not found.'),
    ctx.now,
  ),
);
route('POST', '/maintenance-windows', (ctx) => {
  requireRole(ctx, 'dc_engineer', 'Scheduling maintenance');
  const scope = (str(ctx, 'scope') ?? 'server') as DemoMaintenance['scope'];
  const starts = str(ctx, 'starts_at');
  const ends = str(ctx, 'ends_at');
  if (!starts || Number.isNaN(Date.parse(starts))) invalid('starts_at', 'Enter a start.');
  if (!ends || Date.parse(ends) <= Date.parse(starts!))
    invalid('ends_at', 'The end must be after the start.');
  const m: DemoMaintenance = {
    id: ctx.db.nextId(),
    scope,
    site_id: scope === 'site' ? (num(ctx, 'site_id') ?? null) : null,
    rack_id: scope === 'rack' ? (num(ctx, 'rack_id') ?? null) : null,
    server_id: scope === 'server' ? (num(ctx, 'server_id') ?? null) : null,
    starts_at: new Date(starts!).toISOString(),
    ends_at: new Date(ends!).toISOString(),
    reason: str(ctx, 'reason') ?? '',
    created_by: ctx.user?.name ?? 'demo user',
    created_at: iso(ctx.now),
  };
  if (
    (scope === 'site' && !m.site_id) ||
    (scope === 'rack' && !m.rack_id) ||
    (scope === 'server' && !m.server_id)
  )
    invalid(`${scope}_id`, `Choose a ${scope}.`);
  ctx.db.maintenance.push(m);
  audit(ctx, 'maintenance.create', 'maintenance_window', m.id, null, { scope, reason: m.reason });
  return maintOut(ctx.db, m, ctx.now);
});
route('PATCH|PUT', '/maintenance-windows/:id', (ctx) => {
  requireRole(ctx, 'dc_engineer', 'Changing maintenance');
  const m = ctx.db.maintenance.find((x) => x.id === pid(ctx)) ?? fail(404, 'Window not found.');
  if (str(ctx, 'starts_at')) m.starts_at = new Date(str(ctx, 'starts_at')!).toISOString();
  if (str(ctx, 'ends_at')) m.ends_at = new Date(str(ctx, 'ends_at')!).toISOString();
  if (typeof ctx.body.reason === 'string') m.reason = ctx.body.reason;
  audit(ctx, 'maintenance.update', 'maintenance_window', m.id, null, ctx.body);
  return maintOut(ctx.db, m, ctx.now);
});
route('DELETE', '/maintenance-windows/:id', (ctx) => {
  requireRole(ctx, 'dc_engineer', 'Cancelling maintenance');
  const id = pid(ctx);
  ctx.db.maintenance = ctx.db.maintenance.filter((m) => m.id !== id);
  audit(ctx, 'maintenance.delete', 'maintenance_window', id, null, null);
});

route('GET', '/collectors', (ctx) => {
  const siteId = qInt(ctx, 'site_id');
  return page(
    ctx,
    ctx.db.collectors
      .filter((c) => canSee(ctx, c.site_id) && (siteId === undefined || c.site_id === siteId))
      .map((c) => collectorOut(ctx.db, c, ctx.now)),
  );
});
route('GET', '/collectors/:id', (ctx) =>
  collectorOut(
    ctx.db,
    ctx.db.collectors.find((c) => c.id === pid(ctx)) ?? fail(404, 'Collector not found.'),
    ctx.now,
  ),
);
route('POST', '/collectors', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Registering collectors');
  const name = (str(ctx, 'name') ?? '').trim();
  if (ctx.db.collectors.some((c) => c.name === name)) fail(409, 'A collector with that name already exists.');
  const c = {
    id: ctx.db.nextId(),
    site_id: num(ctx, 'site_id') ?? invalid('site_id', 'Choose a site.'),
    name,
    version: null,
    hostname: null,
    enabled: ctx.body.enabled !== false,
    heartbeatAgeS: null,
    cert_fingerprint: (ctx.body.cert_fingerprint as string | null) ?? null,
    created_at: iso(ctx.now),
  };
  ctx.db.collectors.push(c);
  audit(ctx, 'collector.create', 'collector', c.id, null, { name });
  return collectorOut(ctx.db, c, ctx.now);
});
route('PATCH|PUT', '/collectors/:id', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Changing collectors');
  const c = ctx.db.collectors.find((x) => x.id === pid(ctx)) ?? fail(404, 'Collector not found.');
  const before = { enabled: c.enabled, cert_fingerprint: c.cert_fingerprint };
  if (typeof ctx.body.enabled === 'boolean') c.enabled = ctx.body.enabled;
  if (has(ctx, 'cert_fingerprint')) c.cert_fingerprint = (ctx.body.cert_fingerprint as string | null) ?? null;
  audit(ctx, 'collector.update', 'collector', c.id, before, ctx.body);
  return collectorOut(ctx.db, c, ctx.now);
});

// ---------------------------------------------------------------------------------------------- firmware

route('GET', '/firmware/baselines', (ctx) => {
  const vendor = qStr(ctx, 'vendor');
  const model = qStr(ctx, 'model');
  const component = qStr(ctx, 'component');
  const items = ctx.db.baselines
    .filter(
      (b) =>
        (!vendor || b.vendor === vendor) &&
        (!model || b.model === model) &&
        (!component || b.component === component),
    )
    .sort((a, b) =>
      `${a.vendor}|${a.model}|${a.component}`.localeCompare(`${b.vendor}|${b.model}|${b.component}`),
    );
  return page(ctx, items);
});
route('POST', '/firmware/baselines', (ctx) => {
  requireRole(ctx, 'dc_engineer', 'Approving firmware');
  unrestricted(ctx, 'A firmware baseline');
  const b: Baseline = {
    id: ctx.db.nextId(),
    vendor: str(ctx, 'vendor') ?? '',
    model: str(ctx, 'model') ?? '',
    component: str(ctx, 'component') ?? '',
    version: str(ctx, 'version') ?? '',
    notes: (ctx.body.notes as string | null) ?? null,
    updated_by: ctx.user?.name ?? 'demo user',
    updated_at: iso(ctx.now),
  };
  if (
    ctx.db.baselines.some((x) => x.vendor === b.vendor && x.model === b.model && x.component === b.component)
  )
    fail(409, 'A baseline for that vendor, model and component already exists.');
  ctx.db.baselines.push(b);
  audit(ctx, 'baseline.create', 'firmware_baseline', b.id, null, {
    vendor: b.vendor,
    model: b.model,
    component: b.component,
    version: b.version,
  });
  return b;
});
route('PUT|PATCH', '/firmware/baselines/:id', (ctx) => {
  requireRole(ctx, 'dc_engineer', 'Changing approved firmware');
  unrestricted(ctx, 'A firmware baseline');
  const b = ctx.db.baselines.find((x) => x.id === pid(ctx)) ?? fail(404, 'Baseline not found.');
  const before = { version: b.version, notes: b.notes };
  if (typeof ctx.body.version === 'string') b.version = ctx.body.version;
  if (has(ctx, 'notes')) b.notes = (ctx.body.notes as string | null) ?? null;
  b.updated_by = ctx.user?.name ?? 'demo user';
  b.updated_at = iso(ctx.now);
  audit(ctx, 'baseline.update', 'firmware_baseline', b.id, before, { version: b.version, notes: b.notes });
  return b;
});
route('DELETE', '/firmware/baselines/:id', (ctx) => {
  requireRole(ctx, 'dc_engineer', 'Removing baselines');
  unrestricted(ctx, 'A firmware baseline');
  const id = pid(ctx);
  ctx.db.baselines = ctx.db.baselines.filter((b) => b.id !== id);
  audit(ctx, 'baseline.delete', 'firmware_baseline', id, null, null);
});

route('GET', '/firmware/compliance', (ctx): Compliance => {
  const db = ctx.db;
  const siteId = qInt(ctx, 'site_id');
  const vendor = qStr(ctx, 'vendor');
  const model = qStr(ctx, 'model');
  const component = qStr(ctx, 'component');
  const servers = listed(db).filter(
    (s) =>
      canSee(ctx, s.site_id) &&
      (siteId === undefined || s.site_id === siteId) &&
      (!vendor || s.vendor === vendor) &&
      (!model || s.model === model),
  );
  const rows: ComplianceServer[] = [];
  let checked = 0;
  let compliant = 0;
  let componentsOff = 0;
  const modelsWithout = new Set<string>();
  for (const s of servers) {
    const items = firmwareItems(db, s, ctx.now).filter((f) => !component || f.component_key === component);
    const withBaseline = items.filter((f) => f.approved_version !== null);
    if (!db.baselines.some((b) => b.vendor === s.vendor && b.model === s.model))
      modelsWithout.add(`${s.vendor}|${s.model}`);
    if (!withBaseline.length) continue;
    checked++;
    const diffs = withBaseline.filter((f) => f.compliant === false);
    if (!diffs.length) {
      compliant++;
      continue;
    }
    componentsOff += diffs.length;
    rows.push({
      server_id: s.id,
      server_name: s.name,
      site_id: s.site_id,
      site_code: site(db, s.site_id).code,
      rack_name: rackOf(db, s.rack_id)?.name ?? null,
      vendor: s.vendor,
      model: s.model,
      differences: diffs.map((f) => ({
        component: f.component,
        component_key: f.component_key,
        component_type: f.component_type,
        installed_version: f.version,
        approved_version: f.approved_version!,
        collected_at: f.collected_at,
      })),
    });
  }
  const summary = {
    servers_with_firmware: servers.length,
    servers_checked: checked,
    servers_compliant: compliant,
    servers_off_baseline: rows.length,
    components_off_baseline: componentsOff,
    models_without_baseline: modelsWithout.size,
  };
  return page(ctx, rows, { summary }) as Compliance;
});

// ---------------------------------------------------------------------------------------------- admin, analytics

route('GET', '/users', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Viewing users');
  const q = qStr(ctx, 'q');
  const role = qStr(ctx, 'role');
  const codes = ctx.user?.sites ?? [];
  const items = ctx.db.users
    .filter(
      (u) =>
        (!q || like([u.name, u.email, u.sub], q)) &&
        (!role || u.roles.includes(role)) &&
        (codes.length === 0 || (u.sites ?? []).some((s) => codes.includes(s))),
    )
    .sort((a, b) => a.name.localeCompare(b.name));
  return page(ctx, items);
});

route('GET', '/audit', (ctx) => {
  requireRole(ctx, 'platform_admin', 'Viewing the audit log');
  const user = qStr(ctx, 'user');
  const action = qStr(ctx, 'action');
  const objectType = qStr(ctx, 'object_type');
  const objectId = qStr(ctx, 'object_id');
  const from = qStr(ctx, 'from');
  const to = qStr(ctx, 'to');
  const items = ctx.db.audit.filter(
    (a) =>
      (!user || like([a.user_name, a.user_sub], user)) &&
      (!action || (action.endsWith('.') ? a.action.startsWith(action) : a.action === action)) &&
      (!objectType || a.object_type === objectType) &&
      (!objectId || a.object_id === objectId) &&
      (!from || Date.parse(a.time) >= Date.parse(from)) &&
      (!to || Date.parse(a.time) < Date.parse(to)),
  );
  return page(ctx, items);
});

route('GET', '/superset/dashboards', (ctx) => ctx.db.dashboards);
route('POST', '/superset/guest-token', () => fail(409, 'Superset is not used in demo mode.'));

// ---------------------------------------------------------------------------------------------- live feed

const LIVE_METRICS = new Set([
  'inlet_temp_c',
  'exhaust_temp_c',
  'cpu_temp_c',
  'dimm_temp_c',
  'fan_rpm',
  'power_w',
  'psu_input_v',
]);

/** Fresh gauge readings of one server at `now`, for the demo live feed. Null when it can't report. */
export function demoLiveReadings(serverId: number, now: number) {
  const db = getDemoDb();
  const s = db.servers.find((x) => x.id === serverId);
  if (!s || s.status === 'decommissioned' || (s.unreachableSince !== null && now >= s.unreachableSince))
    return null;
  const readings = readingKeys(s)
    .filter(([m]) => LIVE_METRICS.has(m))
    .map(([metric, component]) => {
      const value = sensorValue(db, s, metric, component, now);
      return { metric, component, value, status: sensorStatus(s, metric, component, value), time: iso(now) };
    })
    .filter((r) => r.value !== null);
  return { server_id: s.id, site_id: s.site_id, readings };
}
