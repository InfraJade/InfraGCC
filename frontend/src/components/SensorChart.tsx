import { AnimatePresence, motion } from 'framer-motion';
import { useMemo } from 'react';

import { errorMessage } from '@/api/errors';
import { cn } from '@/lib/cn';
import type { EChartsOption } from '@/lib/echarts';
import { formatTimestamp, formatValue, toMillis, type TimeInput } from '@/lib/format';
import { useResolvedTheme, useTheme } from '@/theme/ThemeProvider';
import {
  chartPalette,
  health as healthTokens,
  motion as motionTokens,
  themes,
  type ThemeName,
} from '@/theme/tokens';

import { EChart } from './EChart';
import { EmptyState } from './EmptyState';
import { Age } from './Reading';
import { Skeleton } from './Skeleton';

export type SensorPoint = readonly [TimeInput, number | null];

export interface SensorSeries {
  /** Stable id: ECharts matches series by id, so updates animate instead of redrawing. */
  id: string;
  name: string;
  points: readonly SensorPoint[];
  /** Override the categorical color (default: palette slot by series order — keep order stable). */
  color?: string;
}

export interface Threshold {
  value: number;
  severity: 'warning' | 'critical';
  label?: string;
}

export interface SensorChartProps {
  series: readonly SensorSeries[];
  /** Unit for the axis, tooltip and latest values, e.g. "°C", "RPM", "W". */
  unit: string;
  thresholds?: readonly Threshold[];
  title?: string;
  height?: number;
  precision?: number;
  yMin?: number;
  yMax?: number;
  loading?: boolean;
  error?: unknown;
  /** Show latest value + age per series under the chart (default true). */
  showLatest?: boolean;
  className?: string;
}

function latestPoint(points: readonly SensorPoint[]): { value: number | null; time: TimeInput } | null {
  for (let i = points.length - 1; i >= 0; i--) {
    const p = points[i];
    if (p && p[1] !== null) return { value: p[1], time: p[0] };
  }
  return null;
}

export function buildSensorOption(args: {
  series: readonly SensorSeries[];
  unit: string;
  thresholds: readonly Threshold[];
  theme: ThemeName;
  reducedMotion: boolean;
  precision: number | undefined;
  yMin: number | undefined;
  yMax: number | undefined;
}): EChartsOption {
  const { series, unit, thresholds, theme, reducedMotion, precision, yMin, yMax } = args;
  const t = themes[theme];
  const palette = chartPalette[theme];
  const rgb = (hex: string, a: number) => {
    const n = Number.parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  };
  const thresholdMax = thresholds.length ? Math.max(...thresholds.map((th) => th.value)) : undefined;

  return {
    animation: !reducedMotion,
    animationDuration: motionTokens.duration.chart,
    animationDurationUpdate: motionTokens.duration.chart,
    animationEasingUpdate: 'cubicOut',
    aria: { enabled: true },
    textStyle: { fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif', color: t.textMuted },
    grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: t.chartAxis, width: 1, type: 'dashed' } },
      backgroundColor: t.surfaceRaised,
      borderColor: rgb(t.border, 0.12),
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { color: t.text, fontSize: 12 },
      extraCssText: 'border-radius:10px;box-shadow:0 8px 24px -8px rgba(0,0,0,.4);',
      valueFormatter: (v: unknown) => formatValue(typeof v === 'number' ? v : null, unit, precision),
    },
    // The latest-value chips under the chart are the legend (name + color + value + age).
    legend: { show: false },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: t.chartGrid } },
      axisTick: { show: false },
      axisLabel: { color: t.chartAxis, hideOverlap: true, fontSize: 11 },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      scale: yMin === undefined,
      min: yMin,
      max:
        yMax ??
        (thresholdMax !== undefined
          ? (v: { max: number }) => Math.ceil(Math.max(v.max, thresholdMax) * 1.04)
          : undefined),
      axisLabel: {
        color: t.chartAxis,
        fontSize: 11,
        formatter: (v: number) => formatValue(v, unit, precision ?? (Math.abs(v) >= 100 ? 0 : undefined)),
      },
      splitLine: { lineStyle: { color: t.chartGrid, opacity: 0.6 } },
    },
    series: series.map((s, i) => {
      const color = s.color ?? palette[i % palette.length] ?? t.accent;
      return {
        id: s.id,
        name: s.name,
        type: 'line',
        showSymbol: false,
        symbolSize: 8,
        connectNulls: false,
        lineStyle: { width: 2, color },
        itemStyle: { color, borderColor: t.surface, borderWidth: 2 },
        emphasis: { focus: 'series' },
        data: s.points.map(([time, value]) => [toMillis(time), value]),
        ...(i === 0 && thresholds.length
          ? {
              markLine: {
                silent: true,
                symbol: 'none',
                animation: false,
                data: thresholds.map((th) => {
                  const c =
                    th.severity === 'critical' ? healthTokens.Critical[theme] : healthTokens.Warning[theme];
                  const label = th.label ?? (th.severity === 'critical' ? 'Critical' : 'Warning');
                  return {
                    yAxis: th.value,
                    name: label,
                    lineStyle: { color: c, type: 'dashed', width: 1 },
                    label: {
                      formatter: `${label} ${formatValue(th.value, unit, precision)}`,
                      position: 'insideEndTop',
                      color: c,
                      fontSize: 11,
                    },
                  };
                }),
              },
            }
          : {}),
      };
    }),
  };
}

