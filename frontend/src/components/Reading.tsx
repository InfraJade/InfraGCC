import { cn } from '@/lib/cn';
import { ageTickMs, formatAge, formatTimestamp, formatValue, toMillis, type TimeInput } from '@/lib/format';
import { useNow } from '@/lib/useNow';

export interface ReadingProps {
  value: number | null | undefined;
  unit?: string;
  /** When the value was measured. Without it the age reads "age unknown" — every number shows its age. */
  time?: TimeInput | null;
  precision?: number;
  /** Older than this (ms) is shown as stale. Default 2 min (design freshness target). */
  staleAfterMs?: number;
  /** inline: "41.2 °C · 30 s ago"; stacked: value on top, age below; value: value only + age in title. */
  layout?: 'inline' | 'stacked' | 'value';
  className?: string;
  valueClassName?: string;
}

export const DEFAULT_STALE_MS = 120_000;

/** Ticking age label shared by Reading and anything else that shows "x s ago". */
export function Age({
  time,
  staleAfterMs = DEFAULT_STALE_MS,
  className,
}: {
  time: TimeInput;
  staleAfterMs?: number;
  className?: string;
}) {
  const tick = ageTickMs(time);
  const now = useNow(tick);
  const stale = now - toMillis(time) > staleAfterMs;
  return (
    <time
      dateTime={new Date(toMillis(time)).toISOString()}
      title={formatTimestamp(time)}
      data-stale={stale || undefined}
      className={cn(
        'tabular whitespace-nowrap',
        stale ? 'text-health-warning' : 'text-text-subtle',
        className,
      )}
    >
      {formatAge(time, now)}
      {stale ? <span className="sr-only"> (stale)</span> : null}
    </time>
  );
}

/** A number with its unit and its age (DESIGN rule): "41 °C, 30 s ago", ticking live. */
export function Reading({
  value,
  unit,
  time,
  precision,
  staleAfterMs = DEFAULT_STALE_MS,
  layout = 'inline',
  className,
  valueClassName,
}: ReadingProps) {
  const text = formatValue(value, unit, precision);
  const valueEl = (
    <data
      value={value ?? ''}
      className={cn('tabular font-medium text-text', valueClassName)}
      aria-label={value === null || value === undefined ? 'no reading' : undefined}
    >
      {text}
    </data>
  );
  const validTime = time !== null && time !== undefined && !Number.isNaN(toMillis(time));
  const ageEl = validTime ? (
    <Age time={time} staleAfterMs={staleAfterMs} className="text-xs" />
  ) : (
    <span className="text-xs text-text-subtle">age unknown</span>
  );

  if (layout === 'value') {
    return (
      <span className={className} title={validTime ? formatTimestamp(time) : undefined}>
        {valueEl}
      </span>
    );
  }
  if (layout === 'stacked') {
    return (
      <span className={cn('inline-flex flex-col', className)}>
        {valueEl}
        {ageEl}
      </span>
    );
  }
  return (
    <span className={cn('inline-flex items-baseline gap-1.5', className)}>
      {valueEl}
      <span aria-hidden="true" className="text-text-subtle">
        ·
      </span>
      {ageEl}
    </span>
  );
}
