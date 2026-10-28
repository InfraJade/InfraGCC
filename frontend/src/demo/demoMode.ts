/**
 * Demo mode: when on, every API call and the live feed are answered in the browser from a generated sample
 * data set (`src/demo/`) instead of the backend. Per browser (localStorage), so it never affects other users.
 * Sign-in still goes through SSO: roles and site limits are the real user's, only the data is fake.
 */
import { useSyncExternalStore } from 'react';

import { readJson, writeJson } from '@/lib/storage';

const KEY = 'gcc.demoMode';
const listeners = new Set<() => void>();

let enabled = readJson(KEY, false, (v): v is boolean => typeof v === 'boolean');

export function isDemoMode(): boolean {
  return enabled;
}

export function setDemoMode(on: boolean): void {
  if (on === enabled) return;
  enabled = on;
  writeJson(KEY, on);
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// Another tab flipped the switch: follow it.
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key !== KEY) return;
    const next = readJson(KEY, false, (v): v is boolean => typeof v === 'boolean');
    if (next !== enabled) {
      enabled = next;
      listeners.forEach((l) => l());
    }
  });
}

export function useDemoMode(): boolean {
  return useSyncExternalStore(subscribe, isDemoMode, () => false);
}
