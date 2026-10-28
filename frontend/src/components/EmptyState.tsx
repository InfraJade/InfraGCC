import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';

import { Icon, type IconName } from './Icon';

export interface EmptyStateProps {
  icon?: IconName;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  tone?: 'neutral' | 'error';
  className?: string;
}

export function EmptyState({
  icon = 'layers',
  title,
  description,
  action,
  tone = 'neutral',
  className,
}: EmptyStateProps) {
  return (
    <div
      role={tone === 'error' ? 'alert' : undefined}
      className={cn('flex flex-col items-center justify-center gap-2 px-6 py-10 text-center', className)}
    >
      <span
        className={cn(
          'mb-1 inline-flex h-11 w-11 items-center justify-center rounded-full',
          tone === 'error' ? 'bg-health-critical/10 text-health-critical' : 'bg-text/5 text-text-subtle',
        )}
      >
        <Icon name={tone === 'error' ? 'triangle-alert' : icon} size={20} />
      </span>
      <p className="text-sm font-semibold text-text">{title}</p>
      {description ? <div className="max-w-md text-sm text-text-muted">{description}</div> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
