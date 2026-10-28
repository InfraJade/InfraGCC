/**
 * Data hooks shared by every screen.
 *
 * - `useApiQuery(path, query)`: one GET, keyed `[resource, 'get', path, query]`.
 * - `useCursorList(path, query)`: a cursor-paginated list (`{items, next_cursor}`) as an infinite query, with
 *   `tableProps` ready to spread into <DataTable>.
 * - `useApiMutation(fn, {invalidate})`: a write that refreshes the given resources afterwards and toasts errors.
 * - `useMe()` / `useCan()`: the signed-in user's capabilities from `GET /api/v1/me` (the API enforces the same
 *   rules; the UI only hides what the user can't do).
 * - `downloadCsv()`: authenticated CSV export saved as a file.
 */
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryKey,
  type UseQueryOptions,
} from '@tanstack/react-query';
import { useCallback } from 'react';

import { useAuth } from '@/auth/AuthProvider';
import type { Role } from '@/auth/roles';
import { useToast } from '@/components/Toast';

import { useApi } from './ApiProvider';
import type { Api } from './client';
import { errorMessage, parseProblemResponse } from './errors';
import { queryKeys } from './queryClient';
import type { Capability, Me, Page, QueryParams } from './types';

const API_PREFIX = '/api/v1/';

/** '/api/v1/alert-rules/3' → 'alert-rules'; '/api/v1/firmware/compliance' → 'firmware'. */
export function resourceOf(path: string): string {
  const rest = path.startsWith(API_PREFIX) ? path.slice(API_PREFIX.length) : path.replace(/^\/+/, '');
  return rest.split(/[/?]/)[0] ?? rest;
}

/** Drop empty values so equivalent filters share a cache entry. */
export function cleanQuery(query: QueryParams | undefined): QueryParams {
  const out: QueryParams = {};
  if (!query) return out;
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === '') continue;
    if (Array.isArray(v) && v.length === 0) continue;
    out[k] = v;
  }
  return out;
}

export function apiKey(path: string, query?: QueryParams): QueryKey {
  return [resourceOf(path), 'get', path, cleanQuery(query)];
}

type QueryOpts<T> = Omit<UseQueryOptions<T, Error, T, QueryKey>, 'queryKey' | 'queryFn'>;

/** GET one resource. Pass `enabled: false` (or a null path) to wait for an id. */
export function useApiQuery<T>(path: string | null, query?: QueryParams, options: QueryOpts<T> = {}) {
  const api = useApi();
  return useQuery<T, Error, T, QueryKey>({
    queryKey: path ? apiKey(path, query) : ['disabled'],
    queryFn: ({ signal }) => api.json<T>(path ?? '', { query: cleanQuery(query), signal }),
    ...options,
    enabled: path !== null && (options.enabled ?? true),
  });
}

export interface CursorListOptions {
  /** Page size (API default 50, max 500). */
  limit?: number;
  enabled?: boolean;
  /** Background refresh, e.g. 30 s for alert lists. */
  refetchInterval?: number | false;
  staleTime?: number;
}

/** A cursor-paginated list as an infinite query; `tableProps` plugs straight into <DataTable>. */
export function useCursorList<T>(path: string, query?: QueryParams, options: CursorListOptions = {}) {
  const api = useApi();
  const q = cleanQuery(query);
  const limit = options.limit ?? 50;
  const result = useInfiniteQuery({
    queryKey: [resourceOf(path), 'list', path, q, limit],
    queryFn: ({ pageParam, signal }) =>
      api.json<Page<T>>(path, { query: { ...q, limit, cursor: pageParam }, signal }),
    initialPageParam: null as string | null,
    getNextPageParam: (last: Page<T>) => last.next_cursor ?? null,
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
    refetchInterval: options.refetchInterval,
    staleTime: options.staleTime,
  });
  const items: T[] = result.data?.pages.flatMap((p) => p.items) ?? [];
  const { fetchNextPage, refetch } = result;
  const loadMore = useCallback(() => void fetchNextPage(), [fetchNextPage]);
  const retry = useCallback(() => void refetch(), [refetch]);
  return {
    ...result,
    items,
    /** The first page (some lists carry extras on it, e.g. the compliance summary). */
    firstPage: result.data?.pages[0],
    tableProps: {
      rows: items,
      loading: result.isPending,
      error: result.error,
      onRetry: retry,
      hasMore: result.hasNextPage,
      onLoadMore: loadMore,
      loadingMore: result.isFetchingNextPage,
    },
  };
}

