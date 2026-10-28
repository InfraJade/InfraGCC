import { send, useApiMutation, useCan, useCursorList } from '@/api/hooks';
import type { AlertRule, Metric } from '@/api/types';
import { Pill, SeverityBadge } from '@/components/Badges';
import { type Column } from '@/components/DataTable';
import { FormField, NumberInput, Select, TextArea, TextInput } from '@/components/FormField';
import { Age } from '@/components/Reading';
import { useUrlState } from '@/lib/useUrlState';

import {
  CrudList,
  FilterSelect,
  formatDuration,
  isInt,
  RowSwitch,
  type CrudForm,
  type FormApi,
  type FormErrors,
} from './crud';
import { metricOptions, useMetrics, useUnrestricted } from './pickers';

export interface RuleForm {
  name: string;
  description: string;
  rule_type: string;
  metric: string;
  severity: string;
  duration_s: string;
  route: string;
  enabled: string;
  /** JSON object text. */
  condition: string;
}

const RULE_TYPES = [
  { value: 'threshold', label: 'Threshold' },
  { value: 'state', label: 'State' },
  { value: 'missing_data', label: 'Missing data' },
  { value: 'event', label: 'Event' },
  { value: 'compliance', label: 'Compliance' },
];
const TYPE_WORD: Record<string, string> = Object.fromEntries(RULE_TYPES.map((t) => [t.value, t.label]));
/** Which metric types each rule type can watch (mirrors the API). */
const RULE_METRIC_TYPES: Record<string, string[]> = {
  threshold: ['gauge'],
  state: ['state'],
  event: ['event'],
  compliance: ['version'],
};
const SEVERITIES = [
  { value: 'Critical', label: 'Critical' },
  { value: 'Warning', label: 'Warning' },
  { value: 'Info', label: 'Info' },
];
const ENABLED_OPTIONS = [
  { value: 'true', label: 'Enabled' },
  { value: 'false', label: 'Disabled' },
];

/** Parse the condition text: a JSON object, or an error message. */
export function parseCondition(text: string): { value: Record<string, unknown> } | { error: string } {
  const t = text.trim();
  if (t === '') return { value: {} };
  let parsed: unknown;
  try {
    parsed = JSON.parse(t);
  } catch (err) {
    return { error: `Not valid JSON: ${err instanceof Error ? err.message : String(err)}` };
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed))
    return { error: 'The condition must be a JSON object, e.g. {"bmc_limits": "prefer"}.' };
  return { value: parsed as Record<string, unknown> };
}

