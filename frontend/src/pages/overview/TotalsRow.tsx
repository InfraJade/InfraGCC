import type { OverviewTotals } from '@/api/types';
import { StatTile } from '@/components/StatTile';
import { cn } from '@/lib/cn';
import { formatValue } from '@/lib/format';

import { HealthBar } from './HealthBar';
import { openAlertTotal } from './useOverview';

/** Headline numbers for all (or the filtered) sites. */
export function TotalsRow({
  totals,
  size = 'md',
  className,
}: {
  totals: OverviewTotals;
  size?: 'md' | 'lg';
  className?: string;
}) {
  const measured = totals.freshness.latest_reading_at ?? null;
  const alerts = totals.alerts;
  const open = openAlertTotal(alerts);
  const collectorsDown = totals.collectors_total - totals.collectors_online;
  const stale = totals.freshness.servers_stale ?? 0;
  return (
    <div className={cn('grid gap-4 sm:grid-cols-2 xl:grid-cols-4', className)}>
      <StatTile
        label="Servers"
        icon="server"
        size={size}
        value={totals.server_count}
        time={measured}
        health={totals.worst_health}
        footnote={<HealthBar counts={totals.health} size="sm" className="mt-1 w-full" />}
        to="/inventory"
      />
      <StatTile
        label="Open alerts"
        icon="bell"
        size={size}
        value={open}
        time={measured}
        health={alerts.critical ? 'Critical' : alerts.warning ? 'Warning' : 'OK'}
        footnote={[
          `${alerts.critical ?? 0} critical`,
          `${alerts.warning ?? 0} warning`,
          alerts.acknowledged ? `${alerts.acknowledged} acknowledged` : null,
        ]
          .filter(Boolean)
          .join(' · ')}
        to="/alerts"
      />
      <StatTile
        label="Power draw"
        icon="zap"
        size={size}
        value={totals.power_w === null ? null : totals.power_w / 1000}
        unit="kW"
        precision={1}
        time={measured}
        footnote={`${formatValue(totals.server_count)} servers, ${totals.sites} site${totals.sites === 1 ? '' : 's'}`}
      />
      <StatTile
        label="Collectors"
        icon="activity"
        size={size}
        value={totals.collectors_online}
        time={measured}
        health={totals.collectors_total === 0 ? 'Unknown' : collectorsDown > 0 ? 'Critical' : 'OK'}
        footnote={[
          `of ${totals.collectors_total} online`,
          stale > 0 ? `${stale} server${stale === 1 ? '' : 's'} stale` : null,
        ]
          .filter(Boolean)
          .join(' · ')}
      />
    </div>
  );
}
