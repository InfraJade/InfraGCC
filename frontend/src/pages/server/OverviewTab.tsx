import { AnimatePresence, motion } from 'framer-motion';
import { useMemo } from 'react';
import { Link } from 'react-router-dom';

import { readingKey, type LiveServerState } from '@/api/LiveProvider';
import type { Alert, HealthPart, LatestReading } from '@/api/types';
import { SeverityBadge } from '@/components/Badges';
import { EmptyState } from '@/components/EmptyState';
import { GlassCard } from '@/components/GlassCard';
import { HealthBadge } from '@/components/HealthBadge';
import { Icon, type IconName } from '@/components/Icon';
import { Age } from '@/components/Reading';
import { formatTimestamp, formatValue, toMillis } from '@/lib/format';
import { normalizeHealth } from '@/lib/health';
import { useTheme } from '@/theme/ThemeProvider';
import { health as healthTokens, motion as motionTokens } from '@/theme/tokens';

import { categoryLabel, groupBy, sortCategories } from './common';

const CATEGORY_ICONS: Record<string, IconName> = {
  thermal: 'thermometer',
  cooling: 'fan',
  power: 'zap',
  processor: 'chip',
  memory: 'chip',
  storage: 'layers',
  network: 'globe',
};

/** REST latest readings with newer live readings laid over them (a live value wins when its time is newer). */
export function mergeReadings(
  rest: readonly LatestReading[],
  live: LiveServerState['readings'] | undefined,
): LatestReading[] {
  if (!live) return [...rest];
  return rest.map((r) => {
    const l = live[readingKey(r.metric, r.component)];
    if (!l || toMillis(l.time) <= toMillis(r.time)) return r;
    return { ...r, value: l.value, status: l.status, time: l.time };
  });
}

/** REST health per part with live health changes laid over them (live changes are always newer). */
export function mergeHealth(
  rest: readonly HealthPart[],
  live: LiveServerState['health'] | undefined,
): HealthPart[] {
  if (!live) return [...rest];
  return rest.map((p) => {
    const l = live[readingKey(p.metric, p.component)];
    if (!l || toMillis(l.since) < toMillis(p.since)) return p;
    return { ...p, health: normalizeHealth(l.health), state: l.state, since: l.since };
  });
}

function byComponent<T extends { component: string; metric_name: string }>(a: T, b: T): number {
  return (
    a.metric_name.localeCompare(b.metric_name, 'en') ||
    a.component.localeCompare(b.component, 'en', { numeric: true })
  );
}

