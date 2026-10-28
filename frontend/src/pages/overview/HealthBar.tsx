import type { HealthCounts } from '@/api/types';
import { Icon } from '@/components/Icon';
import { cn } from '@/lib/cn';
import { healthClasses } from '@/lib/health';
import { health as healthTokens, type HealthState } from '@/theme/tokens';

const ORDER: { state: HealthState; key: keyof HealthCounts }[] = [
  { state: 'Critical', key: 'critical' },
  { state: 'Warning', key: 'warning' },
  { state: 'Unknown', key: 'unknown' },
  { state: 'OK', key: 'ok' },
];

export function healthSummary(counts: HealthCounts | undefined): string {
  const parts = ORDER.map(({ state, key }) => ({ state, n: counts?.[key] ?? 0 })).filter((p) => p.n > 0);
  return parts.length ? parts.map((p) => `${p.n} ${healthTokens[p.state].label}`).join(', ') : 'no servers';
}

/**
 * Server health distribution: a stacked bar (decorative) plus a legend of words and counts, so the
 * information never depends on color (DESIGN rule).
 */
export function HealthBar({
  counts,
  size = 'md',
  legend = true,
  className,
}: {
  counts: HealthCounts | undefined;
  size?: 'sm' | 'md' | 'lg';
  legend?: boolean;
  className?: string;
}) {
  const parts = ORDER.map(({ state, key }) => ({ state, n: counts?.[key] ?? 0 }));
  const total = parts.reduce((a, p) => a + p.n, 0);
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <div
        role="img"
        aria-label={`Server health: ${healthSummary(counts)}`}
        className={cn(
          'flex w-full overflow-hidden rounded-full bg-text/10',
          size === 'sm' ? 'h-1.5' : size === 'lg' ? 'h-3' : 'h-2',
        )}
      >
        {total > 0
          ? parts
              .filter((p) => p.n > 0)
              .map((p) => (
                <span
                  key={p.state}
                  className={cn('h-full', healthClasses[p.state].dot)}
                  style={{ width: `${(p.n / total) * 100}%` }}
                />
              ))
          : null}
      </div>
      {legend ? (
        <ul
          aria-hidden="true"
          className={cn(
            'flex flex-wrap gap-x-3 gap-y-0.5 text-text-muted',
            size === 'lg' ? 'text-sm wall:text-base' : 'text-xs',
          )}
        >
          {parts
            .filter((p) => p.n > 0 || p.state === 'OK')
            .map((p) => (
              <li key={p.state} className="inline-flex items-center gap-1">
                <Icon name={healthTokens[p.state].icon} size={12} className={healthClasses[p.state].text} />
                <span className="tabular font-medium text-text">{p.n}</span>
                {healthTokens[p.state].label}
              </li>
            ))}
        </ul>
      ) : null}
    </div>
  );
}
