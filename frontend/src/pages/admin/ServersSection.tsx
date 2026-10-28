import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { useApiQuery, useCan, useCursorList } from '@/api/hooks';
import type { ServerDetail, ServerListItem } from '@/api/types';
import { ServerStatusBadge } from '@/components/Badges';
import { Button } from '@/components/Button';
import { type Column } from '@/components/DataTable';
import { FormField, NumberInput, Select, TextArea, TextInput } from '@/components/FormField';
import { HealthBadge } from '@/components/HealthBadge';
import { Icon } from '@/components/Icon';
import { useDebouncedValue } from '@/lib/useDebouncedValue';
import { numberParam, useUrlState } from '@/lib/useUrlState';

import {
  CrudList,
  FilterSelect,
  Hint,
  isInt,
  optText,
  type CrudForm,
  type FormApi,
  type FormErrors,
} from './crud';
import { useCollectors, useRacks, useRooms, useSiteParam, useSites } from './pickers';

export interface ServerForm {
  bmc_host: string;
  site_id: string;
  room_id: string;
  rack_id: string;
  position_u: string;
  height_u: string;
  /** '' = automatic (least-loaded enabled collector at the site). */
  collector_id: string;
  name: string;
  asset_tag: string;
  notes: string;
  /** Edit only: notes come from the server detail; untouched until it has loaded. */
  notes_loaded: boolean;
  status: string;
}

const STATUS_OPTIONS = [
  { value: 'active', label: 'Active (monitored and alerting)' },
  { value: 'maintenance', label: 'Maintenance (monitored, alerts muted)' },
];
const EDIT_STATUS_OPTIONS = [
  ...STATUS_OPTIONS,
  { value: 'decommissioned', label: 'Decommissioned (no longer polled)' },
];
const STATUS_FILTER = [
  { value: 'active', label: 'Active' },
  { value: 'maintenance', label: 'Maintenance' },
  { value: 'decommissioned', label: 'Decommissioned' },
];

const columns: Column<ServerListItem>[] = [
  {
    id: 'name',
    header: 'Server',
    cell: (s) => (
      <Link to={`/servers/${s.id}`} className="font-medium text-text hover:text-accent hover:underline">
        {s.name || s.bmc_host}
      </Link>
    ),
  },
  { id: 'bmc', header: 'BMC host', cell: (s) => <span className="font-mono text-xs">{s.bmc_host}</span> },
  {
    id: 'location',
    header: 'Site / rack / U',
    cell: (s) => (
      <span className="whitespace-nowrap">
        {s.site.code} / {s.rack ? s.rack.name : <span className="text-text-subtle">not racked</span>}
        {s.position_u
          ? ` / U${s.position_u}${s.height_u > 1 ? `–U${s.position_u + s.height_u - 1}` : ''}`
          : ''}
      </span>
    ),
  },
  {
    id: 'model',
    header: 'Model',
    cell: (s) =>
      s.model || s.vendor ? (
        [s.vendor, s.model].filter(Boolean).join(' ')
      ) : (
        <span className="text-text-subtle">Not discovered yet</span>
      ),
  },
  { id: 'status', header: 'Status', cell: (s) => <ServerStatusBadge status={s.status} /> },
  {
    id: 'health',
    header: 'Health',
    cell: (s) => <HealthBadge health={s.health} size="sm" context={s.name || s.bmc_host} />,
  },
  {
    id: 'collector',
    header: 'Collector',
    cell: (s) => s.collector_name ?? <span className="text-text-subtle">None</span>,
  },
];

