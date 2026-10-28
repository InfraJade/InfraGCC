import { useSyncExternalStore } from 'react';

function getMql(query: string): MediaQueryList | null {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null;
  return window.matchMedia(query);
}

/** Live boolean for a media query (false where matchMedia is unavailable). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mql = getMql(query);
      if (!mql) return () => undefined;
      mql.addEventListener('change', onChange);
      return () => mql.removeEventListener('change', onChange);
    },
    () => getMql(query)?.matches ?? false,
    () => false,
  );
}

export const usePrefersReducedMotion = () => useMediaQuery('(prefers-reduced-motion: reduce)');
export const usePrefersReducedTransparency = () => useMediaQuery('(prefers-reduced-transparency: reduce)');
