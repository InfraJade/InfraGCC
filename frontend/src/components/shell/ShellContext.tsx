import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

import { readJson, writeJson } from '@/lib/storage';

export interface SiteOption {
  id: number;
  code: string;
  name: string;
  health?: string | null;
}

export interface SearchResult {
  id: string;
  /** site | room | rack | server | component | alert | … */
  kind: string;
  label: string;
  sublabel?: string;
  to: string;
  health?: string | null;
}

/** Fetch results for the global search box. Wired to `GET /api/v1/search?q=` by the app. */
export type SearchSource = (q: string, signal: AbortSignal) => Promise<SearchResult[]>;

export interface ShellData {
  sites: SiteOption[];
  search: SearchSource | null;
  /** Open alerts for the bell; null = unknown (not loaded). */
  openAlerts: { count: number; critical: number } | null;
}

interface ShellContextValue extends ShellData {
  /** Selected site ids for the global site filter; empty = all sites. */
  siteFilter: number[];
  setSiteFilter: (ids: number[]) => void;
}

const ShellContext = createContext<ShellContextValue | null>(null);

const FILTER_KEY = 'gcc.siteFilter';
const isNumArray = (v: unknown): v is number[] => Array.isArray(v) && v.every((x) => typeof x === 'number');

export function ShellProvider({ children, data }: { children: ReactNode; data: ShellData }) {
  const [siteFilter, setFilterState] = useState<number[]>(() => readJson(FILTER_KEY, [], isNumArray));
  const setSiteFilter = useCallback((ids: number[]) => {
    setFilterState(ids);
    writeJson(FILTER_KEY, ids);
  }, []);
  const value = useMemo(() => ({ ...data, siteFilter, setSiteFilter }), [data, siteFilter, setSiteFilter]);
  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}

const EMPTY: ShellContextValue = {
  sites: [],
  search: null,
  openAlerts: null,
  siteFilter: [],
  setSiteFilter: () => undefined,
};

export function useShell(): ShellContextValue {
  return useContext(ShellContext) ?? EMPTY;
}

/** The global site filter, resolved against the known sites (empty = all). */
export function useSiteFilter(): {
  siteIds: number[];
  setSiteIds: (ids: number[]) => void;
  sites: SiteOption[];
} {
  const { siteFilter, setSiteFilter, sites } = useShell();
  const known = new Set(sites.map((s) => s.id));
  const siteIds = sites.length ? siteFilter.filter((id) => known.has(id)) : siteFilter;
  return { siteIds, setSiteIds: setSiteFilter, sites };
}
