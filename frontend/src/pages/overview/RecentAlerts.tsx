import { Link } from 'react-router-dom';

import { useApiQuery } from '@/api/hooks';
import type { Alert, Page } from '@/api/types';
import { AlertStateBadge, SeverityBadge } from '@/components/Badges';
import { EmptyState } from '@/components/EmptyState';
import { GlassCard } from '@/components/GlassCard';
import { Age } from '@/components/Reading';
import { Skeleton } from '@/components/Skeleton';
import { useSiteFilter } from '@/components/shell/ShellContext';
import { errorMessage } from '@/api/errors';
import { cn } from '@/lib/cn';

/**
 * Newest unresolved Critical/Warning alerts (refreshed every 30 s; live alert pushes refresh it too because
 * the key starts with 'alerts').
 */
export function RecentAlerts({ limit = 6, size = 'md' }: { limit?: number; size?: 'md' | 'wall' }) {
  const { siteIds } = useSiteFilter();
  const large = size === 'wall';
  const query = useApiQuery<Page<Alert>>(
    '/api/v1/alerts',
    {
      state: ['open', 'acknowledged'],
      severity: ['Critical', 'Warning'],
      muted: false,
      site_id: siteIds.length === 1 ? siteIds[0] : undefined,
      limit: siteIds.length > 1 ? limit * 3 : limit,
    },
    { refetchInterval: 30_000, staleTime: 10_000 },
  );
  const items = (query.data?.items ?? [])
    .filter((a) => siteIds.length <= 1 || (a.site !== null && siteIds.includes(a.site.id)))
    .slice(0, limit);

  return (
    <GlassCard
      as="section"
      padding={large ? 'lg' : 'md'}
      title={<span className={cn(large && 'text-lg wall:text-2xl')}>Latest critical and warning alerts</span>}
      actions={
        <Link to="/alerts" className="text-sm font-medium text-accent hover:underline">
          All alerts
        </Link>
      }
    >
      {query.isPending ? (
        <Skeleton lines={4} label="Loading alerts" />
      ) : query.isError && !query.data ? (
        <EmptyState tone="error" title="Couldn't load alerts" description={errorMessage(query.error)} />
      ) : items.length === 0 ? (
        <EmptyState icon="circle-check" title="No open critical or warning alerts" />
      ) : (
        <ul className="divide-y divide-text/10">
          {items.map((a) => (
            <li key={a.id}>
              <Link
                to={`/alerts?id=${a.id}`}
                className={cn(
                  'flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md px-2 py-2.5 hover:bg-text/5',
                  large && 'py-3.5',
                )}
              >
                <SeverityBadge severity={a.severity} />
                <span
                  className={cn(
                    'min-w-0 flex-1 truncate font-medium text-text',
                    large && 'text-lg wall:text-xl',
                  )}
                >
                  {a.title}
                </span>
                <span className="text-sm text-text-muted">
                  {[a.server?.name, a.site?.code].filter(Boolean).join(' · ')}
                </span>
                {a.state === 'acknowledged' ? <AlertStateBadge state={a.state} /> : null}
                <span className="text-xs text-text-subtle">
                  opened <Age time={a.opened_at} />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </GlassCard>
  );
}
