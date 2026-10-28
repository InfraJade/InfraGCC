import { useMemo } from 'react';

import { useCan, useCursorList } from '@/api/hooks';
import type { Alert, AlertState, Severity } from '@/api/types';
import { Button } from '@/components/Button';
import { DataTable } from '@/components/DataTable';
import { FormField, Select } from '@/components/FormField';
import { GlassCard } from '@/components/GlassCard';
import { PageHeader } from '@/components/PageHeader';
import { useSiteFilter } from '@/components/shell/ShellContext';
import { numberParam, useUrlState } from '@/lib/useUrlState';

import { AlertDrawer } from './alerts/AlertDrawer';
import { alertColumns } from './alerts/columns';
import {
  DateTimeField,
  listSummary,
  localToIso,
  parseList,
  resolveSite,
  SearchField,
  SegmentedControl,
  SiteSelect,
  ToggleGroup,
} from './alerts/filterControls';
import { useAlertAction, useMetricUnits } from './alerts/useAlertActions';

type View = 'active' | 'resolved' | 'all';

const VIEW_STATES: Record<View, AlertState[] | undefined> = {
  active: ['open', 'acknowledged'],
  resolved: ['resolved'],
  all: undefined,
};
const SEVERITIES: readonly Severity[] = ['Critical', 'Warning', 'Info'];

const DEFAULTS = {
  view: 'active',
  severity: '',
  site_id: '',
  muted: '',
  q: '',
  from: '',
  to: '',
  id: '',
};

export default function AlertsPage() {
  const [f, setF] = useUrlState(DEFAULTS);
  const { siteIds } = useSiteFilter();
  const can = useCan();
  const units = useMetricUnits();

  const view: View = f.view === 'resolved' || f.view === 'all' ? f.view : 'active';
  const severities = parseList(f.severity, SEVERITIES);
  const site = resolveSite(f.site_id, siteIds);
  const query = {
    state: VIEW_STATES[view],
    severity: severities,
    site_id: site.siteId,
    muted: f.muted === 'muted' ? true : f.muted === 'unmuted' ? false : undefined,
    q: f.q || undefined,
    from: localToIso(f.from),
    to: localToIso(f.to),
  };
  const list = useCursorList<Alert>('/api/v1/alerts', query, { refetchInterval: 30_000 });
  const clientSites = site.clientSiteIds;
  const rows = useMemo(
    () =>
      clientSites ? list.items.filter((a) => a.site !== null && clientSites.includes(a.site.id)) : list.items,
    [list.items, clientSites],
  );

  const { mutate: ack, isPending: acking, variables: ackVars } = useAlertAction();
  const ackingId = acking ? (ackVars?.id ?? null) : null;
  const canAck = can('ack_alerts');
  const columns = useMemo(
    () => alertColumns({ units, canAck, ackingId, onQuickAck: (a) => ack({ id: a.id, action: 'ack' }) }),
    [units, canAck, ackingId, ack],
  );

  const selectedId = numberParam(f.id) ?? null;
  const filtered =
    severities.length > 0 || f.site_id !== '' || f.muted !== '' || f.q !== '' || f.from !== '' || f.to !== '';

  return (
    <div>
      <PageHeader
        title="Alerts"
        subtitle="Open and past alerts. The list refreshes every 30 s and whenever an alert changes."
        actions={
          <Button icon="refresh" onClick={() => void list.refetch()} loading={list.isRefetching}>
            Refresh
          </Button>
        }
      />

      <GlassCard className="mb-4" as="section" aria-label="Alert filters">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <SegmentedControl<View>
              label="Alert state"
              value={view}
              onChange={(v) => setF({ view: v === 'active' ? '' : v })}
              options={[
                { value: 'active', label: 'Active', icon: 'bell' },
                { value: 'resolved', label: 'Resolved', icon: 'circle-check' },
                { value: 'all', label: 'All', icon: 'list' },
              ]}
            />
            <ToggleGroup<Severity>
              label="Severity"
              values={severities}
              onChange={(v) => setF({ severity: v.join(',') })}
              options={[
                { value: 'Critical', label: 'Critical', icon: 'octagon-x' },
                { value: 'Warning', label: 'Warning', icon: 'triangle-alert' },
                { value: 'Info', label: 'Info', icon: 'info' },
              ]}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            <SearchField
              label="Search"
              value={f.q}
              onCommit={(q) => setF({ q })}
              placeholder="Title, message, server, component"
            />
            <SiteSelect urlValue={f.site_id} onChange={(v) => setF({ site_id: v })} />
            <FormField label="Maintenance">
              <Select
                value={f.muted}
                onChange={(e) => setF({ muted: e.target.value })}
                options={[
                  { value: '', label: 'Muted or not' },
                  { value: 'muted', label: 'Muted only' },
                  { value: 'unmuted', label: 'Not muted' },
                ]}
              />
            </FormField>
            <DateTimeField label="Opened from" value={f.from} onChange={(from) => setF({ from })} />
            <DateTimeField label="Opened before" value={f.to} onChange={(to) => setF({ to })} />
          </div>
          {filtered ? (
            <div>
              <Button
                size="sm"
                variant="ghost"
                icon="x"
                onClick={() => setF({ severity: '', site_id: '', muted: '', q: '', from: '', to: '' })}
              >
                Clear filters
              </Button>
            </div>
          ) : null}
        </div>
      </GlassCard>

      <DataTable<Alert>
        {...list.tableProps}
        rows={rows}
        columns={columns}
        getRowId={(a) => a.id}
        caption="Alerts"
        persistKey="alerts"
        onRowClick={(a) => setF({ id: a.id })}
        rowLabel={(a) => `${a.severity} alert: ${a.title}${a.server ? ` on ${a.server.name}` : ''}`}
        summary={listSummary(rows.length, list.hasNextPage, 'alerts')}
        emptyTitle={view === 'active' ? 'No active alerts' : 'No alerts match'}
        emptyDescription={
          filtered
            ? 'Try fewer filters or a wider time range.'
            : view === 'active'
              ? 'Every server is within its limits right now.'
              : 'Nothing has been recorded yet.'
        }
      />

      <AlertDrawer alertId={selectedId} onClose={() => setF({ id: null })} units={units} />
    </div>
  );
}
