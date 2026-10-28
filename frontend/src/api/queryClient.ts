import { QueryClient } from '@tanstack/react-query';

import { ApiError } from './errors';

/** Retry transient failures only: never 4xx (except 408/429), at most twice. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= 2) return false;
  if (error instanceof ApiError) return error.status >= 500 || error.status === 408 || error.status === 429;
  return true;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        retry: shouldRetry,
        refetchOnWindowFocus: true,
      },
      mutations: { retry: false },
    },
  });
}

/**
 * Query keys. Every REST query key starts with its resource (the path segment after /api/v1/), so a mutation
 * or a live message can refresh a whole resource with one prefix: e.g. ['alerts'] covers alert lists,
 * details and counts; ['servers'] covers server lists, details, readings and events.
 */
export const queryKeys = {
  live: {
    server: (id: number) => ['live', 'server', id] as const,
    site: (id: number) => ['live', 'site', id] as const,
    alerts: ['live', 'alerts'] as const,
  },
  me: ['me'] as const,
  overview: ['overview'] as const,
  alerts: ['alerts'] as const,
  sites: ['sites'] as const,
  servers: ['servers'] as const,
  server: (id: number) => ['servers', id] as const,
  search: (q: string) => ['search', q] as const,
  supersetDashboards: ['superset', 'dashboards'] as const,
};
