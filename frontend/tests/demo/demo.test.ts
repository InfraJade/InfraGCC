import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  AlertDetail,
  Overview,
  Page,
  Readings,
  ServerDetail,
  ServerListItem,
  SiteSummary,
} from '@/api/types';
import { isDemoMode, setDemoMode } from '@/demo/demoMode';
import { createDemoFetch } from '@/demo/fetch';
import { DemoLiveClient } from '@/demo/live';
import { buildDemoDb } from '@/demo/seed';
import { getDemoDb, handleDemoRequest, resetDemoDb, type DemoUser } from '@/demo/server';

const user = (roles: DemoUser['roles'], sites: string[] = []): DemoUser => ({
  sub: `test-${roles.join('-')}-${sites.join('-')}`,
  username: roles[0] ?? 'nobody',
  name: `Test ${roles[0] ?? ''}`,
  email: null,
  roles,
  sites,
  expiresAt: null,
});
const admin = user(['platform_admin']);
const viewer = user(['viewer']);
const noc = user(['noc_operator']);
const pune = user(['noc_operator'], ['PNQ1']);

function get<T>(path: string, query: Record<string, string | string[]> = {}, as: DemoUser = admin): T {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) for (const x of Array.isArray(v) ? v : [v]) qs.append(k, x);
  const res = handleDemoRequest('GET', path, qs, undefined, as);
  expect(res.status, path).toBe(200);
  return res.body as T;
}
const send = (method: string, path: string, body: unknown, as: DemoUser = admin) =>
  handleDemoRequest(method, path, new URLSearchParams(), body, as);

beforeEach(() => resetDemoDb());

describe('demo data set', () => {
  it('is deterministic and has three sites with racks and servers', () => {
    const a = buildDemoDb(Date.UTC(2026, 9, 28));
    const b = buildDemoDb(Date.UTC(2026, 9, 28));
    expect(a.sites.map((s) => s.code)).toEqual(['PNQ1', 'HYD1', 'BLR1']);
    expect(a.rooms).toHaveLength(5);
    expect(a.racks).toHaveLength(15);
    expect(a.servers.length).toBeGreaterThan(55);
    expect(a.servers.map((s) => s.serial)).toEqual(b.servers.map((s) => s.serial));
    expect(new Set(a.servers.map((s) => s.vendor))).toEqual(new Set(['Dell', 'HPE', 'Lenovo']));
  });
});

