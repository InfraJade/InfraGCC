import { embedDashboard } from '@superset-ui/embedded-sdk';
import { useEffect, useRef, useState } from 'react';

import { errorMessage } from '@/api/errors';
import { cn } from '@/lib/cn';
import { useResolvedTheme } from '@/theme/ThemeProvider';

import { EmptyState } from './EmptyState';
import { Skeleton } from './Skeleton';

export interface SupersetDashboardProps {
  /** `embedded_uuid` from GET /api/v1/superset/dashboards. */
  embeddedUuid: string;
  /** Public Superset origin (guest-token response `superset_url`, or runtime config). */
  supersetUrl: string;
  /** Calls POST /api/v1/superset/guest-token and returns the token (the SDK refreshes it before expiry). */
  fetchGuestToken: () => Promise<string>;
  title: string;
  height?: number | string;
  className?: string;
}

/** Embedded Superset dashboard (guest token with the user's site RLS; no separate Superset sign-in). */
export function SupersetDashboard({
  embeddedUuid,
  supersetUrl,
  fetchGuestToken,
  title,
  height = 'calc(100vh - 14rem)',
  className,
}: SupersetDashboardProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const tokenFn = useRef(fetchGuestToken);
  tokenFn.current = fetchGuestToken;
  const theme = useResolvedTheme();
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    const mountPoint = mountRef.current;
    if (!mountPoint) return;
    let cancelled = false;
    let unmount: (() => void) | null = null;
    setState('loading');
    embedDashboard({
      id: embeddedUuid,
      supersetDomain: supersetUrl.replace(/\/+$/, ''),
      mountPoint,
      fetchGuestToken: () => tokenFn.current(),
      iframeTitle: title,
      dashboardUiConfig: { hideTitle: true, filters: { expanded: false } },
    })
      .then((d) => {
        if (cancelled) {
          d.unmount();
          return;
        }
        unmount = d.unmount;
        try {
          d.setThemeMode(theme === 'dark' ? 'dark' : 'default');
        } catch {
          /* older Superset without theme API */
        }
        setState('ready');
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e);
        setState('error');
      });
    return () => {
      cancelled = true;
      unmount?.();
    };
    // theme is applied on embed; switching theme re-embeds via key in parent if needed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [embeddedUuid, supersetUrl, title]);

  return (
    <div className={cn('glass relative overflow-hidden rounded-xl', className)} style={{ height }}>
      {state === 'loading' ? (
        <Skeleton className="absolute inset-0 h-full rounded-none" label={`Loading ${title}`} />
      ) : null}
      {state === 'error' ? (
        <EmptyState tone="error" title={`Couldn't load “${title}”`} description={errorMessage(error)} />
      ) : null}
      <div ref={mountRef} className="h-full w-full [&>iframe]:h-full [&>iframe]:w-full [&>iframe]:border-0" />
    </div>
  );
}
