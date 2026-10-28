import { useMemo } from 'react';
import { Link } from 'react-router-dom';

import { useCan, useCursorList } from '@/api/hooks';
import type { Compliance, ComplianceServer } from '@/api/types';
import { Button } from '@/components/Button';
import { DataTable, type Column } from '@/components/DataTable';
import { GlassCard } from '@/components/GlassCard';
import { Icon } from '@/components/Icon';
import { PageHeader } from '@/components/PageHeader';
import { useSiteFilter } from '@/components/shell/ShellContext';
import { StatTile } from '@/components/StatTile';
import { numberParam, useUrlState } from '@/lib/useUrlState';

import { listSummary, resolveSite, SearchField, SiteSelect } from './alerts/filterControls';
import { componentTypeLabel, DifferencesDrawer } from './firmware/DifferencesDrawer';

const DEFAULTS = { site_id: '', vendor: '', model: '', component: '', server: '' };

const dash = <span className="text-text-subtle">—</span>;

const columns: Column<ComplianceServer>[] = [
  {
    id: 'server',
    header: 'Server',
    hideable: false,
    cell: (s) => (
      <Link
        to={`/servers/${s.server_id}`}
        onClick={(e) => e.stopPropagation()}
        className="font-medium text-accent hover:underline"
      >
        {s.server_name}
      </Link>
    ),
  },
  { id: 'site', header: 'Site', cell: (s) => s.site_code },
  { id: 'rack', header: 'Rack', cell: (s) => s.rack_name ?? dash },
  {
    id: 'vendor_model',
    header: 'Vendor / model',
    cell: (s) => [s.vendor, s.model].filter(Boolean).join(' ') || dash,
  },
  {
    id: 'differences',
    header: 'Off baseline',
    hideable: false,
    cell: (s) => (
      <span className="inline-flex flex-col">
        <span className="inline-flex items-center gap-1 font-medium text-text">
          <Icon name="triangle-alert" size={13} className="text-health-warning" />
          {s.differences.length === 1 ? '1 component' : `${s.differences.length} components`}
        </span>
        <span className="max-w-[24rem] truncate text-xs text-text-subtle">
          {s.differences.map((d) => `${d.component} (${componentTypeLabel(d.component_type)})`).join(', ')}
        </span>
      </span>
    ),
  },
  {
    id: 'open',
    header: <span className="sr-only">Details</span>,
    label: 'Details',
    hideable: false,
    align: 'right',
    cell: () => (
      <span className="inline-flex items-center gap-1 text-xs text-text-muted">
        Details
        <Icon name="chevron-right" size={13} />
      </span>
    ),
  },
];

export default function FirmwarePage() {
  const [f, setF] = useUrlState(DEFAULTS);
  const { siteIds } = useSiteFilter();
  const can = useCan();
  const site = resolveSite(f.site_id, siteIds);

  const query = {
    site_id: site.siteId,
    vendor: f.vendor || undefined,
    model: f.model || undefined,
    component: f.component || undefined,
  };
  const list = useCursorList<ComplianceServer>('/api/v1/firmware/compliance', query);
  const summary = (list.firstPage as Compliance | undefined)?.summary;
  const clientSites = site.clientSiteIds;
  const rows = useMemo(
    () => (clientSites ? list.items.filter((s) => clientSites.includes(s.site_id)) : list.items),
    [list.items, clientSites],
  );
  const selectedId = numberParam(f.server);
  const selected = rows.find((s) => s.server_id === selectedId) ?? null;
  const filtered = Boolean(f.site_id || f.vendor || f.model || f.component);
  const loading = list.isPending;
  const asOf = list.dataUpdatedAt || null;

  return (
    <div>
      <PageHeader
        title="Firmware compliance"
        subtitle="Installed BIOS, BMC, drive and adapter firmware compared with the approved baseline for each model."
        actions={
          can('edit_baselines') ? (
            <Link
              to="/admin/baselines"
              className="glass-subtle inline-flex h-9 items-center gap-2 rounded-md px-3.5 text-sm font-medium text-text hover:bg-text/10"
            >
              <Icon name="sliders" size={16} />
              Edit baselines
            </Link>
          ) : null
        }
      />

      <section
        aria-label="Compliance summary"
        className="mb-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5"
      >
        <StatTile
          label="Servers checked"
          icon="server"
          value={summary?.servers_checked}
          time={asOf}
          loading={loading}
          footnote={summary ? `of ${summary.servers_with_firmware} reporting firmware` : undefined}
        />
        <StatTile
          label="Compliant"
          icon="circle-check"
          value={summary?.servers_compliant}
          time={asOf}
          loading={loading}
          footnote="servers on the baseline"
        />
        <StatTile
          label="Off baseline"
          icon="triangle-alert"
          value={summary?.servers_off_baseline}
          time={asOf}
          loading={loading}
          footnote="servers"
        />
        <StatTile
          label="Components off baseline"
          icon="chip"
          value={summary?.components_off_baseline}
          time={asOf}
          loading={loading}
          footnote="across those servers"
        />
        <StatTile
          label="Models without a baseline"
          icon="circle-help"
          value={summary?.models_without_baseline}
          time={asOf}
          loading={loading}
          footnote="not checked"
        />
      </section>

      <GlassCard className="mb-4" as="section" aria-label="Compliance filters">
        <div className="grid items-end gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <SiteSelect urlValue={f.site_id} onChange={(v) => setF({ site_id: v })} />
          <SearchField
            label="Vendor"
            search={false}
            value={f.vendor}
            onCommit={(vendor) => setF({ vendor })}
            placeholder="e.g. Dell"
          />
          <SearchField
            label="Model"
            search={false}
            value={f.model}
            onCommit={(model) => setF({ model })}
            placeholder="e.g. PowerEdge R750"
          />
          <SearchField
            label="Firmware component"
            search={false}
            value={f.component}
            onCommit={(component) => setF({ component })}
            placeholder="e.g. BIOS"
          />
        </div>
        {filtered ? (
          <Button
            className="mt-3"
            size="sm"
            variant="ghost"
            icon="x"
            onClick={() => setF({ site_id: '', vendor: '', model: '', component: '' })}
          >
            Clear filters
          </Button>
        ) : null}
      </GlassCard>

      <DataTable<ComplianceServer>
        {...list.tableProps}
        rows={rows}
        columns={columns}
        getRowId={(s) => s.server_id}
        caption="Servers off the approved firmware baseline"
        persistKey="firmware.offBaseline"
        onRowClick={(s) => setF({ server: s.server_id })}
        rowLabel={(s) =>
          `${s.server_name}: ${s.differences.length} component${s.differences.length === 1 ? '' : 's'} off baseline, show details`
        }
        summary={listSummary(rows.length, list.hasNextPage, 'servers off baseline')}
        emptyTitle={
          filtered
            ? 'No servers off the baseline match these filters'
            : 'Every checked server matches its approved baseline'
        }
        emptyDescription={
          summary && summary.models_without_baseline > 0
            ? `${summary.models_without_baseline} model${summary.models_without_baseline === 1 ? ' has' : 's have'} no baseline yet, so their servers aren't checked.`
            : undefined
        }
      />

      <DifferencesDrawer server={selected} onClose={() => setF({ server: null })} />
    </div>
  );
}
