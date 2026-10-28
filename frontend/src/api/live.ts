/**
 * Client for the live WebSocket `/api/v1/live` (DECISIONS D23, contract in the build brief):
 *
 *   client → {"type":"auth","token":"<access token>"}            first message (server deadline 5 s)
 *   server → {"type":"ready","user":{...}}
 *   client → {"type":"subscribe","servers":[ids],"sites":[ids]}   / "unsubscribe" with the same shape
 *   server → readings | health | alert messages (app.core.live), {"type":"ping"} every 25 s
 *   client → {"type":"auth","token":...} again after a token renew
 *
 * Subscriptions are reference-counted (several components can watch the same server) and replayed after
 * every (re)connect. Reconnects use exponential backoff with jitter; an auth-related close renews the token
 * before reconnecting.
 */

export interface LiveReading {
  metric: string;
  component: string;
  value: number | null;
  status: string | null;
  time: string;
}

export interface ReadingsMessage {
  type: 'readings';
  server_id: number;
  site_id: number;
  readings: LiveReading[];
}

export interface HealthChange {
  metric: string;
  component: string;
  health: string;
  state: string | null;
  since: string;
}

export interface HealthMessage {
  type: 'health';
  server_id: number;
  site_id: number;
  changes: HealthChange[];
  /** Worst health across the server after this change. */
  server_health: string;
}

export interface AlertMessage {
  type: 'alert';
  alert_id: number;
  server_id: number | null;
  site_id: number | null;
  state: string;
  severity: string;
  title: string;
  /** opened | updated | acknowledged | resolved | escalated */
  change: string;
}

export type LiveMessage = ReadingsMessage | HealthMessage | AlertMessage;

interface ReadyMessage {
  type: 'ready';
  user?: Record<string, unknown>;
}

export type LiveStatus = 'idle' | 'connecting' | 'authenticating' | 'open' | 'reconnecting' | 'closed';

export interface BackoffOptions {
  initialMs: number;
  maxMs: number;
  factor: number;
  /** 0..1 — fraction of the delay randomly removed. */
  jitter: number;
}

export interface LiveClientOptions {
  url: string | (() => string);
  getToken: () => Promise<string | null>;
  /** Called before reconnecting after an auth-related close. */
  renewToken?: () => Promise<string | null>;
  WebSocketImpl?: typeof WebSocket;
  backoff?: Partial<BackoffOptions>;
  random?: () => number;
  /** Reconnect if "ready" doesn't arrive in time (ms). */
  readyTimeoutMs?: number;
  /** Reconnect if nothing (not even a ping) arrives for this long (ms). Server pings every 25 s. */
  idleTimeoutMs?: number;
  onError?: (error: unknown) => void;
}

/** Close codes that mean "your token was rejected". */
const AUTH_CLOSE_CODES = new Set([1008, 4001, 4003, 4401, 4403]);

export const DEFAULT_BACKOFF: BackoffOptions = { initialMs: 1000, maxMs: 30_000, factor: 2, jitter: 0.3 };

export function backoffDelay(
  attempt: number,
  opts: BackoffOptions = DEFAULT_BACKOFF,
  random: () => number = Math.random,
): number {
  const base = Math.min(opts.maxMs, opts.initialMs * opts.factor ** attempt);
  return Math.round(base * (1 - opts.jitter * random()));
}

function isLiveMessage(m: { type?: unknown }): m is LiveMessage {
  return m.type === 'readings' || m.type === 'health' || m.type === 'alert';
}

/** What screens need from a live connection (the WebSocket client, or the demo-mode feed). */
export interface LiveFeed {
  readonly status: LiveStatus;
  connect(): void;
  close(): void;
  onMessage(listener: (m: LiveMessage) => void): () => void;
  onStatus(listener: (s: LiveStatus) => void): () => void;
  subscribe(target: { servers?: readonly number[]; sites?: readonly number[] }): () => void;
  reauth(token?: string | null): Promise<void>;
}

export class LiveClient implements LiveFeed {
  private readonly opts: LiveClientOptions;
  private readonly backoff: BackoffOptions;
  private ws: WebSocket | null = null;
  private _status: LiveStatus = 'idle';
  private attempts = 0;
  private stopped = true;
  private needsRenew = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private readyTimer: ReturnType<typeof setTimeout> | null = null;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly serverRefs = new Map<number, number>();
  private readonly siteRefs = new Map<number, number>();
  private readonly messageListeners = new Set<(m: LiveMessage) => void>();
  private readonly statusListeners = new Set<(s: LiveStatus) => void>();

  constructor(opts: LiveClientOptions) {
    this.opts = opts;
    this.backoff = { ...DEFAULT_BACKOFF, ...opts.backoff };
  }

  get status(): LiveStatus {
    return this._status;
  }

  /** Currently subscribed ids (for tests/debugging). */
  get subscriptions(): { servers: number[]; sites: number[] } {
    return { servers: [...this.serverRefs.keys()], sites: [...this.siteRefs.keys()] };
  }

  connect(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.attempts = 0;
    this.open();
  }

  close(): void {
    this.stopped = true;
    this.clearTimers();
    const ws = this.ws;
    this.ws = null;
    if (ws && ws.readyState <= 1) ws.close(1000, 'client closing');
    this.setStatus('closed');
  }

  onMessage(listener: (m: LiveMessage) => void): () => void {
    this.messageListeners.add(listener);
    return () => this.messageListeners.delete(listener);
  }

  onStatus(listener: (s: LiveStatus) => void): () => void {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  }

