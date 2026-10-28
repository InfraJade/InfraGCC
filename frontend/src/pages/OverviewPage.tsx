import { Link } from 'react-router-dom';

import { EmptyState } from '@/components/EmptyState';
import { GlassCard } from '@/components/GlassCard';
import { Icon } from '@/components/Icon';
import { PageHeader } from '@/components/PageHeader';
import { QueryState } from '@/components/QueryState';
import { Age } from '@/components/Reading';
import { SkeletonCard } from '@/components/Skeleton';
import { useSiteFilter } from '@/components/shell/ShellContext';

import { RecentAlerts } from './overview/RecentAlerts';
import { SiteCard } from './overview/SiteCard';
import { TotalsRow } from './overview/TotalsRow';
import { useOverview } from './overview/useOverview';

function OverviewSkeleton() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true">
      <span className="sr-only">Loading the overview</span>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <SkeletonCard className="h-72" />
        <SkeletonCard className="h-72" />
      </div>
    </div>
  );
}

/** Global overview: every site with server counts, health, open alerts and power draw, updating live. */
export default function OverviewPage() {
  const { query, view } = useOverview();
  const { sites: allSites, siteIds } = useSiteFilter();
  const latest = view?.totals.freshness.latest_reading_at;

  return (
    <>
      <PageHeader
        title="Global overview"
        subtitle={
          view ? (
            <span>
              {view.filtered
                ? `${view.sites.length} of ${allSites.length || view.sites.length} sites (site filter on)`
                : `${view.sites.length} site${view.sites.length === 1 ? '' : 's'}`}
              {latest ? (
                <>
                  {' · latest reading '}
                  <Age time={latest} />
                </>
              ) : null}
            </span>
          ) : (
            'All sites at a glance'
          )
        }
        actions={
          <Link
            to="/wall"
            className="glass-subtle inline-flex h-9 items-center gap-2 rounded-md px-3.5 text-sm font-medium text-text hover:bg-text/10"
          >
            <Icon name="maximize" size={16} />
            Wall mode
          </Link>
        }
      />
      <QueryState query={query} what="the overview" skeleton={<OverviewSkeleton />}>
        {() =>
          view ? (
            <div className="flex flex-col gap-6">
              <TotalsRow totals={view.totals} />
              {view.sites.length === 0 ? (
                <GlassCard>
                  <EmptyState
                    icon="building"
                    title={siteIds.length ? 'No sites match the site filter' : 'No sites yet'}
                    description={
                      siteIds.length
                        ? 'Choose "All sites" in the top bar to see every site you have access to.'
                        : 'A platform admin adds sites under Admin → Sites & rooms.'
                    }
                  />
                </GlassCard>
              ) : (
                <section aria-label="Sites" className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
                  {view.sites.map((s) => (
                    <SiteCard key={s.id} site={s} />
                  ))}
                </section>
              )}
              <RecentAlerts />
            </div>
          ) : null
        }
      </QueryState>
    </>
  );
}
