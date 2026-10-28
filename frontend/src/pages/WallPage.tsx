import { EmptyState } from '@/components/EmptyState';
import { GlassCard } from '@/components/GlassCard';
import { QueryState } from '@/components/QueryState';
import { Age } from '@/components/Reading';
import { SkeletonCard } from '@/components/Skeleton';
import { WallLayout } from '@/components/shell/WallLayout';

import { RecentAlerts } from './overview/RecentAlerts';
import { SiteCard } from './overview/SiteCard';
import { TotalsRow } from './overview/TotalsRow';
import { useOverview } from './overview/useOverview';

/**
 * NOC wall screen: the global overview in full-screen mode at wall scale (large type, no sidebar), refreshed
 * every 30 s and on live pushes. Honors the global site filter, so one wall can show one site.
 */
export default function WallPage() {
  const { query, view } = useOverview();
  const latest = view?.totals.freshness.latest_reading_at;
  return (
    <WallLayout
      title={view?.filtered ? `Overview: ${view.sites.map((s) => s.code).join(', ')}` : 'Global overview'}
    >
      <QueryState
        query={query}
        what="the overview"
        skeleton={
          <div className="grid gap-6 lg:grid-cols-2" aria-busy="true">
            <SkeletonCard className="h-80" />
            <SkeletonCard className="h-80" />
          </div>
        }
      >
        {() =>
          view ? (
            <div className="flex flex-col gap-6 wall:gap-8">
              <TotalsRow totals={view.totals} size="lg" />
              {view.sites.length === 0 ? (
                <GlassCard padding="lg">
                  <EmptyState icon="building" title="No sites to show" />
                </GlassCard>
              ) : (
                <section aria-label="Sites" className="grid gap-6 lg:grid-cols-2 wall:grid-cols-3 wall:gap-8">
                  {view.sites.map((s) => (
                    <SiteCard key={s.id} site={s} size="wall" />
                  ))}
                </section>
              )}
              <RecentAlerts size="wall" limit={8} />
              {latest ? (
                <p className="text-right text-sm text-text-subtle">
                  Latest reading <Age time={latest} /> · refreshes every 30 s and on live updates
                </p>
              ) : null}
            </div>
          ) : null
        }
      </QueryState>
    </WallLayout>
  );
}
