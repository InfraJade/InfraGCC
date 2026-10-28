import { Link } from 'react-router-dom';

import type { AlertCounts, SiteSummary } from '@/api/types';
import { Pill, SeverityBadge } from '@/components/Badges';
import { GlassCard } from '@/components/GlassCard';
import { HealthBadge } from '@/components/HealthBadge';
import { Age, Reading } from '@/components/Reading';
import { cn } from '@/lib/cn';
import { formatValue } from '@/lib/format';
import { healthClasses } from '@/lib/health';

import { HealthBar, healthSummary } from './HealthBar';
import { openAlertTotal } from './useOverview';

/** Open alerts by severity as word pills ("2 Critical"), or "No open alerts". */
export function AlertCountPills({ alerts, large }: { alerts: AlertCounts | undefined; large?: boolean }) {
  const total = openAlertTotal(alerts);
  if (total === 0)
    return (
      <Pill icon="circle-check" className={healthClasses.OK.soft}>
        No open alerts
      </Pill>
    );
  const items: { severity: string; n: number }[] = [
    { severity: 'Critical', n: alerts?.critical ?? 0 },
    { severity: 'Warning', n: alerts?.warning ?? 0 },
    { severity: 'Info', n: alerts?.info ?? 0 },
  ].filter((i) => i.n > 0);
  return (
    <ul className={cn('flex flex-wrap items-center gap-1.5', large && 'gap-2')} aria-label="Open alerts">
      {items.map((i) => (
        <li key={i.severity} className="inline-flex items-center gap-1">
          <span
            className={cn('tabular font-semibold text-text', large ? 'text-lg wall:text-2xl' : 'text-sm')}
          >
            {i.n}
          </span>
          <SeverityBadge severity={i.severity} />
        </li>
      ))}
    </ul>
  );
}

function Metric({ label, children, large }: { label: string; children: React.ReactNode; large?: boolean }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt
        className={cn(
          'uppercase tracking-wider text-text-subtle',
          large ? 'text-xs wall:text-sm' : 'text-[11px]',
        )}
      >
        {label}
      </dt>
      <dd className={cn('min-w-0', large ? 'text-base wall:text-xl' : 'text-sm')}>{children}</dd>
    </div>
  );
}

/** One site on the overview / wall: health, servers, open alerts, power, inlet, collectors, freshness. */
export function SiteCard({ site, size = 'md' }: { site: SiteSummary; size?: 'md' | 'wall' }) {
  const large = size === 'wall';
  const measured = site.freshness?.latest_reading_at ?? null;
  const stale = site.freshness?.servers_stale ?? 0;
  const capacityKw =
    site.rack_power_capacity_w !== null && site.rack_power_capacity_w !== undefined
      ? site.rack_power_capacity_w / 1000
      : null;
  const usedPct =
    capacityKw && site.power_w !== null && site.power_w !== undefined
      ? Math.min(100, (site.power_w / 1000 / capacityKw) * 100)
      : null;
  const collectorsDown = (site.collectors_total ?? 0) - (site.collectors_online ?? 0);

  return (
    <Link
      to={`/sites/${site.id}`}
      className="block rounded-xl focus-visible:outline-offset-4"
      aria-label={`${site.code} ${site.name}: health ${site.worst_health ?? 'Unknown'}, ${site.server_count ?? 0} servers (${healthSummary(site.health)}), ${openAlertTotal(site.alerts)} open alerts`}
    >
      <GlassCard interactive as="article" padding={large ? 'lg' : 'md'} className="h-full">
        <header className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2
              className={cn(
                'font-semibold tracking-tight text-text',
                large ? 'text-2xl wall:text-4xl' : 'text-lg',
              )}
            >
              {site.code}
              <span
                className={cn(
                  'ml-2 font-normal text-text-muted',
                  large ? 'text-lg wall:text-2xl' : 'text-sm',
                )}
              >
                {site.name}
              </span>
            </h2>
            <p className={cn('text-text-subtle', large ? 'text-sm wall:text-base' : 'text-xs')}>
              {site.city}, {site.country}
            </p>
          </div>
          <HealthBadge health={site.worst_health} size={large ? 'lg' : 'md'} />
        </header>

        <div className="mt-4 flex flex-col gap-1.5">
          <div className="flex items-baseline justify-between gap-2">
            <span className={cn('text-text-muted', large ? 'text-base wall:text-lg' : 'text-sm')}>
              <span
                className={cn(
                  'tabular font-semibold text-text',
                  large ? 'text-3xl wall:text-5xl' : 'text-2xl',
                )}
              >
                {formatValue(site.server_count ?? 0)}
              </span>{' '}
              servers
            </span>
            {site.servers_in_maintenance ? (
              <span className="text-xs text-text-subtle">{site.servers_in_maintenance} in maintenance</span>
            ) : null}
          </div>
          <HealthBar counts={site.health} size={large ? 'lg' : 'md'} />
        </div>

        <div className="mt-4">
          <AlertCountPills alerts={site.alerts} large={large} />
          {site.alerts?.acknowledged || site.alerts?.muted ? (
            <p className="mt-1 text-xs text-text-subtle">
              {[
                site.alerts.acknowledged ? `${site.alerts.acknowledged} acknowledged` : null,
                site.alerts.muted ? `${site.alerts.muted} muted by maintenance` : null,
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
          ) : null}
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-t hairline pt-4">
          <Metric label="Power draw" large={large}>
            <Reading value={site.power_w ?? null} unit="W" time={measured} layout="stacked" />
            {capacityKw !== null ? (
              <span className="block text-xs text-text-subtle">
                of {formatValue(capacityKw, 'kW', 1)} rack capacity
                {usedPct !== null ? ` (${formatValue(usedPct, '%', 0)})` : ''}
              </span>
            ) : null}
          </Metric>
          <Metric label="Inlet avg / max" large={large}>
            <span className="tabular font-medium text-text">
              {formatValue(site.inlet_avg_c ?? null, '°C')} / {formatValue(site.inlet_max_c ?? null, '°C')}
            </span>
            {measured ? (
              <Age time={measured} className="block text-xs" />
            ) : (
              <span className="block text-xs text-text-subtle">age unknown</span>
            )}
          </Metric>
          <Metric label="Collectors" large={large}>
            <span
              className={cn('tabular font-medium', collectorsDown > 0 ? 'text-health-critical' : 'text-text')}
            >
              {site.collectors_online ?? 0} of {site.collectors_total ?? 0} online
            </span>
            {collectorsDown > 0 ? (
              <span className="block text-xs text-health-critical">{collectorsDown} offline</span>
            ) : null}
          </Metric>
          <Metric label="Data" large={large}>
            <span className="tabular font-medium text-text">
              {site.freshness?.servers_reporting ?? 0} reporting
            </span>
            <span className={cn('block text-xs', stale > 0 ? 'text-health-warning' : 'text-text-subtle')}>
              {stale > 0 ? `${stale} stale (no reading for 5 min)` : 'none stale'}
            </span>
          </Metric>
        </dl>
      </GlassCard>
    </Link>
  );
}
