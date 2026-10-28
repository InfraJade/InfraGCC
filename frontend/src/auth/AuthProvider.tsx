import type { User, UserManager } from 'oidc-client-ts';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { createUserManager, toAuthUser, type AuthUser } from './oidc';
import { hasRole as hasRoleIn, type Role } from './roles';

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

export interface AuthContextValue {
  status: AuthStatus;
  user: AuthUser | null;
  /** Last sign-in / renew error, for the login page. */
  error: unknown;
  signIn: (returnTo?: string) => Promise<void>;
  signOut: () => Promise<void>;
  /** A currently valid access token (renews silently if it has expired), or null when signed out. */
  getAccessToken: () => Promise<string | null>;
  /** Force a silent renew (used after a 401). Resolves to the new token, or null if renew failed. */
  renew: () => Promise<string | null>;
  /** Process the redirect on /auth/callback; resolves to the path to return to. */
  completeSignIn: () => Promise<string>;
  hasRole: (role: Role) => boolean;
  /** Whether the user may see a site (by code); users without site groups see all sites. */
  canSeeSite: (siteCode: string) => boolean;
  /** Subscribe to token changes (sign-in and silent renew); used by the live WebSocket to re-auth. */
  onTokenChange: (listener: (token: string | null) => void) => () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

interface RedirectState {
  returnTo?: string;
}

function safeReturnTo(path: unknown): string {
  // Only same-app paths; never an absolute URL (open redirect).
  return typeof path === 'string' &&
    path.startsWith('/') &&
    !path.startsWith('//') &&
    !path.startsWith('/auth/')
    ? path
    : '/';
}

// signinCallback() must run once per redirect, even under React StrictMode's double effects.
let callbackPromise: Promise<User | undefined> | null = null;

export function AuthProvider({ children, userManager }: { children: ReactNode; userManager?: UserManager }) {
  const um = useMemo(() => userManager ?? createUserManager(), [userManager]);
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<AuthUser | null>(null);
  const [error, setError] = useState<unknown>(null);
  const listeners = useRef(new Set<(token: string | null) => void>());
  const renewing = useRef<Promise<string | null> | null>(null);

  const apply = useCallback((u: User | null) => {
    const next = u && !u.expired ? toAuthUser(u) : null;
    setUser(next);
    setStatus(next ? 'authenticated' : 'unauthenticated');
    listeners.current.forEach((l) => l(next?.accessToken ?? null));
  }, []);

  const renew = useCallback((): Promise<string | null> => {
    renewing.current ??= um
      .signinSilent()
      .then((u) => {
        apply(u);
        return u && !u.expired ? u.access_token : null;
      })
      .catch((e: unknown) => {
        setError(e);
        return null;
      })
      .finally(() => {
        renewing.current = null;
      });
    return renewing.current;
  }, [um, apply]);

  useEffect(() => {
    let cancelled = false;
    // On /auth/callback the CallbackPage drives sign-in; don't race it with a stale stored user.
    const onCallback = window.location.pathname.startsWith('/auth/callback');
    if (!onCallback) {
      um.getUser()
        .then(async (u) => {
          if (cancelled) return;
          if (u && u.expired) {
            const token = await renew();
            if (!token && !cancelled) {
              await um.removeUser();
              apply(null);
            }
            return;
          }
          apply(u);
        })
        .catch((e: unknown) => {
          if (cancelled) return;
          setError(e);
          apply(null);
        });
    }

    const onLoaded = (u: User) => apply(u);
    const onUnloaded = () => apply(null);
    const onExpired = () => {
      void renew().then((t) => {
        if (!t) apply(null);
      });
    };
    const onRenewError = (e: Error) => setError(e);
    um.events.addUserLoaded(onLoaded);
    um.events.addUserUnloaded(onUnloaded);
    um.events.addAccessTokenExpired(onExpired);
    um.events.addSilentRenewError(onRenewError);
    return () => {
      cancelled = true;
      um.events.removeUserLoaded(onLoaded);
      um.events.removeUserUnloaded(onUnloaded);
      um.events.removeAccessTokenExpired(onExpired);
      um.events.removeSilentRenewError(onRenewError);
    };
  }, [um, apply, renew]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      error,
      signIn: async (returnTo) => {
        setError(null);
        const state: RedirectState = { returnTo: safeReturnTo(returnTo) };
        await um.signinRedirect({ state });
      },
      signOut: async () => {
        const current = await um.getUser().catch(() => null);
        try {
          await um.signoutRedirect({ id_token_hint: current?.id_token });
        } catch {
          // IdP unreachable: still end the local session.
          await um.removeUser();
          window.location.assign('/login');
        }
      },
      getAccessToken: async () => {
        const u = await um.getUser();
        if (u && !u.expired) return u.access_token;
        if (!u) return null;
        return renew();
      },
      renew,
      completeSignIn: async () => {
        callbackPromise ??= um.signinCallback();
        try {
          const u = await callbackPromise;
          if (u) apply(u);
          const state = (u?.state ?? {}) as RedirectState;
          return safeReturnTo(state.returnTo);
        } catch (e) {
          callbackPromise = null;
          setError(e);
          apply(null);
          throw e;
        }
      },
      hasRole: (role) => (user ? hasRoleIn(user.roles, role) : false),
      canSeeSite: (code) =>
        user ? user.sites.length === 0 || user.sites.includes(code.toUpperCase()) : false,
      onTokenChange: (listener) => {
        listeners.current.add(listener);
        return () => listeners.current.delete(listener);
      },
    }),
    [status, user, error, um, renew, apply],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}

/** Test/gallery helper: a fixed, signed-in auth context. */
export function createStaticAuth(user: AuthUser): AuthContextValue {
  return {
    status: 'authenticated',
    user,
    error: null,
    signIn: () => Promise.resolve(),
    signOut: () => Promise.resolve(),
    getAccessToken: () => Promise.resolve(user.accessToken),
    renew: () => Promise.resolve(user.accessToken),
    completeSignIn: () => Promise.resolve('/'),
    hasRole: (role) => hasRoleIn(user.roles, role),
    canSeeSite: (code) => user.sites.length === 0 || user.sites.includes(code.toUpperCase()),
    onTokenChange: () => () => undefined,
  };
}
