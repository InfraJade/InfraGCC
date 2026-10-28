import { useState } from 'react';
import { useParams } from 'react-router-dom';

import { useApiQuery, useCan } from '@/api/hooks';
import { useLiveServer, type LiveServerState } from '@/api/LiveProvider';
import type { ServerDetail } from '@/api/types';
import { Pill, ServerStatusBadge } from '@/components/Badges';
import { Button } from '@/components/Button';
import { HealthBadge } from '@/components/HealthBadge';
import { PageHeader, type Breadcrumb } from '@/components/PageHeader';
import { QueryState } from '@/components/QueryState';
import { Age } from '@/components/Reading';
import { Skeleton } from '@/components/Skeleton';
import { Tabs, type TabItem } from '@/components/Tabs';
import { healthClasses } from '@/lib/health';
import { idParam, useUrlState } from '@/lib/useUrlState';
import { ChartsTab } from '@/pages/server/ChartsTab';
import { NotFoundState } from '@/pages/server/common';
import { EditServerDialog } from '@/pages/server/EditServerDialog';
import { EventsTab } from '@/pages/server/EventsTab';
import { FactsCard } from '@/pages/server/FactsCard';
import { FirmwareTab } from '@/pages/server/FirmwareTab';
import { InventoryTab } from '@/pages/server/InventoryTab';
import { OverviewTab } from '@/pages/server/OverviewTab';

const REFRESH_MS = 60_000;
const TAB_IDS = ['overview', 'charts', 'inventory', 'firmware', 'events'] as const;
type TabId = (typeof TAB_IDS)[number];

export default function ServerPage() {
  const serverId = idParam(useParams().serverId);
  if (serverId === null) {
    return (
      <>
        <PageHeader title="Server" breadcrumbs={[{ label: 'Overview', to: '/' }, { label: 'Server' }]} />
        <NotFoundState what="this server" />
      </>
    );
  }
  return <ServerScreen serverId={serverId} />;
}

function ServerScreen({ serverId }: { serverId: number }) {
  const query = useApiQuery<ServerDetail>(`/api/v1/servers/${serverId}`, undefined, {
    refetchInterval: REFRESH_MS,
  });
  const live = useLiveServer(serverId);
  return (
    <QueryState query={query} what="this server" skeleton={<ServerSkeleton />}>
      {(server) => <ServerBody server={server} live={live} />}
    </QueryState>
  );
}

function ServerBody({ server, live }: { server: ServerDetail; live: LiveServerState | null }) {
  const can = useCan();
  const [editing, setEditing] = useState(false);
  const [url, setUrl] = useUrlState({ tab: 'overview', range: '24h' });
  const tab: TabId = (TAB_IDS as readonly string[]).includes(url.tab) ? (url.tab as TabId) : 'overview';
  const health = live?.serverHealth ?? server.health;
  const alertCount = server.active_alerts.length;
  const offBaseline = server.firmware.filter((f) => f.compliant === false).length;
  const installed = server.components.filter((c) => !c.removed_at).length;

  const breadcrumbs: Breadcrumb[] = [
    { label: 'Overview', to: '/' },
    { label: server.site.code, to: `/sites/${server.site.id}` },
  ];
  if (server.rack) breadcrumbs.push({ label: `Rack ${server.rack.name}`, to: `/racks/${server.rack.id}` });
  breadcrumbs.push({ label: server.name });

  const tabs: TabItem[] = [
    {
      id: 'overview',
      label: 'Overview',
      badge: alertCount ? (
        <Pill className={healthClasses.Critical.soft} title={`${alertCount} active alerts`}>
          {alertCount}
        </Pill>
      ) : undefined,
    },
    { id: 'charts', label: 'Charts' },
    {
      id: 'inventory',
      label: 'Inventory',
      badge: <span className="text-xs text-text-subtle">{installed}</span>,
    },
    {
      id: 'firmware',
      label: 'Firmware',
      badge: offBaseline ? (
        <Pill className={healthClasses.Warning.soft} title={`${offBaseline} off baseline`}>
          {offBaseline}
        </Pill>
      ) : undefined,
    },
    { id: 'events', label: 'Events' },
  ];

  return (
    <>
      <PageHeader
        title={server.name}
        badge={
          <span className="flex flex-wrap items-center gap-2">
            <HealthBadge health={health} context={server.name} />
            <ServerStatusBadge status={server.status} />
          </span>
        }
        breadcrumbs={breadcrumbs}
        subtitle={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>
              {[server.vendor, server.model].filter(Boolean).join(' ') || 'Model not yet discovered'}
            </span>
            <span className="flex items-center gap-1">
              Last seen{' '}
              {server.last_seen_at ? (
                <Age time={server.last_seen_at} />
              ) : (
                <span className="text-text-subtle">never</span>
              )}
            </span>
          </span>
        }
        actions={
          can('onboard_servers') ? (
            <Button icon="sliders" onClick={() => setEditing(true)}>
              Edit
            </Button>
          ) : null
        }
      />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 xl:order-2">
          <FactsCard server={server} />
        </div>
        <div className="min-w-0 xl:order-1">
          <Tabs
            label="Server sections"
            tabs={tabs}
            value={tab}
            onChange={(id) => setUrl({ tab: id === 'overview' ? null : id })}
          >
            {(active) => {
              switch (active as TabId) {
                case 'charts':
                  return (
                    <ChartsTab
                      serverId={server.id}
                      range={url.range}
                      onRangeChange={(r) => setUrl({ range: r === '24h' ? null : r })}
                    />
                  );
                case 'inventory':
                  return <InventoryTab components={server.components} />;
                case 'firmware':
                  return <FirmwareTab firmware={server.firmware} />;
                case 'events':
                  return <EventsTab serverId={server.id} />;
                default:
                  return (
                    <OverviewTab
                      readings={server.latest_readings}
                      healthParts={server.health_parts}
                      alerts={server.active_alerts}
                      live={live}
                    />
                  );
              }
            }}
          </Tabs>
        </div>
      </div>

      {can('onboard_servers') ? (
        <EditServerDialog server={server} open={editing} onClose={() => setEditing(false)} />
      ) : null}
    </>
  );
}

function ServerSkeleton() {
  return (
    <div aria-busy="true">
      <span className="sr-only">Loading this server</span>
      <Skeleton className="mb-2 h-3 w-56" />
      <Skeleton className="mb-6 h-8 w-64" />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="flex flex-col gap-4 xl:order-1">
          <Skeleton className="h-9 w-80 rounded-lg" />
          <Skeleton className="h-72 w-full rounded-xl" />
        </div>
        <Skeleton className="h-96 w-full rounded-xl xl:order-2" />
      </div>
    </div>
  );
}
