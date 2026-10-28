/**
 * Render a page the way the app does (query client, toasts, signed-in auth, API client, live client, shell,
 * router), against a fake API defined by a route table. The real `createApi` client is used with a fake
 * `fetch`, so query strings, bodies and problem+json errors go through the production code paths.
 *
 *   const { calls, user } = renderPage(<ServerPage />, {
 *     path: '/servers/:serverId', url: '/servers/7', roles: ['noc_operator'],
 *     routes: [{ path: '/api/v1/servers/7', reply: serverDetail }],
 *   });
 *
 * Pages that draw charts need `vi.mock('@/lib/echarts', ...)` in the test file (see tests/app/smoke.test.tsx).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderResult } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import { ApiProvider } from '@/api/ApiProvider';
import { createApi, type Api } from '@/api/client';
import { LiveClient } from '@/api/live';
import { LiveProvider } from '@/api/LiveProvider';
import { AuthContext, createStaticAuth } from '@/auth/AuthProvider';
import type { AuthUser } from '@/auth/oidc';
import type { Role } from '@/auth/roles';
import { ShellProvider, type ShellData, type SiteOption } from '@/components/shell/ShellContext';
import { ToastProvider } from '@/components/Toast';

export interface FakeRequest {
  method: string;
  url: URL;
  /** Parsed JSON body (or undefined). */
  body: unknown;
  /** Route params from a `:name` path pattern. */
  params: Record<string, string>;
}

export interface FakeRoute {
  method?: string;
  /** '/api/v1/servers/:id' (with :params) or a RegExp tested against the pathname. */
  path: string | RegExp;
  /** JSON body, or a function of the request. */
  reply?: unknown;
  status?: number;
  headers?: Record<string, string>;
}

export interface Call {
  method: string;
  path: string;
  query: URLSearchParams;
  body: unknown;
}

function matchPath(pattern: string | RegExp, pathname: string): Record<string, string> | null {
  if (pattern instanceof RegExp) return pattern.test(pathname) ? {} : null;
  const a = pattern.split('/');
  const b = pathname.split('/');
  if (a.length !== b.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < a.length; i++) {
    const seg = a[i] ?? '';
    if (seg.startsWith(':')) params[seg.slice(1)] = decodeURIComponent(b[i] ?? '');
    else if (seg !== b[i]) return null;
  }
  return params;
}

/** A fake `fetch` serving the route table; unknown routes answer 404 problem+json. */
export function createFakeFetch(routes: FakeRoute[], calls: Call[]): typeof fetch {
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(input, init);
    const url = new URL(req.url);
    const text = req.method === 'GET' || req.method === 'HEAD' ? '' : await req.text();
    let body: unknown = undefined;
    try {
      body = text ? (JSON.parse(text) as unknown) : undefined;
    } catch {
      body = text;
    }
    calls.push({ method: req.method, path: url.pathname, query: url.searchParams, body });
    for (const r of routes) {
      if ((r.method ?? 'GET').toUpperCase() !== req.method) continue;
      const params = matchPath(r.path, url.pathname);
      if (!params) continue;
      const value =
        typeof r.reply === 'function'
          ? (r.reply as (req: FakeRequest) => unknown)({ method: req.method, url, body, params })
          : r.reply;
      const status = r.status ?? (value === undefined ? 204 : 200);
      if (status === 204) return new Response(null, { status });
      const isText = typeof value === 'string';
      return new Response(isText ? value : JSON.stringify(value), {
        status,
        headers: {
          'content-type': isText
            ? 'text/plain'
            : status >= 400
              ? 'application/problem+json'
              : 'application/json',
          ...r.headers,
        },
      });
    }
    return new Response(
      JSON.stringify({
        type: 'about:blank',
        title: 'Not found',
        status: 404,
        detail: `${req.method} ${url.pathname}`,
      }),
      { status: 404, headers: { 'content-type': 'application/problem+json' } },
    );
  };
}

export function createFakeApi(routes: FakeRoute[]): { api: Api; calls: Call[] } {
  const calls: Call[] = [];
  const api = createApi(
    { getAccessToken: () => Promise.resolve('test-token'), renew: () => Promise.resolve(null) },
    { baseUrl: 'http://api.test', baseFetch: createFakeFetch(routes, calls) },
  );
  return { api, calls };
}

