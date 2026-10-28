import type { ReactNode } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { Button } from '@/components/Button';
import { EmptyState } from '@/components/EmptyState';
import { GlassCard } from '@/components/GlassCard';
import { FullPageSpinner } from '@/components/Spinner';

import { useAuth } from './AuthProvider';
import { ROLE_LABELS, type Role } from './roles';

/** Signed-in users only; others go to /login and come back afterwards. */
export function RequireAuth({ children }: { children?: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === 'loading') return <FullPageSpinner label="Checking your session…" />;
  if (status === 'unauthenticated') {
    const returnTo = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate to="/login" replace state={{ returnTo }} />;
  }
  return children ? <>{children}</> : <Outlet />;
}

/** Role-guarded route section: renders a 403 page instead of redirecting, so the URL stays shareable. */
export function RequireRole({ role, children }: { role: Role; children?: ReactNode }) {
  const { hasRole } = useAuth();
  if (!hasRole(role)) return <Forbidden role={role} />;
  return children ? <>{children}</> : <Outlet />;
}

export function Forbidden({ role }: { role?: Role }) {
  return (
    <GlassCard className="mx-auto mt-10 max-w-lg">
      <EmptyState
        icon="shield"
        title="You don't have access to this page"
        description={
          role
            ? `It needs the ${ROLE_LABELS[role]} role or higher. Roles come from your company SSO groups — ask your platform admin.`
            : 'Ask your platform admin for access.'
        }
        action={
          <Button icon="chevron-left" onClick={() => window.history.back()}>
            Go back
          </Button>
        }
      />
    </GlassCard>
  );
}
