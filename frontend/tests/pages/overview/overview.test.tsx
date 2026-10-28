import { act, screen, within } from '@testing-library/react';

import { applyLiveMessage } from '@/api/LiveProvider';
import type { Overview, SiteSummary } from '@/api/types';
import OverviewPage from '@/pages/OverviewPage';
import { aggregateSites } from '@/pages/overview/useOverview';
import WallPage from '@/pages/WallPage';

import { renderPage, TEST_SITES } from '../../utils/renderPage';

const now = new Date().toISOString();

const pune = {
  id: 1,
  code: 'PNQ1',
  name: 'Pune DC1',
  city: 'Pune',
  country: 'India',
  timezone: 'Asia/Kolkata',
  room_count: 2,
  rack_count: 6,
  server_count: 20,
  servers_in_maintenance: 1,
  health: { ok: 16, warning: 3, critical: 1, unknown: 0 },
  worst_health: 'Critical',
  alerts: { critical: 1, warning: 2, info: 0, acknowledged: 1, muted: 0 },
  power_w: 6400,
  rack_power_capacity_w: 48000,
  inlet_avg_c: 23.4,
  inlet_max_c: 31.2,
  freshness: {
    latest_reading_at: now,
    oldest_server_reading_at: now,
    servers_reporting: 20,
    servers_stale: 0,
  },
  collectors_online: 2,
  collectors_total: 2,
} satisfies SiteSummary;

const hyderabad = {
  ...pune,
  id: 2,
  code: 'HYD1',
  name: 'Hyderabad DC2',
  city: 'Hyderabad',
  server_count: 19,
  servers_in_maintenance: 0,
  health: { ok: 19, warning: 0, critical: 0, unknown: 0 },
  worst_health: 'OK',
  alerts: { critical: 0, warning: 0, info: 0, acknowledged: 0, muted: 0 },
  power_w: 5000,
  collectors_online: 0,
  collectors_total: 1,
} satisfies SiteSummary;

const overview = {
  generated_at: now,
  totals: {
    sites: 2,
    server_count: 39,
    health: { ok: 35, warning: 3, critical: 1, unknown: 0 },
    worst_health: 'Critical',
    alerts: { critical: 1, warning: 2, info: 0, acknowledged: 1, muted: 0 },
    power_w: 11400,
    freshness: { latest_reading_at: now, servers_reporting: 39, servers_stale: 0 },
    collectors_online: 2,
    collectors_total: 3,
  },
  sites: [pune, hyderabad],
} satisfies Overview;

const routes = [
  { path: '/api/v1/overview', reply: overview },
  { path: '/api/v1/alerts', reply: { items: [], next_cursor: null } },
];

describe('aggregateSites', () => {
  it('sums counts, keeps the worst health and the newest reading', () => {
    const t = aggregateSites([pune, hyderabad]);
    expect(t).toMatchObject({
      sites: 2,
      server_count: 39,
      worst_health: 'Critical',
      power_w: 11400,
      collectors_online: 2,
      collectors_total: 3,
      alerts: { critical: 1, warning: 2, acknowledged: 1 },
      health: { ok: 35, warning: 3, critical: 1 },
    });
    expect(aggregateSites([{ ...hyderabad, power_w: null }]).power_w).toBeNull();
    expect(aggregateSites([]).worst_health).toBe('Unknown');
  });
});

describe('OverviewPage', () => {
  it('shows totals and one card per site with health as words', async () => {
    renderPage(<OverviewPage />, { routes });
    const sites = await screen.findByRole('region', { name: 'Sites' });
    const cards = within(sites).getAllByRole('link');
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveAttribute('href', '/sites/1');
    expect(cards[0]).toHaveAccessibleName(/PNQ1 Pune DC1: health Critical, 20 servers .*3 open alerts/);
    expect(cards[0]!.querySelector('header [data-health]')).toHaveTextContent('Critical');
    expect(within(cards[1]!).getByText('0 of 1 online')).toBeInTheDocument();
    // totals: power in kW with its unit, open alert count
    expect(screen.getAllByTestId('stat-value').map((e) => e.textContent)).toContain('11.4 kW');
    expect(screen.getByRole('link', { name: 'Open alerts: 3' })).toBeInTheDocument();
    expect(await screen.findByText('No open critical or warning alerts')).toBeInTheDocument();
  });

  it('narrows to the global site filter and recomputes totals', async () => {
    window.localStorage.setItem('gcc.siteFilter', JSON.stringify([2]));
    renderPage(<OverviewPage />, { routes, shell: { sites: TEST_SITES } });
    const sites = await screen.findByRole('region', { name: 'Sites' });
    expect(within(sites).getAllByRole('link')).toHaveLength(1);
    expect(screen.getByText(/1 of 2 sites \(site filter on\)/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Servers: 19' })).toBeInTheDocument();
  });

  it('refetches when a live health change arrives for a site', async () => {
    const { calls, queryClient } = renderPage(<OverviewPage />, { routes });
    await screen.findByRole('region', { name: 'Sites' });
    const before = calls.filter((c) => c.path === '/api/v1/overview').length;
    act(() =>
      applyLiveMessage(queryClient, {
        type: 'health',
        server_id: 5,
        site_id: 1,
        changes: [],
        server_health: 'Critical',
      }),
    );
    await vi.waitFor(() =>
      expect(calls.filter((c) => c.path === '/api/v1/overview').length).toBeGreaterThan(before),
    );
  });

  it('shows a retry card when the overview fails', async () => {
    renderPage(<OverviewPage />, {
      routes: [
        { path: '/api/v1/overview', status: 503, reply: { title: 'Service unavailable', status: 503 } },
      ],
    });
    expect(await screen.findByText("Couldn't load the overview")).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});

describe('WallPage', () => {
  it('renders the sites at wall scale with critical alerts', async () => {
    renderPage(<WallPage />, {
      path: '/wall',
      routes: [
        { path: '/api/v1/overview', reply: overview },
        {
          path: '/api/v1/alerts',
          reply: {
            items: [
              {
                id: 9,
                rule: { id: 1, name: 'Inlet temperature high', rule_type: 'threshold' },
                server: { id: 3, name: 'pnq1-srv-003', bmc_host: 'http://bmc:20003' },
                site: { id: 1, code: 'PNQ1', name: 'Pune DC1' },
                collector: null,
                metric: 'inlet_temp_c',
                component: 'Inlet',
                state: 'open',
                severity: 'Critical',
                title: 'Inlet temperature high',
                message: 'Inlet 38 °C',
                value: 38,
                threshold: 35,
                muted: false,
                occurrences: 1,
                opened_at: now,
                last_seen_at: now,
                acked_at: null,
                acked_by: null,
                resolved_at: null,
                resolved_by: null,
                notified_at: null,
                escalated_at: null,
                manually_resolvable: false,
              },
            ],
            next_cursor: null,
          },
        },
      ],
    });
    expect(await screen.findByRole('heading', { name: 'Global overview', level: 1 })).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: /Inlet temperature high/ })).toHaveAttribute(
      'href',
      '/alerts?id=9',
    );
    expect(screen.getByRole('link', { name: 'Exit wall mode' })).toBeInTheDocument();
  });
});
