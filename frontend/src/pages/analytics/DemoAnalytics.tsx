/**
 * Analytics in demo mode: the same six dashboards as the Superset embed (same tabs and slugs), drawn in-app
 * from the demo data because Superset can only read the real database. Every chart has a legend or a title
 * naming its single series, a hover tooltip, and a table with the numbers next to it.
 */
import { useMemo, type ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { DataTable, type Column } from '@/components/DataTable';
import { EChart } from '@/components/EChart';
import { GlassCard } from '@/components/GlassCard';
import { Pill, SeverityBadge } from '@/components/Badges';
import { HealthBadge } from '@/components/HealthBadge';
import { StatTile } from '@/components/StatTile';
import {
  alertsPerDay,
  alertStats,
  fleetByModel,
  fleetTotals,
  healthBySite,
  hottestServers,
  inletBySite,
  partsByKind,
  powerBySite,
  rackUtilization,
  unhealthyParts,
  type SiteSeries,
} from '@/demo/analytics';
import type { EChartsOption } from '@/lib/echarts';
import { formatTimestamp } from '@/lib/format';
import { useNow } from '@/lib/useNow';
import { useResolvedTheme, useTheme } from '@/theme/ThemeProvider';
import { chartPalette, health as healthTokens, motion, themes, type ThemeName } from '@/theme/tokens';

// ---------------------------------------------------------------------------------------------- chart options

function rgba(hex: string, a: number) {
  const n = Number.parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

function base(theme: ThemeName, reducedMotion: boolean, unit: string): EChartsOption {
  const t = themes[theme];
  return {
    animation: !reducedMotion,
    animationDuration: motion.duration.chart,
    aria: { enabled: true },
    textStyle: { fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif', color: t.textMuted },
    grid: { left: 8, right: 20, top: 36, bottom: 8, containLabel: true },
    tooltip: {
      backgroundColor: t.surfaceRaised,
      borderColor: rgba(t.border, 0.12),
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { color: t.text, fontSize: 12 },
      extraCssText: 'border-radius:10px;box-shadow:0 8px 24px -8px rgba(0,0,0,.4);',
      valueFormatter: (v: unknown) =>
        typeof v === 'number' ? `${v.toLocaleString('en-IN')}${unit ? ` ${unit}` : ''}` : '—',
    },
    legend: {
      top: 0,
      left: 0,
      icon: 'roundRect',
      itemWidth: 12,
      itemHeight: 4,
      textStyle: { color: t.textMuted, fontSize: 12 },
    },
  };
}

const axisLabel = (theme: ThemeName) => ({ color: themes[theme].chartAxis, fontSize: 11, hideOverlap: true });

function lineOption(
  series: SiteSeries[],
  unit: string,
  theme: ThemeName,
  reducedMotion: boolean,
  limit?: { value: number; label: string },
): EChartsOption {
  const t = themes[theme];
  const palette = chartPalette[theme];
  return {
    ...base(theme, reducedMotion, unit),
    tooltip: {
      ...(base(theme, reducedMotion, unit).tooltip as object),
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: t.chartAxis, width: 1, type: 'dashed' } },
    },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: t.chartGrid } },
      axisTick: { show: false },
      axisLabel: axisLabel(theme),
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { ...axisLabel(theme), formatter: (v: number) => `${v} ${unit}` },
      splitLine: { lineStyle: { color: t.chartGrid, opacity: 0.6 } },
    },
    series: series.map((s, i) => ({
      id: s.code,
      name: `${s.code} · ${s.name}`,
      type: 'line',
      showSymbol: false,
      symbolSize: 8,
      lineStyle: { width: 2, color: palette[i] },
      itemStyle: { color: palette[i], borderColor: t.surface, borderWidth: 2 },
      emphasis: { focus: 'series' },
      data: s.points.map((p) => [p.t, p.v]),
      ...(i === 0 && limit
        ? {
            markLine: {
              silent: true,
              symbol: 'none',
              lineStyle: { color: healthTokens.Warning[theme], type: 'dashed', width: 1 },
              label: { formatter: limit.label, color: t.textMuted, fontSize: 11, position: 'insideEndTop' },
              data: [{ yAxis: limit.value }],
            },
          }
        : {}),
    })),
  };
}

