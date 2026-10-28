import { useEffect, useRef, type CSSProperties } from 'react';

import { initChart, type ECharts, type EChartsOption } from '@/lib/echarts';

export interface EChartProps {
  option: EChartsOption;
  /** Accessible name for the chart image. */
  ariaLabel: string;
  className?: string;
  style?: CSSProperties;
  /**
   * Components replaced (not merged) on update. Default ['series']: series are matched by `id`, so
   * existing lines animate to their new data while removed series disappear.
   */
  replaceMerge?: string[];
  onReady?: (chart: ECharts) => void;
}

/**
 * Thin ECharts binding: one instance per mount, `setOption` on every option change (no remount, so
 * ECharts animates the update), ResizeObserver-driven resize, dispose on unmount.
 */
const DEFAULT_REPLACE = ['series'];

export function EChart({
  option,
  ariaLabel,
  className,
  style,
  replaceMerge = DEFAULT_REPLACE,
  onReady,
}: EChartProps) {
  const elRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ECharts | null>(null);
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  useEffect(() => {
    const el = elRef.current;
    if (!el) return;
    const chart = initChart(el);
    chartRef.current = chart;
    onReadyRef.current?.(chart);
    let frame = 0;
    const ro =
      typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(() => {
            cancelAnimationFrame(frame);
            frame = requestAnimationFrame(() => chart.resize());
          })
        : null;
    ro?.observe(el);
    return () => {
      cancelAnimationFrame(frame);
      ro?.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, { replaceMerge, lazyUpdate: true });
  }, [option, replaceMerge]);

  return <div ref={elRef} role="img" aria-label={ariaLabel} className={className} style={style} />;
}
