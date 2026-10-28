/**
 * Turns `tokens.ts` into CSS custom properties. Used by the Tailwind plugin in `tailwind.config.ts`
 * (which writes them into the generated stylesheet) — nothing here touches the DOM.
 *
 * Colors are emitted as space-separated RGB channels (`--c-text: 232 238 242`) so Tailwind's
 * `<alpha-value>` modifiers keep working: `bg-surface/80`, `text-health-critical`, …
 */
import {
  glass,
  health,
  healthStates,
  motion,
  shadows,
  themes,
  type HealthState,
  type ThemeColors,
  type ThemeName,
} from './tokens';

export function hexToChannels(hex: string): string {
  const h = hex.replace('#', '');
  const full =
    h.length === 3
      ? h
          .split('')
          .map((c) => c + c)
          .join('')
      : h;
  const n = Number.parseInt(full, 16);
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`;
}

export function kebab(s: string): string {
  return s.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`);
}

export const themeColorKeys = Object.keys(themes.dark) as (keyof ThemeColors)[];

export function healthVar(state: HealthState): string {
  return `--c-health-${state.toLowerCase()}`;
}

/** Variables that differ per theme. */
export function themeVariables(name: ThemeName): Record<string, string> {
  const vars: Record<string, string> = { 'color-scheme': name };
  const colors = themes[name];
  for (const key of themeColorKeys) vars[`--c-${kebab(key)}`] = hexToChannels(colors[key]);
  for (const state of healthStates) vars[healthVar(state)] = hexToChannels(health[state][name]);
  vars['--glass-tint'] = 'var(--c-glass)';
  vars['--glass-alpha-subtle'] = String(glass.alpha[name].subtle);
  vars['--glass-alpha-base'] = String(glass.alpha[name].base);
  vars['--glass-alpha-strong'] = String(glass.alpha[name].strong);
  vars['--glass-border-alpha'] = String(glass.borderAlpha[name]);
  vars['--glass-blur-sm'] = `${glass.blur.sm}px`;
  vars['--glass-blur-md'] = `${glass.blur.md}px`;
  vars['--glass-blur-lg'] = `${glass.blur.lg}px`;
  vars['--shadow-sm'] = shadows[name].sm;
  vars['--shadow-md'] = shadows[name].md;
  vars['--shadow-lg'] = shadows[name].lg;
  return vars;
}

/** Variables shared by both themes. */
export function staticVariables(): Record<string, string> {
  const vars: Record<string, string> = { '--glass-saturate': String(glass.saturate) };
  for (const [k, v] of Object.entries(motion.duration)) vars[`--dur-${k}`] = `${v}ms`;
  for (const [k, v] of Object.entries(motion.easing)) vars[`--ease-${k}`] = `cubic-bezier(${v.join(',')})`;
  return vars;
}

/** Solid-surface fallback for `prefers-reduced-transparency` and the manual setting. */
export function reducedTransparencyVariables(): Record<string, string> {
  return {
    '--glass-tint': 'var(--c-surface)',
    '--glass-alpha-subtle': '1',
    '--glass-alpha-base': '1',
    '--glass-alpha-strong': '1',
    '--glass-blur-sm': '0px',
    '--glass-blur-md': '0px',
    '--glass-blur-lg': '0px',
  };
}

/** The full CSS-in-JS rule set that the Tailwind plugin injects with `addBase`. */
export function baseThemeRules(): Record<string, Record<string, string | Record<string, string>>> {
  const reduced = reducedTransparencyVariables();
  // `[data-theme]` scopes can be nested (the component gallery renders both themes on one page),
  // so the transparency override also targets nested scopes to win over their glass alphas.
  return {
    ':root, [data-theme="dark"]': { ...staticVariables(), ...themeVariables('dark') },
    '[data-theme="light"]': themeVariables('light'),
    '[data-transparency="reduced"], [data-transparency="reduced"] [data-theme]': reduced,
    '@media (prefers-reduced-transparency: reduce)': { ':root, :root [data-theme]': reduced },
  };
}
