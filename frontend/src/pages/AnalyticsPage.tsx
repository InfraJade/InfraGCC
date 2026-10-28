import { useQuery } from '@tanstack/react-query';
import { useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { useApi } from '@/api/ApiProvider';
import { errorMessage } from '@/api/errors';
import { queryKeys } from '@/api/queryClient';
import { Button } from '@/components/Button';
import { EmptyState } from '@/components/EmptyState';
import { GlassCard } from '@/components/GlassCard';
import { PageHeader } from '@/components/PageHeader';
import { Skeleton } from '@/components/Skeleton';
import { SupersetDashboard } from '@/components/SupersetDashboard';
import { Tabs } from '@/components/Tabs';
import { getConfig } from '@/config';
import { useDemoMode } from '@/demo/demoMode';

import { DemoDashboard } from './analytics/DemoAnalytics';

// Shapes from the build brief (switch to the generated `paths` types once openapi-app.json exists).
interface DashboardInfo {
  slug: string;
  title: string;
  embedded_uuid: string;
  refresh_s: number;
}
interface GuestToken {
  token: string;
  expires_at: string;
  superset_url: string;
}

/** Embedded Superset dashboards, one tab each (/analytics/:slug); in-app demo dashboards in demo mode. */
export default function AnalyticsPage() {
  const api = useApi();
  const navigate = useNavigate();
  const { slug } = useParams();
  const demo = useDemoMode();
  const dashboards = useQuery({
    queryKey: queryKeys.supersetDashboards,
    queryFn: () => api.json<DashboardInfo[]>('/api/v1/superset/dashboards'),
    staleTime: 10 * 60_000,
  });

  const list = dashboards.data ?? [];
  const active = list.find((d) => d.slug === slug) ?? list[0];

  const fetchGuestToken = useCallback(async () => {
    if (!active) throw new Error('No dashboard selected');
    const res = await api.json<GuestToken>('/api/v1/superset/guest-token', {
      method: 'POST',
      body: JSON.stringify({ dashboard: active.embedded_uuid }),
    });
    return res.token;
  }, [api, active]);

  return (
    <>
      <PageHeader
        title="Analytics"
        subtitle={
          demo
            ? 'Trends, capacity and health from the demo data'
            : 'Trends, capacity and health from Apache Superset'
        }
      />
      {dashboards.isPending ? (
        <Skeleton className="h-[60vh] w-full rounded-xl" label="Loading dashboards" />
      ) : dashboards.isError ? (
        <GlassCard>
          <EmptyState
            tone="error"
            title="Couldn't load the dashboard list"
            description={errorMessage(dashboards.error)}
            action={
              <Button icon="refresh" onClick={() => void dashboards.refetch()}>
                Retry
              </Button>
            }
          />
        </GlassCard>
      ) : !active ? (
        <GlassCard>
          <EmptyState icon="chart" title="No dashboards are available yet" />
        </GlassCard>
      ) : (
        <Tabs
          label="Dashboards"
          tabs={list.map((d) => ({ id: d.slug, label: d.title }))}
          value={active.slug}
          onChange={(id) => void navigate(`/analytics/${id}`)}
        >
          {() =>
            demo ? (
              <DemoDashboard slug={active.slug} />
            ) : (
              <SupersetDashboard
                key={active.embedded_uuid}
                embeddedUuid={active.embedded_uuid}
                supersetUrl={getConfig().supersetUrl}
                fetchGuestToken={fetchGuestToken}
                title={active.title}
              />
            )
          }
        </Tabs>
      )}
    </>
  );
}
