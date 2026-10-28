import { useState } from 'react';

import { send, useApiMutation, useCan, useCursorList } from '@/api/hooks';
import type { Collector } from '@/api/types';
import { OnlineBadge } from '@/components/Badges';
import { Button } from '@/components/Button';
import { type Column } from '@/components/DataTable';
import { Drawer } from '@/components/Drawer';
import { FormField, Select, TextInput } from '@/components/FormField';
import { KeyValueList } from '@/components/KeyValue';
import { Age } from '@/components/Reading';
import { formatNumber, formatTimestamp } from '@/lib/format';

import { CrudList, FilterSelect, Hint, optText, RowSwitch, type CrudForm, type FormErrors } from './crud';
import { useSiteParam, useSites } from './pickers';

interface CollectorForm {
  site_id: string;
  name: string;
  cert_fingerprint: string;
}

function shortFingerprint(fp: string | null): string | null {
  if (!fp) return null;
  const clean = fp.replace(/^sha256:/i, '');
  return clean.length > 16 ? `${clean.slice(0, 16)}…` : clean;
}

function statValue(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return formatNumber(v, Number.isInteger(v) ? 0 : 2);
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (typeof v === 'string') return v;
  return JSON.stringify(v);
}

/** "servers_polled" → "Servers polled". */
const statLabel = (k: string) => {
  const s = k.replace(/[_-]+/g, ' ').trim();
  return s ? s[0]!.toUpperCase() + s.slice(1) : k;
};

function CollectorDrawer({ collector, onClose }: { collector: Collector | null; onClose: () => void }) {
  const stats = collector ? Object.entries(collector.stats ?? {}) : [];
  return (
    <Drawer
      open={collector !== null}
      onClose={onClose}
      title={collector ? collector.name : ''}
      description={collector ? `Collector at ${collector.site_code}` : undefined}
    >
      {collector ? (
        <div className="flex flex-col gap-6">
          <KeyValueList
            items={[
              { label: 'Status', value: <OnlineBadge online={collector.online} /> },
              {
                label: 'Last heartbeat',
                value: collector.last_heartbeat ? <Age time={collector.last_heartbeat} /> : 'Never',
              },
              { label: 'Version', value: collector.version },
              { label: 'Host name', value: collector.hostname },
              { label: 'Enabled', value: collector.enabled ? 'Yes' : 'No' },
              { label: 'Servers preferring it', value: formatNumber(collector.servers_preferred, 0) },
              {
                label: 'Certificate',
                value: collector.cert_fingerprint ? (
                  <span className="break-all font-mono text-xs">{collector.cert_fingerprint}</span>
                ) : (
                  'Not set'
                ),
              },
              { label: 'Registered', value: formatTimestamp(collector.created_at) },
            ]}
          />
          <section aria-label="Collector stats">
            <h3 className="mb-1 text-sm font-semibold text-text">Stats</h3>
            <p className="mb-3 text-xs text-text-subtle">
              Reported with the heartbeat
              {collector.last_heartbeat ? (
                <>
                  {' '}
                  (<Age time={collector.last_heartbeat} />)
                </>
              ) : null}
              .
            </p>
            {stats.length ? (
              <KeyValueList items={stats.map(([k, v]) => ({ label: statLabel(k), value: statValue(v) }))} />
            ) : (
              <p className="text-sm text-text-muted">No stats reported yet.</p>
            )}
          </section>
        </div>
      ) : null}
    </Drawer>
  );
}

