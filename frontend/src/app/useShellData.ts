import { useMemo } from 'react';

import { useApi } from '@/api/ApiProvider';
import { useApiQuery } from '@/api/hooks';
import type { Overview, Page, SearchOut, SiteSummary } from '@/api/types';
import type { SearchResult, SearchSource, ShellData, SiteOption } from '@/components/shell/ShellContext';

/** Flatten `GET /api/v1/search` (servers, racks, sites) into the global search's result list. */
export function toSearchResults(out: SearchOut): SearchResult[] {
  const sites: SearchResult[] = out.sites.map((s) => ({
    id: `site-${s.id}`,
    kind: 'site',
    label: `${s.code} · ${s.name}`,
    sublabel: s.city,
    to: `/sites/${s.id}`,
  }));
  const racks: SearchResult[] = out.racks.map((r) => ({
    id: `rack-${r.id}`,
    kind: 'rack',
    label: r.name,
    sublabel: `${r.site_code} · ${r.room_name}`,
    to: `/racks/${r.id}`,
  }));
  const servers: SearchResult[] = out.servers.map((s) => {
    const where = [s.site_code, s.rack_name, s.position_u ? `U${s.position_u}` : null]
      .filter(Boolean)
      .join(' · ');
    const ids = [s.model, s.serial ? `S/N ${s.serial}` : null, s.asset_tag].filter(Boolean).join(' · ');
    return {
      id: `server-${s.id}`,
      kind: 'server',
      label: s.name,
      sublabel: [where, ids].filter(Boolean).join(' — ') || s.bmc_host,
      to: `/servers/${s.id}`,
      health: s.health,
    };
  });
  return [...servers, ...racks, ...sites];
}

const REFRESH_MS = 30_000;

/** Open-alert counts for the bell: unresolved, unmuted alerts (acknowledged ones included). */
export function openAlertCounts(overview: Overview | undefined): ShellData['openAlerts'] {
  if (!overview) return null;
  const a = overview.totals.alerts;
  const critical = a.critical ?? 0;
  return { count: critical + (a.warning ?? 0) + (a.info ?? 0), critical };
}

/** Data for the shell: sidebar sites (with worst health), global search, alerts bell. */
export function useShellData(): ShellData {
  const api = useApi();
  const sitesQuery = useApiQuery<Page<SiteSummary>>(
    '/api/v1/sites',
    { limit: 500 },
    { staleTime: REFRESH_MS, refetchInterval: 60_000 },
  );
  // The overview is shared with the overview page (same key), so the bell costs nothing extra there.
  const overview = useApiQuery<Overview>('/api/v1/overview', undefined, {
    staleTime: 15_000,
    refetchInterval: REFRESH_MS,
  });

  const search = useMemo<SearchSource>(
    () => async (q, signal) =>
      toSearchResults(await api.json<SearchOut>('/api/v1/search', { query: { q, limit: 8 }, signal })),
    [api],
  );

  const siteItems = sitesQuery.data?.items;
  const sites = useMemo<SiteOption[]>(
    () =>
      (siteItems ?? []).map((s) => ({
        id: s.id,
        code: s.code,
        name: s.name,
        health: s.worst_health ?? null,
      })),
    [siteItems],
  );
  const openAlerts = openAlertCounts(overview.data);
  const count = openAlerts?.count;
  const critical = openAlerts?.critical;

  return useMemo(
    () => ({
      sites,
      search,
      openAlerts: count === undefined || critical === undefined ? null : { count, critical },
    }),
    [sites, search, count, critical],
  );
}
