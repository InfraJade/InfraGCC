import { Link } from 'react-router-dom';

import { useCan, useCursorList } from '@/api/hooks';
import type { Room, SiteOut, SiteSummary } from '@/api/types';
import { type Column } from '@/components/DataTable';
import { FormField, Select, TextInput } from '@/components/FormField';
import { HealthBadge } from '@/components/HealthBadge';
import { formatNumber } from '@/lib/format';

import { CrudList, FilterSelect, optText, type CrudForm, type FormErrors } from './crud';
import { useSiteParam, useSites, useUnrestricted } from './pickers';

// ---------------------------------------------------------------------------------------------- sites

interface SiteForm {
  code: string;
  name: string;
  city: string;
  country: string;
  timezone: string;
}

const count = (n: number | undefined) => formatNumber(n ?? 0, 0);

const siteColumns: Column<SiteSummary>[] = [
  {
    id: 'code',
    header: 'Code',
    cell: (s) => (
      <Link to={`/sites/${s.id}`} className="font-medium text-text hover:text-accent hover:underline">
        {s.code}
      </Link>
    ),
  },
  { id: 'name', header: 'Name', cell: (s) => s.name },
  { id: 'city', header: 'City', cell: (s) => s.city },
  { id: 'country', header: 'Country', cell: (s) => s.country },
  { id: 'timezone', header: 'Time zone', cell: (s) => s.timezone },
  { id: 'rooms', header: 'Rooms', align: 'right', cell: (s) => count(s.room_count) },
  { id: 'racks', header: 'Racks', align: 'right', cell: (s) => count(s.rack_count) },
  { id: 'servers', header: 'Servers', align: 'right', cell: (s) => count(s.server_count) },
  {
    id: 'health',
    header: 'Worst health',
    cell: (s) => <HealthBadge health={s.worst_health} size="sm" context={s.code} />,
  },
];

/** IANA zones the browser knows (falls back to a short list). */
function timeZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  try {
    const zones = intl.supportedValuesOf?.('timeZone');
    if (zones?.length) return zones.includes('UTC') ? zones : ['UTC', ...zones];
  } catch {
    // older engines
  }
  return ['UTC', 'Asia/Kolkata', 'Asia/Singapore', 'Europe/London', 'America/New_York'];
}

function SitesList() {
  const can = useCan();
  const unrestricted = useUnrestricted();
  const canEdit = can('edit_sites');
  const list = useCursorList<SiteSummary>('/api/v1/sites');
  const zones = timeZones().map((z) => ({ value: z, label: z }));

  const form: CrudForm<SiteSummary, SiteForm, SiteOut> = {
    empty: () => ({ code: '', name: '', city: '', country: '', timezone: 'UTC' }),
    fromRow: (s) => ({ code: s.code, name: s.name, city: s.city, country: s.country, timezone: s.timezone }),
    validate: (v, mode) => {
      const e: FormErrors = {};
      if (mode === 'create' && !/^[A-Z0-9][A-Z0-9-]{1,15}$/.test(v.code.trim()))
        e.code = 'Use 2–16 capital letters, digits or dashes, e.g. PNQ1.';
      if (!v.name.trim()) e.name = 'Enter a name.';
      if (!v.city.trim()) e.city = 'Enter a city.';
      if (!v.country.trim()) e.country = 'Enter a country.';
      return e;
    },
    create: unrestricted
      ? (v) => ({
          method: 'POST',
          path: '/api/v1/sites',
          body: {
            code: v.code.trim(),
            name: v.name.trim(),
            city: v.city.trim(),
            country: v.country.trim(),
            timezone: v.timezone,
          },
        })
      : undefined,
    update: (v, s) => ({
      method: 'PATCH',
      path: `/api/v1/sites/${s.id}`,
      body: { name: v.name.trim(), city: v.city.trim(), country: v.country.trim(), timezone: v.timezone },
    }),
    render: ({ values, set, errors, mode }) => (
      <>
        <FormField
          label="Code"
          required={mode === 'create'}
          error={errors.code}
          hint={
            mode === 'create'
              ? 'Short code used everywhere, e.g. PNQ1. It cannot change later.'
              : 'Codes cannot change.'
          }
        >
          <TextInput
            value={values.code}
            disabled={mode === 'edit'}
            maxLength={16}
            onChange={(e) => set('code', e.target.value.toUpperCase())}
          />
        </FormField>
        <FormField label="Name" required error={errors.name}>
          <TextInput value={values.name} maxLength={120} onChange={(e) => set('name', e.target.value)} />
        </FormField>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="City" required error={errors.city}>
            <TextInput value={values.city} maxLength={120} onChange={(e) => set('city', e.target.value)} />
          </FormField>
          <FormField label="Country" required error={errors.country}>
            <TextInput
              value={values.country}
              maxLength={80}
              onChange={(e) => set('country', e.target.value)}
            />
          </FormField>
        </div>
        <FormField label="Time zone" required error={errors.timezone} hint="Used for site-local times.">
          <Select value={values.timezone} options={zones} onChange={(e) => set('timezone', e.target.value)} />
        </FormField>
      </>
    ),
  };

  return (
    <CrudList<SiteSummary, SiteForm, SiteOut>
      title="Sites"
      noun="site"
      caption="Sites"
      intro="Data centers with their rooms, racks and servers."
      columns={siteColumns}
      table={list.tableProps}
      getRowId={(s) => s.id}
      rowName={(s) => `site ${s.code}`}
      invalidate={['sites', 'rooms', 'overview']}
      canEdit={canEdit}
      readOnlyReason="Changing sites and rooms needs the Platform admin role."
      emptyTitle="No sites yet"
      emptyDescription={
        canEdit ? 'Add the first data center with "Add site".' : 'No sites are visible to you.'
      }
      form={form}
      remove={
        unrestricted
          ? {
              path: (s) => `/api/v1/sites/${s.id}`,
              description: () => 'Only empty sites can be deleted (no rooms, servers or collectors).',
            }
          : undefined
      }
      persistKey="admin-sites"
    />
  );
}

