import { screen, waitFor } from '@testing-library/react';

import { useApiQuery, useCan } from '@/api/hooks';
import { buildUrl } from '@/api/client';
import { openAlertCounts, toSearchResults, useShellData } from '@/app/useShellData';
import type { Overview } from '@/api/types';

import { meFor, renderPage } from '../utils/renderPage';

describe('toSearchResults', () => {
  it('maps servers, racks and sites to routes (servers first)', () => {
    const results = toSearchResults({
      query: 'r750',
      servers: [
        {
          id: 7,
          name: 'pnq1-srv-007',
          bmc_host: 'http://bmc:20007',
          serial: 'SN7',
          asset_tag: null,
          model: 'PowerEdge R750',
          site_code: 'PNQ1',
          rack_name: 'R01',
          position_u: 12,
          health: 'Warning',
        },
      ],
      racks: [{ id: 3, name: 'R03', room_name: 'Hall A', site_id: 1, site_code: 'PNQ1' }],
      sites: [{ id: 1, code: 'PNQ1', name: 'Pune DC1', city: 'Pune' }],
    });
    expect(results.map((r) => r.to)).toEqual(['/servers/7', '/racks/3', '/sites/1']);
    expect(results[0]).toMatchObject({
      kind: 'server',
      health: 'Warning',
      sublabel: 'PNQ1 · R01 · U12 — PowerEdge R750 · S/N SN7',
    });
  });
});

describe('openAlertCounts', () => {
  it('counts unresolved unmuted alerts by severity', () => {
    const overview = {
      totals: { alerts: { critical: 2, warning: 3, info: 1, acknowledged: 4, muted: 9 } },
    } as unknown as Overview;
    expect(openAlertCounts(overview)).toEqual({ count: 6, critical: 2 });
    expect(openAlertCounts(undefined)).toBeNull();
  });
});

describe('buildUrl', () => {
  it('repeats keys for list values and drops empty ones', () => {
    expect(buildUrl('', '/api/v1/alerts', { state: ['open', 'acknowledged'], q: '', site_id: 2 })).toBe(
      '/api/v1/alerts?state=open&state=acknowledged&site_id=2',
    );
  });
});

function ShellProbe() {
  const data = useShellData();
  return (
    <p>
      {data.sites.map((s) => `${s.code}:${s.health}`).join(',')}|{data.openAlerts?.count ?? 'none'}
    </p>
  );
}

function CanProbe() {
  const can = useCan();
  const me = useApiQuery('/api/v1/me');
  return (
    <p>
      {me.isSuccess ? 'loaded' : 'loading'}:{String(can('ack_alerts'))}:{String(can('edit_thresholds'))}
    </p>
  );
}

describe('shell data and capabilities against the fake API', () => {
  it('loads sites and the open-alert count', async () => {
    renderPage(<ShellProbe />, {
      routes: [
        {
          path: '/api/v1/sites',
          reply: {
            items: [{ id: 1, code: 'PNQ1', name: 'Pune DC1', worst_health: 'Critical' }],
            next_cursor: null,
          },
        },
        {
          path: '/api/v1/overview',
          reply: { totals: { alerts: { critical: 1, warning: 2, info: 0 } }, sites: [] },
        },
      ],
    });
    expect(await screen.findByText('PNQ1:Critical|3')).toBeInTheDocument();
  });

  it('answers capabilities from /me, with the role rule as fallback', async () => {
    renderPage(<CanProbe />, {
      roles: ['noc_operator'],
      routes: [{ path: '/api/v1/me', reply: meFor(['noc_operator']) }],
    });
    await waitFor(() => expect(screen.getByText('loaded:true:false')).toBeInTheDocument());
  });
});
