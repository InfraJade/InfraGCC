import { useCan, useCursorList } from '@/api/hooks';
import type { Maintenance } from '@/api/types';
import { Pill } from '@/components/Badges';
import { Combobox } from '@/components/Combobox';
import { type Column } from '@/components/DataTable';
import { FormField, Select, TextArea, TextInput } from '@/components/FormField';
import { formatTimestamp, toMillis } from '@/lib/format';
import { healthClasses } from '@/lib/health';
import { numberParam, useUrlState } from '@/lib/useUrlState';

import {
  CrudList,
  FilterSelect,
  Hint,
  isoToLocalInput,
  localInputToIso,
  toLocalInput,
  type CrudForm,
  type FormApi,
  type FormErrors,
} from './crud';
import { useRacks, useRooms, useSiteParam, useSites, useSiteServers } from './pickers';

export interface MaintenanceForm {
  scope: string;
  site_id: string;
  room_id: string;
  rack_id: string;
  server_id: string;
  /** datetime-local values in the browser's time zone. */
  starts_at: string;
  ends_at: string;
  reason: string;
}

const WHEN_OPTIONS = [
  { value: 'current_and_upcoming', label: 'Current & upcoming' },
  { value: 'active', label: 'Active now' },
  { value: 'upcoming', label: 'Upcoming' },
  { value: 'past', label: 'Past' },
];
const SCOPE_OPTIONS = [
  { value: 'server', label: 'One server' },
  { value: 'rack', label: 'A whole rack' },
  { value: 'site', label: 'A whole site' },
];
const SCOPE_WORD: Record<string, string> = { server: 'Server', rack: 'Rack', site: 'Site' };

const NEUTRAL = 'text-text-muted bg-text/5 ring-1 ring-inset ring-text/15';

function WindowState({ mw }: { mw: Maintenance }) {
  if (mw.active)
    return (
      <Pill icon="clock" className={healthClasses.Warning.soft}>
        Active now
      </Pill>
    );
  return toMillis(mw.starts_at) > Date.now() ? (
    <Pill icon="clock" className="text-info bg-info/10 ring-1 ring-inset ring-info/30">
      Upcoming
    </Pill>
  ) : (
    <Pill icon="check" className={NEUTRAL}>
      Ended
    </Pill>
  );
}

const Time = ({ iso }: { iso: string }) => (
  <time dateTime={iso} className="tabular whitespace-nowrap">
    {formatTimestamp(iso)}
  </time>
);

const columns: Column<Maintenance>[] = [
  { id: 'target', header: 'Target', cell: (m) => <span className="font-medium">{m.target_name}</span> },
  { id: 'scope', header: 'Scope', cell: (m) => SCOPE_WORD[m.scope] ?? m.scope },
  { id: 'starts', header: 'Starts', cell: (m) => <Time iso={m.starts_at} /> },
  { id: 'ends', header: 'Ends', cell: (m) => <Time iso={m.ends_at} /> },
  { id: 'state', header: 'Active now', label: 'Active now', cell: (m) => <WindowState mw={m} /> },
  {
    id: 'reason',
    header: 'Reason',
    cell: (m) => (
      <span className="line-clamp-2 max-w-xs" title={m.reason}>
        {m.reason}
      </span>
    ),
  },
  {
    id: 'created_by',
    header: 'Created by',
    cell: (m) => m.created_by ?? <span className="text-text-subtle">—</span>,
  },
];

/** "UTC+05:30" for the browser's current offset. */
function browserOffset(): string {
  const off = -new Date().getTimezoneOffset();
  const abs = Math.abs(off);
  return `UTC${off >= 0 ? '+' : '-'}${String(Math.floor(abs / 60)).padStart(2, '0')}:${String(abs % 60).padStart(2, '0')}`;
}

function defaultStart(): Date {
  const d = new Date();
  d.setSeconds(0, 0);
  d.setMinutes(Math.ceil((d.getMinutes() + 1) / 15) * 15);
  return d;
}

