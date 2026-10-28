import { useQueries, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';

import { useAuth } from '@/auth/AuthProvider';
import { liveUrl } from '@/config';
import { useDemoMode } from '@/demo/demoMode';
import { DemoLiveClient } from '@/demo/live';

import {
  LiveClient,
  type AlertMessage,
  type HealthChange,
  type LiveFeed,
  type LiveMessage,
  type LiveReading,
  type LiveStatus,
} from './live';
import { queryKeys } from './queryClient';

/** Live state of one server, kept in the TanStack Query cache under ['live','server',id]. */
export interface LiveServerState {
  serverId: number;
  /** Latest reading per `${metric}|${component}`. */
  readings: Record<string, LiveReading>;
  /** Latest health per `${metric}|${component}`. */
  health: Record<string, HealthChange>;
  serverHealth: string | null;
  updatedAt: number | null;
}

/** Live state of one site under ['live','site',id]. */
export interface LiveSiteState {
  siteId: number;
  /** Worst health per server id, as pushed by health messages. */
  serverHealth: Record<number, string>;
  lastAlert: AlertMessage | null;
  updatedAt: number | null;
}

export const readingKey = (metric: string, component: string) => `${metric}|${component}`;

export const emptyServer = (serverId: number): LiveServerState => ({
  serverId,
  readings: {},
  health: {},
  serverHealth: null,
  updatedAt: null,
});

export const emptySite = (siteId: number): LiveSiteState => ({
  siteId,
  serverHealth: {},
  lastAlert: null,
  updatedAt: null,
});

const MAX_RECENT_ALERTS = 50;

/** Fold one live message into the query cache. Exported for tests. */
export function applyLiveMessage(qc: QueryClient, msg: LiveMessage, now = Date.now()): void {
  if (msg.type === 'readings') {
    qc.setQueryData<LiveServerState>(queryKeys.live.server(msg.server_id), (prev) => {
      const base = prev ?? emptyServer(msg.server_id);
      const readings = { ...base.readings };
      for (const r of msg.readings) {
        const k = readingKey(r.metric, r.component);
        const old = readings[k];
        if (!old || Date.parse(r.time) >= Date.parse(old.time)) readings[k] = r;
      }
      return { ...base, readings, updatedAt: now };
    });
  } else if (msg.type === 'health') {
    qc.setQueryData<LiveServerState>(queryKeys.live.server(msg.server_id), (prev) => {
      const base = prev ?? emptyServer(msg.server_id);
      const health = { ...base.health };
      for (const c of msg.changes) health[readingKey(c.metric, c.component)] = c;
      return { ...base, health, serverHealth: msg.server_health, updatedAt: now };
    });
    qc.setQueryData<LiveSiteState>(queryKeys.live.site(msg.site_id), (prev) => {
      const base = prev ?? emptySite(msg.site_id);
      return {
        ...base,
        serverHealth: { ...base.serverHealth, [msg.server_id]: msg.server_health },
        updatedAt: now,
      };
    });
  } else {
    qc.setQueryData<AlertMessage[]>(queryKeys.live.alerts, (prev) =>
      [msg, ...(prev ?? []).filter((a) => a.alert_id !== msg.alert_id)].slice(0, MAX_RECENT_ALERTS),
    );
    if (msg.site_id !== null) {
      const siteId = msg.site_id;
      qc.setQueryData<LiveSiteState>(queryKeys.live.site(siteId), (prev) => ({
        ...(prev ?? emptySite(siteId)),
        lastAlert: msg,
        updatedAt: now,
      }));
    }
    // Alert lists/counters (and the per-site counts on the overview) refetch in the background.
    void qc.invalidateQueries({ queryKey: queryKeys.alerts });
    void qc.invalidateQueries({ queryKey: queryKeys.overview });
  }
}

const LiveContext = createContext<LiveFeed | null>(null);

/**
 * Owns the live WebSocket while a user is signed in: connects, re-authenticates on token renew, and feeds
 * every message into the query cache. In demo mode a simulated feed takes the socket's place. Screens use the
 * hooks below.
 */
export function LiveProvider({ children, client: injected }: { children: ReactNode; client?: LiveFeed }) {
  const auth = useAuth();
  const qc = useQueryClient();
  const demo = useDemoMode();
  const [client, setClient] = useState<LiveFeed | null>(injected ?? null);
  const signedIn = auth.status === 'authenticated';
  const { getAccessToken, renew, onTokenChange } = auth;

  useEffect(() => {
    if (injected) return;
    if (!signedIn) return;
    const c: LiveFeed = demo
      ? new DemoLiveClient()
      : new LiveClient({
          url: () => liveUrl(),
          getToken: getAccessToken,
          renewToken: renew,
          onError: (e) => {
            if (import.meta.env.DEV) console.warn('[live]', e);
          },
        });
    setClient(c);
    c.connect();
    return () => {
      c.close();
      setClient(null);
    };
    // getAccessToken/renew are read through the client only at call time; reconnecting on their identity
    // change would drop the socket on every auth state update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signedIn, injected, demo]);

  useEffect(() => {
    if (!client) return;
    const offMsg = client.onMessage((m) => applyLiveMessage(qc, m));
    const offToken = onTokenChange((token) => {
      if (token) void client.reauth(token);
    });
    return () => {
      offMsg();
      offToken();
    };
  }, [client, qc, onTokenChange]);

  return <LiveContext.Provider value={client}>{children}</LiveContext.Provider>;
}

export function useLiveClient(): LiveFeed | null {
  return useContext(LiveContext);
}

const noopSubscribe = () => () => undefined;

/** Connection status for the "live" indicator. */
export function useLiveStatus(): LiveStatus {
  const client = useLiveClient();
  return useSyncExternalStore(
    client ? (cb) => client.onStatus(cb) : noopSubscribe,
    () => client?.status ?? 'idle',
    () => 'idle',
  );
}

/** Subscribe to one server; returns its live readings/health (updated by pushed messages). */
export function useLiveServer(serverId: number | null | undefined): LiveServerState | null {
  const client = useLiveClient();
  const qc = useQueryClient();
  const enabled = typeof serverId === 'number';

  useEffect(() => {
    if (!client || typeof serverId !== 'number') return;
    return client.subscribe({ servers: [serverId] });
  }, [client, serverId]);

  const { data } = useQuery({
    queryKey: queryKeys.live.server(serverId ?? -1),
    queryFn: () =>
      qc.getQueryData<LiveServerState>(queryKeys.live.server(serverId ?? -1)) ?? emptyServer(serverId ?? -1),
    enabled,
    staleTime: Infinity,
    gcTime: 10 * 60_000,
  });
  return enabled ? (data ?? null) : null;
}

/** Subscribe to sites (overview, site view); returns live state per site id. */
export function useLiveSites(siteIds: readonly number[]): Record<number, LiveSiteState> {
  const client = useLiveClient();
  const qc = useQueryClient();
  const key = [...new Set(siteIds)].sort((a, b) => a - b).join(',');
  const ids = useMemo(() => (key ? key.split(',').map(Number) : []), [key]);

  useEffect(() => {
    if (!client || ids.length === 0) return;
    return client.subscribe({ sites: ids });
  }, [client, ids]);

  return useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKeys.live.site(id),
      queryFn: () => qc.getQueryData<LiveSiteState>(queryKeys.live.site(id)) ?? emptySite(id),
      staleTime: Infinity,
      gcTime: 10 * 60_000,
    })),
    combine: (results) => {
      const out: Record<number, LiveSiteState> = {};
      results.forEach((r, i) => {
        const id = ids[i];
        if (id !== undefined) out[id] = r.data ?? emptySite(id);
      });
      return out;
    },
  });
}

/** Recent pushed alert changes (newest first), e.g. for the alerts bell. */
export function useLiveAlerts(): AlertMessage[] {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: queryKeys.live.alerts,
    queryFn: () => qc.getQueryData<AlertMessage[]>(queryKeys.live.alerts) ?? [],
    staleTime: Infinity,
  });
  return data ?? [];
}