export function testUser(roles: Role[] = ['viewer'], sites: string[] = []): AuthUser {
  return {
    sub: 'test-user',
    username: 'tester',
    name: 'Test User',
    email: 'tester@gcc.example',
    roles,
    sites,
    groups: roles.map((r) => `gcc-${r.replace('_', '-')}`),
    accessToken: 'test-token',
    expiresAt: null,
  };
}

export const TEST_SITES: SiteOption[] = [
  { id: 1, code: 'PNQ1', name: 'Pune DC1', health: 'Warning' },
  { id: 2, code: 'HYD1', name: 'Hyderabad DC2', health: 'OK' },
];

/** Shows the current location so tests can assert navigation: `screen.getByTestId('location')`. */
function LocationProbe() {
  const loc = useLocation();
  return (
    <output data-testid="location" hidden>
      {`${loc.pathname}${loc.search}`}
    </output>
  );
}

export interface RenderPageOptions {
  /** Route pattern the page is mounted at, e.g. '/servers/:serverId' (default '/'). */
  path?: string;
  /** Initial URL (default = path). */
  url?: string;
  routes?: FakeRoute[];
  roles?: Role[];
  sites?: string[];
  shell?: Partial<ShellData>;
  queryClient?: QueryClient;
}

export interface RenderPageResult extends RenderResult {
  calls: Call[];
  api: Api;
  queryClient: QueryClient;
  live: LiveClient;
  user: ReturnType<typeof userEvent.setup>;
}

export function renderPage(ui: ReactElement, options: RenderPageOptions = {}): RenderPageResult {
  const { api, calls } = createFakeApi(options.routes ?? []);
  const queryClient =
    options.queryClient ??
    new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
    });
  // Never connected: subscriptions are recorded, no socket is opened.
  const live = new LiveClient({ url: 'ws://live.test', getToken: () => Promise.resolve('test-token') });
  const auth = createStaticAuth(testUser(options.roles, options.sites));
  const shell: ShellData = { sites: TEST_SITES, search: null, openAlerts: null, ...options.shell };
  const path = options.path ?? '/';
  const user = userEvent.setup();
  const result = render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthContext.Provider value={auth}>
          <ApiProvider api={api}>
            <LiveProvider client={live}>
              <ShellProvider data={shell}>
                <MemoryRouter initialEntries={[options.url ?? path]}>
                  <Routes>
                    <Route path={path} element={ui} />
                    <Route path="*" element={<p>Navigated away</p>} />
                  </Routes>
                  <LocationProbe />
                </MemoryRouter>
              </ShellProvider>
            </LiveProvider>
          </ApiProvider>
        </AuthContext.Provider>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { ...result, calls, api, queryClient, live, user };
}

/** Minimal `/api/v1/me` reply for a role set (capabilities mirror the backend). */
export function meFor(roles: Role[]): Record<string, unknown> {
  const rank = (r: Role) => ['viewer', 'noc_operator', 'dc_engineer', 'platform_admin'].indexOf(r);
  const top = Math.max(...roles.map((r) => (r === 'analyst' ? 0 : rank(r))));
  const op = top >= 1;
  const eng = top >= 2;
  const admin = top >= 3;
  return {
    sub: 'test-user',
    username: 'tester',
    name: 'Test User',
    email: null,
    roles,
    primary_role: roles[0] ?? null,
    site_limited: false,
    sites: null,
    token_expires_at: new Date(Date.now() + 3600_000).toISOString(),
    capabilities: {
      view: top >= 0,
      ack_alerts: op,
      comment_alerts: op,
      resolve_alerts: op,
      onboard_servers: eng,
      edit_racks: eng,
      edit_maintenance: eng,
      edit_baselines: eng,
      edit_sites: admin,
      edit_collectors: admin,
      edit_thresholds: admin,
      edit_alert_rules: admin,
      edit_alert_routes: admin,
      view_users: admin,
      view_audit: admin,
      superset_editor: admin || roles.includes('analyst'),
    },
  };
}
