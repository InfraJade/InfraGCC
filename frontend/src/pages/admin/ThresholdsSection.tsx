import { Link } from 'react-router-dom';

import { useApiQuery, useCan, useCursorList } from '@/api/hooks';
import type { Metric, ServerDetail, Threshold } from '@/api/types';
import { Age } from '@/components/Reading';
import { Combobox } from '@/components/Combobox';
import { type Column } from '@/components/DataTable';
import { FormField, NumberInput, Select, TextInput } from '@/components/FormField';
import { formatValue } from '@/lib/format';
import { numberParam, useUrlState } from '@/lib/useUrlState';

import {
  CrudList,
  FilterSelect,
  Hint,
  isNumber,
  numText,
  optNumber,
  optText,
  type CrudForm,
  type FormApi,
  type FormErrors,
} from './crud';
import { metricOptions, useMetrics, useSites, useSiteServers, useUnrestricted } from './pickers';

export interface ThresholdForm {
  metric: string;
  scope: string;
  site_id: string;
  server_id: string;
  vendor: string;
  model: string;
  direction: string;
  warning: string;
  critical: string;
  nominal: string;
}

const SCOPE_OPTIONS = [
  { value: 'global', label: 'Global (every server)' },
  { value: 'model', label: 'Server model' },
  { value: 'site', label: 'Site' },
  { value: 'server', label: 'One server' },
];
const SCOPE_WORD: Record<string, string> = {
  global: 'Global',
  model: 'Model',
  site: 'Site',
  server: 'Server',
};
const DIRECTION_OPTIONS = [
  { value: 'above', label: 'Alert above the limit' },
  { value: 'below', label: 'Alert below the limit' },
  { value: 'deviation_pct', label: 'Deviation from nominal (%)' },
  { value: 'pct_of_capacity', label: 'Percent of capacity (%)' },
];
const DIRECTION_WORD: Record<string, string> = {
  above: 'Above',
  below: 'Below',
  deviation_pct: 'Deviation from nominal',
  pct_of_capacity: '% of capacity',
};

/** Limits of percentage directions are in %, others in the metric's unit. */
export function limitUnit(direction: string, unit: string): string {
  return direction === 'deviation_pct' || direction === 'pct_of_capacity' ? '%' : unit;
}

function ServerName({ id }: { id: number }) {
  const q = useApiQuery<ServerDetail>(`/api/v1/servers/${id}`, undefined, { staleTime: 5 * 60_000 });
  return (
    <Link to={`/servers/${id}`} className="hover:text-accent hover:underline">
      {q.data ? q.data.name || q.data.bmc_host : `Server ${id}`}
    </Link>
  );
}