const NO_THRESHOLDS: readonly Threshold[] = [];

/**
 * Time-series sensor chart: multiple series, unit-aware axis, threshold lines, theme from tokens.
 * Updates in place (ECharts animates the data change); the latest-value chips cross-fade.
 */
export function SensorChart({
  series,
  unit,
  thresholds = NO_THRESHOLDS,
  title,
  height = 240,
  precision,
  yMin,
  yMax,
  loading,
  error,
  showLatest = true,
  className,
}: SensorChartProps) {
  const theme = useResolvedTheme();
  const { reducedMotion } = useTheme();
  const option = useMemo(
    () => buildSensorOption({ series, unit, thresholds, theme, reducedMotion, precision, yMin, yMax }),
    [series, unit, thresholds, theme, reducedMotion, precision, yMin, yMax],
  );
  const hasData = series.some((s) => s.points.length > 0);
  const palette = chartPalette[theme];
  const label = `${title ?? 'Sensor chart'} in ${unit}: ${series.map((s) => s.name).join(', ') || 'no series'}`;

  return (
    <figure className={cn('m-0 flex flex-col gap-2', className)}>
      {title ? <figcaption className="text-sm font-semibold text-text">{title}</figcaption> : null}
      <div className="relative" style={{ height }}>
        {loading ? (
          <Skeleton className="h-full w-full rounded-lg" label={`Loading ${title ?? 'chart'}`} />
        ) : error ? (
          <EmptyState tone="error" title="Couldn't load readings" description={errorMessage(error)} />
        ) : !hasData ? (
          <EmptyState icon="activity" title="No readings in this range" />
        ) : null}
        <EChart
          option={option}
          ariaLabel={label}
          className={cn('absolute inset-0', (loading || error || !hasData) && 'invisible')}
        />
      </div>
      {showLatest && hasData ? (
        <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs" aria-label="Latest values">
          {series.map((s, i) => {
            const last = latestPoint(s.points);
            const color = s.color ?? palette[i % palette.length];
            return (
              <li key={s.id} className="flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className="h-0.5 w-3 rounded-full"
                  style={{ backgroundColor: color }}
                />
                <span className="text-text-muted">{s.name}</span>
                <AnimatePresence mode="popLayout" initial={false}>
                  <motion.span
                    key={last ? `${last.value}-${toMillis(last.time)}` : 'none'}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: motionTokens.duration.base / 1000 }}
                    className="tabular font-medium text-text"
                    title={last ? formatTimestamp(last.time) : undefined}
                  >
                    {formatValue(last?.value ?? null, unit, precision)}
                  </motion.span>
                </AnimatePresence>
                {last ? <Age time={last.time} /> : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </figure>
  );
}
