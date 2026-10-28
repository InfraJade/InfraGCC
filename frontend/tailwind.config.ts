import type { Config } from 'tailwindcss';
import plugin from 'tailwindcss/plugin';

import { baseThemeRules, kebab, themeColorKeys } from './src/theme/cssVars';
import {
  breakpoints,
  brand,
  fonts,
  healthStates,
  motion,
  neutral,
  radii,
  spacing,
  zIndex,
} from './src/theme/tokens';

const channel = (name: string) => `rgb(var(${name}) / <alpha-value>)`;

const semantic = Object.fromEntries(themeColorKeys.map((k) => [kebab(k), channel(`--c-${kebab(k)}`)]));
const healthColors = Object.fromEntries(
  healthStates.map((s) => [s.toLowerCase(), channel(`--c-health-${s.toLowerCase()}`)]),
);

const ms = (n: number) => `${n}ms`;
const bezier = (v: readonly number[]) => `cubic-bezier(${v.join(',')})`;

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    screens: breakpoints,
    spacing,
    borderRadius: { ...radii, DEFAULT: radii.md },
    fontFamily: { sans: [...fonts.sans], mono: [...fonts.mono] },
    zIndex: Object.fromEntries(Object.entries(zIndex).map(([k, v]) => [k, String(v)])),
    extend: {
      colors: {
        brand,
        neutral,
        ...semantic,
        health: healthColors,
      },
      boxShadow: {
        sm: 'var(--shadow-sm)',
        DEFAULT: 'var(--shadow-md)',
        md: 'var(--shadow-md)',
        lg: 'var(--shadow-lg)',
      },
      backdropBlur: { sm: 'var(--glass-blur-sm)', md: 'var(--glass-blur-md)', lg: 'var(--glass-blur-lg)' },
      transitionDuration: Object.fromEntries(Object.entries(motion.duration).map(([k, v]) => [k, ms(v)])),
      transitionTimingFunction: Object.fromEntries(
        Object.entries(motion.easing).map(([k, v]) => [k, bezier(v)]),
      ),
      keyframes: {
        shimmer: { '0%': { backgroundPosition: '-200% 0' }, '100%': { backgroundPosition: '200% 0' } },
        'pulse-ring': {
          '0%': { transform: 'scale(0.9)', opacity: '0.7' },
          '100%': { transform: 'scale(1.8)', opacity: '0' },
        },
        // Login visuals.
        led: { '0%, 100%': { opacity: '1' }, '45%': { opacity: '0.25' }, '55%': { opacity: '0.9' } },
        ecg: { '0%': { strokeDashoffset: '1000' }, '100%': { strokeDashoffset: '0' } },
        wave: { '0%': { transform: 'translateX(0)' }, '100%': { transform: 'translateX(-50%)' } },
        'spin-slow': { to: { transform: 'rotate(360deg)' } },
        sheen: {
          '0%': { transform: 'translateX(-120%) skewX(-20deg)' },
          '60%, 100%': { transform: 'translateX(220%) skewX(-20deg)' },
        },
        aurora: {
          '0%, 100%': { transform: 'translate3d(0,0,0) scale(1)' },
          '50%': { transform: 'translate3d(4%, -3%, 0) scale(1.08)' },
        },
      },
      animation: {
        shimmer: 'shimmer 1.6s linear infinite',
        'pulse-ring': 'pulse-ring 1.6s var(--ease-standard) infinite',
        led: 'led 2.4s ease-in-out infinite',
        ecg: 'ecg 3.2s linear infinite',
        wave: 'wave 4s linear infinite',
        'spin-slow': 'spin-slow 40s linear infinite',
        sheen: 'sheen 3.6s ease-in-out infinite',
        aurora: 'aurora 18s ease-in-out infinite',
      },
    },
  },
  plugins: [
    plugin((api) => {
      api.addBase(baseThemeRules());
      api.addComponents({
        // Glass surfaces. Tint, alpha and blur come from CSS variables, so reduced transparency turns
        // every glass surface solid in one place.
        '.glass': {
          backgroundColor: 'rgb(var(--glass-tint) / var(--glass-alpha-base))',
          backdropFilter: 'blur(var(--glass-blur-md)) saturate(var(--glass-saturate))',
          border: '1px solid rgb(var(--c-border) / var(--glass-border-alpha))',
          boxShadow: 'var(--shadow-md)',
        },
        '.glass-subtle': {
          backgroundColor: 'rgb(var(--glass-tint) / var(--glass-alpha-subtle))',
          backdropFilter: 'blur(var(--glass-blur-sm)) saturate(var(--glass-saturate))',
          border: '1px solid rgb(var(--c-border) / var(--glass-border-alpha))',
        },
        '.glass-strong': {
          backgroundColor: 'rgb(var(--glass-tint) / var(--glass-alpha-strong))',
          backdropFilter: 'blur(var(--glass-blur-lg)) saturate(var(--glass-saturate))',
          border: '1px solid rgb(var(--c-border) / var(--glass-border-alpha))',
          boxShadow: 'var(--shadow-lg)',
        },
        '.hairline': { borderColor: 'rgb(var(--c-border) / var(--glass-border-alpha))' },
      });
    }),
  ],
} satisfies Config;
