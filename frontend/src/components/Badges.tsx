import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';
import { healthClasses } from '@/lib/health';

import { Icon, type IconName } from './Icon';

/** Shared pill: icon + word + tint. Never color alone (DESIGN rule). */
export function Pill({
  icon,
  children,
  className,
  title,
}: {
  icon?: IconName;
  children: ReactNode;
  className: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium leading-5',
        className,
      )}
    >
      {icon ? <Icon name={icon} size={13} /> : null}
      <span>{children}</span>
    </span>
  );
}

const SEVERITY: Record<string, { icon: IconName; cls: string; label: string }> = {
  critical: { icon: 'octagon-x', cls: healthClasses.Critical.soft, label: 'Critical' },
  warning: { icon: 'triangle-alert', cls: healthClasses.Warning.soft, label: 'Warning' },
  info: { icon: 'info', cls: 'text-info bg-info/10 ring-1 ring-inset ring-info/30', label: 'Info' },
};

/** Alert severity: Critical / Warning / Info. */
export function SeverityBadge({
  severity,
  className,
}: {
  severity: string | null | undefined;
  className?: string;
}) {
  const s = SEVERITY[(severity ?? '').toLowerCase()] ?? {
    icon: 'circle-help' as const,
    cls: healthClasses.Unknown.soft,
    label: severity || 'Unknown',
  };
  return (
    <Pill icon={s.icon} className={cn(s.cls, className)}>
      {s.label}
    </Pill>
  );
}

const NEUTRAL = 'text-text-muted bg-text/5 ring-1 ring-inset ring-text/15';

const ALERT_STATE: Record<string, { icon: IconName; cls: string; label: string }> = {
  open: { icon: 'bell', cls: 'text-accent bg-accent/10 ring-1 ring-inset ring-accent/30', label: 'Open' },
  acknowledged: { icon: 'eye', cls: NEUTRAL, label: 'Acknowledged' },
  resolved: { icon: 'circle-check', cls: healthClasses.OK.soft, label: 'Resolved' },
};

/** Alert lifecycle state: Open / Acknowledged / Resolved, plus "Muted" when a maintenance window covers it. */
export function AlertStateBadge({
  state,
  muted,
  className,
}: {
  state: string | null | undefined;
  muted?: boolean;
  className?: string;
}) {
  const s = ALERT_STATE[(state ?? '').toLowerCase()] ?? {
    icon: 'circle-help' as const,
    cls: NEUTRAL,
    label: state ?? '—',
  };
  return (
    <span className={cn('inline-flex flex-wrap items-center gap-1', className)}>
      <Pill icon={s.icon} className={s.cls}>
        {s.label}
      </Pill>
      {muted ? (
        <Pill icon="clock" className={NEUTRAL} title="A maintenance window covers this alert">
          Muted
        </Pill>
      ) : null}
    </span>
  );
}

const SERVER_STATUS: Record<string, { icon: IconName; cls: string; label: string }> = {
  active: { icon: 'activity', cls: NEUTRAL, label: 'Active' },
  maintenance: { icon: 'clock', cls: healthClasses.Warning.soft, label: 'Maintenance' },
  decommissioned: { icon: 'x', cls: healthClasses.Unknown.soft, label: 'Decommissioned' },
};

/** Server lifecycle status (separate from health). */
export function ServerStatusBadge({
  status,
  className,
}: {
  status: string | null | undefined;
  className?: string;
}) {
  const s = SERVER_STATUS[(status ?? '').toLowerCase()] ?? {
    icon: 'circle-help' as const,
    cls: NEUTRAL,
    label: status ?? '—',
  };
  return (
    <Pill icon={s.icon} className={cn(s.cls, className)}>
      {s.label}
    </Pill>
  );
}

/** Online/offline for collectors (word + color + icon). */
export function OnlineBadge({ online, className }: { online: boolean; className?: string }) {
  return online ? (
    <Pill icon="circle-check" className={cn(healthClasses.OK.soft, className)}>
      Online
    </Pill>
  ) : (
    <Pill icon="wifi-off" className={cn(healthClasses.Critical.soft, className)}>
      Offline
    </Pill>
  );
}
