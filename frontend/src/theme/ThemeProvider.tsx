import { MotionConfig } from 'framer-motion';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { readJson, writeJson } from '@/lib/storage';
import { usePrefersReducedMotion, usePrefersReducedTransparency } from '@/lib/useMediaQuery';

import type { ThemeName } from './tokens';

export interface ThemePrefs {
  theme: ThemeName;
  /** Manual "reduce transparency" setting; the OS preference applies on top of it. */
  reduceTransparency: boolean;
}

export const DEFAULT_PREFS: ThemePrefs = { theme: 'dark', reduceTransparency: false };

export function prefsKey(userKey: string): string {
  return `gcc.prefs.${userKey}`;
}

function isPrefs(v: unknown): v is ThemePrefs {
  if (typeof v !== 'object' || v === null) return false;
  const o = v as Record<string, unknown>;
  return (o.theme === 'dark' || o.theme === 'light') && typeof o.reduceTransparency === 'boolean';
}

/** A user's saved prefs; a user without saved prefs inherits what was chosen before sign-in. */
export function readPrefs(userKey: string): ThemePrefs {
  const anonymous = readJson(prefsKey('anonymous'), DEFAULT_PREFS, isPrefs);
  return userKey === 'anonymous' ? anonymous : readJson(prefsKey(userKey), anonymous, isPrefs);
}

export interface ThemeContextValue {
  theme: ThemeName;
  setTheme: (t: ThemeName) => void;
  toggleTheme: () => void;
  /** Manual setting. */
  reduceTransparency: boolean;
  setReduceTransparency: (v: boolean) => void;
  /** Effective: manual setting OR the OS preference. */
  transparencyReduced: boolean;
  reducedMotion: boolean;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);
const ThemeScopeContext = createContext<ThemeName | null>(null);

interface ThemeProviderProps {
  /** Preferences are stored per signed-in user (`sub`), or under "anonymous" before sign-in. */
  userKey?: string;
  children: ReactNode;
}

export function ThemeProvider({ userKey = 'anonymous', children }: ThemeProviderProps) {
  const [prefs, setPrefs] = useState<ThemePrefs>(() => readPrefs(userKey));
  const [loadedFor, setLoadedFor] = useState(userKey);
  const systemReducedMotion = usePrefersReducedMotion();
  const systemReducedTransparency = usePrefersReducedTransparency();

  // A different user signed in: load their preferences (render-phase update, no flash).
  if (loadedFor !== userKey) {
    setLoadedFor(userKey);
    setPrefs(readPrefs(userKey));
  }

  const update = useCallback(
    (patch: Partial<ThemePrefs>) => {
      setPrefs((prev) => {
        const next = { ...prev, ...patch };
        writeJson(prefsKey(userKey), next);
        return next;
      });
    },
    [userKey],
  );

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = prefs.theme;
    if (prefs.reduceTransparency) root.dataset.transparency = 'reduced';
    else delete root.dataset.transparency;
  }, [prefs]);

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme: prefs.theme,
      setTheme: (theme) => update({ theme }),
      toggleTheme: () => update({ theme: prefs.theme === 'dark' ? 'light' : 'dark' }),
      reduceTransparency: prefs.reduceTransparency,
      setReduceTransparency: (reduceTransparency) => update({ reduceTransparency }),
      transparencyReduced: prefs.reduceTransparency || systemReducedTransparency,
      reducedMotion: systemReducedMotion,
    }),
    [prefs, update, systemReducedMotion, systemReducedTransparency],
  );

  return (
    <ThemeContext.Provider value={value}>
      <MotionConfig reducedMotion="user">{children}</MotionConfig>
    </ThemeContext.Provider>
  );
}

const FALLBACK: ThemeContextValue = {
  theme: 'dark',
  setTheme: () => undefined,
  toggleTheme: () => undefined,
  reduceTransparency: false,
  setReduceTransparency: () => undefined,
  transparencyReduced: false,
  reducedMotion: false,
};

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext) ?? FALLBACK;
}

/** The theme that applies at this point of the tree (a nested ThemeScope wins over the global theme). */
export function useResolvedTheme(): ThemeName {
  const scope = useContext(ThemeScopeContext);
  const { theme } = useTheme();
  return scope ?? theme;
}

/** Renders children in a fixed theme regardless of the global one (CSS variables + JS consumers). */
export function ThemeScope({
  theme,
  className,
  children,
}: {
  theme: ThemeName;
  className?: string;
  children: ReactNode;
}) {
  return (
    <ThemeScopeContext.Provider value={theme}>
      <div data-theme={theme} className={className}>
        {children}
      </div>
    </ThemeScopeContext.Provider>
  );
}