function ServerFields({ form, row }: { form: FormApi<ServerForm>; row: ServerListItem | null }) {
  const { values, set, patch, errors, mode } = form;
  const sites = useSites();
  const siteId = numberParam(values.site_id);
  const rooms = useRooms(siteId);
  const racks = useRacks(numberParam(values.room_id));
  const collectors = useCollectors(siteId);
  const detail = useApiQuery<ServerDetail>(mode === 'edit' && row ? `/api/v1/servers/${row.id}` : null);
  const hasDetail = detail.data !== undefined;
  const loadedNotes = detail.data?.notes ?? '';
  const notesReady = values.notes_loaded;
  // Notes aren't in the list rows: fill them in once the server detail arrives.
  useEffect(() => {
    if (!notesReady && hasDetail) patch({ notes: loadedNotes, notes_loaded: true });
  }, [hasDetail, loadedNotes, notesReady, patch]);

  return (
    <>
      <FormField
        label="BMC address"
        required={mode === 'create'}
        error={errors.bmc_host}
        hint={
          mode === 'create'
            ? 'Host name, IP or URL of the iDRAC / iLO / XCC, e.g. 10.20.1.11 or https://idrac-a01-07:443.'
            : 'The BMC address is fixed; onboard again to change it.'
        }
      >
        <TextInput
          value={values.bmc_host}
          disabled={mode === 'edit'}
          maxLength={255}
          autoComplete="off"
          spellCheck={false}
          onChange={(e) => set('bmc_host', e.target.value)}
        />
      </FormField>
      <div className="grid gap-4 sm:grid-cols-3">
        <FormField label="Site" required error={errors.site_id}>
          <Select
            value={values.site_id}
            options={sites.options}
            placeholder="Choose a site"
            onChange={(e) => patch({ site_id: e.target.value, room_id: '', rack_id: '', collector_id: '' })}
          />
        </FormField>
        <FormField label="Room" required error={errors.room_id}>
          <Select
            value={values.room_id}
            options={rooms.options}
            placeholder={values.site_id ? 'Choose a room' : 'Choose a site first'}
            disabled={!values.site_id}
            onChange={(e) => patch({ room_id: e.target.value, rack_id: '' })}
          />
        </FormField>
        <FormField label="Rack" required={mode === 'create'} error={errors.rack_id}>
          <Select
            value={values.rack_id}
            options={racks.options}
            placeholder={
              values.room_id ? (mode === 'edit' ? 'Not racked' : 'Choose a rack') : 'Choose a room first'
            }
            disabled={!values.room_id}
            onChange={(e) => set('rack_id', e.target.value)}
          />
        </FormField>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField
          label="Position"
          required={mode === 'create' || values.rack_id !== ''}
          error={errors.position_u}
          hint="Lowest U the server occupies (1 = bottom)."
        >
          <NumberInput
            unit="U"
            min={1}
            max={60}
            step={1}
            value={values.position_u}
            onChange={(e) => set('position_u', e.target.value)}
          />
        </FormField>
        <FormField label="Height" required error={errors.height_u} hint="1–10 U">
          <NumberInput
            unit="U"
            min={1}
            max={10}
            step={1}
            value={values.height_u}
            onChange={(e) => set('height_u', e.target.value)}
          />
        </FormField>
      </div>
      <FormField
        label="Collector"
        error={errors.collector_id}
        hint="Collectors of the chosen site. Automatic picks the least-loaded enabled one and fails over by itself."
      >
        <Select
          value={values.collector_id}
          options={collectors.options}
          placeholder="Automatic"
          disabled={!values.site_id}
          onChange={(e) => set('collector_id', e.target.value)}
        />
      </FormField>
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Name" error={errors.name} hint="Optional; defaults to the discovered host name.">
          <TextInput value={values.name} maxLength={128} onChange={(e) => set('name', e.target.value)} />
        </FormField>
        <FormField label="Asset tag" error={errors.asset_tag}>
          <TextInput
            value={values.asset_tag}
            maxLength={64}
            onChange={(e) => set('asset_tag', e.target.value)}
          />
        </FormField>
      </div>
      <FormField label={mode === 'create' ? 'Initial status' : 'Status'} required error={errors.status}>
        <Select
          value={values.status}
          options={mode === 'create' ? STATUS_OPTIONS : EDIT_STATUS_OPTIONS}
          onChange={(e) => set('status', e.target.value)}
        />
      </FormField>
      <FormField label="Notes" error={errors.notes}>
        <TextArea
          value={values.notes}
          maxLength={4000}
          disabled={mode === 'edit' && !values.notes_loaded}
          placeholder={mode === 'edit' && !values.notes_loaded ? 'Loading notes…' : undefined}
          onChange={(e) => set('notes', e.target.value)}
        />
      </FormField>
      {mode === 'create' ? (
        <Hint>
          You only enter where the server is and how to reach its BMC. The collector discovers vendor, model,
          serial and parts on its next poll.
        </Hint>
      ) : null}
    </>
  );
}

function validate(v: ServerForm, mode: 'create' | 'edit'): FormErrors {
  const e: FormErrors = {};
  if (mode === 'create' && !v.bmc_host.trim()) e.bmc_host = 'Enter the BMC address.';
  if (!v.site_id) e.site_id = 'Choose a site.';
  if (mode === 'create' && !v.room_id) e.room_id = 'Choose a room.';
  if (mode === 'create' && !v.rack_id) e.rack_id = 'Choose a rack.';
  if ((mode === 'create' || v.rack_id) && !isInt(v.position_u, 1, 60))
    e.position_u = 'Enter a whole U position from 1 to 60.';
  if (!isInt(v.height_u, 1, 10)) e.height_u = 'Enter a height from 1 to 10 U.';
  return e;
}

