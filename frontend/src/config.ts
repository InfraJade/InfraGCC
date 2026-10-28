/**
 * Runtime configuration.
 *
 * One image works anywhere: the container writes `/config.js` at start-up, which sets
 * `window.__GCC_CONFIG__`. Missing or empty values fall back to Vite build-time env (`VITE_*`) and then to
 * the local dev defaults.
 */

export interface RuntimeConfig {
  oidcAuthority: string;
  oidcClientId: string;
  supersetUrl: string;
  /** Base URL of the app API. Empty string = same origin (nginx / Vite proxy `/api`). */
  apiBase: string;
}

declare global {
  interface Window {
    __GCC_CONFIG__?: Partial<Record<keyof RuntimeConfig, string>>;
  }
}

function pick(...values: (string | undefined)[]): string | undefined {
  for (const v of values) {
    if (typeof v === 'string' && v.trim() !== '') return v.trim();
  }
  return undefined;
}

export function loadConfig(): RuntimeConfig {
  const runtime = (typeof window !== 'undefined' ? window.__GCC_CONFIG__ : undefined) ?? {};
  const env = import.meta.env;
  return {
    oidcAuthority: pick(runtime.oidcAuthority, env.VITE_OIDC_AUTHORITY) ?? 'http://localhost:8080/realms/gcc',
    oidcClientId: pick(runtime.oidcClientId, env.VITE_OIDC_CLIENT_ID) ?? 'gcc-web',
    supersetUrl: pick(runtime.supersetUrl, env.VITE_SUPERSET_URL) ?? 'http://localhost:8090',
    apiBase: (pick(runtime.apiBase, env.VITE_API_BASE) ?? '').replace(/\/+$/, ''),
  };
}

let cached: RuntimeConfig | undefined;

export function getConfig(): RuntimeConfig {
  cached ??= loadConfig();
  return cached;
}

/** WebSocket URL for `/api/v1/live`, derived from the API base (or the page origin). */
export function liveUrl(config: RuntimeConfig = getConfig()): string {
  const base = config.apiBase || window.location.origin;
  return `${base.replace(/^http/, 'ws')}/api/v1/live`;
}
