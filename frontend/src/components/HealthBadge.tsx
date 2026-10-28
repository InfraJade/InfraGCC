import { cn } from '@/lib/cn';
import { healthClasses, normalizeHealth } from '@/lib/health';
import { health as healthTokens } from '@/theme/tokens';

import { Icon } from './Icon';

export interface HealthBadgeProps {
  /** Any API health string; unknown values render as "Unknown". */
  health: string | null | undefined;
  size?: 'sm' | 'md' | 'lg';
  /** soft = tinted pill (default), solid = filled pill, plain = icon + word only. */
  variant?: 'soft' | 'solid' | 'plain';
  /** Optional prefix for screen readers / context, e.g. "Fan 3". Visible text stays the health word. */
  context?: string;
  className?: string;
}

const sizes = {
  sm: { box: 'gap-1 px-1.5 py-0.5 text-[11px]', icon: 12 },
  md: { box: 'gap-1.5 px-2 py-0.5 text-xs', icon: 14 },
  lg: { box: 'gap-2 px-3 py-1 text-sm', icon: 16 },
} as const;

/** Health shown as word + color + icon — never color alone (DESIGN rule). */
export function HealthBadge({ health, size = 'md', variant = 'soft', context, className }: HealthBadgeProps) {
  const state = normalizeHealth(health);
  const t = healthTokens[state];
  const c = healthClasses[state];
  const s = sizes[size];
  return (
    <span
      data-health={state}
      className={cn(
        'inline-flex shrink-0 items-center whitespace-nowrap rounded-full font-medium leading-5',
        s.box,
        variant === 'soft' && c.soft,
        variant === 'solid' && c.solid,
        variant === 'plain' && cn(c.text, 'px-0'),
        className,
      )}
      title={context ? `${context}: ${t.label}` : undefined}
    >
      <Icon name={t.icon} size={s.icon} />
      {context ? <span className="sr-only">{context}: </span> : null}
      <span>{t.label}</span>
    </span>
  );
}
