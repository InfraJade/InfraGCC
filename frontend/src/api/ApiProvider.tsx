import { useQueryClient } from '@tanstack/react-query';
import { createContext, useContext, useEffect, useMemo, useRef, type ReactNode } from 'react';

import { useAuth } from '@/auth/AuthProvider';
import { useDemoMode } from '@/demo/demoMode';
import { createDemoFetch, demoUserFrom } from '@/demo/fetch';

import { createApi, type Api } from './client';

const ApiContext = createContext<Api | null>(null);

/**
 * Provides the authenticated API client (bearer token, renew-and-retry on 401). In demo mode the same client
 * is backed by the in-browser demo data instead of the network; flipping the switch drops every cached
 * response so all screens reload from the new source.
 */
export function ApiProvider({ children, api }: { children: ReactNode; api?: Api }) {
  const auth = useAuth();
  const demo = useDemoMode();
  const qc = useQueryClient();
  // Keep the latest auth functions without rebuilding the client on every auth state change.
  const authRef = useRef(auth);
  authRef.current = auth;
  const value = useMemo(
    () =>
      api ??
      createApi(
        {
          getAccessToken: () => authRef.current.getAccessToken(),
          renew: () => authRef.current.renew(),
          onUnauthorized: () => {
            if (authRef.current.status === 'authenticated')
              void authRef.current.signIn(window.location.pathname);
          },
        },
        demo ? { baseFetch: createDemoFetch(() => demoUserFrom(authRef.current.user)) } : {},
      ),
    [api, demo],
  );

  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    qc.removeQueries({ queryKey: ['live'] });
    void qc.resetQueries();
  }, [demo, qc]);

  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>;
}

export function useApi(): Api {
  const ctx = useContext(ApiContext);
  if (!ctx) throw new Error('useApi must be used inside <ApiProvider>');
  return ctx;
}