function RuleFields({
  form,
  metrics,
  row,
}: {
  form: FormApi<RuleForm>;
  metrics: Metric[];
  row: AlertRule | null;
}) {
  const { values, set, patch, errors, mode } = form;
  const metricTypes = RULE_METRIC_TYPES[values.rule_type];
  return (
    <>
      {mode === 'create' ? (
        <FormField label="Name" required error={errors.name}>
          <TextInput value={values.name} maxLength={120} onChange={(e) => set('name', e.target.value)} />
        </FormField>
      ) : (
        <p className="text-sm text-text-muted">
          {TYPE_WORD[row?.rule_type ?? ''] ?? row?.rule_type} rule
          {row?.metric ? (
            <>
              {' '}
              on <span className="font-mono text-xs text-text">{row.metric}</span>
            </>
          ) : null}
          {row?.builtin ? ' · built-in (can be changed and disabled, not deleted)' : null}
        </p>
      )}
      <FormField label="Description" error={errors.description}>
        <TextArea
          value={values.description}
          rows={2}
          maxLength={4000}
          onChange={(e) => set('description', e.target.value)}
        />
      </FormField>
      {mode === 'create' ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Type" required error={errors.rule_type}>
            <Select
              value={values.rule_type}
              options={RULE_TYPES}
              onChange={(e) => patch({ rule_type: e.target.value, metric: '' })}
            />
          </FormField>
          {metricTypes ? (
            <FormField label="Metric" required error={errors.metric}>
              <Select
                value={values.metric}
                options={metricOptions(metrics, metricTypes)}
                placeholder="Choose a metric"
                onChange={(e) => set('metric', e.target.value)}
              />
            </FormField>
          ) : (
            <p className="self-end pb-2 text-xs text-text-subtle">Missing-data rules watch every metric.</p>
          )}
        </div>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-3">
        <FormField label="Severity" required error={errors.severity}>
          <Select
            value={values.severity}
            options={SEVERITIES}
            onChange={(e) => set('severity', e.target.value)}
          />
        </FormField>
        <FormField label="Duration" required error={errors.duration_s} hint="How long before it fires">
          <NumberInput
            unit="s"
            min={0}
            max={86400}
            step={1}
            value={values.duration_s}
            onChange={(e) => set('duration_s', e.target.value)}
          />
        </FormField>
        <FormField label="Route" required error={errors.route} hint="Routing key, e.g. hardware">
          <TextInput value={values.route} maxLength={32} onChange={(e) => set('route', e.target.value)} />
        </FormField>
      </div>
      <FormField label="State" error={errors.enabled}>
        <Select
          value={values.enabled}
          options={ENABLED_OPTIONS}
          onChange={(e) => set('enabled', e.target.value)}
        />
      </FormField>
      <FormField
        label="Condition (JSON)"
        error={errors.condition}
        hint='A JSON object with the rule options, e.g. {"bmc_limits": "prefer"}. Checked before saving.'
      >
        <TextArea
          value={values.condition}
          rows={6}
          spellCheck={false}
          className="font-mono text-xs"
          onChange={(e) => set('condition', e.target.value)}
        />
      </FormField>
    </>
  );
}

function validate(v: RuleForm, mode: 'create' | 'edit'): FormErrors {
  const e: FormErrors = {};
  if (mode === 'create') {
    if (!v.name.trim()) e.name = 'Enter a name.';
    if (RULE_METRIC_TYPES[v.rule_type] && !v.metric) e.metric = 'Choose a metric.';
  }
  if (!isInt(v.duration_s, 0, 86400)) e.duration_s = 'Enter whole seconds from 0 to 86,400.';
  if (!/^[a-z0-9_-]{1,32}$/.test(v.route.trim())) e.route = 'Lower-case letters, digits, - and _ (max 32).';
  const cond = parseCondition(v.condition);
  if ('error' in cond) e.condition = cond.error;
  return e;
}

export default function AlertRulesSection() {
  const can = useCan();
  const unrestricted = useUnrestricted();
  const canEdit = can('edit_alert_rules') && unrestricted;
  const { metrics } = useMetrics();
  const [f, setF] = useUrlState({ type: '', enabled: '' });
  const list = useCursorList<AlertRule>('/api/v1/alert-rules', { rule_type: f.type, enabled: f.enabled });
  const toggle = useApiMutation<{ id: number; enabled: boolean }, AlertRule>(
    (api, v) => api.json<AlertRule>(`/api/v1/alert-rules/${v.id}`, send('PUT', { enabled: v.enabled })),
    { invalidate: ['alert-rules'], success: (r) => `${r.name} ${r.enabled ? 'enabled' : 'disabled'}` },
  );

  const columns: Column<AlertRule>[] = [
    {
      id: 'name',
      header: 'Rule',
      cell: (r) => (
        <span className="flex flex-col gap-0.5">
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="font-medium">{r.name}</span>
            {r.builtin ? (
              <Pill icon="shield" className="text-text-muted bg-text/5 ring-1 ring-inset ring-text/15">
                Built-in
              </Pill>
            ) : null}
          </span>
          {r.description ? (
            <span className="line-clamp-1 text-xs text-text-subtle">{r.description}</span>
          ) : null}
        </span>
      ),
    },
    { id: 'type', header: 'Type', cell: (r) => TYPE_WORD[r.rule_type] ?? r.rule_type },
    {
      id: 'metric',
      header: 'Metric',
      cell: (r) =>
        r.metric ? (
          <span className="font-mono text-xs">{r.metric}</span>
        ) : (
          <span className="text-text-subtle">Any</span>
        ),
    },
    { id: 'severity', header: 'Severity', cell: (r) => <SeverityBadge severity={r.severity} /> },
    { id: 'duration', header: 'Duration', cell: (r) => formatDuration(r.duration_s) },
    { id: 'route', header: 'Route', cell: (r) => <span className="font-mono text-xs">{r.route}</span> },
    {
      id: 'enabled',
      header: 'Enabled',
      cell: (r) => (
        <RowSwitch
          checked={r.enabled}
          label={`Enabled: ${r.name}`}
          busy={toggle.isPending && toggle.variables?.id === r.id}
          onChange={canEdit ? (enabled) => toggle.mutate({ id: r.id, enabled }) : undefined}
        />
      ),
    },
    {
      id: 'updated',
      header: 'Updated',
      cell: (r) => (
        <span className="flex flex-col">
          <Age time={r.updated_at} className="text-xs" />
          <span className="text-xs text-text-subtle">{r.updated_by ?? 'system'}</span>
        </span>
      ),
    },
  ];

  const form: CrudForm<AlertRule, RuleForm, AlertRule> = {
    size: 'lg',
    empty: () => ({
      name: '',
      description: '',
      rule_type: 'threshold',
      metric: '',
      severity: 'Warning',
      duration_s: '0',
      route: 'hardware',
      enabled: 'true',
      condition: '{}',
    }),
    fromRow: (r) => ({
      name: r.name,
      description: r.description,
      rule_type: r.rule_type,
      metric: r.metric ?? '',
      severity: r.severity,
      duration_s: String(r.duration_s),
      route: r.route,
      enabled: String(r.enabled),
      condition: JSON.stringify(r.condition ?? {}, null, 2),
    }),
    validate: (v, mode) => validate(v, mode),
    create: (v) => {
      const cond = parseCondition(v.condition);
      return {
        method: 'POST',
        path: '/api/v1/alert-rules',
        body: {
          name: v.name.trim(),
          description: v.description.trim(),
          rule_type: v.rule_type,
          metric: RULE_METRIC_TYPES[v.rule_type] ? v.metric : null,
          condition: 'value' in cond ? cond.value : {},
          duration_s: Number(v.duration_s),
          severity: v.severity,
          route: v.route.trim(),
          enabled: v.enabled === 'true',
        },
      };
    },
    update: (v, r) => {
      const cond = parseCondition(v.condition);
      return {
        method: 'PUT',
        path: `/api/v1/alert-rules/${r.id}`,
        body: {
          description: v.description.trim(),
          severity: v.severity,
          duration_s: Number(v.duration_s),
          route: v.route.trim(),
          enabled: v.enabled === 'true',
          condition: 'value' in cond ? cond.value : {},
        },
      };
    },
    render: (form, row) => <RuleFields form={form} metrics={metrics} row={row} />,
  };

  return (
    <CrudList<AlertRule, RuleForm, AlertRule>
      title="Alert rules"
      noun="alert rule"
      caption="Alert rules"
      intro="What raises an alert. Built-in rules can be tuned or disabled; custom rules can also be deleted."
      columns={columns}
      table={list.tableProps}
      getRowId={(r) => r.id}
      rowName={(r) => r.name}
      invalidate={['alert-rules']}
      canEdit={canEdit}
      readOnlyReason={
        can('edit_alert_rules')
          ? 'Alert rules apply to every site, so only platform admins without a site limit can change them.'
          : 'Changing alert rules needs the Platform admin role.'
      }
      createLabel="Add custom rule"
      toolbar={
        <>
          <FilterSelect
            label="Type"
            value={f.type}
            onChange={(v) => setF({ type: v })}
            options={RULE_TYPES}
            placeholder="All types"
          />
          <FilterSelect
            label="Enabled"
            value={f.enabled}
            onChange={(v) => setF({ enabled: v })}
            options={[
              { value: 'true', label: 'Enabled only' },
              { value: 'false', label: 'Disabled only' },
            ]}
            placeholder="Enabled and disabled"
          />
        </>
      }
      emptyTitle="No alert rules"
      emptyDescription="No rules match these filters."
      form={form}
      remove={{
        path: (r) => `/api/v1/alert-rules/${r.id}`,
        allowed: (r) => !r.builtin,
        description: () =>
          'Rules that already raised alerts cannot be deleted (their history is kept); disable them instead.',
      }}
      persistKey="admin-alert-rules"
    />
  );
}
