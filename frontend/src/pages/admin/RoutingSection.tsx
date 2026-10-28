import { send, useApiMutation, useCan, useCursorList } from '@/api/hooks';
import type { AlertRoute } from '@/api/types';
import { Pill, SeverityBadge } from '@/components/Badges';
import { type Column } from '@/components/DataTable';
import { FormField, Select, TextArea, TextInput } from '@/components/FormField';
import { formatTimestamp } from '@/lib/format';

import { CrudList, FilterSelect, Hint, RowSwitch, type CrudForm, type FormErrors } from './crud';
import { useSiteParam, useSites, useUnrestricted } from './pickers';

interface RouteForm {
  name: string;
  route: string;
  site_id: string;
  min_severity: string;
  escalation_level: string;
  channel: string;
  /** Empty on edit = keep the stored target (it is encrypted and never sent back). */
  target: string;
  enabled: boolean;
}

const CHANNEL_OPTIONS = [
  { value: 'email', label: 'Email' },
  { value: 'teams', label: 'Microsoft Teams' },
];
const SEVERITY_OPTIONS = [
  { value: 'Critical', label: 'Critical only' },
  { value: 'Warning', label: 'Warning and up' },
  { value: 'Info', label: 'Everything (Info and up)' },
];
const LEVEL_OPTIONS = [
  { value: '0', label: 'First notice (when the alert opens)' },
  ...[1, 2, 3, 4, 5].map((n) => ({
    value: String(n),
    label: `Escalation ${n} (critical unacknowledged ${n * 15} min)`,
  })),
];
const CHANNEL_WORD: Record<string, string> = { email: 'Email', teams: 'Teams' };
const NEUTRAL = 'text-text-muted bg-text/5 ring-1 ring-inset ring-text/15';

const EMAIL_RE = /^[^\s@,]+@[^\s@,]+\.[^\s@,]+$/;

function validate(v: RouteForm, mode: 'create' | 'edit', row: AlertRoute | null): FormErrors {
  const e: FormErrors = {};
  if (!v.name.trim()) e.name = 'Give the route a name.';
  if (!/^(\*|[a-z0-9_-]{1,32})$/.test(v.route.trim()))
    e.route = 'Use * for every team, or a key like hardware (lower-case letters, digits, - and _).';
  const target = v.target.trim();
  const needsTarget = mode === 'create' || (row !== null && v.channel !== row.channel);
  if (!target && needsTarget)
    e.target =
      v.channel === 'teams' ? 'Paste the Teams incoming-webhook URL.' : 'Enter at least one email address.';
  if (target && v.channel === 'email') {
    const bad = target
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s && !EMAIL_RE.test(s));
    if (bad.length) e.target = `Not an email address: ${bad.join(', ')}`;
  }
  if (target && v.channel === 'teams' && !/^https:\/\/\S+$/.test(target))
    e.target = 'The webhook URL must start with https://.';
  return e;
}

