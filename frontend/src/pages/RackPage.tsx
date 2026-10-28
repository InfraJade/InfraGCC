import { useMemo } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { useApiQuery } from '@/api/hooks';
import { useLiveSites } from '@/api/LiveProvider';
import type { RackDetail } from '@/api/types';
import { GlassCard } from '@/components/GlassCard';
import { HealthBadge } from '@/components/HealthBadge';
import { KeyValueList } from '@/components/KeyValue';
import { PageHeader } from '@/components/PageHeader';
import { QueryState } from '@/components/QueryState';
import { RackView, type RackServer as RackViewServer } from '@/components/RackView';
import { Reading } from '@/components/Reading';
import { Skeleton } from '@/components/Skeleton';
import { formatNumber, formatValue, toMillis } from '@/lib/format';
import { worstHealth } from '@/lib/health';
import { idParam } from '@/lib/useUrlState';
import { RackServersTable, type RackRow } from '@/pages/rack/RackServersTable';
import { NotFoundState } from '@/pages/server/common';

const REFRESH_MS = 60_000;

export default function RackPage() {
  const rackId = idParam(useParams().rackId);
  if (rackId === null) {
    return (
      <>
        <PageHeader title="Rack" breadcrumbs={[{ label: 'Overview', to: '/' }, { label: 'Rack' }]} />
        <NotFoundState what="this rack" />
      </>
    );
  }
  return <RackScreen rackId={rackId} />;
}

function RackScreen({ rackId }: { rackId: number }) {
  const query = useApiQuery<RackDetail>(`/api/v1/racks/${rackId}`, undefined, {
    refetchInterval: REFRESH_MS,
  });
  return (
    <QueryState query={query} what="this rack" skeleton={<RackSkeleton />}>
      {(rack) => <RackBody rack={rack} />}
    </QueryState>
  );
}

function RackBody({ rack }: { rack: RackDetail }) {
  const navigate = useNavigate();
  const live = useLiveSites([rack.site.id])[rack.site.id];
  const liveHealth = live?.serverHealth;

  const rows: RackRow[] = useMemo(
    () => rack.servers.map((s) => ({ ...s, liveHealth: liveHealth?.[s.id] ?? s.health })),
    [rack.servers, liveHealth],
  );

  const elevation: RackViewServer[] = useMemo(
    () =>
      rows
        .filter((s): s is RackRow & { position_u: number } => s.position_u !== null)
        .map((s) => ({
          id: s.id,
          name: s.name,
          positionU: s.position_u,
          heightU: s.height_u,
          health: s.liveHealth,
          inletTempC: s.inlet_temp?.value ?? null,
          inletTime: s.inlet_temp?.time ?? null,
          model: [s.vendor, s.model].filter(Boolean).join(' ') || undefined,
          status: s.status,
        })),
    [rows],
  );

  const unplaced = rows.length - elevation.length;
  // Recomputed from the live-overlaid servers, so a pushed health change shows before the next refetch.
  const worst = rows.length ? worstHealth(rows.map((r) => r.liveHealth)) : rack.worst_health;
  const powerTime = latestTime(rack.servers.map((s) => s.power?.time));
  const capacity = rack.power_capacity_w;
  const pct = capacity && rack.power_w !== null ? (rack.power_w / capacity) * 100 : null;
  const label = `${rack.site.code} ${rack.room.name} ${rack.name}`;

  return (
    <>
      <PageHeader
        title={`Rack ${rack.name}`}
        badge={<HealthBadge health={worst} context={`Rack ${rack.name}`} />}
        subtitle={`${rack.site.name} · ${rack.room.name}${rack.row ? ` · Row ${rack.row}` : ''}`}
        breadcrumbs={[
          { label: 'Overview', to: '/' },
          { label: rack.site.code, to: `/sites/${rack.site.id}` },
          { label: `Rack ${rack.name}` },
        ]}
      />

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        <GlassCard as="section" title="Elevation" aria-label={`Elevation of ${label}`}>
          <RackView
            name={rack.name}
            heightU={rack.height_u}
            servers={elevation}
            onServerClick={(s) => navigate(`/servers/${s.id}`)}
            className="mx-auto"
          />
          {unplaced > 0 ? (
            <p className="mt-3 text-xs text-text-muted">
              {unplaced} server{unplaced === 1 ? ' has' : 's have'} no U position and{' '}
              {unplaced === 1 ? 'is' : 'are'} listed in the table only.
            </p>
          ) : null}
        </GlassCard>

        <div className="flex min-w-0 flex-col gap-6">
          <GlassCard as="section" title="Rack facts" aria-label="Rack facts">
            <KeyValueList
              columns={2}
              items={[
                {
                  label: 'Site',
                  value: (
                    <Link to={`/sites/${rack.site.id}`} className="text-accent hover:underline">
                      {rack.site.code} {rack.site.name}
                    </Link>
                  ),
                },
                { label: 'Room', value: rack.room.name },
                { label: 'Row', value: rack.row },
                { label: 'Height', value: `${rack.height_u} U` },
                { label: 'Used', value: `${rack.used_u} U` },
                { label: 'Free', value: `${rack.free_u} U` },
                {
                  label: 'Power draw',
                  value: (
                    <span className="flex flex-col">
                      <Reading value={rack.power_w} unit="W" time={powerTime} />
                      <span className="text-xs text-text-muted">
                        {capacity
                          ? `of ${formatValue(capacity, 'W')} capacity${pct !== null ? ` (${formatNumber(pct, 0)} %)` : ''}`
                          : 'no capacity set'}
                      </span>
                    </span>
                  ),
                },
                { label: 'Worst health', value: <HealthBadge health={worst} size="sm" /> },
              ]}
            />
          </GlassCard>

          <RackServersTable rows={rows} rackName={rack.name} />
        </div>
      </div>
    </>
  );
}

function latestTime(times: (string | undefined)[]): string | null {
  let best: string | null = null;
  for (const t of times) {
    if (t && (best === null || toMillis(t) > toMillis(best))) best = t;
  }
  return best;
}

function RackSkeleton() {
  return (
    <div aria-busy="true">
      <span className="sr-only">Loading this rack</span>
      <Skeleton className="mb-2 h-3 w-40" />
      <Skeleton className="mb-6 h-8 w-56" />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        <Skeleton className="h-[32rem] w-full rounded-xl" />
        <div className="flex flex-col gap-6">
          <Skeleton className="h-40 w-full rounded-xl" />
          <Skeleton className="h-72 w-full rounded-xl" />
        </div>
      </div>
    </div>
  );
}
