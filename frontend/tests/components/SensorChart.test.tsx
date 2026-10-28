import { render, screen } from '@testing-library/react';

import { buildSensorOption, SensorChart, type SensorSeries } from '@/components/SensorChart';

const chart = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() };
const initChart = vi.fn((_el: HTMLElement) => chart);

vi.mock('@/lib/echarts', () => ({ initChart: (el: HTMLElement) => initChart(el) }));

const t0 = Date.parse('2026-10-22T10:00:00Z');
const inlet = (last: number): SensorSeries[] => [
  {
    id: 'inlet',
    name: 'Inlet',
    points: [
      [t0 - 60_000, 24.1],
      [t0, last],
    ],
  },
  {
    id: 'exhaust',
    name: 'Exhaust',
    points: [
      [t0 - 60_000, 37.0],
      [t0, 37.4],
    ],
  },
];

describe('SensorChart', () => {
  beforeEach(() => {
    chart.setOption.mockClear();
    chart.dispose.mockClear();
    initChart.mockClear();
  });

  it('initialises ECharts once and passes the option', () => {
    render(<SensorChart title="Temperatures" unit="°C" series={inlet(24.5)} />);
    expect(initChart).toHaveBeenCalledTimes(1);
    expect(chart.setOption).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('img', { name: /Temperatures in °C: Inlet, Exhaust/ })).toBeInTheDocument();
  });

  it('updates data in place without re-creating the chart', () => {
    const { rerender, unmount } = render(<SensorChart unit="°C" series={inlet(24.5)} />);
    rerender(<SensorChart unit="°C" series={inlet(25.9)} />);
    expect(initChart).toHaveBeenCalledTimes(1);
    expect(chart.setOption).toHaveBeenCalledTimes(2);
    const [option, opts] = chart.setOption.mock.lastCall as [
      { series: { id: string; data: unknown[] }[] },
      { replaceMerge: string[] },
    ];
    expect(option.series[0]?.id).toBe('inlet');
    expect(option.series[0]?.data.at(-1)).toEqual([t0, 25.9]);
    expect(opts.replaceMerge).toEqual(['series']);
    unmount();
    expect(chart.dispose).toHaveBeenCalledTimes(1);
  });

  it('does not call setOption again when re-rendered with the same props', () => {
    const series = inlet(24.5);
    const { rerender } = render(<SensorChart unit="°C" series={series} />);
    rerender(<SensorChart unit="°C" series={series} />);
    expect(chart.setOption).toHaveBeenCalledTimes(1);
  });

  it('shows latest values with unit (the legend) and an empty state without data', () => {
    const { rerender } = render(<SensorChart unit="°C" series={inlet(24.5)} />);
    const latest = screen.getByRole('list', { name: 'Latest values' });
    expect(latest).toHaveTextContent('Inlet');
    expect(latest).toHaveTextContent('24.5 °C');
    rerender(<SensorChart unit="°C" series={[{ id: 'p', name: 'Power', points: [] }]} />);
    expect(screen.getByText('No readings in this range')).toBeInTheDocument();
  });
});

describe('buildSensorOption', () => {
  const base = {
    series: inlet(24.5),
    unit: '°C',
    theme: 'dark' as const,
    reducedMotion: false,
    precision: undefined,
    yMin: undefined,
    yMax: undefined,
  };

  it('draws threshold mark lines in health colors with labels', () => {
    const option = buildSensorOption({
      ...base,
      thresholds: [
        { value: 27, severity: 'warning' },
        { value: 35, severity: 'critical', label: 'Inlet critical' },
      ],
    }) as { series: { markLine?: { data: { yAxis: number; label: { formatter: string } }[] } }[] };
    const lines = option.series[0]?.markLine?.data ?? [];
    expect(lines.map((l) => l.yAxis)).toEqual([27, 35]);
    expect(lines[0]?.label.formatter).toBe('Warning 27 °C');
    expect(lines[1]?.label.formatter).toBe('Inlet critical 35 °C');
    expect(option.series[1]?.markLine).toBeUndefined();
  });

  it('formats the y axis with the unit', () => {
    const option = buildSensorOption({ ...base, thresholds: [] }) as {
      yAxis: { axisLabel: { formatter: (v: number) => string } };
    };
    expect(option.yAxis.axisLabel.formatter(30)).toBe('30 °C');
    expect(buildSensorOption({ ...base, unit: 'RPM', thresholds: [] })).toBeTruthy();
  });

  it('turns animation off for reduced motion and switches colors by theme', () => {
    const dark = buildSensorOption({ ...base, thresholds: [] }) as {
      animation: boolean;
      series: { lineStyle: { color: string } }[];
    };
    const light = buildSensorOption({
      ...base,
      theme: 'light',
      reducedMotion: true,
      thresholds: [],
    }) as typeof dark;
    expect(dark.animation).toBe(true);
    expect(light.animation).toBe(false);
    expect(dark.series[0]?.lineStyle.color).not.toBe(light.series[0]?.lineStyle.color);
  });
});
