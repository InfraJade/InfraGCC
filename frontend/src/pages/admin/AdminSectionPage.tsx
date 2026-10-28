import { Suspense } from 'react';

import { Skeleton } from '@/components/Skeleton';

import type { AdminSection } from './sections';

export default function AdminSectionPage({ section }: { section: AdminSection }) {
  const Section = section.component;
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full rounded-xl" label={`Loading ${section.label}`} />}>
      <Section />
    </Suspense>
  );
}
