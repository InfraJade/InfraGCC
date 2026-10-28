import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { cn } from '@/lib/cn';
import { formatValue, type TimeInput } from '@/lib/format';

import { GlassCard } from './GlassCard';
import { HealthBadge } from './HealthBadge';
import { Icon, type IconName } from './Icon';
import { Age } from './Reading';
import { Skeleton } from './Skeleton';

export interface StatTileProps {
  label: string;
  value: number | null | undefined;
  unit?: string;
  /** When the value was measured; shown as a ticking age. */
  time?: TimeInput | null;
  precision?: number;
  icon?: IconName;
  /** Optional health word+color+icon next to the label. */
  health?: string | null;
  /** Change vs a previous period; `goodWhen` decides the color (up is not always good). */
  delta?: { value: number; unit?: string; label?: string; goodWhen?: 'up' | 'down' };
  /** Secondary line under the value, e.g. "of 42 U". */
  footnote?: ReactNode;
  /** Makes the whole tile a link. */
  to?: string;
  loading?: boolean;
  size?: 'md' | 'lg';
  className?: string;
}

/** A headline number with its unit and age. */
export function StatTile({
  label,
  value,
  unit,
  time,
  precision,
  icon,
  health,
  delta,
  footnote,
  to,
  loading,
  size = 'md',
  className,
}: StatTileProps) {
  const body = (
    <>
      <div className="flex items-start justify-between gap-2">
        <span className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-text-muted">
          {icon ? <Icon name={icon} size={14} className="text-accent" /> : null}
          {label}
        </span>
        {health !== undefined ? <HealthBadge health={health} size="sm" /> : null}
      </div>
      {loading ? (
        <div className="mt-3 space-y-2" aria-busy="true">
          <span className="sr-only">Loading {label}</span>
          <Skeleton className="h-8 w-28" />
          <Skeleton className="h-3 w-16" />
        </div>
      ) : (
        <>
          <div
            className={cn(
              'tabular mt-2 font-semibold tracking-tight text-text',
              size === 'lg' ? 'text-4xl' : 'text-3xl',
            )}
            data-testid="stat-value"
          >
            {formatValue(value, unit, precision)}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            {delta ? <Delta {...delta} /> : null}
            {time ? <Age time={time} /> : <span className="text-text-subtle">age unknown</span>}
            {footnote ? <span className="text-text-muted">{footnote}</span> : null}
          </div>
        </>
      )}
    </>
  );

  if (to) {
    return (
      <Link
        to={to}
        className={cn('block rounded-xl focus-visible:outline-offset-4', className)}
        aria-label={`${label}: ${formatValue(value, unit, precision)}`}
      >
        <GlassCard interactive>{body}</GlassCard>
      </Link>
    );
  }
  return <GlassCard className={className}>{body}</GlassCard>;
}

function Delta({ value, unit, label, goodWhen = 'up' }: NonNullable<StatTileProps['delta']>) {
  const up = value > 0;
  const flat = value === 0;
  const good = flat ? null : (up && goodWhen === 'up') || (!up && goodWhen === 'down');
  return (
    <span
      className={cn(
        'inline-flex items-center gap-0.5 font-medium',
        good === null ? 'text-text-muted' : good ? 'text-health-ok' : 'text-health-critical',
      )}
    >
      {!flat ? <Icon name={up ? 'arrow-up' : 'arrow-down'} size={12} /> : null}
      <span className="tabular">
        {up ? '+' : ''}
        {formatValue(value, unit)}
      </span>
      {label ? <span className="font-normal text-text-subtle">{label}</span> : null}
    </span>
  );
}
