import { Link } from 'react-router-dom';

import { useCan, useCursorList } from '@/api/hooks';
import type { Rack } from '@/api/types';
import { type Column } from '@/components/DataTable';
import { FormField, NumberInput, Select, TextInput } from '@/components/FormField';
import { formatNumber, formatValue } from '@/lib/format';
import { numberParam, useUrlState } from '@/lib/useUrlState';

import {
  CrudList,
  FilterSelect,
  isInt,
  numText,
  optNumber,
  optText,
  type CrudForm,
  type FormApi,
  type FormErrors,
} from './crud';
import { useRooms, useSiteParam, useSites } from './pickers';

interface RackForm {
  site_id: string;
  room_id: string;
  name: string;
  row: string;
  height_u: string;
  power_capacity_w: string;
}

const columns: Column<Rack>[] = [
  { id: 'site', header: 'Site', cell: (r) => r.site_code },
  { id: 'room', header: 'Room', cell: (r) => r.room_name },
  {
    id: 'name',
    header: 'Rack',
    cell: (r) => (
      <Link to={`/racks/${r.id}`} className="font-medium text-text hover:text-accent hover:underline">
        {r.name}
      </Link>
    ),
  },
  { id: 'row', header: 'Row', cell: (r) => r.row ?? <span className="text-text-subtle">—</span> },
  { id: 'height', header: 'Height', align: 'right', cell: (r) => `${r.height_u} U` },
  {
    id: 'used',
    header: 'Used',
    align: 'right',
    cell: (r) => (
      <span title={`${r.height_u - r.used_u} U free`}>
        {r.used_u} of {r.height_u} U
      </span>
    ),
  },
  { id: 'servers', header: 'Servers', align: 'right', cell: (r) => formatNumber(r.server_count, 0) },
  {
    id: 'power',
    header: 'Power capacity',
    align: 'right',
    cell: (r) =>
      r.power_capacity_w === null ? (
        <span className="text-text-subtle">Not set</span>
      ) : (
        formatValue(r.power_capacity_w, 'W')
      ),
  },
];

function RackFields({ form }: { form: FormApi<RackForm> }) {
  const { values, set, patch, errors, mode } = form;
  const sites = useSites();
  const rooms = useRooms(numberParam(values.site_id));
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField
          label="Site"
          required
          error={errors.site_id}
          hint={mode === 'edit' ? 'A rack can move to another room of the same site only.' : undefined}
        >
          <Select
            value={values.site_id}
            options={sites.options}
            placeholder="Choose a site"
            disabled={mode === 'edit'}
            onChange={(e) => patch({ site_id: e.target.value, room_id: '' })}
          />
        </FormField>
        <FormField label="Room" required error={errors.room_id}>
          <Select
            value={values.room_id}
            options={rooms.options}
            placeholder={
              values.site_id ? (rooms.loading ? 'Loading rooms…' : 'Choose a room') : 'Choose a site first'
            }
            disabled={!values.site_id}
            onChange={(e) => set('room_id', e.target.value)}
          />
        </FormField>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Name" required error={errors.name} hint="Unique within the room, e.g. R03.">
          <TextInput value={values.name} maxLength={64} onChange={(e) => set('name', e.target.value)} />
        </FormField>
        <FormField label="Row" error={errors.row}>
          <TextInput value={values.row} maxLength={32} onChange={(e) => set('row', e.target.value)} />
        </FormField>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Height" required error={errors.height_u} hint="1–60 U">
          <NumberInput
            unit="U"
            min={1}
            max={60}
            step={1}
            value={values.height_u}
            onChange={(e) => set('height_u', e.target.value)}
          />
        </FormField>
        <FormField
          label="Power capacity"
          error={errors.power_capacity_w}
          hint="Optional; feeds power headroom."
        >
          <NumberInput
            unit="W"
            min={0}
            step={100}
            value={values.power_capacity_w}
            onChange={(e) => set('power_capacity_w', e.target.value)}
          />
        </FormField>
      </div>
    </>
  );
}

export default function RacksSection() {
  const can = useCan();
  const canEdit = can('edit_racks');
  const sites = useSites();
  const [siteId, setSiteId] = useSiteParam();
  const [f, setF] = useUrlState({ room: '' });
  const roomId = numberParam(f.room);
  const rooms = useRooms(siteId);
  const list = useCursorList<Rack>('/api/v1/racks', { site_id: siteId, room_id: roomId });

  const form: CrudForm<Rack, RackForm, Rack> = {
    empty: () => ({
      site_id: siteId ? String(siteId) : '',
      room_id: roomId ? String(roomId) : '',
      name: '',
      row: '',
      height_u: '42',
      power_capacity_w: '',
    }),
    fromRow: (r) => ({
      site_id: String(r.site_id),
      room_id: String(r.room_id),
      name: r.name,
      row: r.row ?? '',
      height_u: String(r.height_u),
      power_capacity_w: numText(r.power_capacity_w),
    }),
    validate: (v) => {
      const e: FormErrors = {};
      if (!v.site_id) e.site_id = 'Choose a site.';
      if (!v.room_id) e.room_id = 'Choose a room.';
      if (!v.name.trim()) e.name = 'Enter a name.';
      if (!isInt(v.height_u, 1, 60)) e.height_u = 'Enter a whole number from 1 to 60.';
      if (v.power_capacity_w.trim() && !isInt(v.power_capacity_w, 0))
        e.power_capacity_w = 'Enter whole watts (0 or more), or leave empty.';
      return e;
    },
    create: (v) => ({
      method: 'POST',
      path: '/api/v1/racks',
      body: {
        room_id: Number(v.room_id),
        name: v.name.trim(),
        row: optText(v.row),
        height_u: Number(v.height_u),
        power_capacity_w: optNumber(v.power_capacity_w),
      },
    }),
    update: (v, r) => ({
      method: 'PATCH',
      path: `/api/v1/racks/${r.id}`,
      body: {
        room_id: Number(v.room_id),
        name: v.name.trim(),
        row: optText(v.row),
        height_u: Number(v.height_u),
        power_capacity_w: optNumber(v.power_capacity_w),
      },
    }),
    render: (form) => <RackFields form={form} />,
  };

  return (
    <CrudList<Rack, RackForm, Rack>
      title="Racks"
      noun="rack"
      caption="Racks"
      intro="Rack heights bound server positions; a rack can only be shortened down to its highest server."
      columns={columns}
      table={list.tableProps}
      getRowId={(r) => r.id}
      rowName={(r) => `rack ${r.name}`}
      invalidate={['racks', 'rooms', 'sites']}
      canEdit={canEdit}
      readOnlyReason="Changing racks needs the DC engineer role."
      toolbar={
        <>
          <FilterSelect
            label="Site"
            value={siteId ? String(siteId) : ''}
            onChange={(v) => {
              setSiteId(v);
              setF({ room: '' });
            }}
            options={sites.options}
            placeholder="All sites"
          />
          <FilterSelect
            label="Room"
            value={roomId ? String(roomId) : ''}
            onChange={(v) => setF({ room: v })}
            options={rooms.options}
            placeholder={siteId ? 'All rooms' : 'Choose a site for rooms'}
            disabled={!siteId}
          />
        </>
      }
      emptyTitle="No racks"
      emptyDescription="No racks match these filters."
      form={form}
      remove={{
        path: (r) => `/api/v1/racks/${r.id}`,
        description: (r) =>
          r.server_count > 0
            ? `${r.name} still holds ${r.server_count} servers; the API refuses until they are moved or decommissioned.`
            : 'The rack has no servers. This cannot be undone.',
      }}
      persistKey="admin-racks"
    />
  );
}
