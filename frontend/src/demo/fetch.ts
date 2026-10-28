/**
 * A `fetch` replacement for demo mode: requests to `/api/v1/*` are answered by the in-browser demo backend
 * (`server.ts`) with real `Response` objects (JSON, CSV or RFC 9457 problem+json), after a short random delay
 * so loading states look natural. Nothing leaves the browser.
 */
import type { AuthUser } from '@/auth/oidc';

import { DemoHttpError, handleDemoRequest, type DemoUser } from './server';

const API_PREFIX = '/api/v1';

function delay(ms: number, signal?: AbortSignal | null): Promise<void> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(t);
      reject(new DOMException('Aborted', 'AbortError'));
    });
  });
}

function problem(status: number, title: string, detail?: string, errors?: unknown): Response {
  return new Response(
    JSON.stringify({ type: 'about:blank', title, status, detail, ...(errors ? { errors } : {}) }),
    {
      status,
      headers: { 'Content-Type': 'application/problem+json' },
    },
  );
}

export function createDemoFetch(
  getUser: () => DemoUser | null,
  latencyMs: [number, number] = [80, 260],
): typeof fetch {
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(input, init);
    const url = new URL(req.url, window.location.origin);
    const at = url.pathname.indexOf(API_PREFIX);
    if (at < 0) return problem(404, 'Not Found', 'Demo mode only serves the app API.');
    const path = url.pathname.slice(at + API_PREFIX.length) || '/';

    let body: unknown;
    if (req.method !== 'GET' && req.method !== 'HEAD') {
      const text = await req.text();
      if (text) {
        try {
          body = JSON.parse(text);
        } catch {
          return problem(400, 'Bad Request', 'The request body is not valid JSON.');
        }
      }
    }
    await delay(latencyMs[0] + Math.random() * (latencyMs[1] - latencyMs[0]), init?.signal ?? req.signal);

    try {
      const res = handleDemoRequest(req.method, path, url.searchParams, body, getUser());
      if (res.status === 204 || res.body === undefined)
        return new Response(null, { status: res.status === 200 ? 204 : res.status });
      const contentType = res.contentType ?? 'application/json';
      const payload =
        contentType.startsWith('application/json') || typeof res.body !== 'string'
          ? JSON.stringify(res.body)
          : res.body;
      return new Response(payload, {
        status: res.status,
        headers: { 'Content-Type': contentType, ...res.headers },
      });
    } catch (e) {
      if (e instanceof DemoHttpError) return problem(e.status, e.title, e.detail, e.errors);
      if (import.meta.env.DEV) console.error('[demo]', e);
      return problem(500, 'Internal Server Error', 'The demo data could not answer this request.');
    }
  };
}

/** The signed-in user as the demo backend sees them (same roles and site limits as in SSO). */
export function demoUserFrom(user: AuthUser | null): DemoUser | null {
  if (!user) return null;
  return {
    sub: user.sub,
    username: user.username,
    name: user.name,
    email: user.email,
    roles: user.roles,
    sites: user.sites,
    expiresAt: user.expiresAt,
  };
}