function ThresholdFields({ form, metrics }: { form: FormApi<ThresholdForm>; metrics: Metric[] }) {
  const { values, set, patch, errors, mode } = form;
  const unrestricted = useUnrestricted();
  const sites = useSites();
  const servers = useSiteServers(values.scope === 'server' ? numberParam(values.site_id) : undefined);
  const metric = metrics.find((m) => m.code === values.metric);
  const unit = limitUnit(values.direction, metric?.unit ?? '');
  const scopes = unrestricted
    ? SCOPE_OPTIONS
    : SCOPE_OPTIONS.filter((s) => s.value === 'site' || s.value === 'server');
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Metric" required error={errors.metric}>
          <Select
            value={values.metric}
            options={metricOptions(metrics, ['gauge'])}
            placeholder="Choose a metric"
            disabled={mode === 'edit'}
            onChange={(e) => set('metric', e.target.value)}
          />
        </FormField>
        <FormField label="Applies to" required error={errors.scope}>
          <Select
            value={values.scope}
            options={scopes}
            disabled={mode === 'edit'}
            onChange={(e) =>
              patch({ scope: e.target.value, site_id: '', server_id: '', vendor: '', model: '' })
            }
          />
        </FormField>
      </div>
      {values.scope === 'model' ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField
            label="Vendor"
            error={errors.vendor}
            hint="Optional: empty matches the model from any vendor."
          >
            <TextInput
              value={values.vendor}
              maxLength={32}
              disabled={mode === 'edit'}
              onChange={(e) => set('vendor', e.target.value)}
            />
          </FormField>
          <FormField label="Model" required error={errors.model} hint="As discovered, e.g. PowerEdge R750.">
            <TextInput
              value={values.model}
              maxLength={128}
              disabled={mode === 'edit'}
              onChange={(e) => set('model', e.target.value)}
            />
          </FormField>
        </div>
      ) : null}
      {values.scope === 'site' || values.scope === 'server' ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Site" required error={errors.site_id}>
            <Select
              value={values.site_id}
              options={sites.options}
              placeholder="Choose a site"
              disabled={mode === 'edit'}
              onChange={(e) => patch({ site_id: e.target.value, server_id: '' })}
            />
          </FormField>
          {values.scope === 'server' ? (
            <FormField label="Server" required error={errors.server_id}>
              <Combobox
                options={servers.options}
                value={values.server_id || null}
                onChange={(v) => set('server_id', v ?? '')}
                placeholder={values.site_id ? 'Search servers…' : 'Choose a site first'}
                loading={servers.loading}
                disabled={mode === 'edit' || !values.site_id}
              />
            </FormField>
          ) : null}
        </div>
      ) : null}
      <FormField label="Direction" required error={errors.direction}>
        <Select
          value={values.direction}
          options={DIRECTION_OPTIONS}
          onChange={(e) => set('direction', e.target.value)}
        />
      </FormField>
      <div className="grid gap-4 sm:grid-cols-3">
        <FormField label="Warning" error={errors.warning}>
          <NumberInput
            unit={unit}
            step="any"
            value={values.warning}
            onChange={(e) => set('warning', e.target.value)}
          />
        </FormField>
        <FormField label="Critical" error={errors.critical}>
          <NumberInput
            unit={unit}
            step="any"
            value={values.critical}
            onChange={(e) => set('critical', e.target.value)}
          />
        </FormField>
        <FormField
          label="Nominal"
          required={values.direction === 'deviation_pct'}
          error={errors.nominal}
          hint="Expected value"
        >
          <NumberInput
            unit={metric?.unit}
            step="any"
            value={values.nominal}
            onChange={(e) => set('nominal', e.target.value)}
          />
        </FormField>
      </div>
      <Hint>
        Set a warning limit, a critical limit or both. The most specific threshold wins: server, then site,
        then model, then global; BMC limits apply when none is set.
      </Hint>
    </>
  );
}

function validate(v: ThresholdForm, mode: 'create' | 'edit'): FormErrors {
  const e: FormErrors = {};
  if (mode === 'create') {
    if (!v.metric) e.metric = 'Choose a metric.';
    if ((v.scope === 'site' || v.scope === 'server') && !v.site_id) e.site_id = 'Choose a site.';
    if (v.scope === 'server' && !v.server_id) e.server_id = 'Choose a server.';
    if (v.scope === 'model' && !v.model.trim()) e.model = 'Enter the model.';
  }
  for (const k of ['warning', 'critical', 'nominal'] as const)
    if (v[k].trim() && !isNumber(v[k])) e[k] = 'Enter a number.';
  if (!v.warning.trim() && !v.critical.trim()) e.warning = 'Set a warning or a critical limit (or both).';
  if (v.direction === 'deviation_pct' && !v.nominal.trim()) e.nominal = 'Deviation needs the nominal value.';
  return e;
}

const limits = (v: ThresholdForm) => ({
  direction: v.direction,
  warning: optNumber(v.warning),
  critical: optNumber(v.critical),
  nominal: optNumber(v.nominal),
});

