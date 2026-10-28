import { QueryClient } from '@tanstack/react-query';

import { backoffDelay, LiveClient, type LiveMessage } from '@/api/live';
import { applyLiveMessage, readingKey, type LiveServerState, type LiveSiteState } from '@/api/LiveProvider';
import { queryKeys } from '@/api/queryClient';

/** Minimal controllable WebSocket double. */
class MockSocket {
  static instances: MockSocket[] = [];
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  closedWith: number | null = null;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    MockSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(JSON.parse(data) as Record<string, unknown>);
  }
  close(code = 1000) {
    this.closedWith = code;
    this.readyState = 3;
  }
  // server-side helpers
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  receive(msg: unknown) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
  drop(code = 1006) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

const flush = () => new Promise<void>((r) => setTimeout(r, 0));
const latest = () => {
  const s = MockSocket.instances[MockSocket.instances.length - 1];
  if (!s) throw new Error('no socket');
  return s;
};

function makeClient(overrides: Partial<ConstructorParameters<typeof LiveClient>[0]> = {}) {
  let token = 'tok-1';
  const client = new LiveClient({
    url: 'ws://test/api/v1/live',
    getToken: () => Promise.resolve(token),
    renewToken: vi.fn(() => {
      token = 'tok-renewed';
      return Promise.resolve(token);
    }),
    WebSocketImpl: MockSocket as unknown as typeof WebSocket,
    random: () => 0,
    backoff: { initialMs: 1000, maxMs: 8000, factor: 2, jitter: 0.3 },
    ...overrides,
  });
  return client;
}

describe('LiveClient protocol', () => {
  beforeEach(() => {
    MockSocket.instances = [];
  });
  afterEach(() => vi.useRealTimers());

  it('sends auth as the first message, then subscribes after "ready"', async () => {
    const client = makeClient();
    const unsub = client.subscribe({ servers: [12], sites: [1] });
    client.connect();
    const ws = latest();
    expect(ws.url).toBe('ws://test/api/v1/live'); // no token in the URL
    expect(client.status).toBe('connecting');
    ws.open();
    await flush();
    expect(ws.sent[0]).toEqual({ type: 'auth', token: 'tok-1' });
    expect(ws.sent).toHaveLength(1);
    expect(client.status).toBe('authenticating');

    ws.receive({ type: 'ready', user: { sub: 'u1' } });
    expect(client.status).toBe('open');
    expect(ws.sent[1]).toEqual({ type: 'subscribe', servers: [12], sites: [1] });

    unsub();
    expect(ws.sent[2]).toEqual({ type: 'unsubscribe', servers: [12], sites: [1] });
    client.close();
  });

  it('reference-counts subscriptions and only sends changes', async () => {
    const client = makeClient();
    client.connect();
    const ws = latest();
    ws.open();
    await flush();
    ws.receive({ type: 'ready' });
    const a = client.subscribe({ servers: [5] });
    const b = client.subscribe({ servers: [5, 6] });
    expect(ws.sent.slice(1)).toEqual([
      { type: 'subscribe', servers: [5], sites: [] },
      { type: 'subscribe', servers: [6], sites: [] },
    ]);
    a();
    expect(ws.sent).toHaveLength(3); // server 5 still watched by b
    b();
    expect(ws.sent[3]).toEqual({ type: 'unsubscribe', servers: [5, 6], sites: [] });
    expect(client.subscriptions).toEqual({ servers: [], sites: [] });
  });

  it('delivers readings/health/alert messages and ignores pings', async () => {
    const client = makeClient();
    const got: LiveMessage[] = [];
    client.onMessage((m) => got.push(m));
    client.connect();
    const ws = latest();
    ws.open();
    await flush();
    ws.receive({ type: 'ready' });
    ws.receive({ type: 'ping' });
    ws.receive({ type: 'readings', server_id: 1, site_id: 1, readings: [] });
    ws.receive({
      type: 'alert',
      alert_id: 9,
      server_id: 1,
      site_id: 1,
      state: 'open',
      severity: 'Critical',
      title: 'x',
      change: 'opened',
    });
    expect(got.map((m) => m.type)).toEqual(['readings', 'alert']);
  });

  it('reconnects with exponential backoff and re-subscribes', async () => {
    vi.useFakeTimers();
    const client = makeClient();
    client.subscribe({ sites: [2] });
    client.connect();
    let ws = latest();
    ws.open();
    await vi.advanceTimersByTimeAsync(0);
    ws.receive({ type: 'ready' });

    ws.drop(1006);
    expect(client.status).toBe('reconnecting');
    expect(MockSocket.instances).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(999);
    expect(MockSocket.instances).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(MockSocket.instances).toHaveLength(2); // after 1 s

    // fails again before ready → next delay doubles (2 s)
    latest().drop(1006);
    await vi.advanceTimersByTimeAsync(1999);
    expect(MockSocket.instances).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(MockSocket.instances).toHaveLength(3);

    ws = latest();
    ws.open();
    await vi.advanceTimersByTimeAsync(0);
    expect(ws.sent[0]).toEqual({ type: 'auth', token: 'tok-1' });
    ws.receive({ type: 'ready' });
    expect(ws.sent[1]).toEqual({ type: 'subscribe', servers: [], sites: [2] });

    // backoff resets after a successful ready
    ws.drop(1006);
    await vi.advanceTimersByTimeAsync(1000);
    expect(MockSocket.instances).toHaveLength(4);
    client.close();
  });

  it('renews the token before reconnecting after an auth close', async () => {
    vi.useFakeTimers();
    const renewToken = vi.fn(() => Promise.resolve('tok-renewed'));
    let token = 'tok-old';
    const client = makeClient({
      getToken: () => Promise.resolve(token),
      renewToken: () => renewToken().then((t) => (token = t)),
    });
    client.connect();
    const ws = latest();
    ws.open();
    await vi.advanceTimersByTimeAsync(0);
    ws.drop(4401);
    await vi.advanceTimersByTimeAsync(1000);
    expect(renewToken).toHaveBeenCalledTimes(1);
    const ws2 = latest();
    expect(ws2).not.toBe(ws);
    ws2.open();
    await vi.advanceTimersByTimeAsync(0);
    expect(ws2.sent[0]).toEqual({ type: 'auth', token: 'tok-renewed' });
    client.close();
  });

  it('re-sends auth on the open socket after a token renew', async () => {
    const client = makeClient();
    client.connect();
    const ws = latest();
    ws.open();
    await flush();
    ws.receive({ type: 'ready' });
    await client.reauth('tok-fresh');
    expect(ws.sent[ws.sent.length - 1]).toEqual({ type: 'auth', token: 'tok-fresh' });
  });

  it('does not reconnect after close()', async () => {
    vi.useFakeTimers();
    const client = makeClient();
    client.connect();
    const ws = latest();
    ws.open();
    await vi.advanceTimersByTimeAsync(0);
    client.close();
    expect(ws.closedWith).toBe(1000);
    expect(client.status).toBe('closed');
    await vi.advanceTimersByTimeAsync(60_000);
    expect(MockSocket.instances).toHaveLength(1);
  });

  it('computes capped, jittered backoff', () => {
    const opts = { initialMs: 1000, maxMs: 30_000, factor: 2, jitter: 0.3 };
    expect(backoffDelay(0, opts, () => 0)).toBe(1000);
    expect(backoffDelay(3, opts, () => 0)).toBe(8000);
    expect(backoffDelay(10, opts, () => 0)).toBe(30_000);
    expect(backoffDelay(0, opts, () => 1)).toBe(700);
  });
});

