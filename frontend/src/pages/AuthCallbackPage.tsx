import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { errorMessage } from '@/api/errors';
import { useAuth } from '@/auth/AuthProvider';
import { EmptyState } from '@/components/EmptyState';
import { GlassCard } from '@/components/GlassCard';
import { FullPageSpinner } from '@/components/Spinner';

/** /auth/callback — finishes the OIDC redirect (and silent renews in an iframe), then returns to the app. */
export default function AuthCallbackPage() {
  const { completeSignIn } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    // Inside the silent-renew iframe the parent window handles the response; render nothing there.
    if (window.self !== window.top) {
      void completeSignIn().catch(() => undefined);
      return;
    }
    completeSignIn()
      .then((to) => navigate(to, { replace: true }))
      .catch((e: unknown) => setError(e));
  }, [completeSignIn, navigate]);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <GlassCard className="max-w-md">
          <EmptyState
            tone="error"
            title="Sign-in could not be completed"
            description={errorMessage(error)}
            action={
              <Link to="/login" className="text-sm font-medium text-accent hover:underline">
                Back to sign in
              </Link>
            }
          />
        </GlassCard>
      </div>
    );
  }
  return <FullPageSpinner label="Signing you in…" />;
}
