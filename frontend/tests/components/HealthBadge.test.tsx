import { render, screen } from '@testing-library/react';

import { HealthBadge } from '@/components/HealthBadge';
import { normalizeHealth, worstHealth } from '@/lib/health';

describe('HealthBadge', () => {
  it.each([
    ['OK', 'OK', 'text-health-ok'],
    ['Warning', 'Warning', 'text-health-warning'],
    ['Critical', 'Critical', 'text-health-critical'],
    ['Unknown', 'Unknown', 'text-health-unknown'],
  ])('shows %s as a word, a color and an icon', (input, word, colorClass) => {
    const { container } = render(<HealthBadge health={input} />);
    const badge = container.querySelector('[data-health]');
    expect(badge).toHaveAttribute('data-health', word);
    expect(badge).toHaveClass(colorClass);
    expect(screen.getByText(word)).toBeInTheDocument();
    expect(badge?.querySelector('svg')).not.toBeNull();
  });

  it('falls back to Unknown for missing or unexpected values', () => {
    render(<HealthBadge health={null} />);
    expect(screen.getByText('Unknown')).toBeInTheDocument();
  });

  it('accepts lowercase API values and adds screen-reader context', () => {
    render(<HealthBadge health="critical" context="PSU 1" />);
    expect(screen.getByText('Critical')).toBeInTheDocument();
    expect(screen.getByText(/PSU 1/)).toHaveClass('sr-only');
  });

  it('keeps the word in the plain variant (never color alone)', () => {
    render(<HealthBadge health="Warning" variant="plain" />);
    expect(screen.getByText('Warning')).toBeInTheDocument();
  });
});

describe('health helpers', () => {
  it('normalizes', () => {
    expect(normalizeHealth('ok')).toBe('OK');
    expect(normalizeHealth('Degraded')).toBe('Warning');
    expect(normalizeHealth(undefined)).toBe('Unknown');
  });

  it('picks the worst state like the backend (Critical > Warning > Unknown > OK)', () => {
    expect(worstHealth(['OK', 'Warning', 'OK'])).toBe('Warning');
    expect(worstHealth(['OK', 'Unknown'])).toBe('Unknown');
    expect(worstHealth(['Critical', 'Warning'])).toBe('Critical');
    expect(worstHealth([])).toBe('Unknown');
  });
});
