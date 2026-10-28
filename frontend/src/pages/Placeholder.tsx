import type { ReactNode } from 'react';

import { EmptyState } from '@/components/EmptyState';
import { GlassCard } from '@/components/GlassCard';
import type { IconName } from '@/components/Icon';
import { PageHeader, type Breadcrumb } from '@/components/PageHeader';

export interface PlaceholderPageProps {
  title: string;
  subtitle?: string;
  breadcrumbs?: Breadcrumb[];
  icon?: IconName;
  /** What this screen will show (from DESIGN.md → Frontend → Screens). */
  description: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}

/** Wave-1 placeholder: real header + a note on what the screen will contain. */
export function PlaceholderPage({
  title,
  subtitle,
  breadcrumbs,
  icon = 'layers',
  description,
  actions,
  children,
}: PlaceholderPageProps) {
  return (
    <>
      <PageHeader title={title} subtitle={subtitle} breadcrumbs={breadcrumbs} actions={actions} />
      {children}
      <GlassCard>
        <EmptyState icon={icon} title="Coming in wave 2" description={description} />
      </GlassCard>
    </>
  );
}
