import '@testing-library/jest-dom/vitest';

import { cleanup, configure } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// findBy*/waitFor default to 1 s, which a loaded machine (or CI runner) can exceed for lazy pages + queries.
configure({ asyncUtilTimeout: 5000 });

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

// jsdom lacks these browser APIs.
if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (!('ResizeObserver' in window)) {
  Object.defineProperty(window, 'ResizeObserver', { writable: true, value: ResizeObserverStub });
  Object.defineProperty(globalThis, 'ResizeObserver', { writable: true, value: ResizeObserverStub });
}

if (!('CSS' in window) || typeof CSS.escape !== 'function') {
  Object.defineProperty(window, 'CSS', {
    writable: true,
    value: { escape: (s: string) => s.replace(/["\\]/g, '\\$&') },
  });
}

// jsdom's AbortSignal is not the class Node's Request (undici) accepts, so `new Request(url, { signal })` with
// TanStack Query's signal throws in tests (browsers are fine). Tests don't need aborts: drop the signal.
const NativeRequest = globalThis.Request;
class TestRequest extends NativeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    if (init && 'signal' in init) {
      const rest: RequestInit = { ...init };
      delete rest.signal;
      super(input, rest);
    } else {
      super(input, init);
    }
  }
}
Object.defineProperty(globalThis, 'Request', { writable: true, value: TestRequest });
