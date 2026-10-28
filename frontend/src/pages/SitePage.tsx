import { useParams } from 'react-router-dom';

import { useApiQuery } from '@/api/hooks';
import { useLiveSites } from '@/api/LiveProvider';
import type { AlertCounts, SiteDetail } from '@/api/types';
import { OnlineBadge } from '@/components/Badges';
import { EmptyState } from '@/components/EmptyState';
import { GlassCard } from '@/components/GlassCard';
import { HealthBadge } from '@/components/HealthBadge';
import { PageHeader } from '@/components/PageHeader';
import { QueryState } from '@/components/QueryState';
import { Age } from '@/components/Reading';
import { Skeleton, SkeletonCard } from '@/components/Skeleton';
import { StatTile } from '@/components/StatTile';
import { formatNumber, formatValue } from '@/lib/format';
import { idParam } from '@/lib/useUrlState';
import { NotFoundState, useThrottledRefetch } from '@/pages/server/common';
import { RoomCard } from '@/pages/site/RoomCard';

const REFRESH_MS = 60_000;
const LIVE_THROTTLE_MS = 10_000;

export default function SitePage() {
  const siteId = idParam(useParams().siteId);
  if (siteId === null) {
    return (
      <>
        <PageHeader title="Site" breadcrumbs={[{ label: 'Overview', to: '/' }, { label: 'Site' }]} />
        <NotFoundState what="this site" />
      </>
    );
  }
  return <SiteView siteId={siteId} />;
}

function SiteView({ siteId }: { siteId: number }) {
  const query = useApiQuery<SiteDetail>(`/api/v1/sites/${siteId}`, undefined, {
    refetchInterval: REFRESH_MS,
  });
  const live = useLiveSites([siteId])[siteId];
  const { refetch } = query;
  // A health/alert push for this site → refresh its rollups (at most every 10 s).
  useThrottledRefetch(live?.updatedAt, () => void refetch(), LIVE_THROTTLE_MS);

  return (
    <QueryState query={query} what="this site" skeleton={<SiteSkeleton />}>
      {(site) => <SiteBody site={site} fetchedAt={query.dataUpdatedAt} />}
    </QueryState>
  );
}

function SiteBody({ site, fetchedAt }: { site: SiteDetail; fetchedAt: number }) {
  const alerts: Partial<AlertCounts> = site.alerts ?? {};
  const critical = alerts.critical ?? 0;
  const warning = alerts.warning ?? 0;
  const info = alerts.info ?? 0;
  const latest = site.freshness?.latest_reading_at ?? null;
  const capacity = site.rack_power_capacity_w ?? null;
  const power = site.power_w ?? null;
  const pct = capacity && power !== null ? (power / capacity) * 100 : null;
  const rooms = site.rooms ?? [];
  const collectors = site.collectors ?? [];
  const stale = site.freshness?.servers_stale ?? 0;

  return (
    <>
      <PageHeader
        title={
          <>
            <span className="font-mono text-text-muted">{site.code}</span> {site.name}
          </>
        }
        badge={<HealthBadge health={site.worst_health} context={`Site ${site.code}`} />}
        breadcrumbs={[{ label: 'Overview', to: '/' }, { label: `${site.code} ${site.name}` }]}
        subtitle={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>
              {site.city}, {site.country}
            </span>
            <span className="text-text-subtle">{site.timezone}</span>
            <span className="flex items-center gap-1">
              Latest reading{' '}
              {latest ? <Age time={latest} /> : <span className="text-text-subtle">none yet</span>}
            </span>
            {stale > 0 ? (
              <span className="text-health-warning">
                {stale} server{stale === 1 ? '' : 's'} not reporting
              </span>
            ) : null}
          </span>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <StatTile
          label="Servers"
          icon="server"
          value={site.server_count ?? 0}
          time={fetchedAt || null}
          footnote={`${site.servers_in_maintenance ?? 0} in maintenance`}
        />
        <StatTile
          label="Open alerts"
          icon="bell"
          value={critical + warning + info}
          time={fetchedAt || null}
          to={`/alerts?site_id=${site.id}`}
          footnote={`${critical} critical · ${warning} warning · ${info} info`}
        />
        <StatTile
          label="Power draw"
          icon="zap"
          value={power}
          unit="W"
          time={latest}
          footnote={
            capacity
              ? `of ${formatValue(capacity, 'W')} rack capacity${pct !== null ? ` (${formatNumber(pct, 0)} %)` : ''}`
              : 'no rack capacity set'
          }
        />
        <StatTile
          label="Inlet average"
          icon="thermometer"
          value={site.inlet_avg_c ?? null}
          unit="°C"
          time={latest}
          footnote={`max ${formatValue(site.inlet_max_c ?? null, '°C')}`}
        />
        <StatTile
          label="Collectors online"
          icon="activity"
          value={site.collectors_online ?? 0}
          time={fetchedAt || null}
          footnote={`of ${site.collectors_total ?? 0}`}
        />
      </div>

      <h2 className="mb-3 mt-8 text-sm font-semibold uppercase tracking-wider text-text-muted">Rooms</h2>
      {rooms.length === 0 ? (
        <GlassCard>
          <EmptyState
            icon="building"
            title="No rooms at this site yet"
            description="DC engineers add rooms and racks under Admin, then onboard servers into them."
          />
        </GlassCard>
      ) : (
        <div className="flex flex-col gap-4">
          {rooms.map((room) => (
            <RoomCard key={room.id} room={room} readingTime={latest} />
          ))}
        </div>
      )}

      <GlassCard as="section" className="mt-6" title="Collectors" aria-label="Collectors">
        {collectors.length === 0 ? (
          <EmptyState
            icon="server"
            title="No collectors at this site"
            description="A collector polls the BMCs at this site; platform admins register them under Admin."
          />
        ) : (
          <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {collectors.map((c) => (
              <li
                key={c.id}
                className="glass-subtle flex items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm"
              >
                <span className="truncate font-medium text-text">{c.name}</span>
                <OnlineBadge online={c.online} />
              </li>
            ))}
          </ul>
        )}
      </GlassCard>
    </>
  );
}

function SiteSkeleton() {
  return (
    <div aria-busy="true">
      <span className="sr-only">Loading this site</span>
      <Skeleton className="mb-2 h-3 w-40" />
      <Skeleton className="mb-6 h-8 w-72" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {Array.from({ length: 5 }, (_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
      <Skeleton className="mt-8 h-64 w-full rounded-xl" />
    </div>
  );
}
