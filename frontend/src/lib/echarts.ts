/**
 * Tree-shaken ECharts: only the pieces the app uses. Import ECharts through this module only
 * (tests mock it here).
 */
import { BarChart, LineChart } from 'echarts/charts';
import {
  AriaComponent,
  DatasetComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  MarkAreaComponent,
  DatasetComponent,
  AriaComponent,
  CanvasRenderer,
]);

export type ECharts = echarts.ECharts;
export type EChartsOption = echarts.EChartsCoreOption;

export function initChart(el: HTMLElement): ECharts {
  return echarts.init(el, undefined, { renderer: 'canvas' });
}