export default function ServersSection() {
  const can = useCan();
  const canEdit = can('onboard_servers');
  const sites = useSites();
  const [siteId, setSiteId] = useSiteParam();
  const [f, setF] = useUrlState({ q: '', status: '' });
  const q = useDebouncedValue(f.q.trim(), 300);
  const list = useCursorList<ServerListItem>('/api/v1/servers', {
    site_id: siteId,
    status: f.status,
    q,
    sort: 'site',
  });
  const [created, setCreated] = useState<ServerDetail | null>(null);

  const form: CrudForm<ServerListItem, ServerForm, ServerDetail> = {
    size: 'lg',
    empty: () => ({
      bmc_host: '',
      site_id: siteId ? String(siteId) : '',
      room_id: '',
      rack_id: '',
      position_u: '',
      height_u: '1',
      collector_id: '',
      name: '',
      asset_tag: '',
      notes: '',
      notes_loaded: true,
      status: 'active',
    }),
    fromRow: (s) => ({
      bmc_host: s.bmc_host,
      site_id: String(s.site.id),
      room_id: s.room ? String(s.room.id) : '',
      rack_id: s.rack ? String(s.rack.id) : '',
      position_u: s.position_u ? String(s.position_u) : '',
      height_u: String(s.height_u),
      collector_id: s.collector_id ? String(s.collector_id) : '',
      name: s.name,
      asset_tag: s.asset_tag ?? '',
      notes: '',
      notes_loaded: false,
      status: s.status,
    }),
    validate: (v, mode) => validate(v, mode),
    description: (mode) =>
      mode === 'create'
        ? 'Add a server by its BMC address and rack position.'
        : 'Move the server, change its status or collector.',
    create: (v) => ({
      method: 'POST',
      path: '/api/v1/servers',
      body: {
        bmc_host: v.bmc_host.trim(),
        rack_id: Number(v.rack_id),
        position_u: Number(v.position_u),
        height_u: Number(v.height_u),
        collector_id: v.collector_id ? Number(v.collector_id) : null,
        name: optText(v.name),
        asset_tag: optText(v.asset_tag),
        notes: optText(v.notes),
        status: v.status,
      },
    }),
    update: (v, s) => ({
      method: 'PATCH',
      path: `/api/v1/servers/${s.id}`,
      body: {
        rack_id: v.rack_id ? Number(v.rack_id) : null,
        position_u: v.rack_id ? Number(v.position_u) : null,
        height_u: Number(v.height_u),
        status: v.status,
        collector_id: v.collector_id ? Number(v.collector_id) : null,
        name: optText(v.name),
        asset_tag: optText(v.asset_tag),
        ...(v.notes_loaded ? { notes: optText(v.notes) } : {}),
      },
    }),
    render: (form, row) => <ServerFields form={form} row={row} />,
    onSaved: (result, mode) => {
      if (mode === 'create') setCreated(result);
    },
  };

  return (
    <CrudList<ServerListItem, ServerForm, ServerDetail>
      title="Servers"
      noun="server"
      caption="Servers"
      intro="Onboard servers by BMC address and rack position; move, re-assign or decommission them."
      columns={columns}
      table={list.tableProps}
      getRowId={(s) => s.id}
      rowName={(s) => s.name || s.bmc_host}
      invalidate={['servers', 'racks', 'sites', 'overview', 'collectors']}
      canEdit={canEdit}
      readOnlyReason="Onboarding and moving servers needs the DC engineer role."
      createLabel="Onboard server"
      toolbar={
        <>
          <FormField label="Search servers" hideLabel className="w-56">
            <TextInput
              type="search"
              placeholder="Name, BMC, serial, asset tag…"
              value={f.q}
              onChange={(e) => setF({ q: e.target.value })}
            />
          </FormField>
          <FilterSelect
            label="Site"
            value={siteId ? String(siteId) : ''}
            onChange={setSiteId}
            options={sites.options}
            placeholder="All sites"
          />
          <FilterSelect
            label="Status"
            value={f.status}
            onChange={(v) => setF({ status: v })}
            options={STATUS_FILTER}
            placeholder="Any status"
          />
        </>
      }
      emptyTitle="No servers"
      emptyDescription={
        canEdit ? 'Onboard a server, or loosen the filters.' : 'No servers match these filters.'
      }
      form={form}
      remove={{
        path: (s) => `/api/v1/servers/${s.id}`,
        verb: 'Decommission',
        done: 'decommissioned',
        allowed: (s) => s.status !== 'decommissioned',
        description: () =>
          'It stops being polled and leaves the default lists; its history is kept and it can be brought back by changing its status.',
      }}
      persistKey="admin-servers"
    >
      {created ? (
        <div
          role="status"
          className="glass-subtle flex flex-wrap items-center gap-3 rounded-lg px-4 py-3 text-sm text-text"
        >
          <Icon name="circle-check" size={18} className="text-health-ok" />
          <span className="flex-1">
            <span className="font-medium">{created.name || created.bmc_host}</span> is onboarded. Its
            collector discovers vendor, model and serial on the next poll.
          </span>
          <Link
            to={`/servers/${created.id}`}
            className="inline-flex items-center gap-1 font-medium text-accent hover:underline"
          >
            Open server page
            <Icon name="chevron-right" size={14} />
          </Link>
          <Button size="sm" variant="ghost" onClick={() => setCreated(null)}>
            Dismiss
          </Button>
        </div>
      ) : null}
    </CrudList>
  );
}