export function OverviewTab({
  readings,
  healthParts,
  alerts,
  live,
}: {
  readings: readonly LatestReading[];
  healthParts: readonly HealthPart[];
  alerts: readonly Alert[];
  live: LiveServerState | null;
}) {
  const merged = useMemo(() => mergeReadings(readings, live?.readings), [readings, live?.readings]);
  const parts = useMemo(() => mergeHealth(healthParts, live?.health), [healthParts, live?.health]);
  const sensorGroups = useMemo(() => groupBy(merged, (r) => r.category), [merged]);
  const partHealth = useMemo(
    () => new Map(parts.map((p) => [readingKey(p.metric, p.component), p.health] as const)),
    [parts],
  );
  const partGroups = useMemo(() => groupBy(parts, (p) => p.category), [parts]);

  return (
    <div className="flex flex-col gap-6">
      <section aria-labelledby="sensors-heading">
        <h2
          id="sensors-heading"
          className="mb-3 text-sm font-semibold uppercase tracking-wider text-text-muted"
        >
          Live sensors
        </h2>
        {merged.length === 0 ? (
          <GlassCard>
            <EmptyState
              icon="activity"
              title="No sensor readings yet"
              description="Readings appear within a minute or two of the collector's first poll of this BMC."
            />
          </GlassCard>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {sortCategories(sensorGroups.keys()).map((cat) => (
              <GlassCard
                key={cat}
                as="section"
                aria-label={`${categoryLabel(cat)} sensors`}
                title={
                  <span className="flex items-center gap-2">
                    <Icon name={CATEGORY_ICONS[cat] ?? 'activity'} size={14} className="text-accent" />
                    {categoryLabel(cat)}
                  </span>
                }
              >
                <ul className="divide-y divide-text/10">
                  {[...(sensorGroups.get(cat) ?? [])].sort(byComponent).map((r) => (
                    <SensorRow
                      key={readingKey(r.metric, r.component)}
                      reading={r}
                      health={partHealth.get(readingKey(r.metric, r.component))}
                    />
                  ))}
                </ul>
              </GlassCard>
            ))}
          </div>
        )}
      </section>

      <div className="grid gap-6 xl:grid-cols-2">
        <section aria-labelledby="parts-heading">
          <h2
            id="parts-heading"
            className="mb-3 text-sm font-semibold uppercase tracking-wider text-text-muted"
          >
            Health per part
          </h2>
          <GlassCard>
            {parts.length === 0 ? (
              <EmptyState icon="shield" title="No health reported yet" />
            ) : (
              <div className="flex flex-col gap-4">
                {sortCategories(partGroups.keys()).map((cat) => (
                  <div key={cat}>
                    <h3 className="mb-1 text-xs font-medium uppercase tracking-wider text-text-subtle">
                      {categoryLabel(cat)}
                    </h3>
                    <ul className="divide-y divide-text/10">
                      {[...(partGroups.get(cat) ?? [])]
                        .sort(
                          (a, b) =>
                            healthTokens[normalizeHealth(b.health)].rank -
                              healthTokens[normalizeHealth(a.health)].rank || byComponent(a, b),
                        )
                        .map((p) => (
                          <li
                            key={readingKey(p.metric, p.component)}
                            className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-2 text-sm"
                          >
                            <span className="min-w-0">
                              <span className="text-text">{p.metric_name}</span>
                              {p.component ? (
                                <span className="ml-1.5 text-xs text-text-muted">{p.component}</span>
                              ) : null}
                              {p.state ? (
                                <span className="block text-xs text-text-subtle">{p.state}</span>
                              ) : null}
                            </span>
                            <span className="flex items-center gap-2 text-xs">
                              <HealthBadge
                                health={p.health}
                                size="sm"
                                context={`${p.metric_name} ${p.component}`.trim()}
                              />
                              <span className="text-text-subtle">
                                since <Age time={p.since} staleAfterMs={Number.POSITIVE_INFINITY} />
                              </span>
                            </span>
                          </li>
                        ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </GlassCard>
        </section>

        <section aria-labelledby="alerts-heading">
          <h2
            id="alerts-heading"
            className="mb-3 text-sm font-semibold uppercase tracking-wider text-text-muted"
          >
            Active alerts
          </h2>
          <GlassCard>
            {alerts.length === 0 ? (
              <EmptyState
                icon="circle-check"
                title="No active alerts"
                description="Nothing needs attention."
              />
            ) : (
              <ul className="divide-y divide-text/10">
                {alerts.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm">
                    <SeverityBadge severity={a.severity} />
                    <Link
                      to={`/alerts?id=${a.id}`}
                      className="min-w-0 flex-1 text-text hover:text-accent hover:underline"
                    >
                      {a.title}
                    </Link>
                    <span className="text-xs text-text-subtle">
                      opened <Age time={a.opened_at} staleAfterMs={Number.POSITIVE_INFINITY} />
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </GlassCard>
        </section>
      </div>
    </div>
  );
}

/**
 * One latest reading. The badge is the reading's status when it is a health word (OK / Warning / Critical);
 * state metrics report words like On, Up or Reachable instead, which are shown as text next to the part's
 * health from `health_parts`.
 */
function SensorRow({ reading: r, health }: { reading: LatestReading; health?: string }) {
  const { reducedMotion } = useTheme();
  const isState = r.type === 'state';
  const statusIsHealth = r.status !== null && normalizeHealth(r.status) !== 'Unknown';
  const stateWord = isState && r.status && !statusIsHealth ? r.status : null;
  const badge = statusIsHealth ? r.status : (health ?? r.status);
  return (
    <li
      className="flex items-center justify-between gap-3 py-2 text-sm"
      data-sensor={readingKey(r.metric, r.component)}
    >
      <span className="min-w-0">
        <span className="text-text">{r.metric_name}</span>
        {r.component ? <span className="ml-1.5 text-xs text-text-muted">{r.component}</span> : null}
      </span>
      <span className="flex shrink-0 items-center gap-2">
        {!isState ? (
          <AnimatePresence mode="popLayout" initial={false}>
            <motion.span
              key={`${r.value}-${r.time}`}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: reducedMotion ? 0 : motionTokens.duration.base / 1000 }}
              className="tabular font-medium text-text"
              title={formatTimestamp(r.time)}
            >
              {formatValue(r.value, r.unit || undefined)}
            </motion.span>
          </AnimatePresence>
        ) : null}
        {stateWord ? <span className="font-medium text-text">{stateWord}</span> : null}
        <Age time={r.time} className="text-xs" />
        {badge ? (
          <HealthBadge health={badge} size="sm" context={`${r.metric_name} ${r.component}`.trim()} />
        ) : null}
      </span>
    </li>
  );
}
