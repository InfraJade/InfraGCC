import { act, render, screen } from '@testing-library/react';

import { Reading } from '@/components/Reading';
import { ageTickMs, formatAge, formatValue } from '@/lib/format';

const NOW = Date.parse('2026-10-22T10:00:00Z');

describe('formatAge', () => {
  it.each([
    [0, 'now'],
    [-5_000, 'now'], // clock skew: future readings read as "now"
    [1_000, '1 s ago'],
    [30_000, '30 s ago'],
    [59_999, '59 s ago'],
    [60_000, '1 min ago'],
    [5 * 60_000 + 10_000, '5 min ago'],
    [3 * 3600_000, '3 h ago'],
    [47 * 3600_000, '47 h ago'],
    [3 * 86_400_000, '3 d ago'],
  ])('%i ms old → %s', (ageMs, expected) => {
    expect(formatAge(NOW - ageMs, NOW)).toBe(expected);
  });

  it('handles ISO strings, Dates and invalid input', () => {
    expect(formatAge('2026-10-22T09:59:30Z', NOW)).toBe('30 s ago');
    expect(formatAge(new Date(NOW - 120_000), NOW)).toBe('2 min ago');
    expect(formatAge('not a date', NOW)).toBe('unknown age');
  });

  it('ticks fast for fresh values and slower for old ones', () => {
    expect(ageTickMs(NOW - 10_000, NOW)).toBe(1000);
    expect(ageTickMs(NOW - 10 * 60_000, NOW)).toBe(15_000);
    expect(ageTickMs(NOW - 2 * 3600_000, NOW)).toBe(60_000);
  });
});

describe('formatValue', () => {
  it('always shows the unit, with unit-aware precision', () => {
    expect(formatValue(41.24, '°C')).toBe('41.2 °C');
    expect(formatValue(2140.4, 'RPM')).toBe('2,140 RPM');
    expect(formatValue(612.7, 'W')).toBe('613 W');
    expect(formatValue(87, '%')).toBe('87 %');
    expect(formatValue(87.25, '%')).toBe('87.3 %');
    expect(formatValue(3, 'W', 2)).toBe('3.00 W');
  });
  it('renders missing values as a dash', () => {
    expect(formatValue(null, '°C')).toBe('—');
    expect(formatValue(Number.NaN, '°C')).toBe('—');
  });
});

describe('<Reading>', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => vi.useRealTimers());

  it('shows "41 °C, 30 s ago" and keeps ticking', () => {
    render(<Reading value={41} unit="°C" time={NOW - 30_000} precision={0} />);
    expect(screen.getByText('41 °C')).toBeInTheDocument();
    expect(screen.getByText('30 s ago')).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(15_000);
    });
    expect(screen.getByText('45 s ago')).toBeInTheDocument();
  });

  it('marks stale readings (older than 2 minutes) in words, not only color', () => {
    render(<Reading value={22} unit="°C" time={NOW - 5 * 60_000} />);
    const age = screen.getByText(/5 min ago/);
    expect(age.closest('time')).toHaveAttribute('data-stale', 'true');
    expect(screen.getByText('(stale)')).toBeInTheDocument();
  });

  it('says when the age is unknown', () => {
    render(<Reading value={10} unit="%" />);
    expect(screen.getByText('age unknown')).toBeInTheDocument();
  });

  it('labels missing values for screen readers', () => {
    render(<Reading value={null} unit="°C" time={NOW} />);
    expect(screen.getByLabelText('no reading')).toHaveTextContent('—');
  });
});
