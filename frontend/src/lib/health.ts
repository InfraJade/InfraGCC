import { health, type HealthState } from '@/theme/tokens';

export type { HealthState };

/** Map whatever the API sends ("OK", "ok", "Warning", null, …) to one of the four states. */
export function normalizeHealth(value: string | null | undefined): HealthState {
  switch ((value ?? '').trim().toLowerCase()) {
    case 'ok':
    case 'healthy':
      return 'OK';
    case 'warning':
    case 'degraded':
      return 'Warning';
    case 'critical':
    case 'failed':
      return 'Critical';
    default:
      return 'Unknown';
  }
}

/** Worst health of a set (Critical > Warning > Unknown > OK), same order as the backend. */
export function worstHealth(values: Iterable<string | null | undefined>): HealthState {
  let worst: HealthState = 'OK';
  let any = false;
  for (const v of values) {
    any = true;
    const h = normalizeHealth(v);
    if (health[h].rank > health[worst].rank) worst = h;
  }
  return any ? worst : 'Unknown';
}

/** Static Tailwind classes per state (class names must be literal for Tailwind's scanner). */
export const healthClasses: Record<
  HealthState,
  { text: string; soft: string; solid: string; fill: string; stroke: string; dot: string }
> = {
  OK: {
    text: 'text-health-ok',
    soft: 'text-health-ok bg-health-ok/10 ring-1 ring-inset ring-health-ok/30',
    solid: 'bg-health-ok text-canvas',
    fill: 'fill-health-ok/15',
    stroke: 'stroke-health-ok',
    dot: 'bg-health-ok',
  },
  Warning: {
    text: 'text-health-warning',
    soft: 'text-health-warning bg-health-warning/10 ring-1 ring-inset ring-health-warning/35',
    solid: 'bg-health-warning text-canvas',
    fill: 'fill-health-warning/20',
    stroke: 'stroke-health-warning',
    dot: 'bg-health-warning',
  },
  Critical: {
    text: 'text-health-critical',
    soft: 'text-health-critical bg-health-critical/10 ring-1 ring-inset ring-health-critical/40',
    solid: 'bg-health-critical text-canvas',
    fill: 'fill-health-critical/20',
    stroke: 'stroke-health-critical',
    dot: 'bg-health-critical',
  },
  Unknown: {
    text: 'text-health-unknown',
    soft: 'text-health-unknown bg-health-unknown/10 ring-1 ring-inset ring-health-unknown/30',
    solid: 'bg-health-unknown text-canvas',
    fill: 'fill-health-unknown/10',
    stroke: 'stroke-health-unknown',
    dot: 'bg-health-unknown',
  },
};