/** Horizontal bars, one series, value labels at the bar end. */
function hbarOption(
  rows: { label: string; value: number }[],
  unit: string,
  theme: ThemeName,
  reducedMotion: boolean,
  color?: (value: number) => string,
): EChartsOption {
  const t = themes[theme];
  const palette = chartPalette[theme];
  const ordered = [...rows].reverse();
  return {
    ...base(theme, reducedMotion, unit),
    legend: { show: false },
    grid: { left: 8, right: 56, top: 8, bottom: 8, containLabel: true },
    tooltip: { ...(base(theme, reducedMotion, unit).tooltip as object), trigger: 'item' },
    xAxis: {
      type: 'value',
      axisLabel: { ...axisLabel(theme), formatter: (v: number) => `${v}${unit === '%' ? '%' : ''}` },
      splitLine: { lineStyle: { color: t.chartGrid, opacity: 0.6 } },
    },
    yAxis: {
      type: 'category',
      data: ordered.map((r) => r.label),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: t.chartGrid } },
      axisLabel: { color: t.textMuted, fontSize: 11 },
    },
    series: [
      {
        type: 'bar',
        barMaxWidth: 16,
        data: ordered.map((r) => ({
          value: r.value,
          itemStyle: { color: color?.(r.value) ?? palette[0], borderRadius: [0, 4, 4, 0] },
        })),
        label: {
          show: true,
          position: 'right',
          color: t.text,
          fontSize: 11,
          formatter: (p: { value: number }) => `${p.value.toLocaleString('en-IN')}${unit ? ` ${unit}` : ''}`,
        },
      },
    ],
  };
}

/** Stacked vertical bars by status (health or severity colors). */
function stackedOption(
  categories: string[],
  stacks: { name: string; color: string; data: number[] }[],
  theme: ThemeName,
  reducedMotion: boolean,
  timeAxis = false,
): EChartsOption {
  const t = themes[theme];
  return {
    ...base(theme, reducedMotion, ''),
    tooltip: {
      ...(base(theme, reducedMotion, '').tooltip as object),
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: rgba(t.text, 0.05) } },
    },
    xAxis: {
      type: 'category',
      data: categories,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: t.chartGrid } },
      axisLabel: { ...axisLabel(theme), interval: timeAxis ? 'auto' : 0 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: axisLabel(theme),
      splitLine: { lineStyle: { color: t.chartGrid, opacity: 0.6 } },
    },
    series: stacks.map((s, i) => ({
      name: s.name,
      type: 'bar',
      stack: 'total',
      barMaxWidth: timeAxis ? 14 : 40,
      itemStyle: {
        color: s.color,
        borderColor: t.surface,
        borderWidth: 1,
        borderRadius: i === stacks.length - 1 ? [4, 4, 0, 0] : 0,
      },
      emphasis: { focus: 'series' },
      data: s.data,
    })),
  };
}

// ---------------------------------------------------------------------------------------------- layout parts

function ChartCard({
  title,
  subtitle,
  children,
  height = 280,
}: {
  title: string;
  subtitle?: string;
  children: (h: number) => ReactNode;
  height?: number;
}) {
  return (
    <GlassCard
      as="section"
      title={title}
      actions={subtitle ? <span className="text-xs text-text-subtle">{subtitle}</span> : undefined}
    >
      {children(height)}
    </GlassCard>
  );
}