/** Fetch every page of a (small) list, e.g. sites, rooms or racks for a picker. Max 2,000 rows. */
export async function fetchAll<T>(api: Api, path: string, query?: QueryParams, signal?: AbortSignal) {
  const out: T[] = [];
  let cursor: string | null = null;
  for (let i = 0; i < 4; i++) {
    const page: Page<T> = await api.json<Page<T>>(path, {
      query: { ...cleanQuery(query), limit: 500, cursor },
      signal,
    });
    out.push(...page.items);
    cursor = page.next_cursor ?? null;
    if (!cursor) break;
  }
  return out;
}

/** Every item of a small list (pickers, lookups), cached for a minute. */
export function useAllItems<T>(
  path: string | null,
  query?: QueryParams,
  options: { enabled?: boolean } = {},
) {
  const api = useApi();
  const q = cleanQuery(query);
  return useQuery({
    queryKey: path ? [resourceOf(path), 'all', path, q] : ['disabled'],
    queryFn: ({ signal }) => fetchAll<T>(api, path ?? '', q, signal),
    enabled: path !== null && (options.enabled ?? true),
    staleTime: 60_000,
  });
}

export interface MutationOptions<R> {
  /** Resources or query-key prefixes to refresh afterwards, e.g. ['racks', 'sites']. */
  invalidate?: (string | QueryKey)[];
  /** Toast on success (string or built from the result). */
  success?: string | ((result: R) => string);
  /** Toast errors (default true). Forms that show field errors inline pass false. */
  toastErrors?: boolean;
  onSuccess?: (result: R) => void;
}

/** A write: runs `fn(api, vars)`, refreshes the listed resources, toasts the outcome. */
export function useApiMutation<V, R = unknown>(
  fn: (api: Api, vars: V) => Promise<R>,
  options: MutationOptions<R> = {},
) {
  const api = useApi();
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation<R, Error, V>({
    mutationFn: (vars) => fn(api, vars),
    onSuccess: async (result) => {
      await Promise.all(
        (options.invalidate ?? []).map((k) =>
          qc.invalidateQueries({ queryKey: typeof k === 'string' ? [k] : k }),
        ),
      );
      if (options.success)
        toast({
          tone: 'success',
          title: typeof options.success === 'string' ? options.success : options.success(result),
        });
      options.onSuccess?.(result);
    },
    onError: (err) => {
      if (options.toastErrors !== false)
        toast({ tone: 'error', title: "That didn't work", description: errorMessage(err) });
    },
  });
}

/** JSON body helper for mutations: `api.json(path, send('POST', body))`. */
export function send(method: 'POST' | 'PUT' | 'PATCH' | 'DELETE', body?: unknown): RequestInit {
  return body === undefined ? { method } : { method, body: JSON.stringify(body) };
}

// ---- who am I / what may I do ----

/** Minimum role per capability: mirrors backend `app.core.security.capabilities`, used until /me loads. */
const CAPABILITY_ROLES: Record<string, Role> = {
  view: 'viewer',
  ack_alerts: 'noc_operator',
  comment_alerts: 'noc_operator',
  resolve_alerts: 'noc_operator',
  onboard_servers: 'dc_engineer',
  edit_racks: 'dc_engineer',
  edit_maintenance: 'dc_engineer',
  edit_baselines: 'dc_engineer',
  edit_sites: 'platform_admin',
  edit_collectors: 'platform_admin',
  edit_thresholds: 'platform_admin',
  edit_alert_rules: 'platform_admin',
  edit_alert_routes: 'platform_admin',
  view_users: 'platform_admin',
  view_audit: 'platform_admin',
  superset_editor: 'analyst',
};

export function useMe() {
  const api = useApi();
  const { status } = useAuth();
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: ({ signal }) => api.json<Me>('/api/v1/me', { signal }),
    enabled: status === 'authenticated',
    staleTime: 5 * 60_000,
  });
}

/** `can('ack_alerts')`: the server's answer from /me, or the role rule while /me is loading. */
export function useCan(): (capability: Capability) => boolean {
  const me = useMe();
  const { hasRole } = useAuth();
  const caps = me.data?.capabilities;
  return useCallback(
    (capability: Capability) => {
      if (caps && capability in caps) return caps[capability] === true;
      const role = CAPABILITY_ROLES[capability];
      return role ? hasRole(role) : false;
    },
    [caps, hasRole],
  );
}

// ---- CSV export ----

/** Download an authenticated CSV export (the API needs the bearer token, so a plain link won't do). */
export async function downloadCsv(api: Api, path: string, query: QueryParams, fallbackName: string) {
  const res = await api.fetch(
    new Request(api.url(path, cleanQuery(query)), { headers: { Accept: 'text/csv' } }),
  );
  if (!res.ok) throw await parseProblemResponse(res);
  const blob = await res.blob();
  const disposition = res.headers.get('content-disposition') ?? '';
  const name = /filename="?([^";]+)"?/i.exec(disposition)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
