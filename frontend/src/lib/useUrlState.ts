import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

export type UrlValue = string | number | boolean | null | undefined;

/**
 * Filters kept in the URL query string (shareable, survive reload, back button works).
 *
 *   const [f, setF] = useUrlState({ q: '', health: '', site_id: '' });
 *   setF({ health: 'Critical' });   // merges; empty/null values are removed from the URL
 *
 * Values are strings; use `numberParam(f.site_id)` for ids.
 */
export function useUrlState<K extends string>(
  defaults: Record<K, string>,
): [Record<K, string>, (patch: Partial<Record<K, UrlValue>>) => void] {
  const [params, setParams] = useSearchParams();
  const defaultsKey = JSON.stringify(defaults);

  const values = useMemo(() => {
    const d = JSON.parse(defaultsKey) as Record<K, string>;
    const out = { ...d };
    for (const k of Object.keys(d) as K[]) {
      const v = params.get(k);
      if (v !== null) out[k] = v;
    }
    return out;
  }, [params, defaultsKey]);

  const set = useCallback(
    (patch: Partial<Record<K, UrlValue>>) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch) as [K, UrlValue][]) {
            if (v === null || v === undefined || v === '' || v === false) next.delete(k);
            else next.set(k, String(v));
          }
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );
  return [values, set];
}

/** "12" → 12, "" / "abc" → undefined. */
export function numberParam(v: string | null | undefined): number | undefined {
  if (v === null || v === undefined || v.trim() === '') return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

/** Route param → positive integer id, or null. */
export function idParam(v: string | undefined): number | null {
  const n = numberParam(v);
  return n !== undefined && Number.isInteger(n) && n > 0 ? n : null;
}