function Tiles({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">{children}</div>;
}

const ServerLink = ({ id, name }: { id: number; name: string }) => (
  <Link to={`/servers/${id}`} className="font-medium text-text hover:text-accent hover:underline">
    {name}
  </Link>
);

function useChartEnv() {
  const theme = useResolvedTheme();
  const { reducedMotion } = useTheme();
  // Aggregates are computed for the current minute, so they refresh once a minute like a dashboard.
  const now = Math.floor(useNow(60_000) / 60_000) * 60_000;
  return { theme, reducedMotion, now };
}

// ---------------------------------------------------------------------------------------------- dashboards

function OverviewDashboard() {
  const { theme, reducedMotion, now } = useChartEnv();
  const data = useMemo(
    () => ({
      totals: fleetTotals(now),
      health: healthBySite(),
      power: powerBySite(undefined, undefined, now),
      stats: alertStats(now),
    }),
    [now],
  );
  const healthStacks = (['OK', 'Warning', 'Critical', 'Unknown'] as const).map((h) => ({
    name: h,
    color: healthTokens[h][theme],
    data: data.health.map((s) => s.counts[h]),
  }));
  return (
    <div className="flex flex-col gap-6">
      <Tiles>
        <StatTile
          time={now}
          label="Servers monitored"
          value={data.totals.servers}
          icon="server"
          footnote={`${data.totals.sites} sites · ${data.totals.racks} racks`}
        />
        <StatTile
          time={now}
          label="Healthy"
          value={data.totals.healthyPct}
          unit="%"
          icon="circle-check"
          footnote="servers with every part OK"
        />
        <StatTile
          time={now}
          label="Open alerts"
          value={data.stats.open + data.stats.acknowledged}
          icon="bell"
          footnote={`${data.stats.acknowledged} acknowledged`}
        />
        <StatTile
          time={now}
          label="Power draw"
          value={data.totals.powerKw}
          unit="kW"
          icon="zap"
          footnote={`of ${data.totals.capacityKw} kW rack capacity`}
        />
      </Tiles>
      <div className="grid gap-6 xl:grid-cols-2">
        <ChartCard title="Server health by site" subtitle="now">
          {(h) => (
            <EChart
              style={{ height: h }}
              ariaLabel="Stacked bars: servers by health per site"
              option={stackedOption(
                data.health.map((s) => s.code),
                healthStacks,
                theme,
                reducedMotion,
              )}
            />
          )}
        </ChartCard>
        <ChartCard title="Power draw by site" subtitle="last 24 h, kW">
          {(h) => (
            <EChart
              style={{ height: h }}
              ariaLabel="Lines: power draw per site over 24 hours"
              option={lineOption(data.power, 'kW', theme, reducedMotion)}
            />
          )}
        </ChartCard>
      </div>
      <DataTable
        caption="Health by site"
        getRowId={(r) => r.code}
        rows={data.health}
        columns={[
          {
            id: 'site',
            header: 'Site',
            cell: (r) => <span className="font-medium">{`${r.code} · ${r.name}`}</span>,
          },
          { id: 'total', header: 'Servers', align: 'right', cell: (r) => r.total },
          { id: 'ok', header: 'OK', align: 'right', cell: (r) => r.counts.OK },
          { id: 'warning', header: 'Warning', align: 'right', cell: (r) => r.counts.Warning },
          { id: 'critical', header: 'Critical', align: 'right', cell: (r) => r.counts.Critical },
        ]}
      />
    </div>
  );
}

function ThermalDashboard() {
  const { theme, reducedMotion, now } = useChartEnv();
  const data = useMemo(
    () => ({ inlet: inletBySite(undefined, undefined, now), hot: hottestServers(10, now) }),
    [now],
  );
  const limit = 27;
  const columns: Column<(typeof data.hot)[number]>[] = [
    { id: 'name', header: 'Server', cell: (r) => <ServerLink id={r.id} name={r.name} /> },
    { id: 'site', header: 'Site', cell: (r) => r.site },
    { id: 'rack', header: 'Rack', cell: (r) => r.rack },
    { id: 'model', header: 'Model', cell: (r) => r.model },
    {
      id: 'inlet',
      header: 'Inlet',
      align: 'right',
      cell: (r) => <span className="tabular">{r.value.toFixed(1)} °C</span>,
    },
    {
      id: 'state',
      header: 'State',
      cell: (r) => <HealthBadge health={r.value >= 35 ? 'Critical' : r.value >= limit ? 'Warning' : 'OK'} />,
    },
  ];
  const over = data.hot.filter((r) => r.value >= limit).length;
  return (
    <div className="flex flex-col gap-6">
      <Tiles>
        {data.inlet.map((s) => (
          <StatTile
            time={now}
            key={s.code}
            label={`${s.code} inlet (avg)`}
            value={s.points.at(-1)?.v ?? null}
            unit="°C"
            icon="thermometer"
            footnote={s.name}
          />
        ))}
        <StatTile
          time={now}
          label="Servers over 27 °C"
          value={over}
          icon="triangle-alert"
          health={over ? 'Warning' : 'OK'}
          footnote="inlet warning limit"
        />
      </Tiles>
      <div className="grid gap-6 xl:grid-cols-2">
        <ChartCard title="Average inlet temperature by site" subtitle="last 24 h">
          {(h) => (
            <EChart
              style={{ height: h }}
              ariaLabel="Lines: average inlet temperature per site over 24 hours"
              option={lineOption(data.inlet, '°C', theme, reducedMotion, {
                value: limit,
                label: 'Warning 27 °C',
              })}
            />
          )}
        </ChartCard>
        <ChartCard title="Hottest servers (inlet)" subtitle="now, °C">
          {(h) => (
            <EChart
              style={{ height: h }}
              ariaLabel="Bars: ten hottest servers by inlet temperature"
              option={hbarOption(
                data.hot.map((r) => ({ label: r.name.replace('.demo.local', ''), value: r.value })),
                '°C',
                theme,
                reducedMotion,
                (v) => (v >= limit ? healthTokens.Warning[theme] : chartPalette[theme][0]!),
              )}
            />
          )}
        </ChartCard>
      </div>
      <DataTable caption="Hottest servers" getRowId={(r) => r.id} rows={data.hot} columns={columns} />
    </div>
  );
}

function PowerDashboard() {
  const { theme, reducedMotion, now } = useChartEnv();
  const data = useMemo(
    () => ({
      totals: fleetTotals(now),
      racks: rackUtilization(now),
      week: powerBySite(7 * 86_400_000, 3_600_000, now),
    }),
    [now],
  );
  const top = data.racks.slice(0, 10);
  const columns: Column<(typeof data.racks)[number]>[] = [
    {
      id: 'rack',
      header: 'Rack',
      cell: (r) => (
        <Link to={`/racks/${r.id}`} className="font-medium hover:text-accent hover:underline">
          {r.rack}
        </Link>
      ),
    },
    { id: 'site', header: 'Site', cell: (r) => r.site },
    { id: 'servers', header: 'Servers', align: 'right', cell: (r) => r.servers },
    {
      id: 'power',
      header: 'Power',
      align: 'right',
      cell: (r) => <span className="tabular">{r.powerKw} kW</span>,
    },
    {
      id: 'cap',
      header: 'Capacity',
      align: 'right',
      cell: (r) => <span className="tabular">{r.capacityKw} kW</span>,
    },
    { id: 'pct', header: 'Used', align: 'right', cell: (r) => <span className="tabular">{r.pct} %</span> },
  ];
  return (
    <div className="flex flex-col gap-6">
      <Tiles>
        <StatTile time={now} label="Power draw" value={data.totals.powerKw} unit="kW" icon="zap" />
        <StatTile time={now} label="Rack capacity" value={data.totals.capacityKw} unit="kW" icon="rack" />
        <StatTile
          time={now}
          label="Capacity used"
          value={Math.round((data.totals.powerKw / Math.max(1, data.totals.capacityKw)) * 1000) / 10}
          unit="%"
          icon="activity"
        />
        <StatTile
          time={now}
          label="Busiest rack"
          value={top[0]?.pct ?? null}
          unit="%"
          icon="building"
          footnote={top[0] ? `${top[0].rack} · ${top[0].site}` : undefined}
        />
      </Tiles>
      <div className="grid gap-6 xl:grid-cols-2">
        <ChartCard title="Power draw by site" subtitle="last 7 days, hourly, kW">
          {(h) => (
            <EChart
              style={{ height: h }}
              ariaLabel="Lines: power draw per site over 7 days"
              option={lineOption(data.week, 'kW', theme, reducedMotion)}
            />
          )}
        </ChartCard>
        <ChartCard title="Rack power, % of capacity" subtitle="top 10 racks, now">
          {(h) => (
            <EChart
              style={{ height: h }}
              ariaLabel="Bars: rack power draw as percent of capacity"
              option={hbarOption(
                top.map((r) => ({ label: `${r.rack} · ${r.site}`, value: r.pct })),
                '%',
                theme,
                reducedMotion,
                (v) => (v >= 90 ? healthTokens.Warning[theme] : chartPalette[theme][0]!),
              )}
            />
          )}
        </ChartCard>
      </div>
      <DataTable
        caption="Rack power"
        getRowId={(r) => r.id}
        rows={data.racks}
        columns={columns}
        maxHeight="24rem"
      />
    </div>
  );
}

function HardwareDashboard() {
  const { theme, reducedMotion, now } = useChartEnv();
  const data = useMemo(() => {
    const parts = unhealthyParts(now);
    return { parts, kinds: partsByKind(parts), health: healthBySite() };
  }, [now]);
  const critical = data.parts.filter((p) => p.health === 'Critical').length;
  const columns: Column<(typeof data.parts)[number]>[] = [
    { id: 'server', header: 'Server', cell: (r) => <ServerLink id={r.serverId} name={r.server} /> },
    { id: 'site', header: 'Site', cell: (r) => r.site },
    { id: 'kind', header: 'Kind', cell: (r) => r.metric },
    { id: 'part', header: 'Part', cell: (r) => r.part },
    { id: 'health', header: 'Health', cell: (r) => <HealthBadge health={r.health} /> },
    { id: 'state', header: 'State', cell: (r) => r.state },
    {
      id: 'since',
      header: 'Since',
      cell: (r) => <span className="tabular whitespace-nowrap">{formatTimestamp(r.since)}</span>,
    },
  ];
  return (
    <div className="flex flex-col gap-6">
      <Tiles>
        <StatTile time={now} label="Unhealthy parts" value={data.parts.length} icon="chip" />
        <StatTile
          time={now}
          label="Critical parts"
          value={critical}
          icon="octagon-x"
          health={critical ? 'Critical' : 'OK'}
        />
        <StatTile
          time={now}
          label="Servers affected"
          value={new Set(data.parts.map((p) => p.serverId)).size}
          icon="server"
        />
        <StatTile
          time={now}
          label="Healthy servers"
          value={data.health.reduce((n, s) => n + s.counts.OK, 0)}
          icon="circle-check"
          footnote={`of ${data.health.reduce((n, s) => n + s.total, 0)}`}
        />
      </Tiles>
      <ChartCard title="Unhealthy parts by kind" subtitle="now" height={260}>
        {(h) => (
          <EChart
            style={{ height: h }}
            ariaLabel="Bars: unhealthy parts by kind"
            option={hbarOption(
              data.kinds.map((k) => ({ label: k.kind, value: k.count })),
              '',
              theme,
              reducedMotion,
            )}
          />
        )}
      </ChartCard>
      <DataTable caption="Unhealthy parts" getRowId={(r) => r.key} rows={data.parts} columns={columns} />
    </div>
  );
}

function AlertsDashboard() {
  const { theme, reducedMotion, now } = useChartEnv();
  const data = useMemo(() => ({ days: alertsPerDay(30, now), stats: alertStats(now) }), [now]);
  const labels = data.days.map((d) =>
    new Date(d.day).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }),
  );
  const stacks = [
    { name: 'Warning', color: healthTokens.Warning[theme], data: data.days.map((d) => d.warning) },
    { name: 'Critical', color: healthTokens.Critical[theme], data: data.days.map((d) => d.critical) },
  ];
  const fmtMin = (m: number | null) => (m === null ? null : Math.round(m));
  return (
    <div className="flex flex-col gap-6">
      <Tiles>
        <StatTile
          time={now}
          label="Open now"
          value={data.stats.open}
          icon="bell"
          footnote={`${data.stats.acknowledged} more acknowledged`}
        />
        <StatTile time={now} label="Resolved (30 days)" value={data.stats.resolved30d} icon="circle-check" />
        <StatTile
          time={now}
          label="Median time to acknowledge"
          value={fmtMin(data.stats.medianAckMin)}
          unit="min"
          icon="clock"
        />
        <StatTile
          time={now}
          label="Median time to resolve"
          value={fmtMin(data.stats.medianResolveMin)}
          unit="min"
          icon="clock"
        />
      </Tiles>
      <ChartCard title="Alerts opened per day" subtitle="last 30 days">
        {(h) => (
          <EChart
            style={{ height: h }}
            ariaLabel="Stacked bars: alerts opened per day by severity"
            option={stackedOption(labels, stacks, theme, reducedMotion, true)}
          />
        )}
      </ChartCard>
      <DataTable
        caption="Noisiest rules"
        getRowId={(r) => r.rule}
        rows={data.stats.topRules}
        columns={[
          {
            id: 'rule',
            header: 'Rule (last 30 days)',
            cell: (r) => <span className="font-medium">{r.rule}</span>,
          },
          { id: 'count', header: 'Alerts', align: 'right', cell: (r) => r.count },
          { id: 'critical', header: 'Critical', align: 'right', cell: (r) => r.critical },
          {
            id: 'severity',
            header: 'Worst',
            cell: (r) => <SeverityBadge severity={r.critical ? 'Critical' : 'Warning'} />,
          },
        ]}
      />
    </div>
  );
}

