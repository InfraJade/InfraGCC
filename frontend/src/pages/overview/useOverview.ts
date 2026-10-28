import { useQueryClient, type QueryKey } from '@tanstack/react-query';
import { useEffect, useMemo, useRef } from 'react';

import { useApiQuery } from '@/api/hooks';
import { useLiveSites } from '@/api/LiveProvider';
import { queryKeys } from '@/api/queryClient';
import type {
  AlertCounts,
  Freshness,
  HealthCounts,
  Overview,
  OverviewTotals,
  SiteSummary,
} from '@/api/types';
import { useSiteFilter } from '@/components/shell/ShellContext';
import { worstHealth } from '@/lib/health';

const sum = (values: (number | null | undefined)[]): number =>
  values.reduce<number>((a, v) => a + (v ?? 0), 0);

/** Sum of nullable values; null when every value is null (e.g. no power readings at all). */
const sumOrNull = (values: (number | null | undefined)[]): number | null =>
  values.some((v) => v !== null && v !== undefined) ? sum(values) : null;

const latest = (values: (string | null | undefined)[], pick: 'max' | 'min'): string | null => {
  const ms = values.filter((v): v is string => !!v).map((v) => Date.parse(v));
  if (!ms.length) return null;
  return new Date(pick === 'max' ? Math.max(...ms) : Math.min(...ms)).toISOString();
};

/** Totals over a subset of sites (the global site filter), shaped like the API's overview totals. */
export function aggregateSites(sites: readonly SiteSummary[]): OverviewTotals {
  const health: HealthCounts = {
    ok: sum(sites.map((s) => s.health?.ok)),
    warning: sum(sites.map((s) => s.health?.warning)),
    critical: sum(sites.map((s) => s.health?.critical)),
    unknown: sum(sites.map((s) => s.health?.unknown)),
  };
  const alerts: AlertCounts = {
    critical: sum(sites.map((s) => s.alerts?.critical)),
    warning: sum(sites.map((s) => s.alerts?.warning)),
    info: sum(sites.map((s) => s.alerts?.info)),
    acknowledged: sum(sites.map((s) => s.alerts?.acknowledged)),
    muted: sum(sites.map((s) => s.alerts?.muted)),
  };
  const freshness: Freshness = {
    latest_reading_at: latest(
      sites.map((s) => s.freshness?.latest_reading_at),
      'max',
    ),
    oldest_server_reading_at: latest(
      sites.map((s) => s.freshness?.oldest_server_reading_at),
      'min',
    ),
    servers_reporting: sum(sites.map((s) => s.freshness?.servers_reporting)),
    servers_stale: sum(sites.map((s) => s.freshness?.servers_stale)),
  };
  return {
    sites: sites.length,
    server_count: sum(sites.map((s) => s.server_count)),
    health,
    worst_health: sites.length ? worstHealth(sites.map((s) => s.worst_health)) : 'Unknown',
    alerts,
    power_w: sumOrNull(sites.map((s) => s.power_w)),
    freshness,
    collectors_online: sum(sites.map((s) => s.collectors_online)),
    collectors_total: sum(sites.map((s) => s.collectors_total)),
  };
}

/** Open alerts in the bell's sense: unresolved and not muted, any severity. */
export function openAlertTotal(a: AlertCounts | undefined): number {
  return (a?.critical ?? 0) + (a?.warning ?? 0) + (a?.info ?? 0);
}

/**
 * Refetch `queryKey` when a live health/alert push arrives for any of these sites, at most once per
 * `minIntervalMs` (a busy site can push several messages a second).
 */
export function useLiveRefresh(siteIds: readonly number[], queryKey: QueryKey, minIntervalMs = 10_000) {
  const qc = useQueryClient();
  const live = useLiveSites(siteIds);
  const stamp = Math.max(0, ...Object.values(live).map((s) => s.updatedAt ?? 0));
  const last = useRef(0);
  // Live state already cached when the page mounts is older than the data the page is about to fetch.
  const initial = useRef(stamp);
  const keyRef = useRef(queryKey);
  keyRef.current = queryKey;

  useEffect(() => {
    if (!stamp || stamp === initial.current) return;
    const wait = last.current + minIntervalMs - Date.now();
    const run = () => {
      last.current = Date.now();
      void qc.invalidateQueries({ queryKey: keyRef.current });
    };
    if (wait <= 0) {
      run();
      return;
    }
    const t = setTimeout(run, wait);
    return () => clearTimeout(t);
  }, [stamp, qc, minIntervalMs]);
}

/** The overview, narrowed to the global site filter, refreshed every 30 s and on live pushes. */
export function useOverview() {
  const query = useApiQuery<Overview>('/api/v1/overview', undefined, {
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
  const { siteIds } = useSiteFilter();
  const allSites = query.data?.sites;
  const allIds = useMemo(() => (allSites ?? []).map((s) => s.id), [allSites]);
  useLiveRefresh(allIds, queryKeys.overview);

  const filterKey = siteIds.join(',');
  const view = useMemo(() => {
    const data = query.data;
    if (!data) return null;
    const ids = filterKey ? new Set(filterKey.split(',').map(Number)) : null;
    const sites = ids ? data.sites.filter((s) => ids.has(s.id)) : data.sites;
    const filtered = ids !== null && sites.length !== data.sites.length;
    return {
      generatedAt: data.generated_at,
      sites,
      totals: filtered ? aggregateSites(sites) : data.totals,
      filtered,
    };
  }, [query.data, filterKey]);

  return { query, view };
}
