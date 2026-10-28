import { createAuthFetch, createApi, unwrap } from '@/api/client';
import { ApiError, errorMessage, NetworkError, parseProblemResponse, toProblem } from '@/api/errors';

const problemJson = (status: number, body: Record<string, unknown>) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/problem+json' } });

describe('problem+json parsing', () => {
  it('parses RFC 9457 bodies into a typed ApiError', async () => {
    const err = await parseProblemResponse(
      problemJson(404, {
        type: 'https://gcc.example/problems/not-found',
        title: 'Not found',
        status: 404,
        detail: 'Server 99 does not exist.',
        instance: '/api/v1/servers/99',
        server_id: 99,
      }),
    );
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.isNotFound).toBe(true);
    expect(err.message).toBe('Server 99 does not exist.');
    expect(err.problem.instance).toBe('/api/v1/servers/99');
    expect(err.problem.server_id).toBe(99);
  });

  it('keeps validation errors and exposes them per field', async () => {
    const err = await parseProblemResponse(
      problemJson(422, {
        type: 'https://gcc.example/problems/validation-failed',
        title: 'Validation failed',
        status: 422,
        detail: 'The request did not pass validation.',
        errors: [
          { loc: ['body', 'position_u'], msg: 'Input should be greater than 0', type: 'greater_than' },
          { loc: ['body', 'rack_id'], msg: 'Field required', type: 'missing' },
        ],
      }),
    );
    expect(err.isValidation).toBe(true);
    expect(err.fieldErrors()).toEqual({
      position_u: 'Input should be greater than 0',
      rack_id: 'Field required',
    });
    expect(errorMessage(err)).toContain('position_u: Input should be greater than 0');
  });

  it('falls back to the HTTP status for non-JSON or empty bodies', async () => {
    const html = await parseProblemResponse(
      new Response('<html>Bad gateway</html>', { status: 502, headers: { 'Content-Type': 'text/html' } }),
    );
    expect(html.problem).toMatchObject({ type: 'about:blank', title: 'Bad gateway', status: 502 });
    const empty = await parseProblemResponse(new Response(null, { status: 503 }));
    expect(empty.problem.title).toBe('Service unavailable');
    expect(toProblem({ detail: [{ msg: 'x' }] }, 400).detail).toBeUndefined();
  });

  it('gives readable messages for any thrown value', () => {
    expect(errorMessage(new NetworkError())).toMatch(/could not be reached/);
    expect(errorMessage('boom')).toBe('boom');
    expect(errorMessage(42)).toBe('Something went wrong.');
  });
});

describe('authenticated fetch', () => {
  it('adds the bearer token', async () => {
    const base = vi.fn((req: Request | string | URL) => {
      const r = req as Request;
      return Promise.resolve(new Response(r.headers.get('Authorization'), { status: 200 }));
    });
    const f = createAuthFetch({ getAccessToken: async () => 'tok-1', renew: async () => null }, base);
    const res = await f(new Request('http://x/api/v1/sites'));
    expect(await res.text()).toBe('Bearer tok-1');
  });

  it('renews once on 401 and retries the request with the new token and body', async () => {
    const seen: { auth: string | null; body: string }[] = [];
    const base = vi.fn(async (req: Request | string | URL) => {
      const r = req as Request;
      seen.push({ auth: r.headers.get('Authorization'), body: await r.text() });
      return new Response(null, { status: seen.length === 1 ? 401 : 200 });
    });
    const renew = vi.fn(async () => 'tok-2');
    const f = createAuthFetch({ getAccessToken: async () => 'tok-1', renew }, base);
    const res = await f(
      new Request('http://x/api/v1/alerts/1/ack', { method: 'POST', body: '{"note":"on it"}' }),
    );
    expect(res.status).toBe(200);
    expect(renew).toHaveBeenCalledTimes(1);
    expect(seen).toEqual([
      { auth: 'Bearer tok-1', body: '{"note":"on it"}' },
      { auth: 'Bearer tok-2', body: '{"note":"on it"}' },
    ]);
  });

  it('gives up after one retry and reports the lost session', async () => {
    const base = vi.fn(async () => new Response(null, { status: 401 }));
    const onUnauthorized = vi.fn();
    const f = createAuthFetch(
      { getAccessToken: async () => 't', renew: async () => 't2', onUnauthorized },
      base,
    );
    const res = await f(new Request('http://x/api/v1/sites'));
    expect(res.status).toBe(401);
    expect(base).toHaveBeenCalledTimes(2);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it('does not retry when renew fails', async () => {
    const base = vi.fn(async () => new Response(null, { status: 401 }));
    const onUnauthorized = vi.fn();
    const f = createAuthFetch(
      { getAccessToken: async () => 't', renew: async () => null, onUnauthorized },
      base,
    );
    await f(new Request('http://x/api/v1/sites'));
    expect(base).toHaveBeenCalledTimes(1);
    expect(onUnauthorized).toHaveBeenCalled();
  });

  it('turns transport failures into NetworkError', async () => {
    const base = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    const f = createAuthFetch({ getAccessToken: async () => null, renew: async () => null }, base);
    await expect(f(new Request('http://x/api'))).rejects.toBeInstanceOf(NetworkError);
  });
});

describe('createApi', () => {
  it('json() sends query params and throws ApiError from problem+json', async () => {
    const base = vi.fn(async (req: Request | string | URL) => {
      const r = req as Request;
      if (r.url.includes('/search'))
        return new Response(JSON.stringify([{ id: 1 }]), { headers: { 'Content-Type': 'application/json' } });
      return problemJson(403, {
        type: 't',
        title: 'Forbidden',
        status: 403,
        detail: 'Site HYD1 is outside your scope.',
      });
    });
    const api = createApi(
      { getAccessToken: async () => 't', renew: async () => null },
      { baseUrl: 'http://api.test', baseFetch: base },
    );
    await expect(
      api.json('/api/v1/search', { query: { q: 'srv 1', limit: 8, skip: undefined } }),
    ).resolves.toEqual([{ id: 1 }]);
    expect((base.mock.calls[0]?.[0] as Request).url).toBe('http://api.test/api/v1/search?q=srv+1&limit=8');
    await expect(api.json('/api/v1/sites/2')).rejects.toMatchObject({
      status: 403,
      message: 'Site HYD1 is outside your scope.',
    });
  });

  it('unwrap() returns data or throws ApiError', async () => {
    await expect(unwrap({ data: { ok: 1 }, response: new Response(null, { status: 200 }) })).resolves.toEqual(
      { ok: 1 },
    );
    await expect(
      unwrap({
        error: { title: 'Conflict', status: 409, type: 'x', detail: 'Position taken' },
        response: new Response(null, { status: 409 }),
      }),
    ).rejects.toMatchObject({ status: 409, message: 'Position taken' });
  });
});
