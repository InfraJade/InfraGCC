import type { UseQueryResult } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { ApiError, errorMessage } from '@/api/errors';

import { Button } from './Button';
import { EmptyState } from './EmptyState';
import { GlassCard } from './GlassCard';
import { Icon } from './Icon';
import { Skeleton } from './Skeleton';

export interface QueryStateProps<T> {
  query: Pick<UseQueryResult<T>, 'data' | 'isPending' | 'isError' | 'error' | 'refetch'>;
  /** What is loading, for the error/404 text, e.g. "this server". */
  what: string;
  /** Loading placeholder (default: a card-sized skeleton). */
  skeleton?: ReactNode;
  children: (data: T) => ReactNode;
}

/**
 * Pending → skeleton, error → retry card (404 → "not found or not in your sites"), data → children.
 * Keeps showing stale data while a background refetch fails (the error is only shown with no data).
 */
export function QueryState<T>({ query, what, skeleton, children }: QueryStateProps<T>) {
  if (query.data !== undefined) return <>{children(query.data)}</>;
  if (query.isPending)
    return <>{skeleton ?? <Skeleton className="h-64 w-full rounded-xl" label={`Loading ${what}`} />}</>;
  return <QueryError error={query.error} what={what} onRetry={() => void query.refetch()} />;
}

export function QueryError({ error, what, onRetry }: { error: unknown; what: string; onRetry?: () => void }) {
  const notFound = error instanceof ApiError && (error.isNotFound || error.isForbidden);
  return (
    <GlassCard>
      {notFound ? (
        <EmptyState
          icon="circle-help"
          title={`We couldn't find ${what}`}
          description="It may have been removed, or it belongs to a site you don't have access to."
          action={
            <Link
              to="/"
              className="glass-subtle inline-flex h-9 items-center gap-2 rounded-md px-3.5 text-sm font-medium text-text hover:bg-text/10"
            >
              <Icon name="chevron-left" size={16} />
              Back to overview
            </Link>
          }
        />
      ) : (
        <EmptyState
          tone="error"
          title={`Couldn't load ${what}`}
          description={errorMessage(error)}
          action={
            onRetry ? (
              <Button icon="refresh" onClick={onRetry}>
                Retry
              </Button>
            ) : undefined
          }
        />
      )}
    </GlassCard>
  );
}
