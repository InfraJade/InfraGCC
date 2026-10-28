import { keepPreviousData } from '@tanstack/react-query';
import { useMemo } from 'react';

import { useApiQuery } from '@/api/hooks';
import type { EffectiveLimit, Readings, ThresholdPage } from '@/api/types';
import { GlassCard } from '@/components/GlassCard';
import { SensorChart, type SensorSeries, type Threshold } from '@/components/SensorChart';
import { cn } from '@/lib/cn';
import { useNow } from '@/lib/useNow';

export const RANGES = [
  { id: '6h', label: '6 h', ms: 6 * 3600_000 },
  { id: '24h', label: '24 h', ms: 24 * 3600_000 },
  { id: '7d', label: '7 d', ms: 7 * 24 * 3600_000 },
] as const;
export type RangeId = (typeof RANGES)[number]['id'];

export function rangeOf(id: string): (typeof RANGES)[number] {
  return RANGES.find((r) => r.id === id) ?? RANGES[1];
}

interface ChartDef {
  id: string;
  title: string;
  unit: string;
  metrics: { metric: string; label: string }[];
}

const CHARTS: ChartDef[] = [
  {
    id: 'air',
    title: 'Inlet and exhaust temperature',
    unit: '°C',
    metrics: [
      { metric: 'inlet_temp_c', label: 'Inlet' },
      { metric: 'exhaust_temp_c', label: 'Exhaust' },
    ],
  },
  { id: 'cpu', title: 'CPU temperature', unit: '°C', metrics: [{ metric: 'cpu_temp_c', label: 'CPU' }] },
  { id: 'power', title: 'Power draw', unit: 'W', metrics: [{ metric: 'power_w', label: 'Power' }] },
  { id: 'fans', title: 'Fan speed', unit: 'RPM', metrics: [{ metric: 'fan_rpm', label: 'Fan' }] },
];

const MINUTE = 60_000;

/** 24-hour (6 h / 7 d) history charts. Mounted only while the Charts tab is open, so nothing loads before. */
export function ChartsTab({
  serverId,
  range,
  onRangeChange,
}: {
  serverId: number;
  range: string;
  onRangeChange: (id: RangeId) => void;
}) {
  const r = rangeOf(range);
  // The window slides once a minute (stable query keys in between).
  const now = useNow(MINUTE);
  const to = Math.floor(now / MINUTE) * MINUTE;
  const span = useMemo(
    () => ({ from: new Date(to - r.ms).toISOString(), to: new Date(to).toISOString() }),
    [to, r.ms],
  );
  const limits = useApiQuery<ThresholdPage>(
    '/api/v1/thresholds',
    { server_id: serverId },
    { staleTime: 5 * MINUTE },
  );
  const effective = limits.data?.effective ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-text-muted">
          History of the last {r.label}; dashed lines are the warning and critical limits that apply to this
          server.
        </p>
        <div role="group" aria-label="Time range" className="glass-subtle inline-flex gap-1 rounded-lg p-1">
          {RANGES.map((opt) => (
            <button
              key={opt.id}
              type="button"
              aria-pressed={opt.id === r.id}
              onClick={() => onRangeChange(opt.id)}
              className={cn(
                'rounded-md px-3 py-1 text-sm font-medium transition-colors duration-fast',
                opt.id === r.id ? 'bg-text/10 text-text shadow-sm' : 'text-text-muted hover:text-text',
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        {CHARTS.map((c) => (
          <MetricChart key={c.id} def={c} serverId={serverId} span={span} effective={effective} />
        ))}
      </div>
    </div>
  );
}

function MetricChart({
  def,
  serverId,
  span,
  effective,
}: {
  def: ChartDef;
  serverId: number;
  span: { from: string; to: string };
  effective: readonly EffectiveLimit[];
}) {
  const path = `/api/v1/servers/${serverId}/readings`;
  // The sliding window changes the key every minute, which refetches; keep the old lines meanwhile.
  const opts = { placeholderData: keepPreviousData };
  // At most two metrics per chart: two fixed hook calls (the second disabled when unused).
  const first = def.metrics[0];
  const second = def.metrics[1];
  const q1 = useApiQuery<Readings>(first ? path : null, { metric: first?.metric, ...span }, opts);
  const q2 = useApiQuery<Readings>(second ? path : null, { metric: second?.metric, ...span }, opts);
  const queries = second ? [q1, q2] : [q1];

  const series: SensorSeries[] = useMemo(() => {
    const out: SensorSeries[] = [];
    const results = [q1.data, second ? q2.data : undefined];
    def.metrics.forEach((m, i) => {
      const data = results[i];
      if (!data) return;
      for (const s of data.series) {
        const multi = def.metrics.length > 1;
        const name = s.component
          ? multi
            ? `${m.label} ${s.component}`
            : s.component
          : multi
            ? m.label
            : data.metric_name;
        out.push({
          id: `${m.metric}|${s.component}`,
          name,
          points: s.points.map((p) => [p.t, p.v] as const),
        });
      }
    });
    return out;
  }, [def.metrics, q1.data, q2.data, second]);

  const thresholds = useMemo(
    () =>
      thresholdsFor(
        def.metrics.map((m) => m.metric),
        effective,
        def.metrics.length > 1 ? def.metrics : null,
      ),
    [def.metrics, effective],
  );

  const loading = queries.some((q) => q.isPending);
  const error = queries.find((q) => q.error && !q.data)?.error;

  return (
    <GlassCard as="section" aria-label={def.title}>
      <SensorChart
        title={def.title}
        unit={def.unit}
        series={series}
        thresholds={thresholds}
        loading={loading}
        error={error ?? undefined}
        height={240}
      />
    </GlassCard>
  );
}

/**
 * Warning/critical lines for the given metrics from the effective limits (server > site > model > global >
 * BMC). Components of one metric usually share a limit; when they differ the tightest one is drawn.
 */
export function thresholdsFor(
  metrics: readonly string[],
  effective: readonly EffectiveLimit[],
  labels: readonly { metric: string; label: string }[] | null,
): Threshold[] {
  const out: Threshold[] = [];
  for (const metric of metrics) {
    const rows = effective.filter((e) => e.metric === metric);
    const prefix = labels?.find((l) => l.metric === metric)?.label;
    const add = (
      values: (number | null | undefined)[],
      severity: Threshold['severity'],
      pick: 'min' | 'max',
      lower: boolean,
    ) => {
      const nums = values.filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
      if (!nums.length) return;
      const value = pick === 'min' ? Math.min(...nums) : Math.max(...nums);
      const word = severity === 'critical' ? 'Critical' : 'Warning';
      const label = [prefix, lower ? `low ${word.toLowerCase()}` : word.toLowerCase()]
        .filter(Boolean)
        .join(' ');
      if (!out.some((t) => t.value === value && t.severity === severity))
        out.push({ value, severity, label: label.charAt(0).toUpperCase() + label.slice(1) });
    };
    const above = rows.filter((e) => e.direction === 'above');
    add(
      above.map((e) => e.warning),
      'warning',
      'min',
      false,
    );
    add(
      above.map((e) => e.critical),
      'critical',
      'min',
      false,
    );
    const below = rows.filter((e) => e.direction === 'below');
    add(
      below.map((e) => e.warning),
      'warning',
      'max',
      true,
    );
    add(
      below.map((e) => e.critical),
      'critical',
      'max',
      true,
    );
    add(
      rows.map((e) => e.lower_warning),
      'warning',
      'max',
      true,
    );
    add(
      rows.map((e) => e.lower_critical),
      'critical',
      'max',
      true,
    );
  }
  return out;
}
