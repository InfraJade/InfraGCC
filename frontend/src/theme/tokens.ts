/**
 * Design tokens — the ONE source of truth for the look of the app.
 *
 * Everything visual derives from this file:
 *   - `cssVars.ts` turns the semantic theme colors into CSS custom properties (dark + light);
 *   - `tailwind.config.ts` builds the Tailwind theme from these tokens (colors point at the CSS variables);
 *   - charts (ECharts) read `chartPalette`, `themes` and `health` directly.
 *
 * Plain data only (no DOM, no imports) so it can be loaded by Tailwind's config loader too.
 */

/** Jade-green brand scale. 500 is the brand jade. */
export const brand = {
  50: '#e8fbf3',
  100: '#c9f5e2',
  200: '#96ebc7',
  300: '#5cdca8',
  400: '#2bc98c',
  500: '#0faf76',
  600: '#078e61',
  700: '#08714f',
  800: '#0b5a41',
  900: '#0b4a37',
  950: '#03291f',
} as const;

/** Cool neutral scale used by both themes. */
export const neutral = {
  0: '#ffffff',
  50: '#f6f8fa',
  100: '#edf1f4',
  200: '#dce3e9',
  300: '#c1cbd4',
  400: '#94a3b1',
  500: '#6b7a89',
  600: '#4f5d6b',
  700: '#3a4652',
  800: '#26303a',
  850: '#1b232c',
  900: '#121920',
  950: '#0a0f14',
} as const;

export type ThemeName = 'dark' | 'light';

/** Semantic colors per theme. Every key becomes a CSS variable `--c-<kebab-key>` and a Tailwind color. */
export interface ThemeColors {
  /** Page canvas behind the glass. */
  canvas: string;
  /** Soft background glows painted on the canvas (top-left / bottom-right). */
  glowA: string;
  glowB: string;
  /** Tint of glass surfaces (mixed with `glass.alpha.*`). */
  glass: string;
  /** Solid surfaces: used when transparency is reduced, and for menus/dialogs. */
  surface: string;
  surfaceRaised: string;
  surfaceSunken: string;
  /** Hairlines; mixed with `borderAlpha`. */
  border: string;
  text: string;
  textMuted: string;
  textSubtle: string;
  /** Accent (links, primary buttons, focus ring). */
  accent: string;
  accentHover: string;
  /** Text drawn on top of `accent`. */
  onAccent: string;
  focus: string;
  /** Modal / drawer backdrop. */
  scrim: string;
  /** Chart chrome. */
  chartGrid: string;
  chartAxis: string;
  /** Neutral "info" tone (toasts, Info severity). */
  info: string;
}

export const themes: Record<ThemeName, ThemeColors> = {
  dark: {
    canvas: '#060b0f',
    glowA: '#0b4a37',
    glowB: '#13304a',
    glass: '#ffffff',
    surface: '#121a21',
    surfaceRaised: '#19232c',
    surfaceSunken: '#0b1116',
    border: '#ffffff',
    text: '#e8eef2',
    textMuted: '#a3b1bd',
    textSubtle: '#76879a',
    accent: '#2bc98c',
    accentHover: '#5cdca8',
    onAccent: '#03291f',
    focus: '#5cdca8',
    scrim: '#000000',
    chartGrid: '#26303a',
    chartAxis: '#94a3b1',
    info: '#6aa8f0',
  },
  light: {
    canvas: '#e9f0ee',
    glowA: '#b5ecd5',
    glowB: '#cbdcf2',
    glass: '#ffffff',
    surface: '#ffffff',
    surfaceRaised: '#ffffff',
    surfaceSunken: '#f1f5f4',
    border: '#0f1a20',
    text: '#0f1a20',
    textMuted: '#45525e',
    textSubtle: '#66737f',
    accent: '#078e61',
    accentHover: '#08714f',
    onAccent: '#ffffff',
    focus: '#078e61',
    scrim: '#0f1a20',
    chartGrid: '#dce3e9',
    chartAxis: '#4f5d6b',
    info: '#1d5fbf',
  },
};

/** Health states as the API reports them (`app.core.enums.Health`). */
export type HealthState = 'OK' | 'Warning' | 'Critical' | 'Unknown';
export const healthStates: readonly HealthState[] = ['OK', 'Warning', 'Critical', 'Unknown'];

/**
 * Health is ALWAYS shown as word + color + icon (DESIGN rule). Colors are reserved: never reuse them for
 * chart series. `rank` orders worst-first sorting (same order as the backend's Health.worst()).
 */
