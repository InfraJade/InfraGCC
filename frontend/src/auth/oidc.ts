import { UserManager, WebStorageStateStore, type User } from 'oidc-client-ts';

import { getConfig, type RuntimeConfig } from '@/config';

import { decodeJwtPayload, stringArrayClaim } from './jwt';
import { rolesFromGroups, sitesFromGroups, type Role } from './roles';

export const CALLBACK_PATH = '/auth/callback';
export const LOGIN_PATH = '/login';

/**
 * Keycloak (any OIDC IdP) via authorization code + PKCE. Tokens live in sessionStorage (per tab, gone when
 * the browser closes). Silent renew uses the refresh token when the IdP issues one (Keycloak does).
 */
export function createUserManager(config: RuntimeConfig = getConfig()): UserManager {
  const origin = window.location.origin;
  return new UserManager({
    authority: config.oidcAuthority,
    client_id: config.oidcClientId,
    redirect_uri: `${origin}${CALLBACK_PATH}`,
    post_logout_redirect_uri: `${origin}${LOGIN_PATH}`,
    silent_redirect_uri: `${origin}${CALLBACK_PATH}`,
    response_type: 'code',
    scope: 'openid profile email',
    automaticSilentRenew: true,
    accessTokenExpiringNotificationTimeInSeconds: 60,
    loadUserInfo: false,
    monitorSession: false,
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  });
}

export interface AuthUser {
  sub: string;
  username: string;
  name: string;
  email: string | null;
  roles: Role[];
  /** Site codes the user is limited to; empty = all sites. */
  sites: string[];
  groups: string[];
  accessToken: string;
  /** Epoch seconds. */
  expiresAt: number | null;
}

/** Build the app's user from an oidc-client-ts User; groups come from the ACCESS token (D20). */
export function toAuthUser(user: User): AuthUser {
  const access = decodeJwtPayload(user.access_token);
  const groups = stringArrayClaim(access, 'groups');
  const fallbackGroups = groups.length ? groups : stringArrayClaim(user.profile, 'groups');
  const profile = user.profile;
  const username = profile.preferred_username ?? profile.sub;
  return {
    sub: profile.sub,
    username,
    name: profile.name ?? ([profile.given_name, profile.family_name].filter(Boolean).join(' ') || username),
    email: profile.email ?? null,
    roles: rolesFromGroups(fallbackGroups),
    sites: sitesFromGroups(fallbackGroups),
    groups: fallbackGroups,
    accessToken: user.access_token,
    expiresAt: user.expires_at ?? null,
  };
}
