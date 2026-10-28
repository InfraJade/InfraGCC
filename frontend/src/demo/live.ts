/**
 * Demo-mode replacement for the live WebSocket: "connects" instantly and pushes fresh readings for every
 * subscribed server every few seconds, computed from the same sensor model as the demo API, so values on the
 * server page tick the way they do with real hardware.
 */
import type { LiveFeed, LiveMessage, LiveStatus } from '@/api/live';

import { demoLiveReadings } from './server';

const PUSH_INTERVAL_MS = 5_000;

export class DemoLiveClient implements LiveFeed {
  private _status: LiveStatus = 'idle';
  private timer: ReturnType<typeof setInterval> | null = null;
  private readonly servers = new Map<number, number>();
  private readonly messageListeners = new Set<(m: LiveMessage) => void>();
  private readonly statusListeners = new Set<(s: LiveStatus) => void>();

  get status(): LiveStatus {
    return this._status;
  }

  connect(): void {
    if (this.timer) return;
    this.setStatus('connecting');
    setTimeout(() => {
      if (this._status !== 'connecting') return;
      this.setStatus('open');
      this.push();
    }, 300);
    this.timer = setInterval(() => this.push(), PUSH_INTERVAL_MS);
  }

  close(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
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

  subscribe(target: { servers?: readonly number[]; sites?: readonly number[] }): () => void {
    const ids = [...new Set(target.servers ?? [])];
    for (const id of ids) this.servers.set(id, (this.servers.get(id) ?? 0) + 1);
    if (this._status === 'open' && ids.length) queueMicrotask(() => this.push(ids));
    let done = false;
    return () => {
      if (done) return;
      done = true;
      for (const id of ids) {
        const n = (this.servers.get(id) ?? 1) - 1;
        if (n <= 0) this.servers.delete(id);
        else this.servers.set(id, n);
      }
    };
  }

  async reauth(): Promise<void> {
    /* nothing to re-authenticate */
  }

  private push(ids: readonly number[] = [...this.servers.keys()]): void {
    if (this._status !== 'open') return;
    const now = Date.now();
    for (const id of ids) {
      const msg = demoLiveReadings(id, now);
      if (!msg) continue;
      const out: LiveMessage = { type: 'readings', ...msg };
      this.messageListeners.forEach((l) => l(out));
    }
  }

  private setStatus(s: LiveStatus): void {
    this._status = s;
    this.statusListeners.forEach((l) => l(s));
  }
}