describe('applyLiveMessage → query cache', () => {
  it('keeps the newest reading per metric/component and health per server and site', () => {
    const qc = new QueryClient();
    applyLiveMessage(qc, {
      type: 'readings',
      server_id: 3,
      site_id: 1,
      readings: [
        { metric: 'inlet_temp_c', component: '', value: 24, status: 'OK', time: '2026-10-22T10:01:00Z' },
        { metric: 'fan_rpm', component: 'Fan 1', value: 6100, status: 'OK', time: '2026-10-22T10:01:00Z' },
      ],
    });
    // an older, late-arriving value must not overwrite the newer one
    applyLiveMessage(qc, {
      type: 'readings',
      server_id: 3,
      site_id: 1,
      readings: [
        { metric: 'inlet_temp_c', component: '', value: 21, status: 'OK', time: '2026-10-22T10:00:00Z' },
      ],
    });
    applyLiveMessage(qc, {
      type: 'health',
      server_id: 3,
      site_id: 1,
      server_health: 'Warning',
      changes: [
        {
          metric: 'psu_health',
          component: 'PSU 1',
          health: 'Warning',
          state: 'Enabled',
          since: '2026-10-22T10:01:00Z',
        },
      ],
    });
    const server = qc.getQueryData<LiveServerState>(queryKeys.live.server(3));
    expect(server?.readings[readingKey('inlet_temp_c', '')]?.value).toBe(24);
    expect(server?.readings[readingKey('fan_rpm', 'Fan 1')]?.value).toBe(6100);
    expect(server?.serverHealth).toBe('Warning');
    expect(qc.getQueryData<LiveSiteState>(queryKeys.live.site(1))?.serverHealth[3]).toBe('Warning');
  });

  it('records alert changes (deduped by id) and invalidates alert queries', () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, 'invalidateQueries');
    const alert = {
      type: 'alert' as const,
      alert_id: 7,
      server_id: 3,
      site_id: 1,
      state: 'open',
      severity: 'Critical',
      title: 'Inlet hot',
      change: 'opened',
    };
    applyLiveMessage(qc, alert);
    applyLiveMessage(qc, { ...alert, state: 'acknowledged', change: 'acknowledged' });
    const recent = qc.getQueryData<LiveMessage[]>(queryKeys.live.alerts);
    expect(recent).toHaveLength(1);
    expect(recent?.[0]).toMatchObject({ state: 'acknowledged' });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['alerts'] });
  });
});