export default function RoutingSection() {
  const can = useCan();
  const canEdit = can('edit_alert_routes');
  const unrestricted = useUnrestricted();
  const sites = useSites();
  const [siteId, setSiteId] = useSiteParam();
  const list = useCursorList<AlertRoute>('/api/v1/alert-routes', { site_id: siteId });
  const toggle = useApiMutation<{ id: number; enabled: boolean }, AlertRoute>(
    (api, v) => api.json<AlertRoute>(`/api/v1/alert-routes/${v.id}`, send('PATCH', { enabled: v.enabled })),
    { invalidate: ['alert-routes'], success: (r) => `${r.name} ${r.enabled ? 'enabled' : 'disabled'}` },
  );
  // Site-limited admins may only change routes of their own sites.
  const mayChange = (r: AlertRoute) => unrestricted || r.site_id !== null;

  const siteName = (id: number | null) =>
    id === null ? 'All sites' : (sites.byId.get(id)?.code ?? `Site ${id}`);

  const columns: Column<AlertRoute>[] = [
    { id: 'name', header: 'Name', cell: (r) => <span className="font-medium">{r.name}</span> },
    { id: 'site', header: 'Site', cell: (r) => siteName(r.site_id) },
    {
      id: 'route',
      header: 'Team',
      label: 'Team (route key)',
      cell: (r) => (r.route === '*' ? 'Any' : <span className="font-mono text-xs">{r.route}</span>),
    },
    {
      id: 'severity',
      header: 'Min. severity',
      cell: (r) => <SeverityBadge severity={r.min_severity} />,
    },
    {
      id: 'level',
      header: 'When',
      cell: (r) =>
        r.escalation_level === 0 ? (
          'On open'
        ) : (
          <Pill icon="clock" className={NEUTRAL}>
            Escalation {r.escalation_level}
          </Pill>
        ),
    },
    { id: 'channel', header: 'Channel', cell: (r) => CHANNEL_WORD[r.channel] ?? r.channel },
    {
      id: 'target',
      header: 'Target',
      cell: (r) => (
        <span className="font-mono text-xs" title="Stored encrypted; only a hint is shown.">
          {r.target_hint}
        </span>
      ),
    },
    {
      id: 'enabled',
      header: 'Enabled',
      cell: (r) => (
        <RowSwitch
          checked={r.enabled}
          label={`Enabled: ${r.name}`}
          busy={toggle.isPending && toggle.variables?.id === r.id}
          onChange={canEdit && mayChange(r) ? (enabled) => toggle.mutate({ id: r.id, enabled }) : undefined}
        />
      ),
    },
    {
      id: 'updated',
      header: 'Updated',
      defaultHidden: true,
      cell: (r) => <span className="tabular whitespace-nowrap">{formatTimestamp(r.updated_at)}</span>,
    },
  ];

  const form: CrudForm<AlertRoute, RouteForm, AlertRoute> = {
    empty: () => ({
      name: '',
      route: '*',
      site_id: siteId ? String(siteId) : '',
      min_severity: 'Critical',
      escalation_level: '0',
      channel: 'email',
      target: '',
      enabled: true,
    }),
    fromRow: (r) => ({
      name: r.name,
      route: r.route,
      site_id: r.site_id === null ? '' : String(r.site_id),
      min_severity: r.min_severity,
      escalation_level: String(r.escalation_level),
      channel: r.channel,
      target: '',
      enabled: r.enabled,
    }),
    validate,
    editable: mayChange,
    create: (v) => ({
      method: 'POST',
      path: '/api/v1/alert-routes',
      body: {
        name: v.name.trim(),
        route: v.route.trim(),
        site_id: v.site_id ? Number(v.site_id) : null,
        min_severity: v.min_severity,
        escalation_level: Number(v.escalation_level),
        channel: v.channel,
        target: v.target.trim(),
        enabled: v.enabled,
      },
    }),
    update: (v, r) => ({
      method: 'PATCH',
      path: `/api/v1/alert-routes/${r.id}`,
      body: {
        name: v.name.trim(),
        route: v.route.trim(),
        site_id: v.site_id ? Number(v.site_id) : null,
        min_severity: v.min_severity,
        escalation_level: Number(v.escalation_level),
        channel: v.channel,
        ...(v.target.trim() ? { target: v.target.trim() } : {}),
      },
    }),
    size: 'lg',
    render: ({ values, set, errors, mode }, row) => (
      <>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Name" required error={errors.name}>
            <TextInput
              value={values.name}
              maxLength={120}
              placeholder="e.g. PNQ1 NOC email"
              onChange={(e) => set('name', e.target.value)}
            />
          </FormField>
          <FormField
            label="Site"
            error={errors.site_id}
            hint={unrestricted ? 'Leave on “All sites” for a company-wide route.' : undefined}
          >
            <Select
              value={values.site_id}
              options={unrestricted ? [{ value: '', label: 'All sites' }, ...sites.options] : sites.options}
              placeholder={unrestricted ? undefined : 'Choose a site'}
              onChange={(e) => set('site_id', e.target.value)}
            />
          </FormField>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Minimum severity" required error={errors.min_severity}>
            <Select
              value={values.min_severity}
              options={SEVERITY_OPTIONS}
              onChange={(e) => set('min_severity', e.target.value)}
            />
          </FormField>
          <FormField
            label="Team (route key)"
            required
            error={errors.route}
            hint="Alert rules carry a route key (default hardware). * matches every rule."
          >
            <TextInput
              value={values.route}
              maxLength={32}
              spellCheck={false}
              className="font-mono"
              onChange={(e) => set('route', e.target.value.toLowerCase())}
            />
          </FormField>
        </div>
        <FormField label="When to notify" required error={errors.escalation_level}>
          <Select
            value={values.escalation_level}
            options={LEVEL_OPTIONS}
            onChange={(e) => set('escalation_level', e.target.value)}
          />
        </FormField>
        <div className="grid gap-4 sm:grid-cols-[12rem_1fr]">
          <FormField label="Channel" required error={errors.channel}>
            <Select
              value={values.channel}
              options={CHANNEL_OPTIONS}
              onChange={(e) => set('channel', e.target.value)}
            />
          </FormField>
          <FormField
            label={values.channel === 'teams' ? 'Webhook URL' : 'Email addresses'}
            required={mode === 'create'}
            error={errors.target}
            hint={
              mode === 'edit' && row
                ? `Currently ${row.target_hint}. Leave empty to keep it${
                    values.channel !== row.channel ? ' (a new channel needs a new target)' : ''
                  }.`
                : values.channel === 'teams'
                  ? 'The incoming-webhook URL of the Teams channel.'
                  : 'Comma-separated, e.g. noc@example.com, oncall@example.com'
            }
          >
            {values.channel === 'teams' ? (
              <TextInput
                value={values.target}
                maxLength={2000}
                spellCheck={false}
                className="font-mono"
                placeholder="https://…"
                onChange={(e) => set('target', e.target.value)}
              />
            ) : (
              <TextArea
                value={values.target}
                maxLength={2000}
                rows={2}
                spellCheck={false}
                onChange={(e) => set('target', e.target.value)}
              />
            )}
          </FormField>
        </div>
        <Hint>Targets are stored encrypted and never shown again; the list shows a masked hint.</Hint>
      </>
    ),
  };

  return (
    <CrudList<AlertRoute, RouteForm, AlertRoute>
      title="Alert routing"
      noun="route"
      caption="Alert routes"
      intro="Where notifications go: by site, team and minimum severity. Unacknowledged critical alerts escalate every 15 minutes to the next level."
      columns={columns}
      table={list.tableProps}
      getRowId={(r) => r.id}
      rowName={(r) => r.name}
      invalidate={['alert-routes']}
      canEdit={canEdit}
      readOnlyReason="Changing alert routing needs the Platform admin role."
      createLabel="Add route"
      toolbar={
        <FilterSelect
          label="Site"
          value={siteId ? String(siteId) : ''}
          onChange={setSiteId}
          options={sites.options}
          placeholder="All sites"
        />
      }
      emptyTitle="No routes"
      emptyDescription="Without a route, alerts show in the app but nobody is notified."
      form={form}
      remove={{
        path: (r) => `/api/v1/alert-routes/${r.id}`,
        allowed: mayChange,
        description: () => 'Alerts that only matched this route will no longer notify anyone.',
      }}
      persistKey="admin-routing"
    />
  );
}
