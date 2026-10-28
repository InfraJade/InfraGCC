import { Link } from 'react-router-dom';

import { EmptyState } from '@/components/EmptyState';
import { GlassCard } from '@/components/GlassCard';

export default function NotFoundPage() {
  return (
    <GlassCard className="mx-auto mt-10 max-w-lg">
      <EmptyState
        icon="search"
        title="Page not found"
        description="The address may be mistyped, or the item was removed."
        action={
          <Link to="/" className="text-sm font-medium text-accent hover:underline">
            Go to the overview
          </Link>
        }
      />
    </GlassCard>
  );
}
