/** Picker data for admin forms and filters (sites, rooms by site, racks by room, collectors by site, metrics). */
import { useMemo } from 'react';

import { useAllItems, useApiQuery } from '@/api/hooks';
import type { Collector, Metric, Rack, Room, ServerListItem, SiteSummary } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';
import type { SelectOption } from '@/components/FormField';
import { useSiteFilter } from '@/components/shell/ShellContext';
import { numberParam, useUrlState } from '@/lib/useUrlState';

export function useSites() {
  const q = useAllItems<SiteSummary>('/api/v1/sites');
  const sites = useMemo(() => q.data ?? [], [q.data]);
  const options: SelectOption[] = useMemo(
    () => sites.map((s) => ({ value: String(s.id), label: `${s.code} · ${s.name}` })),
    [sites],
  );
  const byId = useMemo(() => new Map(sites.map((s) => [s.id, s])), [sites]);
  return { sites, options, byId, loading: q.isPending };
}

export function useRooms(siteId: number | undefined) {
  const q = useAllItems<Room>(siteId ? '/api/v1/rooms' : null, { site_id: siteId });
  const rooms = useMemo(() => q.data ?? [], [q.data]);
  const options: SelectOption[] = useMemo(
    () =>
      rooms.map((r) => ({ value: String(r.id), label: r.floor ? `${r.name} (floor ${r.floor})` : r.name })),
    [rooms],
  );
  return { rooms, options, loading: siteId !== undefined && q.isPending };
}

export function useRacks(roomId: number | undefined) {
  const q = useAllItems<Rack>(roomId ? '/api/v1/racks' : null, { room_id: roomId });
  const racks = useMemo(() => q.data ?? [], [q.data]);
  const options: SelectOption[] = useMemo(
    () =>
      racks.map((r) => ({
        value: String(r.id),
        label: `${r.name}${r.row ? ` · row ${r.row}` : ''} · ${r.used_u} of ${r.height_u} U used`,
      })),
    [racks],
  );
  return { racks, options, loading: roomId !== undefined && q.isPending };
}

export function useCollectors(siteId: number | undefined) {
  const q = useAllItems<Collector>(siteId ? '/api/v1/collectors' : null, { site_id: siteId });
  const collectors = useMemo(() => q.data ?? [], [q.data]);
  const options: SelectOption[] = useMemo(
    () =>
      collectors.map((c) => ({
        value: String(c.id),
        label: `${c.name}${c.online ? '' : ' (offline)'}${c.enabled ? '' : ' (disabled)'}`,
      })),
    [collectors],
  );
  return { collectors, options, loading: siteId !== undefined && q.isPending };
}

/** Servers of one site for a picker (name, else BMC address). */
export function useSiteServers(siteId: number | undefined) {
  const q = useAllItems<ServerListItem>(siteId ? '/api/v1/servers' : null, { site_id: siteId });
  const servers = useMemo(() => q.data ?? [], [q.data]);
  const options = useMemo(
    () =>
      servers.map((s) => ({
        value: String(s.id),
        label: s.name || s.bmc_host,
        description: [s.rack?.name, s.position_u ? `U${s.position_u}` : null, s.model]
          .filter(Boolean)
          .join(' · '),
      })),
    [servers],
  );
  return { servers, options, loading: siteId !== undefined && q.isPending };
}

export function useMetrics() {
  const q = useApiQuery<Metric[]>('/api/v1/metrics', undefined, { staleTime: 10 * 60_000 });
  const metrics = useMemo(() => q.data ?? [], [q.data]);
  const byCode = useMemo(() => new Map(metrics.map((m) => [m.code, m])), [metrics]);
  return { metrics, byCode, loading: q.isPending };
}

/** Metric options, optionally limited to metric types (gauge, state, event, version). */
export function metricOptions(metrics: readonly Metric[], types?: readonly string[]): SelectOption[] {
  return metrics
    .filter((m) => !types || types.includes(m.type))
    .map((m) => ({ value: m.code, label: m.unit ? `${m.name} (${m.unit})` : m.name }));
}

/**
 * A list's site filter kept in the URL (`?site=`). With no choice in the URL it follows the global site
 * filter when exactly one site is selected there; "All sites" is stored as `all`.
 */
export function useSiteParam(): [number | undefined, (id: string) => void] {
  const { siteIds } = useSiteFilter();
  const [f, setF] = useUrlState({ site: '' });
  const fallback = siteIds.length === 1 ? siteIds[0] : undefined;
  const value = f.site === 'all' ? undefined : f.site === '' ? fallback : numberParam(f.site);
  return [value, (id: string) => setF({ site: id === '' ? 'all' : id })];
}

/** Users limited to some sites can't change things that apply to every site (baselines, rules, global limits). */
export function useUnrestricted(): boolean {
  const { user } = useAuth();
  return (user?.sites.length ?? 0) === 0;
}