describe('demo API', () => {
  it('answers every screen endpoint', () => {
    const db = getDemoDb();
    const server = db.servers[0]!;
    const paths = [
      '/me',
      '/metrics',
      '/overview',
      '/sites',
      `/sites/${db.sites[0]!.id}`,
      '/rooms',
      '/racks',
      `/racks/${db.racks[0]!.id}`,
      '/servers',
      `/servers/${server.id}`,
      `/servers/${server.id}/events`,
      '/components',
      '/alerts',
      `/alerts/${db.alerts[0]!.id}`,
      '/alert-rules',
      '/thresholds',
      '/alert-routes',
      '/maintenance-windows',
      '/collectors',
      '/firmware/baselines',
      '/firmware/compliance',
      '/users',
      '/audit',
      '/superset/dashboards',
    ];
    for (const p of paths) expect(() => get(p)).not.toThrow();
    expect(get<unknown>('/search', { q: 'pnq' })).toMatchObject({ query: 'pnq' });
    expect(get<unknown>('/thresholds', { server_id: String(server.id) })).toHaveProperty('effective');
  });

  it('builds an overview with totals that match the site cards', () => {
    const o = get<Overview>('/overview');
    expect(o.sites).toHaveLength(3);
    expect(o.totals.server_count).toBe(o.sites.reduce((n, s) => n + s.server_count, 0));
    expect(o.totals.alerts.critical).toBeGreaterThan(0);
    expect(o.totals.health.critical + o.totals.health.warning).toBeGreaterThan(0);
    expect(o.totals.collectors_online).toBe(o.totals.collectors_total - 1);
  });

  it('paginates with cursors and filters', () => {
    const first = get<Page<ServerListItem>>('/servers', { limit: '10' });
    expect(first.items).toHaveLength(10);
    expect(first.next_cursor).toBeTruthy();
    const second = get<Page<ServerListItem>>('/servers', { limit: '10', cursor: first.next_cursor! });
    expect(second.items[0]!.id).not.toBe(first.items[0]!.id);
    const crit = get<Page<ServerListItem>>('/servers', { health: 'Critical', limit: '500' });
    expect(crit.items.length).toBeGreaterThan(0);
    expect(crit.items.every((s) => s.health === 'Critical')).toBe(true);
    const open = get<Page<AlertDetail>>('/alerts', { state: ['open', 'acknowledged'], limit: '500' });
    expect(open.items.every((a) => a.state !== 'resolved')).toBe(true);
  });

  it('limits site-restricted users to their sites', () => {
    const sites = get<Page<SiteSummary>>('/sites', {}, pune);
    expect(sites.items.map((s) => s.code)).toEqual(['PNQ1']);
    const servers = get<Page<ServerListItem>>('/servers', { limit: '500' }, pune);
    expect(servers.items.every((s) => s.site.code === 'PNQ1')).toBe(true);
    const other = getDemoDb().servers.find((s) => s.site_id !== 1)!;
    expect(() =>
      handleDemoRequest('GET', `/servers/${other.id}`, new URLSearchParams(), undefined, pune),
    ).toThrow('Server not found.');
  });

  it('enforces roles on writes and applies acknowledgements', () => {
    const alert = getDemoDb().alerts.find((a) => a.state === 'open' && !a.muted)!;
    expect(() => send('POST', `/alerts/${alert.id}/ack`, {}, viewer)).toThrow(/role/);
    const res = send('POST', `/alerts/${alert.id}/ack`, { note: 'on it' }, noc);
    expect(res.status).toBe(200);
    expect((res.body as AlertDetail).state).toBe('acknowledged');
    expect((res.body as AlertDetail).activity[0]).toMatchObject({ action: 'acknowledged', note: 'on it' });
    expect(getDemoDb().audit[0]).toMatchObject({ action: 'alert.ack' });
    resetDemoDb();
    expect(getDemoDb().alerts.find((a) => a.id === alert.id)!.state).toBe('open');
  });

  it('returns readings history and live-consistent server detail', () => {
    const s = getDemoDb().servers[0]!;
    const detail = get<ServerDetail>(`/servers/${s.id}`);
    expect(detail.latest_readings.find((r) => r.metric === 'inlet_temp_c')?.value).toBeTypeOf('number');
    expect(detail.health_parts.length).toBeGreaterThan(10);
    const r = get<Readings>(`/servers/${s.id}/readings`, { metric: 'cpu_temp_c' });
    expect(r.resolution).toBe('5m');
    expect(r.series).toHaveLength(2);
    expect(r.series[0]!.points.length).toBeGreaterThan(200);
  });

  it('exports CSV', () => {
    const res = handleDemoRequest('GET', '/servers/export.csv', new URLSearchParams(), undefined, admin);
    expect(res.contentType).toMatch(/text\/csv/);
    expect(String(res.body).split('\n')[0]).toMatch(/^id,name,site/);
  });
});

describe('demo fetch', () => {
  const demoFetch = createDemoFetch(() => admin, [0, 0]);

  it('serves JSON and problem+json responses', async () => {
    const ok = await demoFetch(new Request('http://localhost/api/v1/sites?limit=2'));
    expect(ok.status).toBe(200);
    expect(((await ok.json()) as Page<SiteSummary>).items).toHaveLength(2);
    const missing = await demoFetch(new Request('http://localhost/api/v1/servers/99999'));
    expect(missing.status).toBe(404);
    expect(missing.headers.get('Content-Type')).toBe('application/problem+json');
  });

  it('returns 204 for deletes', async () => {
    const res = await demoFetch(
      new Request('http://localhost/api/v1/maintenance-windows/1', { method: 'DELETE' }),
    );
    expect(res.status).toBe(204);
  });
});

describe('demo mode switch and live feed', () => {
  afterEach(() => {
    setDemoMode(false);
    vi.useRealTimers();
  });

  it('remembers the setting in the browser', () => {
    setDemoMode(true);
    expect(isDemoMode()).toBe(true);
    expect(window.localStorage.getItem('gcc.demoMode')).toBe('true');
  });

  it('pushes readings for subscribed servers', () => {
    vi.useFakeTimers();
    const live = new DemoLiveClient();
    const got: unknown[] = [];
    live.onMessage((m) => got.push(m));
    live.connect();
    const id = getDemoDb().servers[0]!.id;
    live.subscribe({ servers: [id] });
    vi.advanceTimersByTime(5_500);
    expect(live.status).toBe('open');
    expect(got.length).toBeGreaterThan(0);
    expect(got[0]).toMatchObject({ type: 'readings', server_id: id });
    live.close();
  });
});
