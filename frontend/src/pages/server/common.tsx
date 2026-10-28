import { useEffect, useRef } from 'react';

import { ApiError } from '@/api/errors';
import { QueryError } from '@/components/QueryState';

/** Synthetic 404 for ids that can't exist (e.g. `/servers/abc`): same screen as an API 404, no request. */
export const NOT_FOUND = new ApiError({ type: 'about:blank', title: 'Not found', status: 404 });

export function NotFoundState({ what }: { what: string }) {
  return <QueryError error={NOT_FOUND} what={what} />;
}

/**
 * Call `refetch` when `trigger` changes (a live push), at most once per `intervalMs`: a burst of pushes
 * becomes one refetch now and, if more arrive, one more when the interval has passed (trailing call).
 */
export function useThrottledRefetch(
  trigger: number | null | undefined,
  refetch: () => void,
  intervalMs = 10_000,
) {
  const last = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const seen = useRef(trigger);
  const refetchRef = useRef(refetch);
  refetchRef.current = refetch;

  useEffect(() => {
    if (trigger === null || trigger === undefined || trigger === seen.current) return;
    seen.current = trigger;
    if (timer.current) return; // a trailing refetch is already scheduled
    const wait = last.current + intervalMs - Date.now();
    const run = () => {
      timer.current = null;
      last.current = Date.now();
      refetchRef.current();
    };
    if (wait <= 0) run();
    else timer.current = setTimeout(run, wait);
  }, [trigger, intervalMs]);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
}

/** Order categories the way people scan a server: temperatures, cooling, power, then the rest A→Z. */
const CATEGORY_ORDER = ['thermal', 'cooling', 'power', 'processor', 'memory', 'storage', 'network', 'system'];

export function categoryRank(category: string): number {
  const i = CATEGORY_ORDER.indexOf(category.toLowerCase());
  return i === -1 ? CATEGORY_ORDER.length : i;
}

export function sortCategories(categories: Iterable<string>): string[] {
  return [...new Set(categories)].sort(
    (a, b) => categoryRank(a) - categoryRank(b) || a.localeCompare(b, 'en'),
  );
}

const CATEGORY_LABELS: Record<string, string> = {
  thermal: 'Thermal',
  cooling: 'Cooling',
  power: 'Power',
  processor: 'Processors',
  memory: 'Memory',
  storage: 'Storage',
  network: 'Network',
  system: 'System',
};

export function categoryLabel(category: string): string {
  const key = category.toLowerCase();
  return CATEGORY_LABELS[key] ?? (category ? category.charAt(0).toUpperCase() + category.slice(1) : 'Other');
}

/** Group items by a key, keeping first-seen order inside each group. */
export function groupBy<T>(items: readonly T[], key: (item: T) => string): Map<string, T[]> {
  const out = new Map<string, T[]>();
  for (const it of items) {
    const k = key(it);
    const list = out.get(k);
    if (list) list.push(it);
    else out.set(k, [it]);
  }
  return out;
}
