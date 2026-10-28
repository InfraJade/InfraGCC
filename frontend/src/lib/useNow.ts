import { useSyncExternalStore } from 'react';

/**
 * Shared clocks: one timer per interval for the whole app, however many components read it
 * (a table of 500 readings re-renders from one interval, not 500).
 */
interface Clock {
  now: number;
  listeners: Set<() => void>;
  timer: ReturnType<typeof setInterval> | null;
  /** Stable subscribe function: a new one per render would make React resubscribe every render. */
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => number;
}

const clocks = new Map<number, Clock>();

function clock(intervalMs: number): Clock {
  const existing = clocks.get(intervalMs);
  if (existing) return existing;
  const c: Clock = {
    now: Date.now(),
    listeners: new Set(),
    timer: null,
    subscribe: (listener) => {
      c.listeners.add(listener);
      if (c.timer === null) {
        c.timer = setInterval(() => {
          c.now = Date.now();
          c.listeners.forEach((l) => l());
        }, intervalMs);
      }
      return () => {
        c.listeners.delete(listener);
        if (c.listeners.size === 0 && c.timer !== null) {
          clearInterval(c.timer);
          c.timer = null;
        }
      };
    },
    // Repeated calls must return the same value. While no timer runs, the cached time is refreshed
    // only once it is a full interval old, so a newly mounted reader never shows a stale clock.
    getSnapshot: () => {
      if (c.timer === null && Date.now() - c.now >= intervalMs) c.now = Date.now();
      return c.now;
    },
  };
  clocks.set(intervalMs, c);
  return c;
}

/** Current time in ms, re-rendering every `intervalMs`. */
export function useNow(intervalMs = 1000): number {
  const c = clock(intervalMs);
  return useSyncExternalStore(c.subscribe, c.getSnapshot, c.getSnapshot);
}