function MaintenanceFields({ form, row }: { form: FormApi<MaintenanceForm>; row: Maintenance | null }) {
  const { values, set, patch, errors, mode } = form;
  const sites = useSites();
  const siteId = numberParam(values.site_id);
  const rooms = useRooms(values.scope === 'rack' ? siteId : undefined);
  const racks = useRacks(values.scope === 'rack' ? numberParam(values.room_id) : undefined);
  const servers = useSiteServers(values.scope === 'server' ? siteId : undefined);

  return (
    <>
      {mode === 'edit' && row ? (
        <p className="text-sm text-text-muted">
          {SCOPE_WORD[row.scope] ?? row.scope}:{' '}
          <span className="font-medium text-text">{row.target_name}</span>
          <span className="block text-xs text-text-subtle">
            To cover something else, create a new window.
          </span>
        </p>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField label="Covers" required error={errors.scope}>
              <Select
                value={values.scope}
                options={SCOPE_OPTIONS}
                onChange={(e) => patch({ scope: e.target.value, room_id: '', rack_id: '', server_id: '' })}
              />
            </FormField>
            <FormField label="Site" required error={errors.site_id}>
              <Select
                value={values.site_id}
                options={sites.options}
                placeholder="Choose a site"
                onChange={(e) => patch({ site_id: e.target.value, room_id: '', rack_id: '', server_id: '' })}
              />
            </FormField>
          </div>
          {values.scope === 'rack' ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField label="Room" required error={errors.room_id}>
                <Select
                  value={values.room_id}
                  options={rooms.options}
                  placeholder={values.site_id ? 'Choose a room' : 'Choose a site first'}
                  disabled={!values.site_id}
                  onChange={(e) => patch({ room_id: e.target.value, rack_id: '' })}
                />
              </FormField>
              <FormField label="Rack" required error={errors.rack_id}>
                <Select
                  value={values.rack_id}
                  options={racks.options}
                  placeholder={values.room_id ? 'Choose a rack' : 'Choose a room first'}
                  disabled={!values.room_id}
                  onChange={(e) => set('rack_id', e.target.value)}
                />
              </FormField>
            </div>
          ) : null}
          {values.scope === 'server' ? (
            <FormField label="Server" required error={errors.server_id}>
              <Combobox
                options={servers.options}
                value={values.server_id || null}
                onChange={(v) => set('server_id', v ?? '')}
                placeholder={values.site_id ? 'Search servers of the site…' : 'Choose a site first'}
                loading={servers.loading}
                disabled={!values.site_id}
              />
            </FormField>
          ) : null}
        </>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Starts" required error={errors.starts_at}>
          <TextInput
            type="datetime-local"
            value={values.starts_at}
            onChange={(e) => set('starts_at', e.target.value)}
          />
        </FormField>
        <FormField label="Ends" required error={errors.ends_at}>
          <TextInput
            type="datetime-local"
            value={values.ends_at}
            onChange={(e) => set('ends_at', e.target.value)}
          />
        </FormField>
      </div>
      <Hint>
        Times are in your browser&apos;s time zone ({browserOffset()}) and are sent with that offset. Alerts
        for the covered servers are muted while the window is active.
      </Hint>
      <FormField label="Reason" required error={errors.reason}>
        <TextArea value={values.reason} maxLength={2000} onChange={(e) => set('reason', e.target.value)} />
      </FormField>
    </>
  );
}

function validate(v: MaintenanceForm, mode: 'create' | 'edit'): FormErrors {
  const e: FormErrors = {};
  if (mode === 'create') {
    if (!v.site_id) e.site_id = 'Choose a site.';
    if (v.scope === 'rack' && !v.rack_id) e.rack_id = 'Choose a rack.';
    if (v.scope === 'rack' && !v.room_id) e.room_id = 'Choose a room.';
    if (v.scope === 'server' && !v.server_id) e.server_id = 'Choose a server.';
  }
  const start = localInputToIso(v.starts_at);
  const end = localInputToIso(v.ends_at);
  if (!start) e.starts_at = 'Enter a start date and time.';
  if (!end) e.ends_at = 'Enter an end date and time.';
  if (start && end && toMillis(end) <= toMillis(start)) e.ends_at = 'The end must be after the start.';
  if (!v.reason.trim()) e.reason = 'Say what the work is.';
  return e;
}

export default function MaintenanceSection() {
  const can = useCan();
  const canEdit = can('edit_maintenance');
  const sites = useSites();
  const [siteId, setSiteId] = useSiteParam();
  const [f, setF] = useUrlState({ when: 'current_and_upcoming' });
  const list = useCursorList<Maintenance>('/api/v1/maintenance-windows', { when: f.when, site_id: siteId });

  const form: CrudForm<Maintenance, MaintenanceForm, Maintenance> = {
    empty: () => {
      const start = defaultStart();
      return {
        scope: 'server',
        site_id: siteId ? String(siteId) : '',
        room_id: '',
        rack_id: '',
        server_id: '',
        starts_at: toLocalInput(start),
        ends_at: toLocalInput(new Date(start.getTime() + 2 * 3600_000)),
        reason: '',
      };
    },
    fromRow: (m) => ({
      scope: m.scope,
      site_id: String(m.target_site_id),
      room_id: '',
      rack_id: m.rack_id ? String(m.rack_id) : '',
      server_id: m.server_id ? String(m.server_id) : '',
      starts_at: isoToLocalInput(m.starts_at),
      ends_at: isoToLocalInput(m.ends_at),
      reason: m.reason,
    }),
    validate: (v, mode) => validate(v, mode),
    create: (v) => ({
      method: 'POST',
      path: '/api/v1/maintenance-windows',
      body: {
        scope: v.scope,
        site_id: v.scope === 'site' ? Number(v.site_id) : null,
        rack_id: v.scope === 'rack' ? Number(v.rack_id) : null,
        server_id: v.scope === 'server' ? Number(v.server_id) : null,
        starts_at: localInputToIso(v.starts_at),
        ends_at: localInputToIso(v.ends_at),
        reason: v.reason.trim(),
      },
    }),
    update: (v, m) => ({
      method: 'PATCH',
      path: `/api/v1/maintenance-windows/${m.id}`,
      body: {
        starts_at: localInputToIso(v.starts_at),
        ends_at: localInputToIso(v.ends_at),
        reason: v.reason.trim(),
      },
    }),
    render: (form, row) => <MaintenanceFields form={form} row={row} />,
  };

  return (
    <CrudList<Maintenance, MaintenanceForm, Maintenance>
      title="Maintenance windows"
      noun="maintenance window"
      caption="Maintenance windows"
      intro="Planned work: alerts for the covered site, rack or server are muted while a window is active."
      columns={columns}
      table={list.tableProps}
      getRowId={(m) => m.id}
      rowName={(m) => `window for ${m.target_name}`}
      invalidate={['maintenance-windows', 'servers', 'alerts', 'overview']}
      canEdit={canEdit}
      readOnlyReason="Scheduling maintenance needs the DC engineer role."
      createLabel="Schedule maintenance"
      toolbar={
        <>
          <FilterSelect
            label="When"
            value={f.when}
            onChange={(v) => setF({ when: v === 'current_and_upcoming' ? '' : v })}
            options={WHEN_OPTIONS}
          />
          <FilterSelect
            label="Site"
            value={siteId ? String(siteId) : ''}
            onChange={setSiteId}
            options={sites.options}
            placeholder="All sites"
          />
        </>
      }
      emptyTitle="No maintenance windows"
      emptyDescription={
        f.when === 'past'
          ? 'No past windows match.'
          : 'Nothing is scheduled. Planned work goes here so alerts stay quiet.'
      }
      form={form}
      remove={{
        path: (m) => `/api/v1/maintenance-windows/${m.id}`,
        description: (m) =>
          m.active
            ? 'The window is active now: alerts for its servers start notifying again.'
            : 'The window is removed.',
      }}
      persistKey="admin-maintenance"
    />
  );
}