  /** Watch servers/sites; returns the matching unsubscribe. */
  subscribe(target: { servers?: readonly number[]; sites?: readonly number[] }): () => void {
    const servers = [...new Set(target.servers ?? [])];
    const sites = [...new Set(target.sites ?? [])];
    const newServers = servers.filter((id) => inc(this.serverRefs, id) === 1);
    const newSites = sites.filter((id) => inc(this.siteRefs, id) === 1);
    if (this._status === 'open' && (newServers.length || newSites.length)) {
      this.send({ type: 'subscribe', servers: newServers, sites: newSites });
    }
    let done = false;
    return () => {
      if (done) return;
      done = true;
      const goneServers = servers.filter((id) => dec(this.serverRefs, id) === 0);
      const goneSites = sites.filter((id) => dec(this.siteRefs, id) === 0);
      if (this._status === 'open' && (goneServers.length || goneSites.length)) {
        this.send({ type: 'unsubscribe', servers: goneServers, sites: goneSites });
      }
    };
  }

  /** Re-authenticate the open socket with a refreshed token (after silent renew). */
  async reauth(token?: string | null): Promise<void> {
    const ws = this.ws;
    if (!ws || ws.readyState !== 1) return;
    const t = token ?? (await this.opts.getToken());
    if (t && ws === this.ws) this.send({ type: 'auth', token: t });
  }

  private open(): void {
    if (this.stopped) return;
    this.setStatus(this.attempts > 0 ? 'reconnecting' : 'connecting');
    const Impl = this.opts.WebSocketImpl ?? WebSocket;
    const url = typeof this.opts.url === 'function' ? this.opts.url() : this.opts.url;
    let ws: WebSocket;
    try {
      ws = new Impl(url);
    } catch (e) {
      this.opts.onError?.(e);
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      if (ws !== this.ws) return;
      this.setStatus('authenticating');
      void this.opts
        .getToken()
        .then((token) => {
          if (ws !== this.ws) return;
          if (!token) {
            this.needsRenew = true;
            ws.close(4001, 'no token');
            return;
          }
          // The token is ALWAYS the first message (never in the URL: D23).
          ws.send(JSON.stringify({ type: 'auth', token }));
          this.armReadyTimer(ws);
        })
        .catch((e: unknown) => {
          this.opts.onError?.(e);
          ws.close(4001, 'token error');
        });
    };

    ws.onmessage = (ev: MessageEvent) => {
      if (ws !== this.ws) return;
      this.armIdleTimer(ws);
      let msg: { type?: unknown };
      try {
        msg = JSON.parse(String(ev.data)) as { type?: unknown };
      } catch {
        return;
      }
      if (msg.type === 'ready') {
        this.onReady(msg as ReadyMessage);
      } else if (msg.type === 'ping') {
        // keep-alive only
      } else if (isLiveMessage(msg)) {
        this.messageListeners.forEach((l) => l(msg));
      } else if (msg.type === 'error') {
        this.opts.onError?.(msg);
      }
    };

    ws.onerror = () => {
      /* a close event always follows */
    };

    ws.onclose = (ev: CloseEvent) => {
      if (ws !== this.ws) return;
      this.ws = null;
      this.clearTimers();
      if (this.stopped) {
        this.setStatus('closed');
        return;
      }
      if (AUTH_CLOSE_CODES.has(ev.code)) this.needsRenew = true;
      this.scheduleReconnect();
    };
  }

  private onReady(_msg: ReadyMessage): void {
    if (this.readyTimer) clearTimeout(this.readyTimer);
    this.readyTimer = null;
    this.attempts = 0;
    this.needsRenew = false;
    this.setStatus('open');
    const servers = [...this.serverRefs.keys()];
    const sites = [...this.siteRefs.keys()];
    if (servers.length || sites.length) this.send({ type: 'subscribe', servers, sites });
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    const delay = backoffDelay(this.attempts, this.backoff, this.opts.random);
    this.attempts += 1;
    this.setStatus('reconnecting');
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      const go = () => this.open();
      if (this.needsRenew && this.opts.renewToken) {
        void this.opts.renewToken().then(go, go);
      } else {
        go();
      }
    }, delay);
  }

  private armReadyTimer(ws: WebSocket): void {
    if (this.readyTimer) clearTimeout(this.readyTimer);
    this.readyTimer = setTimeout(() => {
      if (ws === this.ws && this._status !== 'open') ws.close(4000, 'ready timeout');
    }, this.opts.readyTimeoutMs ?? 10_000);
  }

  private armIdleTimer(ws: WebSocket): void {
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(() => {
      if (ws === this.ws) ws.close(4000, 'idle timeout');
    }, this.opts.idleTimeoutMs ?? 60_000);
  }

  private clearTimers(): void {
    for (const t of [this.reconnectTimer, this.readyTimer, this.idleTimer]) if (t) clearTimeout(t);
    this.reconnectTimer = this.readyTimer = this.idleTimer = null;
  }

  private send(payload: Record<string, unknown>): void {
    if (this.ws?.readyState === 1) this.ws.send(JSON.stringify(payload));
  }

  private setStatus(s: LiveStatus): void {
    if (s === this._status) return;
    this._status = s;
    this.statusListeners.forEach((l) => l(s));
  }
}

function inc(map: Map<number, number>, id: number): number {
  const n = (map.get(id) ?? 0) + 1;
  map.set(id, n);
  return n;
}

function dec(map: Map<number, number>, id: number): number {
  const n = (map.get(id) ?? 0) - 1;
  if (n <= 0) map.delete(id);
  else map.set(id, n);
  return Math.max(0, n);
}