// ---------------------------------------------------------------------------------------------- rooms

interface RoomForm {
  site_id: string;
  name: string;
  floor: string;
}

const roomColumns: Column<Room>[] = [
  { id: 'site', header: 'Site', cell: (r) => r.site_code },
  { id: 'name', header: 'Room', cell: (r) => <span className="font-medium">{r.name}</span> },
  { id: 'floor', header: 'Floor', cell: (r) => r.floor ?? <span className="text-text-subtle">—</span> },
  { id: 'racks', header: 'Racks', align: 'right', cell: (r) => formatNumber(r.rack_count, 0) },
];

function RoomsList() {
  const can = useCan();
  const canEdit = can('edit_sites');
  const sites = useSites();
  const [siteId, setSiteId] = useSiteParam();
  const list = useCursorList<Room>('/api/v1/rooms', { site_id: siteId });

  const form: CrudForm<Room, RoomForm, Room> = {
    empty: () => ({ site_id: siteId ? String(siteId) : '', name: '', floor: '' }),
    fromRow: (r) => ({ site_id: String(r.site_id), name: r.name, floor: r.floor ?? '' }),
    validate: (v) => {
      const e: FormErrors = {};
      if (!v.site_id) e.site_id = 'Choose a site.';
      if (!v.name.trim()) e.name = 'Enter a name.';
      return e;
    },
    create: (v) => ({
      method: 'POST',
      path: '/api/v1/rooms',
      body: { site_id: Number(v.site_id), name: v.name.trim(), floor: optText(v.floor) },
    }),
    update: (v, r) => ({
      method: 'PATCH',
      path: `/api/v1/rooms/${r.id}`,
      body: { name: v.name.trim(), floor: optText(v.floor) },
    }),
    render: ({ values, set, errors, mode }) => (
      <>
        <FormField
          label="Site"
          required
          error={errors.site_id}
          hint={mode === 'edit' ? 'A room stays in its site.' : undefined}
        >
          <Select
            value={values.site_id}
            options={sites.options}
            placeholder="Choose a site"
            disabled={mode === 'edit'}
            onChange={(e) => set('site_id', e.target.value)}
          />
        </FormField>
        <FormField label="Name" required error={errors.name} hint="Unique within the site, e.g. Hall A.">
          <TextInput value={values.name} maxLength={64} onChange={(e) => set('name', e.target.value)} />
        </FormField>
        <FormField label="Floor" error={errors.floor}>
          <TextInput value={values.floor} maxLength={32} onChange={(e) => set('floor', e.target.value)} />
        </FormField>
      </>
    ),
  };

  return (
    <CrudList<Room, RoomForm, Room>
      title="Rooms"
      noun="room"
      caption="Rooms"
      intro="Halls inside each site; racks belong to a room."
      columns={roomColumns}
      table={list.tableProps}
      getRowId={(r) => r.id}
      rowName={(r) => `room ${r.name} (${r.site_code})`}
      invalidate={['rooms', 'sites', 'racks']}
      canEdit={canEdit}
      toolbar={
        <FilterSelect
          label="Site"
          value={siteId ? String(siteId) : ''}
          onChange={setSiteId}
          options={sites.options}
          placeholder="All sites"
        />
      }
      emptyTitle="No rooms"
      emptyDescription={siteId ? 'This site has no rooms yet.' : 'No rooms yet.'}
      form={form}
      remove={{
        path: (r) => `/api/v1/rooms/${r.id}`,
        description: () => 'Only rooms without racks can be deleted.',
      }}
      persistKey="admin-rooms"
    />
  );
}

export default function SitesSection() {
  return (
    <div className="flex flex-col gap-8">
      <SitesList />
      <RoomsList />
    </div>
  );
}
