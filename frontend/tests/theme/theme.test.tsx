import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { baseThemeRules, hexToChannels, themeVariables } from '@/theme/cssVars';
import { prefsKey, readPrefs, ThemeProvider, useTheme } from '@/theme/ThemeProvider';

function Probe() {
  const { theme, toggleTheme, reduceTransparency, setReduceTransparency } = useTheme();
  return (
    <>
      <span data-testid="theme">{theme}</span>
      <button type="button" onClick={toggleTheme}>
        toggle
      </button>
      <button type="button" onClick={() => setReduceTransparency(!reduceTransparency)}>
        transparency
      </button>
    </>
  );
}

describe('ThemeProvider', () => {
  it('defaults to dark and persists the toggle per user', async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider userKey="u1">
        <Probe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId('theme')).toHaveTextContent('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
    await user.click(screen.getByText('toggle'));
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(readPrefs('u1').theme).toBe('light');
    expect(readPrefs('u2').theme).toBe('dark');

    await user.click(screen.getByText('transparency'));
    expect(document.documentElement.dataset.transparency).toBe('reduced');
  });

  it('survives broken or unavailable storage', () => {
    window.localStorage.setItem(prefsKey('u3'), '{not json');
    expect(readPrefs('u3')).toEqual({ theme: 'dark', reduceTransparency: false });
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    expect(readPrefs('u3').theme).toBe('dark');
    spy.mockRestore();
  });
});

describe('token → CSS variables', () => {
  it('emits RGB channels for both themes and a solid fallback for reduced transparency', () => {
    expect(hexToChannels('#0faf76')).toBe('15 175 118');
    expect(themeVariables('dark')['--c-health-critical']).toBeDefined();
    expect(themeVariables('light')['color-scheme']).toBe('light');
    const rules = baseThemeRules();
    expect(
      rules['[data-transparency="reduced"], [data-transparency="reduced"] [data-theme]']?.[
        '--glass-alpha-base'
      ],
    ).toBe('1');
    expect(rules['@media (prefers-reduced-transparency: reduce)']).toBeDefined();
  });
});
