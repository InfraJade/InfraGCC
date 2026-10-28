import { useMemo } from 'react';
import { Link } from 'react-router-dom';

import { useCursorList } from '@/api/hooks';
import type { ServerListItem } from '@/api/types';
import { ServerStatusBadge } from '@/components/Badges';
import { Button } from '@/components/Button';
import { DataTable, type Column, type SortState } from '@/components/DataTable';
import { FormField, Select } from '@/components/FormField';
import { HealthBadge } from '@/components/HealthBadge';
import { Age } from '@/components/Reading';
import { useSiteFilter } from '@/components/shell/ShellContext';
import { useUrlState } from '@/lib/useUrlState';

import { listSummary, resolveSite, SearchField } from '../alerts/filterControls';

import { ExportCsvButton } from './ExportCsvButton';

/** Sort keys the API accepts; only these may be reversed with a "-" prefix. */
const SORTABLE = new Set(['name', 'health', 'site', 'rack', 'vendor', 'model', 'last_seen']);
const DESC_OK = new Set(['name', 'health', 'last_seen']);

export function sortToState(sort: string): SortState | null {
  const desc = sort.startsWith('-');
  const id = desc ? sort.slice(1) : sort;
  if (!SORTABLE.has(id)) return null;
  return { id, direction: desc ? 'desc' : 'asc' };
}

/** Table sort → API `sort`; columns the API can only sort ascending go back to the default order. */
export function stateToSort(s: SortState | null): string {
  if (!s || !SORTABLE.has(s.id)) return '';
  if (s.direction === 'desc') return DESC_OK.has(s.id) ? `-${s.id}` : '';
  return s.id;
}

const DEFAULTS = { q: '', health: '', status: '', vendor: '', model: '', sort: '' };

const dash = <span className="text-text-subtle">—</span>;

const columns: Column<ServerListItem>[] = [
  {
    id: 'name',
    header: 'Name',
    sortable: true,
    hideable: false,
    cell: (s) => (
      <Link to={`/servers/${s.id}`} className="font-medium text-accent hover:underline">
        {s.name}
      </Link>
    ),
  },
  {
    id: 'health',
    header: 'Health',
    sortable: true,
    cell: (s) => <HealthBadge health={s.health} size="sm" />,
  },
  { id: 'status', header: 'Status', cell: (s) => <ServerStatusBadge status={s.status} /> },
  {
    id: 'site',
    header: 'Site',
    sortable: true,
    cell: (s) => <span title={s.site.name}>{s.site.code}</span>,
  },
  {
    id: 'rack',
    header: 'Rack',
    sortable: true,
    cell: (s) =>
      s.rack ? (
        <Link to={`/racks/${s.rack.id}`} className="hover:underline">
          {s.rack.name}
          {s.position_u !== null ? <span className="text-text-muted"> · U{s.position_u}</span> : null}
        </Link>
      ) : (
        <span className="text-text-subtle">Not racked</span>
      ),
  },
  { id: 'vendor', header: 'Vendor', sortable: true, cell: (s) => s.vendor ?? dash },
  { id: 'model', header: 'Model', sortable: true, cell: (s) => s.model ?? dash },
  { id: 'serial', header: 'Serial', cell: (s) => (s.serial ? <code>{s.serial}</code> : dash) },
  { id: 'asset_tag', header: 'Asset tag', defaultHidden: true, cell: (s) => s.asset_tag ?? dash },
  { id: 'bmc_host', header: 'BMC host', cell: (s) => <code className="text-xs">{s.bmc_host}</code> },
  { id: 'collector', header: 'Collector', defaultHidden: true, cell: (s) => s.collector_name ?? dash },
  {
    id: 'last_seen',
    header: 'Last seen',
    sortable: true,
    cell: (s) =>
      s.last_seen_at ? <Age time={s.last_seen_at} /> : <span className="text-text-subtle">Never</span>,
  },
  {
    id: 'open_alerts',
    header: 'Open alerts',
    align: 'right',
    cell: (s) =>
      s.open_alerts > 0 ? (
        <span className="tabular font-medium text-health-warning">{s.open_alerts}</span>
      ) : (
        <span className="tabular text-text-subtle">0</span>
      ),
  },
];

export function ServersTab() {
  const [f, setF] = useUrlState(DEFAULTS);
  const { siteIds } = useSiteFilter();
  const site = resolveSite('', siteIds);

  const filters = {
    q: f.q || undefined,
    health: f.health || undefined,
    status: f.status || undefined,
    vendor: f.vendor || undefined,
    model: f.model || undefined,
    site_id: site.siteId,
  };
  const sortParam = sortToState(f.sort) ? f.sort : '';
  const query = { ...filters, sort: sortParam || undefined };
  const list = useCursorList<ServerListItem>('/api/v1/servers', query);
  const clientSites = site.clientSiteIds;
  const rows = useMemo(
    () => (clientSites ? list.items.filter((s) => clientSites.includes(s.site.id)) : list.items),
    [list.items, clientSites],
  );
  const filtered = Boolean(f.q || f.health || f.status || f.vendor || f.model);

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <SearchField
          label="Search servers"
          value={f.q}
          onCommit={(q) => setF({ q })}
          placeholder="Name, serial, BMC address, asset tag"
        />
        <FormField label="Health">
          <Select
            value={f.health}
            onChange={(e) => setF({ health: e.target.value })}
            options={[
              { value: '', label: 'Any health' },
              { value: 'Critical', label: 'Critical' },
              { value: 'Warning', label: 'Warning' },
              { value: 'OK', label: 'OK' },
              { value: 'Unknown', label: 'Unknown' },
            ]}
          />
        </FormField>
        <FormField label="Status">
          <Select
            value={f.status}
            onChange={(e) => setF({ status: e.target.value })}
            options={[
              { value: '', label: 'Active and maintenance' },
              { value: 'active', label: 'Active' },
              { value: 'maintenance', label: 'Maintenance' },
              { value: 'decommissioned', label: 'Decommissioned' },
            ]}
          />
        </FormField>
        <SearchField
          label="Vendor"
          search={false}
          value={f.vendor}
          onCommit={(vendor) => setF({ vendor })}
          placeholder="e.g. Dell"
          hint="Exact name"
        />
        <SearchField
          label="Model"
          search={false}
          value={f.model}
          onCommit={(model) => setF({ model })}
          placeholder="e.g. PowerEdge R750"
          hint="Exact name"
        />
      </div>

      <DataTable<ServerListItem>
        {...list.tableProps}
        rows={rows}
        columns={columns}
        getRowId={(s) => s.id}
        caption="Servers"
        persistKey="inventory.servers"
        sort={sortToState(sortParam)}
        onSortChange={(s) => setF({ sort: stateToSort(s) })}
        summary={listSummary(rows.length, list.hasNextPage, 'servers')}
        toolbar={
          <>
            <ExportCsvButton path="/api/v1/servers/export.csv" query={query} filename="servers.csv" />
            {filtered ? (
              <Button
                size="sm"
                variant="ghost"
                icon="x"
                onClick={() => setF({ q: '', health: '', status: '', vendor: '', model: '' })}
              >
                Clear filters
              </Button>
            ) : null}
          </>
        }
        emptyTitle={filtered ? 'No servers match' : 'No servers yet'}
        emptyDescription={
          filtered
            ? 'Check the spelling, or clear a filter. Vendor and model need the exact name.'
            : 'Servers appear here once they are onboarded in Admin.'
        }
      />
    </div>
  );
}
