import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { cn } from '@/lib/cn';

import { Icon } from './Icon';

export interface Breadcrumb {
  label: string;
  to?: string;
}

export interface PageHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  breadcrumbs?: Breadcrumb[];
  /** Right-aligned buttons. */
  actions?: ReactNode;
  /** Small element after the title (e.g. a HealthBadge). */
  badge?: ReactNode;
  className?: string;
}

export function PageHeader({ title, subtitle, breadcrumbs, actions, badge, className }: PageHeaderProps) {
  return (
    <header className={cn('mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between', className)}>
      <div className="min-w-0">
        {breadcrumbs && breadcrumbs.length > 0 ? (
          <nav aria-label="Breadcrumb" className="mb-1.5">
            <ol className="flex flex-wrap items-center gap-1 text-xs text-text-muted">
              {breadcrumbs.map((b, i) => {
                const last = i === breadcrumbs.length - 1;
                return (
                  <li key={`${b.label}-${i}`} className="flex items-center gap-1">
                    {b.to && !last ? (
                      <Link to={b.to} className="rounded hover:text-text hover:underline">
                        {b.label}
                      </Link>
                    ) : (
                      <span
                        aria-current={last ? 'page' : undefined}
                        className={last ? 'text-text' : undefined}
                      >
                        {b.label}
                      </span>
                    )}
                    {!last ? <Icon name="chevron-right" size={12} className="text-text-subtle" /> : null}
                  </li>
                );
              })}
            </ol>
          </nav>
        ) : null}
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="truncate text-2xl font-semibold tracking-tight text-text">{title}</h1>
          {badge}
        </div>
        {subtitle ? <p className="mt-1 text-sm text-text-muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