export const health: Record<
  HealthState,
  {
    label: string;
    icon: 'circle-check' | 'triangle-alert' | 'octagon-x' | 'circle-help';
    rank: number;
    dark: string;
    light: string;
  }
> = {
  OK: { label: 'OK', icon: 'circle-check', rank: 0, dark: '#3dd68c', light: '#0b7a4b' },
  Unknown: { label: 'Unknown', icon: 'circle-help', rank: 1, dark: '#9aa9b6', light: '#5b6977' },
  Warning: { label: 'Warning', icon: 'triangle-alert', rank: 2, dark: '#f5b83d', light: '#9a5b00' },
  Critical: { label: 'Critical', icon: 'octagon-x', rank: 3, dark: '#ff6b78', light: '#c21f37' },
};

/** Glass recipe: tint alpha levels, border alpha, blur radii (px). */
export const glass = {
  alpha: {
    dark: { subtle: 0.035, base: 0.06, strong: 0.1 },
    light: { subtle: 0.45, base: 0.62, strong: 0.78 },
  },
  borderAlpha: { dark: 0.09, light: 0.1 },
  blur: { sm: 8, md: 16, lg: 28 },
  saturate: 1.4,
} as const;

export const radii = {
  none: '0',
  sm: '6px',
  md: '10px',
  lg: '14px',
  xl: '20px',
  '2xl': '28px',
  full: '9999px',
} as const;

export const shadows = {
  dark: {
    sm: '0 1px 2px rgb(0 0 0 / 0.35)',
    md: '0 8px 24px -8px rgb(0 0 0 / 0.55), inset 0 1px 0 rgb(255 255 255 / 0.05)',
    lg: '0 24px 60px -16px rgb(0 0 0 / 0.65), inset 0 1px 0 rgb(255 255 255 / 0.06)',
  },
  light: {
    sm: '0 1px 2px rgb(15 26 32 / 0.08)',
    md: '0 8px 24px -10px rgb(15 26 32 / 0.18), inset 0 1px 0 rgb(255 255 255 / 0.7)',
    lg: '0 24px 60px -20px rgb(15 26 32 / 0.28), inset 0 1px 0 rgb(255 255 255 / 0.8)',
  },
} as const;

/** 4 px spacing grid (Tailwind keys → rem). */
export const spacing = {
  px: '1px',
  0: '0',
  0.5: '0.125rem',
  1: '0.25rem',
  1.5: '0.375rem',
  2: '0.5rem',
  2.5: '0.625rem',
  3: '0.75rem',
  3.5: '0.875rem',
  4: '1rem',
  5: '1.25rem',
  6: '1.5rem',
  7: '1.75rem',
  8: '2rem',
  9: '2.25rem',
  10: '2.5rem',
  11: '2.75rem',
  12: '3rem',
  14: '3.5rem',
  16: '4rem',
  20: '5rem',
  24: '6rem',
  28: '7rem',
  32: '8rem',
  36: '9rem',
  40: '10rem',
  44: '11rem',
  48: '12rem',
  52: '13rem',
  56: '14rem',
  60: '15rem',
  64: '16rem',
  72: '18rem',
  80: '20rem',
  96: '24rem',
} as const;

export const fonts = {
  sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif'],
  mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Consolas', 'monospace'],
} as const;

/** Motion: durations in ms, easings as cubic-bezier control points (Framer Motion + CSS). */
export const motion = {
  duration: { instant: 80, fast: 140, base: 220, slow: 360, chart: 450 },
  easing: {
    standard: [0.2, 0, 0, 1],
    emphasized: [0.3, 0, 0, 1],
    exit: [0.4, 0, 1, 1],
  },
} as const;

export const zIndex = {
  sidebar: 30,
  topbar: 40,
  dropdown: 50,
  drawer: 60,
  modal: 70,
  toast: 80,
  tooltip: 90,
} as const;

/**
 * Categorical chart palette (identity), in fixed order — never cycled; a 9th series folds into "Other".
 * Validated reference palette (adjacent-pair CVD ΔE ≥ 8 in both modes). Health colors are NOT in here.
 */
export const chartPalette: Record<ThemeName, readonly string[]> = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
};

/** Breakpoints (laptop + tablet are the design targets; wall = NOC screen). */
export const breakpoints = {
  sm: '640px',
  md: '768px',
  lg: '1024px',
  xl: '1280px',
  '2xl': '1536px',
  wall: '1920px',
} as const;

export const tokens = {
  brand,
  neutral,
  themes,
  health,
  glass,
  radii,
  shadows,
  spacing,
  fonts,
  motion,
  zIndex,
  chartPalette,
  breakpoints,
} as const;