function FirmwareDashboard() {
  const { theme, reducedMotion, now } = useChartEnv();
  const rows = useMemo(() => fleetByModel(now), [now]);
  const checked = rows.filter((r) => !r.noBaseline);
  const compliant = checked.reduce((n, r) => n + r.compliant, 0);
  const total = checked.reduce((n, r) => n + r.servers, 0);
  const stacks = [
    { name: 'On baseline', color: healthTokens.OK[theme], data: rows.map((r) => r.compliant) },
    { name: 'Off baseline', color: healthTokens.Warning[theme], data: rows.map((r) => r.offBaseline) },
    {
      name: 'No baseline',
      color: healthTokens.Unknown[theme],
      data: rows.map((r) => (r.noBaseline ? r.servers : 0)),
    },
  ];
  return (
    <div className="flex flex-col gap-6">
      <Tiles>
        <StatTile time={now} label="Server models" value={rows.length} icon="layers" />
        <StatTile
          time={now}
          label="On baseline"
          value={total ? Math.round((compliant / total) * 1000) / 10 : null}
          unit="%"
          icon="shield"
          footnote={`${compliant} of ${total} checked servers`}
        />
        <StatTile
          time={now}
          label="Off baseline"
          value={checked.reduce((n, r) => n + r.offBaseline, 0)}
          icon="triangle-alert"
          to="/firmware"
        />
        <StatTile
          time={now}
          label="Models without baseline"
          value={rows.filter((r) => r.noBaseline).length}
          icon="circle-help"
          to="/admin/baselines"
        />
      </Tiles>
      <ChartCard title="Firmware compliance by model" subtitle="servers">
        {(h) => (
          <EChart
            style={{ height: h }}
            ariaLabel="Stacked bars: servers on, off and without firmware baseline per model"
            option={stackedOption(
              rows.map((r) =>
                r.model.replace('ThinkSystem ', '').replace('ProLiant ', '').replace('PowerEdge ', ''),
              ),
              stacks,
              theme,
              reducedMotion,
            )}
          />
        )}
      </ChartCard>
      <DataTable
        caption="Fleet by model"
        getRowId={(r) => r.key}
        rows={rows}
        columns={[
          { id: 'vendor', header: 'Vendor', cell: (r) => r.vendor },
          { id: 'model', header: 'Model', cell: (r) => <span className="font-medium">{r.model}</span> },
          { id: 'servers', header: 'Servers', align: 'right', cell: (r) => r.servers },
          {
            id: 'ok',
            header: 'On baseline',
            align: 'right',
            cell: (r) => (r.noBaseline ? '—' : r.compliant),
          },
          {
            id: 'off',
            header: 'Off baseline',
            align: 'right',
            cell: (r) => (r.noBaseline ? '—' : r.offBaseline),
          },
          {
            id: 'state',
            header: 'Baseline',
            cell: (r) =>
              r.noBaseline ? (
                <Pill icon="circle-help" className="text-text-muted bg-text/5 ring-1 ring-inset ring-text/15">
                  None yet
                </Pill>
              ) : (
                <HealthBadge health={r.offBaseline ? 'Warning' : 'OK'} />
              ),
          },
        ]}
      />
    </div>
  );
}

const DASHBOARDS: Record<string, () => ReactNode> = {
  'dc-overview': () => <OverviewDashboard />,
  thermal: () => <ThermalDashboard />,
  'power-capacity': () => <PowerDashboard />,
  'hardware-health': () => <HardwareDashboard />,
  alerts: () => <AlertsDashboard />,
  'inventory-firmware': () => <FirmwareDashboard />,
};

export function DemoDashboard({ slug }: { slug: string }) {
  const render = DASHBOARDS[slug] ?? DASHBOARDS['dc-overview']!;
  return <>{render()}</>;
}
