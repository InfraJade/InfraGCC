import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { StatTile } from '@/components/StatTile';

describe('StatTile', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-22T10:00:00Z'));
  });
  afterEach(() => vi.useRealTimers());

  it('shows the value with its unit and its age', () => {
    render(<StatTile label="Total power" value={182450} unit="W" time="2026-10-22T09:59:30Z" />);
    expect(screen.getByText('Total power')).toBeInTheDocument();
    expect(screen.getByTestId('stat-value')).toHaveTextContent('182,450 W');
    expect(screen.getByText('30 s ago')).toBeInTheDocument();
  });

  it('says the age is unknown when no time is given', () => {
    render(<StatTile label="Servers" value={12} unit="servers" />);
    expect(screen.getByText('age unknown')).toBeInTheDocument();
  });

  it('renders a health badge, delta and footnote', () => {
    render(
      <StatTile
        label="Avg inlet"
        value={27.8}
        unit="°C"
        time="2026-10-22T09:59:00Z"
        health="Warning"
        delta={{ value: -1.5, unit: '°C', goodWhen: 'down', label: 'vs 24 h' }}
        footnote="12 racks"
      />,
    );
    expect(screen.getByTestId('stat-value')).toHaveTextContent('27.8 °C');
    expect(screen.getByText('Warning')).toBeInTheDocument();
    expect(screen.getByText('-1.5 °C').parentElement).toHaveClass('text-health-ok');
    expect(screen.getByText('12 racks')).toBeInTheDocument();
  });

  it('shows a skeleton while loading', () => {
    render(<StatTile label="Open alerts" value={null} loading />);
    expect(screen.queryByTestId('stat-value')).toBeNull();
    expect(screen.getByText('Loading Open alerts')).toBeInTheDocument();
  });

  it('becomes a link with an accessible name when `to` is set', () => {
    render(
      <MemoryRouter>
        <StatTile label="Open alerts" value={7} unit="alerts" to="/alerts" time="2026-10-22T10:00:00Z" />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: 'Open alerts: 7 alerts' })).toHaveAttribute('href', '/alerts');
  });
});