export default function CollectorsSection() {
  const can = useCan();
  const canEdit = can('edit_collectors');
  const sites = useSites();
  const [siteId, setSiteId] = useSiteParam();
  const list = useCursorList<Collector>(
    '/api/v1/collectors',
    { site_id: siteId },
    { refetchInterval: 30_000 },
  );
  const [details, setDetails] = useState<Collector | null>(null);
  const toggle = useApiMutation<{ id: number; enabled: boolean }, Collector>(
    (api, v) => api.json<Collector>(`/api/v1/collectors/${v.id}`, send('PATCH', { enabled: v.enabled })),
    {
      invalidate: ['collectors'],
      success: (c) => `${c.name} ${c.enabled ? 'enabled' : 'disabled'}`,
    },
  );

  const columns: Column<Collector>[] = [
    { id: 'name', header: 'Name', cell: (c) => <span className="font-medium">{c.name}</span> },
    { id: 'site', header: 'Site', cell: (c) => c.site_code },
    { id: 'online', header: 'Status', cell: (c) => <OnlineBadge online={c.online} /> },
    {
      id: 'heartbeat',
      header: 'Last heartbeat',
      cell: (c) =>
        c.last_heartbeat ? <Age time={c.last_heartbeat} /> : <span className="text-text-subtle">Never</span>,
    },
    {
      id: 'version',
      header: 'Version',
      cell: (c) => c.version ?? <span className="text-text-subtle">—</span>,
    },
    {
      id: 'hostname',
      header: 'Host name',
      cell: (c) => c.hostname ?? <span className="text-text-subtle">—</span>,
    },
    {
      id: 'servers',
      header: 'Servers',
      label: 'Servers preferring it',
      align: 'right',
      cell: (c) => formatNumber(c.servers_preferred, 0),
    },
    {
      id: 'enabled',
      header: 'Enabled',
      cell: (c) => (
        <RowSwitch
          checked={c.enabled}
          label={`Enabled: ${c.name}`}
          busy={toggle.isPending && toggle.variables?.id === c.id}
          onChange={canEdit ? (enabled) => toggle.mutate({ id: c.id, enabled }) : undefined}
        />
      ),
    },
    {
      id: 'cert',
      header: 'Certificate',
      cell: (c) =>
        c.cert_fingerprint ? (
          <span className="font-mono text-xs" title={c.cert_fingerprint}>
            {shortFingerprint(c.cert_fingerprint)}
          </span>
        ) : (
          <span className="text-text-subtle">Not set</span>
        ),
    },
  ];

  const form: CrudForm<Collector, CollectorForm, Collector> = {
    empty: () => ({ site_id: siteId ? String(siteId) : '', name: '', cert_fingerprint: '' }),
    fromRow: (c) => ({
      site_id: String(c.site_id),
      name: c.name,
      cert_fingerprint: c.cert_fingerprint ?? '',
    }),
    validate: (v, mode) => {
      const e: FormErrors = {};
      if (mode === 'create') {
        if (!v.site_id) e.site_id = 'Choose a site.';
        if (!/^[a-z0-9][a-z0-9-]*$/.test(v.name.trim()))
          e.name = 'Use lower-case letters, digits and dashes, e.g. pnq1-collector-a.';
      }
      return e;
    },
    create: (v) => ({
      method: 'POST',
      path: '/api/v1/collectors',
      body: {
        site_id: Number(v.site_id),
        name: v.name.trim(),
        cert_fingerprint: optText(v.cert_fingerprint),
      },
    }),
    update: (v, c) => ({
      method: 'PATCH',
      path: `/api/v1/collectors/${c.id}`,
      body: { cert_fingerprint: optText(v.cert_fingerprint) },
    }),
    render: ({ values, set, errors, mode }) => (
      <>
        <FormField label="Site" required={mode === 'create'} error={errors.site_id}>
          <Select
            value={values.site_id}
            options={sites.options}
            placeholder="Choose a site"
            disabled={mode === 'edit'}
            onChange={(e) => set('site_id', e.target.value)}
          />
        </FormField>
        <FormField
          label="Name"
          required={mode === 'create'}
          error={errors.name}
          hint={
            mode === 'create' ? 'The collector identifies itself with this name.' : 'Names cannot change.'
          }
        >
          <TextInput
            value={values.name}
            maxLength={64}
            disabled={mode === 'edit'}
            onChange={(e) => set('name', e.target.value.toLowerCase())}
          />
        </FormField>
        <FormField
          label="Certificate fingerprint"
          error={errors.cert_fingerprint}
          hint="SHA-256 of the collector's client certificate (mTLS). Leave empty when not using mTLS."
        >
          <TextInput
            value={values.cert_fingerprint}
            maxLength={128}
            spellCheck={false}
            className="font-mono"
            onChange={(e) => set('cert_fingerprint', e.target.value)}
          />
        </FormField>
        {mode === 'create' ? (
          <Hint>New collectors start enabled. Servers at the site can then be assigned to it.</Hint>
        ) : null}
      </>
    ),
  };

  return (
    <>
      <CrudList<Collector, CollectorForm, Collector>
        title="Collectors"
        noun="collector"
        caption="Collectors"
        intro="On-prem collectors poll the BMCs of their site and report a heartbeat about every 30 s."
        columns={columns}
        table={list.tableProps}
        getRowId={(c) => c.id}
        rowName={(c) => c.name}
        invalidate={['collectors', 'overview']}
        canEdit={canEdit}
        readOnlyReason="Registering and enabling collectors needs the Platform admin role."
        createLabel="Register collector"
        toolbar={
          <FilterSelect
            label="Site"
            value={siteId ? String(siteId) : ''}
            onChange={setSiteId}
            options={sites.options}
            placeholder="All sites"
          />
        }
        emptyTitle="No collectors"
        emptyDescription="Register a collector for each site so its servers get polled."
        form={form}
        rowActions={(c) => (
          <Button size="sm" variant="ghost" aria-label={`Details of ${c.name}`} onClick={() => setDetails(c)}>
            Details
          </Button>
        )}
        persistKey="admin-collectors"
      />
      <CollectorDrawer
        collector={details ? (list.items.find((c) => c.id === details.id) ?? details) : null}
        onClose={() => setDetails(null)}
      />
    </>
  );
}