export default function ThresholdsSection() {
  const can = useCan();
  const canEdit = can('edit_thresholds');
  const unrestricted = useUnrestricted();
  const sites = useSites();
  const { metrics } = useMetrics();
  const [f, setF] = useUrlState({ metric: '', scope: '' });
  const list = useCursorList<Threshold>('/api/v1/thresholds', { metric: f.metric, scope: f.scope });

  const target = (t: Threshold) => {
    switch (t.scope) {
      case 'global':
        return 'All servers';
      case 'model':
        return `${t.vendor ?? 'Any vendor'} ${t.model ?? ''}`.trim();
      case 'site': {
        const s = t.site_id !== null ? sites.byId.get(t.site_id) : undefined;
        return s ? s.code : `Site ${t.site_id ?? ''}`;
      }
      default:
        return t.server_id !== null ? <ServerName id={t.server_id} /> : '—';
    }
  };

  const value = (t: Threshold, v: number | null, unit = limitUnit(t.direction, t.unit)) =>
    v === null ? (
      <span className="text-text-subtle">—</span>
    ) : (
      <span className="tabular">{formatValue(v, unit)}</span>
    );

  const columns: Column<Threshold>[] = [
    {
      id: 'metric',
      header: 'Metric',
      cell: (t) => (
        <span className="flex flex-col">
          <span className="font-medium">{t.metric_name}</span>
          <span className="text-xs text-text-subtle">
            {t.metric}
            {t.unit ? ` · ${t.unit}` : ''}
          </span>
        </span>
      ),
    },
    {
      id: 'scope',
      header: 'Applies to',
      cell: (t) => (
        <span className="flex flex-col">
          <span>{SCOPE_WORD[t.scope] ?? t.scope}</span>
          <span className="text-xs text-text-muted">{target(t)}</span>
        </span>
      ),
    },
    { id: 'direction', header: 'Direction', cell: (t) => DIRECTION_WORD[t.direction] ?? t.direction },
    { id: 'warning', header: 'Warning', align: 'right', cell: (t) => value(t, t.warning) },
    { id: 'critical', header: 'Critical', align: 'right', cell: (t) => value(t, t.critical) },
    { id: 'nominal', header: 'Nominal', align: 'right', cell: (t) => value(t, t.nominal, t.unit) },
    {
      id: 'updated',
      header: 'Updated',
      cell: (t) => (
        <span className="flex flex-col">
          <Age time={t.updated_at} className="text-xs" />
          <span className="text-xs text-text-subtle">{t.updated_by ?? 'system'}</span>
        </span>
      ),
    },
  ];

  const form: CrudForm<Threshold, ThresholdForm, Threshold> = {
    size: 'lg',
    empty: () => ({
      metric: f.metric,
      scope: unrestricted ? 'model' : 'site',
      site_id: '',
      server_id: '',
      vendor: '',
      model: '',
      direction: 'above',
      warning: '',
      critical: '',
      nominal: '',
    }),
    fromRow: (t) => ({
      metric: t.metric,
      scope: t.scope,
      site_id: t.site_id !== null ? String(t.site_id) : '',
      server_id: t.server_id !== null ? String(t.server_id) : '',
      vendor: t.vendor ?? '',
      model: t.model ?? '',
      direction: t.direction,
      warning: numText(t.warning),
      critical: numText(t.critical),
      nominal: numText(t.nominal),
    }),
    validate: (v, mode) => validate(v, mode),
    create: (v) => ({
      method: 'POST',
      path: '/api/v1/thresholds',
      body: {
        metric: v.metric,
        scope: v.scope,
        site_id: v.scope === 'site' ? Number(v.site_id) : null,
        server_id: v.scope === 'server' ? Number(v.server_id) : null,
        vendor: v.scope === 'model' ? optText(v.vendor) : null,
        model: v.scope === 'model' ? optText(v.model) : null,
        ...limits(v),
      },
    }),
    update: (v, t) => ({ method: 'PUT', path: `/api/v1/thresholds/${t.id}`, body: limits(v) }),
    editable: (t) => unrestricted || t.scope === 'site' || t.scope === 'server',
    render: (form) => <ThresholdFields form={form} metrics={metrics} />,
  };

  return (
    <CrudList<Threshold, ThresholdForm, Threshold>
      title="Thresholds"
      noun="threshold"
      caption="Thresholds"
      intro="Warning and critical limits per metric. Overrides for a model, site or server beat the global default."
      columns={columns}
      table={list.tableProps}
      getRowId={(t) => t.id}
      rowName={(t) => `${t.metric_name} (${SCOPE_WORD[t.scope] ?? t.scope})`}
      invalidate={['thresholds']}
      canEdit={canEdit}
      readOnlyReason="Changing thresholds needs the Platform admin role."
      createLabel="Add override"
      toolbar={
        <>
          <FilterSelect
            label="Metric"
            value={f.metric}
            onChange={(v) => setF({ metric: v })}
            options={metricOptions(metrics, ['gauge'])}
            placeholder="All metrics"
            className="w-56"
          />
          <FilterSelect
            label="Scope"
            value={f.scope}
            onChange={(v) => setF({ scope: v })}
            options={SCOPE_OPTIONS.map((s) => ({ value: s.value, label: SCOPE_WORD[s.value] ?? s.value }))}
            placeholder="All scopes"
          />
        </>
      }
      emptyTitle="No thresholds"
      emptyDescription="No thresholds match these filters."
      form={form}
      remove={{
        path: (t) => `/api/v1/thresholds/${t.id}`,
        allowed: (t) => t.scope !== 'global' && (unrestricted || t.scope === 'site' || t.scope === 'server'),
        description: () => 'The next less specific threshold (or the global default) applies again.',
      }}
      persistKey="admin-thresholds"
    />
  );
}
